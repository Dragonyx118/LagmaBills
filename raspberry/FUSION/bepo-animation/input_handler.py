"""
input_handler.py — FUSION / RoboEyes
Gestione eventi tastiera: tasti numerici per i mood base, lettere per
le animazioni one-shot, F1-F12 per le sequenze più lunghe. Utile per
testare la faccina da tastiera senza passare da MQTT.

Per aggiungere un nuovo tasto: aggiungi una riga nel dizionario KEYS
(mood semplice) oppure un elif in handle_keydown (animazione/sequenza).
"""

import random
import pygame

from constants import (
    DEFAULT, TIRED, ANGRY, HAPPY, SURPRISED, SAD, LOVE, SCARED,
    BORED, EXCITED, DIZZY, SLEEPY, CONFUSED2, THINKING, TALKING,
    FURIOUS, IDEA, SUSPICIOUS, SMUG,
    SEQ_SLEEP, SEQ_BUTTERFLY, SEQ_SNEEZE, SEQ_GLITCH, SEQ_STARGAZING,
    SEQ_HICCUP, SEQ_DAYDREAM, SEQ_LOADING, SEQ_MATRIX, SEQ_PINGPONG,
    SEQ_COUNTDOWN, SEQ_TETRIS, SEQ_WAKEWORD,
)

KEYS = {
    pygame.K_0: DEFAULT, pygame.K_1: TIRED, pygame.K_2: ANGRY, pygame.K_3: HAPPY,
    pygame.K_4: SURPRISED, pygame.K_5: SAD, pygame.K_6: LOVE, pygame.K_7: SCARED,
    pygame.K_8: BORED, pygame.K_9: EXCITED,
}


def handle_keydown(event, robo, idle_state, idle_timer, neutral_duration):
    """
    Gestisce un singolo evento KEYDOWN.
    idle_state / idle_timer / neutral_duration sono liste a 1 elemento
    (usate come "riferimenti mutabili", come nell'originale) condivise
    con il loop idle in main.py.
    """
    if event.key == pygame.K_ESCAPE:
        pygame.quit()
        import sys
        sys.exit()

    def trigger_command(mood_or_anim, duration_ms=4000):
        if callable(mood_or_anim):
            mood_or_anim()
        else:
            robo.setMood(mood_or_anim)
        idle_state[0] = 'neutral'
        idle_timer[0] = pygame.time.get_ticks() + duration_ms
        neutral_duration[0] = random.randint(8000, 18000)

    if event.key in KEYS:
        trigger_command(KEYS[event.key])
    elif event.key == pygame.K_w:  trigger_command(robo.anim_wink, 1000)
    elif event.key == pygame.K_e:  trigger_command(lambda: robo.anim_wink('right'), 1000)
    elif event.key == pygame.K_l:  trigger_command(robo.anim_look_around, 3000)
    elif event.key == pygame.K_s:  trigger_command(robo.anim_spin, 2500)
    elif event.key == pygame.K_k:  trigger_command(robo.anim_shake, 1000)
    elif event.key == pygame.K_h:  trigger_command(robo.anim_hearts, 2000)
    elif event.key == pygame.K_c:  trigger_command(robo.anim_confused, 1000)
    elif event.key == pygame.K_g:  trigger_command(robo.anim_laugh, 1000)
    elif event.key == pygame.K_b:  robo.blink()
    elif event.key == pygame.K_d:  trigger_command(DIZZY, 3000)
    elif event.key == pygame.K_z:  trigger_command(SLEEPY, 4000)
    elif event.key == pygame.K_x:  trigger_command(CONFUSED2, 3000)
    elif event.key == pygame.K_t:  trigger_command(THINKING, 4000)
    elif event.key == pygame.K_a:  trigger_command(TALKING, 4000)
    elif event.key == pygame.K_f:  trigger_command(FURIOUS, 3000)
    elif event.key == pygame.K_i:  trigger_command(IDEA, 4000)
    elif event.key == pygame.K_u:  trigger_command(SUSPICIOUS, 3000)
    elif event.key == pygame.K_m:  trigger_command(SMUG, 3000)
    elif event.key == pygame.K_F1: trigger_command(SEQ_SLEEP, 8000)
    elif event.key == pygame.K_F2: trigger_command(SEQ_BUTTERFLY, 6000)
    elif event.key == pygame.K_F3: trigger_command(SEQ_SNEEZE, 4000)
    elif event.key == pygame.K_F4: trigger_command(SEQ_GLITCH, 5000)
    elif event.key == pygame.K_F5: trigger_command(SEQ_STARGAZING, 6000)
    elif event.key == pygame.K_F6: trigger_command(SEQ_HICCUP, 5000)
    elif event.key == pygame.K_F7: trigger_command(SEQ_DAYDREAM, 6000)
    elif event.key == pygame.K_F8: trigger_command(SEQ_LOADING, 6000)
    elif event.key == pygame.K_F9: trigger_command(SEQ_MATRIX, 6000)
    elif event.key == pygame.K_F10: trigger_command(SEQ_PINGPONG, 7000)
    elif event.key == pygame.K_F11: trigger_command(SEQ_COUNTDOWN, 8000)
    elif event.key == pygame.K_F12: trigger_command(SEQ_TETRIS, 8000)
    # tasto rapido per testare wakeword senza microfono
    elif event.key == pygame.K_n:  trigger_command(SEQ_WAKEWORD, 10000)
