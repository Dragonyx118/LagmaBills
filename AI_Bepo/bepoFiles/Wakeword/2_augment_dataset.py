#!/usr/bin/env python3
"""
2_augment_dataset.py
Data augmentation audio per dataset positivo.
Obiettivo: aumentare robustezza a rumore reale.

Applica:
- Aggiunta rumore (SNR variabile)
- Simulazione distanza microfono
- Riverbero leggero con pyroomacoustics
- Time stretching lieve
- Risposta impulsiva microfono (IR convolution)
"""

import os
import numpy as np
import soundfile as sf
from pathlib import Path
from tqdm import tqdm
import random
import yaml
import warnings
warnings.filterwarnings("ignore")

with open("config.yaml") as f:
    CFG = yaml.safe_load(f)

SR = CFG["audio"]["sample_rate"]
POS_DIR = Path("data/positive")
NEG_DIR = Path("data/negative")
AUG_DIR = Path("data/augmented")
AUG_DIR.mkdir(parents=True, exist_ok=True)


# ──────────────────────────────────────────────
# Carica rumore di background
# ──────────────────────────────────────────────
_noise_cache: list[np.ndarray] = []

def load_noise_bank(max_files: int = 200) -> list[np.ndarray]:
    """Carica campioni di rumore da dataset negativi."""
    global _noise_cache
    if _noise_cache:
        return _noise_cache

    noise_files = list(Path("data/negative/musan").rglob("*.wav"))[:max_files]
    noise_files += list(Path("data/negative/demand").rglob("*.wav"))[:max_files]

    print(f"Caricamento {len(noise_files)} file rumore...")
    for fp in tqdm(noise_files[:max_files], desc="Noise bank"):
        try:
            audio, sr = sf.read(str(fp))
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
            if sr != SR:
                import librosa
                audio = librosa.resample(audio, orig_sr=sr, target_sr=SR)
            if len(audio) > SR * 2:  # almeno 2 secondi
                _noise_cache.append(audio.astype(np.float32))
        except Exception:
            pass

    if not _noise_cache:
        print("⚠ Nessun file rumore trovato, uso rumore bianco sintetico")
        _noise_cache = [np.random.randn(SR * 5).astype(np.float32)]

    print(f"Noise bank: {len(_noise_cache)} clip")
    return _noise_cache


# ──────────────────────────────────────────────
# Funzioni di augmentation
# ──────────────────────────────────────────────
def add_noise(audio: np.ndarray, snr_db: float,
              noise_bank: list[np.ndarray]) -> np.ndarray:
    """
    Aggiunge rumore reale a SNR specificato.
    SNR basso = molto rumore (es. 5 dB)
    SNR alto = poco rumore (es. 30 dB)
    """
    # Scegli clip rumore casuale e allineala alla lunghezza audio
    noise = random.choice(noise_bank)
    if len(noise) < len(audio):
        repeats = (len(audio) // len(noise)) + 1
        noise = np.tile(noise, repeats)
    start = random.randint(0, max(0, len(noise) - len(audio) - 1))
    noise = noise[start:start + len(audio)]

    # Calcola potenza segnale e rumore
    signal_power = np.mean(audio**2)
    noise_power = np.mean(noise**2)

    if noise_power < 1e-10 or signal_power < 1e-10:
        return audio

    # Scala rumore per ottenere SNR target
    target_noise_power = signal_power / (10 ** (snr_db / 10))
    scale = np.sqrt(target_noise_power / noise_power)
    noisy = audio + scale * noise

    # Clip per evitare distorsione
    return np.clip(noisy, -1.0, 1.0)


def simulate_distance(audio: np.ndarray, distance_db: float) -> np.ndarray:
    """
    Simula attenuazione per distanza microfono.
    distance_db: 0 = vicino, -18 = ~3-5 metri
    """
    scale = 10 ** (distance_db / 20)
    return audio * scale


def apply_reverb(audio: np.ndarray, sr: int,
                 room_scale: float = 0.3,
                 wet_level: float = 0.15) -> np.ndarray:
    """
    Aggiunge riverbero realistico con pyroomacoustics.
    Usa stanze piccole/medie per simulare ambienti domestici.
    """
    try:
        import pyroomacoustics as pra

        # Dimensioni stanza casuali (piccola/media)
        room_x = random.uniform(3.0, 6.0) * (1 + room_scale)
        room_y = random.uniform(3.0, 5.0) * (1 + room_scale)
        room_z = random.uniform(2.4, 3.0)

        rt60 = random.uniform(0.1, 0.4) * (1 + room_scale)  # tempo riverbero

        e_absorption, max_order = pra.inverse_sabine(rt60, [room_x, room_y, room_z])
        materials = pra.Material(e_absorption)

        room = pra.ShoeBox(
            [room_x, room_y, room_z],
            fs=sr,
            materials=materials,
            max_order=min(max_order, 17),
        )

        # Posizione sorgente e microfono casuali
        src_pos = [
            random.uniform(0.5, room_x - 0.5),
            random.uniform(0.5, room_y - 0.5),
            random.uniform(0.8, 1.8),
        ]
        mic_pos = [
            random.uniform(0.5, room_x - 0.5),
            random.uniform(0.5, room_y - 0.5),
            random.uniform(0.8, 1.5),
        ]

        room.add_source(src_pos, signal=audio)
        mic_array = np.array(mic_pos).reshape(3, 1)
        room.add_microphone(mic_array)
        room.simulate()

        reverbed = room.mic_array.signals[0]
        reverbed = reverbed[:len(audio)]  # tronca alla lunghezza originale

        # Mix dry/wet
        out = (1 - wet_level) * audio + wet_level * reverbed
        return np.clip(out, -1.0, 1.0)

    except ImportError:
        # Fallback: riverbero semplice con convoluzione
        return _simple_reverb(audio, wet_level)
    except Exception:
        return audio


def _simple_reverb(audio: np.ndarray, wet: float = 0.15) -> np.ndarray:
    """Riverbero semplice con delay e decay (fallback)."""
    delays_ms = [30, 60, 120]
    decays = [0.4, 0.2, 0.1]
    out = audio.copy()
    for delay_ms, decay in zip(delays_ms, decays):
        delay_samples = int(SR * delay_ms / 1000)
        delayed = np.zeros_like(audio)
        delayed[delay_samples:] = audio[:-delay_samples] * decay
        out = out + wet * delayed
    return np.clip(out, -1.0, 1.0)


def apply_eq_variation(audio: np.ndarray, sr: int) -> np.ndarray:
    """
    Simula diverse risposte in frequenza (microfoni economici).
    Applica filtri casuali leggeri.
    """
    from scipy import signal as sp_signal

    # Scegli variazione casuale
    variation = random.choice(["flat", "bass_boost", "treble_cut", "telephone"])

    if variation == "bass_boost":
        b, a = sp_signal.butter(2, 300 / (sr / 2), btype="high")
        audio = sp_signal.filtfilt(b, a, audio)
    elif variation == "treble_cut":
        b, a = sp_signal.butter(2, 6000 / (sr / 2), btype="low")
        audio = sp_signal.filtfilt(b, a, audio)
    elif variation == "telephone":
        # Bandpass 300-3400 Hz (risposta telefonica)
        b, a = sp_signal.butter(4, [300 / (sr / 2), 3400 / (sr / 2)], btype="band")
        audio = sp_signal.filtfilt(b, a, audio)

    return audio.astype(np.float32)


# ──────────────────────────────────────────────
# Pipeline augmentation
# ──────────────────────────────────────────────
def augment_sample(audio: np.ndarray, sr: int,
                   noise_bank: list[np.ndarray]) -> np.ndarray:
    """
    Applica augmentation casuale a un campione.
    Seleziona combinazioni realistiche (non tutto insieme).
    """
    # Normalizza input
    audio = audio.astype(np.float32)
    max_val = np.max(np.abs(audio))
    if max_val > 0:
        audio = audio / max_val * 0.9

    # 1. Riverbero (60% probabilità, leggero)
    if random.random() < 0.6:
        room_scale = random.uniform(0.1, 0.4)
        wet = random.uniform(0.05, 0.25)
        audio = apply_reverb(audio, sr, room_scale, wet)

    # 2. Simulazione distanza (40% probabilità)
    if random.random() < 0.4:
        dist_db = random.uniform(-15, 0)
        audio = simulate_distance(audio, dist_db)

    # 3. Variazione EQ (50% probabilità)
    if random.random() < 0.5:
        audio = apply_eq_variation(audio, sr)

    # 4. Rumore (80% probabilità, SNR variabile)
    if random.random() < 0.8:
        snr = random.uniform(
            CFG["augmentation"]["noise"]["snr_range_db"][0],
            CFG["augmentation"]["noise"]["snr_range_db"][1],
        )
        audio = add_noise(audio, snr, noise_bank)

    return audio


def augment_dataset(multiplier: int = 3):
    """
    Aumenta dataset positivo di N volte con augmentation.
    multiplier=3 → da 20.000 a 80.000 campioni totali (originali + 3x augmented)
    """
    input_files = sorted(POS_DIR.glob("*.wav"))
    if not input_files:
        print(f"❌ Nessun file in {POS_DIR}. Esegui prima 1_generate_dataset.py")
        return

    noise_bank = load_noise_bank()
    print(f"\nAugmentation: {len(input_files)} file × {multiplier} = "
          f"{len(input_files) * multiplier} nuovi campioni")

    idx = 0
    for wav_file in tqdm(input_files, desc="Augmenting"):
        try:
            audio, sr = sf.read(str(wav_file))
            if len(audio.shape) > 1:
                audio = audio.mean(axis=1)
            audio = audio.astype(np.float32)

            for aug_i in range(multiplier):
                aug_audio = augment_sample(audio.copy(), sr, noise_bank)
                out_path = AUG_DIR / f"aug_{idx:07d}.wav"
                sf.write(str(out_path), aug_audio, SR, subtype="PCM_16")
                idx += 1

        except Exception as e:
            print(f"  Errore {wav_file}: {e}")

    print(f"\n✓ Generati {idx} campioni augmentati in {AUG_DIR}")
    print(f"  Dataset totale positivo: {len(input_files) + idx} campioni")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--multiplier", type=int, default=3,
                        help="Moltiplicatore augmentation (default: 3)")
    args = parser.parse_args()
    augment_dataset(args.multiplier)
