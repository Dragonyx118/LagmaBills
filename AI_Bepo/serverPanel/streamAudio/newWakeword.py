#!/usr/bin/env python3
"""
Wakeword listener — livekit-wakeword + MQTT + WebSocket audio streaming

NOTA: WakeWordModel.predict() è STATELESS — richiede ~2s di audio completo
per ogni chiamata. Usiamo un buffer scorrevole che accumula chunk a 16kHz
e chiama predict() ogni STRIDE_SAMPLES nuovi campioni.
"""

import asyncio
import json
import os
import socket
import queue

import numpy as np
import sounddevice as sd
import websockets
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from livekit.wakeword import WakeWordModel

load_dotenv()

# ── Hardware ───────────────────────────────────────────────
INPUT_DEVICE    = int(os.getenv("INPUT_DEVICE", "2"))
SAMPLE_RATE_HW  = 48000
SAMPLE_RATE_OWW = 16000
CHANNELS        = 2
BLOCKSIZE       = int(1280 * (SAMPLE_RATE_HW / SAMPLE_RATE_OWW))  # 3840

# ── Wakeword ───────────────────────────────────────────────
MODEL_PATH          = os.getenv("WAKEWORD_MODEL", "hey_nova.onnx")
DETECTION_THRESHOLD = float(os.getenv("DETECTION_THRESHOLD", "0.5"))
DEBOUNCE_SEC        = float(os.getenv("DEBOUNCE_SEC", "2.0"))

# Buffer scorrevole: il modello vuole ~2s di audio (>=16 embeddings)
WINDOW_SAMPLES = SAMPLE_RATE_OWW * 2      # 32000 campioni = 2 s
STRIDE_SAMPLES = SAMPLE_RATE_OWW // 4     # 4000  campioni = 0.25 s

# ── MQTT ───────────────────────────────────────────────────
MQTT_HOST  = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT  = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_CMD  = os.getenv("TOPIC_CMD", "robot/cmd")

# ── WebSocket ──────────────────────────────────────────────
WS_URI             = os.getenv("WS_URI", "ws://100.120.32.86:8765")
STREAM_TIMEOUT_SEC = float(os.getenv("STREAM_TIMEOUT_SEC", "30.0"))

# ── Shared state ───────────────────────────────────────────
_ws_audio_queue   = queue.Queue(maxsize=200)
_tts_received     = asyncio.Event()
_streaming_active = asyncio.Event()


def log(tag: str, msg: str) -> None:
    print(f"[{tag}] {msg}", flush=True)


def send_face_command(cmd: str) -> None:
    try:
        with socket.socket() as s:
            s.settimeout(0.5)
            s.connect(("127.0.0.1", 9876))
            s.sendall(cmd.encode())
    except OSError:
        pass


class MQTTManager:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_message = self._on_message
        self._client.on_connect = self._on_connect

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        client.subscribe(TOPIC_CMD, qos=0)
        log("mqtt", f"Connesso a {MQTT_HOST}:{MQTT_PORT}, topic={TOPIC_CMD}")

    def _on_message(self, client, userdata, msg):
        if msg.topic != TOPIC_CMD:
            return
        try:
            data = json.loads(msg.payload.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            return
        if data.get("tts_text"):
            log("mqtt", "tts_text ricevuto -> stop stream")
            self._loop.call_soon_threadsafe(_tts_received.set)

    def start(self) -> None:
        try:
            self._client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            self._client.loop_start()
        except Exception as e:
            log("mqtt", f"WARN: non disponibile: {e}")

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


def build_audio_callback(oww_audio_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    from scipy.signal import resample_poly

    def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:
        mono        = indata[:, 0]
        downsampled = resample_poly(mono, up=1, down=3).astype(np.float32)
        chunk_int16 = (downsampled * 32767).astype(np.int16).copy()

        try:
            loop.call_soon_threadsafe(oww_audio_queue.put_nowait, chunk_int16)
        except asyncio.QueueFull:
            pass

        if _streaming_active.is_set():
            try:
                _ws_audio_queue.put_nowait(chunk_int16)
            except queue.Full:
                pass

    return _callback


async def ws_stream_loop() -> None:
    while True:
        await _streaming_active.wait()
        log("ws", f"Connessione a {WS_URI} ...")
        try:
            async with websockets.connect(WS_URI, ping_interval=20, ping_timeout=10) as ws:
                log("ws", "Connesso — invio audio")
                while _streaming_active.is_set():
                    try:
                        chunk = _ws_audio_queue.get_nowait()
                        await ws.send(chunk.tobytes())
                    except queue.Empty:
                        await asyncio.sleep(0.01)
                log("ws", "Stream terminato")
        except Exception as e:
            if _streaming_active.is_set():
                log("ws", f"Errore: {e} — riprovo tra 1 s")
                await asyncio.sleep(1.0)


async def wakeword_loop(oww_audio_queue: asyncio.Queue) -> None:
    """
    predict() e' stateless: vuole ~2s di audio completo per chiamata.
    Buffer scorrevole WINDOW_SAMPLES campioni @16kHz.
    Inference ogni STRIDE_SAMPLES nuovi campioni (~250 ms).
    """
    loop = asyncio.get_running_loop()
    model = WakeWordModel(models=[MODEL_PATH])

    audio_buffer = np.zeros(WINDOW_SAMPLES, dtype=np.int16)
    samples_since_last_inference = 0
    last_detection_time = 0.0

    log("wakeword", f"In ascolto — modello: {MODEL_PATH}, soglia: {DETECTION_THRESHOLD}")
    log("wakeword", f"Buffer: {WINDOW_SAMPLES} campioni ({WINDOW_SAMPLES/SAMPLE_RATE_OWW:.1f}s) | stride: {STRIDE_SAMPLES} ({STRIDE_SAMPLES/SAMPLE_RATE_OWW*1000:.0f}ms)")

    while True:
        chunk: np.ndarray = await oww_audio_queue.get()

        if _streaming_active.is_set():
            try:
                _ws_audio_queue.put_nowait(chunk)
            except queue.Full:
                pass
            continue

        n = len(chunk)

        # Scorri il buffer e aggiungi chunk in fondo
        if n >= WINDOW_SAMPLES:
            audio_buffer[:] = chunk[-WINDOW_SAMPLES:]
        else:
            audio_buffer[:-n] = audio_buffer[n:]
            audio_buffer[-n:] = chunk

        samples_since_last_inference += n

        if samples_since_last_inference < STRIDE_SAMPLES:
            continue
        samples_since_last_inference = 0

        # Debounce
        now = loop.time()
        if now - last_detection_time < DEBOUNCE_SEC:
            continue

        window_copy = audio_buffer.copy()
        prediction: dict = await loop.run_in_executor(None, model.predict, window_copy)

        for name, score in prediction.items():
            bar = "X" * int(score * 20)
            print(f"\r  {name}: {score:.3f} [{bar:<20}]", end="", flush=True)

            if score >= DETECTION_THRESHOLD:
                print()
                log("wakeword", f"*** RILEVATA! score={score:.3f} ***")
                last_detection_time = loop.time()
                audio_buffer[:] = 0
                samples_since_last_inference = 0

                send_face_command("wakeword_start")

                while not _ws_audio_queue.empty():
                    try:
                        _ws_audio_queue.get_nowait()
                    except queue.Empty:
                        break

                _tts_received.clear()
                _streaming_active.set()
                log("ws", "Streaming attivato")

                try:
                    await asyncio.wait_for(_tts_received.wait(), timeout=STREAM_TIMEOUT_SEC)
                    log("wakeword", "Risposta TTS ricevuta")
                except asyncio.TimeoutError:
                    log("wakeword", f"Timeout dopo {STREAM_TIMEOUT_SEC} s")

                _streaming_active.clear()
                send_face_command("wakeword_end")
                log("ws", "Streaming fermato")


async def main() -> None:
    loop = asyncio.get_running_loop()

    mqtt_mgr = MQTTManager(loop)
    mqtt_mgr.start()

    oww_audio_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    audio_cb = build_audio_callback(oww_audio_queue, loop)

    dev_info = sd.query_devices(INPUT_DEVICE)
    log("*", f"Device: [{INPUT_DEVICE}] {dev_info['name']}")
    log("*", f"HW: {SAMPLE_RATE_HW} Hz -> resample -> {SAMPLE_RATE_OWW} Hz | blocksize={BLOCKSIZE}")
    log("*", f"WS URI: {WS_URI}  |  [Ctrl+C per uscire]")

    stream = sd.InputStream(
        device=INPUT_DEVICE,
        samplerate=SAMPLE_RATE_HW,
        channels=CHANNELS,
        blocksize=BLOCKSIZE,
        dtype="float32",
        callback=audio_cb,
    )

    try:
        with stream:
            await asyncio.gather(
                ws_stream_loop(),
                wakeword_loop(oww_audio_queue),
                return_exceptions=False,
            )
    except KeyboardInterrupt:
        log("*", "Uscita.")
    finally:
        mqtt_mgr.stop()


if __name__ == "__main__":
    asyncio.run(main())