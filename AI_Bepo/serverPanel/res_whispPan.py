import numpy as np
from resemblyzer import VoiceEncoder, preprocess_wav
from pathlib import Path
import os
import threading
import logging
import queue
from collections import deque
from faster_whisper import WhisperModel
import paho.mqtt.client as mqtt
import language_tool_python
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

Base_Dir = Path(__file__).parent
logger   = logging.getLogger(__name__)

# ── MQTT ──────────────────────────────────────────────────────────────
MQTT_HOST = os.getenv("MQTT_HOST", "100.100.61.49")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

def _mqtt_connect():
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
        logger.info(f"MQTT connesso a {MQTT_HOST}:{MQTT_PORT}")
    except Exception as e:
        logger.warning(f"MQTT non disponibile: {e}")

# ── Groq Whisper ───────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

client_groq = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

def transcribe_with_groq(audio_np: np.ndarray) -> str:
    import io
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, audio_np, 16000, format="WAV")
    buf.seek(0)
    buf.name = "audio.wav"

    t = client_groq.audio.transcriptions.create(
        model="whisper-large-v3-turbo",
        file=buf,
        language="it"
    )
    return t.text.strip()

# ── Correttore grammaticale ────────────────────────────────────────────
_tool = None

def get_tool():
    global _tool
    if _tool is None:
        _tool = language_tool_python.LanguageTool("it")
    return _tool

def correggi(testo: str) -> str:
    try:
        tool    = get_tool()
        matches = tool.check(testo)
        return language_tool_python.utils.correct(testo, matches)
    except Exception as e:
        logger.warning(f"Correttore errore: {e}")
        return testo

# ── Modelli ────────────────────────────────────────────────────────────
similarity = float(os.getenv("SPEAKER_SIMILARITY", "0.40"))

logger.info("Caricamento Whisper...")
try:
    Whisper = WhisperModel("small", device="cpu", compute_type="int8")
except Exception:
    Whisper = WhisperModel("base",  device="cpu", compute_type="int8")
logger.info("Whisper caricato")

logger.info("Caricamento Resemblyzer...")
try:
    encoder = VoiceEncoder("cuda")
except Exception:
    encoder = VoiceEncoder("cpu")
logger.info("Resemblyzer caricato")

ground_truth_dir = Base_Dir / "Voci" / "ground"
gt_files = list(ground_truth_dir.glob("*.wav"))
gt_names = [f.stem for f in gt_files]
gt_wavs  = [preprocess_wav(f) for f in gt_files]
gt_emb   = np.array([encoder.embed_utterance(w) for w in gt_wavs]) if gt_files else np.array([])

def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 0 else v

if len(gt_emb) > 0:
    gt_emb = np.array([_normalize(e) for e in gt_emb])

# ── Speaker verification ───────────────────────────────────────────────
def demo15(chunk_audio: np.ndarray):
    max_val = np.max(np.abs(chunk_audio))
    if max_val == 0:
        logger.warning("Audio vuoto ricevuto")
        return False, None

    chunk_audio = chunk_audio / max_val
    chunk_embed = _normalize(encoder.embed_utterance(chunk_audio))
    sims        = np.dot(gt_emb, chunk_embed)
    max_i       = int(sims.argmax())
    max_s       = float(sims[max_i])
    logger.info(f"Similarity: {max_s:.3f} con {gt_names[max_i]}")
    return max_s > similarity, gt_names[max_i]

# ── Buffer circolare ───────────────────────────────────────────────────
# deque(maxlen=N) è il buffer circolare nativo Python:
# - thread-safe per append/popleft (GIL garantisce atomicità)
# - quando pieno, scarta automaticamente il più vecchio (lato sinistro)
#   senza bisogno di lock manuali o codice custom
# - zero overhead: è implementato in C nella stdlib
#
# Funzionamento con il worker:
#   on_audio_ready() fa append() → se deque piena, il chunk più vecchio
#   viene scartato silenziosamente da Python prima dell'insert.
#   Il worker consuma con popleft(). Se deque vuota, _has_audio.wait()
#   mette il worker in sleep finché non arriva un nuovo chunk.
#
# AUDIO_RING_SIZE=3 significa: al massimo 3 sessioni audio in attesa.
# Con Whisper+Resemblyzer che ci mettono ~3-5s, e sessioni che arrivano
# ogni ~5-10s, 3 slot è già abbondante. Aumenta solo se vedi warning.

AUDIO_RING_SIZE = int(os.getenv("AUDIO_RING_SIZE", "3"))

_ring:      deque        = deque(maxlen=AUDIO_RING_SIZE)
_ring_lock: threading.Lock  = threading.Lock()
_has_audio: threading.Event = threading.Event()

def _ring_put(item) -> bool:
    """
    Inserisce nel buffer circolare.
    Ritorna False se era già pieno (= ha scartato il più vecchio).
    """
    with _ring_lock:
        full = len(_ring) == _ring.maxlen
        _ring.append(item)   # deque scarta da sinistra se maxlen raggiunto
        _has_audio.set()
        return not full

def _ring_get(timeout: float = 30.0) -> np.ndarray:
    """
    Estrae il prossimo chunk. Blocca fino a timeout secondi.
    Lancia queue.Empty se scade.
    """
    import time
    deadline = time.monotonic() + timeout
    while True:
        with _ring_lock:
            if _ring:
                item = _ring.popleft()
                if not _ring:
                    _has_audio.clear()
                return item
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise queue.Empty
        _has_audio.wait(timeout=min(remaining, 0.5))

text_queue: queue.Queue = queue.Queue()



# ── Worker ─────────────────────────────────────────────────────────────
def worker():
    while True:
        try:
            audio_np = _ring_get(timeout=30)
        except queue.Empty:
            logger.debug("Nessun audio da 30s — in attesa")
            continue

        logger.info(f"Audio ricevuto: {len(audio_np)} campioni ({len(audio_np)/16000:.2f}s)")
        audio_pc = preprocess_wav(audio_np)
        accepted, name = demo15(audio_pc)

        if accepted and name is not None:
            logger.info(f"Utente riconosciuto: {name}")
            text = None

            # Prova Groq prima (più veloce)
            if GROQ_API_KEY:
                try:
                    text = transcribe_with_groq(audio_pc)
                    text = correggi(text)
                    logger.info(f"Groq trascritto: '{text}'")
                except Exception as e:
                    logger.warning(f"Groq fallito: {e} — uso Whisper locale")

            # Fallback Whisper locale (gestisce sia crash Groq che risposta vuota)
            if not text:
                try:
                    segments, _ = Whisper.transcribe(
                        audio_pc.astype(np.float32),
                        language="it",
                        beam_size=10,
                        temperature=0.1,
                    )
                    raw = "".join(seg.text for seg in segments).strip()
                    if raw:
                        text = correggi(raw)
                        logger.info(f"Whisper locale trascritto: '{text}'")
                except Exception as e2:
                    logger.warning(f"Whisper locale fallito: {e2}")

            if text:
                text_queue.put({"testo": text, "nome": name})
                logger.info(f"Testo in queue per cervello: '{text}'")

            try:
                mqtt_client.publish("robot/alert", "utente_riconosciuto")
            except Exception as e:
                logger.warning(f"MQTT publish fallito: {e}")

        else:
            logger.info("Utente non riconosciuto")
            try:
                mqtt_client.publish("robot/alert", "utente_sconosciuto")
            except Exception as e:
                logger.warning(f"MQTT publish fallito: {e}")





# ── API pubblica 
async def on_audio_ready(audio: np.ndarray):
    inserted = _ring_put(audio)
    if inserted:
        logger.debug(f"Audio in ring buffer ({len(_ring)}/{AUDIO_RING_SIZE})")
    else:
        logger.warning(
            f"Ring buffer pieno ({AUDIO_RING_SIZE} slot) — chunk più vecchio scartato, "
            "processato quello più recente. "
            "Aumenta AUDIO_RING_SIZE nel .env se perdi conversazioni."
        )

def get_text(timeout: float = 0.1):
    try:
        return text_queue.get(timeout=timeout)
    except queue.Empty:
        return None

def start():
    logger.info("Avvio audio pipeline...")
    _mqtt_connect()
    threading.Thread(target=worker, daemon=True).start()
    logger.info("Audio pipeline pronta")