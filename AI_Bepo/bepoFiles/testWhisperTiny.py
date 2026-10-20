#!/usr/bin/env python3

# Primo avvio — trova l'indice corretto del ReSpeaker
#python3 whisper_listen.py --list

# Avvio normale (auto-detect ReSpeaker)
#python3 whisper_listen.py

# Se il device non viene trovato automaticamente (es. indice 3)
#python3 whisper_listen.py --device 3

# Se la VAD non reagisce bene (ambiente rumoroso o mic lontano)
# abbassa SILENCE_THRESH a 300 nel codice, oppure usa le finestre fisse
#python3 whisper_listen.py --no-vad

import argparse, time, threading, queue
import numpy as np
import pyaudio
import whisper

SAMPLE_RATE    = 16000
CHANNELS       = 1
FORMAT         = pyaudio.paInt16
CHUNK          = 512
SILENCE_THRESH = 500     # abbassa a 300 se il mic è lontano, alza a 800 se c'è rumore
SILENCE_SEC    = 1.2
MIN_SPEECH_SEC = 0.4
MAX_SPEECH_SEC = 15.0

GREEN = "\033[92m"; YELLOW = "\033[93m"; CYAN = "\033[96m"
GRAY  = "\033[90m"; RESET  = "\033[0m"

def find_respeaker(pa):
    for i in range(pa.get_device_count()):
        info = pa.get_device_info_by_index(i)
        name = info.get("name", "").lower()
        if info.get("maxInputChannels", 0) > 0:
            if "seeed" in name or "voicecard" in name or "wm8960" in name:
                return i, info["name"]
    return None, "default"

def rms(data):
    return float(np.sqrt(np.mean(data.astype(np.float64) ** 2)))

def record_vad(stream, q, stop):
    buffer, silence_cnt, speaking = [], 0, False
    silence_frames = int(SILENCE_SEC * SAMPLE_RATE / CHUNK)
    while not stop.is_set():
        try:
            raw = stream.read(CHUNK, exception_on_overflow=False)
        except OSError:
            continue
        chunk = np.frombuffer(raw, dtype=np.int16)
        if rms(chunk) > SILENCE_THRESH:
            speaking, silence_cnt = True, 0
            buffer.append(chunk)
        elif speaking:
            silence_cnt += 1
            buffer.append(chunk)
            total_sec = len(buffer) * CHUNK / SAMPLE_RATE
            if silence_cnt >= silence_frames or total_sec >= MAX_SPEECH_SEC:
                speech_sec = (len(buffer) - silence_cnt) * CHUNK / SAMPLE_RATE
                if speech_sec >= MIN_SPEECH_SEC:
                    q.put(np.concatenate(buffer))
                buffer, silence_cnt, speaking = [], 0, False

def record_fixed(stream, q, stop, window_sec=5.0):
    n = int(window_sec * SAMPLE_RATE / CHUNK)
    while not stop.is_set():
        win = []
        for _ in range(n):
            if stop.is_set(): break
            try:
                raw = stream.read(CHUNK, exception_on_overflow=False)
                win.append(np.frombuffer(raw, dtype=np.int16))
            except OSError:
                continue
        if win:
            q.put(np.concatenate(win))

JUNK = {"", ".", "..", "...", "grazie", "grazie.", "sottotitoli",
        "sottotitoli a cura di", "grazie per la visione"}

def transcribe_worker(model, q, stop):
    while not stop.is_set():
        try:
            audio = q.get(timeout=0.5)
        except queue.Empty:
            continue
        audio_f32 = audio.astype(np.float32) / 32768.0
        print(f"{GRAY}  [trascrizione...]{RESET}", end="\r", flush=True)
        result = model.transcribe(
            audio_f32, language="it", fp16=False,
            condition_on_previous_text=False)
        text = result["text"].strip()
        if text.lower() in JUNK or len(text) < 2:
            print(" " * 40, end="\r")
            continue
        print(f"{GREEN}[{time.strftime('%H:%M:%S')}]{RESET} {text}   ")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model",  default="tiny")
    parser.add_argument("--no-vad", action="store_true")
    parser.add_argument("--list",   action="store_true")
    parser.add_argument("--device", type=int, default=None)
    args = parser.parse_args()

    pa = pyaudio.PyAudio()
    if args.list:
        print("\nDispositivi di input:")
        for i in range(pa.get_device_count()):
            info = pa.get_device_info_by_index(i)
            if info.get("maxInputChannels", 0) > 0:
                print(f"  [{i}] {info['name']}  ({int(info['defaultSampleRate'])}Hz)")
        pa.terminate(); return

    print(f"{CYAN}Caricamento modello '{args.model}'...{RESET}")
    model = whisper.load_model(args.model)
    print(f"{GREEN}Pronto.{RESET}\n")

    if args.device is not None:
        dev_idx  = args.device
        dev_name = pa.get_device_info_by_index(dev_idx)["name"]
    else:
        dev_idx, dev_name = find_respeaker(pa)
    if dev_idx is None:
        dev_idx = pa.get_default_input_device_info()["index"]
        dev_name = pa.get_device_info_by_index(dev_idx)["name"]

    print(f"Microfono : {CYAN}[{dev_idx}] {dev_name}{RESET}")
    print(f"Modalità  : {'finestre fisse 5s' if args.no_vad else 'VAD automatico'}")
    print(f"{YELLOW}In ascolto... (Ctrl+C per uscire){RESET}\n")

    stream = pa.open(format=FORMAT, channels=CHANNELS, rate=SAMPLE_RATE,
                     input=True, input_device_index=dev_idx,
                     frames_per_buffer=CHUNK)

    q, stop = queue.Queue(), threading.Event()
    rec_fn = record_fixed if args.no_vad else record_vad
    threading.Thread(target=rec_fn,          args=(stream, q, stop), daemon=True).start()
    threading.Thread(target=transcribe_worker, args=(model,  q, stop), daemon=True).start()

    try:
        while True: time.sleep(0.1)
    except KeyboardInterrupt:
        print(f"\n{GRAY}Chiudo...{RESET}")
        stop.set(); time.sleep(1)
        stream.stop_stream(); stream.close(); pa.terminate()

if __name__ == "__main__":
    main()