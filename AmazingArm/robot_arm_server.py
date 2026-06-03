#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║          Robot Arm - Raspberry Pi Controller                 ║
║  Server REST + I2C master verso ESP32                        ║
╚══════════════════════════════════════════════════════════════╝

Dipendenze:
    pip install flask flask-cors smbus2

Avvio:
    python3 robot_arm_server.py

Endpoint REST:
    GET  /status                      → stato corrente servo
    POST /servo/<id>                  → muovi servo singolo  { "angle": 90 }
    POST /move_all                    → muovi tutti          { "angles": [90,150,35,140,85,80] }
    POST /home                        → vai a HOME
    POST /speed                       → imposta velocità     { "speed": 50 }
    POST /save_step                   → salva posizione corrente
    POST /run_sequence                → esegui sequenza
    POST /reset_sequence              → reset sequenza
    GET  /sequence                    → lista step salvati
    POST /preset/<name>               → esegui preset (pick, place, wave…)
"""

import time
import json
import threading
from flask import Flask, request, jsonify
from flask_cors import CORS

try:
    import smbus2
    I2C_AVAILABLE = True
except ImportError:
    print("⚠  smbus2 non disponibile - modalità simulazione")
    I2C_AVAILABLE = False

# ──────────────────────────────────────────
#  Configurazione
# ──────────────────────────────────────────
ESP32_I2C_ADDR = 0x08
I2C_BUS        = 1          # /dev/i2c-1 su RPi
SERVER_PORT    = 5000

# Limiti servo [min, max, home]
SERVO_LIMITS = [
    (0,   180,  90),   # 0: Base/Waist
    (30,  170, 150),   # 1: Spalla
    (0,   150,  35),   # 2: Gomito
    (0,   180, 140),   # 3: Polso Pitch
    (0,   180,  85),   # 4: Polso Roll
    (20,  160,  80),   # 5: Gripper
]

SERVO_NAMES = ["Base", "Spalla", "Gomito", "Polso Pitch", "Polso Roll", "Gripper"]

# Preset di posizioni utili
PRESETS = {
    "home":        [90, 150, 35, 140, 85, 80],
    "pick_ready":  [90, 120, 80, 110, 85, 20],   # braccio esteso verso il basso
    "pick_open":   [90, 120, 80, 110, 85, 20],   # pinza aperta
    "pick_close":  [90, 120, 80, 110, 85, 140],  # pinza chiusa
    "place_ready": [90,  90, 60, 100, 85, 140],  # braccio sollevato
    "place_drop":  [90,  90, 60, 100, 85, 20],   # rilascia oggetto
    "wave":        [45, 150, 35, 140, 85, 80],   # posizione laterale
    "rest":        [90, 170, 10,  90, 90, 80],   # braccio abbassato
}

# ──────────────────────────────────────────
#  Stato condiviso
# ──────────────────────────────────────────
state = {
    "current_angles": list(PRESETS["home"]),
    "speed":          50,
    "sequence":       [],
    "running":        False,
}
state_lock = threading.Lock()

# ──────────────────────────────────────────
#  I2C helper
# ──────────────────────────────────────────
class ArmController:
    def __init__(self):
        self.bus = None
        if I2C_AVAILABLE:
            try:
                self.bus = smbus2.SMBus(I2C_BUS)
                print(f"✓ I2C aperto su bus {I2C_BUS}, ESP32 @ 0x{ESP32_I2C_ADDR:02X}")
            except Exception as e:
                print(f"⚠ Impossibile aprire I2C: {e}")

    def _send(self, data: list[int]):
        """Invia bytes all'ESP32 via I2C."""
        if self.bus is None:
            print(f"  [SIM] I2C → {[hex(b) for b in data]}")
            return True
        try:
            self.bus.write_i2c_block_data(ESP32_I2C_ADDR, data[0], data[1:])
            return True
        except Exception as e:
            print(f"  ✗ I2C errore: {e}")
            return False

    def _clamp(self, servo_id: int, angle: int) -> int:
        lo, hi, _ = SERVO_LIMITS[servo_id]
        return max(lo, min(hi, int(angle)))

    def move_servo(self, servo_id: int, angle: int) -> bool:
        angle = self._clamp(servo_id, angle)
        ok = self._send([0x01, servo_id, angle])
        if ok:
            with state_lock:
                state["current_angles"][servo_id] = angle
        return ok

    def move_all(self, angles: list[int]) -> bool:
        clamped = [self._clamp(i, angles[i]) for i in range(6)]
        ok = self._send([0x02] + clamped)
        if ok:
            with state_lock:
                state["current_angles"] = clamped
        return ok

    def go_home(self) -> bool:
        ok = self._send([0x03])
        if ok:
            with state_lock:
                state["current_angles"] = list(PRESETS["home"])
        return ok

    def set_speed(self, speed: int) -> bool:
        speed = max(1, min(100, speed))
        ok = self._send([0x05, speed])
        if ok:
            with state_lock:
                state["speed"] = speed
        return ok

    def save_step(self) -> bool:
        ok = self._send([0x06])
        if ok:
            with state_lock:
                state["sequence"].append(list(state["current_angles"]))
        return ok

    def run_sequence(self) -> bool:
        return self._send([0x07])

    def reset_sequence(self) -> bool:
        ok = self._send([0x08])
        if ok:
            with state_lock:
                state["sequence"] = []
        return ok

    def get_status(self) -> list[int]:
        if self.bus is None:
            with state_lock:
                return list(state["current_angles"])
        try:
            data = self.bus.read_i2c_block_data(ESP32_I2C_ADDR, 0x04, 6)
            with state_lock:
                state["current_angles"] = list(data)
            return list(data)
        except Exception as e:
            print(f"  ✗ Lettura I2C: {e}")
            with state_lock:
                return list(state["current_angles"])

    def run_preset(self, name: str) -> bool:
        if name not in PRESETS:
            return False
        return self.move_all(PRESETS[name])

    def pick_sequence(self, waist_angle: int = 90) -> bool:
        """Sequenza automatica pick: base → scendi → chiudi → alza"""
        steps = [
            [waist_angle, 150, 35, 140, 85, 20],   # 1. apri pinza, vai alla base
            [waist_angle, 120, 80, 110, 85, 20],   # 2. scendi verso oggetto
            [waist_angle, 120, 80, 110, 85, 140],  # 3. chiudi pinza
            [waist_angle,  90, 40, 140, 85, 140],  # 4. alza oggetto
        ]
        for step in steps:
            if not self.move_all(step):
                return False
            time.sleep(0.5)
        return True

    def place_sequence(self, waist_angle: int = 0) -> bool:
        """Sequenza automatica place: spostati → abbassa → apri → torna"""
        steps = [
            [waist_angle,  90, 60, 120, 85, 140],  # 1. ruota base
            [waist_angle, 110, 75, 110, 85, 140],  # 2. scendi per piazzare
            [waist_angle, 110, 75, 110, 85, 20],   # 3. apri pinza
            [waist_angle,  90, 35, 140, 85, 20],   # 4. alza
        ]
        for step in steps:
            if not self.move_all(step):
                return False
            time.sleep(0.5)
        return True


arm = ArmController()

# ──────────────────────────────────────────
#  Flask App
# ──────────────────────────────────────────
app = Flask(__name__)
CORS(app)

def success(data=None, msg="OK"):
    resp = {"status": "ok", "message": msg}
    if data is not None:
        resp["data"] = data
    return jsonify(resp)

def error(msg, code=400):
    return jsonify({"status": "error", "message": msg}), code


# ── Status ──────────────────────────────────
@app.route("/status")
def get_status():
    angles = arm.get_status()
    with state_lock:
        spd = state["speed"]
        seq = state["sequence"]
    servos = [
        {"id": i, "name": SERVO_NAMES[i], "angle": angles[i],
         "min": SERVO_LIMITS[i][0], "max": SERVO_LIMITS[i][1]}
        for i in range(6)
    ]
    return success({
        "servos": servos,
        "speed": spd,
        "sequence_steps": len(seq),
    })


# ── Muovi singolo servo ──────────────────────
@app.route("/servo/<int:servo_id>", methods=["POST"])
def move_servo(servo_id):
    if servo_id < 0 or servo_id > 5:
        return error("servo_id deve essere 0-5")
    body = request.get_json(force=True) or {}
    if "angle" not in body:
        return error("Parametro 'angle' mancante")
    ok = arm.move_servo(servo_id, int(body["angle"]))
    return success(msg=f"Servo {SERVO_NAMES[servo_id]} → {body['angle']}°") if ok else error("I2C fallito")


# ── Muovi tutti i servo ──────────────────────
@app.route("/move_all", methods=["POST"])
def move_all():
    body = request.get_json(force=True) or {}
    angles = body.get("angles")
    if not angles or len(angles) != 6:
        return error("'angles' deve essere una lista di 6 valori")
    ok = arm.move_all([int(a) for a in angles])
    return success(msg="Tutti i servo mossi") if ok else error("I2C fallito")


# ── HOME ────────────────────────────────────
@app.route("/home", methods=["POST"])
def go_home():
    ok = arm.go_home()
    return success(msg="→ HOME") if ok else error("I2C fallito")


# ── Velocità ────────────────────────────────
@app.route("/speed", methods=["POST"])
def set_speed():
    body = request.get_json(force=True) or {}
    spd = body.get("speed", 50)
    ok = arm.set_speed(int(spd))
    return success(msg=f"Velocità → {spd}") if ok else error("I2C fallito")


# ── Sequenza ────────────────────────────────
@app.route("/save_step", methods=["POST"])
def save_step():
    ok = arm.save_step()
    with state_lock:
        n = len(state["sequence"])
    return success({"steps": n}, msg=f"Step {n} salvato") if ok else error("I2C fallito")

@app.route("/run_sequence", methods=["POST"])
def run_seq():
    ok = arm.run_sequence()
    return success(msg="Sequenza avviata") if ok else error("I2C fallito")

@app.route("/reset_sequence", methods=["POST"])
def reset_seq():
    ok = arm.reset_sequence()
    return success(msg="Sequenza resettata") if ok else error("I2C fallito")

@app.route("/sequence")
def get_sequence():
    with state_lock:
        seq = state["sequence"]
    return success({"steps": seq, "count": len(seq)})


# ── Preset ──────────────────────────────────
@app.route("/preset/<name>", methods=["POST"])
def run_preset(name):
    if name not in PRESETS:
        return error(f"Preset '{name}' non trovato. Disponibili: {list(PRESETS.keys())}")
    ok = arm.run_preset(name)
    return success(msg=f"Preset '{name}' eseguito") if ok else error("I2C fallito")

@app.route("/presets")
def list_presets():
    return success({"presets": {k: v for k, v in PRESETS.items()}})


# ── Pick & Place automatici ──────────────────
@app.route("/pick", methods=["POST"])
def pick():
    body = request.get_json(force=True) or {}
    waist = int(body.get("waist_angle", 90))
    ok = arm.pick_sequence(waist)
    return success(msg=f"Pick completato (base={waist}°)") if ok else error("Sequenza pick fallita")

@app.route("/place", methods=["POST"])
def place():
    body = request.get_json(force=True) or {}
    waist = int(body.get("waist_angle", 0))
    ok = arm.place_sequence(waist)
    return success(msg=f"Place completato (base={waist}°)") if ok else error("Sequenza place fallita")


# ──────────────────────────────────────────
if __name__ == "__main__":
    print(f"\n🤖 Robot Arm Server avviato su http://0.0.0.0:{SERVER_PORT}\n")
    arm.go_home()
    app.run(host="0.0.0.0", port=SERVER_PORT, debug=False)
