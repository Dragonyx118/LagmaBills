#!/usr/bin/env python3
# drone_mqtt_controller_win.py - Versione Windows (no curses)

import time
import json
import threading
import keyboard
import paho.mqtt.client as mqtt
import os

BROKER = 'LagmaBills.local'

TOPIC_CMD    = 'drone/cmd/rpyt'
TOPIC_STOP   = 'drone/cmd/stop'
TOPIC_PING   = 'drone/cmd/ping'
TOPIC_PONG   = 'drone/status/pong'
TOPIC_STATUS = 'drone/status/bridge'

state_lock = threading.Lock()
state = {
    'latency_ms':   None,
    'bridge_state': 'sconosciuto',
}

roll   = 0.0
pitch  = 0.0
yaw    = 0.0
thrust = 0
running = True

STEP_ANGLE  = 5.0
STEP_THRUST = 2000
MAX_THRUST  = 60000

# ── MQTT ─────────────────────────────────────────
client = mqtt.Client(client_id="drone_controller_pc")

def on_connect(c, userdata, flags, rc):
    if rc == 0:
        print("[+] Connesso al broker")
        c.subscribe(TOPIC_PONG)
        c.subscribe(TOPIC_STATUS)

def on_message(c, userdata, msg):
    with state_lock:
        if msg.topic == TOPIC_PONG:
            try:
                data = json.loads(msg.payload)
                sent = data.get('t')
                if sent:
                    state['latency_ms'] = round((time.time() - sent) * 1000, 1)
            except:
                pass
        elif msg.topic == TOPIC_STATUS:
            try:
                data = json.loads(msg.payload)
                state['bridge_state'] = data.get('stato', '?')
            except:
                pass

client.on_connect = on_connect
client.on_message = on_message
client.connect(BROKER, 1883, keepalive=10)
client.loop_start()

# ── Ping periodico ───────────────────────────────
def ping_loop():
    while running:
        client.publish(TOPIC_PING, json.dumps({'t': time.time()}))
        time.sleep(0.5)

threading.Thread(target=ping_loop, daemon=True).start()

# ── Input tasti ──────────────────────────────────
def leggi_tasti():
    global roll, pitch, yaw, thrust, running

    if keyboard.is_pressed('w'):     pitch += STEP_ANGLE
    elif keyboard.is_pressed('s'):   pitch -= STEP_ANGLE
    if keyboard.is_pressed('a'):     roll  -= STEP_ANGLE
    elif keyboard.is_pressed('d'):   roll  += STEP_ANGLE
    if keyboard.is_pressed('q'):     yaw   -= STEP_ANGLE
    elif keyboard.is_pressed('e'):   yaw   += STEP_ANGLE
    if keyboard.is_pressed('up'):    thrust = min(thrust + STEP_THRUST, MAX_THRUST)
    elif keyboard.is_pressed('down'):thrust = max(thrust - STEP_THRUST, 0)
    if keyboard.is_pressed('space'):
        roll = pitch = yaw = 0.0
        thrust = 0
        client.publish(TOPIC_STOP, '1')
    if keyboard.is_pressed('x'):
        running = False

# ── Display ───────────────────────────────────────
def stampa_stato():
    os.system('cls')
    with state_lock:
        lat = state['latency_ms']
        bridge = state['bridge_state']

    lat_str  = f"{lat:.1f} ms" if lat is not None else "misurazione..."
    warn_str = "  ⚠ ALTA" if lat and lat > 80 else ""

    print("=== Controller Drone MQTT (Windows) ===")
    print(f"Broker: {BROKER}")
    print()
    print("W/S     -> Pitch avanti/indietro")
    print("A/D     -> Roll sinistra/destra")
    print("Q/E     -> Yaw sinistra/destra")
    print("UP/DN   -> Thrust su/giu")
    print("SPACE   -> STOP MOTORI")
    print("X       -> EXIT")
    print("─" * 38)
    print(f"Roll:   {roll:6.1f} deg")
    print(f"Pitch:  {pitch:6.1f} deg")
    print(f"Yaw:    {yaw:6.1f} deg")
    print(f"Thrust: {thrust:6d} / {MAX_THRUST}")
    print("─" * 38)
    print(f"Latenza MQTT: {lat_str}{warn_str}")
    print(f"Bridge:       {bridge}")

# ── Loop principale ───────────────────────────────
print("[*] Connessione al broker...")
time.sleep(1)
print("[*] Avvio controller. Lancia prima drone_mqtt_bridge.py sul Pi!")
time.sleep(1)

try:
    while running:
        leggi_tasti()

        cmd = json.dumps({
            'roll':   round(roll, 1),
            'pitch':  round(pitch, 1),
            'yaw':    round(yaw, 1),
            'thrust': thrust,
        })
        client.publish(TOPIC_CMD, cmd)

        stampa_stato()
        time.sleep(0.05)  # 20Hz

finally:
    client.publish(TOPIC_STOP, '1')
    client.disconnect()
    print("Controller chiuso.")