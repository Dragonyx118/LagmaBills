import socket
import struct
import time
import curses
import subprocess
import sys
import threading

# pip install cflib
import cflib.crtp
from cflib.crazyflie import Crazyflie
from cflib.crazyflie.log import LogConfig
from cflib.crazyflie.syncCrazyflie import SyncCrazyflie

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
# UDP / CRTP (invio comandi)
# ──────────────────────────────────────────

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', LOCAL_PORT))

def invia(roll, pitch, yaw, thrust):
    header = (0x03 << 4) | 0
    data   = struct.pack('<fffH', roll, -pitch, yaw, thrust)
    pkt    = bytes([header]) + data
    cksum  = sum(pkt) & 0xff
    sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

# ──────────────────────────────────────────
# Lettura batteria via cflib (thread separato)
# ──────────────────────────────────────────

batt_lock  = threading.Lock()
batt_data  = {
    'vbat':  None,   # tensione in volt (float)
    'level': None,   # percentuale 0-100 (int)
    'error': None,   # stringa errore se fallisce
    'ready': False,  # True quando il log è attivo
}

def battery_thread():
    """
    Si connette al drone via cflib su UDP e avvia il log pm.vbat / pm.batteryLevel.
    Gira in background e aggiorna batt_data ogni ~500ms.
    """
    uri = f'udp://{DRONE_IP}:{DRONE_PORT}'
    cflib.crtp.init_drivers()

    try:
        cf = Crazyflie(rw_cache='./cache')
        with SyncCrazyflie(uri, cf=cf) as scf:
            logconf = LogConfig(name='Battery', period_in_ms=500)
            try:
                logconf.add_variable('pm.vbat',         'float')
                logconf.add_variable('pm.batteryLevel',  'uint8_t')
            except KeyError as e:
                with batt_lock:
                    batt_data['error'] = f"Variabile log non trovata: {e} — firmware non la espone"
                return

            def callback(timestamp, data, logconf):
                with batt_lock:
                    batt_data['vbat']  = round(data.get('pm.vbat', 0.0), 2)
                    batt_data['level'] = data.get('pm.batteryLevel', 0)
                    batt_data['error'] = None
                    batt_data['ready'] = True

            scf.cf.log.add_config(logconf)
            logconf.data_received_cb.add_callback(callback)
            logconf.error_cb.add_callback(
                lambda conf, msg: _set_batt_error(f"Errore log CRTP: {msg}")
            )
            logconf.start()

            # rimane vivo finché il processo principale gira
            while True:
                time.sleep(1)

    except Exception as e:
        _set_batt_error(f"cflib: {e}")

def _set_batt_error(msg):
    with batt_lock:
        batt_data['error'] = msg
        batt_data['ready'] = False

def get_batt_str():
    """Ritorna stringa pronta per curses."""
    with batt_lock:
        if batt_data['error']:
            return f"Batteria: ERRORE — {batt_data['error']}"
        if not batt_data['ready']:
            return "Batteria: in attesa..."
        v = batt_data['vbat']
        l = batt_data['level']
        return f"Batteria: {v:.2f}V  {l}%"

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
            stdscr.addstr(15, 0, get_batt_str()[:60].ljust(60))

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

    # Avvia lettura batteria in background (non blocca se fallisce)
    t = threading.Thread(target=battery_thread, daemon=True)
    t.start()

    curses.wrapper(main)
    print("Controller chiuso.")