#!/usr/bin/env python3
"""
mqttMedia.py — LagmaBills
Gestisce riproduzione audio, video e immagini via MQTT.
"""

import os
import json
import subprocess
import paho.mqtt.client as mqtt

# ── CONFIGURAZIONE ───────────────────────────────────────────────
MQTT_BROKER   = "100.100.61.49"
MQTT_PORT     = 1883
AUDIO_BASE    = "/home/ladrodirame/data/sounds"  # <── RIPRISTINATO (mancava!)
VIDEO_BASE    = "/home/ladrodirame/data/videos"
STEREO_MAC    = "DD:23:A5:42:C3:92"

# Nuovi canali separati per liste audio
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

# ── BLUETOOTH ────────────────────────────────────────────────────

def connect_bluetooth():
    subprocess.run(
        ["bluetoothctl", "connect", STEREO_MAC],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

def get_bluetooth_sink() -> str | None:
    try:
        out = subprocess.check_output(
            ["pactl", "list", "short", "sinks"], text=True
        )
        for line in out.splitlines():
            mac_under = STEREO_MAC.replace(":", "_")
            if mac_under.lower() in line.lower():
                return line.split()[1]
    except Exception:
        pass
    return None

# ── SCAN FILE ────────────────────────────────────────────────────

def _find_subfolder(base: str, target: str) -> str | None:
    """Trova una sottocartella di base che corrisponde a target ignorando il case."""
    if not os.path.isdir(base):
        return None
    for entry in os.listdir(base):
        if entry.lower() == target.lower() and os.path.isdir(os.path.join(base, entry)):
            return entry
    return None

def scan_audio_files() -> dict:
    result = {"music": [], "sfx": []}
    for target, key in [("music", "music"), ("sfx", "sfx")]:
        real_name = _find_subfolder(AUDIO_BASE, target)
        if real_name is None:
            print(f"[SCAN] Cartella non trovata: {os.path.join(AUDIO_BASE, target)} (case-insensitive)")
            continue
        path = os.path.join(AUDIO_BASE, real_name)
        print(f"[SCAN] Cerco audio in: {path}")
        files = sorted([
            f for f in os.listdir(path)
            if f.lower().endswith(AUDIO_EXTENSIONS)
        ])
        result[key] = [f"{real_name}/{f}" for f in files]
        print(f"[SCAN] {key}: {len(files)} file trovati")
    return result

def scan_video_files() -> dict:
    result = {"videos": []}
    print(f"[SCAN] Cerco video in: {VIDEO_BASE}")
    if os.path.isdir(VIDEO_BASE):
        files = sorted([
            f for f in os.listdir(VIDEO_BASE)
            if f.lower().endswith(VIDEO_EXTENSIONS + IMAGE_EXTENSIONS)
        ])
        result["videos"] = files
        print(f"[SCAN] video: {len(files)} file trovati")
    return result

# ── PUBLISH LISTE ────────────────────────────────────────────────

def publish_audio_list(client):
    files = scan_audio_files()
    
    # Invia la lista della musica su TOPIC_AUDIO_MUSIC_LIST
    client.publish(TOPIC_AUDIO_MUSIC_LIST, json.dumps(files['music']), qos=0, retain=True)
    
    # Invia la lista degli SFX su TOPIC_AUDIO_SFX_LIST
    client.publish(TOPIC_AUDIO_SFX_LIST, json.dumps(files['sfx']), qos=0, retain=True)
    
    print(f"[LIST] Audio separate inviate ── Music: {len(files['music'])} | SFX: {len(files['sfx'])}")

def publish_video_list(client):
    files = scan_video_files()
    client.publish(TOPIC_VIDEO_LIST, json.dumps(files), qos=0, retain=True)
    print(f"[LIST] Video/Immagini: {len(files['videos'])} file")

# ── PLAYBACK ─────────────────────────────────────────────────────

def stop_playback():
    """
    Ferma la riproduzione corrente.
    """
    global current_proc
    if current_proc is None:
        return
    if current_proc.poll() is None:
        current_proc.terminate()
        try:
            current_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            current_proc.kill()
            current_proc.wait()
    else:
        current_proc.wait()
    current_proc = None
    print("[STOP] Riproduzione fermata / processo pulito")

def _mpv_audio_cmd(filepath: str, audio_device: str) -> list:
    return [
        "mpv",
        "--no-video",
        f"--audio-device={audio_device}",
        "--no-terminal",
        "--really-quiet",
        filepath,
    ]

def _mpv_video_cmd(filepath: str, audio_device: str) -> list:
    return [
        "mpv",
        "--vo=drm",
        "--drm-connector=HDMI-A-1",
        f"--audio-device={audio_device}",
        "--no-terminal",
        "--really-quiet",
        filepath,
    ]

def _mpv_image_cmd(filepath: str, duration: int = 10) -> list:
    return [
        "mpv",
        "--vo=drm",
        "--drm-connector=HDMI-A-1",
        "--no-terminal",
        "--really-quiet",
        f"--image-display-duration={duration}",
        filepath,
    ]

def play_audio(filepath: str):
    global current_proc
    stop_playback()
    connect_bluetooth()
    bt_sink = get_bluetooth_sink()
    audio_device = f"pulse/{bt_sink}" if bt_sink else "pulse"
    cmd = _mpv_audio_cmd(filepath, audio_device)
    print(f"[AUDIO] {os.path.basename(filepath)} → {audio_device}")
    current_proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

def play_video(filepath: str):
    global current_proc
    stop_playback()
    connect_bluetooth()
    bt_sink = get_bluetooth_sink()
    audio_device = f"pulse/{bt_sink}" if bt_sink else "pulse"
    cmd = _mpv_video_cmd(filepath, audio_device)
    print(f"[VIDEO] {os.path.basename(filepath)} → HDMI audio:{audio_device}")
    current_proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

def play_image(filepath: str, duration: int = 10):
    global current_proc
    stop_playback()
    cmd = _mpv_image_cmd(filepath, duration)
    print(f"[IMAGE] {os.path.basename(filepath)} → HDMI per {duration}s")
    current_proc = subprocess.Popen(
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )

# ── MQTT CALLBACKS ───────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] Connesso a {MQTT_BROKER}")

        # Pulisce eventuali messaggi retained sui topic di comando
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
        print(f"[MQTT] Errore connessione rc={rc}")

def on_message(client, userdata, msg):
    if not msg.payload:
        return
    payload = msg.payload.decode("utf-8").strip()
    if not payload:
        return

    topic = msg.topic
    print(f"[MSG] {topic} = {payload!r}")

    if topic == TOPIC_AUDIO_STOP:
        stop_playback()

    elif topic == TOPIC_AUDIO_REFRESH:
        publish_audio_list(client)
        publish_video_list(client)

    elif topic == TOPIC_AUDIO_VOLUME:
        try:
            vol = max(0, min(100, int(payload)))
            subprocess.run(
                ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", str(vol / 100.0)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print(f"[VOL] {vol}%")
        except ValueError:
            print(f"[VOL] Payload non valido: '{payload}'")

    elif topic == TOPIC_AUDIO_PLAY:
        if "/" in payload:
            filepath = os.path.join(AUDIO_BASE, payload)
        else:
            filepath = None
            for sub in ("music", "sfx"):
                candidate_dir = _find_subfolder(AUDIO_BASE, sub)
                if candidate_dir:
                    candidate = os.path.join(AUDIO_BASE, candidate_dir, payload)
                    if os.path.exists(candidate):
                        filepath = candidate
                        break

        if filepath and os.path.exists(filepath):
            play_audio(filepath)
        else:
            print(f"[AUDIO] File non trovato: '{payload}'")

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
            print(f"[VIDEO/IMAGE] File non trovato: '{payload}'")

# ── MAIN ─────────────────────────────────────────────────────────

def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="audio_video_player")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_forever()

if __name__ == "__main__":
    main()