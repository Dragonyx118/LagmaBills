"""
sequences/daydream.py — FUSION / RoboEyes
Animazione idle SEQ_DAYDREAM. Mixin con un solo metodo: _run_daydream_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class DaydreamSequenceMixin:
    def _run_daydream_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if elapsed<5.0:
            alpha=int(min(1.0,elapsed/0.6)*255)
            self.eyeLheight_next=int(self.eyeLheight_default*0.55)
            self.eyeRheight_next=int(self.eyeRheight_default*0.55)
            self.eyelids_happy_bottom_offset_next=self.eyeLheight_current//3
            cx=self.screen_width//2+40;cy=self.eyeLy_default-80
            bubbles=[(cx-50,cy+8,24),(cx-20,cy-14,30),(cx+18,cy-18,32),(cx+48,cy-4,24),(cx+60,cy+15,18)]
            for bx,by,br in bubbles:
                s=pygame.Surface((br*2+4,br*2+4),pygame.SRCALPHA)
                pygame.draw.circle(s,(255,255,255,alpha),(br+2,br+2),br)
                self.surface.blit(s,(bx-br-2,by-br-2))
            fill=pygame.Surface((130,44),pygame.SRCALPHA);fill.fill((255,255,255,alpha))
            self.surface.blit(fill,(cx-64,cy-12))
            pulse=0.85+0.15*abs(math.sin(elapsed*3))
            for hx,hy in [(cx-22,cy+4),(cx+18,cy+4)]:
                hs=int(12*pulse)
                sc=pygame.Surface((hs*3,hs*3),pygame.SRCALPHA)
                col=(255,80,120,alpha)
                pygame.draw.circle(sc,col,(hs,hs),hs)
                pygame.draw.circle(sc,col,(hs*2,hs),hs)
                pygame.draw.polygon(sc,col,[(0,hs),(hs*3//2,hs*3),(hs*3,hs)])
                self.surface.blit(sc,(hx-hs,hy-hs))
            for i,r in enumerate([5,7,10]):
                dx2=cx-80+i*22;dy2=self.eyeLy_default-20-i*16
                s2=pygame.Surface((r*2,r*2),pygame.SRCALPHA)
                pygame.draw.circle(s2,(255,255,255,alpha),(r,r),r)
                self.surface.blit(s2,(dx2-r,dy2-r))
        else:
            self.eyelids_happy_bottom_offset_next=0;return False
        return True

