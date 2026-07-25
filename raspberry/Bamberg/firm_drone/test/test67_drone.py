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

    stdscr.addstr(0, 0, "Controller Drone ESP32")
    stdscr.addstr(1, 0, "W/S Pitch  A/D Roll  Q/E Yaw")
    stdscr.addstr(2, 0, "Freccia SU/GIU Thrust")
    stdscr.addstr(3, 0, "SPACE = STOP MOTORI")
    stdscr.addstr(4, 0, "X = EXIT")

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

            if key == ord('x'):
                break

            invia(roll, pitch, yaw, thrust)

            stdscr.addstr(6, 0, f"Roll:   {roll:6.1f}   ")
            stdscr.addstr(7, 0, f"Pitch:  {pitch:6.1f}   ")
            stdscr.addstr(8, 0, f"Yaw:    {yaw:6.1f}   ")
            stdscr.addstr(9, 0, f"Thrust: {thrust:6d}   ")

            stdscr.refresh()
            time.sleep(0.02)

    finally:
        invia(0.0, 0.0, 0.0, 0)
        sock.close()

curses.wrapper(main)
print("Controller chiuso")