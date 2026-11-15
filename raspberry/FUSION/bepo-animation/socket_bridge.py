"""
socket_bridge.py — FUSION / RoboEyes
Listener TCP "raw" sulla porta 9876: usato da wakewordSimple.py e da
altri script sul Pi per cambiare mood/animazione senza passare da
MQTT (comando testuale semplice, una riga per connessione).
Era il vecchio RoboEyes._start_listener(), qui isolato.
"""

import socket
import threading

from constants import MOOD_MAP


def start_socket_listener(robo):
    def listen():
        try:
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('0.0.0.0', 9876))
            s.listen(5)
            while True:
                conn, _ = s.accept()
                data = conn.recv(64).decode().strip()
                conn.close()
                if data in MOOD_MAP:
                    robo.next_mood = MOOD_MAP[data]
                elif data == 'wink':
                    robo.anim_wink('left')
                elif data == 'winkr':
                    robo.anim_wink('right')
                elif data == 'look':
                    robo.anim_look_around()
                elif data == 'spin':
                    robo.anim_spin()
                elif data == 'shake':
                    robo.anim_shake()
                elif data == 'hearts':
                    robo.anim_hearts()
                elif data == 'laugh':
                    robo.anim_laugh()
                elif data == 'confused_anim':
                    robo.anim_confused()
        except Exception as e:
            print('Listener:', e)

    threading.Thread(target=listen, daemon=True).start()
