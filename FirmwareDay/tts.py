import json
import logging
import os
import subprocess
import threading
import time
import queue
import select

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [tts] %(levelname)s: %(message)s"
)
logger = logging.getLogger(__name__)

# ─── CONFIG ───────────────────────────────────
MQTT_HOST   = os.getenv("MQTT_HOST",  "localhost")
MQTT_PORT   = int(os.getenv("MQTT_PORT", "1883"))
TOPIC_CMD   = "robot/cmd"

PIPER_BIN   = os.getenv("PIPER_BIN",  "/home/ladrodirame/AIsburra/piper")
PIPER_MODEL = os.getenv(
    "PIPER_MODEL",
    "/home/ladrodirame/AIsburra/TUFF/piper_voci_italiano/Miro/miro_it-IT.onnx"
)

STEREO_MAC  = os.getenv("STEREO_MAC", "DD:23:A5:42:C3:92")

SAMPLE_RATE = 22050
SILENCE_MS  = 1500
# ──────────────────────────────────────────────

_tts_queue      = queue.Queue()
_stop_event     = threading.Event()
_proc_lock      = threading.Lock()
_current_paplay = None

_piper_proc  = None
_piper_lock  = threading.Lock()
_piper_ready = threading.Event()


def _drain_stderr(proc, stop_event, label="piper"):
    while not stop_event.is_set():
        try:
            r, _, _ = select.select([proc.stderr], [], [], 0.5)
            if r:
                line = proc.stderr.readline()
                if not line:
                    break
                decoded = line.decode(errors="replace").strip()
                if decoded and "Initialized" in decoded:
                    _piper_ready.set()
        except Exception:
            break


_stderr_stop = threading.Event()


def _start_piper():
    global _piper_proc, _stderr_stop
    _piper_ready.clear()
    _stderr_stop.clear()

    logger.info("Caricamento modello piper (solo al primo avvio)...")
    _piper_proc = subprocess.Popen(
        [PIPER_BIN, "--model", PIPER_MODEL, "--output-raw"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    t = threading.Thread(
        target=_drain_stderr,
        args=(_piper_proc, _stderr_stop),
        daemon=True
    )
    t.start()

    if _piper_ready.wait(timeout=15):
        logger.info("Piper pronto.")
    else:
        logger.warning("Piper: timeout attesa inizializzazione — procedo comunque.")

    logger.info("Warm-up piper...")
    try:
        _piper_proc.stdin.write(". \n".encode("utf-8"))
        _piper_proc.stdin.flush()
        buf = b""
        deadline = time.time() + 8
        while time.time() < deadline:
            r, _, _ = select.select([_piper_proc.stdout], [], [], 0.5)
            if r:
                chunk = _piper_proc.stdout.read1(8192)
                if chunk:
                    buf += chunk
            else:
                if buf:
                    break
        logger.info(f"Warm-up completato ({len(buf)} byte scartati).")
    except Exception as e:
        logger.warning(f"Warm-up fallito: {e}")


def _ensure_piper():
    global _piper_proc
    if _piper_proc is None or _piper_proc.poll() is not None:
        logger.warning("Piper era morto, riavvio...")
        _stderr_stop.set()
        _start_piper()


def _synth_audio(text: str) -> bytes:
    with _piper_lock:
        global _piper_proc
        _ensure_piper()

        try:
            clean_text = text.strip()
            if not clean_text.endswith(('.', '?', '!')):
                clean_text += "."
            payload = f"{clean_text}\n".encode("utf-8")
            _piper_proc.stdin.write(payload)
            _piper_proc.stdin.flush()
        except BrokenPipeError:
            logger.warning("BrokenPipe su piper stdin, riavvio...")
            _stderr_stop.set()
            _start_piper()
            _piper_proc.stdin.write(f"{text.strip()}\n".encode("utf-8"))
            _piper_proc.stdin.flush()

        buf = b""
        deadline = time.time() + 15
        first_chunk = True

        while time.time() < deadline:
            timeout = 1.5 if first_chunk else 0.6
            r, _, _ = select.select([_piper_proc.stdout], [], [], timeout)

            if r:
                chunk = _piper_proc.stdout.read1(8192)
                if chunk:
                    buf += chunk
                    first_chunk = False
                else:
                    logger.error("Piper ha chiuso stdout — morto?")
                    _piper_proc = None
                    break
            else:
                if not first_chunk:
                    break
                break

        return buf


# ── BLUETOOTH ────────────────────────────────────────────────────────

def get_bluetooth_sink() -> str | None:
    try:
        out = subprocess.check_output(
            ["pactl", "list", "short", "sinks"], text=True
        )
        mac_under = STEREO_MAC.replace(":", "_")
        for line in out.splitlines():
            if mac_under.lower() in line.lower():
                return line.split()[1]
    except Exception:
        pass
    return None


def _wake_sink(sink: str):
    silence = b'\x00' * int(SAMPLE_RATE * 2 * 1.5)
    try:
        p = subprocess.Popen(
            ["paplay", "--raw",
             "--rate=22050", "--format=s16le", "--channels=1",
             f"--device=pulse/{sink}"],
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        p.stdin.write(silence)
        p.stdin.close()
        p.wait()
    except Exception as e:
        logger.warning(f"Wake sink fallito: {e}")


# ── PLAYBACK ─────────────────────────────────────────────────────────

def _stop_current_playback():
    global _current_paplay
    _stop_event.set()  # Notifica al thread di scartare l'elaborazione corrente
    with _proc_lock:
        if _current_paplay and _current_paplay.poll() is None:
            try:
                _current_paplay.terminate()
                logger.info("Riproduzione interrotta")
            except Exception:
                pass


def _synth_and_play(text: str):
    global _current_paplay

    # Resetta lo stop event all'inizio del ciclo per questa nuova frase
    _stop_event.clear()

    logger.info(f"TTS → '{text[:80]}{'…' if len(text) > 80 else ''}'")

    bt_sink = get_bluetooth_sink()
    if not bt_sink:
        logger.warning("Sink BT non trovato, uso default")

    wake_thread = None
    if bt_sink:
        wake_thread = threading.Thread(
            target=_wake_sink, args=(bt_sink,), daemon=True
        )
        wake_thread.start()

    t_start = time.time()
    audio_data = _synth_audio(text)
    logger.info(f"Sintesi in {time.time() - t_start:.2f}s, {len(audio_data)} byte")

    # 🔥 ABORT CONTROLLO: Se nel frattempo è arrivato un comando di stop, scarta l'audio generato
    if _stop_event.is_set():
        logger.info("Nuovo messaggio MQTT arrivato durante la sintesi. Audio scartato.")
        return

    if not audio_data:
        logger.error("Nessun audio prodotto da piper")
        return

    if wake_thread:
        wake_thread.join(timeout=3)

    silence_bytes = b'\x00' * int(SAMPLE_RATE * (SILENCE_MS / 1000) * 2)
    audio_device = f"pulse/{bt_sink}" if bt_sink else None

    # Ultimo controllo di sicurezza prima di attivare la scheda audio
    if _stop_event.is_set():
        return

    try:
        paplay_cmd = [
            "paplay", "--raw",
            "--rate=22050", "--format=s16le", "--channels=1",
        ]
        if audio_device:
            paplay_cmd.append(f"--device={audio_device}")

        paplay_proc = subprocess.Popen(
            paplay_cmd,
            stdin=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )

        with _proc_lock:
            _current_paplay = paplay_proc

        paplay_proc.stdin.write(silence_bytes)
        paplay_proc.stdin.write(audio_data)
        paplay_proc.stdin.close()
        paplay_proc.wait()

    except Exception as e:
        logger.warning(f"Errore playback: {e}")
    finally:
        with _proc_lock:
            _current_paplay = None


def _worker():
    while True:
        text = _tts_queue.get()
        if text is None:
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

    # Invia segnale di stop immediato a paplay e ai controlli di riproduzione
    _stop_current_playback()

    while not _tts_queue.empty():
        try:
            _tts_queue.get_nowait()
            _tts_queue.task_done()
        except queue.Empty:
            break

    _tts_queue.put(text)
    logger.info(f"[mqtt] in coda: '{text[:60]}'")


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
    _start_piper()

    worker_thread = threading.Thread(target=_worker, daemon=True)
    worker_thread.start()

    mqtt_client = start_mqtt()
    logger.info("tts_player pronto — in attesa di comandi MQTT")

    try:
        worker_thread.join()
    except KeyboardInterrupt:
        logger.info("Uscita.")
        _tts_queue.put(None)
        _stop_current_playback()
        _stderr_stop.set()
        if _piper_proc:
            _piper_proc.terminate()


if __name__ == "__main__":
    main()