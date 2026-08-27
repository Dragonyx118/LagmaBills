#!/usr/bin/env python3
# drone_mqtt_bridge.py - Gira sul Pi
# v3: IFACE aggiornato a wlan0 (scheda USB per il drone)

import socket
import struct
import time
import threading
import subprocess
import sys
import json
import paho.mqtt.client as mqtt

# ── Config ───────────────────────────────────────
BROKER       = 'localhost'
DRONE_IP     = '192.168.43.42'
DRONE_PORT   = 2390
LOCAL_PORT   = 2399
DRONE_SSID   = 'ESP-DRONE_90E5B199B123'
DRONE_PASS   = '12345678'
IFACE        = 'wlan0'           # ← scheda USB Realtek RTL8188EUS

WATCHDOG_TIMEOUT  = 8.0
LAND_THRUST_START = 30000
LAND_THRUST_STEP  = 500
LAND_STEP_DELAY   = 0.05

# Topic MQTT
TOPIC_CMD    = 'drone/cmd/rpyt'
TOPIC_STOP   = 'drone/cmd/stop'
TOPIC_STATUS = 'drone/status/bridge'
TOPIC_PING   = 'drone/cmd/ping'
TOPIC_PONG   = 'drone/status/pong'
TOPIC_PARAM  = 'drone/cmd/param'

# ── Stato condiviso ──────────────────────────────
watchdog_lock   = threading.Lock()
last_cmd_time   = time.time()
watchdog_active = False
stats = {'cmd_count': 0, 'last_thrust': 0}

# ── UDP Socket ───────────────────────────────────
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', LOCAL_PORT))

def invia_crtp(roll, pitch, yaw, thrust):
    header = (0x03 << 4) | 0
    data   = struct.pack('<fffH', roll, -pitch, yaw, int(thrust))
    pkt    = bytes([header]) + data
    cksum  = sum(pkt) & 0xff
    sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

# ── CRTP Parameter Write ─────────────────────────
PARAM_TYPES = {
    'uint8':  0x08,
    'uint16': 0x06,
    'uint32': 0x07,
    'float':  0x0A,
    'int8':   0x00,
    'int16':  0x02,
    'int32':  0x04,
}

def invia_param(group, name, type_str, value):
    type_id = PARAM_TYPES.get(type_str)
    if type_id is None:
        print(f"[PARAM] Tipo sconosciuto: {type_str}")
        return
    header  = (2 << 4) | 3
    group_b = group.encode('ascii') + b'\x00'
    name_b  = name.encode('ascii')  + b'\x00'
    if type_str == 'float':
        val_b = struct.pack('<f', float(value))
    elif type_str in ('uint8', 'int8'):
        val_b = struct.pack('<B' if type_str == 'uint8' else '<b', int(value))
    elif type_str in ('uint16', 'int16'):
        val_b = struct.pack('<H' if type_str == 'uint16' else '<h', int(value))
    elif type_str in ('uint32', 'int32'):
        val_b = struct.pack('<I' if type_str == 'uint32' else '<i', int(value))
    else:
        val_b = struct.pack('<B', int(value))
    payload = bytes([0x02, type_id]) + group_b + name_b + val_b
    pkt     = bytes([header]) + payload
    cksum   = sum(pkt) & 0xff
    sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))
    print(f"[PARAM] {group}.{name} ({type_str}) = {value}")

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

# ── MQTT ─────────────────────────────────────────
mqtt_client = mqtt.Client(client_id="drone_bridge")

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("[+] Bridge connesso al broker MQTT")
        client.subscribe(TOPIC_CMD)
        client.subscribe(TOPIC_STOP)
        client.subscribe(TOPIC_PING)
        client.subscribe(TOPIC_PARAM)
        client.publish(TOPIC_STATUS, '{"stato": "bridge_online"}', retain=True)
    else:
        print(f"[!] Errore MQTT: {rc}")

def on_message(client, userdata, msg):
    global last_cmd_time, watchdog_active
    topic = msg.topic

    if topic == TOPIC_STOP:
        invia_crtp(0, 0, 0, 0)
        with watchdog_lock:
            watchdog_active = False
            stats['last_thrust'] = 0
        print("[STOP] Motori fermati")
        return

    if topic == TOPIC_PING:
        client.publish(TOPIC_PONG, msg.payload)
        return

    if topic == TOPIC_PARAM:
        try:
            d     = json.loads(msg.payload)
            invia_param(d['group'], d['name'], d.get('type', 'float'), d['value'])
            client.publish(TOPIC_STATUS,
                json.dumps({'stato': 'bridge_online',
                            'last_param': f"{d['group']}.{d['name']}={d['value']}"}))
        except Exception as e:
            print(f"[!] Errore param: {e}")
        return

    if topic == TOPIC_CMD:
        try:
            data   = json.loads(msg.payload)
            roll   = float(data.get('roll',   0))
            pitch  = float(data.get('pitch',  0))
            yaw    = float(data.get('yaw',    0))
            thrust = int(data.get('thrust',   0))
            invia_crtp(roll, pitch, yaw, thrust)
            with watchdog_lock:
                last_cmd_time = time.time()
                stats['cmd_count'] += 1
                if thrust > 0:
                    watchdog_active = True
                    stats['last_thrust'] = thrust
        except Exception as e:
            print(f"[!] Errore cmd: {e}")

mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

# ── Watchdog ─────────────────────────────────────
def watchdog_loop(client):
    global watchdog_active
    while True:
        time.sleep(0.5)
        with watchdog_lock:
            active  = watchdog_active
            elapsed = time.time() - last_cmd_time
            last_t  = stats['last_thrust']
        if active and elapsed > WATCHDOG_TIMEOUT:
            print(f"[WATCHDOG] {elapsed:.1f}s senza comandi → atterraggio")
            client.publish(TOPIC_STATUS, '{"stato": "watchdog_landing"}')
            with watchdog_lock:
                watchdog_active = False
            thrust = max(last_t, LAND_THRUST_START)
            while thrust > 0:
                invia_crtp(0.0, 0.0, 0.0, thrust)
                thrust = max(0, thrust - LAND_THRUST_STEP)
                time.sleep(LAND_STEP_DELAY)
            invia_crtp(0.0, 0.0, 0.0, 0)
            print("[WATCHDOG] Atterraggio completato")
            client.publish(TOPIC_STATUS, '{"stato": "bridge_online"}')

# ── Main ─────────────────────────────────────────
if __name__ == '__main__':
    connetti_wifi()
    mqtt_client.connect(BROKER, 1883, keepalive=10)
    mqtt_client.loop_start()
    threading.Thread(target=watchdog_loop, args=(mqtt_client,), daemon=True).start()
    print(f"[*] Watchdog attivo (timeout: {WATCHDOG_TIMEOUT}s)")
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
