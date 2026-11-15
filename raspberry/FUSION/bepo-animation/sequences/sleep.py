"""
sequences/sleep.py — FUSION / RoboEyes
Animazione idle SEQ_SLEEP. Mixin con un solo metodo: _run_sleep_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class SleepSequenceMixin:
    def _run_sleep_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if elapsed<1.0:
            t=elapsed/1.0
            self.eyeLheight_next=max(1,int(self.eyeLheight_default*(1-t)))
            self.eyeRheight_next=max(1,int(self.eyeRheight_default*(1-t)))
        elif elapsed<6.0:
            self.eyeLheight_next=1;self.eyeRheight_next=1
            loop=((elapsed-1.0)%2.0)/2.0
            alpha=min(1.0,loop*3) if loop<0.33 else max(0.0,1.0-(loop-0.33)*2)
            self._draw_zzz(alpha, offset_y=-int(loop*30))
        elif elapsed<7.0:
            t=(elapsed-6.0)/1.0
            self.eyeLheight_next=int(self.eyeLheight_default*t)
            self.eyeRheight_next=int(self.eyeRheight_default*t)
            self.surprised=True
        else:
            self.surprised=False;return False
        return True

