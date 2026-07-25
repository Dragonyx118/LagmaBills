#!/usr/bin/env python3
"""
tts_player.py  –  gira sul Raspberry
Ascolta robot/cmd su MQTT.
Quando arriva tts_text → sintetizza con Piper → riproduce con aplay.
"""

import json
import logging
import os
import subprocess
import tempfile
import threading
import queue

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [tts] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# CONFIG  (puoi sovrascrivere con .env)
# ──────────────────────────────────────────────
MQTT_HOST   = os.getenv("MQTT_HOST",  "100.100.61.49")
MQTT_PORT   = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_CMD   = "robot/cmd"

# Percorso al binario piper  (adatta se lo hai in un venv)
PIPER_BIN   = os.getenv("PIPER_BIN",  "piper")

# Modello vocale – dalla posizione che hai mostrato
PIPER_MODEL = os.getenv(
    "PIPER_MODEL",
    "/home/ladrodirame/AIsburra/piper_voci_italiano/Miro/miro_it-IT.onnx"
)

# Dispositivo ALSA per la riproduzione
# "default" va bene nella maggior parte dei casi;
# usa "plughw:0,0" o "plughw:1,0" se hai bisogno di specificare la scheda
ALSA_DEVICE = os.getenv("ALSA_DEVICE", "plughw:1,0")
# ──────────────────────────────────────────────


# Coda thread-safe: il callback MQTT ci mette i testi,
# il worker li consuma uno alla volta (niente sovrapposizioni audio)
_tts_queue: queue.Queue = queue.Queue()

# Evento per interrompere la riproduzione corrente
# (es. se arriva un nuovo tts_text mentre sta ancora parlando)
_stop_event = threading.Event()
_current_proc = None          # subprocess aplay in esecuzione
_proc_lock    = threading.Lock()


def _stop_current_playback():
    """Interrompe immediatamente aplay se sta girando."""
    global _current_proc
    _stop_event.set()
    with _proc_lock:
        if _current_proc and _current_proc.poll() is None:
            try:
                _current_proc.terminate()
                logger.info("Riproduzione interrotta (nuovo tts in arrivo)")
            except Exception:
                pass


def _synth_and_play(text: str):
    """Chiama Piper in pipe ad aplay — tutto in memoria, nessun file temporaneo."""
    global _current_proc
    _stop_event.clear()

    logger.info(f"TTS → '{text[:80]}{'…' if len(text)>80 else ''}'")

    try:
        # piper legge da stdin, scrive WAV su stdout
        piper_proc = subprocess.Popen(
            [PIPER_BIN, "--model", PIPER_MODEL, "--output-raw"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        # aplay legge PCM raw 16-bit 22050 Hz mono
        # (il sample rate dipende dal modello; miro_it-IT usa 22050)
        aplay_proc = subprocess.Popen(
            [
                "aplay",
                "-r", "22050",
                "-f", "S16_LE",
                "-c", "1",
                "-D", ALSA_DEVICE,
            ],
            stdin=piper_proc.stdout,
            stderr=subprocess.DEVNULL,
        )

        with _proc_lock:
            _current_proc = aplay_proc

        # Manda il testo a piper e chiudi stdin
        piper_proc.stdin.write(text.encode("utf-8"))
        piper_proc.stdin.close()
        piper_proc.stdout.close()   # permette a piper di ricevere SIGPIPE se aplay muore

        aplay_proc.wait()
        piper_proc.wait()

    except FileNotFoundError as e:
        logger.error(
            f"Binario non trovato: {e}\n"
            f"  PIPER_BIN={PIPER_BIN}\n"
            f"  Controlla che piper sia installato e nel PATH, "
            f"oppure imposta PIPER_BIN nel .env"
        )
    except Exception as e:
        logger.warning(f"Errore TTS: {e}")
    finally:
        with _proc_lock:
            _current_proc = None


def _worker():
    """Thread che consuma la coda e riproduce in sequenza."""
    while True:
        text = _tts_queue.get()
        if text is None:          # segnale di shutdown
            break
        _synth_and_play(text)
        _tts_queue.task_done()


# ── MQTT ─────────────────────────────────────────────────────────────

def on_message(client, userdata, msg):
    if msg.topic != TOPIC_CMD:
        return
    try:
        data = json.loads(msg.payload.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        return

    text = data.get("tts_text", "").strip()
    if not text:
        return

    # Se sta già parlando, interrompi e metti il nuovo testo in coda
    _stop_current_playback()

    # Svuota la coda (non ha senso accumulare testi vecchi)
    while not _tts_queue.empty():
        try:
            _tts_queue.get_nowait()
            _tts_queue.task_done()
        except queue.Empty:
            break

    _tts_queue.put(text)
    logger.info(f"[mqtt] tts_text in coda: '{text[:60]}…'" if len(text) > 60 else f"[mqtt] tts_text in coda: '{text}'")


def start_mqtt() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.subscribe(TOPIC_CMD, qos=0)
    client.loop_start()
    logger.info(f"Connesso a {MQTT_HOST}:{MQTT_PORT}, ascolto {TOPIC_CMD}")
    return client


# ── Entry point ───────────────────────────────────────────────────────

def main():
    worker_thread = threading.Thread(target=_worker, daemon=True)
    worker_thread.start()

    mqtt_client = start_mqtt()

    logger.info("tts_player pronto — in attesa di comandi MQTT")
    logger.info(f"  modello : {PIPER_MODEL}")
    logger.info(f"  piper   : {PIPER_BIN}")
    logger.info(f"  alsa    : {ALSA_DEVICE}")

    try:
        worker_thread.join()   # blocca qui; il worker gira per sempre
    except KeyboardInterrupt:
        logger.info("Uscita.")
        _tts_queue.put(None)   # shutdown del worker
        _stop_current_playback()


if __name__ == "__main__":
    main()