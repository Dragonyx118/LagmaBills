#!/usr/bin/env python3
"""
xboxPiDirect.py — LagmaBills
Controller Xbox collegato via Bluetooth DIRETTAMENTE al Raspberry Pi,
nessun PC in mezzo. Comandi motori inviati via UDP loopback allo
stesso listener attivo in testI2C.py (porta 5566).

REQUISITO: controller già "paired + trusted" una volta sola
(vedi PAIRING_xbox_bluetooth.md). Dopo il pairing iniziale,
il tasto sync sul controller riconnette da solo via BlueZ —
questo script rileva la riconnessione in automatico (polling
pygame.joystick ogni 2s quando il joystick non è presente) e
riprende a inviare comandi senza bisogno di riavviare nulla.

Lanciato da HIM.py dentro "avvia_generale()", gira per tutta la
durata della sessione: se il controller si disconnette e si
riconnette più volte, lo script si auto-recupera ogni volta.

DIPENDENZE: pip install pygame
"""

import socket
import struct
import time
import sys
import json

try:
    import pygame
except ImportError:
    sys.exit("Installa pygame:  pip install pygame")

try:
    import paho.mqtt.client as mqtt
    MQTT_OK = True
except ImportError:
    MQTT_OK = False
    print("[WARN] paho-mqtt non trovato — switch modalità (Y/X) disabilitato.")

# ── CONFIG ────────────────────────────────────────────────────────
UDP_TARGET = ("127.0.0.1", 5566)   # listener locale dentro testI2C.py

MQTT_BROKER = "localhost"
MQTT_PORT   = 1883
TOPIC_AUDIO_PLAY    = "pi/audio/play"       # testo semplice: solo nome file (mqttMedia.py)
TOPIC_MODALITA_CMD  = "robot/modalita/cmd"  # {"cmd":"switch","modalita":"generale"}

DEADZONE      = 0.15
VEL_MIN       = 50
VEL_MAX       = 127            # UDP mecanum usa int8 -127..127
VEL_STEP      = 10
CONTROLLER_HZ = 20
RECONNECT_POLL_S = 2.0

# ── Mappatura verificata con mapController.py sul controller reale ──
AXIS_SX_H, AXIS_SX_V = 0, 1
AXIS_DX_H, AXIS_DX_V = 2, 3
AXIS_RT, AXIS_LT     = 4, 5     # attenzione: invertiti rispetto allo standard

BTN_A     = 0
BTN_B     = 1
BTN_X     = 3
BTN_Y     = 4
BTN_VIEW  = 10   # "schede"
BTN_MENU  = 11   # "menu"

# ── Modalità cicliche (stesso ordine/nomi di HIM.py) ────────────────
MODALITA_ORDINE = ["generale", "jarvis", "drone", "esplorazione", "linea"]

# File audio di annuncio per modalità — SOSTITUISCI con i nomi reali
AUDIO_PER_MODALITA = {
    "generale":     "youMayAlsoGiveUp.mp4", # poi parte invincible-edit-epic.mp3
    "jarvis":       "welcome_home_jarvis.mp3",
    "drone":        "StartDrone.mp3",
    "esplorazione": "dora-the-explorer.mp3",
    "linea":        "IWANTLAGMABILLS.mp4",
}

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

mqtt_client = None
if MQTT_OK:
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="xboxPiDirect_audio")
    try:
        mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
    except Exception as e:
        print(f"[XBOX-PI] MQTT non disponibile: {e}")
        MQTT_OK = False


# ── UDP helpers (stesso protocollo di testI2C.py) ──────────────────

def invia_motori(vx: int, vy: int, vr: int):
    vx = max(-127, min(127, vx))
    vy = max(-127, min(127, vy))
    vr = max(-127, min(127, vr))
    sock.sendto(struct.pack("<Bbbb", 0x01, vx, vy, vr), UDP_TARGET)


def invia_stop():
    sock.sendto(struct.pack("<B", 0x03), UDP_TARGET)


# ── MQTT helpers — annuncio audio + switch modalità ────────────────

def play_audio(nome_file: str):
    """
    mqttMedia.py si aspetta testo semplice sul topic (NON JSON):
    solo il nome del file, es. "generale.mp3" — cerca da solo
    in data/sounds/music/ e data/sounds/SFX/. Se il file è in una
    sottocartella specifica, usa "music/nome.mp3" o "SFX/nome.mp3".
    """
    if not MQTT_OK:
        return
    mqtt_client.publish(TOPIC_AUDIO_PLAY, nome_file)


def conferma_switch(nome_modalita: str):
    if not MQTT_OK:
        print("[XBOX-PI] MQTT non disponibile, switch modalità ignorato.")
        return
    payload = json.dumps({"cmd": "switch", "modalita": nome_modalita})
    mqtt_client.publish(TOPIC_MODALITA_CMD, payload)
    print(f"[XBOX-PI] Switch confermato → '{nome_modalita}'")


def _apply_deadzone(v: float) -> float:
    if abs(v) < DEADZONE:
        return 0.0
    sign = 1.0 if v > 0 else -1.0
    return sign * (abs(v) - DEADZONE) / (1.0 - DEADZONE)


def _trigger_value(raw: float) -> float:
    return (raw + 1.0) / 2.0


# ── LOOP PRINCIPALE — hotplug automatico ───────────────────────────

def main():
    pygame.init()
    pygame.joystick.init()

    joystick   = None
    vel        = 100          # scala corrente (0..127)
    prev_cmd   = ""
    prev_vx = prev_vy = prev_vr = 0
    lt_was_pressed = rt_was_pressed = False

    # Indice della modalità in anteprima (ciclata con Y, confermata con X)
    modalita_idx = 0

    print("[XBOX-PI] In ascolto — collega/sincronizza il controller quando vuoi.")
    print(f"[XBOX-PI] Comandi motori → UDP {UDP_TARGET}")
    print("[XBOX-PI] Y = cicla modalità (con audio)  |  X = conferma switch")

    while True:
        # ── Nessun joystick: prova a rilevarne uno ──────────────────
        if joystick is None:
            pygame.joystick.quit()
            pygame.joystick.init()
            if pygame.joystick.get_count() > 0:
                joystick = pygame.joystick.Joystick(0)
                joystick.init()
                print(f"[XBOX-PI] Controller connesso: '{joystick.get_name()}' 🎮")
                pygame.event.clear()
            else:
                time.sleep(RECONNECT_POLL_S)
                continue

        # ── Eventi (disconnessione, bottoni) ────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEREMOVED:
                print("\n[XBOX-PI] Controller disconnesso — in attesa di riconnessione...")
                invia_stop()
                joystick = None
                prev_cmd = ""
                break

            if event.type == pygame.JOYBUTTONDOWN:
                if event.button == BTN_A:
                    invia_stop()
                    prev_cmd = "stop"
                    print("\n[XBOX-PI] STOP emergenza (A)")

                elif event.button == BTN_Y:
                    modalita_idx = (modalita_idx + 1) % len(MODALITA_ORDINE)
                    nome = MODALITA_ORDINE[modalita_idx]
                    audio = AUDIO_PER_MODALITA.get(nome)
                    print(f"\n[XBOX-PI] Anteprima modalità: '{nome}'  (X per confermare)")
                    if audio:
                        play_audio(audio)

                elif event.button == BTN_X:
                    nome = MODALITA_ORDINE[modalita_idx]
                    conferma_switch(nome)

        if joystick is None:
            continue

        # ── Lettura assi ─────────────────────────────────────────────
        try:
            num_axes = joystick.get_numaxes()
            def axis(i): return joystick.get_axis(i) if i < num_axes else 0.0
        except Exception:
            print("\n[XBOX-PI] Errore lettura controller — considerato disconnesso.")
            invia_stop()
            joystick = None
            prev_cmd = ""
            continue

        sx_h = _apply_deadzone(axis(AXIS_SX_H))
        sx_v = _apply_deadzone(axis(AXIS_SX_V))
        dx_h = _apply_deadzone(axis(AXIS_DX_H))
        rt   = _trigger_value(axis(AXIS_RT))
        lt   = _trigger_value(axis(AXIS_LT))

        lt_pressed = lt > 0.5
        rt_pressed = rt > 0.5
        if lt_pressed and not lt_was_pressed:
            vel = max(VEL_MIN, vel - VEL_STEP)
            print(f"\n[XBOX-PI] Velocità ↓ = {vel}")
        if rt_pressed and not rt_was_pressed:
            vel = min(VEL_MAX, vel + VEL_STEP)
            print(f"\n[XBOX-PI] Velocità ↑ = {vel}")
        lt_was_pressed, rt_was_pressed = lt_pressed, rt_pressed

        vy =  -sx_v     # avanti/indietro
        vx =   sx_h     # traslazione laterale
        vr =   dx_h     # rotazione

        if vx == 0.0 and vy == 0.0 and vr == 0.0:
            if prev_cmd != "stop":
                invia_stop()
                prev_cmd = "stop"
        else:
            mvx, mvy, mvr = int(vx * vel), int(vy * vel), int(vr * vel)
            if (abs(mvx - prev_vx) >= 3 or abs(mvy - prev_vy) >= 3 or
                    abs(mvr - prev_vr) >= 3 or prev_cmd == "stop"):
                invia_motori(mvx, mvy, mvr)
                prev_cmd = "move"
                prev_vx, prev_vy, prev_vr = mvx, mvy, mvr

        time.sleep(1.0 / CONTROLLER_HZ)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        invia_stop()
        if MQTT_OK and mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        print("\n[XBOX-PI] Interrotto.")