import socket
import struct
import time
import curses
import subprocess
import sys
import threading

DRONE_IP       = '192.168.43.42'
DRONE_PORT     = 2390
LOCAL_PORT     = 2399
DRONE_SSID     = 'ESP-DRONE_90E5B199B123'
DRONE_PASSWORD = '12345678'
IFACE          = 'wlan1'

# ──────────────────────────────────────────
# Wi-Fi
# ──────────────────────────────────────────

def connetti_wifi():
    print(f"[*] Connessione a '{DRONE_SSID}' su {IFACE}...")
    subprocess.run(['sudo', 'ip', 'link', 'set', IFACE, 'up'], check=True)
    subprocess.run(['sudo', 'nmcli', 'device', 'disconnect', IFACE], capture_output=True)

    result = subprocess.run(
        ['sudo', 'nmcli', 'device', 'wifi', 'connect', DRONE_SSID,
         'password', DRONE_PASSWORD, 'ifname', IFACE],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[!] Errore connessione Wi-Fi:\n{result.stderr}")
        sys.exit(1)

    print(f"[+] Connesso a '{DRONE_SSID}' su {IFACE}")
    print("[*] Attendo assegnazione IP...")
    time.sleep(2)

    ip_result = subprocess.run(['ip', 'addr', 'show', IFACE], capture_output=True, text=True)
    print(ip_result.stdout)

# ──────────────────────────────────────────
# Socket UDP condiviso
# ──────────────────────────────────────────

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', LOCAL_PORT))
sock.settimeout(0.05)

sock_lock = threading.Lock()

# ──────────────────────────────────────────
# Invio comandi CRTP (commander)
# ──────────────────────────────────────────

def invia(roll, pitch, yaw, thrust):
    header = (0x03 << 4) | 0
    data   = struct.pack('<fffH', roll, -pitch, yaw, thrust)
    pkt    = bytes([header]) + data
    cksum  = sum(pkt) & 0xff
    with sock_lock:
        sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

# ──────────────────────────────────────────
# Lettura batteria via CRTP LOG raw
#
# Sequenza:
#   1. GET_INFO  (port=5, channel=0, cmd=1) → numero variabili nella TOC
#   2. GET_ITEM  (port=5, channel=0, cmd=2, id) × N → trova pm.vbat e pm.batteryLevel
#   3. CREATE_BLOCK (port=5, channel=1, cmd=0) → crea log block con le due variabili
#   4. START (port=5, channel=1, cmd=3) → abilita il log ogni 500ms
#   5. Loop: riceve pacchetti CRTP port=5 channel=2 con i dati
# ──────────────────────────────────────────

batt_lock = threading.Lock()
batt_data = {
    'vbat':  None,
    'level': None,
    'error': None,
    'ready': False,
}

LOG_PORT = 5

def crtp_send(port, channel, data: bytes) -> None:
    header = (port << 4) | channel
    pkt    = bytes([header]) + data
    cksum  = sum(pkt) & 0xff
    with sock_lock:
        sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

def crtp_recv(timeout=1.0):
    """Riceve un pacchetto CRTP grezzo. Ritorna (port, channel, payload) o None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with sock_lock:
                data, _ = sock.recvfrom(64)
        except socket.timeout:
            continue
        except Exception:
            continue
        if len(data) < 1:
            continue
        hdr  = data[0]
        port = (hdr >> 4) & 0x0F
        chan = hdr & 0x03
        return port, chan, data[1:]
    return None

def crtp_recv_expect(port, channel, timeout=1.0):
    """Riceve finché non arriva un pacchetto con port e channel attesi."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pkt = crtp_recv(timeout=0.1)
        if pkt and pkt[0] == port and pkt[1] == channel:
            return pkt[2]
    return None

def battery_thread():
    time.sleep(1.5)  # aspetta che il socket sia pronto e il Wi-Fi stabile

    try:
        # ── 1. GET_INFO: quante variabili ha la TOC? ──
        crtp_send(LOG_PORT, 0, bytes([1]))  # cmd=1 GET_INFO
        resp = crtp_recv_expect(LOG_PORT, 0, timeout=3.0)
        if resp is None or len(resp) < 3:
            _set_batt_error("GET_INFO senza risposta — drone non raggiungibile o firmware incompatibile")
            return
        # risposta: cmd(1) + num_variables(2) + crc(4) + max_packet(1) + max_ops(1)
        num_vars = struct.unpack_from('<H', resp, 1)[0] if len(resp) >= 3 else 0
        if num_vars == 0:
            _set_batt_error("TOC vuota — firmware non supporta logging")
            return

        # ── 2. Scansione TOC: cerca pm.vbat e pm.batteryLevel ──
        vbat_id   = None
        vbat_type = None
        lvl_id    = None
        lvl_type  = None

        TYPE_MAP = {
            1: 'uint8_t',  2: 'uint16_t', 3: 'uint32_t',
            4: 'int8_t',   5: 'int16_t',  6: 'int32_t',
            7: 'float',    8: 'fp16',
        }

        for var_id in range(num_vars):
            crtp_send(LOG_PORT, 0, bytes([2, var_id & 0xFF, (var_id >> 8) & 0xFF]))  # cmd=2 GET_ITEM
            resp = crtp_recv_expect(LOG_PORT, 0, timeout=1.0)
            if resp is None or len(resp) < 4:
                continue
            # risposta: cmd(1) + id(2) + type(1) + group\0name\0
            var_type_byte = resp[3]
            name_bytes    = resp[4:]
            try:
                full_name = name_bytes.decode('ascii', errors='replace').replace('\x00', '.').strip('.')
            except Exception:
                continue

            if 'pm.vbat' in full_name and vbat_id is None:
                vbat_id   = var_id
                vbat_type = var_type_byte
            if 'pm.batteryLevel' in full_name and lvl_id is None:
                lvl_id    = var_id
                lvl_type  = var_type_byte

            if vbat_id is not None and lvl_id is not None:
                break

        if vbat_id is None:
            _set_batt_error("pm.vbat non trovata nella TOC — firmware non la espone")
            return

        # ── 3. CREATE_BLOCK id=1 ──
        BLOCK_ID = 1
        PERIOD   = 10  # unità da 10ms → 100ms
        block_payload = bytes([0, BLOCK_ID])  # cmd=0 CREATE_BLOCK, block_id
        # aggiungi variabili: type(1) + id_low(1) + id_high(1)
        block_payload += bytes([vbat_type, vbat_id & 0xFF, (vbat_id >> 8) & 0xFF])
        if lvl_id is not None:
            block_payload += bytes([lvl_type, lvl_id & 0xFF, (lvl_id >> 8) & 0xFF])

        crtp_send(LOG_PORT, 1, block_payload)
        resp = crtp_recv_expect(LOG_PORT, 1, timeout=2.0)
        if resp is None:
            _set_batt_error("CREATE_BLOCK senza risposta")
            return
        err_code = resp[2] if len(resp) >= 3 else 0xFF
        if err_code != 0:
            _set_batt_error(f"CREATE_BLOCK errore {err_code:#04x} — forse block già esiste, riprovo con delete")
            # tenta di eliminare il block e ricreare
            crtp_send(LOG_PORT, 1, bytes([2, BLOCK_ID]))  # cmd=2 DELETE_BLOCK
            time.sleep(0.2)
            crtp_send(LOG_PORT, 1, block_payload)
            resp = crtp_recv_expect(LOG_PORT, 1, timeout=2.0)
            if resp is None or (len(resp) >= 3 and resp[2] != 0):
                _set_batt_error(f"CREATE_BLOCK fallito anche dopo delete")
                return

        # ── 4. START_LOGGING ──
        crtp_send(LOG_PORT, 1, bytes([3, BLOCK_ID, PERIOD]))  # cmd=3 START
        resp = crtp_recv_expect(LOG_PORT, 1, timeout=2.0)
        if resp is None:
            _set_batt_error("START_LOGGING senza risposta")
            return

        # ── 5. Loop ricezione dati ──
        # pacchetti dati arrivano su port=5, channel=2
        # formato: block_id(1) + timestamp_low(3) + data...
        while True:
            pkt = crtp_recv(timeout=0.5)
            if pkt is None:
                continue
            port, chan, payload = pkt
            if port != LOG_PORT or chan != 2:
                continue
            if len(payload) < 4:
                continue

            # salta block_id(1) + timestamp(3)
            offset = 4
            vbat_val  = None
            level_val = None

            # float = 4 byte
            if offset + 4 <= len(payload):
                vbat_val = struct.unpack_from('<f', payload, offset)[0]
                offset  += 4

            if lvl_id is not None and offset + 1 <= len(payload):
                level_val = payload[offset]

            with batt_lock:
                batt_data['vbat']  = round(vbat_val, 2) if vbat_val is not None else None
                batt_data['level'] = level_val
                batt_data['error'] = None
                batt_data['ready'] = True

    except Exception as e:
        _set_batt_error(f"eccezione: {e}")

def _set_batt_error(msg):
    with batt_lock:
        batt_data['error'] = msg
        batt_data['ready'] = False

def get_batt_str():
    with batt_lock:
        if batt_data['error']:
            return f"Batteria: ERRORE — {batt_data['error']}"
        if not batt_data['ready']:
            return "Batteria: in attesa..."
        v = batt_data['vbat']
        l = batt_data['level']
        if l is not None:
            return f"Batteria: {v:.2f}V  {l}%"
        return f"Batteria: {v:.2f}V"

# ──────────────────────────────────────────
# Controller curses
# ──────────────────────────────────────────

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(20)

    roll   = 0.0
    pitch  = 0.0
    yaw    = 0.0
    thrust = 0

    STEP_ANGLE  = 5.0
    STEP_THRUST = 2000
    MAX_THRUST  = 60000
    MIN_THRUST  = 0

    stdscr.addstr(0, 0, "=== Controller Drone ESP32 ===")
    stdscr.addstr(1, 0, f"Connesso a {DRONE_SSID} via {IFACE}")
    stdscr.addstr(2, 0, "")
    stdscr.addstr(3, 0, "W/S    -> Pitch avanti/indietro")
    stdscr.addstr(4, 0, "A/D    -> Roll sinistra/destra")
    stdscr.addstr(5, 0, "Q/E    -> Yaw sinistra/destra")
    stdscr.addstr(6, 0, "UP/DN  -> Thrust su/giu")
    stdscr.addstr(7, 0, "SPACE  -> STOP MOTORI")
    stdscr.addstr(8, 0, "X      -> EXIT")
    stdscr.addstr(9, 0, "─" * 36)

    try:
        while True:
            key = stdscr.getch()

            if key == ord('w'):
                pitch += STEP_ANGLE
            elif key == ord('s'):
                pitch -= STEP_ANGLE

            if key == ord('a'):
                roll -= STEP_ANGLE
            elif key == ord('d'):
                roll += STEP_ANGLE

            if key == ord('q'):
                yaw -= STEP_ANGLE
            elif key == ord('e'):
                yaw += STEP_ANGLE

            if key == curses.KEY_UP:
                thrust = min(thrust + STEP_THRUST, MAX_THRUST)
            elif key == curses.KEY_DOWN:
                thrust = max(thrust - STEP_THRUST, MIN_THRUST)

            if key == ord(' '):
                thrust = 0
                roll   = 0.0
                pitch  = 0.0
                yaw    = 0.0

            if key == ord('x'):
                break

            invia(roll, pitch, yaw, thrust)

            stdscr.addstr(11, 0, f"Roll:   {roll:6.1f} deg   ")
            stdscr.addstr(12, 0, f"Pitch:  {pitch:6.1f} deg   ")
            stdscr.addstr(13, 0, f"Yaw:    {yaw:6.1f} deg   ")
            stdscr.addstr(14, 0, f"Thrust: {thrust:6d} / {MAX_THRUST}   ")
            stdscr.addstr(15, 0, get_batt_str()[:70].ljust(70))

            stdscr.refresh()
            time.sleep(0.02)

    finally:
        invia(0.0, 0.0, 0.0, 0)
        sock.close()

# ──────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────

if __name__ == '__main__':
    connetti_wifi()

    t = threading.Thread(target=battery_thread, daemon=True)
    t.start()

    curses.wrapper(main)
    print("Controller chiuso.")