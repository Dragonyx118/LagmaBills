"""
main.py — FUSION / RoboEyes — entry point
Comando di avvio invariato:
  startx /usr/bin/python3 /home/ladrodirame/FUSION/main.py -- :0 vt1

Questo file fa solo 3 cose:
  1. assembla la classe RoboEyes a partire dai mixin (eyes/, sequences/)
  2. avvia MQTT
  3. fa girare il loop pygame (eventi tastiera + idle + render)

Tutta la logica vera vive negli altri moduli:
  constants.py       → costanti MOOD/SEQ, mappe nomi, lista idle
  assets.py           → caricamento immagini
  weather.py          → meteo per sequences/weather.py
  eyes/state.py       → stato + init + setter di basso livello
  eyes/moods.py       → setMood() e animazioni one-shot
  eyes/drawing.py     → drawEyes() e helper di disegno
  sequences/*.py      → una animazione idle per file
  mqtt_bridge.py      → ascolto MQTT (robot/face, robot/cmd)
  socket_bridge.py    → listener TCP 9876 (wakeword, comandi rapidi)
  input_handler.py    → mapping tasti per test manuale
"""

import sys
import random

import pygame

from constants import DEFAULT, IDLE_EVENTS, IDLE_EVENT_DURATIONS, BGCOLOR, SEQ_WAKEWORD
from eyes.state import EyesStateMixin
from eyes.moods import MoodsMixin
from eyes.drawing import DrawingMixin
from sequences import SequenceDispatchMixin, ALL_SEQUENCE_MIXINS
from mqtt_bridge import start_mqtt_face
from input_handler import handle_keydown


class RoboEyes(
    EyesStateMixin,
    MoodsMixin,
    DrawingMixin,
    SequenceDispatchMixin,
    *ALL_SEQUENCE_MIXINS,
):
    pass


def main():
    pygame.init()
    pygame.font.init()
    screen = pygame.display.set_mode((1024, 600))
    pygame.display.set_caption('RoboEyes')
    pygame.mouse.set_visible(False)
    draw_surface = pygame.Surface((1024, 600), pygame.SRCALPHA)

    robo = RoboEyes(draw_surface, width=1024, height=600, frame_rate=50)
    robo.begin()
    start_mqtt_face(robo)
    robo.setMood(DEFAULT)
    robo.setAutoblinker(True, interval=2, variation=3)
    robo.setIdleMode(True, interval=4, variation=4)
    robo.setCuriosity(True)
    clock = pygame.time.Clock()

    # ── stato idle (scambia mood a caso quando non succede nulla) ──
    idle_state = ['neutral']
    idle_timer = [pygame.time.get_ticks()]
    neutral_duration = [random.randint(8000, 18000)]
    idle_is_sequence = [False]

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                handle_keydown(event, robo, idle_state, idle_timer, neutral_duration)

        ct = pygame.time.get_ticks()

        # ── logica idle ──────────────────────────────────────────
        # Se SEQ_WAKEWORD è attiva, l'idle non interviene
        if robo.sequence == SEQ_WAKEWORD:
            pass  # wakeword_end arriverà da wakewordSimple.py via socket/mqtt
        elif idle_state[0] == 'neutral':
            if ct - idle_timer[0] >= neutral_duration[0]:
                mood = random.choice(IDLE_EVENTS)
                dur = IDLE_EVENT_DURATIONS.get(mood, 4) * 1000
                robo.setMood(mood)
                idle_state[0] = 'event'
                idle_timer[0] = ct
                neutral_duration[0] = dur
                idle_is_sequence[0] = mood >= 100  # True se è una SEQ_*
        elif idle_state[0] == 'event':
            seq_done = idle_is_sequence[0] and robo.sequence is None
            event_done = ct - idle_timer[0] >= neutral_duration[0]
            if event_done or seq_done:
                robo.setMood(DEFAULT)
                idle_state[0] = 'neutral'
                idle_timer[0] = ct
                neutral_duration[0] = random.randint(15000, 30000)

        robo.update()
        if robo.next_mood is not None:
            idle_state[0] = 'neutral'
            idle_timer[0] = ct + 5000
            neutral_duration[0] = random.randint(8000, 18000)

        screen.fill(BGCOLOR)
        screen.blit(draw_surface, (0, 0))
        pygame.display.flip()
        clock.tick(60)


if __name__ == '__main__':
    main()
