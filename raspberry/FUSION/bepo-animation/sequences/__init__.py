"""
sequences/__init__.py — FUSION / RoboEyes

Registry centrale di tutte le animazioni idle (SEQ_*) + dispatcher.

Per aggiungere una NUOVA animazione:
  1. crea sequences/mia_anim.py con una classe MiaAnimSequenceMixin
     che definisce un solo metodo _run_mia_anim_sequence(self, ct)
     (guarda sequences/sleep.py come modello più semplice)
  2. aggiungi la costante SEQ_MIA_ANIM in constants.py
  3. importa la classe qui sotto e aggiungi una riga a SEQUENCE_METHODS
  4. aggiungi la mixin class alla lista di ereditarietà di RoboEyes
     in main.py
  5. (opzionale) aggiungila a IDLE_EVENTS / IDLE_EVENT_DURATIONS in
     constants.py se vuoi che parta anche da sola durante l'idle

Nessun altro file va toccato.
"""

from constants import (
    SEQ_SLEEP, SEQ_BUTTERFLY, SEQ_SNEEZE, SEQ_GLITCH, SEQ_STARGAZING,
    SEQ_HICCUP, SEQ_DAYDREAM, SEQ_LOADING, SEQ_MATRIX, SEQ_PINGPONG,
    SEQ_COUNTDOWN, SEQ_TETRIS, SEQ_DISCO, SEQ_TYPEWRITER, SEQ_PACMAN,
    SEQ_REBOOT, SEQ_SNAKE, SEQ_DVD, SEQ_HACKER, SEQ_WEATHER, SEQ_AMONGUS,
    SEQ_NEWSTICKER, SEQ_SLOT, SEQ_ULTRAKILL, SEQ_WAKEWORD,
)

from .sleep import SleepSequenceMixin
from .butterfly import ButterflySequenceMixin
from .sneeze import SneezeSequenceMixin
from .glitch import GlitchSequenceMixin
from .stargazing import StargazingSequenceMixin
from .hiccup import HiccupSequenceMixin
from .daydream import DaydreamSequenceMixin
from .loading import LoadingSequenceMixin
from .matrix import MatrixSequenceMixin
from .pingpong import PingpongSequenceMixin
from .countdown import CountdownSequenceMixin
from .tetris import TetrisSequenceMixin
from .disco import DiscoSequenceMixin
from .typewriter import TypewriterSequenceMixin
from .pacman import PacmanSequenceMixin
from .reboot import RebootSequenceMixin
from .snake import SnakeSequenceMixin
from .dvd import DvdSequenceMixin
from .hacker import HackerSequenceMixin
from .weather import WeatherSequenceMixin
from .amongus import AmongusSequenceMixin
from .newsticker import NewstickerSequenceMixin
from .slot import SlotSequenceMixin
from .ultrakill import UltrakillSequenceMixin
from .wakeword import WakewordSequenceMixin

# Tutte le mixin delle sequenze, da aggiungere all'ereditarietà di
# RoboEyes in main.py (comodo per non dimenticarne una).
ALL_SEQUENCE_MIXINS = [
    SleepSequenceMixin, ButterflySequenceMixin, SneezeSequenceMixin,
    GlitchSequenceMixin, StargazingSequenceMixin, HiccupSequenceMixin,
    DaydreamSequenceMixin, LoadingSequenceMixin, MatrixSequenceMixin,
    PingpongSequenceMixin, CountdownSequenceMixin, TetrisSequenceMixin,
    DiscoSequenceMixin, TypewriterSequenceMixin, PacmanSequenceMixin,
    RebootSequenceMixin, SnakeSequenceMixin, DvdSequenceMixin,
    HackerSequenceMixin, WeatherSequenceMixin, AmongusSequenceMixin,
    NewstickerSequenceMixin, SlotSequenceMixin, UltrakillSequenceMixin,
    WakewordSequenceMixin,
]

# costante SEQ_* -> nome del metodo che la gestisce
SEQUENCE_METHODS = {
    SEQ_SLEEP:      "_run_sleep_sequence",
    SEQ_BUTTERFLY:  "_run_butterfly_sequence",
    SEQ_SNEEZE:     "_run_sneeze_sequence",
    SEQ_GLITCH:     "_run_glitch_sequence",
    SEQ_STARGAZING: "_run_stargazing_sequence",
    SEQ_HICCUP:     "_run_hiccup_sequence",
    SEQ_DAYDREAM:   "_run_daydream_sequence",
    SEQ_LOADING:    "_run_loading_sequence",
    SEQ_MATRIX:     "_run_matrix_sequence",
    SEQ_PINGPONG:   "_run_pingpong_sequence",
    SEQ_COUNTDOWN:  "_run_countdown_sequence",
    SEQ_TETRIS:     "_run_tetris_sequence",
    SEQ_DISCO:      "_run_disco_sequence",
    SEQ_TYPEWRITER: "_run_typewriter_sequence",
    SEQ_PACMAN:     "_run_pacman_sequence",
    SEQ_REBOOT:     "_run_reboot_sequence",
    SEQ_SNAKE:      "_run_snake_sequence",
    SEQ_DVD:        "_run_dvd_sequence",
    SEQ_HACKER:     "_run_hacker_sequence",
    SEQ_WEATHER:    "_run_weather_sequence",
    SEQ_AMONGUS:    "_run_amongus_sequence",
    SEQ_NEWSTICKER: "_run_newsticker_sequence",
    SEQ_SLOT:       "_run_slot_sequence",
    SEQ_ULTRAKILL:  "_run_ultrakill_sequence",
    SEQ_WAKEWORD:   "_run_wakeword_sequence",
}


class SequenceDispatchMixin:
    """
    Sostituisce il vecchio _run_sequence() con un if/elif infinito:
    guarda semplicemente nel registry sopra quale metodo chiamare.
    Ogni metodo _run_xxx_sequence calcola da solo il proprio `elapsed`
    e ritorna True (sequenza ancora attiva) o False (terminata).
    """

    def _run_sequence(self, ct):
        method_name = SEQUENCE_METHODS.get(self.sequence)
        if method_name is None:
            return False
        return getattr(self, method_name)(ct)
