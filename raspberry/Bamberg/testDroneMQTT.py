import socket
import struct
import time
import threading
import subprocess
import sys
import json
import paho.mqtt.client as mqtt

#pip install paho-mqtt
#Thread UDP      → spamma comandi al drone a 50Hz sempre
#Thread Watchdog → controlla ogni 1s se l'app è ancora viva
#Thread Landing  → (si spawna solo se serve) abbassa thrust gradualmente

# ──────────────────────────────────────────
# Configurazione
# ──────────────────────────────────────────

DRONE_IP       = '192.168.43.42'
DRONE_PORT     = 2390
LOCAL_PORT     = 2399
DRONE_SSID     = 'ESP-DRONE_90E5B199B123'
DRONE_PASSWORD = '12345678'
IFACE          = 'wlan1'

MQTT_BROKER    = 'localhost'
MQTT_PORT      = 1883

# Topic in ingresso (app → Pi)
TOPIC_CMD      = 'drone/cmd/rpyt'   # payload JSON: {"roll":0,"pitch":0,"yaw":0,"thrust":0}
TOPIC_STOP     = 'drone/cmd/stop'

# Topic in uscita (Pi → app)
TOPIC_STATUS   = 'drone/status/connected'   # "true" / "false"
TOPIC_STATE    = 'drone/status/state'       # JSON stato corrente

LOOP_HZ        = 50        # frequenza invio UDP (50 Hz = 20ms)
MAX_THRUST     = 60000
LANDING_STEP   = 1500      # quanto scende il thrust ad ogni step durante auto-landing
LANDING_HZ     = 10        # Hz durante auto-landing (più lento per non crashare)
MQTT_TIMEOUT   = 2.0       # secondi senza messaggi prima di avviare auto-landing

# ──────────────────────────────────────────
# Stato condiviso (thread-safe con Lock)
# ──────────────────────────────────────────

lock  = threading.Lock()
state = {
    'roll':    0.0,
    'pitch':   0.0,
    'yaw':     0.0,
    'thrust':  0,
    'landing': False,   # True = auto-landing in corso
    'armed':   False,   # True = drone in volo (thrust > 0 almeno una volta)
    'running': True,    # False = spegni tutto e termina
}

last_mqtt_msg = time.time()   # timestamp ultimo messaggio ricevuto dall'app

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
# UDP / CRTP
# ──────────────────────────────────────────

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', LOCAL_PORT))

def invia(roll, pitch, yaw, thrust):
    header = (0x03 << 4) | 0
    data   = struct.pack('<fffH', roll, -pitch, yaw, int(thrust))
    pkt    = bytes([header]) + data
    cksum  = sum(pkt) & 0xff
    sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

# ──────────────────────────────────────────
# Thread UDP — spamma comandi al drone a 50Hz
# ──────────────────────────────────────────

def udp_loop():
    interval = 1.0 / LOOP_HZ
    while True:
        with lock:
            if not state['running']:
                break
            r = state['roll']
            p = state['pitch']
            y = state['yaw']
            t = state['thrust']
        invia(r, p, y, t)
        time.sleep(interval)

    invia(0.0, 0.0, 0.0, 0)
    sock.close()
    print("[UDP] Thread terminato.")

# ──────────────────────────────────────────
# Thread Auto-landing
# ──────────────────────────────────────────

def auto_landing_loop(mqtt_client):
    """
    Abbassa il thrust di LANDING_STEP ogni (1/LANDING_HZ) secondi fino a 0.
    Il thread UDP continua a spammare i valori aggiornati al drone.
    """
    print("[LANDING] Auto-landing avviato...")
    interval = 1.0 / LANDING_HZ

    while True:
        with lock:
            if not state['landing']:
                break
            t = state['thrust']
            if t <= 0:
                state['thrust']  = 0
                state['landing'] = False
                state['armed']   = False
                break
            state['thrust'] = max(0, t - LANDING_STEP)
            t_new = state['thrust']

        print(f"[LANDING] Thrust: {t_new}")
        time.sleep(interval)

    print("[LANDING] Atterrato.")
    if mqtt_client.is_connected():
        mqtt_client.publish(TOPIC_STATE, json.dumps({
            'roll': 0, 'pitch': 0, 'yaw': 0, 'thrust': 0, 'landing': False
        }))

# ──────────────────────────────────────────
# Thread Watchdog — monitora timeout MQTT
# ──────────────────────────────────────────

def watchdog_loop(mqtt_client):
    """
    Controlla ogni secondo se l'app sta ancora mandando comandi.
    Se il timeout scade e il drone è in volo, avvia auto-landing.
    """
    while True:
        time.sleep(1.0)
        with lock:
            if not state['running']:
                break
            elapsed   = time.time() - last_mqtt_msg
            in_flight = state['armed'] and state['thrust'] > 0
            landing   = state['landing']

        if in_flight and not landing and elapsed > MQTT_TIMEOUT:
            print(f"[WATCHDOG] Nessun comando da {elapsed:.1f}s → auto-landing")
            with lock:
                state['landing'] = True
            threading.Thread(target=auto_landing_loop, args=(mqtt_client,), daemon=True).start()

    print("[WATCHDOG] Thread terminato.")

# ──────────────────────────────────────────
# MQTT callbacks
# ──────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Connesso al broker ({MQTT_BROKER}:{MQTT_PORT})")
        client.subscribe(TOPIC_CMD)
        client.subscribe(TOPIC_STOP)
        client.publish(TOPIC_STATUS, 'true', retain=True)
    else:
        print(f"[MQTT] Connessione fallita, rc={rc}")

def on_disconnect(client, userdata, rc):
    print(f"[MQTT] Disconnesso (rc={rc})")
    client.publish(TOPIC_STATUS, 'false', retain=True)

def on_message(client, userdata, msg):
    global last_mqtt_msg
    last_mqtt_msg = time.time()

    if msg.topic == TOPIC_STOP:
        with lock:
            state['roll']    = 0.0
            state['pitch']   = 0.0
            state['yaw']     = 0.0
            state['thrust']  = 0
            state['landing'] = False
            state['armed']   = False
        print("[MQTT] STOP ricevuto")
        return

    if msg.topic == TOPIC_CMD:
        try:
            payload = json.loads(msg.payload.decode())
            roll    = float(payload.get('roll',   0.0))
            pitch   = float(payload.get('pitch',  0.0))
            yaw     = float(payload.get('yaw',    0.0))
            thrust  = int(payload.get('thrust',   0))
            thrust  = max(0, min(thrust, MAX_THRUST))

            with lock:
                # Se arriva un nuovo comando durante auto-landing, annulla landing
                if state['landing'] and thrust > 0:
                    state['landing'] = False

                state['roll']   = roll
                state['pitch']  = pitch
                state['yaw']    = yaw
                state['thrust'] = thrust

                if thrust > 0:
                    state['armed'] = True

            client.publish(TOPIC_STATE, json.dumps({
                'roll': roll, 'pitch': pitch,
                'yaw': yaw,   'thrust': thrust,
                'landing': False
            }))

        except (json.JSONDecodeError, ValueError) as e:
            print(f"[MQTT] Payload non valido: {e}")

# ──────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────

if __name__ == '__main__':
    connetti_wifi()

    # Avvia thread UDP
    t_udp = threading.Thread(target=udp_loop, daemon=True)
    t_udp.start()

    # Setup MQTT
    client = mqtt.Client()
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    # Will message: se il Pi crasha, il broker pubblica automaticamente "false"
    client.will_set(TOPIC_STATUS, 'false', retain=True)

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    # Avvia watchdog
    t_watchdog = threading.Thread(target=watchdog_loop, args=(client,), daemon=True)
    t_watchdog.start()

    print("[*] Drone controller avviato. In attesa di comandi MQTT...")
    print(f"    Comandi :  {TOPIC_CMD}")
    print(f"    Stop    :  {TOPIC_STOP}")
    print(f"    Stato   :  {TOPIC_STATE}")
    print(f"    Auto-landing dopo {MQTT_TIMEOUT}s senza comandi")
    print("    Ctrl+C per uscire")

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[*] Uscita...")
        with lock:
            state['running'] = False
            state['thrust']  = 0
        client.publish(TOPIC_STATUS, 'false', retain=True)
        client.disconnect()
        time.sleep(0.5)

    print("Controller chiuso.")