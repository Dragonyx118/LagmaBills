"""
sequences/amongus.py — FUSION / RoboEyes
Animazione idle SEQ_AMONGUS. Mixin con un solo metodo: _run_amongus_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class AmongusSequenceMixin:
    def _run_amongus_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        d=self.seq_data
        img=self._get_img_au()
        if 'x' not in d:
            d['x']=float(-100)
            d['y']=float(self.screen_height*0.5)
            d['vx']=70.0
            d['vy']=15.0
            d['rot']=0.0
            d['rot_speed']=0.4
            d['impostor']=random.random()<0.3
            d['font']=pygame.font.SysFont('monospace',26,bold=True)
            d['stars']=[(random.randint(0,1024),random.randint(0,600),random.uniform(0.5,3)) for _ in range(80)]
            d['star_speed']=20.0
        if elapsed<9.0:
            dt2=self.frame_interval/1000.0
            d['x']+=d['vx']*dt2
            d['y']+=math.sin(elapsed*0.4)*d['vy']*dt2
            d['rot']+=d['rot_speed']*dt2
            for i,(sx,sy,sr) in enumerate(d['stars']):
                nx2=sx-d['star_speed']*sr*dt2
                if nx2<0:nx2=self.screen_width
                d['stars'][i]=(nx2,sy,sr)
                brightness=int(150+sr*35)
                r_px=max(1,int(sr))
                pygame.draw.circle(self.surface,(brightness,brightness,brightness),(int(nx2),int(sy)),r_px)
            rot_deg=math.degrees(d['rot'])
            rotated=pygame.transform.rotate(img,rot_deg)
            rw,rh=rotated.get_size()
            self.surface.blit(rotated,(int(d['x'])-rw//2,int(d['y'])-rh//2))
            if d['impostor']:
                txt=d['font'].render('sus',True,(255,50,50))
                self.surface.blit(txt,(int(d['x'])-txt.get_width()//2,int(d['y'])-rh//2-30))
            self.eyeLx_next=self.eyeLx_default+int((d['x']-self.screen_width//2)*0.18)
            self.eyeRx_next=self.eyeRx_default+int((d['x']-self.screen_width//2)*0.18)
            self.eyeLy_next=self.eyeLy_default+int((d['y']-self.screen_height//2)*0.12)
            self.eyeRy_next=self.eyeRy_default+int((d['y']-self.screen_height//2)*0.12)
            if d['x']>self.screen_width+120:return False
        else:
            return False
        return True

