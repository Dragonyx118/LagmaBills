"""
sequences/butterfly.py — FUSION / RoboEyes
Animazione idle SEQ_BUTTERFLY. Mixin con un solo metodo: _run_butterfly_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class ButterflySequenceMixin:
    def _run_butterfly_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        self.happy=True
        duration=5.0
        if elapsed<duration:
            prog=elapsed/duration
            bx=int(-80+prog*(self.screen_width+160))
            by=int(self.screen_height*0.3+math.sin(prog*math.pi*3)*80)
            self._draw_butterfly(bx,by,elapsed)
            eye_cx=self.screen_width//2
            dx=bx-eye_cx
            self.eyeLx_next=self.eyeLx_default+int(dx*0.3)
            self.eyeRx_next=self.eyeRx_default+int(dx*0.3)
            self.eyeLy_next=self.eyeLy_default+int((by-self.screen_height//2)*0.2)
            self.eyeRy_next=self.eyeRy_default+int((by-self.screen_height//2)*0.2)
            if 0.4<prog<0.6:
                self.surprised=True;self.happy=False
            else:
                self.surprised=False;self.happy=True
        else:
            self.happy=False;return False
        return True

