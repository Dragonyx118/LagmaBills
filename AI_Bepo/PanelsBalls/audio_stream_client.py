#!/usr/bin/env python3
"""
audio_stream_client.py
Gira sul Raspberry. Ascolta MQTT per start/stop dello stream audio.
- Riceve "wakeword_start" su robot/audio_stream → avvia stream WebSocket
- Riceve "wakeword_end"   su robot/audio_stream → ferma stream
  (oppure quando command_sender pubblica tts_text su robot/cmd)
"""

import asyncio
import websockets
import pyaudio
import sys
import json
import paho.mqtt.client as mqtt
import os
from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────
WS_URI       = os.getenv("WS_URI", "ws://100.120.32.86:8765")
MQTT_HOST    = os.getenv("MQTT_HOST", "100.0.0.0")
MQTT_PORT    = int(os.getenv("MQTT_PORT", "1883"))

TOPIC_STREAM = "robot/audio_stream"   # riceve "start" / "stop"
TOPIC_CMD    = "robot/cmd"            # monitora tts_text in arrivo

SAMPLE_RATE  = 16000
CHANNELS     = 1
FORMAT       = pyaudio.paInt16
CHUNK        = 1024
DEVICE_NAME  = "seeed-2mic-voicecard"
# ──────────────────────────────────────────────

# Event asyncio condiviso: settato = stream attivo
_stream_active = asyncio.Event()
_loop: asyncio.AbstractEventLoop = None


def find_device_index(pa, name_hint):
    if name_hint is None:
        return None
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        if name_hint.lower() in info["name"].lower() and info["maxInputChannels"] > 0:
            print(f"[audio] Device: [{i}] {info['name']}")
            return i
    print(f"[audio] WARN: '{name_hint}' non trovato, uso default")
    return None


# ── MQTT callbacks ────────────────────────────────────────────────────
def on_mqtt_message(client, userdata, msg):
    global _loop
    topic = msg.topic
    try:
        payload = msg.payload.decode()
    except Exception:
        return

    if topic == TOPIC_STREAM:
        if payload == "start":
            print("[mqtt] → START stream audio")
            _loop.call_soon_threadsafe(_stream_active.set)
        elif payload == "stop":
            print("[mqtt] → STOP stream audio")
            _loop.call_soon_threadsafe(_stream_active.clear)

    elif topic == TOPIC_CMD:
        # Quando arriva un nuovo tts_text, ferma lo stream
        try:
            data = json.loads(payload)
            if data.get("tts_text"):
                print(f"[mqtt] tts_text ricevuto → stop stream")
                _loop.call_soon_threadsafe(_stream_active.clear)
        except json.JSONDecodeError:
            pass


def start_mqtt():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_mqtt_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.subscribe([(TOPIC_STREAM, 0), (TOPIC_CMD, 0)])
    client.loop_start()
    print(f"[mqtt] Connesso a {MQTT_HOST}:{MQTT_PORT}")
    return client


# ── Stream audio ──────────────────────────────────────────────────────
async def stream_audio():
    pa = pyaudio.PyAudio()
    dev_index = find_device_index(pa, DEVICE_NAME)

    stream = pa.open(
        rate=SAMPLE_RATE,
        channels=CHANNELS,
        format=FORMAT,
        input=True,
        input_device_index=dev_index,
        frames_per_buffer=CHUNK,
    )
    print(f"[audio] Stream pronto: {SAMPLE_RATE}Hz chunk={CHUNK}")

    loop = asyncio.get_event_loop()

    while True:
        # Aspetta che lo stream venga attivato
        print("[audio] In attesa di start...")
        await _stream_active.wait()

        print(f"[ws] Connessione a {WS_URI} ...")
        reconnect_delay = 1.0

        try:
            async with websockets.connect(
                WS_URI,
                ping_interval=20,
                ping_timeout=10,
            ) as ws:
                print(f"[ws] Connesso — invio audio")
                reconnect_delay = 1.0

                while _stream_active.is_set():
                    raw = await loop.run_in_executor(
                        None,
                        lambda: stream.read(CHUNK, exception_on_overflow=False)
                    )
                    await ws.send(raw)

                # stream_active cleared → chiudi la connessione WS
                print("[ws] Stream fermato, chiudo connessione")

        except (websockets.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            if _stream_active.is_set():
                print(f"[ws] Disconnesso: {e} — riconnessione in {reconnect_delay}s")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 30)
            # se non è più attivo, torna ad aspettare il prossimo start


async def main():
    global _loop
    _loop = asyncio.get_event_loop()

    start_mqtt()
    await stream_audio()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[info] Interrotto")
        sys.exit(0)