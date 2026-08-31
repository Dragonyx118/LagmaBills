#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║         MQTT ROBOT TESTER — ESP32 Motori Mecanum             ║
║  Broker (Tailscale PC): 100.100.61.49:1883                   ║
║  Topic CMD : robot/motori/cmd                                ║
║  Topic STATO: robot/motori/stato  (ricezione telemetria)     ║
╚══════════════════════════════════════════════════════════════╝

"""

import json
import threading
import time
import sys

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Installa paho-mqtt:  pip install paho-mqtt")
    sys.exit(1)

# ── CONFIGURAZIONE ────────────────────────────────────────────────
BROKER_HOST  = "100.100.61.49"
BROKER_PORT  = 1883
TOPIC_CMD    = "robot/motori/cmd"
TOPIC_STATO  = "robot/motori/stato"
TOPIC_LOG    = "robot/motori/log"

# ── STATO TELEMETRIA ──────────────────────────────────────────────
last_stato: dict = {}

# ─────────────────────────────────────────────────────────────────
#  CALLBACK MQTT
# ─────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] Connesso a {BROKER_HOST}:{BROKER_PORT}")
        client.subscribe(TOPIC_STATO)
        client.subscribe(TOPIC_LOG)
        print(f"[MQTT] Iscritto a {TOPIC_STATO} e {TOPIC_LOG}")
    else:
        print(f"[MQTT] Connessione fallita, rc={rc}")

def on_disconnect(client, userdata, rc, properties=None, reason=None):
    print(f"[MQTT] Disconnesso (rc={rc})")

def on_message(client, userdata, msg):
    global last_stato
    if msg.topic == TOPIC_STATO:
        try:
            last_stato = json.loads(msg.payload.decode())
        except Exception:
            pass
        enc    = f"ENC FL:{last_stato.get('fl',0):6}  FR:{last_stato.get('fr',0):6}  RL:{last_stato.get('rl',0):6}  RR:{last_stato.get('rr',0):6}"
        pwm    = f"PWM FL:{last_stato.get('vfl',0):4}  FR:{last_stato.get('vfr',0):4}  RL:{last_stato.get('vrl',0):4}  RR:{last_stato.get('vrr',0):4}"
        vel    = f"Vel:{last_stato.get('vel',0)}  Stato:{last_stato.get('stato',0)}"
        online = "🟢 ONLINE" if last_stato.get("online") else "🔴 OFFLINE"
        print(f"\r\033[K[TEL] {online}  {enc}  {pwm}  {vel}", end="", flush=True)
    elif msg.topic == TOPIC_LOG:
        print(f"\n[LOG] {msg.payload.decode()}")

# ─────────────────────────────────────────────────────────────────
#  INVIO COMANDI
# ─────────────────────────────────────────────────────────────────

def send(client: mqtt.Client, payload: dict):
    msg = json.dumps(payload)
    client.publish(TOPIC_CMD, msg)
    print(f"\n[TX]  {msg}")

def cmd(client, c: str, **kwargs):
    send(client, {"cmd": c, **kwargs})

# ─────────────────────────────────────────────────────────────────
#  MENU INTERATTIVO
# ─────────────────────────────────────────────────────────────────

HELP = """
╔══════════════════════════════════════════════════════════════════╗
║                    COMANDI DISPONIBILI                           ║
╠══════════════════════════════════════════════════════════════════╣
║  PRESET MOVIMENTO                                                ║
║    w / avanti          → Avanti                                  ║
║    s / indietro        → Indietro                                ║
║    a / sinistra        → Laterale sinistra                       ║
║    d / destra          → Laterale destra                         ║
║    q / ruota_sx        → Rotazione sinistra                      ║
║    e / ruota_dx        → Rotazione destra                        ║
║    x / stop            → STOP                                    ║
╠══════════════════════════════════════════════════════════════════╣
║  DIAGONALI                                                       ║
║    diag_avanti_dx      diag_avanti_sx                            ║
║    diag_indietro_dx    diag_indietro_sx                          ║
╠══════════════════════════════════════════════════════════════════╣
║  VELOCITÀ                                                        ║
║    vel <0-255>         → es: vel 180                             ║
╠══════════════════════════════════════════════════════════════════╣
║  MOTORI SINGOLI (via MQTT) — valori grezzi, nessuna inversione   ║
║    fl <v>   fr <v>   rl <v>   rr <v>   range -255..255           ║
╠══════════════════════════════════════════════════════════════════╣
║  COPPIE                                                          ║
║    sx <v>   dx <v>   ant <v>   post <v>                          ║
║    diag1 <v>   diag2 <v>                                         ║
╠══════════════════════════════════════════════════════════════════╣
║  TUTTI / SET — valori grezzi, nessuna inversione                 ║
║    tutti <v>           → es: tutti 150                           ║
║    set <fl> <fr> <rl> <rr>  → es: set 150 -150 150 -150          ║
╠══════════════════════════════════════════════════════════════════╣
║  MECANUM VETTORIALE                                              ║
║    mecanum <vx> <vy> <vr>   → es: mecanum 0 150 0                ║
╠══════════════════════════════════════════════════════════════════╣
║  ENCODER                                                         ║
║    reset_enc           → Azzera tutti gli encoder                ║
╠══════════════════════════════════════════════════════════════════╣
║  SEQUENZE DI TEST                                                ║
║    test_base           → Avanti/Stop/Indietro/Stop               ║
║    test_rotazioni      → Ruota DX poi SX                         ║
║    test_laterali       → Destra poi Sinistra                     ║
║    test_singoli        → Test ogni motore singolo                ║
╠══════════════════════════════════════════════════════════════════╣
║    help / h  → mostra questo menu                                ║
║    stato     → stampa ultima telemetria                          ║
║    quit      → esci                                              ║
╚══════════════════════════════════════════════════════════════════╝
"""

def print_stato():
    if not last_stato:
        print("\n[INFO] Nessuna telemetria ricevuta ancora.")
        return
    print("\n── Ultima telemetria ──────────────────────────────")
    for k, v in last_stato.items():
        print(f"  {k:10}: {v}")
    print("───────────────────────────────────────────────────")

def run_test_base(client, vel=150):
    print("\n[TEST] Base: Avanti→Stop→Indietro→Stop")
    cmd(client, "velocita", val=vel)
    time.sleep(0.2)
    cmd(client, "avanti"); time.sleep(1.5)
    cmd(client, "stop");   time.sleep(0.5)
    cmd(client, "indietro"); time.sleep(1.5)
    cmd(client, "stop")

def run_test_rotazioni(client, vel=120):
    print("\n[TEST] Rotazioni: DX→Stop→SX→Stop")
    cmd(client, "velocita", val=vel)
    time.sleep(0.2)
    cmd(client, "ruota_dx"); time.sleep(1.0)
    cmd(client, "stop");     time.sleep(0.5)
    cmd(client, "ruota_sx"); time.sleep(1.0)
    cmd(client, "stop")

def run_test_laterali(client, vel=150):
    print("\n[TEST] Laterali: Destra→Stop→Sinistra→Stop")
    cmd(client, "velocita", val=vel)
    time.sleep(0.2)
    cmd(client, "destra");   time.sleep(1.0)
    cmd(client, "stop");     time.sleep(0.5)
    cmd(client, "sinistra"); time.sleep(1.0)
    cmd(client, "stop")

def run_test_singoli(client, vel=120):
    print("\n[TEST] Motori singoli (ogni motore 0.8s) — valori grezzi")
    for motore in ["fl", "fr", "rl", "rr"]:
        print(f"  → {motore.upper()}")
        cmd(client, motore, val=vel)
        time.sleep(0.8)
        cmd(client, motore, val=0)
        time.sleep(0.3)

# ─────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="robot_tester_pc")
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    print(f"[MQTT] Connessione a {BROKER_HOST}:{BROKER_PORT}...")
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    except Exception as e:
        print(f"[ERRORE] Impossibile connettersi: {e}")
        sys.exit(1)

    client.loop_start()
    time.sleep(1.0)

    print(HELP)

    vel_corrente = 150

    try:
        while True:
            try:
                raw = input("\ncmd> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not raw:
                continue

            parts = raw.split()
            p0    = parts[0].lower()

            # ── Quit ──────────────────────────────────────────
            if p0 in ("quit", "exit"):
                break

            # ── Help ──────────────────────────────────────────
            elif p0 in ("help", "h", "?"):
                print(HELP)

            # ── Stato ─────────────────────────────────────────
            elif p0 == "stato":
                print_stato()

            # ── Preset movimento (con inversione FL/RL) ───────
            elif p0 in ("w", "avanti"):
                cmd(client, "avanti")
            elif p0 in ("s", "indietro"):
                cmd(client, "indietro")
            elif p0 in ("a", "sinistra"):
                cmd(client, "sinistra")
            elif p0 in ("d", "destra"):
                cmd(client, "destra")
            elif p0 in ("q", "ruota_sx"):
                cmd(client, "ruota_sx")
            elif p0 in ("e", "ruota_dx"):
                cmd(client, "ruota_dx")
            elif p0 in ("x", "stop"):
                cmd(client, "stop")

            # ── Diagonali (con inversione FL/RL) ──────────────
            elif p0 == "diag_avanti_dx":
                cmd(client, "diag_avanti_dx")
            elif p0 == "diag_avanti_sx":
                cmd(client, "diag_avanti_sx")
            elif p0 == "diag_indietro_dx":
                cmd(client, "diag_indietro_dx")
            elif p0 == "diag_indietro_sx":
                cmd(client, "diag_indietro_sx")

            # ── Velocità globale ──────────────────────────────
            elif p0 == "vel":
                if len(parts) < 2:
                    print("[ERR] Uso: vel <0-255>")
                else:
                    vel_corrente = max(0, min(255, int(parts[1])))
                    cmd(client, "velocita", val=vel_corrente)

            # ── Motori singoli — grezzi, nessuna inversione ───
            elif p0 in ("fl", "fr", "rl", "rr"):
                if len(parts) < 2:
                    print(f"[ERR] Uso: {p0} <-255..255>")
                else:
                    v = max(-255, min(255, int(parts[1])))
                    cmd(client, p0, val=v)

            # ── Coppie — grezze ───────────────────────────────
            elif p0 in ("sx", "dx", "ant", "post", "diag1", "diag2"):
                if len(parts) < 2:
                    print(f"[ERR] Uso: {p0} <-255..255>")
                else:
                    v = max(-255, min(255, int(parts[1])))
                    cmd(client, p0, val=v)

            # ── Tutti — grezzo ────────────────────────────────
            elif p0 == "tutti":
                if len(parts) < 2:
                    print("[ERR] Uso: tutti <-255..255>")
                else:
                    v = max(-255, min(255, int(parts[1])))
                    cmd(client, "tutti", val=v)

            # ── Set individuale — grezzo ──────────────────────
            elif p0 == "set":
                if len(parts) < 5:
                    print("[ERR] Uso: set <fl> <fr> <rl> <rr>")
                else:
                    fl, fr, rl, rr = [max(-255, min(255, int(x))) for x in parts[1:5]]
                    cmd(client, "set", fl=fl, fr=fr, rl=rl, rr=rr)

            # ── Mecanum vettoriale ────────────────────────────
            elif p0 == "mecanum":
                if len(parts) < 4:
                    print("[ERR] Uso: mecanum <vx> <vy> <vr>")
                else:
                    vx, vy, vr = int(parts[1]), int(parts[2]), int(parts[3])
                    cmd(client, "mecanum", vx=vx, vy=vy, vr=vr)

            # ── Reset encoder ─────────────────────────────────
            elif p0 == "reset_enc":
                cmd(client, "reset_enc")

            # ── Sequenze di test ──────────────────────────────
            elif p0 == "test_base":
                t = threading.Thread(target=run_test_base, args=(client, vel_corrente), daemon=True)
                t.start()
            elif p0 == "test_rotazioni":
                t = threading.Thread(target=run_test_rotazioni, args=(client, vel_corrente), daemon=True)
                t.start()
            elif p0 == "test_laterali":
                t = threading.Thread(target=run_test_laterali, args=(client, vel_corrente), daemon=True)
                t.start()
            elif p0 == "test_singoli":
                t = threading.Thread(target=run_test_singoli, args=(client, vel_corrente), daemon=True)
                t.start()

            else:
                print(f"[?] Comando non riconosciuto: '{raw}'  (digita 'help')")

    finally:
        print("\n[MQTT] Stop motori e disconnessione...")
        cmd(client, "stop")
        time.sleep(0.3)
        client.loop_stop()
        client.disconnect()
        print("Ciao!")

if __name__ == "__main__":
    main()