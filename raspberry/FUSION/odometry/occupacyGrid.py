"""
occupancy_grid.py — Stage B (v2, corrected)
LagmaBills — Mappatura locale con 6 HC-SR04

CORREZIONI rispetto alla v1:
  - Nomi sensori allineati al firmware ESP32:
      FRONTE, RETRO, SINISTRA, DESTRA, CLIFF_F, CLIFF_R
  - Unità corretta: l'ESP32 pubblica in CENTIMETRI (uint16_t cm)
    → conversione /100.0 (non /1000.0)
  - CLIFF_F e CLIFF_R NON aggiornano la mappa ostacoli:
    guardano in basso (dirupi/scalini) → layer separato cliff_active
  - Publish aggiuntivo: robot/cliff/stato → {"cliff_f": bool, "cliff_r": bool}
  - Parametri sensore allineati al datasheet HC-SR04:
      range max reale ~3m, non 4m
      timeout già impostato a 300 cm nel firmware → filtra 9999

Topic MQTT in entrata:
  robot/odometria          → {"x": float, "y": float, "theta": float, ...}
  robot/sensori/distanze   → {"FRONTE": cm, "RETRO": cm, "SINISTRA": cm,
                               "DESTRA": cm, "CLIFF_F": cm, "CLIFF_R": cm}
Topic MQTT in uscita:
  robot/mappa/grid         → occupancy grid JSON
  robot/mappa/status       → stato
  robot/cliff/stato        → {"cliff_f": bool, "cliff_r": bool, "ts": float}

Dipendenze: pip install paho-mqtt numpy
"""

import json
import math
import time
import threading
import numpy as np
import paho.mqtt.client as mqtt

# ─── CONFIGURAZIONE ────────────────────────────────────────────────────────────

MQTT_BROKER = "100.100.61.49"
MQTT_PORT   = 1883

# Dimensione mappa
GRID_SIZE_M = 10.0      # metri per lato
CELL_SIZE_M = 0.05      # 5 cm per cella
GRID_CELLS  = int(GRID_SIZE_M / CELL_SIZE_M)  # 200×200

# Log-odds Bayesiano
LOG_OCC_HIT   =  0.85
LOG_OCC_MISS  = -0.40
LOG_OCC_MAX   =  3.5
LOG_OCC_MIN   = -3.5
LOG_OCC_THRES =  0.5

# Soglia cliff: se il sensore cliff legge > questa distanza dal suolo
# significa che NON c'è pavimento → pericolo dirupo.
# Calibra con il robot su pavimento piano (di solito ~5-8 cm)
CLIFF_THRESHOLD_CM = 12.0   # cm — oltre questa = caduta/gradino

# Valore che l'ESP32 manda quando non c'è echo (out-of-range)
SENSOR_INVALID = 9999

# Parametri fisici sensori (per i 4 sensori laterali/frontali)
SENSOR_MIN_CM  = 3.0    # letture sotto → rumore, ignora
SENSOR_MAX_CM  = 300.0  # limite firmware ESP32 (hardcoded a 300 cm)

# ─── GEOMETRIA SENSORI ─────────────────────────────────────────────────────────
#
# Sistema di riferimento robot: X = avanti, Y = sinistra
# Angoli: 0 = avanti, +CCW (right-hand rule)
#
# Il firmware usa:
#   TRIG/ECHO[0] = FRONTE    (anteriore centro)
#   TRIG/ECHO[1] = RETRO     (posteriore centro)
#   TRIG/ECHO[2] = SINISTRA  (laterale sx)
#   TRIG/ECHO[3] = DESTRA    (laterale dx)
#   TRIG/ECHO[4] = CLIFF_F   (cliff anteriore, punta in giù)
#   TRIG/ECHO[5] = CLIFF_R   (cliff posteriore, punta in giù)
#
# I sensori CLIFF non entrano nella mappa ostacoli.

SENSOR_CONFIG = {
    #   nome        offset X (m)  offset Y (m)  angolo assoluto (rad)
    "FRONTE":   {"dx":  0.15, "dy":  0.00, "angle": math.radians(  0)},
    "RETRO":    {"dx": -0.15, "dy":  0.00, "angle": math.radians(180)},
    "SINISTRA": {"dx":  0.00, "dy":  0.15, "angle": math.radians( 90)},
    "DESTRA":   {"dx":  0.00, "dy": -0.15, "angle": math.radians(-90)},
    # CLIFF_F e CLIFF_R esclusi — gestiti separatamente
}

MAP_PUBLISH_INTERVAL = 1.0   # secondi tra aggiornamenti mappa

# ─── STATO GLOBALE ─────────────────────────────────────────────────────────────

grid      = np.zeros((GRID_CELLS, GRID_CELLS), dtype=np.float32)
pose      = {"x": 0.0, "y": 0.0, "theta": 0.0}
cliff     = {"cliff_f": False, "cliff_r": False}

# Ultimi valori grezzi dei sensori (per publish al viewer)
sensor_raw = {k: SENSOR_INVALID for k in list(SENSOR_CONFIG.keys()) + ["CLIFF_F", "CLIFF_R"]}

pose_lock   = threading.Lock()
grid_lock   = threading.Lock()
cliff_lock  = threading.Lock()

# ─── UTILITY GRIGLIA ───────────────────────────────────────────────────────────

def world_to_cell(wx: float, wy: float):
    cx = int((wx + GRID_SIZE_M / 2) / CELL_SIZE_M)
    cy = int((wy + GRID_SIZE_M / 2) / CELL_SIZE_M)
    if 0 <= cx < GRID_CELLS and 0 <= cy < GRID_CELLS:
        return cx, cy
    return None


def bresenham_line(x0, y0, x1, y1):
    cells = []
    dx = abs(x1 - x0); dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    x, y = x0, y0
    while True:
        cells.append((x, y))
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 > -dy: err -= dy; x += sx
        if e2 <  dx: err += dx; y += sy
    return cells


def update_grid_with_reading(robot_x, robot_y, robot_theta, sensor_name, distance_cm):
    """
    Aggiorna la occupancy grid con una lettura HC-SR04.
    distance_cm: già in centimetri, come arriva dall'ESP32.
    """
    if distance_cm == SENSOR_INVALID:
        return
    if distance_cm < SENSOR_MIN_CM or distance_cm > SENSOR_MAX_CM:
        return

    cfg = SENSOR_CONFIG[sensor_name]
    distance_m = distance_cm / 100.0

    cos_t = math.cos(robot_theta)
    sin_t = math.sin(robot_theta)

    # Posizione sensore in world frame
    sx = robot_x + cos_t * cfg["dx"] - sin_t * cfg["dy"]
    sy = robot_y + sin_t * cfg["dx"] + cos_t * cfg["dy"]

    abs_angle = robot_theta + cfg["angle"]

    # Punto finale raggio
    ex = sx + math.cos(abs_angle) * distance_m
    ey = sy + math.sin(abs_angle) * distance_m

    src = world_to_cell(sx, sy)
    end = world_to_cell(ex, ey)

    if src is None:
        return

    with grid_lock:
        if end is not None:
            ray = bresenham_line(src[0], src[1], end[0], end[1])
            # Celle libere (esclusa l'ultima)
            for cx, cy in ray[:-1]:
                grid[cx, cy] = max(LOG_OCC_MIN, grid[cx, cy] + LOG_OCC_MISS)
            # Cella occupata
            grid[end[0], end[1]] = min(LOG_OCC_MAX, grid[end[0], end[1]] + LOG_OCC_HIT)
        else:
            # Fine raggio fuori griglia → marca solo celle libere interne
            # Clamp end al bordo della griglia
            end_x = sx + math.cos(abs_angle) * GRID_SIZE_M
            end_y = sy + math.sin(abs_angle) * GRID_SIZE_M
            clamped = world_to_cell(end_x, end_y)
            if clamped:
                ray = bresenham_line(src[0], src[1], clamped[0], clamped[1])
                for cx, cy in ray:
                    grid[cx, cy] = max(LOG_OCC_MIN, grid[cx, cy] + LOG_OCC_MISS)


def update_cliff(cliff_f_cm, cliff_r_cm):
    """
    Aggiorna lo stato cliff.
    I sensori puntano verso il basso: se la distanza letta è MAGGIORE
    della soglia, il pavimento non è lì → pericolo.
    """
    with cliff_lock:
        # Ignora letture invalide (mantieni stato precedente)
        if cliff_f_cm != SENSOR_INVALID:
            cliff["cliff_f"] = (cliff_f_cm > CLIFF_THRESHOLD_CM)
        if cliff_r_cm != SENSOR_INVALID:
            cliff["cliff_r"] = (cliff_r_cm > CLIFF_THRESHOLD_CM)


def grid_to_dict() -> dict:
    with grid_lock:
        quantized = np.zeros_like(grid, dtype=np.int8)
        quantized[grid >  LOG_OCC_THRES] =  1
        quantized[grid < -LOG_OCC_THRES] = -1

    with pose_lock:
        robot_cell = world_to_cell(pose["x"], pose["y"])
        theta = pose["theta"]

    with cliff_lock:
        cliff_snap = dict(cliff)

    with threading.Lock():
        sensors_snap = dict(sensor_raw)

    return {
        "ts":          time.time(),
        "size":        GRID_CELLS,
        "cell_m":      CELL_SIZE_M,
        "grid_m":      GRID_SIZE_M,
        "robot_cell":  list(robot_cell) if robot_cell else [GRID_CELLS // 2, GRID_CELLS // 2],
        "robot_theta": theta,
        "occupied":    [[int(x), int(y)] for x, y in zip(*np.where(quantized ==  1))],
        "free":        [[int(x), int(y)] for x, y in zip(*np.where(quantized == -1))],
        "cliff":       cliff_snap,
        "sensors":     sensors_snap,   # distanze grezze in cm per il viewer
    }

# ─── CALLBACK MQTT ─────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("[MQTT] Connesso al broker")
        client.subscribe("robot/odometria")
        client.subscribe("robot/sensori/distanze")
        client.subscribe("robot/mappa/get")
    else:
        print(f"[MQTT] Errore connessione: rc={rc}")


def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
    except Exception as e:
        print(f"[MQTT] Payload non valido su {msg.topic}: {e}")
        return

    if msg.topic == "robot/odometria":
        with pose_lock:
            pose["x"]     = float(payload.get("x", 0))
            pose["y"]     = float(payload.get("y", 0))
            pose["theta"] = float(payload.get("theta", 0))

    elif msg.topic == "robot/sensori/distanze":
        with pose_lock:
            rx, ry, rt = pose["x"], pose["y"], pose["theta"]

        # Aggiorna mappa ostacoli (solo i 4 sensori laterali)
        for name in SENSOR_CONFIG:
            raw = payload.get(name)
            if raw is None:
                continue
            val = float(raw)
            sensor_raw[name] = val
            # distanza già in cm dall'ESP32
            update_grid_with_reading(rx, ry, rt, name, val)

        # Gestisci cliff separatamente
        cf = float(payload.get("CLIFF_F", SENSOR_INVALID))
        cr = float(payload.get("CLIFF_R", SENSOR_INVALID))
        sensor_raw["CLIFF_F"] = cf
        sensor_raw["CLIFF_R"] = cr
        update_cliff(cf, cr)

        # Pubblica stato cliff immediatamente
        with cliff_lock:
            cliff_payload = {
                "cliff_f": cliff["cliff_f"],
                "cliff_r": cliff["cliff_r"],
                "cf_cm":   cf if cf != SENSOR_INVALID else -1,
                "cr_cm":   cr if cr != SENSOR_INVALID else -1,
                "ts":      time.time(),
            }
        client.publish("robot/cliff/stato", json.dumps(cliff_payload))

    elif msg.topic == "robot/mappa/get":
        client.publish("robot/mappa/grid", json.dumps(grid_to_dict()))

# ─── PUBLISHER PERIODICO ───────────────────────────────────────────────────────

def periodic_publish(client: mqtt.Client):
    while True:
        time.sleep(MAP_PUBLISH_INTERVAL)
        data = grid_to_dict()
        client.publish("robot/mappa/grid", json.dumps(data))

        with cliff_lock:
            cf_str = "⚠️ CLIFF!" if cliff["cliff_f"] or cliff["cliff_r"] else "OK"
        print(f"[MAPPA] occ={len(data['occupied'])} free={len(data['free'])} "
              f"| FRONTE={sensor_raw['FRONTE']}cm RETRO={sensor_raw['RETRO']}cm "
              f"SX={sensor_raw['SINISTRA']}cm DX={sensor_raw['DESTRA']}cm "
              f"| Cliff: {cf_str}")

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=== LagmaBills — Occupancy Grid v2 ===")
    print(f"Griglia: {GRID_CELLS}×{GRID_CELLS} celle ({GRID_SIZE_M}m × {GRID_SIZE_M}m @ {CELL_SIZE_M*100:.0f}cm/cella)")
    print(f"Soglia cliff: {CLIFF_THRESHOLD_CM} cm")
    print(f"Sensori mappa: {list(SENSOR_CONFIG.keys())}")
    print(f"Sensori cliff: CLIFF_F, CLIFF_R (layer separato)")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    pub_thread = threading.Thread(target=periodic_publish, args=(client,), daemon=True)
    pub_thread.start()

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Interruzione — chiusura.")
        client.disconnect()


if __name__ == "__main__":
    main()
