import asyncio
import json
import logging
import os

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------------
# configurazione
# -----------------------------------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "100.100.61.49")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

# topic su cui pubblica i comandi
# il Raspberry è iscritto a questo topic e esegue quello che arriva
TOPIC_CMD = "robot/cmd"

# -----------------------------------------------------------------------
# client MQTT
# -----------------------------------------------------------------------
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)


def _connect():
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        # loop_start avvia un thread in background che gestisce
        # la connessione — riconnessione automatica se cade
        mqtt_client.loop_start()
        logger.info(f"command_sender connesso a {MQTT_HOST}:{MQTT_PORT}")
    except Exception as e:
        logger.warning(f"MQTT non disponibile: {e}")


# -----------------------------------------------------------------------
# ultimo comando mandato — serve per il rate limiting
# se il comando è identico al precedente non lo rimandiamo
# evita di bombardare il Raspberry con stop continui
# -----------------------------------------------------------------------
_ultimo_comando = None


def _stesso_comando(nuovo):
    global _ultimo_comando
    # confronta solo movement e face_emotion — tts_text cambia sempre
    if _ultimo_comando is None:
        return False
    return (
        nuovo.get("movement") == _ultimo_comando.get("movement")
        and nuovo.get("face_emotion") == _ultimo_comando.get("face_emotion")
        and nuovo.get("tts_text") == _ultimo_comando.get("tts_text")
    )


# -----------------------------------------------------------------------
# funzione di invio
# -----------------------------------------------------------------------
def _pubblica(comando):
    global _ultimo_comando
    if _stesso_comando(comando):
        return
    try:
        payload = json.dumps(comando, ensure_ascii=False)
        mqtt_client.publish(TOPIC_CMD, payload)
        _ultimo_comando = comando
        logger.info(f"→ Raspberry: {payload}")

        # Se il comando contiene tts_text, ferma lo stream audio
        if comando.get("tts_text"):
            invia_wakeword_end()

    except Exception as e:
        logger.warning(f"Publish fallito: {e}")

TOPIC_STREAM = "robot/audio_stream"

def invia_wakeword_start():
    """Chiamato da wakeword.py quando rileva la wake word."""
    try:
        mqtt_client.publish(TOPIC_STREAM, "start")
        logger.info("→ Raspberry: audio_stream START")
    except Exception as e:
        logger.warning(f"Publish wakeword_start fallito: {e}")


def invia_wakeword_end():
    """Chiamato dopo aver ricevuto tts_text e inviato al Raspberry."""
    try:
        mqtt_client.publish(TOPIC_STREAM, "stop")
        logger.info("→ Raspberry: audio_stream STOP")
    except Exception as e:
        logger.warning(f"Publish wakeword_end fallito: {e}")


# -----------------------------------------------------------------------
# loop principale — legge dalla command_queue di cervello.py
# ⚠️ command_queue viene importata da cervello.py
# -----------------------------------------------------------------------
async def run(command_queue):
    # command_queue è la asyncio.Queue di cervello.py
    # cervello.py ci mette dentro i JSON
    # noi li leggiamo e li mandiamo via MQTT
    _connect()
    logger.info("command_sender avviato")

    while True:
        try:
            # aspetta il prossimo comando dalla queue
            # timeout=1 — se non arriva niente in 1 secondo continua il loop
            # questo permette di gestire Ctrl+C senza bloccarsi
            comando = await asyncio.wait_for(
                command_queue.get(),
                timeout=1.0
            )
            _pubblica(comando)
            command_queue.task_done()
        except asyncio.TimeoutError:
            # nessun comando in 1 secondo — normale, continua ad aspettare
            continue
        except Exception as e:
            logger.warning(f"Errore nel loop command_sender: {e}")
