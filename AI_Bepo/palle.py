#!/usr/bin/env python3
"""
Prova le voci Piper TTS italiano (Aurora, Leonardo, Giorgio)
Usa il comando piper via subprocess - più compatibile con tutte le versioni.
"""

import os
import sys
import subprocess
import glob
import tempfile
import platform

# ── Installazione dipendenze ──────────────────────────────────────────────────

def installa(pacchetto, import_nome=None):
    import_nome = import_nome or pacchetto
    try:
        __import__(import_nome)
    except ImportError:
        print(f"📦 Installo {pacchetto}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pacchetto],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"   ✅ {pacchetto} installato.")

installa("piper-tts", "piper")

# ── Trova il comando piper ────────────────────────────────────────────────────

def trova_piper():
    """Cerca l'eseguibile piper installato da pip."""
    # Percorsi comuni dove pip installa gli script
    candidati = [
        os.path.join(os.path.dirname(sys.executable), "piper"),
        os.path.join(os.path.dirname(sys.executable), "piper.exe"),
        os.path.join(sys.prefix, "bin", "piper"),
        os.path.join(sys.prefix, "Scripts", "piper.exe"),
        os.path.expanduser("~/.local/bin/piper"),
    ]
    for c in candidati:
        if os.path.isfile(c):
            return c
    # Prova anche con which/where
    try:
        risultato = subprocess.check_output(
            ["where" if platform.system() == "Windows" else "which", "piper"],
            stderr=subprocess.DEVNULL
        ).decode().strip().splitlines()[0]
        if risultato:
            return risultato
    except Exception:
        pass
    return None

# ── Riproduzione audio ────────────────────────────────────────────────────────

def riproduci_wav(percorso_wav):
    """Riproduce un file WAV con il player disponibile sul sistema."""
    sistema = platform.system()
    if sistema == "Windows":
        os.startfile(percorso_wav)
        input("   [Premi Invio quando hai finito di ascoltare]")
    elif sistema == "Darwin":
        subprocess.call(["afplay", percorso_wav])
    else:
        for cmd in ["aplay", "paplay", "mpv", "ffplay", "cvlc"]:
            if subprocess.call(["which", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0:
                subprocess.call([cmd, percorso_wav],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
        print(f"   ⚠️  Nessun player trovato. File salvato in: {percorso_wav}")

def sintetizza_e_riproduci(piper_cmd, onnx_path, json_path, testo):
    """Usa il comando piper per sintetizzare il testo e lo riproduce."""
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()

    # Piper cerca sempre nomefile.onnx.json — crea un link/copia se necessario
    json_atteso = onnx_path + ".json"
    json_creato = False
    if not os.path.exists(json_atteso):
        import shutil
        shutil.copy2(json_path, json_atteso)
        json_creato = True

    try:
        cmd = [
            piper_cmd,
            "--model", onnx_path,
            "--output_file", tmp.name,
        ]
        proc = subprocess.run(
            cmd,
            input=testo.encode("utf-8"),
            capture_output=True,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode().strip())

        dim = os.path.getsize(tmp.name)
        if dim < 100:
            raise RuntimeError("File WAV troppo piccolo, sintesi fallita")

        print("   🔊 Riproduzione in corso...")
        riproduci_wav(tmp.name)

    finally:
        if json_creato and os.path.exists(json_atteso):
            try:
                os.unlink(json_atteso)
            except Exception:
                pass
        try:
            os.unlink(tmp.name)
        except Exception:
            pass

# ── Ricerca modelli scaricati ─────────────────────────────────────────────────

CARTELLA_VOCI = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piper_voci_italiano")

def trova_modelli():
    pattern = os.path.join(CARTELLA_VOCI, "**", "*.onnx")
    files = glob.glob(pattern, recursive=True)
    validi = {}
    for f in files:
        json_1 = f + ".json"
        json_2 = os.path.splitext(f)[0] + ".json"
        json_path = json_1 if os.path.exists(json_1) else (json_2 if os.path.exists(json_2) else None)
        if json_path:
            nome_cartella = os.path.basename(os.path.dirname(f))
            nome_file     = os.path.splitext(os.path.basename(f))[0]
            label         = f"{nome_cartella} — {nome_file}"
            validi[label] = (f, json_path)
    return validi

# ── Interfaccia testuale ──────────────────────────────────────────────────────

def scegli_voce(modelli):
    nomi = list(modelli.keys())
    print("\n🎙️  Voci disponibili:")
    for i, nome in enumerate(nomi, 1):
        print(f"   {i}) {nome}")
    print()
    while True:
        scelta = input(f"Scegli voce [1-{len(nomi)}]: ").strip()
        if scelta.isdigit() and 1 <= int(scelta) <= len(nomi):
            label = nomi[int(scelta) - 1]
            onnx, json_p = modelli[label]
            return label, onnx, json_p
        print("   ⚠️  Inserisci un numero valido.")

def main():
    print("\n🇮🇹  Test voci Piper TTS - Italiano")
    print("=" * 42)

    # Trova piper
    piper_cmd = trova_piper()
    if not piper_cmd:
        print("\n❌ Comando 'piper' non trovato.")
        print("   Prova: pip install piper-tts")
        sys.exit(1)
    print(f"✅ Piper trovato: {piper_cmd}")

    # Trova modelli
    if not os.path.isdir(CARTELLA_VOCI):
        print(f"\n❌ Cartella non trovata: {CARTELLA_VOCI}")
        sys.exit(1)

    modelli = trova_modelli()
    if not modelli:
        print(f"\n❌ Nessun modello .onnx trovato in: {CARTELLA_VOCI}")
        sys.exit(1)

    while True:
        nome, onnx_path, json_path = scegli_voce(modelli)

        print(f"\n📝 Voce attiva: {nome}")
        print("   (digita 'cambia' per cambiare voce, 'esci' per uscire)\n")

        while True:
            testo = input("Testo: ").strip()
            if not testo:
                continue
            if testo.lower() == "esci":
                print("\n👋 Arrivederci!")
                sys.exit(0)
            if testo.lower() == "cambia":
                break
            try:
                sintetizza_e_riproduci(piper_cmd, onnx_path, json_path, testo)
            except Exception as e:
                print(f"   ❌ Errore: {e}")

if __name__ == "__main__":
    main()
