"""
sequences/slot.py — FUSION / RoboEyes
Animazione idle SEQ_SLOT. Mixin con un solo metodo: _run_slot_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class SlotSequenceMixin:
    def _run_slot_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        d=self.seq_data
        sym_chars=list(range(7))
        if 'font' not in d:
            d['font']=pygame.font.SysFont('monospace',64,bold=True)
            d['imgs']=self._get_slot_imgs()
            d['font_sm']=pygame.font.SysFont('monospace',26,bold=True)
            d['font_big']=pygame.font.SysFont('monospace',52,bold=True)
            d['reels']=[0.0,0.0,0.0]
            d['speeds']=[18.0,14.0,10.0]
            d['stopped']=[False,False,False]
            d['stop_times']=[1.8,2.8,3.8]
            d['result']=[0,0,0]
        if elapsed<6.5:
            dt2=self.frame_interval/1000.0
            machine_x=self.screen_width//2-220;machine_y=120
            pygame.draw.rect(self.surface,(60,20,80),(machine_x-20,machine_y-20,480,300),border_radius=20)
            pygame.draw.rect(self.surface,(100,40,130),(machine_x-20,machine_y-20,480,300),border_radius=20,width=5)
            title=d['font_sm'].render('* LUCKY ROBOT *',True,(255,220,0))
            self.surface.blit(title,(self.screen_width//2-title.get_width()//2,machine_y-16))
            for ri in range(3):
                rx=machine_x+ri*150+10
                ry=machine_y+30
                pygame.draw.rect(self.surface,(20,10,30),(rx,ry,120,180),border_radius=8)
                pygame.draw.rect(self.surface,(200,180,220),(rx,ry,120,180),border_radius=8,width=3)
                if not d['stopped'][ri]:
                    d['reels'][ri]+=d['speeds'][ri]*dt2
                if not d['stopped'][ri] and elapsed>=d['stop_times'][ri]:
                    d['stopped'][ri]=True
                    d['result'][ri]=int(d['reels'][ri])%len(sym_chars)
                idx=int(d['reels'][ri])%len(sym_chars)
                sym=sym_chars[idx]
                imgs=d['imgs']
                img_main=imgs[sym]
                if not d['stopped'][ri]:
                    img_main=img_main.copy(); img_main.set_alpha(180)
                self.surface.blit(img_main,(rx+15,ry+45))
                for yo,prev_delta in [(-55,-1),(100,1)]:
                    prev_idx=(idx+prev_delta)%len(sym_chars)
                    small=pygame.transform.smoothscale(imgs[sym_chars[prev_idx]],(60,60))
                    small.set_alpha(80)
                    self.surface.blit(small,(rx+30,ry+90+yo))
            if all(d['stopped']):
                r=d['result']
                if r[0]==r[1]==r[2]:
                    res=d['font_big'].render('JACKPOT!!!',True,(255,220,0))
                    self.surprised=True
                    for _ in range(10):
                        sx=random.randint(0,self.screen_width);sy=random.randint(0,120)
                        pygame.draw.circle(self.surface,(random.randint(150,255),random.randint(150,255),0),(sx,sy),random.randint(3,8))
                elif r[0]==r[1] or r[1]==r[2] or r[0]==r[2]:
                    res=d['font_big'].render('SMALL WIN!',True,(100,255,100))
                    self.happy=True
                else:
                    res=d['font_big'].render('NOPE :(',True,(180,80,80))
                    self.sad=True
                self.surface.blit(res,(self.screen_width//2-res.get_width()//2,machine_y+290))
            if not all(d['stopped']):
                bounce=int(math.sin(elapsed*12)*8)
                self.eyeLy_next=self.eyeLy_default+bounce
                self.eyeRy_next=self.eyeRy_default-bounce
        else:
            self.surprised=False;self.happy=False;self.sad=False;return False
        return True

