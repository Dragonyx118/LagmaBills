#!/usr/bin/env python3
# Riceve comandi MQTT e li forwarda via UDP CRTP al drone

import socket
import struct
import time
import threading
import subprocess
import sys
import paho.mqtt.client as mqtt

# ── Config ──────────────────────────────────────
BROKER       = 'localhost'
DRONE_IP     = '192.168.43.42'
DRONE_PORT   = 2390
LOCAL_PORT   = 2399
DRONE_SSID   = 'ESP-DRONE_90E5B199B123'
DRONE_PASS   = '12345678'
IFACE        = 'wlan1'

# Topic MQTT
TOPIC_CMD    = 'drone/cmd/rpyt'      # riceve comandi {roll, pitch, yaw, thrust}
TOPIC_STOP   = 'drone/cmd/stop'      # riceve qualsiasi msg -> stop motori
TOPIC_STATUS = 'drone/status/bridge' # pubblica latenza e stato
TOPIC_PING   = 'drone/cmd/ping'      # per misurare latenza
TOPIC_PONG   = 'drone/status/pong'   # risposta ping

# ── UDP Socket ───────────────────────────────────
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', LOCAL_PORT))

def invia_crtp(roll, pitch, yaw, thrust):
    header = (0x03 << 4) | 0
    data   = struct.pack('<fffH', roll, -pitch, yaw, int(thrust))
    pkt    = bytes([header]) + data
    cksum  = sum(pkt) & 0xff
    sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

# ── Stats latenza ────────────────────────────────
stats = {
    'last_latency_ms': 0,
    'cmd_count': 0,
    'last_cmd_time': 0,
}

# ── WiFi ─────────────────────────────────────────
def connetti_wifi():
    print(f"[*] Connessione a '{DRONE_SSID}' su {IFACE}...")
    subprocess.run(['sudo', 'ip', 'link', 'set', IFACE, 'up'], check=True)
    subprocess.run(['sudo', 'nmcli', 'device', 'disconnect', IFACE], capture_output=True)
    result = subprocess.run(
        ['sudo', 'nmcli', 'device', 'wifi', 'connect', DRONE_SSID,
         'password', DRONE_PASS, 'ifname', IFACE],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"[!] Errore WiFi:\n{result.stderr}")
        sys.exit(1)
    print(f"[+] Connesso a '{DRONE_SSID}'")
    time.sleep(2)

# ── MQTT Callbacks ───────────────────────────────
mqtt_client = mqtt.Client(client_id="drone_bridge")

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[+] Bridge connesso al broker MQTT")
        client.subscribe(TOPIC_CMD)
        client.subscribe(TOPIC_STOP)
        client.subscribe(TOPIC_PING)
        client.publish(TOPIC_STATUS, '{"stato": "bridge_online"}', retain=True)
    else:
        print(f"[!] Errore connessione MQTT: {rc}")

def on_message(client, userdata, msg):
    topic = msg.topic
    now = time.time()

    if topic == TOPIC_STOP:
        invia_crtp(0, 0, 0, 0)
        print("[STOP] Motori fermati")
        return

    if topic == TOPIC_PING:
        # Rimanda subito il payload con timestamp aggiunto
        client.publish(TOPIC_PONG, msg.payload)
        return

    if topic == TOPIC_CMD:
        try:
            import json
            data = json.loads(msg.payload)
            roll   = float(data.get('roll',   0))
            pitch  = float(data.get('pitch',  0))
            yaw    = float(data.get('yaw',    0))
            thrust = int(data.get('thrust', 0))

            # Misura tempo dalla ricezione al send UDP
            t_recv = time.time()
            invia_crtp(roll, pitch, yaw, thrust)
            t_send = time.time()

            stats['cmd_count'] += 1
            stats['last_cmd_time'] = now

            # Pubblica stats ogni 50 comandi
            if stats['cmd_count'] % 50 == 0:
                import json as j
                client.publish(TOPIC_STATUS, j.dumps({
                    'cmd_count': stats['cmd_count'],
                    'udp_dispatch_us': round((t_send - t_recv) * 1e6, 1),
                }))

        except Exception as e:
            print(f"[!] Errore parsing cmd: {e}")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# ── Main ─────────────────────────────────────────
if __name__ == '__main__':
    connetti_wifi()

    mqtt_client.connect(BROKER, 1883, keepalive=10)
    mqtt_client.loop_start()

    print("[*] Bridge attivo. Ctrl+C per uscire.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        invia_crtp(0, 0, 0, 0)
        mqtt_client.publish(TOPIC_STATUS, '{"stato": "bridge_offline"}', retain=True)
        mqtt_client.disconnect()
        sock.close()
        print("Bridge chiuso.")