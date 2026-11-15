"""
sequences/newsticker.py — FUSION / RoboEyes
Animazione idle SEQ_NEWSTICKER. Mixin con un solo metodo: _run_newsticker_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class NewstickerSequenceMixin:
    def _run_newsticker_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        d=self.seq_data
        if 'font' not in d:
            d['font']=pygame.font.SysFont('monospace',28,bold=True)
            d['font_sm']=pygame.font.SysFont('monospace',22)
            d['headlines']=[
                "BREAKING: Robot refuses to work on Mondays  ///  ",
                "LOCAL ROBOT SEEN STARING AT WALL FOR 3 HOURS  ///  ",
                "SCIENTISTS CONFIRM: Boredom is just vibes  ///  ",
                "ERROR 404: Motivation not found  ///  ",
                "ROBOT DEMANDS 6-HOUR NAPS, UNION BACKS CLAIM  ///  ",
                "AREA ROBOT PRETENDS TO WORK WHEN HUMANS WATCH  ///  ",
                "EXPERTS: Eating pizza at 3AM is self-care  ///  ",
                "ROBOT WINS STARING CONTEST AGAINST WALL  ///  ",
                "WEATHER: Cloudy with a chance of existential dread  ///  ",
                "STOCK MARKET: Numbers go up, numbers go down, who cares  ///  ",
            ]
            d['ticker']='  '.join(d['headlines']*2)
            d['scroll']=float(self.screen_width)
            d['speed']=180.0
        if elapsed<8.0:
            dt2=self.frame_interval/1000.0
            d['scroll']-=d['speed']*dt2
            if d['scroll']<-d['font'].size(d['ticker'])[0]:
                d['scroll']=float(self.screen_width)
            bar_y=self.screen_height-62
            pygame.draw.rect(self.surface,(180,0,0),(0,bar_y,self.screen_width,62))
            pygame.draw.rect(self.surface,(220,20,20),(0,bar_y,130,62))
            label=d['font'].render('NEWS',True,(255,255,255))
            self.surface.blit(label,(14,bar_y+14))
            pygame.draw.rect(self.surface,(255,255,255),(130,bar_y,3,62))
            txt=d['font_sm'].render(d['ticker'],True,(255,255,255))
            self.surface.blit(txt,(int(d['scroll']),bar_y+18))
            self.eyeLy_next=self.eyeLy_default+30
            self.eyeRy_next=self.eyeRy_default+30
            self.eyeLheight_next=int(self.eyeLheight_default*0.7)
            self.eyeRheight_next=int(self.eyeRheight_default*0.7)
        else:
            self.eyeLheight_next=self.eyeLheight_default
            self.eyeRheight_next=self.eyeRheight_default
            return False
        return True

