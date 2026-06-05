import asyncio
import json
import os
import socket
import queue
import sys
import time as _time

from scipy.signal import resample_poly, butter, lfilter

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["VECLIB_MAXIMUM_THREADS"] = "1"
os.environ["NUMEXPR_NUM_THREADS"] = "1"

import numpy as np
import sounddevice as sd
import websockets
import paho.mqtt.client as mqtt
from dotenv import load_dotenv
from openwakeword.model import Model

load_dotenv()

SAMPLE_RATE_HW  = 48000
SAMPLE_RATE_OWW = 16000
DOWN_FACTOR     = SAMPLE_RATE_HW // SAMPLE_RATE_OWW
CHANNELS        = 2
CANALE_MIC      = int(os.getenv("MIC_CHANNEL", "0"))
CHUNK_SIZE_OWW  = 1280
CHUNK_SIZE_HW   = CHUNK_SIZE_OWW * DOWN_FACTOR
GAIN_AUDIO      = float(os.getenv("GAIN_AUDIO", "1.0"))
_HP_B, _HP_A = butter(2, 80.0 / (SAMPLE_RATE_HW / 2), btype='high')

MODEL_PATH          = os.getenv("WAKEWORD_MODEL", "hey_nova.onnx")
DETECTION_THRESHOLD = float(os.getenv("DETECTION_THRESHOLD", "0.12"))
DEBOUNCE_SEC        = float(os.getenv("DEBOUNCE_SEC", "2.0"))

MQTT_HOST  = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT  = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_CMD  = os.getenv("TOPIC_CMD", "robot/cmd")

WS_URI             = os.getenv("WS_URI", "ws://100.120.32.86:8765")
STREAM_TIMEOUT_SEC = float(os.getenv("STREAM_TIMEOUT_SEC", "30.0"))

_ws_audio_queue   = queue.Queue(maxsize=200)
_tts_received     = asyncio.Event()
_streaming_active = asyncio.Event()
_ws_connected     = asyncio.Event()
_tts_playing      = asyncio.Event()
_boot_ready       = asyncio.Event()

_start_time = _time.monotonic()

def elapsed() -> str:
    return f"{_time.monotonic() - _start_time:7.2f}s"

def log(tag: str, msg: str) -> None:
    print(f"\n[{elapsed()}] [{tag}] {msg}", flush=True)

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
            self._loop.call_soon_threadsafe(_tts_playing.set)

    def start(self) -> None:
        try:
            self._client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            self._client.loop_start()
        except Exception as e:
            log("mqtt", f"WARN: non disponibile: {e}")

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


def build_audio_callback(oww_queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
    zi = [np.zeros(max(len(_HP_B), len(_HP_A)) - 1)]

    def _callback(indata: np.ndarray, frames: int, time_info, status) -> None:
        if status and "overflow" not in str(status):
            log("audio_cb", f"Status anomalo: {status}")

        if not _boot_ready.is_set():
            return

        mono_raw = indata[:, CANALE_MIC].copy() * GAIN_AUDIO
        filtered, zi[0] = lfilter(_HP_B, _HP_A, mono_raw, zi=zi[0])
        mono_16k = resample_poly(filtered, 1, DOWN_FACTOR)
        mono_16k = np.clip(mono_16k, -1.0, 1.0)
        mono_int16 = (mono_16k * 32767.0).astype(np.int16)

        loop.call_soon_threadsafe(
            lambda c=mono_int16: oww_queue.put_nowait(c) if not oww_queue.full() else None
        )

        if _streaming_active.is_set() and _ws_connected.is_set() and not _tts_playing.is_set():
            try:
                _ws_audio_queue.put_nowait(mono_int16)
            except queue.Full:
                try:
                    _ws_audio_queue.get_nowait()
                    _ws_audio_queue.put_nowait(mono_int16)
                except queue.Empty:
                    pass

    return _callback


async def ws_stream_loop() -> None:
    while True:
        await _streaming_active.wait()
        log("ws", f"Connessione a {WS_URI} ...")
        try:
            async with websockets.connect(WS_URI, ping_interval=20, ping_timeout=10) as ws:
                _ws_connected.set()          # ← AGGIUNTO
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
                log("ws", f"Errore: {e} — riprovo tra 1s")
                await asyncio.sleep(1.0)
        finally:
            _ws_connected.clear()            # ← AGGIUNTO


async def wakeword_loop(oww_queue: asyncio.Queue) -> None:
    loop = asyncio.get_running_loop()

    log("wakeword", f"Caricamento modello: {MODEL_PATH}...")
    oww_model = Model(wakeword_models=[MODEL_PATH], inference_framework="onnx")
    model_key = list(oww_model.models.keys())[0]
    log("wakeword", f"Modello pronto — chiave: '{model_key}'")

    last_detection_time = 0.0

    log("wakeword", "Stabilizzazione hardware (0.5s)...")
    _boot_ready.set()
    await asyncio.sleep(0.5)

    flushed = 0
    while not oww_queue.empty():
        try:
            oww_queue.get_nowait()
            flushed += 1
        except asyncio.QueueEmpty:
            break
    log("wakeword", f"Svuotati {flushed} chunk di warm-up")
    log("wakeword", f"Pronto! Modello: {MODEL_PATH} | soglia: {DETECTION_THRESHOLD} | canale: {CANALE_MIC}")
    log("wakeword", f"In ascolto — chiama 'Hey Nova'")

    while True:
        chunk: np.ndarray = await oww_queue.get()

        if _streaming_active.is_set():
            continue

        rms = float(np.sqrt(np.mean((chunk.astype(np.float32) / 32767.0) ** 2)))
        meter = int(min(rms * 10, 1.0) * 30)
        bar = "█" * meter + "░" * (30 - meter)

        now = loop.time()
        if now - last_detection_time < DEBOUNCE_SEC:
            sys.stdout.write(f"\r🎤 [{bar}] rms={rms:.4f} | debounce...          ")
            sys.stdout.flush()
            continue

        prediction = await loop.run_in_executor(None, oww_model.predict, chunk)
        score = prediction.get(model_key, 0.0)

        sys.stdout.write(
            f"\r🎤 [{bar}] rms={rms:.4f} | {model_key}: {score:.3f}"
            + (" ◀◀◀ RILEVATA!" if score >= DETECTION_THRESHOLD else "          ")
        )
        sys.stdout.flush()

        if score >= DETECTION_THRESHOLD:
            print()
            log("wakeword", f"*** WAKEWORD '{model_key}' rilevata! score={score:.3f} ***")

            oww_model.reset()
            last_detection_time = loop.time()

            send_face_command("wakeword_start")

            while not _ws_audio_queue.empty():
                try:
                    _ws_audio_queue.get_nowait()
                except queue.Empty:
                    break

            _tts_received.clear()
            _tts_playing.clear()
            _streaming_active.set()
            log("ws", "Streaming attivato")

            t0 = _time.monotonic()
            try:
                await asyncio.wait_for(_tts_received.wait(), timeout=STREAM_TIMEOUT_SEC)
                log("wakeword", f"TTS ricevuto dopo {_time.monotonic() - t0:.2f}s")
            except asyncio.TimeoutError:
                log("wakeword", f"Timeout dopo {STREAM_TIMEOUT_SEC}s")

            _streaming_active.clear()
            _ws_connected.clear()    # ← AGGIUNTO
            _tts_playing.clear()

            while not oww_queue.empty():
                try:
                    oww_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

            send_face_command("wakeword_end")
            log("ws", "Streaming fermato, ritorno in ascolto.")


async def main() -> None:
    loop = asyncio.get_running_loop()

    mqtt_mgr = MQTTManager(loop)
    mqtt_mgr.start()

    oww_queue: asyncio.Queue = asyncio.Queue(maxsize=200)
    audio_cb = build_audio_callback(oww_queue, loop)

    target_device_index = None
    try:
        for idx, dev in enumerate(sd.query_devices()):
            name = dev["name"].lower()
            if ("i2s" in name or "seeed" in name) and dev["max_input_channels"] >= CHANNELS:
                target_device_index = idx
                break
    except Exception as e:
        log("WARN", f"Errore ispezione device: {e}")

    if target_device_index is None:
        log("WARN", "ReSpeaker non trovato per nome, uso INPUT_DEVICE env")
        target_device_index = int(os.getenv("INPUT_DEVICE", "2"))

    dev_info = sd.query_devices(target_device_index)
    log("*", f"Device hardware selezionato: [{target_device_index}] {dev_info['name']}")
    log("*", f"Pipeline HW: {SAMPLE_RATE_HW}Hz -> Downsampling SW a {SAMPLE_RATE_OWW}Hz")
    log("*", f"Chunk HW: {CHUNK_SIZE_HW} frms -> Chunk OWW: {CHUNK_SIZE_OWW} frms (80ms)")
    log("*", f"Canale MIC selezionato: {CANALE_MIC} | Gain: {GAIN_AUDIO}")

    stream = sd.InputStream(
        device=target_device_index,
        samplerate=SAMPLE_RATE_HW,
        channels=CHANNELS,
        blocksize=CHUNK_SIZE_HW,
        dtype="float32",
        callback=audio_cb,
    )

    try:
        with stream:
            await asyncio.gather(
                ws_stream_loop(),
                wakeword_loop(oww_queue),
                return_exceptions=False,
            )
    except KeyboardInterrupt:
        log("*", "Chiusura in corso...")
    finally:
        mqtt_mgr.stop()


if __name__ == "__main__":
    asyncio.run(main())