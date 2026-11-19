#!/usr/bin/env python3
"""
xboxPiDirect.py — LagmaBills
Controller Xbox collegato via Bluetooth DIRETTAMENTE al Raspberry Pi,
nessun PC in mezzo. Comandi motori inviati via UDP loopback allo
stesso listener attivo in testI2C.py (porta 5566).

REQUISITO: controller già "paired + trusted" una volta sola
(vedi PAIRING_xbox_bluetooth.md).
"""

import socket
import struct
import time
import sys
import json
import os
import subprocess
import signal

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
TOPIC_FACE_PREVIEW   = "robot/face/mode_preview"  # anteprima faccina (Y=nome, X/disco="end")
TOPIC_FACCIA_CMD     = "robot/faccia/cmd"      # "pausa" | "riprendi" — gestito da HIM.py

DEADZONE             = 0.15
DOOM_AXIS_DEADZONE   = 0.35
DOOM_SWAP_COOLDOWN_S = 0.25
DOOM_KEY_HOLD_S      = 0.10
VEL_MIN              = 50
VEL_MAX              = 127            # UDP mecanum usa int8 -127..127
VEL_STEP             = 10
CONTROLLER_HZ        = 20
RECONNECT_POLL_S     = 2.0

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

# Ordine completo possibile dei tasti arma di DOOM (1=Pugno/Motosega, 2=Pistola, 3=Pompa, ecc.)
DOOM_TUTTE_ARMI = ["2", "1", "3", "4", "5", "6", "7"]
# Armi iniziali attive nella rotazione (pistola "2" e pugno/motosega "1")
DOOM_ARMI_INIZIALI = ["2", "1"]

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
MODALITA_ORDINE = ["generale", "jarvis", "drone", "esplorazione", "linea", "doom"]

DOOM_WAD    = os.path.expanduser("~/LBSof/doom/DOOM.WAD")
FACE_SCRIPT = "/home/ladrodirame/FUSION/bepo-animation/main.py"

# Sequenza multimediale per modalità
MEDIA_PER_MODALITA = {
    "generale":     [("video", "youMayAlsoGiveUp.mp4"),
                      ("audio", "invincible-edit-epic.mp3")],
    "jarvis":       [("audio", "welcome_home_jarvis.mp3")],
    "drone":        [("audio", "StartDrone.mp3")],
    "esplorazione": [("audio", "dora-the-explorer.mp3")],
    "linea":        [("video", "IWANTLAGMABILLS.mp4")],
    "doom":         [("audio", "doom-eternal.mp3")],
}

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# ── Stato sequenza multimediale in corso ────────────────────────────
_pending = {"nome": None, "step": 0}
modalita_attiva = None
mqtt_client = None


def _on_mqtt_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        client.subscribe(TOPIC_VIDEO_FINISHED)


def _on_mqtt_message(client, userdata, msg):
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
    if not MQTT_OK:
        return
    mqtt_client.publish(TOPIC_AUDIO_PLAY, nome_file)


def play_video(nome_file: str):
    if not MQTT_OK:
        return
    mqtt_client.publish(TOPIC_VIDEO_PLAY, nome_file)


def _play_step(nome: str, step_idx: int):
    passi = MEDIA_PER_MODALITA.get(nome)
    if not passi or step_idx >= len(passi):
        _pending["nome"] = None
        return

    tipo, file = passi[step_idx]
    if tipo == "video":
        play_video(file)
        _pending["nome"] = nome
        _pending["step"] = step_idx
    else:
        play_audio(file)
        _pending["nome"] = None


def play_sequence(nome: str):
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


# ── Gestione faccina + xdotool per DOOM ────────────────────────────

doom_process = None
_doom_keys_down = set()
_doom_armi_attive = list(DOOM_ARMI_INIZIALI)
_doom_arma_idx = 0
_doom_ultimo_dpad_t = 0.0


def _x11_env() -> dict:
    env = os.environ.copy()
    env["DISPLAY"] = ":0"
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env["SDL_AUDIODRIVER"] = "pipewire"
    xauth = os.path.expanduser("~/.Xauthority")
    if os.path.exists(xauth) and "XAUTHORITY" not in env:
        env["XAUTHORITY"] = xauth
    env.pop("SDL_VIDEODRIVER", None)
    return env


def _xorg_attivo() -> bool:
    res = subprocess.run(
        ["pgrep", "-f", "Xorg.*:0"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    return res.returncode == 0


def _garantisci_xorg():
    """Avvia un server X su :0 se non è già attivo, senza legarlo alla faccina."""
    if _xorg_attivo():
        return
    subprocess.Popen(
        ["xinit", "/bin/sleep", "infinity", "--", ":0", "vt1"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True
    )
    for _ in range(25):
        if _xorg_attivo():
            time.sleep(0.5)
            return
        time.sleep(0.2)


def spegni_faccia():
    """Invia pausa via MQTT e ferma solo lo script della faccina (Xorg resta su :0)."""
    if MQTT_OK:
        mqtt_client.publish(TOPIC_FACCIA_CMD, "pausa")
    subprocess.run(
        ["pkill", "-f", "bepo-animation/main.py"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    time.sleep(0.3)
    subprocess.run(
        ["pkill", "-9", "-f", "bepo-animation/main.py"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    print("\n[XBOX-PI] Faccia spenta/fermata (Xorg su :0 mantenuto attivo)")


def riattiva_faccia():
    """Riprende la faccina via MQTT e, se non gira, la rilancia su :0."""
    if MQTT_OK:
        mqtt_client.publish(TOPIC_FACCIA_CMD, "riprendi")
    faccia_attiva = subprocess.run(
        ["pgrep", "-f", "bepo-animation/main.py"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    ).returncode == 0
    if not faccia_attiva and os.path.exists(FACE_SCRIPT):
        _garantisci_xorg()
        subprocess.Popen(
            ["/usr/bin/python3", FACE_SCRIPT],
            env=_x11_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True
        )
    print("[XBOX-PI] Faccia riattivata")


def xdotool_key_state(key_name: str, pressed: bool):
    """Invia keydown o keyup su DISPLAY=:0 solo quando lo stato cambia."""
    attivo = key_name in _doom_keys_down
    if pressed == attivo:
        return
    azione = "keydown" if pressed else "keyup"
    try:
        subprocess.run(
            ["xdotool", azione, key_name],
            env=_x11_env(),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=1.0
        )
        if pressed:
            _doom_keys_down.add(key_name)
        else:
            _doom_keys_down.discard(key_name)
    except Exception as e:
        print(f"\n[XBOX-PI] Errore xdotool ({azione} {key_name}): {e}")


def xdotool_tap_key(key_name: str, hold_s: float = DOOM_KEY_HOLD_S):
    """Invia keydown, attende hold_s e invia keyup su DISPLAY=:0."""
    env = _x11_env()
    try:
        r1 = subprocess.run(
            ["xdotool", "keydown", key_name],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1.0
        )
        time.sleep(hold_s)
        r2 = subprocess.run(
            ["xdotool", "keyup", key_name],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=1.0
        )
        if r1.returncode != 0 or r2.returncode != 0:
            err = (r1.stderr or r2.stderr).strip()
            print(f"\n[XBOX-PI] xdotool warning ({key_name}): {err}")
    except Exception as e:
        print(f"\n[XBOX-PI] Errore xdotool ({key_name}): {e}")


def rilascia_tutti_tasti_doom():
    for key_name in list(_doom_keys_down):
        xdotool_key_state(key_name, False)
    _doom_keys_down.clear()


def _reset_armi_doom():
    global _doom_armi_attive, _doom_arma_idx
    _doom_armi_attive = list(DOOM_ARMI_INIZIALI)
    _doom_arma_idx = 0


def _aggiungi_arma_doom():
    global _doom_armi_attive, _doom_arma_idx
    for arma in DOOM_TUTTE_ARMI:
        if arma not in _doom_armi_attive:
            _doom_armi_attive.append(arma)
            _doom_arma_idx = len(_doom_armi_attive) - 1
            xdotool_tap_key(arma)
            print(f"\n[XBOX-PI] DOOM +arma '{arma}' → slot attivi: {_doom_armi_attive}")
            return
    print(f"\n[XBOX-PI] DOOM tutte le armi già aggiunte: {_doom_armi_attive}")


def _rimuovi_arma_doom():
    global _doom_armi_attive, _doom_arma_idx
    if len(_doom_armi_attive) <= len(DOOM_ARMI_INIZIALI):
        print(f"\n[XBOX-PI] DOOM slot minimi attivi: {_doom_armi_attive}")
        return
    rimossa = _doom_armi_attive.pop()
    _doom_arma_idx = min(_doom_arma_idx, len(_doom_armi_attive) - 1)
    arma_corrente = _doom_armi_attive[_doom_arma_idx]
    xdotool_tap_key(arma_corrente)
    print(f"\n[XBOX-PI] DOOM -arma '{rimossa}' → attiva '{arma_corrente}' | slot: {_doom_armi_attive}")


def avvia_doom():
    global doom_process, _doom_ultimo_dpad_t
    if doom_process is not None:
        return
    _reset_armi_doom()
    _doom_ultimo_dpad_t = 0.0
    invia_stop()
    spegni_faccia()
    _garantisci_xorg()
    doom_process = subprocess.Popen(
        ["chocolate-doom", "-iwad", DOOM_WAD, "-fullscreen"],
        env=_x11_env(),
        preexec_fn=os.setsid
    )
    print("\n[XBOX-PI] 🔫 DOOM avviato su :0 — D-pad su/giù swap, dx/sx +/- arma, MENU esce")


def ferma_doom():
    global doom_process
    rilascia_tutti_tasti_doom()
    if doom_process is not None:
        try:
            os.killpg(os.getpgid(doom_process.pid), signal.SIGTERM)
        except Exception:
            pass
        doom_process = None
        print("\n[XBOX-PI] DOOM terminato")
    riattiva_faccia()


def face_preview(nome_modalita: str):
    if not MQTT_OK:
        return
    mqtt_client.publish(TOPIC_FACE_PREVIEW, nome_modalita)


def face_preview_end():
    if not MQTT_OK:
        return
    mqtt_client.publish(TOPIC_FACE_PREVIEW, "end")


def _apply_deadzone(v: float, dz: float = DEADZONE) -> float:
    if abs(v) < dz:
        return 0.0
    sign = 1.0 if v > 0 else -1.0
    return sign * (abs(v) - dz) / (1.0 - dz)


def _trigger_value(raw: float) -> float:
    return (raw + 1.0) / 2.0


# ── LOOP PRINCIPALE — hotplug automatico ───────────────────────────

def main():
    global modalita_attiva, doom_process, _doom_arma_idx, _doom_ultimo_dpad_t

    pygame.init()
    pygame.joystick.init()

    joystick   = None
    vel        = 100
    prev_cmd   = ""
    prev_vx = prev_vy = prev_vr = 0
    lt_was_pressed = rt_was_pressed = False

    modalita_idx = 0
    contesto = "auto"
    servo_angles = dict(SERVO_HOME)
    altro_idx = 0

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

        # Se DOOM è stato chiuso dall'interno, ripristina faccina e modalità generale
        if doom_process is not None and doom_process.poll() is not None:
            print("\n[XBOX-PI] DOOM chiuso dall'interno — ripristino faccina")
            rilascia_tutti_tasti_doom()
            doom_process = None
            riattiva_faccia()
            modalita_attiva = "generale"
            modalita_idx = MODALITA_ORDINE.index("generale")
            conferma_switch("generale")

        # Prova a rilevare il joystick
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
                rilascia_tutti_tasti_doom()
                invia_stop()
                face_preview_end()
                joystick = None
                prev_cmd = ""
                break

            if event.type == pygame.JOYBUTTONDOWN:
                # Modalità DOOM attiva: MENU esce, gli altri bottoni inviano tasti via xdotool
                if modalita_attiva == "doom" and doom_process is not None:
                    if event.button == BTN_MENU:
                        ferma_doom()
                        modalita_attiva = "generale"
                        modalita_idx = MODALITA_ORDINE.index("generale")
                        conferma_switch("generale")
                        print("\n[XBOX-PI] Uscito da DOOM → modalità GENERALE")
                    elif event.button == BTN_A:
                        xdotool_key_state("Control_L", True)
                    elif event.button == BTN_B:
                        xdotool_key_state("space", True)
                    elif event.button == BTN_X:
                        xdotool_key_state("Return", True)
                    elif event.button == BTN_Y:
                        xdotool_key_state("Escape", True)
                    elif event.button == BTN_VIEW:
                        xdotool_key_state("Tab", True)
                    continue

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
                    face_preview(nome)

                elif event.button == BTN_X:
                    nome = MODALITA_ORDINE[modalita_idx]
                    modalita_precedente = modalita_attiva
                    modalita_attiva = nome
                    face_preview_end()

                    if nome == "doom":
                        invia_stop()
                        if modalita_precedente == "drone":
                            invia_drone_stop()
                        avvia_doom()
                    else:
                        conferma_switch(nome)

                        if nome != "generale":
                            invia_stop()
                        contesto = "auto"

                        if modalita_precedente == "drone" and nome != "drone":
                            invia_drone_stop()
                        if nome == "drone":
                            drone_armato = False
                            drone_thrust = 0

                        if modalita_precedente == "doom":
                            ferma_doom()

                elif event.button == BTN_VIEW:
                    nome = MODALITA_ORDINE[modalita_idx]
                    print(f"\n[XBOX-PI] Ripeto media di '{nome}' (schede)")
                    play_sequence(nome)

                elif event.button == BTN_MENU:
                    if modalita_attiva == "generale":
                        contesto = "braccio" if contesto == "auto" else "auto"
                        invia_stop()
                        print(f"\n[XBOX-PI] Contesto → {contesto.upper()}")

            elif event.type == pygame.JOYBUTTONUP:
                if modalita_attiva == "doom" and doom_process is not None:
                    if event.button == BTN_A:
                        xdotool_key_state("Control_L", False)
                    elif event.button == BTN_B:
                        xdotool_key_state("space", False)
                    elif event.button == BTN_X:
                        xdotool_key_state("Return", False)
                    elif event.button == BTN_Y:
                        xdotool_key_state("Escape", False)
                    elif event.button == BTN_VIEW:
                        xdotool_key_state("Tab", False)

            elif event.type == pygame.JOYHATMOTION:
                dx, dy = event.value
                if modalita_attiva == "doom" and doom_process is not None:
                    now_dpad = time.monotonic()
                    if (now_dpad - _doom_ultimo_dpad_t) >= DOOM_SWAP_COOLDOWN_S:
                        if dx == 1:
                            _doom_ultimo_dpad_t = now_dpad
                            _aggiungi_arma_doom()
                        elif dx == -1:
                            _doom_ultimo_dpad_t = now_dpad
                            _rimuovi_arma_doom()
                        elif dy in (1, -1) and _doom_armi_attive:
                            _doom_ultimo_dpad_t = now_dpad
                            if dy == 1:
                                _doom_arma_idx = (_doom_arma_idx + 1) % len(_doom_armi_attive)
                            else:
                                _doom_arma_idx = (_doom_arma_idx - 1) % len(_doom_armi_attive)
                            arma = _doom_armi_attive[_doom_arma_idx]
                            xdotool_tap_key(arma)
                            print(f"\n[XBOX-PI] DOOM arma → {arma} ({_doom_armi_attive})")
                elif modalita_attiva == "generale" and contesto == "braccio":
                    if dy == 1:
                        altro_idx = (altro_idx + 1) % len(ALTRI_SERVI)
                        print(f"\n[XBOX-PI] Servo selezionato: {ALTRI_SERVI[altro_idx]}")
                    elif dy == -1:
                        altro_idx = (altro_idx - 1) % len(ALTRI_SERVI)
                        print(f"\n[XBOX-PI] Servo selezionato: {ALTRI_SERVI[altro_idx]}")

        if joystick is None:
            continue

        # ── Lettura assi
        try:
            num_axes = joystick.get_numaxes()
            def axis(i): return joystick.get_axis(i) if i < num_axes else 0.0
        except Exception:
            print("\n[XBOX-PI] Errore lettura controller — considerato disconnesso.")
            rilascia_tutti_tasti_doom()
            invia_stop()
            face_preview_end()
            joystick = None
            prev_cmd = ""
            continue

        # Modalità DOOM: stick sx = avanti/indietro + strafe (comma/period), stick dx = gira (Left/Right), LT = corsa, RT = sparo
        if modalita_attiva == "doom" and doom_process is not None:
            sx_h = _apply_deadzone(axis(AXIS_SX_H), DOOM_AXIS_DEADZONE)
            sx_v = _apply_deadzone(axis(AXIS_SX_V), DOOM_AXIS_DEADZONE)
            dx_h = _apply_deadzone(axis(AXIS_DX_H), DOOM_AXIS_DEADZONE)
            rt   = _trigger_value(axis(AXIS_RT))
            lt   = _trigger_value(axis(AXIS_LT))

            xdotool_key_state("Up", sx_v < 0.0)
            xdotool_key_state("Down", sx_v > 0.0)

            xdotool_key_state("comma", sx_h < 0.0)
            xdotool_key_state("period", sx_h > 0.0)

            xdotool_key_state("Left", dx_h < 0.0)
            xdotool_key_state("Right", dx_h > 0.0)

            xdotool_key_state("Shift_L", lt > 0.5)
            xdotool_key_state("Control_L", (rt > 0.5) or (joystick.get_button(BTN_A) if joystick.get_numbuttons() > BTN_A else False))

            time.sleep(1.0 / CONTROLLER_HZ)
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
        # CONTESTO: modalità "generale" → Auto oppure Braccio tramite tasto menù
        # ═══════════════════════════════════════════════════════════
        if modalita_attiva == "generale" and contesto == "auto":
            if lt_edge:
                vel = max(VEL_MIN, vel - VEL_STEP)
                print(f"\n[XBOX-PI] Velocità ↓ = {vel}")
            if rt_edge:
                vel = min(VEL_MAX, vel + VEL_STEP)
                print(f"\n[XBOX-PI] Velocità ↑ = {vel}")

            vy = -sx_v
            vx = sx_h
            vr = dx_h

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
                pitch = -dx_v * DRONE_MAX_ANGLE

                invia_drone_rpyt(roll, pitch, yaw, drone_thrust)

        time.sleep(1.0 / CONTROLLER_HZ)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        rilascia_tutti_tasti_doom()
        invia_stop()
        ferma_doom()
        face_preview_end()
        if MQTT_OK and mqtt_client:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
        print("\n[XBOX-PI] Interrotto.")