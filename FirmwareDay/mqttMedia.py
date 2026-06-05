#!/usr/bin/env python3
"""
mqttAudio.py — LagmaBills
Gestisce riproduzione audio, video e immagini via MQTT.
"""

import os
import json
import subprocess
import paho.mqtt.client as mqtt

# ── CONFIGURAZIONE ───────────────────────────────────────────────
MQTT_BROKER    = "100.100.61.49"
MQTT_PORT      = 1883
AUDIO_BASE     = "/home/ladrodirame/data/sounds"
VIDEO_BASE     = "/home/ladrodirame/data/videos"
STEREO_MAC     = "DD:23:A5:42:C3:92"

TOPIC_AUDIO_PLAY    = "pi/audio/play"
TOPIC_AUDIO_STOP    = "pi/audio/stop"
TOPIC_AUDIO_VOLUME  = "pi/audio/volume"
TOPIC_AUDIO_REFRESH = "pi/audio/refresh"
TOPIC_AUDIO_LIST    = "pi/audio/list"
TOPIC_VIDEO_PLAY    = "pi/video/play"
TOPIC_VIDEO_STOP    = "pi/video/stop"
TOPIC_VIDEO_LIST    = "pi/video/list"

VIDEO_EXTENSIONS = (".mp4", ".mkv", ".avi", ".mov", ".webm")
AUDIO_EXTENSIONS = (".mp3", ".wav", ".ogg", ".flac")
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
    client.publish(TOPIC_AUDIO_LIST, json.dumps(files), qos=0, retain=True)
    total = len(files["music"]) + len(files["sfx"])
    print(f"[LIST] Audio: {total} file pubblicati")

def publish_video_list(client):
    files = scan_video_files()
    client.publish(TOPIC_VIDEO_LIST, json.dumps(files), qos=0, retain=True)
    print(f"[LIST] Video/Immagini: {len(files['videos'])} file pubblicati")

# ── PLAYBACK ─────────────────────────────────────────────────────

def stop_playback():
    """Ferma la riproduzione corrente se attiva."""
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
    current_proc = None
    print("[STOP] Riproduzione fermata")

def play_audio(filepath: str):
    global current_proc
    stop_playback()
    connect_bluetooth()
    current_proc = subprocess.Popen(
        ["mpg123", filepath],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    print(f"[AUDIO] {filepath}")

def play_video(filepath: str):
    global current_proc
    stop_playback()
    connect_bluetooth()

    bt_sink = get_bluetooth_sink()
    audio_device = f"pulse/{bt_sink}" if bt_sink else "pulse"

    cmd = [
        "mpv",
        "--vo=drm",
        "--drm-connector=HDMI-A-1",
        f"--audio-device={audio_device}",
        "--no-terminal",
        "--really-quiet",
        filepath
    ]

    current_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    print(f"[VIDEO] {filepath} → video:HDMI audio:{audio_device}")

def play_image(filepath: str, duration: int = 10):
    global current_proc
    stop_playback()
    cmd = [
        "mpv",
        "--vo=drm",
        "--drm-connector=HDMI-A-1",
        "--no-terminal",
        "--really-quiet",
        f"--image-display-duration={duration}",
        filepath
    ]
    current_proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    print(f"[IMAGE] {filepath} → HDMI per {duration}s")

# ── MQTT CALLBACKS ───────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[MQTT] Connesso a {MQTT_BROKER}")
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
    payload = msg.payload.decode("utf-8").strip()
    topic   = msg.topic

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
            for sub in ("music", "SFX"):
                candidate = os.path.join(AUDIO_BASE, sub, payload)
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