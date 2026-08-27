#!/usr/bin/env python3
"""
================================================================
 ODOMETRIA MECANUM — Brochiachio / LagmaBills
 Calcola la posa (x, y, theta) del robot dai tick encoder
 pubblicati da PCBmotori su MQTT.

 Subscribe: robot/motori/stato
 Publish:   robot/odometria

 Formato publish (robot/odometria):
   {
     "x": 0.123,        # metri, origine al punto di avvio
     "y": -0.045,       # metri
     "theta": 1.57,     # radianti, +CCW (antiorario)
     "vx": 0.10,        # m/s, velocità istantanea in avanti
     "vy": -0.02,       # m/s, velocità istantanea laterale
     "omega": 0.0,      # rad/s, velocità angolare
     "ts": 1710000000.0 # timestamp unix
   }

================================================================
 PARAMETRI DA CALIBRARE (sostituisci con le misure reali):

   TICKS_PER_REV  →  conta i tick su un giro completo di ruota
                     fermo il robot, segni la ruota, giri a mano
                     di 360° e leggi l'encoder dal seriale

   WHEEL_DIAM_M   →  diametro ruota in metri (già noto: 97mm)

   L_LAT_M        →  semidistanza laterale tra centro ruota sx
                     e centro ruota dx (metà dell'interasse laterale)

   L_LON_M        →  semidistanza longitudinale tra asse anteriore
                     e asse posteriore

 Nota Mecanum X-configuration:
   FL = vy + vx + vr * (L_LAT + L_LON)
   FR = vy - vx - vr * (L_LAT + L_LON)
   RL = vy - vx + vr * (L_LAT + L_LON)
   RR = vy + vx - vr * (L_LAT + L_LON)

 Cinematica inversa (da tick a velocità):
   vx    = (FL - FR - RL + RR) / 4
   vy    = (FL + FR + RL + RR) / 4
   omega = (-FL + FR - RL + RR) / (4 * (L_LAT + L_LON))
   (tutti in unità di tick/s, poi convertiti in m/s e rad/s)
================================================================
"""

import json
import math
import time
import paho.mqtt.client as mqtt

# ── PARAMETRI FISICI ─────────────────────────────────────────────
# Questi sono i valori da calibrare. Finché non hai le misure reali
# usa questi placeholder: la struttura del codice è corretta, i
# valori numerici saranno approssimativi.

TICKS_PER_REV = 374          # tick per giro ruota (stima: 11 * 34)
                              # VERIFICA: gira la ruota a mano di 360°
                              # e conta i tick sul seriale PCBmotori

WHEEL_DIAM_M  = 0.097        # 97mm — già confermato

# Placeholder — misura quando il robot è assemblato:
#   L_LAT_M = distanza tra centro ruota SX e mezzeria robot (m)
#   L_LON_M = distanza tra asse anteriore e mezzeria robot (m)
L_LAT_M = 0.100              # PLACEHOLDER — misura l'interasse laterale / 2
L_LON_M = 0.090              # PLACEHOLDER — misura il passo longitudinale / 2

# ── MQTT ─────────────────────────────────────────────────────────
MQTT_BROKER   = "LagmaBills.local"   # o IP 192.168.1.x
MQTT_PORT     = 1883
TOPIC_SUB     = "robot/motori/stato"
TOPIC_PUB     = "robot/odometria"
CLIENT_ID     = "odometria"

# ── COSTANTI DERIVATE ────────────────────────────────────────────
WHEEL_CIRC_M  = math.pi * WHEEL_DIAM_M          # circonferenza ruota
M_PER_TICK    = WHEEL_CIRC_M / TICKS_PER_REV    # metri per tick
L_SUM         = L_LAT_M + L_LON_M               # (l + w) per cinematica

# ── STATO GLOBALE ────────────────────────────────────────────────
pose = {"x": 0.0, "y": 0.0, "theta": 0.0}

prev_ticks = {"fl": None, "fr": None, "rl": None, "rr": None}
prev_time  = None


def reset_pose():
    """Azzera la posa — chiama quando vuoi un nuovo punto di origine."""
    global pose, prev_ticks, prev_time
    pose = {"x": 0.0, "y": 0.0, "theta": 0.0}
    prev_ticks = {"fl": None, "fr": None, "rl": None, "rr": None}
    prev_time = None
    print("[odometria] Posa azzerata")


def update_pose(fl, fr, rl, rr, now):
    """
    Aggiorna la posa con i tick correnti dei 4 encoder.
    Cinematica Mecanum X-config (right-hand rule, +x avanti, +y sinistra).
    """
    global pose, prev_ticks, prev_time

    # Prima lettura — inizializza senza integrare
    if prev_ticks["fl"] is None:
        prev_ticks = {"fl": fl, "fr": fr, "rl": rl, "rr": rr}
        prev_time  = now
        return None

    dt = now - prev_time
    if dt <= 0:
        return None

    # Delta tick per ogni ruota
    d_fl = fl - prev_ticks["fl"]
    d_fr = fr - prev_ticks["fr"]
    d_rl = rl - prev_ticks["rl"]
    d_rr = rr - prev_ticks["rr"]

    prev_ticks = {"fl": fl, "fr": fr, "rl": rl, "rr": rr}
    prev_time  = now

    # Velocità locale in tick/s
    v_fl = d_fl / dt
    v_fr = d_fr / dt
    v_rl = d_rl / dt
    v_rr = d_rr / dt

    # Cinematica inversa Mecanum → velocità del robot in frame locale
    # (unità: tick/s, poi converti)
    vx_tps    = ( v_fl - v_fr - v_rl + v_rr) / 4.0
    vy_tps    = ( v_fl + v_fr + v_rl + v_rr) / 4.0
    omega_tps = (-v_fl + v_fr - v_rl + v_rr) / (4.0 * L_SUM / M_PER_TICK)

    # Converti in m/s e rad/s
    vx_ms    = vx_tps * M_PER_TICK
    vy_ms    = vy_tps * M_PER_TICK
    omega_rs = omega_tps * M_PER_TICK  # già rad/s perché L_SUM è in m

    # Integrazione della posa in frame globale (Eulero forward)
    theta = pose["theta"]
    dx_global =  vx_ms * math.cos(theta) - vy_ms * math.sin(theta)
    dy_global =  vx_ms * math.sin(theta) + vy_ms * math.cos(theta)

    pose["x"]     += dx_global * dt
    pose["y"]     += dy_global * dt
    pose["theta"] += omega_rs  * dt

    # Normalizza theta in [-pi, pi]
    pose["theta"] = math.atan2(
        math.sin(pose["theta"]),
        math.cos(pose["theta"])
    )

    return {
        "x":     round(pose["x"],     4),
        "y":     round(pose["y"],     4),
        "theta": round(pose["theta"], 4),
        "vx":    round(vx_ms,         4),
        "vy":    round(vy_ms,         4),
        "omega": round(omega_rs,      4),
        "ts":    round(now,           3)
    }


# ── MQTT CALLBACKS ───────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[odometria] MQTT connesso a {MQTT_BROKER}")
        client.subscribe(TOPIC_SUB)
        print(f"[odometria] Subscribed a {TOPIC_SUB}")
    else:
        print(f"[odometria] Connessione MQTT fallita, rc={rc}")


def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        return

    # Valida che tutti i campi encoder siano presenti
    for key in ("fl", "fr", "rl", "rr"):
        if key not in data:
            return

    now = time.time()
    result = update_pose(
        data["fl"], data["fr"],
        data["rl"], data["rr"],
        now
    )

    if result is None:
        return

    payload = json.dumps(result)
    client.publish(TOPIC_PUB, payload)

    # Debug seriale
    print(
        f"x={result['x']:+.3f}m  y={result['y']:+.3f}m  "
        f"θ={math.degrees(result['theta']):+.1f}°  "
        f"vx={result['vx']:+.3f}m/s  vy={result['vy']:+.3f}m/s  "
        f"ω={result['omega']:+.3f}rad/s"
    )


def on_disconnect(client, userdata, rc):
    print(f"[odometria] MQTT disconnesso (rc={rc}), riconnessione...")


# ── MAIN ─────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print(" Odometria Mecanum — Brochiachio")
    print("=" * 60)
    print(f" Broker:         {MQTT_BROKER}:{MQTT_PORT}")
    print(f" Subscribe:      {TOPIC_SUB}")
    print(f" Publish:        {TOPIC_PUB}")
    print(f" Ruota:          ø{WHEEL_DIAM_M*1000:.0f}mm  "
          f"{M_PER_TICK*1000:.3f}mm/tick")
    print(f" Ticks/giro:     {TICKS_PER_REV}  (VERIFICA con encoder fisico)")
    print(f" L_lat:          {L_LAT_M*1000:.0f}mm  (PLACEHOLDER)")
    print(f" L_lon:          {L_LON_M*1000:.0f}mm  (PLACEHOLDER)")
    print("=" * 60)
    print(" NOTA: i valori PLACEHOLDER devono essere misurati sul")
    print(" robot assemblato prima di usare i dati per la mappa.")
    print("=" * 60)

    client = mqtt.Client(client_id=CLIENT_ID)
    client.on_connect    = on_connect
    client.on_message    = on_message
    client.on_disconnect = on_disconnect

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[odometria] Impossibile connettersi: {e}")
        print("  Verifica che il broker Mosquitto sia attivo su LagmaBills")
        return

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[odometria] Interrotto")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()