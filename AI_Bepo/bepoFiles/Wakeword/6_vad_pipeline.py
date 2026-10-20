#!/usr/bin/env python3
"""
6_vad_pipeline.py
Utilità avanzate per ottimizzazione RPi:

1. TuningLab     - trova threshold ottimale con curve ROC
2. StressTest    - benchmark CPU/RAM su RPi
3. ThresholdSweep- sweep soglie su audio reale registrato
4. SystemOptimizer - suggerimenti configurazione RPi

Uso:
  python 6_vad_pipeline.py --tune          # Analisi threshold
  python 6_vad_pipeline.py --stress        # Stress test performance
  python 6_vad_pipeline.py --sweep AUDIO   # Sweep su file audio
  python 6_vad_pipeline.py --rpi-optimize  # Consigli ottimizzazione RPi
"""

import os
import sys
import time
import argparse
import numpy as np
from pathlib import Path
import yaml

os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

with open("config.yaml") as f:
    CFG = yaml.safe_load(f)

SR = CFG["audio"]["sample_rate"]
CHUNK = CFG["audio"]["chunk_size"]


# ──────────────────────────────────────────────
# 1. Threshold Tuning
# ──────────────────────────────────────────────
class ThresholdTuner:
    """
    Trova threshold ottimale analizzando:
    - Precision/Recall curve
    - False Positive Rate
    - Detection Rate su audio reale
    """

    def __init__(self, model_path: str):
        from wakeword_pipeline import TFLiteInferenceEngine, FeatureExtractor
        self.engine = TFLiteInferenceEngine(model_path)
        self.features = FeatureExtractor()

    def score_audio_file(self, audio_path: str) -> list[float]:
        """Calcola score frame-by-frame su un file audio."""
        import soundfile as sf

        audio, sr = sf.read(audio_path)
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)
        audio_int16 = (audio * 32767).astype(np.int16)

        scores = []
        for i in range(0, len(audio_int16) - CHUNK, CHUNK // 2):
            chunk = audio_int16[i:i + CHUNK]
            feat = self.features.extract(chunk)
            if feat is not None:
                scores.append(self.engine.predict(feat))
        return scores

    def analyze_threshold_sweep(self, positive_dir: str,
                                 negative_dir: str,
                                 n_files: int = 50):
        """
        Sweep threshold [0.1, 0.99] e calcola metriche.
        Genera curva ROC e suggerisce threshold ottimale.
        """
        print("Analisi threshold sweep...")

        # Raccoglie score
        pos_scores, neg_scores = [], []

        pos_files = list(Path(positive_dir).glob("*.wav"))[:n_files]
        neg_files = list(Path(negative_dir).rglob("*.wav"))[:n_files]

        print(f"  Scoring {len(pos_files)} positivi...")
        for f in pos_files:
            scores = self.score_audio_file(str(f))
            if scores:
                pos_scores.append(max(scores))  # Peak score per file

        print(f"  Scoring {len(neg_files)} negativi...")
        for f in neg_files:
            scores = self.score_audio_file(str(f))
            if scores:
                neg_scores.append(max(scores))

        if not pos_scores or not neg_scores:
            print("❌ Dati insufficienti")
            return

        pos_scores = np.array(pos_scores)
        neg_scores = np.array(neg_scores)

        print(f"\n  Score positivi: mean={pos_scores.mean():.3f} "
              f"std={pos_scores.std():.3f} min={pos_scores.min():.3f}")
        print(f"  Score negativi: mean={neg_scores.mean():.3f} "
              f"std={neg_scores.std():.3f} max={neg_scores.max():.3f}")

        print(f"\n  {'Threshold':>10} | {'TPR%':>8} | {'FPR%':>8} | "
              f"{'Precision':>10} | {'F1':>8}")
        print("  " + "-"*55)

        best_f1, best_thresh = 0, 0.5

        for thresh in np.arange(0.3, 0.98, 0.05):
            tpr = (pos_scores >= thresh).mean()
            fpr = (neg_scores >= thresh).mean()
            precision = tpr / (tpr + fpr + 1e-8)
            recall = tpr
            f1 = 2 * precision * recall / (precision + recall + 1e-8)

            marker = " ← " if f1 > best_f1 else ""
            if f1 > best_f1:
                best_f1, best_thresh = f1, thresh

            print(f"  {thresh:>10.2f} | {tpr*100:>7.1f}% | {fpr*100:>7.1f}% | "
                  f"{precision*100:>9.1f}% | {f1*100:>7.1f}%{marker}")

        print(f"\n  ✓ Threshold ottimale: {best_thresh:.2f} (F1={best_f1:.3f})")
        print(f"\n  Aggiorna config.yaml:")
        print(f"    inference.threshold: {best_thresh:.2f}")


# ──────────────────────────────────────────────
# 2. Stress Test Performance
# ──────────────────────────────────────────────
class StressTester:
    """Benchmark completo per valutare performance su RPi."""

    def __init__(self, model_path: str):
        from wakeword_pipeline import TFLiteInferenceEngine, FeatureExtractor
        self.engine = TFLiteInferenceEngine(model_path)
        self.features = FeatureExtractor()
        self.model_path = model_path

    def run_inference_benchmark(self, n_runs: int = 500) -> dict:
        """Benchmark latenza inferenza."""
        print(f"\nBenchmark inferenza ({n_runs} runs)...")

        # Genera input casuale
        test_input = np.random.randn(96).astype(np.float32)

        # Warmup
        for _ in range(20):
            self.engine.predict(test_input)

        # Benchmark
        latencies = []
        for _ in range(n_runs):
            t0 = time.perf_counter()
            self.engine.predict(test_input)
            latencies.append((time.perf_counter() - t0) * 1000)

        latencies = np.array(latencies)
        model_size = Path(self.model_path).stat().st_size

        results = {
            "model_size_kb": model_size / 1024,
            "mean_ms": np.mean(latencies),
            "p50_ms": np.percentile(latencies, 50),
            "p95_ms": np.percentile(latencies, 95),
            "p99_ms": np.percentile(latencies, 99),
        }

        print(f"  Modello size: {results['model_size_kb']:.1f} KB")
        print(f"  Latenza media: {results['mean_ms']:.2f}ms")
        print(f"  P50: {results['p50_ms']:.2f}ms")
        print(f"  P95: {results['p95_ms']:.2f}ms")
        print(f"  P99: {results['p99_ms']:.2f}ms")

        chunk_ms = CHUNK / SR * 1000
        utilization = results["mean_ms"] / chunk_ms * 100
        print(f"\n  Chunk audio: {chunk_ms:.0f}ms")
        print(f"  CPU utilization (solo inference): {utilization:.1f}%")

        if results["mean_ms"] < chunk_ms * 0.3:
            print("  ✓ Performance: OTTIMA (<30% del budget temporale)")
        elif results["mean_ms"] < chunk_ms * 0.6:
            print("  ✓ Performance: BUONA (<60% del budget temporale)")
        else:
            print("  ⚠ Performance: BORDERLINE (considera quantizzazione aggressiva)")

        return results

    def monitor_realtime(self, duration_s: int = 30):
        """Monitora CPU e RAM durante inferenza real-time simulata."""
        try:
            import psutil
        except ImportError:
            print("  Installa psutil: pip install psutil")
            return

        print(f"\nMonitoraggio real-time ({duration_s}s)...")
        process = psutil.Process(os.getpid())

        cpu_samples = []
        ram_samples = []

        start = time.time()
        while time.time() - start < duration_s:
            # Simula inferenza continua
            audio_chunk = np.random.randint(-32768, 32767, CHUNK, dtype=np.int16)
            feat = self.features.extract(audio_chunk)
            if feat is not None:
                self.engine.predict(feat)

            cpu_samples.append(process.cpu_percent(interval=None))
            ram_samples.append(process.memory_info().rss / 1024 / 1024)  # MB
            time.sleep(CHUNK / SR)  # Simula intervallo reale

        print(f"  CPU: mean={np.mean(cpu_samples):.1f}% "
              f"max={np.max(cpu_samples):.1f}%")
        print(f"  RAM: mean={np.mean(ram_samples):.1f}MB "
              f"max={np.max(ram_samples):.1f}MB")


# ──────────────────────────────────────────────
# 3. Sweep su file audio reale
# ──────────────────────────────────────────────
def sweep_audio_file(model_path: str, audio_path: str,
                     threshold: float = 0.5, debug: bool = True):
    """
    Analizza un file audio e mostra tutti i momenti di detection.
    Utile per verificare falsi positivi su audio reale.
    """
    from wakeword_pipeline import TFLiteInferenceEngine, FeatureExtractor
    import soundfile as sf

    engine = TFLiteInferenceEngine(model_path)
    extractor = FeatureExtractor()

    audio, sr = sf.read(audio_path)
    if len(audio.shape) > 1:
        audio = audio.mean(axis=1)
    audio_int16 = (audio * 32767).astype(np.int16)

    duration = len(audio) / sr
    print(f"\nAnalisi: {Path(audio_path).name} ({duration:.1f}s)")
    print(f"Threshold: {threshold}")
    print("-" * 50)

    detections = []
    scores_by_time = []

    smooth_window = deque([0.0] * 4, maxlen=4)

    from collections import deque
    smooth_window = deque([0.0] * 4, maxlen=4)

    for i, start in enumerate(range(0, len(audio_int16) - CHUNK, CHUNK // 2)):
        chunk = audio_int16[start:start + CHUNK]
        feat = extractor.extract(chunk)
        if feat is None:
            continue

        score = engine.predict(feat)
        smooth_window.append(score)
        smoothed = float(np.mean(smooth_window))
        timestamp = start / sr

        scores_by_time.append((timestamp, smoothed))

        if smoothed >= threshold:
            print(f"  [{timestamp:6.2f}s] DETECTION  score={smoothed:.3f}")
            detections.append(timestamp)

    print(f"\n  Totale detections: {len(detections)}")
    print(f"  Falsi positivi/ora: {len(detections) / (duration / 3600):.1f}")


# ──────────────────────────────────────────────
# 4. Consigli ottimizzazione Raspberry Pi
# ──────────────────────────────────────────────
def print_rpi_optimization_guide():
    """Stampa guida completa ottimizzazione RPi."""
    print("""
╔══════════════════════════════════════════════════════════════╗
║         GUIDA OTTIMIZZAZIONE RASPBERRY PI                     ║
╚══════════════════════════════════════════════════════════════╝

━━━ 1. SISTEMA OPERATIVO ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Usa Raspberry Pi OS Bookworm 64-bit (per NEON SIMD su ARM64)
• Disabilita servizi non necessari:
    sudo systemctl disable bluetooth
    sudo systemctl disable cups
    sudo systemctl disable triggerhappy

• Imposta CPU governor per performance:
    echo performance | sudo tee /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor

━━━ 2. PRIORITÀ PROCESSO ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Avvia con priorità alta:
    sudo nice -n -10 python 5_realtime_inference.py
    # oppure con scheduling real-time:
    sudo chrt -r 50 python 5_realtime_inference.py

• In config.yaml imposta:
    inference.chunk_size: 1280  # 80ms - bilanciamento ottimale

━━━ 3. PYTHON ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Usa PyPy3 se compatibile con le tue dipendenze:
    pypy3 5_realtime_inference.py  # 2-5x più veloce per pure Python

• Disabilita GIL (Python 3.13+ experimental):
    PYTHON_GIL=0 python 5_realtime_inference.py

• Precarica il modello all'avvio (già fatto nella nostra pipeline)

━━━ 4. TFLITE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Usa tflite-runtime invece di tensorflow completo:
    pip install tflite-runtime  # ~5MB vs ~500MB

• Numero thread ottimale per RPi 4:
    num_threads=2  # 4 core, lascia 2 per sistema

• Abilita XNNPACK delegate (acceleratore CPU):
    # Già abilitato di default in tflite-runtime >=2.10

━━━ 5. AUDIO ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Microfono USB consigliato:
    - ReSpeaker 2-Mic Pi HAT (beamforming hardware)
    - Jabra Speak 410
    - RØDE NT-USB Mini

• Configurazione ALSA bassa latenza (/etc/asound.conf):
    pcm.!default {
        type hw
        card 1        # numero card USB
        device 0
    }
    ctl.!default {
        type hw
        card 1
    }

• Testa latenza microfono:
    arecord -D hw:1,0 -f S16_LE -r 16000 -c 1 -d 5 test.wav
    aplay test.wav

━━━ 6. VAD (Voice Activity Detection) ━━━━━━━━━━━━━━━━━━━━━━━━

• webrtcvad aggressiveness:
    0 = poco aggressivo (più sensibile alla voce)
    1 = equilibrato ← CONSIGLIATO per ambienti silenziosi
    2 = moderato  ← CONSIGLIATO per ambienti con rumore
    3 = molto aggressivo (potrebbe tagliare voce bassa)

• Con VAD attivo, risparmio tipico CPU: 30-50%

━━━ 7. OTTIMIZZAZIONI AVANZATE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

• Affinity CPU (dedica core 2-3 all'inferenza):
    taskset -c 2,3 python 5_realtime_inference.py

• Mlock memoria (evita swapping):
    import ctypes
    ctypes.CDLL("libc.so.6").mlockall(3)

• Hugepages per modello grande:
    sudo sysctl vm.nr_hugepages=4

• Disabilita power management USB (evita glitch audio):
    echo on | sudo tee /sys/bus/usb/devices/*/power/control

━━━ 8. PARAMETRI OTTIMALI TESTATI ━━━━━━━━━━━━━━━━━━━━━━━━━━━━

┌─────────────────────┬────────────────────────────────────┐
│ Parametro           │ RPi 4 (4GB)    │ RPi 5 (4GB)      │
├─────────────────────┼─────────────────┼──────────────────┤
│ Chunk size          │ 1280 (80ms)     │ 1280 (80ms)      │
│ TFLite threads      │ 2               │ 2                │
│ Smoothing window    │ 4 frame         │ 4 frame          │
│ Latenza inferenza   │ ~5-8ms          │ ~2-4ms           │
│ CPU usage totale    │ ~15-25%         │ ~8-15%           │
│ RAM usage           │ ~80-120MB       │ ~80-120MB        │
│ Latenza end-to-end  │ ~150-200ms      │ ~100-150ms       │
└─────────────────────┴─────────────────┴──────────────────┘

━━━ 9. AUTOSTART AL BOOT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Crea /etc/systemd/system/wakeword.service:
[Unit]
Description=Wake Word Detector
After=sound.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/wakeword/5_realtime_inference.py
WorkingDirectory=/home/pi/wakeword
Restart=on-failure
RestartSec=5
Nice=-10
User=pi

[Install]
WantedBy=multi-user.target

# Abilita:
sudo systemctl enable wakeword
sudo systemctl start wakeword
sudo systemctl status wakeword
""")


# ──────────────────────────────────────────────
# Main CLI
# ──────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Utilità ottimizzazione wake word")
    parser.add_argument("--model", default="models/aria_int8.tflite")
    parser.add_argument("--tune", action="store_true",
                        help="Analisi threshold con curva ROC")
    parser.add_argument("--stress", action="store_true",
                        help="Stress test performance")
    parser.add_argument("--sweep", metavar="AUDIO_FILE",
                        help="Sweep detection su file audio")
    parser.add_argument("--threshold", type=float,
                        default=CFG["inference"]["threshold"])
    parser.add_argument("--rpi-optimize", action="store_true",
                        help="Mostra guida ottimizzazione RPi")
    args = parser.parse_args()

    if args.rpi_optimize:
        print_rpi_optimization_guide()
        return

    if args.tune:
        tuner = ThresholdTuner(args.model)
        tuner.analyze_threshold_sweep("data/positive", "data/negative")
        return

    if args.stress:
        tester = StressTester(args.model)
        tester.run_inference_benchmark(n_runs=1000)
        tester.monitor_realtime(duration_s=15)
        return

    if args.sweep:
        sweep_audio_file(args.model, args.sweep, args.threshold)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
