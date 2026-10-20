#!/usr/bin/env python3
"""
mapController.py — LagmaBills
Stampa in tempo reale indice e nome di ogni bottone/asse premuto,
per mappare con precisione il controller collegato (Bluetooth diretto
al Pi o USB). Utile perché l'ordine SDL può variare leggermente
tra firmware diversi dello stesso modello di controller.

USO: premi i bottoni uno alla volta e leggi l'indice che appare.
     Muovi gli stick e i grilletti per vedere gli indici degli assi.
     Ctrl+C per uscire.
"""

import pygame
import time
import sys

pygame.init()
pygame.joystick.init()

if pygame.joystick.get_count() == 0:
    sys.exit("Nessun controller rilevato. Collegalo/sincronizzalo e riprova.")

joy = pygame.joystick.Joystick(0)
joy.init()

print(f"Controller: '{joy.get_name()}'")
print(f"Assi: {joy.get_numaxes()}  |  Bottoni: {joy.get_numbuttons()}  |  Hat: {joy.get_numhats()}")
print("\nPremi bottoni / muovi stick e grilletti. Ctrl+C per uscire.\n")

last_axis_vals = [0.0] * joy.get_numaxes()
AXIS_THRESHOLD = 0.3   # evita spam da rumore/drift dello stick

try:
    while True:
        for event in pygame.event.get():
            if event.type == pygame.JOYBUTTONDOWN:
                print(f"[BOTTONE PREMUTO]  indice={event.button}")
            elif event.type == pygame.JOYBUTTONUP:
                print(f"[bottone rilasciato] indice={event.button}")
            elif event.type == pygame.JOYHATMOTION:
                print(f"[D-PAD/HAT] indice={event.hat}  valore={event.value}")

        # Assi: controllo manuale (JOYAXISMOTION spammerebbe troppo)
        for i in range(joy.get_numaxes()):
            v = joy.get_axis(i)
            if abs(v - last_axis_vals[i]) > 0.05 and abs(v) > AXIS_THRESHOLD:
                print(f"[ASSE] indice={i}  valore={v:+.2f}")
            last_axis_vals[i] = v

        time.sleep(0.05)

except KeyboardInterrupt:
    print("\nUscita.")
