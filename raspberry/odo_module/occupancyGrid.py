"""
occupancy_grid.py — Stage B
Brochiachio Mecanum Robot — Local mapping con 6 HC-SR04

Costruisce una occupancy grid 200×200 celle (10m×10m @ 5cm/cella)
aggiornando le celle libere e occupate in base ai sensori ultrasuoni
e alla posa stimata dall'odometria.

Topic MQTT in entrata:
  robot/odometria      → {"x": float, "y": float, "theta": float}
  robot/sensori/distanze → {"FL": mm, "FR": mm, "L": mm, "R": mm, "BL": mm, "BR": mm}

Topic MQTT in uscita:
  robot/mappa/grid     → JSON con la griglia (su richiesta o ogni MAP_PUBLISH_INTERVAL s)
  robot/mappa/status   → stato corrente della mappa

Dipendenze:
  pip install paho-mqtt numpy

Autore: LagmaBills / Brochiachio project
"""

import json
import math
import time
import threading
import numpy as np
import paho.mqtt.client as mqtt

# ─── CONFIGURAZIONE ────────────────────────────────────────────────────────────

MQTT_BROKER   = "localhost"
MQTT_PORT     = 1883

# Dimensione mappa
GRID_SIZE_M   = 10.0     # metri per lato
CELL_SIZE_M   = 0.05     # 5 cm per cella
GRID_CELLS    = int(GRID_SIZE_M / CELL_SIZE_M)  # 200×200

# Valori log-odds per aggiornamento Bayesiano
LOG_OCC_HIT   =  0.85    # aggiunto quando cella è occupata
LOG_OCC_MISS  = -0.40    # sottratto quando cella è libera (raggio libero)
LOG_OCC_MAX   =  3.5     # clamp massimo
LOG_OCC_MIN   = -3.5     # clamp minimo
LOG_OCC_THRES =  0.5     # soglia per considerare cella "occupata" nella visualizzazione

# Geometria sensori ultrasuoni (x, y in metri, angolo in radianti)
# Origine = centro robot, X = avanti, Y = sinistra
# Ordine: FL, FR, L, R, BL, BR
SENSOR_CONFIG = {
    "FL": {"dx":  0.12, "dy":  0.10, "angle": math.radians( 45)},
    "FR": {"dx":  0.12, "dy": -0.10, "angle": math.radians(-45)},
    "L":  {"dx":  0.00, "dy":  0.12, "angle": math.radians( 90)},
    "R":  {"dx":  0.00, "dy": -0.12, "angle": math.radians(-90)},
    "BL": {"dx": -0.12, "dy":  0.10, "angle": math.radians(135)},
    "BR": {"dx": -0.12, "dy": -0.10, "angle": math.radians(-135)},
}

# Parametri sensore HC-SR04
SENSOR_MIN_M  = 0.02     # 2 cm — letture sotto questo valore → ignora
SENSOR_MAX_M  = 4.00     # 4 m  — letture sopra questo valore → ignora (fuori range)
SENSOR_BEAM_HALF_ANGLE = math.radians(7.5)  # metà angolo apertura ~15°

# Quanto spesso pubblicare la mappa completa (secondi)
MAP_PUBLISH_INTERVAL = 2.0

# ─── STATO GLOBALE ─────────────────────────────────────────────────────────────

grid = np.zeros((GRID_CELLS, GRID_CELLS), dtype=np.float32)  # log-odds
pose = {"x": 0.0, "y": 0.0, "theta": 0.0}
pose_lock = threading.Lock()
grid_lock  = threading.Lock()

# ─── FUNZIONI GRIGLIA ──────────────────────────────────────────────────────────

def world_to_cell(wx: float, wy: float) -> tuple[int, int] | None:
    """Converte coordinate mondo (m) in indice cella. None se fuori griglia."""
    cx = int((wx + GRID_SIZE_M / 2) / CELL_SIZE_M)
    cy = int((wy + GRID_SIZE_M / 2) / CELL_SIZE_M)
    if 0 <= cx < GRID_CELLS and 0 <= cy < GRID_CELLS:
        return cx, cy
    return None


def bresenham_line(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Restituisce tutte le celle lungo la linea da (x0,y0) a (x1,y1)."""
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
        if e2 > -dy:
            err -= dy; x += sx
        if e2 < dx:
            err += dx; y += sy
    return cells


def update_grid_with_reading(robot_x: float, robot_y: float, robot_theta: float,
                               sensor_name: str, distance_m: float):
    """
    Aggiorna la occupancy grid con una lettura singola di un sensore ultrasuono.
    Usa un modello log-odds semplificato:
      - celle lungo il raggio → libere (miss)
      - cella al termine del raggio → occupata (hit)
    """
    if distance_m < SENSOR_MIN_M or distance_m > SENSOR_MAX_M:
        return

    cfg = SENSOR_CONFIG[sensor_name]

    # Posizione del sensore in coordinate mondo
    cos_t = math.cos(robot_theta)
    sin_t = math.sin(robot_theta)
    sx = robot_x + cos_t * cfg["dx"] - sin_t * cfg["dy"]
    sy = robot_y + sin_t * cfg["dx"] + cos_t * cfg["dy"]

    # Angolo assoluto del sensore
    abs_angle = robot_theta + cfg["angle"]

    # Punto finale del raggio (cella occupata)
    ex = sx + math.cos(abs_angle) * distance_m
    ey = sy + math.sin(abs_angle) * distance_m

    src = world_to_cell(sx, sy)
    end = world_to_cell(ex, ey)
    if src is None:
        return

    with grid_lock:
        if end is not None:
            # Celle libere lungo il raggio
            ray_cells = bresenham_line(src[0], src[1], end[0], end[1])
            for cx, cy in ray_cells[:-1]:  # escludi ultima (sarà hit)
                grid[cx, cy] = max(LOG_OCC_MIN, grid[cx, cy] + LOG_OCC_MISS)

            # Cella terminale → occupata
            grid[end[0], end[1]] = min(LOG_OCC_MAX, grid[end[0], end[1]] + LOG_OCC_HIT)
        else:
            # Fuori griglia: marca solo le celle libere interne
            ray_cells = bresenham_line(src[0], src[1],
                                        *world_to_cell(
                                            sx + math.cos(abs_angle) * (GRID_SIZE_M / 2),
                                            sy + math.sin(abs_angle) * (GRID_SIZE_M / 2)
                                        ) if world_to_cell(
                                            sx + math.cos(abs_angle) * (GRID_SIZE_M / 2),
                                            sy + math.sin(abs_angle) * (GRID_SIZE_M / 2)
                                        ) else (src[0], src[1]))
            for cx, cy in ray_cells:
                grid[cx, cy] = max(LOG_OCC_MIN, grid[cx, cy] + LOG_OCC_MISS)


def grid_to_dict() -> dict:
    """Serializza la griglia in formato leggero per MQTT/JSON."""
    with grid_lock:
        # Quantizza: -1=libera, 0=sconosciuta, 1=occupata
        quantized = np.zeros_like(grid, dtype=np.int8)
        quantized[grid >  LOG_OCC_THRES] =  1
        quantized[grid < -LOG_OCC_THRES] = -1

    with pose_lock:
        robot_cell = world_to_cell(pose["x"], pose["y"])

    return {
        "ts": time.time(),
        "size": GRID_CELLS,
        "cell_m": CELL_SIZE_M,
        "grid_m": GRID_SIZE_M,
        "robot_cell": list(robot_cell) if robot_cell else [GRID_CELLS//2, GRID_CELLS//2],
        "robot_theta": pose["theta"],
        # Comprimi la griglia: lista di celle occupate e libere (risparmia banda)
        "occupied": [[int(x), int(y)]
                     for x, y in zip(*np.where(quantized == 1))],
        "free":     [[int(x), int(y)]
                     for x, y in zip(*np.where(quantized == -1))],
    }

# ─── CALLBACK MQTT ─────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("[MQTT] Connesso al broker")
        client.subscribe("robot/odometria")
        client.subscribe("robot/sensori/distanze")
        client.subscribe("robot/mappa/get")  # richiesta snapshot on-demand
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

        for sensor_name in SENSOR_CONFIG:
            raw = payload.get(sensor_name)
            if raw is None:
                continue
            # I valori dal PCBsens arrivano in mm → converti in metri
            dist_m = float(raw) / 1000.0
            update_grid_with_reading(rx, ry, rt, sensor_name, dist_m)

    elif msg.topic == "robot/mappa/get":
        # Risponde con uno snapshot immediato
        client.publish("robot/mappa/grid", json.dumps(grid_to_dict()))

# ─── PUBLISHER PERIODICO ───────────────────────────────────────────────────────

def periodic_publish(client: mqtt.Client):
    """Pubblica la mappa ogni MAP_PUBLISH_INTERVAL secondi."""
    while True:
        time.sleep(MAP_PUBLISH_INTERVAL)
        data = grid_to_dict()
        client.publish("robot/mappa/grid", json.dumps(data))
        occ_count = len(data["occupied"])
        free_count = len(data["free"])
        print(f"[MAPPA] Aggiornata — occupate: {occ_count}, libere: {free_count}")

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print("=== Brochiachio — Occupancy Grid ===")
    print(f"Griglia: {GRID_CELLS}×{GRID_CELLS} celle ({GRID_SIZE_M}m × {GRID_SIZE_M}m @ {CELL_SIZE_M*100:.0f}cm)")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)

    # Publisher periodico in thread separato
    pub_thread = threading.Thread(target=periodic_publish, args=(client,), daemon=True)
    pub_thread.start()

    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\n[INFO] Interruzione utente — chiusura.")
        client.disconnect()


if __name__ == "__main__":
    main()