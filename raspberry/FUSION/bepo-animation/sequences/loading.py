"""
sequences/loading.py — FUSION / RoboEyes
Animazione idle SEQ_LOADING. Mixin con un solo metodo: _run_loading_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class LoadingSequenceMixin:
    def _run_loading_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if elapsed<5.0:
            prog=min(1.0,elapsed/4.0)
            self.eyeLx_next=self.eyeLx_default+30
            self.eyeRx_next=self.eyeRx_default+30
            bar_x=self.screen_width//2-200;bar_y=self.eyeLy_default+160
            bar_w=400;bar_h=28
            pygame.draw.rect(self.surface,(60,60,60),(bar_x,bar_y,bar_w,bar_h),border_radius=14)
            pygame.draw.rect(self.surface,(100,220,100),(bar_x,bar_y,int(bar_w*prog),bar_h),border_radius=14)
            pygame.draw.rect(self.surface,(200,200,200),(bar_x,bar_y,bar_w,bar_h),border_radius=14,width=3)
            if 'font' not in self.seq_data:
                self.seq_data['font']=pygame.font.SysFont('monospace',26)
            pct=int(prog*100)
            if prog<1.0:
                txt=self.seq_data['font'].render(f'Loading... {pct}%',True,(180,180,180))
                self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,bar_y+36))
                self.eyeLheight_next=int(self.eyeLheight_default*0.6)
                self.eyeRheight_next=int(self.eyeRheight_default*0.6)
                if int(elapsed)%3==0 and elapsed%1<0.3:
                    self.eyeLheight_next=max(1,int(self.eyeLheight_default*0.1))
                    self.eyeRheight_next=max(1,int(self.eyeRheight_default*0.1))
            else:
                self.eyeLheight_next=self.eyeLheight_default
                self.eyeRheight_next=self.eyeRheight_default
                self.happy=True
                txt2=self.seq_data['font'].render('DONE!',True,(100,255,100))
                self.surface.blit(txt2,(self.screen_width//2-txt2.get_width()//2,bar_y+36))
        else:
            self.happy=False;return False
        return True

