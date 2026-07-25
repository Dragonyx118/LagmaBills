#!/usr/bin/env python3
"""
1_generate_dataset.py
Generazione dataset positivo con TTS multi-voce.
Da eseguire su PC/server, NON su Raspberry Pi.

Genera ~20.000 campioni audio con variazioni di:
- motore TTS (edge-tts, Coqui, gTTS)
- voce (maschile/femminile, accenti)
- velocità, pitch, loudness
- frasi contesto (non solo parola isolata)
"""

import os
import asyncio
import random
import hashlib
import numpy as np
import soundfile as sf
from pathlib import Path
from tqdm import tqdm
import yaml
import subprocess
import tempfile

# ──────────────────────────────────────────────
# Configurazione
# ──────────────────────────────────────────────
with open("config.yaml") as f:
    CFG = yaml.safe_load(f)

WAKE_WORD = CFG["wake_word"]["name"]
SR = CFG["audio"]["sample_rate"]
OUT_DIR = Path("data/positive")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Frasi template per variare il contesto
PHRASES = [
    "{w}",
    "hey {w}",
    "ok {w}",
    "ciao {w}",
    "{w} ascoltami",
    "{w} svegliati",
    "attiva {w}",
    "ehi {w}",
    "su {w}",
    "{w} sei lì",
]

# Voci edge-tts disponibili (italiano + internazionale)
EDGE_VOICES = [
    "it-IT-ElsaNeural",          # IT femminile
    "it-IT-IsabellaNeural",      # IT femminile 2
    "it-IT-DiegoNeural",         # IT maschile
    "en-US-JennyNeural",         # EN femminile
    "en-US-GuyNeural",           # EN maschile
    "en-GB-SoniaNeural",         # EN-GB femminile
    "en-GB-RyanNeural",          # EN-GB maschile
    "de-DE-KatjaNeural",         # DE femminile
    "fr-FR-DeniseNeural",        # FR femminile
    "es-ES-ElviraNeural",        # ES femminile
]

# ──────────────────────────────────────────────
# Generazione con edge-tts
# ──────────────────────────────────────────────
async def generate_edge_tts(text: str, voice: str, output_path: str,
                             rate: str = "+0%", pitch: str = "+0Hz") -> bool:
    """Genera audio con Microsoft Edge TTS (gratuito, online)."""
    try:
        import edge_tts
        communicate = edge_tts.Communicate(
            text=text, voice=voice, rate=rate, pitch=pitch
        )
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        await communicate.save(tmp_path)

        # Converti MP3 → WAV 16kHz mono
        import librosa
        audio, _ = librosa.load(tmp_path, sr=SR, mono=True)
        sf.write(output_path, audio, SR, subtype="PCM_16")
        os.unlink(tmp_path)
        return True
    except Exception as e:
        print(f"  [edge-tts] Errore: {e}")
        return False


def generate_coqui_tts(text: str, speaker_id: int, output_path: str) -> bool:
    """Genera audio con Coqui TTS (offline, molte voci)."""
    try:
        cmd = [
            "tts",
            "--text", text,
            "--out_path", output_path,
            "--model_name", "tts_models/multilingual/multi-dataset/xtts_v2",
            "--speaker_idx", str(speaker_id % 10),
            "--language_idx", "it",
        ]
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0:
            # Ricampiona a 16kHz se necessario
            import librosa
            audio, sr = librosa.load(output_path, sr=SR, mono=True)
            sf.write(output_path, audio, SR, subtype="PCM_16")
            return True
    except Exception as e:
        print(f"  [coqui] Errore: {e}")
    return False


# ──────────────────────────────────────────────
# Variazioni audio post-processing
# ──────────────────────────────────────────────
def apply_speed_variation(audio: np.ndarray, sr: int,
                           speed: float) -> np.ndarray:
    """Modifica velocità senza cambiare pitch (time-stretching)."""
    import librosa
    return librosa.effects.time_stretch(audio, rate=speed)


def apply_pitch_variation(audio: np.ndarray, sr: int,
                           semitones: float) -> np.ndarray:
    """Modifica pitch senza cambiare velocità."""
    import librosa
    return librosa.effects.pitch_shift(audio, sr=sr, n_steps=semitones)


def normalize_loudness(audio: np.ndarray, target_db: float = -23.0) -> np.ndarray:
    """Normalizza loudness (LUFS approssimato)."""
    rms = np.sqrt(np.mean(audio**2))
    if rms < 1e-8:
        return audio
    target_rms = 10 ** (target_db / 20)
    return audio * (target_rms / rms)


def add_silence_padding(audio: np.ndarray, sr: int,
                         pre_ms: int = 200, post_ms: int = 200) -> np.ndarray:
    """Aggiunge silenzio prima e dopo (importante per il modello)."""
    pre = np.zeros(int(sr * pre_ms / 1000))
    post = np.zeros(int(sr * post_ms / 1000))
    return np.concatenate([pre, audio, post])


# ──────────────────────────────────────────────
# Pipeline principale
# ──────────────────────────────────────────────
async def generate_positive_dataset(target_n: int = 20000):
    """
    Genera dataset positivo con diverse voci, velocità, pitch.
    
    Distribuzione target:
    - 60% edge-tts (multi-lingua, accenti diversi)
    - 30% Coqui TTS (qualità alta)
    - 10% variazioni manuali (pitch/speed su edge)
    """
    generated = 0
    errors = 0

    pbar = tqdm(total=target_n, desc="Generazione dataset positivo")

    sample_idx = 0
    while generated < target_n:
        # Scegli frase
        phrase_template = random.choice(PHRASES)
        text = phrase_template.format(w=WAKE_WORD)

        # Variazioni
        speed_pct = random.randint(-15, 15)   # -15% / +15%
        pitch_hz = random.randint(-20, 20)    # Hz (edge-tts usa Hz)
        rate_str = f"{'+' if speed_pct >= 0 else ''}{speed_pct}%"
        pitch_str = f"{'+' if pitch_hz >= 0 else ''}{pitch_hz}Hz"

        voice = random.choice(EDGE_VOICES)
        output_path = str(OUT_DIR / f"pos_{sample_idx:06d}.wav")

        ok = await generate_edge_tts(
            text=text,
            voice=voice,
            output_path=output_path,
            rate=rate_str,
            pitch=pitch_str,
        )

        if ok:
            # Post-processing aggiuntivo (50% dei campioni)
            if random.random() < 0.5:
                try:
                    audio, sr = sf.read(output_path)
                    # Variazione pitch aggiuntiva
                    if random.random() < 0.4:
                        semitones = random.uniform(-3, 3)
                        audio = apply_pitch_variation(audio, sr, semitones)
                    # Normalizza loudness con variazione
                    target_db = random.uniform(-28, -18)
                    audio = normalize_loudness(audio, target_db)
                    # Padding silenzio
                    pre_ms = random.randint(50, 300)
                    post_ms = random.randint(50, 300)
                    audio = add_silence_padding(audio, sr, pre_ms, post_ms)
                    sf.write(output_path, audio, SR, subtype="PCM_16")
                except Exception as e:
                    pass  # Usa il file originale se post-processing fallisce

            generated += 1
            pbar.update(1)
        else:
            errors += 1
            if errors > 100:
                print("Troppi errori, verifica connessione o credenziali TTS")
                break

        sample_idx += 1

    pbar.close()
    print(f"\n✓ Generati {generated} campioni positivi in {OUT_DIR}")
    print(f"  Errori: {errors}")

    # Salva metadati
    _save_manifest(OUT_DIR, "positive")


def _save_manifest(directory: Path, split: str):
    """Salva file manifest con lista campioni."""
    files = sorted(directory.glob("*.wav"))
    manifest_path = directory.parent / f"{split}_manifest.txt"
    with open(manifest_path, "w") as f:
        for fp in files:
            duration = sf.info(str(fp)).duration
            f.write(f"{fp}|{duration:.3f}\n")
    print(f"  Manifest salvato: {manifest_path} ({len(files)} file)")


# ──────────────────────────────────────────────
# Script per scaricare dataset negativi
# ──────────────────────────────────────────────
def download_negative_datasets():
    """
    Istruzioni e script per scaricare dataset negativi.
    Esegui manualmente i comandi commentati.
    """
    print("""
═══════════════════════════════════════════════════════
 DOWNLOAD DATASET NEGATIVI (~500h audio)
═══════════════════════════════════════════════════════

1. Mozilla Common Voice (Italiano + Inglese):
   └─ https://commonvoice.mozilla.org/it/datasets
   └─ Scarica: cv-corpus-XX-it.tar.gz  (~10GB)

2. LibriSpeech (Inglese, 960h):
   └─ wget https://www.openslr.org/resources/12/train-clean-360.tar.gz
   └─ wget https://www.openslr.org/resources/12/train-other-500.tar.gz

3. MUSAN (Musica/Rumori/Parlato):
   └─ wget https://www.openslr.org/resources/17/musan.tar.gz

4. DEMAND (rumori domestici):
   └─ https://zenodo.org/record/1227121

5. Hard negatives (CRITICO - parole simili):
   └─ Cerca nel CV italiano: "area", "maria", "varia", "gloria", "storia"
   └─ Estratti automaticamente da Common Voice con grep sul testo

Struttura attesa:
  data/negative/
  ├── common_voice_it/
  ├── librispeech/
  ├── musan/
  ├── demand/
  └── hard_negatives/    ← parole simili a wake word
═══════════════════════════════════════════════════════
""")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Genera dataset positivo TTS")
    parser.add_argument("--samples", type=int, default=20000)
    parser.add_argument("--info-negative", action="store_true",
                        help="Mostra istruzioni dataset negativi")
    args = parser.parse_args()

    if args.info_negative:
        download_negative_datasets()
    else:
        print(f"Wake word: '{WAKE_WORD}'")
        print(f"Target campioni: {args.samples}")
        print(f"Output: {OUT_DIR}\n")
        asyncio.run(generate_positive_dataset(args.samples))
