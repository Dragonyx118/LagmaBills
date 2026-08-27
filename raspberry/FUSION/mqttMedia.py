#!/usr/bin/env python3
"""
mqttMedia.py — LagmaBills
Gestisce riproduzione audio, video e immagini via MQTT con debug avanzato.
"""

import os
import json
import subprocess
import paho.mqtt.client as mqtt

# ── CONFIGURAZIONE ───────────────────────────────────────────────
MQTT_BROKER   = "100.100.61.49"
MQTT_PORT     = 1883
AUDIO_BASE    = "/home/ladrodirame/data/sounds"
VIDEO_BASE    = "/home/ladrodirame/data/videos"
STEREO_MAC    = "DD:23:A5:42:C3:92"

TOPIC_AUDIO_MUSIC_LIST = "pi/audio/sounds/list"
TOPIC_AUDIO_SFX_LIST   = "pi/audio/sfx/list"

TOPIC_AUDIO_PLAY    = "pi/audio/play"
TOPIC_AUDIO_STOP    = "pi/audio/stop"
TOPIC_AUDIO_VOLUME  = "pi/audio/volume"
TOPIC_AUDIO_REFRESH = "pi/audio/refresh"
TOPIC_VIDEO_PLAY    = "pi/video/play"
TOPIC_VIDEO_STOP    = "pi/video/stop"
TOPIC_VIDEO_LIST    = "pi/video/list"

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".webm")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".opus", ".aiff", ".aac")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")

# ── STATO GLOBALE ────────────────────────────────────────────────
current_proc = None

# ── BLUETOOTH & AUDIO DIAGNOSTIC ─────────────────────────────────

def connect_bluetooth():
    print(f"[BLUETOOTH] Tentativo di connessione a {STEREO_MAC}...")
    subprocess.run(
        ["bluetoothctl", "connect", STEREO_MAC],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

def get_bluetooth_sink() -> str | None:
    try:
        out = subprocess.check_output(
            ["pactl", "list", "short", "sinks"], text=True
        )
        mac_under = STEREO_MAC.replace(":", "_")
        for line in out.splitlines():
            if mac_under.lower() in line.lower():
                return line.split()[1]
    except Exception as e:
        print(f"[DEBUG AUDIO] Errore nella lettura dei sink pulse: {e}")
    return None

def check_audio_status() -> str:
    """Controlla se lo stereo è connesso e restituisce il device mpv appropriato."""
    connect_bluetooth()
    bt_sink = get_bluetooth_sink()
    if bt_sink:
        print(f"[DEBUG AUDIO] Stereo Connesso! Sink trovato: {bt_sink}")
        return f"pulse/{bt_sink}"
    else:
        print("[DEBUG AUDIO] ATTENZIONE: Stereo NON trovato/connesso. Uso 'pulse' di default.")
        return "pulse"

# ── SCAN FILE ────────────────────────────────────────────────────

def scan_audio_files() -> dict:
    result = {"music": [], "sfx": []}
    for subfolder, key in [("music", "music"), ("SFX", "sfx")]:
        path = os.path.join(AUDIO_BASE, subfolder)
        if os.path.isdir(path):
            files = sorted([
                f for f in os.listdir(path)
                if f.lower().endswith(AUDIO_EXTENSIONS)
            ])
            result[key] = [f"{subfolder}/{f}" for f in files]
    return result

def scan_video_files() -> dict:
    result = {"videos": []}
    if os.path.isdir(VIDEO_BASE):
        files = sorted([
            f for f in os.listdir(VIDEO_BASE)
            if f.lower().endswith(VIDEO_EXTENSIONS + IMAGE_EXTENSIONS)
        ])
        result["videos"] = files
    return result

# ── PUBLISH LISTE ────────────────────────────────────────────────

def publish_audio_list(client):
    files = scan_audio_files()
    client.publish(TOPIC_AUDIO_MUSIC_LIST, json.dumps(files['music']), qos=0, retain=True)
    client.publish(TOPIC_AUDIO_SFX_LIST, json.dumps(files['sfx']), qos=0, retain=True)
    print(f"[LIST] Audio separate inviate ── Music: {len(files['music'])} | SFX: {len(files['sfx'])}")

def publish_video_list(client):
    files = scan_video_files()
    client.publish(TOPIC_VIDEO_LIST, json.dumps(files), qos=0, retain=True)
    print(f"[LIST] Video/Immagini inviate: {len(files['videos'])} file")

# ── PLAYBACK ─────────────────────────────────────────────────────

def stop_playback():
    global current_proc
    if current_proc is None:
        return
    
    print("[STOP] Interrompo la riproduzione corrente...")
    if current_proc.poll() is None:
        current_proc.terminate()
        try:
            current_proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            print("[STOP] Forza kill del processo mpv hanguppato")
            current_proc.kill()
            current_proc.wait()
    else:
        current_proc.wait()
    current_proc = None

def _mpv_audio_cmd(filepath: str, audio_device: str) -> list:
    return [
        "mpv",
        "--no-video",
        f"--audio-device={audio_device}",
        "--no-terminal",
        filepath,
    ]

def _mpv_video_cmd(filepath: str, audio_device: str) -> list:
    # NOTA: se dà errore video, prova a rimuovere '--drm-connector=HDMI-A-1'
    return [
        "mpv",
        "--vo=drm",
        "--drm-connector=HDMI-A-1",
        f"--audio-device={audio_device}",
        "--no-terminal",
        filepath,
    ]

def _mpv_image_cmd(filepath: str, duration: int = 10) -> list:
    return [
        "mpv",
        "--vo=drm",
        "--drm-connector=HDMI-A-1",
        "--no-terminal",
        f"--image-display-duration={duration}",
        filepath,
    ]

def play_audio(filepath: str):
    global current_proc
    stop_playback()
    
    audio_device = check_audio_status()
    cmd = _mpv_audio_cmd(filepath, audio_device)
    
    print(f"[AUDIO] Avvio: {os.path.basename(filepath)} su {audio_device}")
    # ATTENZIONE: Lasciamo visibili gli errori di mpv sul terminale per fare debug!
    current_proc = subprocess.Popen(cmd)

def play_video(filepath: str):
    global current_proc
    stop_playback()
    
    audio_device = check_audio_status()
    cmd = _mpv_video_cmd(filepath, audio_device)
    
    print(f"[VIDEO] Avvio video: {os.path.basename(filepath)}")
    print(f"[DEBUG EXEC] Comando eseguito: {' '.join(cmd)}")
    # ATTENZIONE: Se mpv crasha per i permessi video, qui vedrai l'errore esatto!
    current_proc = subprocess.Popen(cmd)

def play_image(filepath: str, duration: int = 10):
    global current_proc
    stop_playback()
    
    cmd = _mpv_image_cmd(filepath, duration)
    print(f"[IMAGE] Avvio immagine: {os.path.basename(filepath)} per {duration}s")
    current_proc = subprocess.Popen(cmd)

# ── MQTT CALLBACKS ───────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] Connesso con successo a {MQTT_BROKER}")

        # Pulisce comandi pendenti vecchi (evita loop di avvii all'avvio dello script)
        for topic in (TOPIC_AUDIO_PLAY, TOPIC_AUDIO_STOP,
                      TOPIC_VIDEO_PLAY,  TOPIC_VIDEO_STOP):
            client.publish(topic, payload=None, qos=0, retain=True)

        topics = [
            TOPIC_AUDIO_PLAY, TOPIC_AUDIO_STOP,
            TOPIC_AUDIO_VOLUME, TOPIC_AUDIO_REFRESH,
            TOPIC_VIDEO_PLAY, TOPIC_VIDEO_STOP,
        ]
        for topic in topics:
            client.subscribe(topic)
            print(f"[MQTT] Iscritto a {topic}")

        publish_audio_list(client)
        publish_video_list(client)
    else:
        print(f"[MQTT] Errore connessione fallita con rc={rc}")

def on_message(client, userdata, msg):
    if not msg.payload:
        return
    payload = msg.payload.decode("utf-8").strip()
    if not payload:
        return

    topic = msg.topic
    print(f"[MSG RECV] {topic} = {payload!r}")

    if topic == TOPIC_AUDIO_STOP:
        stop_playback()

    elif topic == TOPIC_AUDIO_REFRESH:
        publish_audio_list(client)
        publish_video_list(client)

    elif topic == TOPIC_AUDIO_VOLUME:
        try:
            vol = max(0, min(100, int(payload)))
            # Nota: wpctl lavora sul server audio corrente dell'utente loggato
            subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", str(vol / 100.0)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print(f"[VOL] Impostato a {vol}%")
        except ValueError:
            print(f"[VOL] Errore formato volume: '{payload}'")

    elif topic == TOPIC_AUDIO_PLAY:
        if "/" in payload:
            filepath = os.path.join(AUDIO_BASE, payload)
        else:
            filepath = None
            for sub in ("music", "SFX"):
                candidate = os.path.join(AUDIO_BASE, sub, payload)
                if os.path.exists(candidate):
                    filepath = candidate
                    break

        if filepath and os.path.exists(filepath):
            play_audio(filepath)
        else:
            print(f"[AUDIO] File non trovato sul server: '{payload}'")

    elif topic == TOPIC_VIDEO_STOP:
        stop_playback()

    elif topic == TOPIC_VIDEO_PLAY:
        filepath = os.path.join(VIDEO_BASE, payload)
        if os.path.exists(filepath):
            if filepath.lower().endswith(IMAGE_EXTENSIONS):
                play_image(filepath)
            else:
                play_video(filepath)
        else:
            print(f"[VIDEO/IMAGE] File non trovato sul server: '{payload}'")

# ── MAIN ─────────────────────────────────────────────────────────

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="audio_video_player")
    client.on_connect = on_connect
    client.on_message = on_message
    
    print(f"[START] Connessione in corso al broker {MQTT_BROKER}...")
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_forever()

if __name__ == "__main__":
    main()
