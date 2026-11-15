"""
sequences/glitch.py — FUSION / RoboEyes
Animazione idle SEQ_GLITCH. Mixin con un solo metodo: _run_glitch_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class GlitchSequenceMixin:
    def _run_glitch_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if elapsed<4.0:
            glitch_t=(elapsed%0.4)/0.4
            if glitch_t<0.5:
                for _ in range(random.randint(3,8)):
                    gy=random.randint(0,self.screen_height)
                    gw=random.randint(50,400)
                    gx=random.randint(0,self.screen_width-gw)
                    col=(random.randint(0,255),random.randint(0,255),random.randint(0,255))
                    pygame.draw.rect(self.surface,col,(gx,gy,gw,random.randint(2,8)))
                self.eyeLx+=random.randint(-15,15)
                self.eyeRx+=random.randint(-15,15)
                self.eyeLy+=random.randint(-10,10)
            if 'font' not in self.seq_data:
                self.seq_data['font']=pygame.font.SysFont('monospace',40,bold=True)
            if random.random()<0.4:
                font=self.seq_data['font']
                txt=font.render('ERROR_0x'+hex(random.randint(0,65535))[2:].upper(),True,(255,0,0))
                self.surface.blit(txt,(random.randint(0,400),random.randint(0,500)))
        else:
            return False
        return True

