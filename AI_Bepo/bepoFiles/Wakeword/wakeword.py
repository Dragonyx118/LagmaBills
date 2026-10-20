#!/usr/bin/env python3
"""
Wakeword detector con streaming audio RAW PCM16 via WebSocket
Wakeword: hey_no_va.onnx
Destinazione: ws://100.120.32.86:5000

[AGGIORNAMENTO] DOA (Direction of Arrival) con ReSpeaker 2-Mic HAT
- Alla rilevazione della wakeword, stima la direzione del suono (sinistra/centro/destra)
- Invia la direzione via WebSocket come messaggio JSON, poi avvia lo streaming PCM16
- Lo streaming continua finché non arriva un segnale MQTT di stop
"""

import numpy as np
import sounddevice as sd
import onnxruntime as ort
import asyncio
import websockets
import threading
import queue
import time
import sys
import json
import paho.mqtt.client as mqtt

# ─── CONFIG ─────────────────────────────────────────────────────────────────
MODEL_PATH          = "hey_no_va.onnx"
WS_URI              = "ws://100.120.32.86:5000"
SAMPLE_RATE         = 16000
CHANNELS            = 2          # STEREO — mic L (ch0) e mic R (ch1)
CHUNK_MS            = 32
CHUNK_SAMPLES       = int(SAMPLE_RATE * CHUNK_MS / 1000)
DETECTION_THRESHOLD = 0.5

# ─── DOA CONFIG ─────────────────────────────────────────────────────────────
# Distanza tra i due microfoni del ReSpeaker 2-Mic HAT (in metri)
MIC_DISTANCE_M      = 0.065      # ~6.5 cm
SPEED_OF_SOUND      = 343.0      # m/s a temperatura ambiente
# Max delay teorico in campioni tra i due mic
MAX_DELAY_SAMPLES   = int(MIC_DISTANCE_M / SPEED_OF_SOUND * SAMPLE_RATE)  # ~3 campioni

# Angolo minimo (gradi) per considerare sinistra/destra invece di centro
DOA_CENTER_DEADZONE = 20         # ±20° → "centro"

# Numero di chunk da accumulare prima di calcolare la DOA (più campioni = più preciso)
DOA_ACCUMULATE_CHUNKS = 8        # 8 × 32ms = 256ms di audio

# ─── MQTT CONFIG ─────────────────────────────────────────────────────────────
MQTT_BROKER         = "100.120.32.86"   # stesso host della macchinina (o broker separato)
MQTT_PORT           = 1883
MQTT_TOPIC_STOP     = "macchinina/audio/stop"   # topic che ferma lo streaming
MQTT_CLIENT_ID      = "wakeword_detector"
# ─────────────────────────────────────────────────────────────────────────────


class WakewordDetector:
    def __init__(self, model_path):
        print(f"[*] Caricamento modello: {model_path}")
        self.session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        inp = self.session.get_inputs()[0]
        out = self.session.get_outputs()[0]
        print(f"    Input : {inp.name} shape={inp.shape}")
        print(f"    Output: {out.name} shape={out.shape}")
        self.input_name  = inp.name
        self.output_name = out.name
        self.input_shape = inp.shape

        flat_samples = 1
        for d in self.input_shape:
            if isinstance(d, int) and d > 1:
                flat_samples *= d
        self.window_samples = flat_samples if flat_samples > 1 else SAMPLE_RATE
        print(f"    Finestra: {self.window_samples} campioni "
              f"({self.window_samples / SAMPLE_RATE * 1000:.0f} ms)")
        self.buffer = np.zeros(self.window_samples, dtype=np.float32)

    def update(self, chunk_mono: np.ndarray) -> float:
        """Aggiorna con chunk MONO (canale sinistro) e ritorna la confidence."""
        chunk = chunk_mono.astype(np.float32).flatten()
        self.buffer = np.roll(self.buffer, -len(chunk))
        self.buffer[-len(chunk):] = chunk
        x = self.buffer.reshape(self.input_shape).astype(np.float32)
        result = self.session.run([self.output_name], {self.input_name: x})[0]
        flat = result.flatten()
        return float(flat[-1] if len(flat) > 1 else flat[0])


class DOAEstimator:
    """
    Stima la direzione d'arrivo del suono tramite GCC-PHAT
    (Generalized Cross-Correlation with Phase Transform).
    Funziona con 2 microfoni → angolo orizzontale sinistra/centro/destra.
    """
    def __init__(self):
        self.buffer_l = np.array([], dtype=np.float32)
        self.buffer_r = np.array([], dtype=np.float32)
        self.chunk_count = 0

    def add_chunk(self, left: np.ndarray, right: np.ndarray):
        self.buffer_l = np.concatenate([self.buffer_l, left.flatten()])
        self.buffer_r = np.concatenate([self.buffer_r, right.flatten()])
        self.chunk_count += 1

    def ready(self) -> bool:
        return self.chunk_count >= DOA_ACCUMULATE_CHUNKS

    def estimate(self) -> tuple[float, str]:
        """
        Ritorna (angolo_gradi, direzione) dove:
          - angolo_gradi: negativo = sinistra, positivo = destra
          - direzione: "sinistra" | "centro" | "destra"
        """
        angle_deg, direction = _gcc_phat_angle(self.buffer_l, self.buffer_r)
        self.reset()
        return angle_deg, direction

    def reset(self):
        self.buffer_l = np.array([], dtype=np.float32)
        self.buffer_r = np.array([], dtype=np.float32)
        self.chunk_count = 0


def _gcc_phat_angle(sig_l: np.ndarray, sig_r: np.ndarray) -> tuple[float, str]:
    """
    GCC-PHAT: calcola il ritardo tra i due segnali e lo converte in angolo.
    Ritorna (angolo_gradi, direzione).
    """
    n = len(sig_l) + len(sig_r)
    # FFT di entrambi i canali
    SIG_L = np.fft.rfft(sig_l, n=n)
    SIG_R = np.fft.rfft(sig_r, n=n)

    # Cross-correlazione con normalizzazione PHAT (Phase Transform)
    # La normalizzazione rende il metodo robusto al rumore
    cross = SIG_L * np.conj(SIG_R)
    denom = np.abs(cross)
    denom[denom < 1e-10] = 1e-10   # evita divisione per zero
    gcc = np.fft.irfft(cross / denom, n=n)

    # Cerca il picco nel range fisicamente valido (±MAX_DELAY_SAMPLES)
    center = len(gcc) // 2
    # Sposta la correlazione al centro per trovare il lag
    gcc_shifted = np.roll(gcc, center)
    search_range = min(MAX_DELAY_SAMPLES + 2, center)
    search_start = center - search_range
    search_end   = center + search_range + 1
    local = gcc_shifted[search_start:search_end]
    peak_idx = np.argmax(local)
    delay_samples = peak_idx - search_range  # negativo = L anticipa, positivo = R anticipa

    # Converti delay in angolo: sin(θ) = delay × c / (fs × d)
    sin_theta = (delay_samples * SPEED_OF_SOUND) / (SAMPLE_RATE * MIC_DISTANCE_M)
    sin_theta = np.clip(sin_theta, -1.0, 1.0)
    angle_deg = float(np.degrees(np.arcsin(sin_theta)))
    # Convenzione: angolo > 0 → destra, angolo < 0 → sinistra

    if abs(angle_deg) <= DOA_CENTER_DEADZONE:
        direction = "centro"
    elif angle_deg > 0:
        direction = "destra"
    else:
        direction = "sinistra"

    return angle_deg, direction


# ─── CODE CONDIVISO TRA THREAD ───────────────────────────────────────────────
audio_queue: queue.Queue = queue.Queue()
direction_queue: queue.Queue = queue.Queue()  # messaggi JSON direzione
streaming_active = threading.Event()


# ─── MQTT ────────────────────────────────────────────────────────────────────
def on_mqtt_connect(client, userdata, flags, rc):
    if rc == 0:
        print(f"[MQTT] Connesso al broker {MQTT_BROKER}:{MQTT_PORT}")
        client.subscribe(MQTT_TOPIC_STOP)
        print(f"[MQTT] In ascolto su topic: {MQTT_TOPIC_STOP}")
    else:
        print(f"[MQTT] Connessione fallita (rc={rc}), riprovo...")


def on_mqtt_message(client, userdata, msg):
    """Qualsiasi messaggio sul topic di stop ferma lo streaming."""
    payload = msg.payload.decode(errors="ignore").strip()
    print(f"\n[MQTT] Segnale di stop ricevuto (topic={msg.topic}, payload='{payload}')")
    if streaming_active.is_set():
        streaming_active.clear()
        print("[MQTT] Streaming fermato. Torno in ascolto wakeword.\n")


def start_mqtt():
    """Avvia il client MQTT in loop bloccante su un thread dedicato."""
    client = mqtt.Client(client_id=MQTT_CLIENT_ID)
    client.on_connect = on_mqtt_connect
    client.on_message = on_mqtt_message
    client.reconnect_delay_set(min_delay=1, max_delay=10)
    while True:
        try:
            client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            client.loop_forever()   # bloccante, gestisce auto-reconnect
        except Exception as e:
            print(f"[MQTT] Errore connessione: {e}, riprovo in 5s...")
            time.sleep(5)
# ─────────────────────────────────────────────────────────────────────────────


async def ws_sender():
    """
    WebSocket persistente.
    1) Invia subito un messaggio JSON con la direzione quando la wakeword è rilevata.
    2) Poi invia i frame PCM16 raw dello streaming audio.
    """
    while True:
        try:
            print(f"[WS] Connessione a {WS_URI} ...")
            async with websockets.connect(
                WS_URI,
                ping_interval=5,
                max_size=None,
            ) as ws:
                print(f"[WS] Connesso!")
                while True:
                    # Controlla se c'è una direzione da mandare (priorità alta)
                    try:
                        direction_msg = direction_queue.get_nowait()
                        await ws.send(direction_msg)   # JSON testuale
                        print(f"[WS] Direzione inviata: {direction_msg}")
                    except queue.Empty:
                        pass

                    # Poi audio PCM16
                    try:
                        raw_bytes = audio_queue.get(timeout=0.05)
                    except queue.Empty:
                        await asyncio.sleep(0)
                        continue

                    if streaming_active.is_set():
                        await ws.send(raw_bytes)   # binario raw PCM16

        except (websockets.ConnectionClosed, OSError) as e:
            print(f"[WS] Disconnesso ({e}), riconnessione in 2s...")
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[WS] Errore: {e}, riconnessione in 2s...")
            await asyncio.sleep(2)


def run_asyncio_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ws_sender())


def main():
    detector = WakewordDetector(MODEL_PATH)
    doa = DOAEstimator()

    loop = asyncio.new_event_loop()
    ws_thread = threading.Thread(target=run_asyncio_loop, args=(loop,), daemon=True)
    ws_thread.start()

    mqtt_thread = threading.Thread(target=start_mqtt, daemon=True)
    mqtt_thread.start()

    cooldown = 0

    print(f"\n[*] In ascolto... (soglia={DETECTION_THRESHOLD})")
    print(f"    Streaming RAW PCM16 verso {WS_URI}")
    print(f"    Sample rate: {SAMPLE_RATE}Hz, STEREO, 16-bit little-endian")
    print(f"    DOA: distanza mic={MIC_DISTANCE_M*100:.1f}cm, "
          f"deadzone=±{DOA_CENTER_DEADZONE}°, "
          f"finestra={DOA_ACCUMULATE_CHUNKS * CHUNK_MS}ms")
    print(f"    MQTT stop: {MQTT_BROKER}:{MQTT_PORT} → topic '{MQTT_TOPIC_STOP}'")
    print("    [Ctrl+C per uscire]\n")

    def audio_callback(indata, frames, time_info, status):
        nonlocal cooldown
        if status:
            print(f"[!] {status}", file=sys.stderr)

        # indata shape: (frames, 2) — canale 0=L, 1=R
        ch_l = indata[:, 0].copy()   # mic sinistro
        ch_r = indata[:, 1].copy()   # mic destro

        # ── Streaming audio (mono, canale sinistro) verso WebSocket ──
        pcm16 = (ch_l * 32767).clip(-32768, 32767).astype(np.int16)
        audio_queue.put(bytes(pcm16))

        # ── Aggiornamento DOA buffer ──
        doa.add_chunk(ch_l, ch_r)

        if cooldown > 0:
            cooldown -= 1
            return

        # ── Se lo streaming è già attivo non fare detection ──
        if streaming_active.is_set():
            return

        # ── Wakeword detection (usa solo il canale sinistro) ──
        score = detector.update(ch_l)
        bar = "█" * int(score * 20)
        print(f"\r  confidence: {score:.3f} [{bar:<20}]", end="", flush=True)

        if score >= DETECTION_THRESHOLD:
            # Calcola DOA con i campioni accumulati finora
            if doa.ready():
                angle, direction = doa.estimate()
            else:
                # Usa quello che c'è anche se non è ancora pieno
                angle, direction = _gcc_phat_angle(doa.buffer_l, doa.buffer_r) \
                    if len(doa.buffer_l) > 0 else (0.0, "centro")
                doa.reset()

            print(f"\n\n[!] WAKEWORD rilevata! (confidence={score:.3f})")
            print(f"    DOA: {angle:+.1f}° → {direction.upper()}")

            # Manda la direzione via WebSocket come JSON
            msg = json.dumps({
                "event":     "wakeword",
                "direction": direction,         # "sinistra" | "centro" | "destra"
                "angle_deg": round(angle, 1),
                "confidence": round(score, 3),
                "timestamp": time.time(),
            })
            direction_queue.put(msg)

            streaming_active.set()
            cooldown = int(3000 / CHUNK_MS)

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,        # STEREO
            blocksize=CHUNK_SAMPLES,
            dtype="float32",
            callback=audio_callback,
        ):
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n[*] Uscita.")


if __name__ == "__main__":
    main()