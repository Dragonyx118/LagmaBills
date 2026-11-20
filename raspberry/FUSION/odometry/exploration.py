#!/usr/bin/env python3
"""
esplorazione.py — LagmaBills
Modalità "esplorazione autonoma": il robot va in giro da solo
evitando gli ostacoli, SENZA odometria/mappa/goal.

Perché questo approccio invece della vecchia catena
odometria → occupancy_grid → potential_field → navigator:
  la vecchia catena non ha mai funzionato perché dipendeva da
  L_LAT_M/L_LON_M mai calibrati fisicamente sul robot, quindi
  ogni stima di posa (x,y,theta) derivava e la mappa si sporcava
  subito. Qui non c'è nessuna posa da stimare: si guarda solo
  "cosa c'è adesso davanti/ai lati" e si decide subito.

MODIFICHE rispetto alla versione precedente:
  1. FIX CANALE MOTORI — nel protocollo usato in tutto il resto del
     progetto (testI2C.py, navigator.py, firmware ESP32) l'ordine è
     SEMPRE (vx=avanti, vy=laterale, vr=rotazione). La versione
     precedente di questo file metteva la velocità di marcia nel
     secondo argomento (vy = laterale) invece del primo (vx = avanti),
     causando probabile strafe laterale invece di marcia dritta.
     Ora invia_motori(vx, vy, vr) viene chiamata con la marcia SEMPRE
     nel primo argomento.
  2. DISTANZA DI FRENATA DINAMICA — invece di una soglia fissa,
     calcola in tempo reale la velocità del robot dagli encoder
     (via robot/motori/stato) e allarga/restringe la zona di
     frenata in base a quanta strada il robot percorrerebbe durante
     la latenza stimata della catena sensore->decisione->motore.

Logica (macchina a stati semplice):
  1. Se CLIFF rilevato   → stop, indietro breve, ruota, riprova
  2. Se FRONTE < STOP    → stop, ruota verso il lato più libero
  3. Se FRONTE < BRAKE(v)→ rallenta e inizia a virare (BRAKE dipende
                           dalla velocità reale misurata)
  4. Altrimenti          → avanti dritto

Subscribe MQTT:
  robot/sensori/distanze   → {"FRONTE":.., "RETRO":.., "SINISTRA":..,
                               "DESTRA":.., "CLIFF_F":.., "CLIFF_R":..}
  robot/motori/stato       → {"fl":.., "fr":.., "rl":.., "rr":.., ...}
                              (tick encoder assoluti, da testI2C.py)
  robot/esplorazione/cmd   → "start" | "stop"

I comandi motori vengono inviati via UDP in loopback locale
al listener già attivo dentro testI2C.py (porta 5566) —
stessa via che userebbe un PC remoto, ma qui a costo zero
di latenza perché è tutto sullo stesso Pi.
"""

import json
import math
import time
import struct
import socket
import threading
import paho.mqtt.client as mqtt

# ── CONFIG ────────────────────────────────────────────────────────
MQTT_BROKER = "localhost"
MQTT_PORT   = 1883

T_SENSORI   = "robot/sensori/distanze"
T_MOT_STATO = "robot/motori/stato"        # NUOVO: per calcolare la velocità reale
T_CMD       = "robot/esplorazione/cmd"    # "start" / "stop"
T_STATO     = "robot/esplorazione/stato"  # per debug/viewer

UDP_PI_LOCAL = "127.0.0.1"
UDP_CMD_PORT = 5566          # stesso listener usato dal PC remoto

# Soglie (cm)
STOP_DIST_CM    = 15.0
SIDE_CLEAR_CM   = 40.0       # sotto questa, il lato è "poco libero"
CLIFF_BACKUP_S  = 0.6        # secondi di retromarcia dopo un cliff
TURN_TIME_S     = 0.5        # durata rotazione quando schiva ostacolo

VEL_AVANTI = 90              # -127..127
VEL_ROT    = 90

SENSOR_TIMEOUT_S = 1.0       # se i sensori tacciono troppo → stop

# ── PARAMETRI FRENATA DINAMICA ─────────────────────────────────────
# Geometria ruota — stessi valori confermati in odometria.py
TICKS_PER_REV = 1200                       # confermato dal firmware (TICKS_PER_360)
WHEEL_DIAM_M  = 0.097
WHEEL_CIRC_M  = math.pi * WHEEL_DIAM_M
M_PER_TICK    = WHEEL_CIRC_M / TICKS_PER_REV

# Latenza stimata della catena sensore -> decisione -> motore, con
# bridge a 20Hz sensori / 10Hz stato motori e loop esplorazione a 10Hz.
# CALIBRA empiricamente: misura col cronometro quanto tempo passa
# da quando un ostacolo appare a quando il motore riceve lo stop.
LATENZA_TOTALE_S     = 0.15   # secondi
MARGINE_SICUREZZA_CM = 10.0   # margine extra oltre al calcolo geometrico
BRAKE_DIST_MIN_CM    = 25.0   # non scendere mai sotto questo, anche a v=0
BRAKE_RATIO_MIN      = 0.2    # velocità minima (frazione) durante la frenata

# ── STATO ─────────────────────────────────────────────────────────
lock = threading.Lock()
state = {
    "running": False,
    "sensors": {"FRONTE": 9999, "RETRO": 9999, "SINISTRA": 9999,
                "DESTRA": 9999, "CLIFF_F": 9999, "CLIFF_R": 9999},
    "last_sensor_ts": 0.0,
    "mode": "idle",
    # NUOVO: per il calcolo della velocità reale
    "enc_prev": None,     # {"fl":.., "fr":.., "rl":.., "rr":.., "ts":..}
    "speed_cm_s": 0.0,
}

udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)


# ── COMANDI MOTORI (via UDP locale) ────────────────────────────────
# Convenzione fissa in tutto il progetto: vx=avanti, vy=laterale, vr=rotazione

def invia_motori(vx: int, vy: int, vr: int):
    vx = max(-127, min(127, vx))
    vy = max(-127, min(127, vy))
    vr = max(-127, min(127, vr))
    pkt = struct.pack("<Bbbb", 0x01, vx, vy, vr)
    udp_sock.sendto(pkt, (UDP_PI_LOCAL, UDP_CMD_PORT))


def stop():
    udp_sock.sendto(struct.pack("<B", 0x03), (UDP_PI_LOCAL, UDP_CMD_PORT))


# ── VELOCITÀ REALE DAGLI ENCODER ───────────────────────────────────

def aggiorna_velocita_da_encoder(fl, fr, rl, rr, now):
    """Calcola cm/s reali a partire dai tick assoluti degli encoder."""
    with lock:
        prev = state["enc_prev"]
        if prev is not None:
            dt = now - prev["ts"]
            if dt > 0:
                d_media = (abs(fl - prev["fl"]) + abs(fr - prev["fr"]) +
                           abs(rl - prev["rl"]) + abs(rr - prev["rr"])) / 4.0
                v_tick_s = d_media / dt
                state["speed_cm_s"] = v_tick_s * M_PER_TICK * 100.0
        state["enc_prev"] = {"fl": fl, "fr": fr, "rl": rl, "rr": rr, "ts": now}


def brake_dist_dinamica() -> float:
    """
    Distanza (cm) sotto la quale iniziare a frenare, calcolata in base
    alla velocità reale misurata: più veloce va il robot, più ampia
    deve essere la zona di frenata per compensare la latenza della
    catena sensore->decisione->motore.
    """
    with lock:
        v = state["speed_cm_s"]
    dist = STOP_DIST_CM + v * LATENZA_TOTALE_S + MARGINE_SICUREZZA_CM
    return max(BRAKE_DIST_MIN_CM, dist)


# ── LOGICA REATTIVA ───────────────────────────────────────────────

def cliff_rilevato(cliff_soglia_cm=12.0) -> bool:
    s = state["sensors"]
    # CLIFF_F/CLIFF_R alti = niente pavimento sotto = dirupo
    return s["CLIFF_F"] > cliff_soglia_cm or s["CLIFF_R"] > cliff_soglia_cm


def loop_esplorazione():
    """Gira a ~10Hz, decide e manda comandi. Nessuna stima di posa."""
    RATE_HZ = 10
    period = 1.0 / RATE_HZ

    while True:
        t0 = time.time()

        with lock:
            running = state["running"]
            s = dict(state["sensors"])
            last_ts = state["last_sensor_ts"]

        if not running:
            time.sleep(period)
            continue

        # ── Timeout sensori → stop di sicurezza ────────────────────
        if last_ts and (time.time() - last_ts) > SENSOR_TIMEOUT_S:
            stop()
            with lock:
                state["mode"] = "sensor_timeout"
            time.sleep(period)
            continue

        # ── Cliff → stop, retro, ruota, riparti ────────────────────
        if cliff_rilevato():
            with lock:
                state["mode"] = "cliff_evade"
            stop()
            time.sleep(0.1)
            invia_motori(-VEL_AVANTI, 0, 0)      # indietro (FIX: canale vx)
            time.sleep(CLIFF_BACKUP_S)
            invia_motori(0, 0, VEL_ROT)           # ruota sul posto (già corretto)
            time.sleep(TURN_TIME_S)
            stop()
            continue

        fronte = s["FRONTE"]
        sx     = s["SINISTRA"]
        dx     = s["DESTRA"]

        # Distanza di frenata ricalcolata ogni ciclo sulla velocità reale
        brake_dist = brake_dist_dinamica()

        # ── Ostacolo troppo vicino → stop e ruota verso il lato libero ──
        if fronte < STOP_DIST_CM:
            with lock:
                state["mode"] = "obstacle_evade"
            stop()
            time.sleep(0.05)
            verso_dx = dx > sx   # ruota verso il lato con più spazio
            vr = VEL_ROT if verso_dx else -VEL_ROT
            invia_motori(0, 0, vr)
            time.sleep(TURN_TIME_S)
            stop()
            continue

        # ── Zona di frenata: rallenta e comincia a virare ──────────
        if fronte < brake_dist:
            with lock:
                state["mode"] = "braking"
            brake_ratio = (fronte - STOP_DIST_CM) / (brake_dist - STOP_DIST_CM)
            brake_ratio = max(0.0, min(1.0, brake_ratio))
            v = int(VEL_AVANTI * max(BRAKE_RATIO_MIN, brake_ratio))
            # piccola correzione verso il lato più libero mentre rallenta
            vr = int(VEL_ROT * 0.4) if dx > sx else -int(VEL_ROT * 0.4)
            invia_motori(v, 0, vr)                # FIX: marcia nel canale vx
            time.sleep(period)
            continue

        # ── Via libera → avanti dritto ──────────────────────────────
        with lock:
            state["mode"] = "avanti"
        invia_motori(VEL_AVANTI, 0, 0)            # FIX: marcia nel canale vx

        elapsed = time.time() - t0
        time.sleep(max(0.0, period - elapsed))


# ── MQTT CALLBACKS ────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[esplorazione] MQTT connesso")
        client.subscribe(T_SENSORI)
        client.subscribe(T_MOT_STATO)
        client.subscribe(T_CMD)
    else:
        print(f"[esplorazione] Connessione fallita rc={rc}")


def on_message(client, userdata, msg):
    if msg.topic == T_SENSORI:
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            return
        with lock:
            for k in state["sensors"]:
                if k in payload:
                    state["sensors"][k] = float(payload[k])
            state["last_sensor_ts"] = time.time()

    elif msg.topic == T_MOT_STATO:
        try:
            payload = json.loads(msg.payload.decode())
        except json.JSONDecodeError:
            return
        if not all(k in payload for k in ("fl", "fr", "rl", "rr")):
            return
        now = time.time()
        aggiorna_velocita_da_encoder(
            payload["fl"], payload["fr"], payload["rl"], payload["rr"], now
        )

    elif msg.topic == T_CMD:
        cmd = msg.payload.decode().strip().lower()
        if cmd == "start":
            with lock:
                state["running"] = True
            print("[esplorazione] START")
        elif cmd == "stop":
            with lock:
                state["running"] = False
            stop()
            print("[esplorazione] STOP")


# ── MAIN ─────────────────────────────────────────────────────────

def main():
    print("=" * 55)
    print(" Esplorazione autonoma — LagmaBills (reattiva, no odometria)")
    print("=" * 55)
    print(f" Broker: {MQTT_BROKER}:{MQTT_PORT}")
    print(f" Start/Stop: pubblica 'start'/'stop' su {T_CMD}")
    print(f" Stop dist: {STOP_DIST_CM}cm | Brake dist: dinamica "
          f"(min {BRAKE_DIST_MIN_CM}cm, latenza stimata {LATENZA_TOTALE_S*1000:.0f}ms)")
    print("=" * 55)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="esplorazione")
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[esplorazione] Impossibile connettersi: {e}")
        return

    client.loop_start()
    threading.Thread(target=loop_esplorazione, daemon=True).start()

    try:
        while True:
            time.sleep(1)
            with lock:
                print(f"[expl] {'RUN ' if state['running'] else 'STOP'} | "
                      f"mode={state['mode']:16} | "
                      f"v={state['speed_cm_s']:5.1f}cm/s | "
                      f"brake={brake_dist_dinamica():5.1f}cm | "
                      f"F={state['sensors']['FRONTE']:.0f} "
                      f"SX={state['sensors']['SINISTRA']:.0f} "
                      f"DX={state['sensors']['DESTRA']:.0f} "
                      f"CF={state['sensors']['CLIFF_F']:.0f} "
                      f"CR={state['sensors']['CLIFF_R']:.0f}")
    except KeyboardInterrupt:
        print("\n[esplorazione] Interrotto")
        stop()
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()