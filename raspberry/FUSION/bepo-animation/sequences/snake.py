"""
sequences/snake.py — FUSION / RoboEyes
Animazione idle SEQ_SNAKE. Mixin con un solo metodo: _run_snake_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class SnakeSequenceMixin:
    def _run_snake_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        d=self.seq_data
        if 'snake' not in d:
            cell=24
            d['cell']=cell
            d['cols']=self.screen_width//cell
            d['rows']=self.screen_height//cell
            cx,cy=d['cols']//2,d['rows']//2
            d['snake']=[(cx,cy),(cx-1,cy),(cx-2,cy)]
            d['dir']=(1,0)
            d['food']=(random.randint(2,d['cols']-3),random.randint(2,d['rows']-3))
            d['move_timer']=0.0
            d['move_interval']=0.13
            d['score']=0
            d['alive']=True
            d['font']=pygame.font.SysFont('monospace',22,bold=True)
        if elapsed<8.0 and d['alive']:
            d['move_timer']+=self.frame_interval/1000.0
            if d['move_timer']>=d['move_interval']:
                d['move_timer']=0.0
                hx,hy=d['snake'][0]
                dx2,dy2=d['dir']
                fx,fy=d['food']
                if random.random()<0.15:
                    choices=[(1,0),(-1,0),(0,1),(0,-1)]
                    choices=[c for c in choices if c!=(-dx2,-dy2)]
                    d['dir']=random.choice(choices)
                else:
                    wx=fx-hx;wy=fy-hy
                    if abs(wx)>=abs(wy):
                        nd=(1 if wx>0 else -1,0)
                    else:
                        nd=(0,1 if wy>0 else -1)
                    if nd!=(-dx2,-dy2):d['dir']=nd
                dx2,dy2=d['dir']
                nx,ny=hx+dx2,hy+dy2
                nx%=d['cols'];ny%=d['rows']
                if (nx,ny) in d['snake'][1:]:
                    d['alive']=False
                else:
                    d['snake'].insert(0,(nx,ny))
                    if (nx,ny)==d['food']:
                        d['score']+=1
                        d['food']=(random.randint(2,d['cols']-3),random.randint(2,d['rows']-3))
                        d['move_interval']=max(0.06,d['move_interval']-0.004)
                    else:
                        d['snake'].pop()
            cell=d['cell']
            for gx in range(0,self.screen_width,cell):
                pygame.draw.line(self.surface,(18,18,18),(gx,0),(gx,self.screen_height))
            for gy in range(0,self.screen_height,cell):
                pygame.draw.line(self.surface,(18,18,18),(0,gy),(self.screen_width,gy))
            if int(elapsed*4)%2==0:
                fx,fy=d['food']
                pygame.draw.rect(self.surface,(255,60,60),(fx*cell+3,fy*cell+3,cell-6,cell-6),border_radius=4)
            for i,(sx,sy) in enumerate(d['snake']):
                green=max(80,220-i*4)
                col=(0,green,0) if i>0 else (180,255,180)
                pygame.draw.rect(self.surface,col,(sx*cell+2,sy*cell+2,cell-4,cell-4),border_radius=5)
            txt=d['font'].render(f'SCORE: {d["score"]}',True,(0,200,0))
            self.surface.blit(txt,(10,8))
            hx,hy=d['snake'][0]
            self.eyeLx_next=self.eyeLx_default+int((hx*cell-self.screen_width//2)*0.18)
            self.eyeRx_next=self.eyeRx_default+int((hx*cell-self.screen_width//2)*0.18)
            self.eyeLy_next=self.eyeLy_default+int((hy*cell-self.screen_height//2)*0.12)
            self.eyeRy_next=self.eyeRy_default+int((hy*cell-self.screen_height//2)*0.12)
        elif not d.get('alive',True):
            if 'font' in d:
                txt=d['font'].render(f'GAME OVER  SCORE:{d["score"]}',True,(255,80,80))
                self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,self.screen_height//2-16))
            if elapsed>6.5:return False
        else:
            return False
        return True

