"""
sequences/countdown.py — FUSION / RoboEyes
Animazione idle SEQ_COUNTDOWN. Mixin con un solo metodo: _run_countdown_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class CountdownSequenceMixin:
    def _run_countdown_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if elapsed<6.5:
            num=5-int(elapsed)
            if num<0:num=0
            frac=elapsed%1.0
            size=int(180+80*(1-frac))
            alpha=int(255*(1-frac*0.5))
            if 'fonts' not in self.seq_data:
                self.seq_data['fonts']={s:pygame.font.SysFont('monospace',s,bold=True) for s in range(80,280,20)}
            best_size=min(self.seq_data['fonts'].keys(),key=lambda x:abs(x-size))
            font=self.seq_data['fonts'][best_size]
            if num>0:
                label=str(num);col=(255,int(255*(num/5)),0)
            else:
                label='GO!';col=(100,255,100)
            txt=font.render(label,True,col)
            s2=pygame.Surface((txt.get_width(),txt.get_height()),pygame.SRCALPHA)
            s2.blit(txt,(0,0));s2.set_alpha(alpha)
            self.surface.blit(s2,(self.screen_width//2-txt.get_width()//2,self.screen_height//2-txt.get_height()//2))
            scale=0.9+0.2*(1-num/5.0)
            self.eyeLwidth_next=int(self.eyeLwidth_default*scale)
            self.eyeRwidth_next=int(self.eyeRwidth_default*scale)
            self.eyeLheight_next=int(self.eyeLheight_default*scale)
            self.eyeRheight_next=int(self.eyeRheight_default*scale)
        else:
            self.eyeLwidth_next=self.eyeLwidth_default;self.eyeRwidth_next=self.eyeRwidth_default
            self.eyeLheight_next=self.eyeLheight_default;self.eyeRheight_next=self.eyeRheight_default
            return False
        return True

