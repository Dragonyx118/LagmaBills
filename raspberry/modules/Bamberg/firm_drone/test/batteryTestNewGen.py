import socket
import struct
import time
import curses
import subprocess
import sys
import threading

DRONE_IP        = '192.168.43.42'
DRONE_PORT      = 2390
LOCAL_PORT      = 2399   # socket comandi
LOCAL_PORT_BATT = 2398   # socket batteria (separato!)
DRONE_SSID      = 'ESP-DRONE_90E5B199B123'
DRONE_PASSWORD  = '12345678'
IFACE           = 'wlan1'

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
# Due socket separati — NESSUN lock condiviso
# sock_cmd  → solo sendto, mai recvfrom
# sock_batt → solo usato nel thread batteria
# ──────────────────────────────────────────

sock_cmd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_cmd.bind(('', LOCAL_PORT))

sock_batt = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_batt.bind(('', LOCAL_PORT_BATT))
sock_batt.settimeout(0.5)

# ──────────────────────────────────────────
# Invio comandi — usa sock_cmd, mai bloccante
# ──────────────────────────────────────────

def invia(roll, pitch, yaw, thrust):
    header = (0x03 << 4) | 0
    data   = struct.pack('<fffH', roll, -pitch, yaw, thrust)
    pkt    = bytes([header]) + data
    cksum  = sum(pkt) & 0xff
    sock_cmd.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

# ──────────────────────────────────────────
# CRTP helpers — usano SOLO sock_batt
# ──────────────────────────────────────────

LOG_PORT = 5

def _crtp_send(port, channel, data: bytes):
    header = (port << 4) | channel
    pkt    = bytes([header]) + data
    cksum  = sum(pkt) & 0xff
    sock_batt.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

def _crtp_recv(timeout=1.0):
    """Riceve un pacchetto CRTP. Ritorna (port, channel, payload) o None."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            raw, _ = sock_batt.recvfrom(64)
        except socket.timeout:
            continue
        if len(raw) < 1:
            continue
        hdr  = raw[0]
        port = (hdr >> 4) & 0x0F
        chan = hdr & 0x03
        return port, chan, raw[1:]
    return None

def _crtp_recv_expect(port, channel, timeout=2.0):
    """Riceve finché arriva un pacchetto con (port, channel) attesi."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pkt = _crtp_recv(timeout=0.2)
        if pkt and pkt[0] == port and pkt[1] == channel:
            return pkt[2]
    return None

# ──────────────────────────────────────────
# Stato batteria condiviso
# ──────────────────────────────────────────

batt_lock = threading.Lock()
batt_data = {'vbat': None, 'level': None, 'error': None, 'ready': False}

def _set_batt_error(msg):
    with batt_lock:
        batt_data['error'] = msg
        batt_data['ready'] = False

def get_batt_str():
    with batt_lock:
        if batt_data['error']:
            return f"Batt: ERRORE — {batt_data['error']}"
        if not batt_data['ready']:
            return "Batt: in attesa..."
        v = batt_data['vbat']
        l = batt_data['level']
        if l is not None:
            return f"Batt: {v:.2f}V  {l}%"
        return f"Batt: {v:.2f}V"

# ──────────────────────────────────────────
# Thread batteria — CRTP LOG raw
# ──────────────────────────────────────────

# Mappa type_id → (formato struct, dimensione byte)
_TYPE_FMT = {
    1: ('<B', 1),   # uint8_t
    2: ('<H', 2),   # uint16_t
    3: ('<I', 4),   # uint32_t
    4: ('<b', 1),   # int8_t
    5: ('<h', 2),   # int16_t
    6: ('<i', 4),   # int32_t
    7: ('<f', 4),   # float
    8: ('<e', 2),   # fp16
}

def battery_thread():
    time.sleep(2.0)  # aspetta Wi-Fi stabile

    try:
        # 1. GET_INFO
        _crtp_send(LOG_PORT, 0, bytes([1]))
        resp = _crtp_recv_expect(LOG_PORT, 0, timeout=4.0)
        if resp is None or len(resp) < 3:
            _set_batt_error("GET_INFO: nessuna risposta dal drone")
            return
        num_vars = struct.unpack_from('<H', resp, 1)[0]
        if num_vars == 0:
            _set_batt_error("TOC vuota — firmware non supporta logging")
            return

        # 2. Scan TOC
        vbat_id = vbat_type = lvl_id = lvl_type = None

        for var_id in range(num_vars):
            _crtp_send(LOG_PORT, 0, bytes([2, var_id & 0xFF, (var_id >> 8) & 0xFF]))
            resp = _crtp_recv_expect(LOG_PORT, 0, timeout=1.0)
            if resp is None or len(resp) < 5:
                continue
            type_byte = resp[3]
            name_raw  = resp[4:]
            try:
                parts     = name_raw.split(b'\x00')
                full_name = '.'.join(p.decode('ascii', errors='replace') for p in parts if p)
            except Exception:
                continue

            if vbat_id is None and 'pm.vbat' in full_name:
                vbat_id, vbat_type = var_id, type_byte
            if lvl_id is None and 'pm.batteryLevel' in full_name:
                lvl_id, lvl_type = var_id, type_byte

            if vbat_id is not None and lvl_id is not None:
                break

        if vbat_id is None:
            _set_batt_error("pm.vbat non trovata nella TOC")
            return

        # 3. CREATE_BLOCK
        BLOCK_ID = 1
        PERIOD   = 50   # × 10ms = 500ms
        payload  = bytes([0, BLOCK_ID])
        payload += bytes([vbat_type, vbat_id & 0xFF, (vbat_id >> 8) & 0xFF])
        if lvl_id is not None:
            payload += bytes([lvl_type, lvl_id & 0xFF, (lvl_id >> 8) & 0xFF])

        _crtp_send(LOG_PORT, 1, payload)
        resp = _crtp_recv_expect(LOG_PORT, 1, timeout=2.0)
        if resp is None:
            _set_batt_error("CREATE_BLOCK: nessuna risposta")
            return
        err_code = resp[2] if len(resp) >= 3 else 0xFF
        if err_code != 0:
            # block già esiste → delete e riprova
            _crtp_send(LOG_PORT, 1, bytes([2, BLOCK_ID]))
            time.sleep(0.3)
            _crtp_send(LOG_PORT, 1, payload)
            resp = _crtp_recv_expect(LOG_PORT, 1, timeout=2.0)
            if resp is None or (len(resp) >= 3 and resp[2] != 0):
                _set_batt_error("CREATE_BLOCK: fallito anche dopo delete")
                return

        # 4. START
        _crtp_send(LOG_PORT, 1, bytes([3, BLOCK_ID, PERIOD]))
        _crtp_recv_expect(LOG_PORT, 1, timeout=2.0)  # ack facoltativo

        # 5. Loop ricezione — pacchetti su port=5, chan=2
        # formato: block_id(1) + timestamp(3) + dati...
        while True:
            pkt = _crtp_recv(timeout=1.0)
            if pkt is None:
                continue
            port, chan, data = pkt
            if port != LOG_PORT or chan != 2:
                continue
            if len(data) < 4:
                continue

            offset   = 4  # salta block_id + timestamp
            vbat_val = None
            lvl_val  = None

            # vbat
            fmt, sz = _TYPE_FMT.get(vbat_type, ('<f', 4))
            if offset + sz <= len(data):
                vbat_val = struct.unpack_from(fmt, data, offset)[0]
                offset  += sz

            # level
            if lvl_id is not None:
                fmt, sz = _TYPE_FMT.get(lvl_type, ('<B', 1))
                if offset + sz <= len(data):
                    raw = struct.unpack_from(fmt, data, offset)[0]
                    # se float 0.0–1.0 → scala a %
                    if lvl_type == 7 and isinstance(raw, float):
                        lvl_val = int(raw * 100) if raw <= 1.0 else int(raw)
                    else:
                        lvl_val = int(raw)
                    lvl_val = max(0, min(100, lvl_val))

            with batt_lock:
                batt_data['vbat']  = round(float(vbat_val), 2) if vbat_val is not None else None
                batt_data['level'] = lvl_val
                batt_data['error'] = None
                batt_data['ready'] = True

    except Exception as e:
        _set_batt_error(f"eccezione: {e}")

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

    stdscr.addstr(0, 0, "=== Controller Drone ESP32 ===")
    stdscr.addstr(1, 0, f"Connesso a {DRONE_SSID} via {IFACE}")
    stdscr.addstr(2, 0, "")
    stdscr.addstr(3, 0, "W/S    -> Pitch   A/D -> Roll")
    stdscr.addstr(4, 0, "Q/E    -> Yaw     UP/DN -> Thrust")
    stdscr.addstr(5, 0, "SPACE  -> STOP    X -> EXIT")
    stdscr.addstr(6, 0, "─" * 36)

    try:
        while True:
            key = stdscr.getch()

            if   key == ord('w'): pitch += STEP_ANGLE
            elif key == ord('s'): pitch -= STEP_ANGLE
            if   key == ord('a'): roll  -= STEP_ANGLE
            elif key == ord('d'): roll  += STEP_ANGLE
            if   key == ord('q'): yaw   -= STEP_ANGLE
            elif key == ord('e'): yaw   += STEP_ANGLE

            if   key == curses.KEY_UP:   thrust = min(thrust + STEP_THRUST, MAX_THRUST)
            elif key == curses.KEY_DOWN: thrust = max(thrust - STEP_THRUST, 0)

            if key == ord(' '):
                thrust = 0; roll = 0.0; pitch = 0.0; yaw = 0.0

            if key == ord('x'):
                break

            invia(roll, pitch, yaw, thrust)

            stdscr.addstr(8,  0, f"Roll:   {roll:6.1f} deg   ")
            stdscr.addstr(9,  0, f"Pitch:  {pitch:6.1f} deg   ")
            stdscr.addstr(10, 0, f"Yaw:    {yaw:6.1f} deg   ")
            stdscr.addstr(11, 0, f"Thrust: {thrust:6d} / {MAX_THRUST}   ")
            stdscr.addstr(12, 0, get_batt_str()[:70].ljust(70))

            stdscr.refresh()
            time.sleep(0.02)

    finally:
        invia(0.0, 0.0, 0.0, 0)
        sock_cmd.close()
        sock_batt.close()

# ──────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────

if __name__ == '__main__':
    connetti_wifi()

    t = threading.Thread(target=battery_thread, daemon=True)
    t.start()

    curses.wrapper(main)
    print("Controller chiuso.")