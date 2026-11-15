"""
sequences/pacman.py — FUSION / RoboEyes
Animazione idle SEQ_PACMAN. Mixin con un solo metodo: _run_pacman_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class PacmanSequenceMixin:
    def _run_pacman_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if 'dots' not in self.seq_data:
            self.seq_data['dots']=[(random.randint(60,self.screen_width-60),random.randint(60,self.screen_height-60)) for _ in range(18)]
            self.seq_data['px']=float(self.screen_width//2)
            self.seq_data['py']=float(self.screen_height//2)
            self.seq_data['angle']=0.0
            self.seq_data['mouth']=0.0
            self.seq_data['mouth_dir']=1
            self.seq_data['score']=0
            self.seq_data['font']=pygame.font.SysFont('monospace',28,bold=True)
        if elapsed<6.0:
            d=self.seq_data
            if d['dots']:
                tx,ty=min(d['dots'],key=lambda p:(p[0]-d['px'])**2+(p[1]-d['py'])**2)
                dx2=tx-d['px'];dy2=ty-d['py']
                dist=math.hypot(dx2,dy2)
                speed=160
                if dist>6:
                    d['px']+=dx2/dist*speed*self.frame_interval/1000.0
                    d['py']+=dy2/dist*speed*self.frame_interval/1000.0
                    d['angle']=math.atan2(dy2,dx2)
                else:
                    d['score']+=1
                    d['dots'].remove((tx,ty))
            d['mouth']+=d['mouth_dir']*0.15
            if d['mouth']>0.35:d['mouth_dir']=-1
            if d['mouth']<0.0:d['mouth_dir']=1
            for dx3,dy3 in d['dots']:
                pygame.draw.circle(self.surface,(255,220,0),(dx3,dy3),6)
            px,py=int(d['px']),int(d['py'])
            angle=d['angle']
            mouth=d['mouth']
            pygame.draw.circle(self.surface,(0,0,0),(px,py),26)
            pygame.draw.circle(self.surface,(255,220,0),(px,py),24)
            pts=[(px,py)]
            for a_off in [mouth,-mouth]:
                pts.append((px+int(math.cos(angle+a_off)*28),py+int(math.sin(angle+a_off)*28)))
            pygame.draw.polygon(self.surface,(0,0,0),pts)
            txt=d['font'].render(f'SCORE: {d["score"]}',True,(255,220,0))
            self.surface.blit(txt,(10,8))
            self.eyeLx_next=self.eyeLx_default+int((d['px']-self.screen_width//2)*0.2)
            self.eyeRx_next=self.eyeRx_default+int((d['px']-self.screen_width//2)*0.2)
            self.eyeLy_next=self.eyeLy_default+int((d['py']-self.screen_height//2)*0.15)
            self.eyeRy_next=self.eyeRy_default+int((d['py']-self.screen_height//2)*0.15)
            self.happy=True
        else:
            self.happy=False;return False
        return True

