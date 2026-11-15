"""
sequences/hiccup.py — FUSION / RoboEyes
Animazione idle SEQ_HICCUP. Mixin con un solo metodo: _run_hiccup_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class HiccupSequenceMixin:
    def _run_hiccup_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if elapsed<4.0:
            hiccup_t=elapsed%0.8
            if hiccup_t<0.1:
                self.eyeLy+=random.randint(-25,25)
                self.eyeRy+=random.randint(-25,25)
                self.surprised=True
                if 'font' not in self.seq_data:
                    self.seq_data['font']=pygame.font.SysFont('monospace',50,bold=True)
                txt=self.seq_data['font'].render('*HIC*',True,(200,200,255))
                self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,60))
            else:
                self.surprised=False
        else:
            return False
        return True

