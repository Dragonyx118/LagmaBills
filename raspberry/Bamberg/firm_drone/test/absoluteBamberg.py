import socket
import struct
import time
import curses

DRONE_IP = '192.168.43.42'
DRONE_PORT = 2390
LOCAL_PORT = 2399

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', LOCAL_PORT))

def invia(roll, pitch, yaw, thrust):
    header = (0x03 << 4) | 0
    data = struct.pack('<fffH', roll, -pitch, yaw, thrust)
    pkt = bytes([header]) + data
    cksum = sum(pkt) & 0xff
    sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

def imposta_modalita(modalita):
    """
    0 = Stabilize  (sempre disponibile)
    1 = Height-hold (richiede MS5611)
    2 = Position-hold (richiede PMW3901 + VL53L1X)
    3 = Hover (richiede PMW3901 + VL53L1X)
    """
    pkt = bytes([0x05, modalita, 0, 0])
    cksum = sum(pkt) & 0xff
    sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

def leggi_batteria():
    pkt = bytes([0x20, 0, 0])
    sock.sendto(pkt, (DRONE_IP, DRONE_PORT))
    sock.settimeout(0.1)
    try:
        data, _ = sock.recvfrom(1024)
        if len(data) >= 2:
            voltage = data[0] + (data[1] << 8)
            return voltage
    except socket.timeout:
        return None

MODALITA_NOMI = {
    0: "STABILIZE  ",
    1: "HEIGHT-HOLD",
    2: "POS-HOLD   ",
    3: "HOVER      ",
}

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(20)

    roll    = 0.0
    pitch   = 0.0
    yaw     = 0.0
    thrust  = 0
    modalita_attiva = 0

    STEP_ANGLE  = 5.0
    STEP_THRUST = 2000
    MAX_THRUST  = 60000
    MIN_THRUST  = 0

    # Intestazione
    stdscr.addstr(0, 0,  "=== Controller Drone ESP32 ===")
    stdscr.addstr(1, 0,  "W/S    = Pitch avanti/indietro")
    stdscr.addstr(2, 0,  "A/D    = Roll sinistra/destra")
    stdscr.addstr(3, 0,  "Q/E    = Yaw sinistra/destra")
    stdscr.addstr(4, 0,  "SU/GIU = Thrust")
    stdscr.addstr(5, 0,  "SPACE  = STOP MOTORI")
    stdscr.addstr(6, 0,  "--- Modalita' ---")
    stdscr.addstr(7, 0,  "F1 = Stabilize  F2 = Height-Hold")
    stdscr.addstr(8, 0,  "F3 = Pos-Hold   F4 = Hover")
    stdscr.addstr(9, 0,  "X  = EXIT")
    stdscr.addstr(10, 0, "------------------------------")

    ciclo = 0

    try:
        while True:
            ciclo += 1
            key = stdscr.getch()

            # --- Pitch ---
            if key == ord('w'):
                pitch += STEP_ANGLE
            elif key == ord('s'):
                pitch -= STEP_ANGLE

            # --- Roll ---
            if key == ord('a'):
                roll -= STEP_ANGLE
            elif key == ord('d'):
                roll += STEP_ANGLE

            # --- Yaw ---
            if key == ord('q'):
                yaw -= STEP_ANGLE
            elif key == ord('e'):
                yaw += STEP_ANGLE

            # --- Thrust ---
            if key == curses.KEY_UP:
                thrust = min(thrust + STEP_THRUST, MAX_THRUST)
            elif key == curses.KEY_DOWN:
                thrust = max(thrust - STEP_THRUST, MIN_THRUST)

            # --- Stop ---
            if key == ord(' '):
                thrust = 0
                roll   = 0.0
                pitch  = 0.0
                yaw    = 0.0

            # --- Modalità (tasti F1-F4) ---
            if key == curses.KEY_F1:
                modalita_attiva = 0
                imposta_modalita(0)
            elif key == curses.KEY_F2:
                modalita_attiva = 1
                imposta_modalita(1)
            elif key == curses.KEY_F3:
                modalita_attiva = 2
                imposta_modalita(2)
            elif key == curses.KEY_F4:
                modalita_attiva = 3
                imposta_modalita(3)

            # --- Exit ---
            if key == ord('x'):
                break

            # --- Invia comandi ---
            invia(roll, pitch, yaw, thrust)

            # --- Display valori ---
            stdscr.addstr(11, 0, f"Roll:     {roll:7.1f} deg   ")
            stdscr.addstr(12, 0, f"Pitch:    {pitch:7.1f} deg   ")
            stdscr.addstr(13, 0, f"Yaw:      {yaw:7.1f} deg   ")
            stdscr.addstr(14, 0, f"Thrust:   {thrust:7d}       ")
            stdscr.addstr(15, 0, f"Modalita: {MODALITA_NOMI[modalita_attiva]}")

            # --- Batteria ogni 10 cicli ---
            if ciclo % 10 == 0:
                batt = leggi_batteria()
                if batt:
                    # Stima percentuale approssimativa (3.3V = 0%, 4.2V = 100%)
                    perc = max(0, min(100, int((batt - 3300) / 9)))
                    stdscr.addstr(16, 0, f"Batteria: {batt} mV ({perc}%)   ")
                else:
                    stdscr.addstr(16, 0, "Batteria: N/A              ")

            stdscr.refresh()
            time.sleep(0.02)

    finally:
        invia(0.0, 0.0, 0.0, 0)
        sock.close()

curses.wrapper(main)
print("Controller chiuso")