#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║      UDP ROBOT TESTER — ESP32 Motori Mecanum                 ║
║      + Controller Xbox Series S (Bluetooth/USB) via PC       ║
║      + Soglie sicurezza / telemetria ancora su MQTT           ║
╚══════════════════════════════════════════════════════════════╝

Movimento (preset, mecanum, controller Xbox) → UDP diretto al Pi,
bassa latenza, bypassa il broker.
Soglie sicurezza / telemetria / log → restano su MQTT (non critici
sulla latenza, riusano i topic già esistenti sul Pi).

DIPENDENZE: pip install paho-mqtt pygame
"""

import json
import threading
import time
import sys
import socket
import struct

try:
    import paho.mqtt.client as mqtt
except ImportError:
    sys.exit("Installa paho-mqtt:  pip install paho-mqtt")

try:
    import pygame
    PYGAME_OK = True
except ImportError:
    PYGAME_OK = False
    print("[WARN] pygame non trovato — controller Xbox disabilitato.")

# ── CONFIGURAZIONE ────────────────────────────────────────────────
PI_IP        = "100.100.61.49"   # Tailscale IP del Pi (LagmaBills)
UDP_CMD_PORT = 5566              # stesso listener di testI2C.py

BROKER_HOST  = "100.100.61.49"
BROKER_PORT  = 1883
TOPIC_STATO  = "robot/motori/stato"
TOPIC_LOG    = "robot/motori/log"
TOPIC_SOGLIE = "robot/motori/soglie"
TOPIC_SOGLIE_CMD = "robot/motori/cmd"   # set_soglie/get_soglie restano MQTT

# Controller
DEADZONE      = 0.15
VEL_STEP      = 10
VEL_MIN       = 20
VEL_MAX       = 127          # UDP mecanum: int8 -127..127
CONTROLLER_HZ = 20

AXIS_SX_H, AXIS_SX_V = 0, 1
AXIS_DX_H            = 2
AXIS_LT, AXIS_RT     = 4, 5
BTN_A, BTN_B, BTN_START = 0, 1, 7

# ── STATO GLOBALE ─────────────────────────────────────────────────
last_stato:  dict = {}
last_soglie: dict = {}
vel_corrente: int = 90        # scala -127..127 per UDP
xbox_attivo: bool = False
_controller_thread = None
_controller_stop   = threading.Event()
_vel_lock = threading.Lock()

sock_udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ─────────────────────────────────────────────────────────────────
#  UDP — comandi motori (bassa latenza)
# ─────────────────────────────────────────────────────────────────

def udp_motori(vx: int, vy: int, vr: int):
    vx = max(-127, min(127, vx))
    vy = max(-127, min(127, vy))
    vr = max(-127, min(127, vr))
    pkt = struct.pack("<Bbbb", 0x01, vx, vy, vr)
    sock_udp.sendto(pkt, (PI_IP, UDP_CMD_PORT))


def udp_stop():
    sock_udp.sendto(struct.pack("<B", 0x03), (PI_IP, UDP_CMD_PORT))


def udp_servo(ch: int, ang: int):
    pkt = struct.pack("<BBB", 0x02, ch, ang)
    sock_udp.sendto(pkt, (PI_IP, UDP_CMD_PORT))


# Preset di movimento → tradotti in vx,vy,vr e mandati via UDP
_PRESET_VXVYVR = {
    "avanti":            ( 0,  1,  0),
    "indietro":          ( 0, -1,  0),
    "sinistra":          (-1,  0,  0),
    "destra":            ( 1,  0,  0),
    "ruota_sx":          ( 0,  0, -1),
    "ruota_dx":          ( 0,  0,  1),
    "diag_avanti_dx":    ( 1,  1,  0),
    "diag_avanti_sx":    (-1,  1,  0),
    "diag_indietro_dx":  ( 1, -1,  0),
    "diag_indietro_sx":  (-1, -1,  0),
}


def cmd_movimento(nome: str):
    if nome == "stop":
        udp_stop()
        print(f"[TX-UDP] stop")
        return
    if nome not in _PRESET_VXVYVR:
        print(f"[ERR] Preset sconosciuto: {nome}")
        return
    sx, sy, sr = _PRESET_VXVYVR[nome]
    with _vel_lock:
        v = vel_corrente
    udp_motori(sx * v, sy * v, sr * v)
    print(f"[TX-UDP] {nome} → vx={sx*v} vy={sy*v} vr={sr*v}")


# ─────────────────────────────────────────────────────────────────
#  MQTT — soglie / telemetria (non motion-critical)
# ─────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] Connesso a {BROKER_HOST}:{BROKER_PORT}")
        client.subscribe(TOPIC_STATO)
        client.subscribe(TOPIC_LOG)
        client.subscribe(TOPIC_SOGLIE)
    else:
        print(f"[MQTT] Connessione fallita rc={rc}")


def on_message(client, userdata, msg):
    global last_stato, last_soglie
    if msg.topic == TOPIC_STATO:
        try:
            last_stato = json.loads(msg.payload.decode())
        except Exception:
            pass
        enc = (f"FL:{last_stato.get('fl',0):6} FR:{last_stato.get('fr',0):6} "
               f"RL:{last_stato.get('rl',0):6} RR:{last_stato.get('rr',0):6}")
        online = "🟢" if last_stato.get("online") else "🔴"
        xbox_ind = "🎮" if xbox_attivo else "  "
        with _vel_lock:
            v_cur = vel_corrente
        print(f"\r\033[K[TEL]{online}{xbox_ind} ENC {enc} | vel_locale={v_cur}",
              end="", flush=True)

    elif msg.topic == TOPIC_SOGLIE:
        try:
            last_soglie = json.loads(msg.payload.decode())
            keys = ["fronte", "retro", "sinistra", "destra", "cliff_f", "cliff_r"]
            vals = "  ".join(f"{k}={last_soglie.get(k,'?')}" for k in keys)
            print(f"\n[SOGLIE] {vals}")
        except Exception:
            pass

    elif msg.topic == TOPIC_LOG:
        print(f"\n[LOG] {msg.payload.decode()}")


SOGLIE_KEYS = ["fronte", "retro", "sinistra", "destra", "cliff_f", "cliff_r"]


def cmd_soglie(client, parts: list):
    if not parts:
        client.publish(TOPIC_SOGLIE_CMD, json.dumps({"cmd": "get_soglie"}))
        return
    sub = parts[0].lower()
    if sub in ("on", "reset"):
        defaults = dict(zip(SOGLIE_KEYS, [20, 15, 10, 10, 10, 10]))
        client.publish(TOPIC_SOGLIE_CMD, json.dumps({"cmd": "set_soglie", **defaults}))
        return
    if sub == "off":
        zeros = {k: 0 for k in SOGLIE_KEYS}
        client.publish(TOPIC_SOGLIE_CMD, json.dumps({"cmd": "set_soglie", **zeros}))
        return
    payload = {"cmd": "set_soglie"}
    for p in parts:
        if "=" in p:
            k, _, v = p.partition("=")
            if k in SOGLIE_KEYS:
                payload[k] = max(0, min(255, int(v)))
    if len(payload) > 1:
        client.publish(TOPIC_SOGLIE_CMD, json.dumps(payload))


# ─────────────────────────────────────────────────────────────────
#  CONTROLLER XBOX — thread dedicato (comandi via UDP)
# ─────────────────────────────────────────────────────────────────

def _apply_deadzone(v: float) -> float:
    if abs(v) < DEADZONE:
        return 0.0
    sign = 1.0 if v > 0 else -1.0
    return sign * (abs(v) - DEADZONE) / (1.0 - DEADZONE)


def _trigger_value(raw: float) -> float:
    return (raw + 1.0) / 2.0


def controller_loop(stop_event: threading.Event):
    global xbox_attivo, vel_corrente

    if not PYGAME_OK:
        return

    pygame.init()
    pygame.joystick.init()
    joystick = None
    prev_cmd = ""
    prev_vx = prev_vy = prev_vr = 0
    lt_was_pressed = rt_was_pressed = False

    print("\n[XBOX] Thread controller avviato, cerco joystick...")

    while not stop_event.is_set():
        if joystick is None:
            pygame.joystick.quit()
            pygame.joystick.init()
            if pygame.joystick.get_count() > 0:
                joystick = pygame.joystick.Joystick(0)
                joystick.init()
                print(f"\n[XBOX] Trovato: '{joystick.get_name()}' 🎮")
                xbox_attivo = True
                pygame.event.clear()
            else:
                time.sleep(2.0)
                continue

        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEREMOVED:
                print("\n[XBOX] Controller disconnesso.")
                joystick = None
                xbox_attivo = False
                udp_stop()
                prev_cmd = ""
                break
            if event.type == pygame.JOYBUTTONDOWN:
                if event.button == BTN_A:
                    udp_stop()
                    print("\n[XBOX] STOP emergenza (A)")
                    prev_cmd = "stop"
                elif event.button in (BTN_B, BTN_START):
                    xbox_attivo = False
                    udp_stop()
                    print("\n[XBOX] Controller DISATTIVATO")
                    stop_event.set()
                    return

        if joystick is None:
            continue

        try:
            num_axes = joystick.get_numaxes()
            def axis(i): return joystick.get_axis(i) if i < num_axes else 0.0
        except Exception:
            joystick = None
            xbox_attivo = False
            udp_stop()
            continue

        sx_h = _apply_deadzone(axis(AXIS_SX_H))
        sx_v = _apply_deadzone(axis(AXIS_SX_V))
        dx_h = _apply_deadzone(axis(AXIS_DX_H))
        lt_raw, rt_raw = _trigger_value(axis(AXIS_LT)), _trigger_value(axis(AXIS_RT))

        lt_pressed, rt_pressed = lt_raw > 0.5, rt_raw > 0.5
        if lt_pressed and not lt_was_pressed:
            with _vel_lock:
                vel_corrente = max(VEL_MIN, vel_corrente - VEL_STEP)
            print(f"\n[XBOX] Velocità ↓ = {vel_corrente}")
        if rt_pressed and not rt_was_pressed:
            with _vel_lock:
                vel_corrente = min(VEL_MAX, vel_corrente + VEL_STEP)
            print(f"\n[XBOX] Velocità ↑ = {vel_corrente}")
        lt_was_pressed, rt_was_pressed = lt_pressed, rt_pressed

        vy, vx, vr = -sx_v, sx_h, dx_h

        if vx == 0.0 and vy == 0.0 and vr == 0.0:
            if prev_cmd != "stop":
                udp_stop()
                prev_cmd = "stop"
        else:
            with _vel_lock:
                v_scale = vel_corrente
            mvx, mvy, mvr = int(vx * v_scale), int(vy * v_scale), int(vr * v_scale)
            if (abs(mvx - prev_vx) >= 3 or abs(mvy - prev_vy) >= 3 or
                    abs(mvr - prev_vr) >= 3 or prev_cmd == "stop"):
                udp_motori(mvx, mvy, mvr)
                prev_cmd = "move"
                prev_vx, prev_vy, prev_vr = mvx, mvy, mvr

        time.sleep(1.0 / CONTROLLER_HZ)

    xbox_attivo = False
    print("\n[XBOX] Thread controller terminato.")


def start_controller():
    global _controller_thread, _controller_stop, xbox_attivo
    if not PYGAME_OK:
        print("[ERR] pygame non installato.")
        return
    if _controller_thread and _controller_thread.is_alive():
        print("[INFO] Controller già attivo.")
        return
    _controller_stop = threading.Event()
    _controller_thread = threading.Thread(target=controller_loop, args=(_controller_stop,), daemon=True)
    _controller_thread.start()
    xbox_attivo = True
    print("[XBOX] Controller avviato.")


def stop_controller():
    global xbox_attivo
    _controller_stop.set()
    xbox_attivo = False
    udp_stop()
    print("[XBOX] Controller disattivato.")


# ─────────────────────────────────────────────────────────────────
#  MENU (invariato nello spirito, movimento ora via UDP)
# ─────────────────────────────────────────────────────────────────

HELP = """
COMANDI:
  xbox on|off|stato
  w/avanti  s/indietro  a/sinistra  d/destra  q/ruota_sx  e/ruota_dx  x/stop
  diag_avanti_dx  diag_avanti_sx  diag_indietro_dx  diag_indietro_sx
  vel <0-127>              → velocità locale per preset/controller
  mecanum <vx> <vy> <vr>   → -127..127, invio UDP diretto
  soglie [on|off|reset|fronte=20 ...]   → via MQTT
  stato                    → ultima telemetria
  quit / exit
"""


def print_stato():
    if not last_stato:
        print("\n[INFO] Nessuna telemetria ricevuta ancora.")
        return
    print("\n── Telemetria ──────────────────────")
    for k, v in last_stato.items():
        print(f"  {k:10}: {v}")
    if last_soglie:
        print("── Soglie ──────────────────────────")
        for k in SOGLIE_KEYS:
            print(f"  {k:12}: {last_soglie.get(k, '?')}")


def main():
    global vel_corrente

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="robot_tester_pc_udp")
    client.on_connect = on_connect
    client.on_message = on_message

    print(f"[MQTT] Connessione a {BROKER_HOST}:{BROKER_PORT} (soglie/telemetria)...")
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    except Exception as e:
        print(f"[WARN] MQTT non disponibile: {e} (movimento via UDP funziona comunque)")

    client.loop_start()
    time.sleep(0.5)
    client.publish(TOPIC_SOGLIE_CMD, json.dumps({"cmd": "get_soglie"}))

    print(f"[UDP] Comandi motori → {PI_IP}:{UDP_CMD_PORT}")
    print(HELP)

    try:
        while True:
            try:
                raw = input("\ncmd> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not raw:
                continue
            parts = raw.split()
            p0 = parts[0].lower()

            if p0 in ("quit", "exit"):
                break
            elif p0 in ("help", "h", "?"):
                print(HELP)
            elif p0 == "stato":
                print_stato()
            elif p0 == "soglie":
                cmd_soglie(client, parts[1:])
            elif p0 == "xbox":
                sub = parts[1].lower() if len(parts) > 1 else ""
                if sub == "on": start_controller()
                elif sub == "off": stop_controller()
                elif sub == "stato": print(f"[XBOX] attivo: {xbox_attivo}")
                else: print("[ERR] Uso: xbox on|off|stato")
            elif p0 in ("w", "avanti"):    cmd_movimento("avanti")
            elif p0 in ("s", "indietro"):  cmd_movimento("indietro")
            elif p0 in ("a", "sinistra"):  cmd_movimento("sinistra")
            elif p0 in ("d", "destra"):    cmd_movimento("destra")
            elif p0 in ("q", "ruota_sx"):  cmd_movimento("ruota_sx")
            elif p0 in ("e", "ruota_dx"):  cmd_movimento("ruota_dx")
            elif p0 in ("x", "stop"):      cmd_movimento("stop")
            elif p0 in _PRESET_VXVYVR:     cmd_movimento(p0)
            elif p0 == "vel":
                if len(parts) < 2:
                    print("[ERR] Uso: vel <0-127>")
                else:
                    with _vel_lock:
                        vel_corrente = max(0, min(127, int(parts[1])))
                    print(f"Velocità = {vel_corrente}")
            elif p0 == "mecanum":
                if len(parts) < 4:
                    print("[ERR] Uso: mecanum <vx> <vy> <vr>")
                else:
                    vx, vy, vr = int(parts[1]), int(parts[2]), int(parts[3])
                    udp_motori(vx, vy, vr)
                    print(f"[TX-UDP] mecanum vx={vx} vy={vy} vr={vr}")
            else:
                print(f"[?] Comando non riconosciuto: '{raw}'")

    finally:
        print("\n[UDP] Stop motori...")
        _controller_stop.set()
        udp_stop()
        time.sleep(0.2)
        client.loop_stop()
        client.disconnect()
        if PYGAME_OK:
            pygame.quit()
        print("Ciao!")


if __name__ == "__main__":
    main()
