#!/usr/bin/env python3
import numpy as np
import sounddevice as sd
import openwakeword
from openwakeword.model import Model
import time
import sys
import threading
import queue
import socket
import paho.mqtt.client as mqtt   # ← AGGIUNTO
import os
from dotenv import load_dotenv    # ← AGGIUNTO

load_dotenv()                     # ← AGGIUNTO

INPUT_DEVICE        = 2
DETECTION_THRESHOLD = 0.7
MODEL_PATH          = "hey_no_va.onnx"
COOLDOWN_SEC        = 3.0

# ── MQTT config ──────────────────────────────────────────
MQTT_HOST    = os.getenv("MQTT_HOST", "100.0.0.0")
MQTT_PORT    = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_STREAM = "robot/audio_stream"
# ─────────────────────────────────────────────────────────

audio_queue = queue.Queue(maxsize=10)

# ── client MQTT globale ───────────────────────────────────
_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

def _mqtt_connect():
    try:
        _mqtt.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        _mqtt.loop_start()
        print(f"[mqtt] Connesso a {MQTT_HOST}:{MQTT_PORT}")
    except Exception as e:
        print(f"[mqtt] WARN: non disponibile: {e}")
# ─────────────────────────────────────────────────────────

def send_face_command(cmd: str):          
    try:
        s = socket.socket()
        s.settimeout(0.5)
        s.connect(("127.0.0.1", 9876))
        s.sendall(cmd.encode())
        s.close()
    except Exception:
        pass

def main():
    _mqtt_connect()   # ← AGGIUNTO

    oww_model = Model(wakeword_models=[MODEL_PATH], inference_framework="onnx")

    dev_info = sd.query_devices(INPUT_DEVICE)
    print(f"[*] Device: [{INPUT_DEVICE}] {dev_info['name']}")
    print(f"[*] Soglia: {DETECTION_THRESHOLD}")
    print("    [Ctrl+C per uscire]\n")

    last_detection = 0

    def audio_callback(indata, frames, time_info, status):
        chunk = (indata[:, 0] * 32767).astype(np.int16).copy()
        try:
            audio_queue.put_nowait(chunk)
        except queue.Full:
            pass

    def inference_thread():
        nonlocal last_detection
        while True:
            chunk = audio_queue.get()
            if chunk is None:
                break

            if time.time() - last_detection < COOLDOWN_SEC:
                continue

            prediction = oww_model.predict(chunk)

            for name, score in prediction.items():
                bar = "█" * int(score * 20)
                print(f"\r  {name}: {score:.3f} [{bar:<20}]", end="", flush=True)

                if score >= DETECTION_THRESHOLD:
                    print(f"\n\n  *** WAKEWORD rilevata! (score={score:.3f}) ***\n")
                    last_detection = time.time()
                    oww_model.reset()

                    # 1. Anima gli occhi
                    send_face_command("wakeword_start")

                    # 2. Avvia stream audio sul Raspberry ← AGGIUNTO
                    try:
                        _mqtt.publish(TOPIC_STREAM, "start")
                        print("[mqtt] → audio_stream START")
                    except Exception as e:
                        print(f"[mqtt] publish start fallito: {e}")

                    time.sleep(5)          # placeholder STT

                    # 3. Ferma tutto ← MODIFICATO
                    send_face_command("wakeword_end")
                    try:
                        _mqtt.publish(TOPIC_STREAM, "stop")
                        print("[mqtt] → audio_stream STOP")
                    except Exception as e:
                        print(f"[mqtt] publish stop fallito: {e}")

    t = threading.Thread(target=inference_thread, daemon=True)
    t.start()

    try:
        with sd.InputStream(
            device=INPUT_DEVICE,
            samplerate=16000,
            channels=1,
            blocksize=1280,
            dtype="float32",
            callback=audio_callback,
        ):
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n[*] Uscita.")
        audio_queue.put(None)

if __name__ == "__main__":
    main()