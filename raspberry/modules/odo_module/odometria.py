#!/usr/bin/env python3
"""
odometria.py — LagmaBills
Calcola la posa (x, y, theta) dai tick encoder pubblicati da PCBmotori.

CORREZIONI rispetto a provaCodiceMappatura.py:
  - Formula omega corretta: non mescolava tick e metri.
    La conversione M_PER_TICK va applicata DOPO aver calcolato omega,
    non dentro il divisore della formula angolare.
  - Aggiunto on_connect con CallbackAPIVersion.VERSION2
  - Aggiunto subscribe a robot/odometria/reset per azzerare la posa
    senza riavviare il processo

Subscribe:  robot/motori/stato
Publish:    robot/odometria

Formato motori/stato (dall'ESP32):
  {"fl": int, "fr": int, "rl": int, "rr": int}   ← tick assoluti encoder
"""

import json
import math
import time
import paho.mqtt.client as mqtt

# ── PARAMETRI FISICI ─────────────────────────────────────────────
# TICKS_PER_REV: verifica girando la ruota a mano di 360° e leggendo
# l'encoder. Con JGA25-370 + rapporto 1:34 e encoder 11 ppr →
# 11 × 34 = 374 tick/giro (quadratura: ×2 se conti solo un fronte,
# ×4 se conti entrambi i fronti di A e B).
# Il firmware attuale conta su CHANGE (entrambi i fronti di A e B) →
# 11 × 34 × 2 = 748 oppure 11 × 34 × 4 = 1496 a seconda del motore.
# Misura fisicamente e sostituisci.
TICKS_PER_REV = 748           # VERIFICA con encoder fisico

WHEEL_DIAM_M  = 0.097         # 97 mm — già confermato

# Misura sul robot assemblato:
#   L_LAT_M = metà interasse laterale (da centro robot a centro ruota sx o dx)
#   L_LON_M = metà passo longitudinale (da centro robot a asse ant o post)
L_LAT_M = 0.100               # PLACEHOLDER — misura l'interasse laterale / 2
L_LON_M = 0.090               # PLACEHOLDER — misura il passo longitudinale / 2

# ── MQTT ─────────────────────────────────────────────────────────
MQTT_BROKER = "100.100.61.49"     # su Raspberry Pi gira il broker locale
MQTT_PORT   = 1883
TOPIC_SUB   = "robot/motori/stato"
TOPIC_PUB   = "robot/odometria"
TOPIC_RESET = "robot/odometria/reset"
CLIENT_ID   = "odometria"

# ── COSTANTI DERIVATE ────────────────────────────────────────────
WHEEL_CIRC_M = math.pi * WHEEL_DIAM_M
M_PER_TICK   = WHEEL_CIRC_M / TICKS_PER_REV
L_SUM        = L_LAT_M + L_LON_M   # (l_lat + l_lon) in metri

# ── STATO ────────────────────────────────────────────────────────
pose       = {"x": 0.0, "y": 0.0, "theta": 0.0}
prev_ticks = {"fl": None, "fr": None, "rl": None, "rr": None}
prev_time  = None


def reset_pose():
    global pose, prev_ticks, prev_time
    pose       = {"x": 0.0, "y": 0.0, "theta": 0.0}
    prev_ticks = {"fl": None, "fr": None, "rl": None, "rr": None}
    prev_time  = None
    print("[odometria] Posa azzerata")


def update_pose(fl, fr, rl, rr, now):
    """
    Cinematica inversa Mecanum X-config.

    Convenzione segni (right-hand, X=avanti, Y=sinistra):
      vx    = ( FL - FR - RL + RR) / 4         forward
      vy    = ( FL + FR + RL + RR) / 4         strafe
      omega = (-FL + FR - RL + RR) / (4 * L_SUM / M_PER_TICK)

    Nota sulla formula omega:
      Le velocità v_XX sono in tick/s.
      La formula geometrica da cinematica Mecanum dà:
        omega [tick/s / (m/tick)] = omega_tps * M_PER_TICK / L_SUM
      che è già in rad/s perché M_PER_TICK/L_SUM è adimensionale
      (m/tick ÷ m = 1/tick cancellato dai tick/s → rad/s).
    """
    global pose, prev_ticks, prev_time

    if prev_ticks["fl"] is None:
        prev_ticks = {"fl": fl, "fr": fr, "rl": rl, "rr": rr}
        prev_time  = now
        return None

    dt = now - prev_time
    if dt <= 0:
        return None

    d_fl = fl - prev_ticks["fl"]
    d_fr = fr - prev_ticks["fr"]
    d_rl = rl - prev_ticks["rl"]
    d_rr = rr - prev_ticks["rr"]

    prev_ticks = {"fl": fl, "fr": fr, "rl": rl, "rr": rr}
    prev_time  = now

    # Velocità in tick/s
    v_fl = d_fl / dt
    v_fr = d_fr / dt
    v_rl = d_rl / dt
    v_rr = d_rr / dt

    # Cinematica inversa → velocità locali in tick/s
    vx_tps    = ( v_fl - v_fr - v_rl + v_rr) / 4.0
    vy_tps    = ( v_fl + v_fr + v_rl + v_rr) / 4.0
    # omega: tick/s → rad/s
    # Il divisore è il raggio cinematico espresso in tick/m
    omega_rs  = (-v_fl + v_fr - v_rl + v_rr) * M_PER_TICK / (4.0 * L_SUM)

    # Converti vx, vy in m/s
    vx_ms = vx_tps * M_PER_TICK
    vy_ms = vy_tps * M_PER_TICK

    # Integrazione Eulero forward in world frame
    theta = pose["theta"]
    pose["x"]     += (vx_ms * math.cos(theta) - vy_ms * math.sin(theta)) * dt
    pose["y"]     += (vx_ms * math.sin(theta) + vy_ms * math.cos(theta)) * dt
    pose["theta"] += omega_rs * dt
    pose["theta"]  = math.atan2(math.sin(pose["theta"]), math.cos(pose["theta"]))

    return {
        "x":     round(pose["x"],     4),
        "y":     round(pose["y"],     4),
        "theta": round(pose["theta"], 4),
        "vx":    round(vx_ms,         4),
        "vy":    round(vy_ms,         4),
        "omega": round(omega_rs,      4),
        "ts":    round(now,           3),
    }


# ── MQTT CALLBACKS ───────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[odometria] MQTT connesso a {MQTT_BROKER}")
        client.subscribe(TOPIC_SUB)
        client.subscribe(TOPIC_RESET)
        print(f"[odometria] Subscribed: {TOPIC_SUB}, {TOPIC_RESET}")
    else:
        print(f"[odometria] Connessione MQTT fallita, rc={rc}")


def on_message(client, userdata, msg):
    if msg.topic == TOPIC_RESET:
        reset_pose()
        return

    try:
        data = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        return

    for key in ("fl", "fr", "rl", "rr"):
        if key not in data:
            print(f"[odometria] Campo mancante: {key}")
            return

    now    = time.time()
    result = update_pose(data["fl"], data["fr"], data["rl"], data["rr"], now)

    if result is None:
        return

    client.publish(TOPIC_PUB, json.dumps(result))
    print(
        f"x={result['x']:+.3f}m  y={result['y']:+.3f}m  "
        f"θ={math.degrees(result['theta']):+.1f}°  "
        f"vx={result['vx']:+.3f}m/s  vy={result['vy']:+.3f}m/s  "
        f"ω={result['omega']:+.4f}rad/s"
    )


def on_disconnect(client, userdata, rc, properties=None):
    print(f"[odometria] MQTT disconnesso (rc={rc})")


# ── MAIN ─────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print(" Odometria Mecanum — LagmaBills (v2, corrected)")
    print("=" * 60)
    print(f" Broker:         {MQTT_BROKER}:{MQTT_PORT}")
    print(f" Subscribe:      {TOPIC_SUB}")
    print(f" Publish:        {TOPIC_PUB}")
    print(f" Ruota:          ø{WHEEL_DIAM_M*1000:.0f}mm  {M_PER_TICK*1000:.3f}mm/tick")
    print(f" Ticks/giro:     {TICKS_PER_REV}  (verifica con encoder fisico!)")
    print(f" L_lat:          {L_LAT_M*1000:.0f}mm  (placeholder)")
    print(f" L_lon:          {L_LON_M*1000:.0f}mm  (placeholder)")
    print(f" L_sum:          {L_SUM*1000:.0f}mm")
    print("=" * 60)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[odometria] Impossibile connettersi: {e}")
        return

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[odometria] Interrotto")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()