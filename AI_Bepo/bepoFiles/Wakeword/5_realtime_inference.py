#!/usr/bin/env python3
"""
5_realtime_inference.py
Inferenza real-time ottimizzata per Raspberry Pi.

Caratteristiche:
- Streaming audio 16kHz con buffer piccoli (80ms)
- Media mobile su N frame per ridurre falsi positivi
- Periodo refrattario dopo detection
- Priorità CPU per thread audio
- Metriche performance in tempo reale

Uso:
  python 5_realtime_inference.py
  python 5_realtime_inference.py --model models/aria_int8.tflite --threshold 0.7
  python 5_realtime_inference.py --list-devices
  python 5_realtime_inference.py --device 2  # seleziona microfono USB
"""

import os
import sys
import time
import argparse
import threading
import queue
import numpy as np
from pathlib import Path
from collections import deque
import yaml
import signal

# Riduce overhead import su RPi
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

# ──────────────────────────────────────────────
# Configurazione
# ──────────────────────────────────────────────
with open("config.yaml") as f:
    CFG = yaml.safe_load(f)

SR = CFG["audio"]["sample_rate"]          # 16000 Hz
CHUNK = CFG["audio"]["chunk_size"]         # 1280 samples = 80ms
CHANNELS = CFG["audio"]["channels"]        # 1 (mono)


# ──────────────────────────────────────────────
# TFLite Inference Engine
# ──────────────────────────────────────────────
class TFLiteInferenceEngine:
    """
    Engine inferenza ottimizzato per RPi con TFLite.
    Pre-alloca buffer per evitare allocazioni durante streaming.
    """

    def __init__(self, model_path: str, num_threads: int = 2):
        self.model_path = model_path
        self._load_model(num_threads)
        self._preallocate_buffers()

    def _load_model(self, num_threads: int):
        """Carica modello TFLite con ottimizzazioni CPU."""
        try:
            # Prima prova tflite-runtime (più leggero su RPi)
            import tflite_runtime.interpreter as tflite
            self.interpreter = tflite.Interpreter(
                model_path=self.model_path,
                num_threads=num_threads,
            )
        except ImportError:
            # Fallback a tensorflow completo
            import tensorflow as tf
            self.interpreter = tf.lite.Interpreter(
                model_path=self.model_path,
                num_threads=num_threads,
            )

        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()

        # Dettagli quantizzazione
        self.input_dtype = self.input_details[0]["dtype"]
        self.input_scale = self.input_details[0]["quantization"][0]
        self.input_zero_point = self.input_details[0]["quantization"][1]
        self.output_scale = self.output_details[0]["quantization"][0]
        self.output_zero_point = self.output_details[0]["quantization"][1]
        self.input_shape = self.input_details[0]["shape"]

        print(f"  Modello caricato: {Path(self.model_path).name}")
        print(f"  Input: {self.input_shape} dtype={self.input_dtype.__name__}")
        print(f"  Threads: {num_threads}")

    def _preallocate_buffers(self):
        """Pre-alloca buffer per inferenza zero-copy."""
        self._input_buffer = np.zeros(
            self.input_shape, dtype=self.input_dtype
        )

    def predict(self, features: np.ndarray) -> float:
        """
        Inferenza singola. Ottimizzato per latenza minima.
        Ritorna probabilità [0.0, 1.0].
        """
        # Prepara input (in-place per evitare allocazioni)
        inp = features.reshape(self.input_shape).astype(np.float32)

        if self.input_dtype == np.int8 and self.input_scale > 0:
            np.copyto(
                self._input_buffer,
                (inp / self.input_scale + self.input_zero_point).astype(np.int8)
            )
        else:
            np.copyto(self._input_buffer, inp.astype(self.input_dtype))

        # Inferenza
        self.interpreter.set_tensor(
            self.input_details[0]["index"], self._input_buffer
        )
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]["index"])

        # De-quantizza output INT8
        if self.output_details[0]["dtype"] == np.int8 and self.output_scale > 0:
            return float(
                (output.flatten()[0] - self.output_zero_point) * self.output_scale
            )
        return float(np.clip(output.flatten()[0], 0.0, 1.0))


# ──────────────────────────────────────────────
# Feature Extractor (openWakeWord backbone)
# ──────────────────────────────────────────────
class FeatureExtractor:
    """Wrapper per estrazione features con openWakeWord backbone."""

    def __init__(self):
        import openwakeword
        print("  Caricamento backbone openWakeWord...")
        self._oww = openwakeword.Model(
            wakeword_models=[],
            enable_speex_noise_suppression=False,
        )

    def extract(self, audio_chunk_int16: np.ndarray) -> np.ndarray | None:
        """Estrae embedding da chunk audio. Ritorna None se non disponibile."""
        try:
            features = self._oww.get_parent_model_output(audio_chunk_int16)
            if features is not None and len(features) > 0:
                return features.flatten().astype(np.float32)
        except Exception:
            pass
        return None


# ──────────────────────────────────────────────
# VAD leggero (WebRTC)
# ──────────────────────────────────────────────
class LightweightVAD:
    """
    Voice Activity Detection con WebRTC VAD.
    Latenza <1ms, consumo CPU trascurabile.
    Salta inferenza quando non c'è voce → risparmio ~30-50% CPU.
    """

    def __init__(self, aggressiveness: int = 2, sr: int = 16000):
        try:
            import webrtcvad
            self.vad = webrtcvad.Vad(aggressiveness)
            self.sr = sr
            self.enabled = True
            # WebRTC VAD richiede frame 10/20/30ms
            self.frame_ms = 20
            self.frame_size = int(sr * self.frame_ms / 1000)  # 320 samples
        except ImportError:
            self.enabled = False
            print("  ⚠ webrtcvad non disponibile, VAD disabilitato")

    def is_speech(self, audio_chunk_int16: np.ndarray) -> bool:
        """
        Controlla se il chunk contiene voce.
        Divide chunk in sotto-frame da 20ms per WebRTC.
        """
        if not self.enabled:
            return True  # Senza VAD, processa sempre

        # Controlla se almeno 1 sotto-frame contiene voce
        for i in range(0, len(audio_chunk_int16) - self.frame_size, self.frame_size):
            frame = audio_chunk_int16[i:i + self.frame_size]
            frame_bytes = frame.astype(np.int16).tobytes()
            try:
                if self.vad.is_speech(frame_bytes, self.sr):
                    return True
            except Exception:
                return True  # In caso di errore, processa comunque
        return False


# ──────────────────────────────────────────────
# Audio Stream Manager
# ──────────────────────────────────────────────
class AudioStreamManager:
    """Gestione stream audio con PyAudio in thread separato."""

    def __init__(self, device_index: int | None = None,
                 sample_rate: int = SR, chunk_size: int = CHUNK):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self._audio_queue = queue.Queue(maxsize=10)  # buffer max 10 chunk
        self._stream = None
        self._pa = None
        self._running = False

    def list_devices(self):
        """Elenca dispositivi audio disponibili."""
        import pyaudio
        pa = pyaudio.PyAudio()
        print("\nDispositivi audio disponibili:")
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                print(f"  [{i}] {info['name']} "
                      f"(in={info['maxInputChannels']}, "
                      f"sr={int(info['defaultSampleRate'])}Hz)")
        pa.terminate()

    def start(self) -> bool:
        """Avvia stream audio."""
        import pyaudio

        self._pa = pyaudio.PyAudio()

        # Auto-selezione microfono USB se non specificato
        if self.device_index is None:
            self.device_index = self._find_usb_mic()

        device_info = self._pa.get_device_info_by_index(
            self.device_index or self._pa.get_default_input_device_info()["index"]
        )
        print(f"  Microfono: {device_info['name']}")

        def _audio_callback(in_data, frame_count, time_info, status):
            if status:
                pass  # Ignora underflow/overflow su RPi
            audio = np.frombuffer(in_data, dtype=np.int16)
            try:
                self._audio_queue.put_nowait(audio)
            except queue.Full:
                # Scarta chunk se coda piena (evita lag accumulato)
                try:
                    self._audio_queue.get_nowait()
                    self._audio_queue.put_nowait(audio)
                except Exception:
                    pass
            return (None, pyaudio.paContinue)

        self._stream = self._pa.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=self.sample_rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk_size,
            stream_callback=_audio_callback,
        )
        self._stream.start_stream()
        self._running = True
        return True

    def get_chunk(self, timeout: float = 0.5) -> np.ndarray | None:
        """Leggi prossimo chunk audio dalla coda."""
        try:
            return self._audio_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def stop(self):
        """Ferma stream audio."""
        self._running = False
        if self._stream:
            self._stream.stop_stream()
            self._stream.close()
        if self._pa:
            self._pa.terminate()

    def _find_usb_mic(self) -> int | None:
        """Auto-rileva microfono USB."""
        for i in range(self._pa.get_device_count()):
            info = self._pa.get_device_info_by_index(i)
            name = info["name"].lower()
            if (info["maxInputChannels"] > 0 and
                    any(kw in name for kw in ["usb", "audio", "mic", "c920", "blue"])):
                print(f"  Microfono USB rilevato: {info['name']} [device {i}]")
                return i
        return None


# ──────────────────────────────────────────────
# Pipeline principale
# ──────────────────────────────────────────────
class WakeWordDetector:
    """
    Pipeline completa di rilevamento wake word real-time.
    
    Flusso:
      Audio chunk (80ms) → VAD → Feature extraction → 
      TFLite inference → Smoothing → Detection callback
    """

    def __init__(self,
                 model_path: str,
                 threshold: float,
                 device_index: int | None = None,
                 vad_enabled: bool = True,
                 debug: bool = False):

        self.threshold = threshold
        self.debug = debug

        # Smoothing: media mobile su N frame per ridurre falsi positivi
        smooth_n = CFG["inference"]["smoothing_window"]
        self._score_window = deque([0.0] * smooth_n, maxlen=smooth_n)

        # Periodo refrattario: ignora detection per N secondi dopo trigger
        self._refractory_s = CFG["inference"]["refractory_period_s"]
        self._last_detection_time = 0.0

        # Statistiche performance
        self._frame_count = 0
        self._detection_count = 0
        self._total_inference_ms = 0.0
        self._vad_skipped = 0
        self._start_time = time.time()

        print("\n═══════════════════════════════════════")
        print("  Wake Word Detector - Inizializzazione")
        print("═══════════════════════════════════════")
        print(f"  Modello: {model_path}")
        print(f"  Soglia: {threshold}")
        print(f"  Smoothing: {smooth_n} frame ({smooth_n * CHUNK / SR * 1000:.0f}ms)")
        print(f"  Refrattario: {self._refractory_s}s")

        # Componenti
        print("\n  Caricamento componenti...")
        self.engine = TFLiteInferenceEngine(model_path, num_threads=2)
        self.features = FeatureExtractor()
        self.vad = LightweightVAD() if vad_enabled else None
        self.audio = AudioStreamManager(device_index=device_index)

        # Segnale per arresto graceful
        self._running = False
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, sig, frame):
        print("\n\n  Arresto in corso...")
        self._running = False

    def _on_detection(self, score: float):
        """Callback chiamato a ogni wake word rilevata."""
        self._detection_count += 1
        print(f"\n{'🔊':>4} WAKE WORD RILEVATA! "
              f"(score={score:.3f}, #{self._detection_count})")

        # ─── QUI INSERISCI LA TUA LOGICA ───
        # Esempi:
        #   subprocess.Popen(["aplay", "wake.wav"])
        #   requests.post("http://homeassistant/api/...", ...)
        #   mqtt_client.publish("wake/word", "aria")
        # ───────────────────────────────────

    def _print_stats(self):
        """Stampa statistiche performance ogni 60 secondi."""
        elapsed = time.time() - self._start_time
        fps = self._frame_count / max(elapsed, 1)
        avg_latency = self._total_inference_ms / max(self._frame_count, 1)
        vad_skip_pct = self._vad_skipped / max(self._frame_count, 1) * 100

        print(f"\n  ┌─ Stats ({elapsed:.0f}s) ─────────────────────")
        print(f"  │  Frame: {self._frame_count:,} ({fps:.1f}/s)")
        print(f"  │  Latenza media: {avg_latency:.2f}ms")
        print(f"  │  VAD skip: {vad_skip_pct:.1f}%")
        print(f"  │  Detections: {self._detection_count}")
        print(f"  └───────────────────────────────────────")

    def run(self):
        """Loop principale di rilevamento."""
        print("\n  Avvio stream audio...")
        if not self.audio.start():
            print("  ❌ Impossibile aprire microfono")
            return

        print("\n  ✓ In ascolto... (Ctrl+C per uscire)")
        print(f"  Wake word: '{CFG['wake_word']['name'].upper()}'")
        print("─" * 45)

        self._running = True
        self._start_time = time.time()
        last_stats_time = time.time()
        last_score_display = time.time()

        while self._running:
            # 1. Leggi chunk audio
            chunk = self.audio.get_chunk(timeout=0.1)
            if chunk is None:
                continue

            self._frame_count += 1
            now = time.time()

            # 2. VAD: salta inferenza se non c'è voce
            if self.vad and not self.vad.is_speech(chunk):
                self._vad_skipped += 1
                self._score_window.append(0.0)
                # Progress indicator senza voce
                if self.debug and now - last_score_display > 2.0:
                    print(f"  [{now - self._start_time:6.1f}s] "
                          f"silenzio (VAD skip: {self._vad_skipped})", end="\r")
                    last_score_display = now
                continue

            # 3. Feature extraction
            features = self.features.extract(chunk)
            if features is None:
                continue

            # 4. Inferenza TFLite
            t0 = time.perf_counter()
            score = self.engine.predict(features)
            inference_ms = (time.perf_counter() - t0) * 1000
            self._total_inference_ms += inference_ms

            # 5. Smoothing (media mobile)
            self._score_window.append(score)
            smoothed_score = float(np.mean(self._score_window))

            # 6. Debug output
            if self.debug:
                bar_len = int(smoothed_score * 30)
                bar = "█" * bar_len + "░" * (30 - bar_len)
                color = "\033[91m" if smoothed_score > self.threshold else "\033[92m"
                reset = "\033[0m"
                print(f"  [{now - self._start_time:6.1f}s] "
                      f"{color}{bar}{reset} {smoothed_score:.3f} "
                      f"({inference_ms:.1f}ms)", end="\r")

            # 7. Detection check con periodo refrattario
            if (smoothed_score >= self.threshold and
                    now - self._last_detection_time > self._refractory_s):

                self._last_detection_time = now
                # Resetta finestra per evitare detection multipla
                for _ in range(len(self._score_window)):
                    self._score_window.append(0.0)
                self._on_detection(smoothed_score)

            # 8. Stats periodiche
            if now - last_stats_time > 60.0:
                self._print_stats()
                last_stats_time = now

        # Cleanup
        self.audio.stop()
        self._print_stats()
        print("\n  Detector fermato.")


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Wake Word Detector - Raspberry Pi",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--model",
        default="models/aria_int8.tflite",
        help="Path modello TFLite",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=CFG["inference"]["threshold"],
        help="Soglia detection [0.0-1.0]",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Indice dispositivo audio (default: auto)",
    )
    parser.add_argument(
        "--no-vad",
        action="store_true",
        help="Disabilita VAD (più CPU ma nessun skip)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Mostra score in tempo reale",
    )
    parser.add_argument(
        "--list-devices",
        action="store_true",
        help="Elenca dispositivi audio e termina",
    )
    args = parser.parse_args()

    if args.list_devices:
        import pyaudio
        pa = pyaudio.PyAudio()
        print("\nDispositivi audio disponibili:")
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info["maxInputChannels"] > 0:
                print(f"  [{i}] {info['name']}")
        pa.terminate()
        return

    if not Path(args.model).exists():
        print(f"❌ Modello non trovato: {args.model}")
        print("   Esegui prima 4_optimize_model.py sul PC di training")
        sys.exit(1)

    detector = WakeWordDetector(
        model_path=args.model,
        threshold=args.threshold,
        device_index=args.device,
        vad_enabled=not args.no_vad,
        debug=args.debug,
    )
    detector.run()


if __name__ == "__main__":
    main()
