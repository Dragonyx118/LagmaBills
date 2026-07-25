#!/usr/bin/env python3
import numpy as np
import sounddevice as sd
import openwakeword
from openwakeword.model import Model
import time
import sys
import threading
import queue

INPUT_DEVICE        = 2
DETECTION_THRESHOLD = 0.7
MODEL_PATH          = "hey_no_va.onnx"
COOLDOWN_SEC        = 3.0

audio_queue = queue.Queue(maxsize=10)

def main():
    oww_model = Model(wakeword_models=[MODEL_PATH], inference_framework="onnx")

    dev_info = sd.query_devices(INPUT_DEVICE)
    print(f"[*] Device: [{INPUT_DEVICE}] {dev_info['name']}")
    print(f"[*] Soglia: {DETECTION_THRESHOLD}")
    print("    [Ctrl+C per uscire]\n")

    last_detection = 0

    def audio_callback(indata, frames, time_info, status):
        # callback leggerissimo: solo copia in queue
        chunk = (indata[:, 0] * 32767).astype(np.int16).copy()
        try:
            audio_queue.put_nowait(chunk)
        except queue.Full:
            pass  # droppa se il thread di inferenza è in ritardo

    def inference_thread():
        nonlocal last_detection
        while True:
            chunk = audio_queue.get()
            if chunk is None:
                break

            if time.time() - last_detection < COOLDOWN_SEC:
                continue

            prediction = oww_model.predict(chunk)

            for name, score in prediction.items():
                bar = "█" * int(score * 20)
                print(f"\r  {name}: {score:.3f} [{bar:<20}]", end="", flush=True)

                if score >= DETECTION_THRESHOLD:
                    print(f"\n\n  *** WAKEWORD rilevata! (score={score:.3f}) ***\n")
                    last_detection = time.time()
                    oww_model.reset()

    t = threading.Thread(target=inference_thread, daemon=True)
    t.start()

    try:
        with sd.InputStream(
            device=INPUT_DEVICE,
            samplerate=16000,
            channels=1,
            blocksize=1280,
            dtype="float32",
            callback=audio_callback,
        ):
            while True:
                time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\n[*] Uscita.")
        audio_queue.put(None)

if __name__ == "__main__":
    main()