"""
sequences/pingpong.py — FUSION / RoboEyes
Animazione idle SEQ_PINGPONG. Mixin con un solo metodo: _run_pingpong_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class PingpongSequenceMixin:
    def _run_pingpong_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if elapsed<6.0:
            d=self.seq_data
            if 'bx' not in d:
                d['bx']=float(self.screen_width//2)
                d['by']=float(self.screen_height//2)
                d['vx']=220.0*random.choice([-1,1])
                d['vy']=160.0*random.choice([-1,1])
                d['score']=[0,0]
                d['font']=pygame.font.SysFont('monospace',48,bold=True)
                d['font_sm']=pygame.font.SysFont('monospace',22)
            dt=self.frame_interval/1000.0
            d['bx']+=d['vx']*dt
            d['by']+=d['vy']*dt
            if d['by']<14:d['by']=14;d['vy']=abs(d['vy'])
            if d['by']>self.screen_height-14:d['by']=self.screen_height-14;d['vy']=-abs(d['vy'])
            paddle_h=80
            paddle_margin=30
            left_paddle_y=int(d['by'])-paddle_h//2
            right_paddle_y=int(d['by'])-paddle_h//2
            if d['bx']<paddle_margin+12:
                if left_paddle_y < int(d['by']) < left_paddle_y+paddle_h:
                    d['vx']=abs(d['vx'])*random.uniform(0.9,1.1)
                else:
                    d['score'][1]+=1
                    d['bx']=float(self.screen_width//2)
                    d['vx']=220.0
            if d['bx']>self.screen_width-paddle_margin-12:
                if right_paddle_y < int(d['by']) < right_paddle_y+paddle_h:
                    d['vx']=-abs(d['vx'])*random.uniform(0.9,1.1)
                else:
                    d['score'][0]+=1
                    d['bx']=float(self.screen_width//2)
                    d['vx']=-220.0
            for yd in range(0,self.screen_height,30):
                pygame.draw.rect(self.surface,(60,60,60),(self.screen_width//2-3,yd,6,18))
            pygame.draw.rect(self.surface,(200,200,200),(18,left_paddle_y,12,paddle_h),border_radius=6)
            pygame.draw.rect(self.surface,(200,200,200),(self.screen_width-30,right_paddle_y,12,paddle_h),border_radius=6)
            pygame.draw.circle(self.surface,(255,255,255),(int(d['bx']),int(d['by'])),14)
            pygame.draw.circle(self.surface,(0,0,0),(int(d['bx']),int(d['by'])),10)
            sc=d['score']
            txt=d['font'].render(f'{sc[0]}  {sc[1]}',True,(180,180,180))
            self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,20))
            self.eyeLx_next=self.eyeLx_default+int((d['bx']-self.screen_width//2)*0.25)
            self.eyeRx_next=self.eyeRx_default+int((d['bx']-self.screen_width//2)*0.25)
            self.eyeLy_next=self.eyeLy_default+int((d['by']-self.screen_height//2)*0.15)
            self.eyeRy_next=self.eyeRy_default+int((d['by']-self.screen_height//2)*0.15)
        else:
            return False
        return True

