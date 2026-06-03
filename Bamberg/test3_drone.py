import socket
import struct
import time
import curses

#La porta 2390 è quella standard usata da ESP-Drone per il protocollo CRTP via UDP.

DRONE_IP = '192.168.43.42'
DRONE_PORT = 2390
LOCAL_PORT = 2399

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', LOCAL_PORT))

# roba solita protocollo di comunicazione skibidi
def invia(roll, pitch, yaw, thrust):
    header = (0x03 << 4) | 0
    data = struct.pack('<fffH', roll, -pitch, yaw, thrust)
    pkt = bytes([header])
    cksum = sum(b & 0xff for b in pkt) & 0xff
    sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(20)

    roll = 0.0
    pitch = 0.0
    yaw = 0.0
    thrust = 0

    STEP_ANGLE = 5.0
    STEP_THRUST = 1000
    MAX_THRUST = 60000
    MIN_THRUST = 0

    stdscr.addstr(0, 0, "Controller Drone ESP32")
    stdscr.addstr(1, 0, "W/S A/D Q/E Frecce SPACE X")

    try:
        while True:
            key = stdscr.getch()

            # Movimento
            if key == ord('w'):
                pitch = STEP_ANGLE
            elif key == ord('s'):
                pitch = -STEP_ANGLE
            else:
                pitch = 0.0

            if key == ord('a'):
                roll = -STEP_ANGLE
            elif key == ord('d'):
                roll = STEP_ANGLE
            else:
                roll = 0.0

            if key == ord('q'):
                yaw = -STEP_ANGLE
            elif key == ord('e'):
                yaw = STEP_ANGLE
            else:
                yaw = 0.0

            # Thrust
            if key == curses.KEY_UP:
                thrust = min(thrust + STEP_THRUST, MAX_THRUST)
            elif key == curses.KEY_DOWN:
                thrust = max(thrust - STEP_THRUST, MIN_THRUST)

            # Stop immediato
            if key == ord(' '):
                thrust = 0

            # Exit
            if key == ord('x'):
                break

            invia(roll, pitch, yaw, thrust)

            stdscr.addstr(3, 0, f"Roll: {roll}   ")
            stdscr.addstr(4, 0, f"Pitch: {pitch}   ")
            stdscr.addstr(5, 0, f"Yaw: {yaw}   ")
            stdscr.addstr(6, 0, f"Thrust: {thrust}   ")

            stdscr.refresh()
            time.sleep(0.02)

    finally:
        invia(0.0, 0.0, 0.0, 0)
        sock.close()

curses.wrapper(main)
print("ADDIO")