#!/usr/bin/env python3
import numpy as np
import sounddevice as sd
import openwakeword
from openwakeword.model import Model
from scipy.signal import resample_poly
import time
import sys
import threading
import queue
import socket
import asyncio
import websockets
import json
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv

load_dotenv()

INPUT_DEVICE        = 2                  # seeed-2mic-voicecard
DETECTION_THRESHOLD = 0.7
MODEL_PATH          = "hey_mycroft"
COOLDOWN_SEC        = 3.0

# ── Frequenze audio ────────────────────────────────────────
SAMPLE_RATE_HW  = 48000   # frequenza nativa del microfono WM8960
SAMPLE_RATE_OWW = 16000   # frequenza richiesta da openwakeword
CHANNELS        = 2
# blocksize in campioni HW che corrispondono a 1280 campioni a 16kHz
BLOCKSIZE       = int(1280 * (SAMPLE_RATE_HW / SAMPLE_RATE_OWW))  # = 3840
# ──────────────────────────────────────────────────────────

# ── Config ────────────────────────────────────────────────
MQTT_HOST    = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT    = int(os.getenv("MQTT_PORT", "1883"))
WS_URI       = os.getenv("WS_URI", "ws://100.120.32.86:8765")
TOPIC_CMD    = "robot/cmd"
# ─────────────────────────────────────────────────────────

# Queue condivisa tra audio_callback e i thread consumatori
audio_queue      = queue.Queue(maxsize=50)
ws_audio_queue   = queue.Queue(maxsize=100)

# Events
_tts_received     = threading.Event()
_streaming_active = threading.Event()

# ── MQTT ──────────────────────────────────────────────────
_mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

def on_mqtt_message(client, userdata, msg):
    if msg.topic == TOPIC_CMD:
        try:
            data = json.loads(msg.payload.decode())
            if data.get("tts_text"):
                print("\n[mqtt] tts_text ricevuto → stop stream")
                _tts_received.set()
        except Exception:
            pass

def _mqtt_connect():
    try:
        _mqtt.on_message = on_mqtt_message
        _mqtt.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        _mqtt.subscribe(TOPIC_CMD, qos=0)
        _mqtt.loop_start()
        print(f"[mqtt] Connesso a {MQTT_HOST}:{MQTT_PORT}")
    except Exception as e:
        print(f"[mqtt] WARN: non disponibile: {e}")

# ── Socket animazioni ─────────────────────────────────────
def send_face_command(cmd: str):
    try:
        s = socket.socket()
        s.settimeout(0.5)
        s.connect(("127.0.0.1", 9876))
        s.sendall(cmd.encode())
        s.close()
    except Exception:
        pass

# ── Thread WebSocket: manda audio al server ───────────────
def ws_stream_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _stream():
        while True:
            while not _streaming_active.is_set():
                await asyncio.sleep(0.05)

            print(f"[ws] Connessione a {WS_URI} ...")
            try:
                async with websockets.connect(
                    WS_URI,
                    ping_interval=20,
                    ping_timeout=10,
                ) as ws:
                    print("[ws] Connesso — invio audio")
                    while _streaming_active.is_set():
                        try:
                            raw_chunk = ws_audio_queue.get(timeout=0.1)
                            await ws.send(raw_chunk.tobytes())
                        except queue.Empty:
                            continue
                    print("[ws] Stream fermato, chiudo connessione")
            except Exception as e:
                if _streaming_active.is_set():
                    print(f"[ws] Errore connessione: {e} — riprovo tra 1s")
                    await asyncio.sleep(1.0)

    loop.run_until_complete(_stream())

# ── Thread inference: rileva wakeword ─────────────────────
def inference_thread(oww_model):
    last_detection = 0

    while True:
        chunk = audio_queue.get()
        if chunk is None:
            break

        if _streaming_active.is_set():
            try:
                ws_audio_queue.put_nowait(chunk)
            except queue.Full:
                pass
            continue

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

                send_face_command("wakeword_start")

                while not ws_audio_queue.empty():
                    try:
                        ws_audio_queue.get_nowait()
                    except queue.Empty:
                        break

                _tts_received.clear()
                _streaming_active.set()
                print("[ws] Streaming attivato")

                got_response = _tts_received.wait(timeout=30)
                if not got_response:
                    print("[wakeword] Timeout — nessuna risposta dal server")

                _streaming_active.clear()
                send_face_command("wakeword_end")
                print("[ws] Streaming fermato")

# ── Main ──────────────────────────────────────────────────
def main():
    _mqtt_connect()

    oww_model = Model(wakeword_models=[MODEL_PATH], inference_framework="onnx")

    dev_info = sd.query_devices(INPUT_DEVICE)
    print(f"[*] Device: [{INPUT_DEVICE}] {dev_info['name']}")
    print(f"[*] HW samplerate: {SAMPLE_RATE_HW} Hz  →  resample a {SAMPLE_RATE_OWW} Hz (scipy)")
    print(f"[*] Soglia: {DETECTION_THRESHOLD}")
    print(f"[*] WS URI: {WS_URI}")
    print("    [Ctrl+C per uscire]\n")

    def audio_callback(indata, frames, time_info, status):
        # Canale sinistro, resample di qualità 48k→16k con filtro anti-aliasing
        mono = indata[:, 0]
        downsampled = resample_poly(mono, up=1, down=3).astype(np.float32)
        chunk = (downsampled * 32767).astype(np.int16).copy()
        try:
            audio_queue.put_nowait(chunk)
        except queue.Full:
            pass

    t_ws = threading.Thread(target=ws_stream_thread, daemon=True)
    t_ws.start()

    t_inf = threading.Thread(target=inference_thread, args=(oww_model,), daemon=True)
    t_inf.start()

    try:
        with sd.InputStream(
            device=INPUT_DEVICE,
            samplerate=SAMPLE_RATE_HW,   # 48000 Hz — frequenza nativa
            channels=CHANNELS,
            blocksize=BLOCKSIZE,          # 3840 campioni = 1280 @ 16kHz
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