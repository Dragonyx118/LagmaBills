"""
sequences/stargazing.py — FUSION / RoboEyes
Animazione idle SEQ_STARGAZING. Mixin con un solo metodo: _run_stargazing_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class StargazingSequenceMixin:
    def _run_stargazing_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if elapsed<5.0:
            self.eyeLy_next=self.eyeLy_default-40
            self.eyeRy_next=self.eyeRy_default-40
            self._draw_stars(elapsed)
            if int(elapsed*2)%6==0:
                self.eyeLheight_next=int(self.eyeLheight_default*0.7)
                self.eyeRheight_next=int(self.eyeRheight_default*0.7)
            else:
                self.eyeLheight_next=self.eyeLheight_default
                self.eyeRheight_next=self.eyeRheight_default
            self.eyelids_happy_bottom_offset_next=self.eyeLheight_current//4
        else:
            self.eyelids_happy_bottom_offset_next=0;return False
        return True

