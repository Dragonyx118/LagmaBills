#!/usr/bin/env python3
"""
navigator.py — LagmaBills
Navigazione autonoma reattiva per robot Mecanum

Strategia: Potential Field locale
  - Campo attrattivo verso il goal (se impostato) o wandering
  - Campo repulsivo dagli ostacoli rilevati dai sensori
  - STOP di emergenza su cliff (dirupo/scalino)
  - STOP di emergenza se ostacolo troppo vicino su tutti i lati

Subscribe MQTT:
  robot/odometria          → posa attuale
  robot/sensori/distanze   → distanze HC-SR04 in cm
  robot/cliff/stato        → stato sensori cliff
  robot/nav/goal           → {"x": float, "y": float}   (goal opzionale)
  robot/nav/cmd            → "start" | "stop" | "reset_goal"

Publish MQTT:
  robot/motori/cmd         → {"vx": float, "vy": float, "vr": float}
                              (letto dall'ESP32 motori via MQTT callback)
  robot/nav/stato          → stato navigatore (per debug/viewer)

SICUREZZA:
  - Cliff → stop immediato + publish robot/motori/cmd stop
  - Se nessun aggiornamento sensori per >1s → stop
  - Distanza frontale < STOP_DIST_CM → frena
  - Distanza laterale < STOP_DIST_CM → corregge traiettoria

Nota sull'interfaccia motori:
  L'ESP32 motori ascolta robot/motori/cmd e si aspetta:
    {"vx": int -255..255, "vy": int -255..255, "vr": int -255..255}
  dove vx=avanti, vy=laterale, vr=rotazione.
  Il codice chiama mecanumDrive(vx, vy, vr) che già esiste nel firmware.
"""

import json
import math
import time
import threading
import paho.mqtt.client as mqtt

# ── CONFIGURAZIONE ───────────────────────────────────────────────

MQTT_BROKER = "100.100.61.49"
MQTT_PORT   = 1883

# Topic
T_ODOMETRIA = "robot/odometria"
T_SENSORI   = "robot/sensori/distanze"
T_CLIFF     = "robot/cliff/stato"
T_GOAL      = "robot/nav/goal"
T_NAV_CMD   = "robot/nav/cmd"
T_MOTORI    = "robot/motori/cmd"
T_STATO     = "robot/nav/stato"

# ── PARAMETRI SICUREZZA ──────────────────────────────────────────

# Distanza minima frontale prima di frenare (cm)
BRAKE_DIST_CM  = 30.0
# Distanza minima assoluta (stop totale)
STOP_DIST_CM   = 15.0
# Distanza laterale entro cui repulsione laterale entra in gioco
REPULSE_DIST_CM = 40.0

# Timeout sensori: se non arrivano dati da più di N secondi → stop
SENSOR_TIMEOUT_S = 1.0

# ── PARAMETRI POTENTIAL FIELD ────────────────────────────────────

# Gain campo attrattivo (verso goal)
KA = 1.0
# Gain campo repulsivo (da ostacoli)
KR = 0.8
# Velocità massima output (unità ESP32: 0-255)
VEL_MAX  = 180
ROT_MAX  = 120

# Distanza dal goal entro cui si considera "arrivato"
GOAL_RADIUS_M = 0.10   # 10 cm

# ── STATO GLOBALE ────────────────────────────────────────────────

state_lock = threading.Lock()
state = {
    "running":     False,
    "cliff_stop":  False,
    "sensor_stop": False,
    "goal":        None,        # {"x": float, "y": float} oppure None
    "pose":        {"x": 0.0, "y": 0.0, "theta": 0.0},
    "sensors":     {            # distanze in cm
        "FRONTE": 9999, "RETRO": 9999,
        "SINISTRA": 9999, "DESTRA": 9999,
    },
    "cliff":       {"cliff_f": False, "cliff_r": False},
    "last_sensor_ts": 0.0,
    "cmd_vx": 0, "cmd_vy": 0, "cmd_vr": 0,
    "mode": "idle",             # idle | avoid | goto_goal | wander
}

mqtt_client = None

# ── LOGICA NAVIGAZIONE ───────────────────────────────────────────

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def compute_command() -> dict:
    """
    Calcola il comando motori con potential field.
    Restituisce {"vx": int, "vy": int, "vr": int}.
    STOP immediato se cliff o sensori scaduti.
    """
    with state_lock:
        if not state["running"]:
            return {"vx": 0, "vy": 0, "vr": 0}

        # ── STOP DI EMERGENZA ────────────────────────────────────
        if state["cliff_stop"]:
            state["mode"] = "cliff_stop"
            return {"vx": 0, "vy": 0, "vr": 0}

        dt_sensor = time.time() - state["last_sensor_ts"]
        if dt_sensor > SENSOR_TIMEOUT_S and state["last_sensor_ts"] > 0:
            state["sensor_stop"] = True
            state["mode"] = "sensor_timeout"
            return {"vx": 0, "vy": 0, "vr": 0}
        state["sensor_stop"] = False

        sens  = state["sensors"]
        pose  = state["pose"]
        goal  = state["goal"]
        theta = pose["theta"]

        # Letture sensori (cm)
        dist_f = sens.get("FRONTE",  9999)
        dist_r = sens.get("RETRO",   9999)
        dist_l = sens.get("SINISTRA", 9999)
        dist_d = sens.get("DESTRA",   9999)

        # ── STOP FRONTALE ASSOLUTO ───────────────────────────────
        if dist_f < STOP_DIST_CM:
            state["mode"] = "obstacle_stop"
            return {"vx": 0, "vy": 0, "vr": 0}

    # ── CAMPO REPULSIVO ──────────────────────────────────────────
    # Direzioni nel frame ROBOT (X=avanti, Y=sinistra)
    repulse_x = 0.0
    repulse_y = 0.0

    def repulse_component(dist_cm, direction_x, direction_y):
        """Forza repulsiva da un sensore. direction = verso il sensore."""
        if dist_cm >= REPULSE_DIST_CM or dist_cm <= 0:
            return 0.0, 0.0
        # Forza inversamente proporzionale al quadrato della distanza
        force = KR * (1.0 / dist_cm - 1.0 / REPULSE_DIST_CM) ** 2
        # Spinge nella direzione OPPOSTA al sensore
        return -force * direction_x, -force * direction_y

    fx, fy = repulse_component(dist_f, 1.0, 0.0)   # ostacolo avanti → spinge indietro
    repulse_x += fx; repulse_y += fy

    fx, fy = repulse_component(dist_r, -1.0, 0.0)  # ostacolo dietro → spinge avanti
    repulse_x += fx; repulse_y += fy

    fx, fy = repulse_component(dist_l, 0.0, 1.0)   # ostacolo sinistra → spinge dx
    repulse_x += fx; repulse_y += fy

    fx, fy = repulse_component(dist_d, 0.0, -1.0)  # ostacolo destra → spinge sx
    repulse_x += fx; repulse_y += fy

    # ── CAMPO ATTRATTIVO ─────────────────────────────────────────
    attract_x = 0.0
    attract_y = 0.0
    attract_r = 0.0
    mode = "wander"

    with state_lock:
        pose = dict(state["pose"])
        goal = state["goal"]

    if goal is not None:
        dx_w = goal["x"] - pose["x"]
        dy_w = goal["y"] - pose["y"]
        dist_to_goal = math.hypot(dx_w, dy_w)

        if dist_to_goal < GOAL_RADIUS_M:
            # Arrivato al goal
            with state_lock:
                state["goal"] = None
                state["mode"] = "goal_reached"
            if mqtt_client:
                mqtt_client.publish(T_STATO, json.dumps({"event": "goal_reached", "ts": time.time()}))
            return {"vx": 0, "vy": 0, "vr": 0}

        # Direzione verso goal in world frame → trasforma in robot frame
        angle_to_goal_w = math.atan2(dy_w, dx_w)
        angle_local = angle_to_goal_w - pose["theta"]

        # Componenti attrattive nel frame robot
        attract_x = KA * math.cos(angle_local) * min(dist_to_goal, 1.0)
        attract_y = KA * math.sin(angle_local) * min(dist_to_goal, 1.0)

        # Piccola rotazione verso il goal (allineamento)
        angle_err = math.atan2(math.sin(angle_local), math.cos(angle_local))
        attract_r = 0.3 * angle_err
        mode = "goto_goal"
    else:
        # Wander: muoviti in avanti se libero, altrimenti ruota
        if dist_f > BRAKE_DIST_CM:
            attract_x = 0.5
        else:
            attract_r = 0.5 if dist_l < dist_d else -0.5
        mode = "wander"

    # ── SOMMA DEI CAMPI ──────────────────────────────────────────
    total_x = attract_x + repulse_x
    total_y = attract_y + repulse_y
    total_r = attract_r

    # Frenatura proporzionale se frontale tra BRAKE e STOP
    if dist_f < BRAKE_DIST_CM:
        brake = (dist_f - STOP_DIST_CM) / (BRAKE_DIST_CM - STOP_DIST_CM)
        brake = clamp(brake, 0.0, 1.0)
        if total_x > 0:
            total_x *= brake

    # Normalizza e scala a PWM
    mag = math.hypot(total_x, total_y)
    if mag > 1.0:
        total_x /= mag
        total_y /= mag

    vx = int(clamp(total_x * VEL_MAX, -VEL_MAX, VEL_MAX))
    vy = int(clamp(total_y * VEL_MAX, -VEL_MAX, VEL_MAX))
    vr = int(clamp(total_r * ROT_MAX, -ROT_MAX, ROT_MAX))

    with state_lock:
        state["mode"]   = mode
        state["cmd_vx"] = vx
        state["cmd_vy"] = vy
        state["cmd_vr"] = vr

    return {"vx": vx, "vy": vy, "vr": vr}


# ── LOOP DI CONTROLLO ────────────────────────────────────────────

def control_loop():
    """
    Gira a ~20 Hz, calcola il comando e lo pubblica sull'ESP32.
    """
    RATE_HZ = 20
    period  = 1.0 / RATE_HZ

    while True:
        t0  = time.time()
        cmd = compute_command()

        if mqtt_client and mqtt_client.is_connected():
            mqtt_client.publish(T_MOTORI, json.dumps(cmd))

            with state_lock:
                status = {
                    "ts":     round(time.time(), 3),
                    "mode":   state["mode"],
                    "vx":     cmd["vx"],
                    "vy":     cmd["vy"],
                    "vr":     cmd["vr"],
                    "cliff":  state["cliff"],
                    "goal":   state["goal"],
                }
            mqtt_client.publish(T_STATO, json.dumps(status))

        elapsed = time.time() - t0
        time.sleep(max(0.0, period - elapsed))


# ── MQTT CALLBACKS ───────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[navigator] MQTT connesso a {MQTT_BROKER}")
        for t in [T_ODOMETRIA, T_SENSORI, T_CLIFF, T_GOAL, T_NAV_CMD]:
            client.subscribe(t)
            print(f"  sub: {t}")
    else:
        print(f"[navigator] Connessione fallita rc={rc}")


def on_message(client, userdata, msg):
    global mqtt_client
    try:
        payload = json.loads(msg.payload.decode())
    except Exception:
        # Prova come stringa semplice (per comandi tipo "start")
        payload = msg.payload.decode().strip()

    topic = msg.topic

    if topic == T_ODOMETRIA:
        with state_lock:
            state["pose"]["x"]     = float(payload.get("x", 0))
            state["pose"]["y"]     = float(payload.get("y", 0))
            state["pose"]["theta"] = float(payload.get("theta", 0))

    elif topic == T_SENSORI:
        with state_lock:
            for k in ("FRONTE", "RETRO", "SINISTRA", "DESTRA"):
                if k in payload:
                    state["sensors"][k] = float(payload[k])
            state["last_sensor_ts"] = time.time()

    elif topic == T_CLIFF:
        with state_lock:
            state["cliff"]["cliff_f"] = bool(payload.get("cliff_f", False))
            state["cliff"]["cliff_r"] = bool(payload.get("cliff_r", False))
            # Cliff → stop immediato
            state["cliff_stop"] = state["cliff"]["cliff_f"] or state["cliff"]["cliff_r"]
        if state["cliff_stop"]:
            print(f"[navigator] ⚠️  CLIFF STOP! cliff_f={payload.get('cliff_f')} cliff_r={payload.get('cliff_r')}")

    elif topic == T_GOAL:
        if isinstance(payload, dict) and "x" in payload and "y" in payload:
            with state_lock:
                state["goal"] = {"x": float(payload["x"]), "y": float(payload["y"])}
            print(f"[navigator] Goal impostato: x={payload['x']:.2f} y={payload['y']:.2f}")

    elif topic == T_NAV_CMD:
        cmd = payload if isinstance(payload, str) else payload.get("cmd", "")
        cmd = cmd.lower().strip()
        if cmd == "start":
            with state_lock:
                state["running"] = True
            print("[navigator] START")
        elif cmd == "stop":
            with state_lock:
                state["running"] = False
            client.publish(T_MOTORI, json.dumps({"vx": 0, "vy": 0, "vr": 0}))
            print("[navigator] STOP")
        elif cmd == "reset_goal":
            with state_lock:
                state["goal"] = None
            print("[navigator] Goal resettato")
        elif cmd == "reset_cliff":
            with state_lock:
                state["cliff_stop"] = False
            print("[navigator] Cliff reset manuale")


# ── MAIN ─────────────────────────────────────────────────────────

def main():
    global mqtt_client

    print("=" * 60)
    print(" Navigator — LagmaBills (Potential Field)")
    print("=" * 60)
    print(f" Broker:         {MQTT_BROKER}:{MQTT_PORT}")
    print(f" Comandi start/stop: pubblica su {T_NAV_CMD}")
    print(f" Goal:           pubblica su {T_GOAL}  es: {{\"x\":1.0,\"y\":0.5}}")
    print(f" Cliff soglia:   integrata in occupancyGrid.py")
    print(f" Vel max:        vx/vy={VEL_MAX}  vr={ROT_MAX}")
    print(f" Frena a:        {BRAKE_DIST_CM} cm  |  Stop a: {STOP_DIST_CM} cm")
    print("=" * 60)
    print(" Invia 'start' su robot/nav/cmd per avviare la navigazione.")
    print("=" * 60)

    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="navigator")
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[navigator] Impossibile connettersi: {e}")
        return

    mqtt_client.loop_start()

    ctrl_thread = threading.Thread(target=control_loop, daemon=True)
    ctrl_thread.start()

    try:
        while True:
            time.sleep(1)
            with state_lock:
                m    = state["mode"]
                vx   = state["cmd_vx"]
                vy   = state["cmd_vy"]
                vr   = state["cmd_vr"]
                px   = state["pose"]["x"]
                py   = state["pose"]["y"]
                pt   = math.degrees(state["pose"]["theta"])
                goal = state["goal"]
                run  = state["running"]
            gstr = f"({goal['x']:.2f},{goal['y']:.2f})" if goal else "none"
            print(f"[nav] {'RUN' if run else 'STOP':4} | mode={m:15} | "
                  f"pose=({px:+.2f},{py:+.2f},{pt:+.0f}°) | "
                  f"cmd=({vx:+4},{vy:+4},{vr:+4}) | goal={gstr}")
    except KeyboardInterrupt:
        print("\n[navigator] Interrotto")
        mqtt_client.publish(T_MOTORI, json.dumps({"vx": 0, "vy": 0, "vr": 0}))
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()


if __name__ == "__main__":
    main()