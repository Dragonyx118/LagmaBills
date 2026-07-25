import numpy as np
from resemblyzer import VoiceEncoder, preprocess_wav
from pathlib import Path
import os
import threading
import logging
import queue
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

    buffer = io.BytesIO()
    sf.write(buffer, audio_np, 16000, format="WAV")
    buffer.seek(0)
    buffer.name = "audio.wav"

    trascrizione = client_groq.audio.transcriptions.create(
        model="whisper-large-v3-turbo",
        file=buffer,
        language="it"
    )
    return trascrizione.text.strip()

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
# Dimensione massima: di default 3 slot.
# Se il worker (Whisper + Resemblyzer) è occupato e arriva un 4° chunk,
# il più vecchio viene scartato e si processa sempre l'audio più recente.
# Aumenta AUDIO_RING_SIZE nel .env se vuoi conservare più slot (usa più RAM).
AUDIO_RING_SIZE = int(os.getenv("AUDIO_RING_SIZE", "3"))

class RingQueue:
    """
    Queue FIFO a dimensione fissa: quando piena, scarta il chunk più vecchio
    invece di bloccare o lanciare eccezioni.
    Thread-safe tramite threading.Lock.
    """
    def __init__(self, maxsize: int):
        self._maxsize = maxsize
        self._buf: list = []
        self._lock = threading.Lock()
        self._not_empty = threading.Event()

    def put(self, item) -> bool:
        """
        Inserisce item. Se il buffer è pieno, scarta il più vecchio.
        Ritorna True se inserito senza scarto, False se ha scartato un elemento.
        """
        with self._lock:
            dropped = False
            if len(self._buf) >= self._maxsize:
                self._buf.pop(0)   # scarta il più vecchio
                dropped = True
            self._buf.append(item)
            self._not_empty.set()
            return not dropped

    def get(self, timeout: float = None):
        """
        Estrae il prossimo elemento. Blocca fino a timeout secondi.
        Lancia queue.Empty se timeout scade.
        """
        deadline = None
        if timeout is not None:
            import time
            deadline = time.monotonic() + timeout

        while True:
            with self._lock:
                if self._buf:
                    item = self._buf.pop(0)
                    if not self._buf:
                        self._not_empty.clear()
                    return item

            # Calcola quanto aspettare
            if deadline is not None:
                import time
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise queue.Empty
                self._not_empty.wait(timeout=min(remaining, 0.1))
            else:
                self._not_empty.wait(timeout=0.1)

    def qsize(self) -> int:
        with self._lock:
            return len(self._buf)


audio_queue = RingQueue(maxsize=AUDIO_RING_SIZE)
text_queue:  queue.Queue = queue.Queue()

# ── Worker ─────────────────────────────────────────────────────────────
def worker():
    while True:
        try:
            audio_np = audio_queue.get(timeout=30)
        except queue.Empty:
            logger.debug("Nessun audio da 30s — in attesa")
            continue

        logger.info(f"Audio ricevuto: {len(audio_np)} campioni ({len(audio_np)/16000:.2f}s)")
        audio_pc = preprocess_wav(audio_np)
        accepted, name = demo15(audio_pc)

        if accepted and name is not None:
            logger.info(f"Utente riconosciuto: {name}")
            text = None

            if GROQ_API_KEY:
                try:
                    text = transcribe_with_groq(audio_pc)
                    text = correggi(text)
                    logger.info(f"Groq trascritto: '{text}'")
                except Exception as e:
                    logger.warning(f"Groq fallito: {e} — uso Whisper locale")

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

# ── API pubblica ───────────────────────────────────────────────────────
async def on_audio_ready(audio: np.ndarray):
    inserted = audio_queue.put(audio)
    if inserted:
        logger.debug(f"Audio in ring buffer ({audio_queue.qsize()}/{AUDIO_RING_SIZE})")
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