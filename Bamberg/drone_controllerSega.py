import socket
import struct
import time
import curses
import subprocess
import sys

DRONE_IP = '192.168.43.42'
DRONE_PORT = 2390
LOCAL_PORT = 2399
DRONE_SSID = 'ESP-DRONE_90E5B199B123'       # cambia con il tuo SSID esatto (es. ESP-DRONE_XXXX)
DRONE_PASSWORD = '12345678'
IFACE = 'wlan1'

# ──────────────────────────────────────────
# Connessione Wi-Fi sulla seconda scheda
# ──────────────────────────────────────────

def connetti_wifi():
    print(f"[*] Connessione a '{DRONE_SSID}' su {IFACE}...")

    # Assicura che l'interfaccia sia attiva
    subprocess.run(['sudo', 'ip', 'link', 'set', IFACE, 'up'], check=True)

    # Disconnetti eventuali connessioni precedenti sull'interfaccia
    subprocess.run(
        ['sudo', 'nmcli', 'device', 'disconnect', IFACE],
        capture_output=True  # ignora errori se non era connessa
    )

    # Connetti al drone
    result = subprocess.run(
        [
            'sudo', 'nmcli', 'device', 'wifi', 'connect', DRONE_SSID,
            'password', DRONE_PASSWORD,
            'ifname', IFACE
        ],
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"[!] Errore connessione:\n{result.stderr}")
        sys.exit(1)

    print(f"[+] Connesso a '{DRONE_SSID}' su {IFACE}")
    print("[*] Attendo assegnazione IP...")
    time.sleep(2)  # attendi DHCP

    # Mostra IP ottenuto
    ip_result = subprocess.run(
        ['ip', 'addr', 'show', IFACE],
        capture_output=True, text=True
    )
    print(ip_result.stdout)

# ──────────────────────────────────────────
# Socket UDP
# ──────────────────────────────────────────

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', LOCAL_PORT))

# ──────────────────────────────────────────
# Funzioni CRTP
# ──────────────────────────────────────────

def invia(roll, pitch, yaw, thrust):
    header = (0x03 << 4) | 0
    data = struct.pack('<fffH', roll, -pitch, yaw, thrust)
    pkt = bytes([header]) + data
    cksum = sum(pkt) & 0xff
    sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

# ──────────────────────────────────────────
# Controller curses
# ──────────────────────────────────────────

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(20)

    roll = 0.0
    pitch = 0.0
    yaw = 0.0
    thrust = 0

    STEP_ANGLE = 5.0
    STEP_THRUST = 2000
    MAX_THRUST = 60000
    MIN_THRUST = 0

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
                roll = 0.0
                pitch = 0.0
                yaw = 0.0

            if key == ord('x'):
                break

            invia(roll, pitch, yaw, thrust)

            stdscr.addstr(11, 0, f"Roll:   {roll:6.1f} deg   ")
            stdscr.addstr(12, 0, f"Pitch:  {pitch:6.1f} deg   ")
            stdscr.addstr(13, 0, f"Yaw:    {yaw:6.1f} deg   ")
            stdscr.addstr(14, 0, f"Thrust: {thrust:6d} / {MAX_THRUST}   ")

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
    curses.wrapper(main)
    print("Controller chiuso.")
