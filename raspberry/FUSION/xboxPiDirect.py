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

DIPENDENZE: pip install pygame paho-mqtt
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
TOPIC_AUDIO_PLAY     = "pi/audio/play"       # testo semplice: solo nome file
TOPIC_VIDEO_PLAY     = "pi/video/play"       # testo semplice: solo nome file
TOPIC_VIDEO_FINISHED = "pi/video/finished"   # pubblicato da mqttMedia.py a fine video
TOPIC_MODALITA_CMD   = "robot/modalita/cmd"  # {"cmd":"switch","modalita":"generale"}
TOPIC_DRONE_CMD      = "drone/cmd/rpyt"      # {"roll","pitch","yaw","thrust"} — testDroneMQTTsecure.py
TOPIC_DRONE_STOP     = "drone/cmd/stop"

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
BTN_VIEW  = 10   # "schede" — ripete la sequenza multimediale della modalità in anteprima
BTN_MENU  = 11   # "menu" — alterna contesto Auto/Braccio (solo in modalità "generale")

# ── Controllo braccio (contesto "braccio") ──────────────────────────
SERVO_RATE_DEG_S = 90     # gradi/secondo alla massima deflessione stick (base/spalla)
SERVO_STEP_DEG   = 5      # gradi per pressione LT/RT sul servo selezionato tra gli "altri"
SERVO_HOME       = {0: 90, 1: 90, 2: 90, 3: 90, 4: 90, 5: 120, 6: 125}
ALTRI_SERVI      = [2, 3, 4, 5, 6]   # ciclati con le freccine su/giù — 6 = telecamera

# ── Controllo drone (valori collaudati da droneWin.py) ──────────────
DRONE_STEP_THRUST = 2000
DRONE_MAX_THRUST  = 60000
DRONE_MIN_THRUST  = 0
DRONE_MAX_ANGLE   = 30.0   # gradi, deflessione roll/pitch/yaw a stick tutto premuto

# ── Modalità cicliche (stesso ordine/nomi di HIM.py) ────────────────
MODALITA_ORDINE = ["generale", "jarvis", "drone", "esplorazione", "linea"]

# Sequenza multimediale per modalità: lista di ("video"|"audio", nomefile).
# Il video ha già il suo audio incluso in sé. "generale" concatena un
# audio DOPO che il video è terminato (gestito via pi/video/finished).
MEDIA_PER_MODALITA = {
    "generale":     [("video", "youMayAlsoGiveUp.mp4"),
                      ("audio", "invincible-edit-epic.mp3")],
    "jarvis":       [("audio", "welcome_home_jarvis.mp3")],
    "drone":        [("audio", "StartDrone.mp3")],
    "esplorazione": [("audio", "dora-the-explorer.mp3")],
    "linea":        [("video", "IWANTLAGMABILLS.mp4")],
}

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ── Stato sequenza multimediale in corso ────────────────────────────
# Traccia quale video stiamo aspettando finisca, per concatenare il
# passo successivo (es. l'audio dopo il video di "generale").
_pending = {"nome": None, "step": 0}

# Modalità CONFERMATA con X (quella davvero attiva sul robot) — usata
# dal tasto "schede" per ripetere la sequenza multimediale corretta.
modalita_attiva = None

mqtt_client = None


def _on_mqtt_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        client.subscribe(TOPIC_VIDEO_FINISHED)


def _on_mqtt_message(client, userdata, msg):
    """Quando un video finisce naturalmente, prosegue alla prossima
    voce della sequenza (es. l'audio dopo il video di 'generale')."""
    if msg.topic != TOPIC_VIDEO_FINISHED:
        return
    file_finito = msg.payload.decode().strip()
    nome = _pending.get("nome")
    step = _pending.get("step")
    if nome is None:
        return
    passi = MEDIA_PER_MODALITA.get(nome, [])
    if step < len(passi) and passi[step][1] == file_finito:
        _play_step(nome, step + 1)


if MQTT_OK:
    mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="xboxPiDirect_audio")
    mqtt_client.on_connect = _on_mqtt_connect
    mqtt_client.on_message = _on_mqtt_message
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


def invia_servo(ch: int, ang: int):
    ang = max(0, min(180, int(ang)))
    sock.sendto(struct.pack("<BBB", 0x02, ch, ang), UDP_TARGET)


# ── MQTT helpers — media (audio/video) + switch modalità ────────────

def play_audio(nome_file: str):
    """mqttMedia.py si aspetta testo semplice: solo il nome file."""
    if not MQTT_OK:
        return
    mqtt_client.publish(TOPIC_AUDIO_PLAY, nome_file)


def play_video(nome_file: str):
    """mqttMedia.py si aspetta testo semplice: solo il nome file."""
    if not MQTT_OK:
        return
    mqtt_client.publish(TOPIC_VIDEO_PLAY, nome_file)


def _play_step(nome: str, step_idx: int):
    """Avvia il passo step_idx della sequenza multimediale di 'nome'."""
    passi = MEDIA_PER_MODALITA.get(nome)
    if not passi or step_idx >= len(passi):
        _pending["nome"] = None
        return

    tipo, file = passi[step_idx]
    if tipo == "video":
        play_video(file)
        _pending["nome"] = nome
        _pending["step"] = step_idx   # aspettiamo che QUESTO video finisca
    else:
        play_audio(file)
        _pending["nome"] = None       # audio non genera un "finished" da aspettare


def play_sequence(nome: str):
    """Avvia (dal primo passo) la sequenza multimediale di una modalità."""
    if nome not in MEDIA_PER_MODALITA:
        return
    _play_step(nome, 0)


def conferma_switch(nome_modalita: str):
    if not MQTT_OK:
        print("[XBOX-PI] MQTT non disponibile, switch modalità ignorato.")
        return
    payload = json.dumps({"cmd": "switch", "modalita": nome_modalita})
    mqtt_client.publish(TOPIC_MODALITA_CMD, payload)
    print(f"[XBOX-PI] Switch confermato → '{nome_modalita}'")


def invia_drone_rpyt(roll: float, pitch: float, yaw: float, thrust: int):
    if not MQTT_OK:
        return
    payload = json.dumps({
        "roll": round(roll, 2), "pitch": round(pitch, 2),
        "yaw": round(yaw, 2), "thrust": int(thrust),
    })
    mqtt_client.publish(TOPIC_DRONE_CMD, payload)


def invia_drone_stop():
    if not MQTT_OK:
        return
    mqtt_client.publish(TOPIC_DRONE_STOP, "1")


def _apply_deadzone(v: float) -> float:
    if abs(v) < DEADZONE:
        return 0.0
    sign = 1.0 if v > 0 else -1.0
    return sign * (abs(v) - DEADZONE) / (1.0 - DEADZONE)


def _trigger_value(raw: float) -> float:
    return (raw + 1.0) / 2.0


# ── LOOP PRINCIPALE — hotplug automatico ───────────────────────────

def main():
    global modalita_attiva

    pygame.init()
    pygame.joystick.init()

    joystick   = None
    vel        = 100          # scala corrente (0..127)
    prev_cmd   = ""
    prev_vx = prev_vy = prev_vr = 0
    lt_was_pressed = rt_was_pressed = False

    # Indice della modalità in anteprima (ciclata con Y, confermata con X)
    modalita_idx = 0

    # Contesto di controllo (solo rilevante in modalità "generale"):
    # "auto" = guida macchina | "braccio" = controllo servo braccio
    contesto = "auto"
    servo_angles = dict(SERVO_HOME)
    altro_idx = 0   # indice in ALTRI_SERVI del servo attualmente selezionato

    # Stato drone
    drone_armato = False
    drone_thrust = 0

    print("[XBOX-PI] In ascolto — collega/sincronizza il controller quando vuoi.")
    print(f"[XBOX-PI] Comandi motori → UDP {UDP_TARGET}")
    print("[XBOX-PI] Y = cicla modalità (con media)  |  X = conferma switch  |  schede = ripeti media")
    print("[XBOX-PI] menu = alterna Auto/Braccio (solo in modalità generale)")
    print("[XBOX-PI] Drone: RT/LT thrust, stick sx=yaw, stick dx=roll/pitch, B=arma/disarma")

    last_tick = time.monotonic()

    while True:
        now = time.monotonic()
        dt = now - last_tick
        last_tick = now

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

        # ── Eventi (disconnessione, bottoni, D-pad) ─────────────────
        for event in pygame.event.get():
            if event.type == pygame.JOYDEVICEREMOVED:
                print("\n[XBOX-PI] Controller disconnesso — in attesa di riconnessione...")
                invia_stop()
                joystick = None
                prev_cmd = ""
                break

            if event.type == pygame.JOYBUTTONDOWN:
                if event.button == BTN_A:
                    if modalita_attiva == "drone":
                        invia_drone_stop()
                        drone_armato = False
                        drone_thrust = 0
                        print("\n[XBOX-PI] STOP emergenza DRONE — disarmato")
                    else:
                        invia_stop()
                        prev_cmd = "stop"
                        print("\n[XBOX-PI] STOP emergenza (A)")

                elif event.button == BTN_B:
                    if modalita_attiva == "drone":
                        drone_armato = not drone_armato
                        if not drone_armato:
                            drone_thrust = 0
                            invia_drone_stop()
                        print(f"\n[XBOX-PI] Drone {'ARMATO ✈️' if drone_armato else 'disarmato'}")

                elif event.button == BTN_Y:
                    modalita_idx = (modalita_idx + 1) % len(MODALITA_ORDINE)
                    nome = MODALITA_ORDINE[modalita_idx]
                    print(f"\n[XBOX-PI] Anteprima modalità: '{nome}'  (X per confermare)")
                    play_sequence(nome)

                elif event.button == BTN_X:
                    nome = MODALITA_ORDINE[modalita_idx]
                    modalita_precedente = modalita_attiva
                    modalita_attiva = nome
                    conferma_switch(nome)

                    if nome != "generale":
                        invia_stop()
                    contesto = "auto"

                    if modalita_precedente == "drone" and nome != "drone":
                        invia_drone_stop()   # sicurezza: se uscivi dal drone in volo
                    if nome == "drone":
                        drone_armato = False   # richiede sempre un nuovo "arma" (B) entrando
                        drone_thrust = 0

                elif event.button == BTN_VIEW:
                    nome = MODALITA_ORDINE[modalita_idx]
                    print(f"\n[XBOX-PI] Ripeto media di '{nome}' (schede)")
                    play_sequence(nome)

                elif event.button == BTN_MENU:
                    if modalita_attiva == "generale":
                        contesto = "braccio" if contesto == "auto" else "auto"
                        invia_stop()   # ferma il carrello quando si passa al braccio (o viceversa)
                        print(f"\n[XBOX-PI] Contesto → {contesto.upper()}")

            elif event.type == pygame.JOYHATMOTION:
                # D-pad: seleziona quale servo tra ALTRI_SERVI controllare (solo in contesto braccio)
                if modalita_attiva == "generale" and contesto == "braccio":
                    _, dy = event.value
                    if dy == 1:
                        altro_idx = (altro_idx + 1) % len(ALTRI_SERVI)
                        print(f"\n[XBOX-PI] Servo selezionato: {ALTRI_SERVI[altro_idx]}")
                    elif dy == -1:
                        altro_idx = (altro_idx - 1) % len(ALTRI_SERVI)
                        print(f"\n[XBOX-PI] Servo selezionato: {ALTRI_SERVI[altro_idx]}")

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
        lt_edge = lt_pressed and not lt_was_pressed
        rt_edge = rt_pressed and not rt_was_pressed
        lt_was_pressed, rt_was_pressed = lt_pressed, rt_pressed

        # ═══════════════════════════════════════════════════════════
        # CONTESTO: modalità "generale" → Auto oppure Braccio
        # ═══════════════════════════════════════════════════════════
        if modalita_attiva == "generale" and contesto == "auto":
            if lt_edge:
                vel = max(VEL_MIN, vel - VEL_STEP)
                print(f"\n[XBOX-PI] Velocità ↓ = {vel}")
            if rt_edge:
                vel = min(VEL_MAX, vel + VEL_STEP)
                print(f"\n[XBOX-PI] Velocità ↑ = {vel}")

            vy = -sx_v      # stick sx verticale → avanti/indietro
            vx = sx_h       # stick sx orizzontale → traslazione dx/sx
            vr = dx_h       # stick dx orizzontale → rotazione

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

        elif modalita_attiva == "generale" and contesto == "braccio":
            # Stick destro → servo 0 (base), stick sinistro → servo 1 (secondo giunto)
            # Controllo a "velocità": lo stick deflesso muove l'angolo nel tempo (dt).
            cambiato = False

            if abs(dx_h) > 0:
                servo_angles[0] += dx_h * SERVO_RATE_DEG_S * dt
                servo_angles[0] = max(0, min(180, servo_angles[0]))
                cambiato = True
            if abs(sx_h) > 0:
                servo_angles[1] += sx_h * SERVO_RATE_DEG_S * dt
                servo_angles[1] = max(0, min(180, servo_angles[1]))
                cambiato = True

            if cambiato:
                invia_servo(0, servo_angles[0])
                invia_servo(1, servo_angles[1])

            # LT/RT muovono a step il servo selezionato tra ALTRI_SERVI
            if lt_edge or rt_edge:
                ch = ALTRI_SERVI[altro_idx]
                delta = -SERVO_STEP_DEG if lt_edge else SERVO_STEP_DEG
                servo_angles[ch] = max(0, min(180, servo_angles[ch] + delta))
                invia_servo(ch, servo_angles[ch])
                print(f"\n[XBOX-PI] Servo {ch} → {int(servo_angles[ch])}°")

        # ═══════════════════════════════════════════════════════════
        # CONTESTO: modalità "drone"
        # ═══════════════════════════════════════════════════════════
        elif modalita_attiva == "drone":
            if lt_edge:
                drone_thrust = max(DRONE_MIN_THRUST, drone_thrust - DRONE_STEP_THRUST)
                print(f"\n[XBOX-PI] Thrust ↓ = {drone_thrust}")
            if rt_edge:
                drone_thrust = min(DRONE_MAX_THRUST, drone_thrust + DRONE_STEP_THRUST)
                print(f"\n[XBOX-PI] Thrust ↑ = {drone_thrust}")

            if drone_armato:
                dx_v = _apply_deadzone(axis(AXIS_DX_V))
                yaw   = sx_h * DRONE_MAX_ANGLE
                roll  = dx_h * DRONE_MAX_ANGLE
                pitch = -dx_v * DRONE_MAX_ANGLE   # stick su = avanti positivo

                # Heartbeat continuo richiesto dal watchdog del bridge (8s timeout)
                invia_drone_rpyt(roll, pitch, yaw, drone_thrust)

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
