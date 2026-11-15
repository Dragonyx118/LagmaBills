"""
sequences/sneeze.py — FUSION / RoboEyes
Animazione idle SEQ_SNEEZE. Mixin con un solo metodo: _run_sneeze_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class SneezeSequenceMixin:
    def _run_sneeze_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if elapsed<1.2:
            t=elapsed/1.2
            self.eyeLheight_next=max(1,int(self.eyeLheight_default*(1-t*0.8)))
            self.eyeRheight_next=max(1,int(self.eyeRheight_default*(1-t*0.8)))
            self.tired=True
        elif elapsed<1.5:
            dx=random.randint(-30,30);dy=random.randint(-20,20)
            self.eyeLx+=dx;self.eyeRx+=dx
            self.eyeLy+=dy;self.eyeRy+=dy
            self.eyeLheight_next=self.eyeLheight_default
            self.eyeRheight_next=self.eyeRheight_default
            self.tired=False;self.surprised=True
            if 'font' not in self.seq_data:
                self.seq_data['font']=pygame.font.SysFont('monospace',72,bold=True)
            font=self.seq_data['font']
            txt=font.render('ACHOO!',True,(255,255,100))
            self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,80))
        elif elapsed<2.5:
            self.surprised=False
            self.eyeLheight_next=self.eyeLheight_default
            self.eyeRheight_next=self.eyeRheight_default
        else:
            return False
        return True

