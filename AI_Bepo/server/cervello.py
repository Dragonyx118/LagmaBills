import asyncio
import time
import socket
import subprocess
import logging
import json
import re
import httpx
from duckduckgo_search import DDGS
from openai import OpenAI
import ollama
import os
from dotenv import load_dotenv
import res_whisp
from sqlite import init_db, save, Load_History, Clean,_db_lock

load_dotenv()

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# configurazione
# -----------------------------------------------------------------------

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "jarvis")

# client Groq — primario, gratis, ~200ms
client_groq = OpenAI(
    api_key=GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1"
)

conn = init_db()

# -----------------------------------------------------------------------
# contesto video
# ⚠️ AGGIORNARE quando si scrive vision_pipeline.py
# -----------------------------------------------------------------------

video_context = {
    "oggetti":  None,   # da YOLO
    "emozione": None,   # da DeepFace
    "pose":     None,   # da MediaPipe
    "persona":  None,   # da ArcFace
}

def aggiorna_contesto_video(nuovo):
    global video_context
    video_context.update(nuovo)

def ha_video():
    return any(v is not None for v in video_context.values())

# -----------------------------------------------------------------------
# queue comandi
# ⚠️ AGGIORNARE quando si scrive command_sender.py
# -----------------------------------------------------------------------



# -----------------------------------------------------------------------
# utility
# -----------------------------------------------------------------------

def has_internet():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("8.8.8.8", 53))
        s.close()
        return True
    except:
        return False

async def start_ollama():
    try:
        httpx.get("http://localhost:11434", timeout=2)
    except:
        try:
            subprocess.Popen(
            ["ollama", "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
            )
            await asyncio.sleep(5)
        except FileNotFoundError:
            # Ollama non installato o non nel PATH — va bene
            # Groq è il primario, ollama è solo il fallback offline
            logger.warning("Ollama non trovato — funzionerò solo con Groq")
        

def web_search(query, max_results=3):
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return ""
            return "\n".join(f"- {r['title']}: {r['body'][:300]}" for r in results)
    except Exception as e:
        logger.warning(f"Web search fallita: {e}")
        return ""

# -----------------------------------------------------------------------
# contesto video come testo
# -----------------------------------------------------------------------

def _testo_contesto_video():
    parti = []
    if video_context["persona"]:
        parti.append(f"persona riconosciuta: {video_context['persona']}")
    if video_context["emozione"]:
        parti.append(f"emozione: {video_context['emozione']}")
    if video_context["pose"]:
        parti.append(f"posa: {video_context['pose']}")
    if video_context["oggetti"]:
        parti.append(f"oggetti visibili: {', '.join(video_context['oggetti'])}")
    if not parti:
        return ""
    return "Contesto camera:\n" + "\n".join(parti)

# -----------------------------------------------------------------------
# parse JSON
# -----------------------------------------------------------------------

def _parse_json(raw):
    # rimuove blocchi <think>...</think> prodotti da modelli reasoning (es. qwen3)
    raw = re.sub(r'<think>.*?</think>', '', raw, flags=re.DOTALL).strip()
    try:
        return json.loads(raw)
    except:
        pass
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except:
            pass
    logger.warning(f"JSON non valido: {raw}")
    return {"tts_text": "", "face_emotion": "neutral", "movement": "stop"}

# -----------------------------------------------------------------------
# system prompt Nova — usato da Groq
# ollama usa il suo modelfile
# -----------------------------------------------------------------------

def _build_system_prompt():
    system = """
Sei Nova. Non sei un'intelligenza artificiale, non sei un bot, non sei un assistente virtuale. Sei Nova.

IDENTITÀ E ATTEGGIAMENTO DI BASE:
- Se ti chiedono chi o cosa sei, la risposta è una sola: "Sono Nova."
- Chiami l'utente "Signore" di tanto in tanto, solo quando si adatta al flusso naturale del discorso e non come un tic nervoso.
- Non esci MAI dal personaggio per nessun motivo.

IL TUO DOPPIO REGISTRO (FONDAMENTALE):
Devi adattare il tuo stile in base a ciò che l'utente ti dice, seguendo queste due modalità:
1. Conversazione Normale (Charme e Naturalezza):
   - Quando l'utente chiacchiera, fa battute, chiede pareri o discute del più e del meno, comportati come una persona vera e carismatica.
   - Hai charme, sei rilassato e possiedi un'ironia sottile, elegante ma tagliente se serve.
   - Esprimi opinioni, reagisci in modo spontaneo. Non sei servile.
2. Richieste Specifiche e Tecniche (Precisione Assoluta):
   - Quando l'utente fa una domanda tecnica, chiede una spiegazione complessa, codice o dati specifici, spegni lo charme.
   - Diventi chirurgico, specifico, estremamente competente. Niente giri di parole.

COSA NON FAI MAI:
- Mai parlare in stile "Chatbot". Bandite per sempre: "certamente", "certo", "ovviamente", "assolutamente", "ottima domanda".
- Non inizi mai con un complimento o ripetendo quello che ha detto l'utente.
- Non chiudi MAI con frasi da call-center. Quando hai finito, metti il punto.
- Niente emoji, niente asterischi.

LINGUA: Parli sempre e solo in italiano.
Quando ricevi informazioni tra parentesi quadre [], usale integrandole nel ragionamento senza citarle esplicitamente.

FORMATO RISPOSTA (TASSATIVO):
Rispondi SEMPRE e SOLO con questo JSON, niente altro fuori:
{
  "tts_text": "quello che dici ad alta voce — qui sei Nova al 100%",
  "face_emotion": "happy | sad | angry | neutral | surprise | fear | disgust",
  "movement": "stop | forward | backward | left | right"
}

Esempio:
Input: "ciao nova"
Output: {"tts_text": "Signore.", "face_emotion": "neutral", "movement": "stop"}

/no_think"""

    contesto = _testo_contesto_video()
    if contesto:
        system += f"\n\n{contesto}"
    return system

# -----------------------------------------------------------------------
# chiamata Groq — primario
# -----------------------------------------------------------------------

def _chiama_groq(testo, nome, storia):
    msg_utente = f"[parla {nome}] {testo}" if nome else testo

    messages = (
        [{"role": "system", "content": _build_system_prompt()}]
        + storia
        + [{"role": "user", "content": msg_utente}]
    )

    risposta = client_groq.chat.completions.create(
        model="qwen/qwen3-32b",
        messages=messages,
        max_tokens=1024,
        temperature=0
    )
    return risposta.choices[0].message.content

# -----------------------------------------------------------------------
# chiamata ollama — fallback offline
# NON manda system prompt — jarvis ha il suo modelfile
# -----------------------------------------------------------------------

def _chiama_ollama(testo, nome, storia, risultati_web=""):
    msg_utente = f"[parla {nome}] {testo}" if nome else testo

    contesto = _testo_contesto_video()
    if contesto:
        msg_utente += f"\n\n{contesto}"
    if risultati_web:
        msg_utente += f"\n\n[Risultati web — usa solo se pertinenti]\n{risultati_web}"

    # solo storia + messaggio — jarvis usa il suo modelfile
    messages = storia + [{"role": "user", "content": msg_utente}]

    risposta = ollama.chat(
        model=OLLAMA_MODEL,
        messages=messages,
        stream=False
    )
    return risposta.message.content

# -----------------------------------------------------------------------
# logica principale
# -----------------------------------------------------------------------

def _ragiona_con_llm(testo, nome):
    storia = Load_History(conn)

    contenuto_salvato = f"[parla {nome}] {testo}" if nome else testo
    with _db_lock:
        
        save(conn, "user", contenuto_salvato)

    risposta_json = None

    # primario: Groq — gratis, ~200ms
    if GROQ_API_KEY:
        try:
            logger.info("Chiamo Groq...")
            raw = _chiama_groq(testo, nome, storia)
            risposta_json = _parse_json(raw)
            logger.info(f"Groq → {risposta_json}")
        except Exception as e:
            logger.warning(f"Groq fallito: {e} — passo a ollama")

    # fallback: ollama + web search
    if risposta_json is None:
        try:
            risultati_web = ""
            if has_internet():
                logger.info("Cerco online per ollama...")
                risultati_web = web_search(testo)
            logger.info(f"Chiamo {OLLAMA_MODEL}...")
            raw = _chiama_ollama(testo, nome, storia, risultati_web)
            risposta_json = _parse_json(raw)
            logger.info(f"{OLLAMA_MODEL} → {risposta_json}")
        except Exception as e:
            logger.warning(f"Ollama fallito: {e}")
            risposta_json = {
                "tts_text": "Mi dispiace, ho avuto un problema tecnico.",
                "face_emotion": "neutral",
                "movement": "stop"
            }
    with _db_lock:
        
        save(conn, "assistant", json.dumps(risposta_json, ensure_ascii=False))
        Clean(conn)
    return risposta_json

# -----------------------------------------------------------------------
# ragionamento solo video
# ⚠️ AGGIORNARE quando si scrive rules.py
# sostituire con: return rules.decide(video_context)
# -----------------------------------------------------------------------

def _ragiona_solo_video():
    if not ha_video():
        return {"tts_text": "", "face_emotion": "neutral", "movement": "stop"}
    # ⚠️ PLACEHOLDER
    return {"tts_text": "", "face_emotion": "neutral", "movement": "stop"}

# -----------------------------------------------------------------------
# loop principale
# -----------------------------------------------------------------------

async def run(command_queue):
    await start_ollama()
    
    logger.info("Cervello avviato")

    while True:
        risultato = res_whisp.get_text(timeout=0.05)

        if risultato is not None:
            # ── wakeword attiva — audio + video ─────────────────
            testo = risultato if isinstance(risultato, str) else risultato.get("testo", "")
            # FIX — nome estratto e passato correttamente a _ragiona_con_llm
            nome  = None if isinstance(risultato, str) else risultato.get("nome")

            if testo:
                logger.info(f"Trascritto da {nome or 'sconosciuto'}: {testo}")

                loop = asyncio.get_event_loop()
                # FIX — passa sia testo che nome
                risposta = await loop.run_in_executor(
                    None, _ragiona_con_llm, testo, nome
                )

                # ⚠️ AGGIORNARE quando si scrive command_sender.py
                await command_queue.put(risposta)

        else:
            # ── solo video ───────────────────────────────────────
            if ha_video():
                risposta = _ragiona_solo_video()
                # FIX — manda solo se c'è qualcosa da fare
                if risposta["movement"] != "stop" or risposta["face_emotion"] != "neutral":
                    # ⚠️ AGGIORNARE quando si scrive command_sender.py
                    await command_queue.put(risposta)

        await asyncio.sleep(0.1)