#!/usr/bin/env python3
import subprocess
import sys
import os
import signal

# Lista dei processi avviati
processi_attivi = []

def avvia_comando(cmd, shell=False):
    """Avvia un comando in background e salva il processo."""
    try:
        if shell:
            p = subprocess.Popen(cmd, shell=True, preexec_fn=os.setsid)
        else:
            p = subprocess.Popen(cmd, preexec_fn=os.setsid)
        processi_attivi.append(p)
        print(f"  ✔ Avviato: {cmd if isinstance(cmd, str) else ' '.join(cmd)}")
        return p
    except Exception as e:
        print(f"  ✘ Errore avviando '{cmd}': {e}")
        return None

def termina_tutti():
    """Termina tutti i processi avviati."""
    if not processi_attivi:
        print("\nNessun processo attivo da terminare.")
        return
    print(f"\nTerminazione di {len(processi_attivi)} processo/i...")
    for p in processi_attivi:
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except Exception:
            pass
    processi_attivi.clear()
    print("Tutti i processi sono stati terminati.")

def avvia_generale():
    print("\n[GENERALE] Avvio moduli...")
    avvia_comando(["python3", os.path.expanduser("~/FUSION/mqttMedia.py")])
    avvia_comando(["python3", os.path.expanduser("~/FUSION/GPSmqtt.py")])
    avvia_comando(["python3", os.path.expanduser("~/FUSION/streamCamera.py")])
    avvia_comando(["python3", os.path.expanduser("~/FUSION/testI2C.py")])
    avvia_comando(
        "startx /usr/bin/python3 /home/ladrodirame/AIsburra/TUFF/main.py -- :0 vt1",
        shell=True
    )

def avvia_jarvis():
    print("\n[JARVIS] Avvio moduli...")
    avvia_comando(["python3", os.path.expanduser("~/AIsburra/TUFF/wakes.py")])
    avvia_comando(["python3", os.path.expanduser("~/AIsburra/TUFF/bluey.py")])

def avvia_drone():
    print("\n[DRONE] Avvio moduli...")
    avvia_comando(["python3", os.path.expanduser("~/FUSION/droneMqttNew.py")])

def avvia_odometria():
    print("\n[ODOMETRIA] Avvio moduli...")
    avvia_comando(["python3", os.path.expanduser("~/FUSION/odo/myViewerServer.py")])
    avvia_comando(["python3", os.path.expanduser("~/FUSION/odo/navigator.py")])
    avvia_comando(["python3", os.path.expanduser("~/FUSION/odo/occupacyGrid.py")])
    avvia_comando(["python3", os.path.expanduser("~/FUSION/odo/odometria.py")])

def avvia_insegui_linea():
    print("\n[INSEGUI LINEA] Avvio moduli...")
    avvia_comando(["python3", os.path.expanduser("~/FUSION/mqttLinea.py")])

def mostra_menu():
    print("\n" + "═" * 40)
    print("       🤖  RASPBERRY LAUNCHER  🤖")
    print("═" * 40)
    print("  1. Generale")
    print("  2. Jarvis")
    print("  3. Drone")
    print("  4. Odometria")
    print("  5. Insegui Linea")
    print("─" * 40)
    print("  s. Stato processi attivi")
    print("  k. Termina tutti i processi")
    print("  q. Esci")
    print("═" * 40)

def mostra_stato():
    if not processi_attivi:
        print("\nNessun processo attivo.")
    else:
        print(f"\nProcessi attivi: {len(processi_attivi)}")
        for i, p in enumerate(processi_attivi, 1):
            stato = "in esecuzione" if p.poll() is None else "terminato"
            print(f"  [{i}] PID {p.pid} — {stato}")

def main():
    print("\nBenvenuto nel Raspberry Launcher!")

    try:
        while True:
            mostra_menu()
            scelta = input("Scegli un'opzione: ").strip().lower()

            if scelta == "1":
                avvia_generale()
            elif scelta == "2":
                avvia_jarvis()
            elif scelta == "3":
                avvia_drone()
            elif scelta == "4":
                avvia_odometria()
            elif scelta == "5":
                avvia_insegui_linea()
            elif scelta == "s":
                mostra_stato()
            elif scelta == "k":
                termina_tutti()
            elif scelta == "q":
                termina_tutti()
                print("\nArrivederci! 👋\n")
                sys.exit(0)
            else:
                print("\n⚠ Scelta non valida. Riprova.")

    except KeyboardInterrupt:
        print("\n\nInterruzione rilevata (Ctrl+C).")
        termina_tutti()
        print("Arrivederci! 👋\n")
        sys.exit(0)

if __name__ == "__main__":
    main()