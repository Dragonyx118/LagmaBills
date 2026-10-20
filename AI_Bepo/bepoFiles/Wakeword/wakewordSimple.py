#!/usr/bin/env python3
"""
Wakeword detector minimale — stampa a schermo quando rileva la wakeword.
Wakeword: hey_no_va.onnx
"""

import numpy as np
import sounddevice as sd
import onnxruntime as ort
import time
import sys

# ─── CONFIG ──────────────────────────────────────────────────────────────────
MODEL_PATH          = "hey_no_va.onnx"
SAMPLE_RATE         = 16000
CHUNK_MS            = 32
CHUNK_SAMPLES       = int(SAMPLE_RATE * CHUNK_MS / 1000)
DETECTION_THRESHOLD = 0.7
COOLDOWN_CHUNKS     = int(3000 / CHUNK_MS)   # 3 secondi di cooldown dopo rilevazione
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
        chunk = chunk_mono.astype(np.float32).flatten()
        self.buffer = np.roll(self.buffer, -len(chunk))
        self.buffer[-len(chunk):] = chunk
        x = self.buffer.reshape(self.input_shape).astype(np.float32)
        result = self.session.run([self.output_name], {self.input_name: x})[0]
        flat = result.flatten()
        return float(flat[-1] if len(flat) > 1 else flat[0])

    def clear_buffer(self):
        self.buffer[:] = 0


def main():
    detector = WakewordDetector(MODEL_PATH)
    cooldown = 0

    print(f"\n[*] In ascolto... (soglia={DETECTION_THRESHOLD})")
    print("    [Ctrl+C per uscire]\n")

    def audio_callback(indata, frames, time_info, status):
        nonlocal cooldown
        if status:
            print(f"[!] {status}", file=sys.stderr)

        chunk = indata[:, 0]   # mono, canale sinistro

        if cooldown > 0:
            cooldown -= 1
            return

        score = detector.update(chunk)
        bar = "█" * int(score * 20)
        print(f"\r  confidence: {score:.3f} [{bar:<20}]", end="", flush=True)

        if score >= DETECTION_THRESHOLD:
            print(f"\n\n[!] WAKEWORD rilevata! (confidence={score:.3f})\n")
            detector.clear_buffer()
            cooldown = COOLDOWN_CHUNKS

    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
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