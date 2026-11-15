"""
sequences/dvd.py — FUSION / RoboEyes
Animazione idle SEQ_DVD. Mixin con un solo metodo: _run_dvd_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class DvdSequenceMixin:
    def _run_dvd_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        d=self.seq_data
        img=self._get_img_dvd()
        if 'x' not in d:
            w,h=img.get_size()
            d['w']=w;d['h']=h
            d['x']=float(self.screen_width//2-w//2)
            d['y']=float(self.screen_height//2-h//2)
            d['vx']=random.choice([-1,1])*130.0
            d['vy']=random.choice([-1,1])*90.0
            d['col']=(random.randint(80,255),random.randint(80,255),random.randint(80,255))
            d['corners']=0
            d['font_sm']=pygame.font.SysFont('monospace',22)
            d['font_corner']=pygame.font.SysFont('monospace',52,bold=True)
        if elapsed<7.0:
            dt2=self.frame_interval/1000.0
            d['x']+=d['vx']*dt2
            d['y']+=d['vy']*dt2
            w,h=d['w'],d['h']
            hit=False
            corner_hit=False
            if d['x']<=0:d['x']=0;d['vx']=abs(d['vx']);hit=True
            if d['x']+w>=self.screen_width:d['x']=self.screen_width-w;d['vx']=-abs(d['vx']);hit=True
            if d['y']<=0:d['y']=0;d['vy']=abs(d['vy']);hit=True
            if d['y']+h>=self.screen_height:d['y']=self.screen_height-h;d['vy']=-abs(d['vy']);hit=True
            if hit:
                d['col']=(random.randint(80,255),random.randint(80,255),random.randint(80,255))
                d['corners']+=1
                if (abs(d['x'])<=2 or abs(d['x']+w-self.screen_width)<=2) and \
                   (abs(d['y'])<=2 or abs(d['y']+h-self.screen_height)<=2):
                    corner_hit=True
            tinted=img.copy()
            tinted.fill(d['col'],special_flags=pygame.BLEND_RGB_MULT)
            self.surface.blit(tinted,(int(d['x']),int(d['y'])))
            sub=d['font_sm'].render(f'corners hit: {d["corners"]}',True,(80,80,80))
            self.surface.blit(sub,(self.screen_width//2-sub.get_width()//2,self.screen_height-36))
            if corner_hit:
                txt2=d['font_corner'].render('CORNER!!!',True,(255,255,0))
                self.surface.blit(txt2,(self.screen_width//2-txt2.get_width()//2,200))
                self.surprised=True
            cx_logo=d['x']+w//2;cy_logo=d['y']+h//2
            self.eyeLx_next=self.eyeLx_default+int((cx_logo-self.screen_width//2)*0.22)
            self.eyeRx_next=self.eyeRx_default+int((cx_logo-self.screen_width//2)*0.22)
            self.eyeLy_next=self.eyeLy_default+int((cy_logo-self.screen_height//2)*0.15)
            self.eyeRy_next=self.eyeRy_default+int((cy_logo-self.screen_height//2)*0.15)
        else:
            return False
        return True

