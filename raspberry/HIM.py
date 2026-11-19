#!/usr/bin/env python3
"""
HIM.py — LagmaBills Launcher (versione tmux)

Ogni modulo gira nel proprio pannello tmux, con output isolato,
scrollabile e sempre leggibile — niente più stampe che si accavallano
sullo stesso terminale.

Sessione tmux: "lagmabills"
  Ogni modalità crea una FINESTRA tmux dedicata (es. "generale"),
  con un PANNELLO per ogni processo lanciato in quella modalità.

Comandi utili una volta dentro tmux:
  Ctrl+B poi frecce      → passa da un pannello all'altro
  Ctrl+B poi w           → lista finestre (modalità attive)
  Ctrl+B poi d           → "detach" (esci senza killare i processi)
  tmux attach -t lagmabills   → rientra nella sessione da fuori

Modalità non interattive (per activationListener.py):
  python3 HIM.py --auto-start   → avvia faccia+media+pistats+controller e esce
  python3 HIM.py --stop         → termina tutta la sessione tmux e esce
"""

import subprocess
import sys
import os
import shutil
import json

try:
    import paho.mqtt.client as mqtt
    MQTT_OK = True
except ImportError:
    MQTT_OK = False
    print("[WARN] paho-mqtt non trovato — switch modalità da controller disabilitato.")

MQTT_BROKER = "100.100.61.49"
MQTT_PORT   = 1883
TOPIC_MODALITA_CMD = "robot/modalita/cmd"   # {"cmd":"switch","modalita":"generale"}
TOPIC_FACCIA_CMD    = "robot/faccia/cmd"    # "pausa" | "riprendi" — da mqttMedia.py

SESSION = "lagmabills"

# Traccia i pannelli attivi per poterli terminare puliti
pannelli_attivi = []   # lista di (finestra, pannello_id)


def _tmux(*args):
    """Esegue un comando tmux, ritorna stdout."""
    result = subprocess.run(["tmux", *args], capture_output=True, text=True)
    return result.stdout.strip()


def _tmux_ok():
    return shutil.which("tmux") is not None


def _sessione_esiste():
    result = subprocess.run(["tmux", "has-session", "-t", SESSION],
                             capture_output=True)
    return result.returncode == 0


def _assicura_sessione():
    """Crea la sessione tmux se non esiste, senza attaccarsi subito."""
    if not _sessione_esiste():
        subprocess.run(["tmux", "new-session", "-d", "-s", SESSION,
                         "-n", "menu"])
        print(f"  ✔ Sessione tmux '{SESSION}' creata")


def _crea_finestra(nome: str):
    """Crea una nuova finestra tmux per una modalità (es. 'generale')."""
    esistenti = _tmux("list-windows", "-t", SESSION, "-F", "#{window_name}")
    if nome in esistenti.split("\n"):
        subprocess.run(["tmux", "kill-window", "-t", f"{SESSION}:{nome}"])
    subprocess.run(["tmux", "new-window", "-t", SESSION, "-n", nome])
    return nome


def avvia_in_pannello(finestra: str, cmd: str, titolo: str, primo=False):
    """
    Lancia un comando in un pannello della finestra data.
    Se primo=True usa il pannello già esistente della finestra,
    altrimenti ne apre uno nuovo splittando.
    """
    target = f"{SESSION}:{finestra}"

    if not primo:
        subprocess.run(["tmux", "split-window", "-t", target])
        subprocess.run(["tmux", "select-layout", "-t", target, "tiled"])

    subprocess.run(["tmux", "select-pane", "-t", target, "-T", titolo])
    subprocess.run(["tmux", "send-keys", "-t", target, cmd, "Enter"])

    pannelli_attivi.append((finestra, titolo))
    print(f"  ✔ [{finestra}] {titolo} avviato")


def termina_tutti():
    """Chiude tutte le finestre tmux di modalità (tranne 'menu')."""
    if not _sessione_esiste():
        print("\nNessuna sessione attiva da terminare.")
        return
    finestre = _tmux("list-windows", "-t", SESSION, "-F", "#{window_name}").split("\n")
    for f in finestre:
        if f and f not in ("menu", "faccia", "controller", "media", "pistats"):
            subprocess.run(["tmux", "kill-window", "-t", f"{SESSION}:{f}"])
    pannelli_attivi.clear()
    print("Tutte le finestre dei moduli sono state chiuse.")


def termina_finestra(nome: str):
    """Chiude una specifica finestra tmux (una modalità sola)."""
    if not _sessione_esiste():
        return
    esistenti = _tmux("list-windows", "-t", SESSION, "-F", "#{window_name}").split("\n")
    if nome in esistenti:
        subprocess.run(["tmux", "kill-window", "-t", f"{SESSION}:{nome}"])
        print(f"  ✔ Finestra '{nome}' terminata")


def avvia_faccia():
    """
    Avvia l'animazione della faccia (RoboEyes) su X server dedicato
    (:0 vt1, schermo HDMI fisico). Gira in una finestra tmux PROPRIA,
    separata dalle modalità — deve restare attiva SEMPRE, qualunque
    modalità sia selezionata. termina_finestra()/switch_modalita()
    non la toccano mai perché non è nel dizionario MODALITA.
    """
    if not _sessione_esiste():
        return
    esistenti = _tmux("list-windows", "-t", SESSION, "-F", "#{window_name}").split("\n")
    if "faccia" in esistenti:
        print("  ℹ Faccia già attiva, non la riavvio.")
        return
    subprocess.run(["tmux", "new-window", "-t", SESSION, "-n", "faccia"])
    subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}:faccia",
                     "startx /usr/bin/python3 /home/ladrodirame/FUSION/bepo-animation/main.py -- :0 vt1",
                     "Enter"])
    print("  ✔ Faccia (RoboEyes) avviata su :0 vt1")


def avvia_controller():
    """
    Avvia testI2C.py (bridge I2C) + xboxPiDirect.py (controller Bluetooth
    diretto) in una finestra tmux PERSISTENTE, indipendente dalla
    modalità selezionata.
    """
    if not _sessione_esiste():
        return
    esistenti = _tmux("list-windows", "-t", SESSION, "-F", "#{window_name}").split("\n")
    if "controller" in esistenti:
        print("  ℹ Controller già attivo, non lo riavvio.")
        return
    subprocess.run(["tmux", "new-window", "-t", SESSION, "-n", "controller"])
    target = f"{SESSION}:controller"
    subprocess.run(["tmux", "send-keys", "-t", target,
                     "python3 ~/FUSION/testI2C.py", "Enter"])
    subprocess.run(["tmux", "split-window", "-t", target])
    subprocess.run(["tmux", "send-keys", "-t", target,
                     "python3 ~/FUSION/xboxPiDirect.py", "Enter"])
    subprocess.run(["tmux", "select-layout", "-t", target, "even-vertical"])
    print("  ✔ Controller pronto (I2C bridge + Xbox) — puoi già guidare e cambiare modalità")


def avvia_media():
    if not _sessione_esiste():
        return
    esistenti = _tmux("list-windows", "-t", SESSION, "-F", "#{window_name}").split("\n")
    if "media" in esistenti:
        print("  ℹ Media già attivo, non lo riavvio.")
        return
    subprocess.run(["tmux", "new-window", "-t", SESSION, "-n", "media"])
    subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}:media",
                     "DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/1000 python3 ~/FUSION/mqttMedia.py", "Enter"])
    print("  ✔ Media (audio/video) pronto")


def avvia_pistats():
    """
    Avvia piStatsMqtt.py (publish periodico CPU/RAM/temp su MQTT) in una
    finestra tmux PERSISTENTE, indipendente dalla modalità selezionata.
    """
    if not _sessione_esiste():
        return
    esistenti = _tmux("list-windows", "-t", SESSION, "-F", "#{window_name}").split("\n")
    if "pistats" in esistenti:
        print("  ℹ Pi stats già attivo, non lo riavvio.")
        return
    subprocess.run(["tmux", "new-window", "-t", SESSION, "-n", "pistats"])
    subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}:pistats",
                     "python3 ~/FUSION/piStatsMqtt.py", "Enter"])
    print("  ✔ Pi stats (CPU/RAM/temp) pronto")


# ── AVVIO/ARRESTO AUTOMATICO (per activationListener.py) ──────────

def avvia_tutto_automatico():
    """Sequenza di avvio servizi perenni attivi sempre."""
    print("\n[AUTO-START] Avvio automatico LagmaBills...")
    _assicura_sessione()
    avvia_faccia()
    avvia_media()
    avvia_pistats()
    avvia_controller()
    subprocess.run(["tmux", "send-keys", "-t", f"{SESSION}:menu",
                     "python3 ~/FUSION/HIM.py", "Enter"])
    print("[AUTO-START] Completato — sessione tmux attiva in background.")


def ferma_tutto():
    """
    Arresto completo, richiamato da activationListener.py quando
    riceve il comando UDP "STOP" dall'app. Chiude l'intera sessione
    tmux (tutti i moduli, incluse faccia/media/pistats/controller).
    """
    print("\n[AUTO-STOP] Arresto completo LagmaBills...")
    if _sessione_esiste():
        subprocess.run(["tmux", "kill-session", "-t", SESSION])
        print(f"  ✔ Sessione tmux '{SESSION}' terminata (tutti i processi chiusi)")
    else:
        print("  ℹ Nessuna sessione attiva.")


# ── MODALITÀ ─────────────────────────────────────────────────────

def avvia_generale():
    print("\n[GENERALE] Avvio moduli in pannelli separati...")
    avvia_controller()
    fin = _crea_finestra("generale")
    avvia_in_pannello(fin, "python3 ~/FUSION/GPSmqtt.py",     "GPS", primo=True)
    avvia_in_pannello(fin, "python3 ~/FUSION/streamCamera.py","Camera")
    subprocess.run(["tmux", "select-layout", "-t", f"{SESSION}:generale", "tiled"])
    print(f"  → Vai alla finestra con: tmux select-window -t {SESSION}:generale")


def avvia_jarvis():
    print("\n[JARVIS] Avvio moduli in pannelli separati...")
    fin = _crea_finestra("jarvis")
    avvia_in_pannello(fin, "python3 ~/AIsburra/TUFF/wakes.py", "wakeword", primo=True)
    avvia_in_pannello(fin, "python3 ~/AIsburra/TUFF/bluey.py", "bluey")
    subprocess.run(["tmux", "select-layout", "-t", f"{SESSION}:jarvis", "tiled"])


def avvia_drone():
    print("\n[DRONE] Avvio modulo...")
    fin = _crea_finestra("drone")
    avvia_in_pannello(fin, "python3 ~/FUSION/droneMqttNew.py", "drone-bridge", primo=True)


def avvia_esplorazione():
    print("\n[ESPLORAZIONE AUTONOMA] Avvio modulo...")
    fin = _crea_finestra("esplorazione")
    avvia_in_pannello(fin, "python3 ~/FUSION/esplorazione.py", "esplorazione", primo=True)


def avvia_insegui_linea():
    print("\n[INSEGUI LINEA] Avvio modulo...")
    fin = _crea_finestra("linea")
    avvia_in_pannello(fin, "python3 ~/FUSION/mqttLinea.py", "insegui-linea", primo=True)


# ── MENU ─────────────────────────────────────────────────────────

MODALITA = {
    "generale":     (avvia_generale,       "generale"),
    "jarvis":       (avvia_jarvis,         "jarvis"),
    "drone":        (avvia_drone,          "drone"),
    "esplorazione": (avvia_esplorazione,   "esplorazione"),
    "linea":        (avvia_insegui_linea,  "linea"),
}

modalita_corrente = None


def switch_modalita(nome: str):
    """Ferma la modalità attiva (se c'è) e avvia quella richiesta."""
    global modalita_corrente
    if nome not in MODALITA:
        print(f"[SWITCH] Modalità sconosciuta: '{nome}'")
        return

    if modalita_corrente and modalita_corrente != nome:
        _, finestra_vecchia = MODALITA[modalita_corrente]
        termina_finestra(finestra_vecchia)

    funzione, _ = MODALITA[nome]
    funzione()
    modalita_corrente = nome
    print(f"[SWITCH] Modalità attiva ora: {nome}")


# ── MQTT — ricezione comando switch dal controller (Y+X) ──────────

def _on_mqtt_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        client.subscribe(TOPIC_MODALITA_CMD)
        client.subscribe(TOPIC_FACCIA_CMD)
        print(f"[MQTT] In ascolto su {TOPIC_MODALITA_CMD} e {TOPIC_FACCIA_CMD}")


def _on_mqtt_message(client, userdata, msg):
    if msg.topic == TOPIC_FACCIA_CMD:
        comando = msg.payload.decode().strip().lower()
        if comando == "pausa":
            print("\n[FACCIA] Pausa richiesta (video in arrivo)")
            termina_finestra("faccia")
        elif comando == "riprendi":
            print("\n[FACCIA] Ripresa richiesta (video terminato)")
            avvia_faccia()
        return

    try:
        payload = json.loads(msg.payload.decode())
    except Exception:
        return
    if payload.get("cmd") == "switch":
        nome = payload.get("modalita")
        if nome:
            print(f"\n[MQTT] Richiesta switch a '{nome}' dal controller")
            switch_modalita(nome)


def avvia_mqtt_listener():
    if not MQTT_OK:
        return
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=f"him_switch_listener_{os.getpid()}"
    )
    client.on_connect = _on_mqtt_connect
    client.on_message = _on_mqtt_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
    except Exception as e:
        print(f"[MQTT] Impossibile connettersi: {e}")


def mostra_menu():
    print("\n" + "═" * 42)
    print("   🤖  RASPBERRY LAUNCHER (tmux)  🤖")
    print("═" * 42)
    print("  1. Generale")
    print("  2. Jarvis")
    print("  3. Drone")
    print("  4. Esplorazione autonoma")
    print("  5. Insegui Linea")
    print("─" * 42)
    print("  c. Controller pronto (senza scegliere modalità)")
    print("  v. Vai alla sessione tmux (attach)")
    print("  s. Stato finestre attive")
    print("  k. Termina tutti i moduli")
    print("  q. Esci (i processi restano attivi in tmux)")
    print("═" * 42)


def mostra_stato():
    if not _sessione_esiste():
        print("\nNessuna sessione tmux attiva.")
        return
    finestre = _tmux("list-windows", "-t", SESSION,
                      "-F", "#{window_name}: #{window_panes} pannelli").split("\n")
    print(f"\nFinestre attive nella sessione '{SESSION}':")
    for f in finestre:
        if f:
            print(f"  • {f}")


def vai_a_tmux():
    print(f"\nEntrando nella sessione tmux '{SESSION}'...")
    print("(Ctrl+B poi d per uscire senza fermare nulla)\n")
    if os.environ.get("TMUX"):
        os.execvp("tmux", ["tmux", "switch-client", "-t", SESSION])
    else:
        os.execvp("tmux", ["tmux", "attach", "-t", SESSION])


def main():
    if not _tmux_ok():
        print("tmux non è installato. Installa con:  sudo apt install tmux")
        sys.exit(1)

    print("\nBenvenuto nel Raspberry Launcher (tmux edition)!")
    _assicura_sessione()
    avvia_faccia()
    avvia_media()
    avvia_pistats()
    avvia_mqtt_listener()

    try:
        while True:
            mostra_menu()
            scelta = input("Scegli un'opzione: ").strip().lower()

            if scelta == "1":
                switch_modalita("generale")
            elif scelta == "2":
                switch_modalita("jarvis")
            elif scelta == "3":
                switch_modalita("drone")
            elif scelta == "4":
                switch_modalita("esplorazione")
            elif scelta == "5":
                switch_modalita("linea")
            elif scelta == "c":
                avvia_controller()
            elif scelta == "v":
                vai_a_tmux()
            elif scelta == "s":
                mostra_stato()
            elif scelta == "k":
                termina_tutti()
            elif scelta == "q":
                print(f"\nI processi restano attivi in tmux (sessione '{SESSION}').")
                print(f"Rientra con:  tmux attach -t {SESSION}")
                print("\nArrivederci! 👋\n")
                sys.exit(0)
            else:
                print("\n⚠ Scelta non valida. Riprova.")

    except KeyboardInterrupt:
        print(f"\n\nUscita dal menu (i moduli restano attivi in tmux '{SESSION}').")
        print("Arrivederci! 👋\n")
        sys.exit(0)


if __name__ == "__main__":
    if "--auto-start" in sys.argv:
        if not _tmux_ok():
            print("tmux non installato.")
            sys.exit(1)
        avvia_tutto_automatico()
        sys.exit(0)
    elif "--stop" in sys.argv:
        ferma_tutto()
        sys.exit(0)
    else:
        main()