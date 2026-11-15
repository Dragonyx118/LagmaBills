"""
sequences/disco.py — FUSION / RoboEyes
Animazione idle SEQ_DISCO. Mixin con un solo metodo: _run_disco_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class DiscoSequenceMixin:
    def _run_disco_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if elapsed<5.0:
            beat=elapsed*2.5
            for i in range(6):
                phase=(beat+i*0.4)%1.0
                r=int(phase*500)
                alpha=int(255*(1-phase)**2)
                hue=(elapsed*60+i*60)%360
                h=hue/60.0;hi=int(h)%6
                lut=[(255,0,0),(255,165,0),(255,255,0),(0,255,0),(0,150,255),(150,0,255)]
                col=lut[hi%6]
                s=pygame.Surface((r*2+2,r*2+2),pygame.SRCALPHA)
                pygame.draw.circle(s,(col[0],col[1],col[2],alpha),(r+1,r+1),r,max(1,int(8*(1-phase))))
                self.surface.blit(s,(self.screen_width//2-r-1,self.screen_height//2-r-1))
            for _ in range(8):
                sx=random.randint(0,self.screen_width);sy=random.randint(0,self.screen_height)
                sc=random.randint(2,6)
                col2=(random.randint(150,255),random.randint(150,255),random.randint(150,255))
                pygame.draw.circle(self.surface,col2,(sx,sy),sc)
            dance=int(math.sin(elapsed*8)*12)
            self.eyeLy_next=self.eyeLy_default+dance
            self.eyeRy_next=self.eyeRy_default-dance
            self.happy=True
        else:
            self.happy=False;return False
        return True

