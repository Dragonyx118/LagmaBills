#!/usr/bin/env python3
"""
================================================================
 rpi_i2c_mqtt_bridge.py — Raspberry Pi  (versione completa)
 
 • Legge 26 byte dall'ESP32 SENSORI (0x09) via I2C
 • Pubblica su MQTT locale (stesso schema del firmware originale)
 • Riceve comandi MQTT e li manda all'ESP32 SENSORI (0x09) via I2C
 • Inoltra i 26 byte raw all'ESP32 MOTORI (0x08) con opcode 0xE0
 • Riceve comandi MQTT movimento e li manda all'ESP32 MOTORI via I2C
 • Permette di modificare le soglie sicurezza motori via MQTT → I2C 0xE1
 
 DIPENDENZE:
   sudo apt install python3-smbus2 python3-paho-mqtt mosquitto
   sudo raspi-config  →  Interface Options → I2C → Enable
 
 AVVIO:
   python3 rpi_i2c_mqtt_bridge.py
 
================================================================
 LAYOUT BUFFER SENSORI I2C (26 byte, ESP32 slave 0x09):
  [0-1]   FRONTE    uint16_t cm  (9999 = nessuna lettura)
  [2-3]   RETRO     uint16_t cm
  [4-5]   SINISTRA  uint16_t cm
  [6-7]   DESTRA    uint16_t cm
  [8-9]   CLIFF_F   uint16_t cm
  [10-11] CLIFF_R   uint16_t cm
  [12-13] AccX      int16_t ×100
  [14-15] AccY      int16_t ×100
  [16-17] AccZ      int16_t ×100
  [18-19] GyrX      int16_t ×100
  [20-21] GyrY      int16_t ×100
  [22-23] GyrZ      int16_t ×100
  [24]    TCRT mask (bit0=SX bit1=CEN bit2=DX, 1=nero)
  [25]    RELE      (0=off 1=on)
 
================================================================
 MQTT TOPICS IN USCITA (sensori):
  robot/sensori/distanze   → distanze ultrasuoni (JSON)
  robot/sensori/imu        → accelerometro + giroscopio (JSON)
  robot/sensori/tcrt       → sensori linea (JSON)
  robot/sensori/rele       → stato relè (JSON)
  robot/sensori/stato      → online/offline (retain)
 
 MQTT TOPICS IN USCITA (motori):
  robot/motori/stato       → encoder + velocità + soglie (JSON, ogni 500ms)
 
 MQTT TOPICS IN INGRESSO:
  robot/sensori/cmd        → comandi servo/relè verso ESP32 sensori (0x09)
  robot/motori/cmd         → comandi movimento verso ESP32 motori (0x08)
 
================================================================
 COMANDI robot/motori/cmd (JSON):
  {"cmd":"avanti"}   {"cmd":"indietro"}  {"cmd":"stop"}
  {"cmd":"sinistra"} {"cmd":"destra"}
  {"cmd":"ruota_dx"} {"cmd":"ruota_sx"}
  {"cmd":"diag_avanti_dx"}  {"cmd":"diag_avanti_sx"}
  {"cmd":"diag_indietro_dx"}{"cmd":"diag_indietro_sx"}
  {"cmd":"velocita",  "val":150}
  {"cmd":"mecanum",   "vx":0, "vy":100, "vr":0}
  {"cmd":"reset_enc"}
  {"cmd":"set_soglie","fronte":20,"retro":15,"sinistra":10,
                      "destra":10,"cliff_f":10,"cliff_r":10}
  {"cmd":"get_soglie"}   → pubblica su robot/motori/soglie
  {"cmd":"get_stato"}    → forza lettura immediata stato motori
================================================================
"""

import struct
import time
import json
import sys
import logging
import signal

try:
    import smbus2
except ImportError:
    sys.exit("Installa smbus2:  sudo apt install python3-smbus2")

try:
    import paho.mqtt.client as mqtt
except ImportError:
    sys.exit("Installa paho-mqtt:  sudo apt install python3-paho-mqtt")

# ── CONFIG ────────────────────────────────────────────────────────
I2C_BUS         = 1        # /dev/i2c-1
ESP32_SENS_ADDR = 0x09     # ESP32 sensori (slave I2C)
ESP32_MOT_ADDR  = 0x08     # ESP32 motori  (slave I2C)
SENS_BUF_SIZE   = 26       # byte dati sensori
MOT_BUF_SIZE    = 28       # byte risposta motori

MQTT_BROKER  = "localhost"
MQTT_PORT    = 1883
MQTT_CLIENT  = "rpi_bridge"

TOPIC_SENS_CMD  = "robot/sensori/cmd"
TOPIC_MOT_CMD   = "robot/motori/cmd"
TOPIC_MOT_STATO = "robot/motori/stato"
TOPIC_MOT_SOGLIE= "robot/motori/soglie"

POLL_SENS_HZ = 10      # Hz lettura sensori
PERIOD_SENS  = 1.0 / POLL_SENS_HZ
PERIOD_DIAG  = 0.5     # secondi tra aggiornamenti diagnostica

# ── LOGGING ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("bridge")

# ── STATO GLOBALE ─────────────────────────────────────────────────
_last_tcrt  = None
_last_rele  = None
_servo_pos  = [90, 90, 90, 90, 90, 120, 125]
_running    = True
_mot_vel    = 150          # velocità corrente motori (cache locale)
_soglie_cache = [20, 15, 10, 10, 10, 10]  # cache soglie locali


# ════════════════════════════════════════════════════════════════
#  I2C helpers
# ════════════════════════════════════════════════════════════════

def i2c_read(bus: smbus2.SMBus, addr: int, n: int) -> bytes | None:
    try:
        msg = smbus2.i2c_msg.read(addr, n)
        bus.i2c_rdwr(msg)
        return bytes(msg)
    except OSError as e:
        log.warning(f"I2C read 0x{addr:02X}: {e}")
        return None


def i2c_write(bus: smbus2.SMBus, addr: int, data: list) -> bool:
    try:
        msg = smbus2.i2c_msg.write(addr, data)
        bus.i2c_rdwr(msg)
        return True
    except OSError as e:
        log.warning(f"I2C write 0x{addr:02X}: {e}")
        return False


def forward_sensori_a_motori(bus: smbus2.SMBus, raw_buf: bytes):
    """Manda i 26 byte sensori all'ESP32 motori con opcode 0xE0."""
    i2c_write(bus, ESP32_MOT_ADDR, [0xE0] + list(raw_buf))


def leggi_stato_motori(bus: smbus2.SMBus) -> dict | None:
    """
    Legge 28 byte di stato dall'ESP32 motori (0x08).
    Ritorna un dict con encoder, velocità, PWM e soglie, o None.
    Layout risposta:
      [0-3]   encoderFL  int32 LE
      [4-7]   encoderFR  int32 LE
      [8-11]  encoderRL  int32 LE
      [12-15] encoderRR  int32 LE
      [16]    velocita   uint8
      [17]    statoMotori uint8
      [18-21] PWM FL FR RL RR (offset +128)
      [22-27] soglie FRONTE RETRO SX DX CLIFF_F CLIFF_R (cm)
    """
    buf = i2c_read(bus, ESP32_MOT_ADDR, MOT_BUF_SIZE)
    if buf is None:
        return None
    try:
        fl, fr, rl, rr = struct.unpack_from('<iiii', buf, 0)
        vel   = buf[16]
        stato = buf[17]
        pwm   = [buf[18]-128, buf[19]-128, buf[20]-128, buf[21]-128]
        soglie= list(buf[22:28])
        return {
            "enc": {"fl": fl, "fr": fr, "rl": rl, "rr": rr},
            "vel": vel, "stato": stato,
            "pwm": {"fl": pwm[0], "fr": pwm[1], "rl": pwm[2], "rr": pwm[3]},
            "soglie": soglie,
        }
    except Exception as e:
        log.warning(f"Parse stato motori: {e}")
        return None


# ════════════════════════════════════════════════════════════════
#  PARSE BUFFER SENSORI
# ════════════════════════════════════════════════════════════════

def parse_buf(buf: bytes) -> dict:
    def u16(o): return struct.unpack_from('<H', buf, o)[0]
    def i16(o): return struct.unpack_from('<h', buf, o)[0]

    names = ["FRONTE", "RETRO", "SINISTRA", "DESTRA", "CLIFF_F", "CLIFF_R"]
    dist = {}
    for i, name in enumerate(names):
        v = u16(i * 2)
        dist[name] = 0 if v == 9999 else v

    imu = {
        "ax": round(i16(12) / 100.0, 2), "ay": round(i16(14) / 100.0, 2),
        "az": round(i16(16) / 100.0, 2), "gx": round(i16(18) / 100.0, 2),
        "gy": round(i16(20) / 100.0, 2), "gz": round(i16(22) / 100.0, 2),
    }

    mask = buf[24]
    tcrt = {
        "sx":  int(bool(mask & 0x01)),
        "cen": int(bool(mask & 0x02)),
        "dx":  int(bool(mask & 0x04)),
        "_mask": mask,
    }

    rele = int(buf[25]) if len(buf) > 25 else 0
    return {"dist": dist, "imu": imu, "tcrt": tcrt, "rele": rele}


# ════════════════════════════════════════════════════════════════
#  MQTT — callbacks
# ════════════════════════════════════════════════════════════════

def on_connect(client, userdata, flags, rc, props=None):
    if rc == 0:
        log.info("MQTT connesso")
        client.subscribe(TOPIC_SENS_CMD)
        client.subscribe(TOPIC_MOT_CMD)
        client.publish("robot/sensori/stato", json.dumps({"online": True}), retain=True)
    else:
        log.error(f"MQTT connessione fallita rc={rc}")


def on_disconnect(client, userdata, rc, props=None, reason=None):
    log.warning(f"MQTT disconnesso rc={rc}")


def on_message(client, userdata, msg):
    bus: smbus2.SMBus = userdata["bus"]
    try:
        payload = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        log.warning(f"JSON non valido: {msg.payload}")
        return

    cmd = payload.get("cmd")
    if not cmd:
        return

    log.info(f"MQTT [{msg.topic}]: {payload}")

    if msg.topic == TOPIC_SENS_CMD:
        _handle_sensori_cmd(client, bus, cmd, payload)
    elif msg.topic == TOPIC_MOT_CMD:
        _handle_motori_cmd(client, bus, cmd, payload)


# ── Comandi sensori/servo (→ ESP32 0x09) ─────────────────────────

def _handle_sensori_cmd(client, bus, cmd, payload):
    if cmd == "servo":
        ch  = int(payload.get("ch", 0))
        ang = max(0, min(180, int(payload.get("ang", 90))))
        if 0 <= ch <= 6:
            i2c_write(bus, ESP32_SENS_ADDR, [0xAD, ch, ang])
            _servo_pos[ch] = ang

    elif cmd == "servo_rel":
        ch    = int(payload.get("ch", 0))
        delta = int(payload.get("delta", 0))
        if 0 <= ch <= 6:
            target = max(0, min(180, _servo_pos[ch] + delta))
            i2c_write(bus, ESP32_SENS_ADDR, [0xAD, ch, target])
            _servo_pos[ch] = target

    elif cmd == "set":
        for i in range(7):
            v = payload.get(f"s{i}", -1)
            if v is not None and int(v) >= 0:
                deg = max(0, min(180, int(v)))
                i2c_write(bus, ESP32_SENS_ADDR, [0xAD, i, deg])
                _servo_pos[i] = deg

    elif cmd == "home":
        i2c_write(bus, ESP32_SENS_ADDR, [0xAE])

    elif cmd == "riposo":
        i2c_write(bus, ESP32_SENS_ADDR, [0xAF])

    elif cmd == "servo_speed":
        ms = int(payload.get("ms", -1))
        if 1 <= ms <= 50:
            i2c_write(bus, ESP32_SENS_ADDR, [0xB0, ms])
            client.publish("robot/sensori/servo_speed",
                           json.dumps({"ms_per_step": ms,
                                       "deg_per_sec": round(1000/ms)}), retain=True)

    elif cmd == "rele":
        val = 1 if payload.get("val", 0) else 0
        i2c_write(bus, ESP32_SENS_ADDR, [0xAC, val])

    elif cmd == "get_stato":
        buf = i2c_read(bus, ESP32_SENS_ADDR, SENS_BUF_SIZE)
        if buf:
            _publish_sensori(client, parse_buf(buf))

    else:
        log.warning(f"Comando sensori sconosciuto: {cmd}")


# ── Comandi motori (→ ESP32 0x08) ────────────────────────────────

# Mappa comandi stringa → opcode I2C (1 byte)
_MOT_OPCODES = {
    "stop":             [0x00],
    "avanti":           [0x01],
    "indietro":         [0x02],
    "sinistra":         [0x03],
    "destra":           [0x04],
    "diag_avanti_dx":   [0x05],
    "diag_avanti_sx":   [0x06],
    "diag_indietro_dx": [0x07],
    "diag_indietro_sx": [0x08],
    "ruota_dx":         [0x09],
    "ruota_sx":         [0x0A],
    "reset_enc":        [0xFF],
}


def _handle_motori_cmd(client, bus, cmd, payload):
    global _mot_vel, _soglie_cache

    # ── comandi semplici ──────────────────────────────────────────
    if cmd in _MOT_OPCODES:
        i2c_write(bus, ESP32_MOT_ADDR, _MOT_OPCODES[cmd])
        return

    # ── set velocità ──────────────────────────────────────────────
    if cmd == "velocita":
        v = max(0, min(255, int(payload.get("val", _mot_vel))))
        i2c_write(bus, ESP32_MOT_ADDR, [0xF0, v])
        _mot_vel = v
        return

    # ── mecanum drive ─────────────────────────────────────────────
    if cmd == "mecanum":
        vx = max(-127, min(127, int(payload.get("vx", 0))))
        vy = max(-127, min(127, int(payload.get("vy", 0))))
        vr = max(-127, min(127, int(payload.get("vr", 0))))
        i2c_write(bus, ESP32_MOT_ADDR, [0xF2, vx+128, vy+128, vr+128])
        return

    # ── set soglie sicurezza ──────────────────────────────────────
    # {"cmd":"set_soglie","fronte":20,"retro":15,"sinistra":10,
    #                     "destra":10,"cliff_f":10,"cliff_r":10}
    if cmd == "set_soglie":
        keys   = ["fronte", "retro", "sinistra", "destra", "cliff_f", "cliff_r"]
        soglie = [
            max(0, min(255, int(payload.get(k, _soglie_cache[i]))))
            for i, k in enumerate(keys)
        ]
        i2c_write(bus, ESP32_MOT_ADDR, [0xE1] + soglie)
        _soglie_cache = soglie
        log.info(f"Soglie aggiornate: {dict(zip(keys, soglie))}")
        # Pubblica conferma
        client.publish(TOPIC_MOT_SOGLIE,
                       json.dumps(dict(zip(keys, soglie))), retain=True)
        return

    # ── get soglie ────────────────────────────────────────────────
    if cmd == "get_soglie":
        # Legge direttamente dallo stato motori (i byte 22-27 della risposta)
        stato = leggi_stato_motori(bus)
        if stato:
            keys   = ["fronte", "retro", "sinistra", "destra", "cliff_f", "cliff_r"]
            soglie = stato["soglie"]
            _soglie_cache = soglie
            client.publish(TOPIC_MOT_SOGLIE,
                           json.dumps(dict(zip(keys, soglie))), retain=True)
        else:
            # fallback: usa cache locale
            keys = ["fronte", "retro", "sinistra", "destra", "cliff_f", "cliff_r"]
            client.publish(TOPIC_MOT_SOGLIE,
                           json.dumps(dict(zip(keys, _soglie_cache))), retain=True)
        return

    # ── get stato immediato ───────────────────────────────────────
    if cmd == "get_stato":
        stato = leggi_stato_motori(bus)
        if stato:
            _publish_stato_motori(client, stato)
        return

    # ── tutti: tutti i motori allo stesso valore grezzo ───────────
    # {"cmd":"tutti","val":150}
    if cmd == "tutti":
        v = max(-255, min(255, int(payload.get("val", 0))))
        # Usa CMD_SET_MOTORI (0xF2 mecanum non va bene per valori grezzi)
        # Manda set con fl=fr=rl=rr=v (raw, nessuna inversione)
        def clamp8(x): return max(-127, min(127, x // 2))  # scala a ±127 per mecanum
        # Usa opcode 0xF2 con vx=0,vy=v,vr=0 se v nel range mecanum,
        # altrimenti usa il comando "set" raw via strBuf (non disponibile diretto).
        # Soluzione: manda avanti/indietro con velocità forzata se v>0/<0,
        # oppure usa il payload set con fl=fr=rl=rr=v normalizzato.
        # Il modo più corretto è usare il cmd "set" col firmware che accetta raw.
        fl = fr = rl = rr = max(-255, min(255, v))
        # Encode come CMD_SET: opcode non esiste diretto in I2C, ma il firmware
        # accetta 0xF2 (mecanum vy) per movimento dritto.
        # Usiamo mecanum vy per tutti-avanti/indietro, vx=vr=0
        vy = max(-128, min(127, v * 127 // 255))
        i2c_write(bus, ESP32_MOT_ADDR, [0xF2, 128, vy + 128, 128])
        log.info(f"tutti val={v} → mecanum vy={vy}")
        return

    # ── set: quattro motori raw ───────────────────────────────────
    # {"cmd":"set","fl":150,"fr":-150,"rl":150,"rr":-150}
    if cmd == "set":
        fl = max(-255, min(255, int(payload.get("fl", 0))))
        fr = max(-255, min(255, int(payload.get("fr", 0))))
        rl = max(-255, min(255, int(payload.get("rl", 0))))
        rr = max(-255, min(255, int(payload.get("rr", 0))))
        # Calcola vx,vy,vr dalla cinematica inversa mecanum e manda 0xF2
        vy = (fl + fr + rl + rr) // 4
        vx = (-fl + fr + rl - rr) // 4
        vr = (-fl - fr + rl + rr) // 4
        vy = max(-128, min(127, vy * 127 // 255))
        vx = max(-128, min(127, vx * 127 // 255))
        vr = max(-128, min(127, vr * 127 // 255))
        i2c_write(bus, ESP32_MOT_ADDR, [0xF2, vx + 128, vy + 128, vr + 128])
        log.info(f"set fl={fl} fr={fr} rl={rl} rr={rr} → vx={vx} vy={vy} vr={vr}")
        return

    # ── motori singoli: fl/fr/rl/rr ──────────────────────────────
    # {"cmd":"fl","val":150}
    _single_map = {"fl": 0, "fr": 1, "rl": 2, "rr": 3}
    if cmd in _single_map:
        idx = _single_map[cmd]
        v   = max(-255, min(255, int(payload.get("val", 0))))
        # opcode motore singolo non esiste in I2C diretto,
        # ma il firmware accetta CMD_MOTOR_SINGLE non esposto come opcode I2C.
        # Usiamo mecanum con solo il motore richiesto impostando i contributi:
        # FL=idx0: vy+vx+vr=v, altri=0 → non linearmente invertibile in modo pulito.
        # Soluzione pratica: manda il movimento più vicino o logga avviso.
        # Per test singoli il tester li usa per diagnostica, quindi passiamo
        # il comando "set" con un solo motore attivo (approssimato via mecanum):
        vals = [0, 0, 0, 0]
        vals[idx] = v
        fl2, fr2, rl2, rr2 = vals
        vy2 = (fl2+fr2+rl2+rr2)//4
        vx2 = (-fl2+fr2+rl2-rr2)//4
        vr2 = (-fl2-fr2+rl2+rr2)//4
        vy2 = max(-128, min(127, vy2*127//255 if abs(vy2) else 0))
        vx2 = max(-128, min(127, vx2*127//255 if abs(vx2) else 0))
        vr2 = max(-128, min(127, vr2*127//255 if abs(vr2) else 0))
        i2c_write(bus, ESP32_MOT_ADDR, [0xF2, vx2+128, vy2+128, vr2+128])
        log.info(f"singolo {cmd} val={v} → mecanum vx={vx2} vy={vy2} vr={vr2}")
        return

    # ── coppie: sx/dx/ant/post/diag1/diag2 ───────────────────────
    # Questi comandi non sono nativi nel firmware; mappati su mecanum.
    if cmd in ("sx", "dx", "ant", "post", "diag1", "diag2"):
        v = max(-255, min(255, int(payload.get("val", 0))))
        s = max(-128, min(127, v * 127 // 255))
        if   cmd == "ant":   i2c_write(bus, ESP32_MOT_ADDR, [0xF2, 128,   s+128, 128])
        elif cmd == "post":  i2c_write(bus, ESP32_MOT_ADDR, [0xF2, 128,  -s+128, 128])
        elif cmd == "sx":    i2c_write(bus, ESP32_MOT_ADDR, [0xF2, -s+128, 128,  128])
        elif cmd == "dx":    i2c_write(bus, ESP32_MOT_ADDR, [0xF2,  s+128, 128,  128])
        elif cmd == "diag1": i2c_write(bus, ESP32_MOT_ADDR, [0xF2,  s+128, s+128, 128])
        elif cmd == "diag2": i2c_write(bus, ESP32_MOT_ADDR, [0xF2, -s+128, s+128, 128])
        log.info(f"coppia {cmd} val={v} s={s}")
        return

    log.warning(f"Comando motori sconosciuto: {cmd}")


# ════════════════════════════════════════════════════════════════
#  PUBLISH helpers
# ════════════════════════════════════════════════════════════════

def _publish_sensori(client: mqtt.Client, data: dict):
    dist = data["dist"]
    client.publish("robot/sensori/distanze",
                   json.dumps({k: v for k, v in dist.items()}))
    client.publish("robot/sensori/imu",
                   json.dumps(data["imu"]))
    t = data["tcrt"]
    client.publish("robot/sensori/tcrt",
                   json.dumps({"sx": t["sx"], "cen": t["cen"], "dx": t["dx"]}))
    client.publish("robot/sensori/rele",
                   json.dumps({"rele": data["rele"]}), retain=True)


def _publish_stato_motori(client: mqtt.Client, stato: dict):
    e = stato["enc"]
    p = stato["pwm"]
    keys = ["fronte", "retro", "sinistra", "destra", "cliff_f", "cliff_r"]
    payload = {
        "online": True,
        "fl": e["fl"], "fr": e["fr"], "rl": e["rl"], "rr": e["rr"],
        "vel": stato["vel"], "stato": stato["stato"],
        "vfl": p["fl"], "vfr": p["fr"], "vrl": p["rl"], "vrr": p["rr"],
    }
    client.publish(TOPIC_MOT_STATO, json.dumps(payload))
    # Pubblica anche soglie se cambiate
    if stato["soglie"] != _soglie_cache:
        keys_s = ["fronte", "retro", "sinistra", "destra", "cliff_f", "cliff_r"]
        client.publish(TOPIC_MOT_SOGLIE,
                       json.dumps(dict(zip(keys_s, stato["soglie"]))), retain=True)


# ════════════════════════════════════════════════════════════════
#  DIAGNOSTICA TERMINALE
# ════════════════════════════════════════════════════════════════

def print_diagnostica(data: dict, buf: bytes, mot: dict | None):
    d = data["dist"]
    i = data["imu"]
    t = data["tcrt"]
    mask = t["_mask"]

    tcrt_desc = {
        0b000: "LINEA PERSA",   0b010: "CENTRATO ✓",
        0b111: "INCROCIO",      0b001: "DEVIARE A DX",
        0b100: "DEVIARE A SX",  0b011: "LIEVE DX",
        0b110: "LIEVE SX",      0b101: "RUMORE",
    }.get(mask & 0x07, f"mask=0x{mask:02X}")

    tcrt_bar = (
        f"[{'███' if t['sx']  else '   '}|"
        f"{'███' if t['cen'] else '   '}|"
        f"{'███' if t['dx']  else '   '}]"
    )

    # Ultrasuoni su due righe
    dist_names = list(d.items())
    def fmt(name, val): return f"{name}:{val if val else '---':>4}"
    row1 = "  ".join(fmt(n, v) for n, v in dist_names[:3])
    row2 = "  ".join(fmt(n, v) for n, v in dist_names[3:])

    # Motori
    if mot:
        e = mot["enc"]
        enc_str = f"FL={e['fl']}  FR={e['fr']}  RL={e['rl']}  RR={e['rr']}"
        s = mot["soglie"]
        sog_str = f"F:{s[0]} R:{s[1]} SX:{s[2]} DX:{s[3]} CF:{s[4]} CR:{s[5]}"
        stati = {0: "STOP", 1: "IN MOTO", 2: "ROTAZIONE"}
        mot_str = f"{stati.get(mot['stato'], '?')}  vel={mot['vel']}"
    else:
        enc_str = "motori non risponde"
        sog_str = " | ".join(str(v) for v in _soglie_cache)
        mot_str = "---"

    W = 60
    sep = "═" * W
    print(
        f"\033[2J\033[H"
        f"╔{sep}╗\n"
        f"║{'ESP32 → Raspberry Pi  |  I2C bridge LIVE':^{W}}║\n"
        f"╠{sep}╣\n"
        f"║ SENSORI (0x09)                                             ║\n"
        f"║  Dist 1/2: {row1:<{W-13}}║\n"
        f"║  Dist 2/2: {row2:<{W-13}}║\n"
        f"║  IMU acc: ({i['ax']:+.2f},{i['ay']:+.2f},{i['az']:+.2f})  "
        f"gyr: ({i['gx']:+.2f},{i['gy']:+.2f},{i['gz']:+.2f}){'':5}║\n"
        f"║  TCRT {tcrt_bar} {tcrt_desc:<{W-20}}║\n"
        f"║  Relè: {'ON ' if data['rele'] else 'off'}  "
        f"RAW: {buf[:8].hex(' ')} ...{'':13}║\n"
        f"╠{sep}╣\n"
        f"║ MOTORI (0x08)                                              ║\n"
        f"║  Stato: {mot_str:<{W-10}}║\n"
        f"║  Enc:   {enc_str:<{W-10}}║\n"
        f"║  Soglie:{sog_str:<{W-10}}║\n"
        f"╚{sep}╝\n"
        f"  Ctrl+C per uscire\n",
        end="", flush=True
    )


# ════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════

def signal_handler(sig, frame):
    global _running
    log.info("Uscita...")
    _running = False


def main():
    global _running, _last_tcrt, _last_rele

    signal.signal(signal.SIGINT,  signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        bus = smbus2.SMBus(I2C_BUS)
        log.info(f"I2C bus {I2C_BUS} aperto")
    except Exception as e:
        sys.exit(f"Impossibile aprire I2C bus {I2C_BUS}: {e}")

    # Verifica ESP32 sensori
    log.info(f"Verifica ESP32 sensori (0x{ESP32_SENS_ADDR:02X})...")
    if i2c_read(bus, ESP32_SENS_ADDR, SENS_BUF_SIZE) is None:
        log.warning("ESP32 sensori non risponde — continuo comunque")
    else:
        log.info("ESP32 sensori OK")

    # Verifica ESP32 motori
    log.info(f"Verifica ESP32 motori (0x{ESP32_MOT_ADDR:02X})...")
    if i2c_read(bus, ESP32_MOT_ADDR, MOT_BUF_SIZE) is None:
        log.warning("ESP32 motori non risponde — continuo comunque")
    else:
        log.info("ESP32 motori OK")

    # MQTT
    mqttc = mqtt.Client(
        client_id=MQTT_CLIENT,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        userdata={"bus": bus}
    )
    mqttc.will_set("robot/sensori/stato",
                   json.dumps({"online": False}), retain=True)
    mqttc.on_connect    = on_connect
    mqttc.on_disconnect = on_disconnect
    mqttc.on_message    = on_message

    log.info(f"Connessione MQTT a {MQTT_BROKER}:{MQTT_PORT}...")
    try:
        mqttc.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        log.warning(f"MQTT non disponibile: {e} (continuo senza MQTT)")

    mqttc.loop_start()

    t_sens      = time.monotonic()
    t_diag      = time.monotonic()
    t_mot_stato = time.monotonic()
    PERIOD_MOT  = 0.5    # secondi tra letture stato motori

    log.info("Bridge avviato — Ctrl+C per uscire")

    while _running:
        now = time.monotonic()

        if (now - t_sens) >= PERIOD_SENS:
            t_sens = now

            # ── 1. Leggi sensori ──────────────────────────────────
            buf = i2c_read(bus, ESP32_SENS_ADDR, SENS_BUF_SIZE)
            if buf is None:
                time.sleep(0.1)
                continue

            data = parse_buf(buf)

            # ── 2. Forward raw → ESP32 motori ─────────────────────
            forward_sensori_a_motori(bus, buf)

            # ── 3. Pubblica sensori su MQTT ───────────────────────
            if mqttc.is_connected():
                mqttc.publish("robot/sensori/distanze",
                              json.dumps({k: v for k, v in data["dist"].items()}))
                mqttc.publish("robot/sensori/imu",
                              json.dumps(data["imu"]))

                # TCRT: solo su cambio
                mask = data["tcrt"]["_mask"]
                if mask != _last_tcrt:
                    _last_tcrt = mask
                    t = data["tcrt"]
                    mqttc.publish("robot/sensori/tcrt",
                                  json.dumps({"sx": t["sx"],
                                              "cen": t["cen"],
                                              "dx": t["dx"]}))

                # Relè: solo su cambio
                if data["rele"] != _last_rele:
                    _last_rele = data["rele"]
                    mqttc.publish("robot/sensori/rele",
                                  json.dumps({"rele": data["rele"]}), retain=True)

        # ── 4. Stato motori ogni 500ms ────────────────────────────
        if (now - t_mot_stato) >= PERIOD_MOT:
            t_mot_stato = now
            mot = leggi_stato_motori(bus)
            if mot and mqttc.is_connected():
                _publish_stato_motori(mqttc, mot)

            # Diagnostica terminale
            if (now - t_diag) >= PERIOD_DIAG:
                t_diag = now
                if buf:
                    print_diagnostica(data, buf, mot)

        time.sleep(0.005)

    # ── cleanup ───────────────────────────────────────────────────
    log.info("Chiusura bridge...")
    if mqttc.is_connected():
        mqttc.publish("robot/sensori/stato",
                      json.dumps({"online": False}), retain=True)
        mqttc.loop_stop()
        mqttc.disconnect()
    bus.close()
    log.info("Bridge terminato.")


if __name__ == "__main__":
    main()
