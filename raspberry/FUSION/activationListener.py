#!/usr/bin/env python3
"""
activationListener.py — LagmaBills
Resta sempre in ascolto su UDP per i comandi dall'app.
Gira via systemd fin dal boot, indipendentemente da HIM.py.

Comandi UDP ricevuti (testo semplice):
  "START" → avvia HIM.py in modalità automatica (faccia+pistats+controller)
  "STOP"  → termina tutta la sessione tmux 'lagmabills'
  "PAIR"  → sincronizza il controller Xbox via Bluetooth

Il beep passa da MQTT (pi/audio/play) verso mqttMedia.py,
che gira come servizio systemd separato (lagma-media).
"""

import socket
import subprocess
import threading
import time
import paho.mqtt.client as mqtt

UDP_IP   = "0.0.0.0"
UDP_PORT = 5555

MQTT_BROKER = "localhost"
MQTT_PORT   = 1883
TOPIC_AUDIO = "pi/audio/play"

BEEP_ON  = "beep_on.wav"
BEEP_OFF = "beep_off.wav"

HIM_PATH = "/home/ladrodirame/HIM.py"

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="activation_listener")


def beep(filename: str):
    try:
        mqtt_client.publish(TOPIC_AUDIO, filename)
        print(f"[LISTENER] Beep richiesto: {filename}")
    except Exception as e:
        print(f"[LISTENER] Errore beep: {e}")


def avvia():
    print("[LISTENER] Comando START ricevuto → avvio HIM.py")
    subprocess.Popen(["python3", HIM_PATH, "--auto-start"])
    beep(BEEP_ON)


def ferma():
    print("[LISTENER] Comando STOP ricevuto → arresto tutto")
    subprocess.run(["python3", HIM_PATH, "--stop"])
    beep(BEEP_OFF)


# ── BLUETOOTH: sincronizzazione controller ───────────────────────

def _bt(*args, timeout=20):
    """Esegue bluetoothctl e ritorna l'output testuale."""
    try:
        r = subprocess.run(["bluetoothctl", *args],
                           capture_output=True, text=True, timeout=timeout)
        return r.stdout
    except Exception as e:
        print(f"[LISTENER] bluetoothctl errore: {e}")
        return ""


def _trova_xbox():
    """Ritorna la lista di MAC dei dispositivi 'Xbox' noti a BlueZ."""
    macs = []
    for line in _bt("devices").splitlines():
        parts = line.split(" ", 2)   # "Device AA:BB:.. Nome"
        if len(parts) == 3 and "xbox" in parts[2].lower():
            macs.append(parts[1])
    return macs


def sincronizza_controller():
    print("[LISTENER] Comando PAIR → sincronizzazione controller")
    beep(BEEP_ON)

    # 1. Dimentica i vecchi accoppiamenti Xbox (ormai invalidi)
    for mac in _trova_xbox():
        _bt("remove", mac)
        print(f"[LISTENER] Rimosso vecchio accoppiamento {mac}")

    # 2. Scansione: il controller deve essere in modalità pairing
    _bt("--timeout", "15", "scan", "on", timeout=25)

    # 3. Pair + trust + connect
    macs = _trova_xbox()
    if not macs:
        print("[LISTENER] Nessun controller trovato (era in pairing?)")
        beep(BEEP_OFF)
        return

    mac = macs[0]
    _bt("pair", mac)
    _bt("trust", mac)
    out = _bt("connect", mac)
    if "successful" in out.lower():
        print(f"[LISTENER] Controller {mac} connesso")
        beep(BEEP_ON)
    else:
        print(f"[LISTENER] Connessione fallita: {out.strip()}")
        beep(BEEP_OFF)


# ── MAIN ─────────────────────────────────────────────────────────

def main():
    mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_client.loop_start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print(f"[LISTENER] In ascolto UDP su porta {UDP_PORT}...")

    while True:
        data, addr = sock.recvfrom(1024)
        msg = data.decode(errors="ignore").strip().upper()
        print(f"[LISTENER] Ricevuto '{msg}' da {addr}")

        if msg == "START":
            avvia()
        elif msg == "STOP":
            ferma()
        elif msg == "PAIR":
            # In un thread: la procedura dura fino a ~30 secondi
            threading.Thread(target=sincronizza_controller, daemon=True).start()
        else:
            print(f"[LISTENER] Comando sconosciuto: {msg}")


if __name__ == "__main__":
    main()
