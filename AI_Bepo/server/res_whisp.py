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

# -----------------------------------------------------------------------
# MQTT
# -----------------------------------------------------------------------

MQTT_HOST = os.getenv("MQTT_HOST", "100.100.61.49")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

def _mqtt_connect():
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        mqtt_client.loop_start()
        logger.info("MQTT connesso")
    except Exception as e:
        logger.warning(f"MQTT non disponibile: {e}")

# -----------------------------------------------------------------------
# Groq per trascrizione — più veloce di Whisper locale
# -----------------------------------------------------------------------

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# client Groq — stesso SDK OpenAI
client_groq = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

def transcribe_with_groq(audio_np):
    # Groq ha un endpoint Whisper hosted — molto più veloce del locale
    # manda l'audio come file WAV in memoria
    import io
    import soundfile as sf

    # converte numpy array in bytes WAV in memoria
    buffer = io.BytesIO()
    sf.write(buffer, audio_np, 16000, format="WAV")
    buffer.seek(0)
    buffer.name = "audio.wav"  # Groq richiede un nome file

    trascrizione = client_groq.audio.transcriptions.create(
        model="whisper-large-v3-turbo",  # modello Groq gratuito
        file=buffer,
        language="it"
    )
    return trascrizione.text

# -----------------------------------------------------------------------
# correttore grammaticale
# -----------------------------------------------------------------------

_tool = None

def get_tool():
    global _tool
    if _tool is None:
        _tool = language_tool_python.LanguageTool("it")
    return _tool

def correggi(testo):
    try:
        tool   = get_tool()
        matches = tool.check(testo)
        return language_tool_python.utils.correct(testo, matches)
    except Exception as e:
        logger.warning(f"Correttore errore: {e}")
        return testo

# -----------------------------------------------------------------------
# caricamento modelli
# -----------------------------------------------------------------------

similarity = 0.400

logger.info("caricamento whisper...")
try:
    Whisper = WhisperModel("small", device="cpu", compute_type="int8")
except:
    Whisper = WhisperModel("base",  device="cpu", compute_type="int8")
logger.info("whisper caricato")

logger.info("caricamento resemblyzer...")
try:
    encoder = VoiceEncoder("cuda")
except:
    encoder = VoiceEncoder("cpu")
logger.info("resemblyzer caricato")

ground_truth_dir = Base_Dir / "Voci" / "ground"
gt_f     = list(ground_truth_dir.glob("*.wav"))
gt_names = [f.stem for f in gt_f]
gt_wavs  = [preprocess_wav(f) for f in gt_f]
gt_emb   = np.array([encoder.embed_utterance(w) for w in gt_wavs])

def normalize(v):
    return v / np.linalg.norm(v)

if len(gt_emb) > 0:
    gt_emb = np.array([normalize(e) for e in gt_emb])

# -----------------------------------------------------------------------
# speaker verification
# -----------------------------------------------------------------------

def demo15(chunk_audio):
    max_val = np.max(np.abs(chunk_audio))
    if max_val > 0:
        chunk_audio = chunk_audio / max_val
    else:
        print("audio vuoto")
        return False, None
    chunk_embed = encoder.embed_utterance(chunk_audio)
    chunk_embed = normalize(chunk_embed)
    sims  = np.dot(gt_emb, chunk_embed)
    max_i = sims.argmax()
    max_s = sims[max_i]
    print(f"Max similarity: {max_s:.3f} con {gt_names[max_i]}")
    return max_s > similarity, gt_names[max_i]

# -----------------------------------------------------------------------
# queue
# -----------------------------------------------------------------------

audio_queue = queue.Queue(maxsize=10)
text_queue  = queue.Queue()

# -----------------------------------------------------------------------
# worker
# -----------------------------------------------------------------------

def worker():
    while True:
        try:
            audio_np = audio_queue.get(timeout=30)
        except queue.Empty:
            print("Timeout: nessun audio da 30 secondi")
            continue

        audio_pc = preprocess_wav(audio_np)
        accepted, name = demo15(audio_pc)

        if accepted and name is not None:
            print(f"Utente riconosciuto: {name}")

            # prova Groq Whisper — più veloce
            # se fallisce usa Whisper locale come fallback
            text = None
            try:
                text = transcribe_with_groq(audio_pc)
                text = correggi(text)
                print(f"Groq trascritto: {text}")
            except Exception as e:
                logger.warning(f"Groq trascrizione fallita: {e} — uso Whisper locale")
                try:
                    segments, _ = Whisper.transcribe(
                        audio_pc.astype(np.float32),
                        language="it",
                        beam_size=10,
                        temperature=0.1
                    )
                    testo_lista = [seg.text for seg in segments]
                    if testo_lista:
                        text = correggi("".join(testo_lista))
                        print(f"Whisper locale trascritto: {text}")
                except Exception as e2:
                    logger.warning(f"Whisper locale fallito: {e2}")

            if text:
                # mette dizionario con testo e nome — cervello.py li usa entrambi
                text_queue.put({"testo": text, "nome": name})

            # avvisa il Raspberry che l'utente è riconosciuto
            try:
                mqtt_client.publish("robot/alert", "utente_riconosciuto")
            except Exception as e:
                logger.warning(f"MQTT publish fallito: {e}")

        else:
            print("Utente non riconosciuto")
            # avvisa il Raspberry — cervello non riceve niente
            try:
                mqtt_client.publish("robot/alert", "utente_sconosciuto")
            except Exception as e:
                logger.warning(f"MQTT publish fallito: {e}")

        audio_queue.task_done()

# -----------------------------------------------------------------------
# API pubblica
# -----------------------------------------------------------------------

async def on_audio_ready(audio):
    audio_queue.put_nowait(audio)
    logger.debug("chunk audio in queue")

def get_text(timeout=0.1):
    try:
        return text_queue.get(timeout=timeout)
    except queue.Empty:
        return None

def start():
    logger.info("avvio worker audio pipeline...")
    _mqtt_connect()
    threading.Thread(target=worker, daemon=True).start()
    logger.info("audio pipeline pronta")