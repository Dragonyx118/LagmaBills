#!/usr/bin/env python3
"""
activationListener.py — LagmaBills
Resta sempre in ascolto su UDP per i comandi dall'app.
Gira via systemd fin dal boot, indipendentemente da HIM.py.
"""

import socket
import subprocess
import threading
import time
# import paho.mqtt.client as mqtt  # Commentato se non usi più MQTT

UDP_IP   = "0.0.0.0"
UDP_PORT = 5555

# MQTT_BROKER = "localhost"
# MQTT_PORT   = 1883
# TOPIC_AUDIO = "home/ladrodirame/data/sounds"

# BEEP_ON  = "beep_on.wav"
# BEEP_OFF = "beep_off.wav"

HIM_PATH = "/home/ladrodirame/HIM.py"

# print("[DEBUG] Inizializzazione client MQTT...")
# mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="activation_listener")


def beep(filename: str):
    # print(f"[DEBUG] Funzione beep() chiamata con filename: {filename}")
    # try:
    #     mqtt_client.publish(TOPIC_AUDIO, filename)
    #     print(f"[LISTENER] Beep richiesto pubblicato su MQTT: {filename}")
    # except Exception as e:
    #     print(f"[LISTENER] ERRORE beep MQTT: {e}")
    pass


def avvia():
    print("[LISTENER] Comando START ricevuto → avvio HIM.py")
    try:
        subprocess.Popen(["python3", HIM_PATH, "--auto-start"])
        print("[DEBUG] Processo HIM.py avviato con successo.")
    except Exception as e:
        print(f"[DEBUG] Errore nell'avvio di HIM.py: {e}")
    # beep(BEEP_ON)


def ferma():
    print("[LISTENER] Comando STOP ricevuto → arresto tutto")
    try:
        subprocess.run(["python3", HIM_PATH, "--stop"])
        print("[DEBUG] Processo di stop HIM.py completato.")
    except Exception as e:
        print(f"[DEBUG] Errore nell'arresto di HIM.py: {e}")
    # beep(BEEP_OFF)


# ── BLUETOOTH: sincronizzazione controller ───────────────────────

def _bt(*args, timeout=20):
    """Esegue bluetoothctl e ritorna l'output testuale."""
    print(f"[DEBUG] Esecuzione bluetoothctl con argomenti: {args}")
    try:
        r = subprocess.run(["bluetoothctl", *args],
                           capture_output=True, text=True, timeout=timeout)
        print(f"[DEBUG] bluetoothctl output stdout:\n{r.stdout.strip()}")
        if r.stderr:
            print(f"[DEBUG] bluetoothctl output stderr:\n{r.stderr.strip()}")
        return r.stdout
    except Exception as e:
        print(f"[LISTENER] bluetoothctl eccezione: {e}")
        return ""


def _trova_xbox():
    """Ritorna la lista di MAC dei dispositivi 'Xbox' noti a BlueZ."""
    print("[DEBUG] Cerco dispositivi Xbox nei dispositivi noti a BlueZ...")
    macs = []
    devices_output = _bt("devices")
    for line in devices_output.splitlines():
        parts = line.split(" ", 2)   # "Device AA:BB:.. Nome"
        print(f"[DEBUG] Analisi riga devices: {line} -> parti: {parts}")
        if len(parts) == 3 and "xbox" in parts[2].lower():
            macs.append(parts[1])
            print(f"[DEBUG] Trovato dispositivo Xbox compatibile: MAC={parts[1]}, Nome={parts[2]}")
    print(f"[DEBUG] Totale MAC Xbox trovati: {macs}")
    return macs


# Variabile di blocco per evitare esecuzioni simultanee del pairing
pairing_in_corso = threading.Lock()

def sincronizza_controller():
    # Se c'è già una sincronizzazione in corso, ignora il comando duplicato (evita lo spam)
    if not pairing_in_corso.acquire(blocking=False):
        print("[LISTENER] Sincronizzazione già in corso, comando ignorato.")
        return

    try:
        print("[LISTENER] === AVVIO THREAD sincronizzazione_controller (PAIR) ===")
        
        # 1. Avviamo la sessione interattiva pulendo prima eventuali agenti fantasma
        commands = (
            "power on\n"
            "agent off\n"
            "agent on\n"
            "default-agent\n"
            "scan on\n"
        )
        
        print("[DEBUG] Avvio sessione interattiva bluetoothctl...")
        process = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            process.stdin.write(commands)
            process.stdin.flush()
            time.sleep(5) # Lascia il tempo di registrare l'agente e scansionare
        except Exception as e:
            print(f"[DEBUG] Errore nella scrittura iniziale su bluetoothctl: {e}")

        # 2. Cerchiamo il MAC del controller
        macs = _trova_xbox()
        if not macs:
            print("[LISTENER] Nessun controller Xbox trovato nelle vicinanze.")
            process.terminate()
            return

        mac = macs[0]
        print(f"[DEBUG] Trovato controller Xbox: {mac}. Procedo con pairing e connessione...")

        # 3. Inviamo i comandi di pair, trust e connect
        pairing_commands = (
            f"pair {mac}\n"
            f"trust {mac}\n"
            f"connect {mac}\n"
            "quit\n"
        )
        
        try:
            stdout, stderr = process.communicate(input=pairing_commands, timeout=15)
            print(f"[DEBUG] Output sessione bluetoothctl:\n{stdout}")
            
            if "successful" in stdout.lower() or "connected: yes" in _bt("info", mac).lower():
                print(f"[LISTENER] Controller {mac} connesso con successo!")
            else:
                print(f"[LISTENER] Connessione non confermata per {mac}")
        except subprocess.TimeoutExpired:
            process.kill()
            print("[LISTENER] Timeout durante la procedura di pairing/connessione.")
            
    finally:
        # Rilascia il blocco alla fine della procedura (sia in caso di successo che di errore)
        pairing_in_corso.release()


# ── MAIN ─────────────────────────────────────────────────────────

def main():
    print(f"[DEBUG] Configurazione socket UDP su {UDP_IP}:{UDP_PORT}...")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    print(f"[LISTENER] In ascolto UDP su porta {UDP_PORT}...")

    while True:
        try:
            print("[DEBUG] In attesa di ricevere pacchetti UDP...")
            data, addr = sock.recvfrom(1024)
            msg = data.decode(errors="ignore").strip().upper()
            print(f"[LISTENER] Ricevuto pacchetto grezzo da {addr} -> Contenuto decodificato: '{msg}'")

            if msg == "START":
                print("[DEBUG] Riconosciuto comando START")
                avvia()
            elif msg == "STOP":
                print("[DEBUG] Riconosciuto comando STOP")
                ferma()
            elif msg == "PAIR":
                print("[DEBUG] Riconosciuto comando PAIR -> Avvio thread di sincronizzazione")
                threading.Thread(target=sincronizza_controller, daemon=True).start()
            else:
                print(f"[LISTENER] Comando sconosciuto ricevuto: '{msg}'")
        except Exception as e:
            print(f"[LISTENER] ERRORE nel ciclo di ricezione UDP: {e}")


if __name__ == "__main__":
    print("[DEBUG] Script avviato come __main__")
    main()