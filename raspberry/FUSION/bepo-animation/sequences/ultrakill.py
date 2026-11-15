"""
sequences/ultrakill.py — FUSION / RoboEyes
Animazione idle SEQ_ULTRAKILL. Mixin con un solo metodo: _run_ultrakill_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class UltrakillSequenceMixin:
    def _run_ultrakill_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        d=self.seq_data
        if 'font' not in d:
            d['font_mono']=pygame.font.SysFont('monospace',22,bold=False)
            d['font_big']=pygame.font.SysFont('monospace',38,bold=True)
            d['font_xl']=pygame.font.SysFont('monospace',52,bold=True)
            d['scanline_offset']=0
            d['static_lines']=[
                (0.3,  "STATUS UPDATE:",         (200,200,200), 'big'),
                (1.0,  "MACHINE ID:    LagmaBills",(180,180,180),'normal'),
                (1.6,  "OBJECTIVE:     SAVE THE WORLD",(180,180,180),'normal'),
                (2.2,  "LOCATION:      APPROACHING HELL",(180,180,180),'normal'),
                (2.8,  "STATUS:        OPERATIONAL",(180,180,180),'normal'),
            ]
            d['red_lines']=[
                (4.0, "MANKIND IS DEAD.", (200,0,0)),
                (5.0, "BLOOD IS FUEL.",   (220,0,0)),
                (6.0, "HELL IS FULL.",    (240,0,0)),
            ]
            d['glitch_timer']=0.0
        if elapsed<8.5:
            dt2=self.frame_interval/1000.0
            d['glitch_timer']+=dt2
            for sy in range(0,self.screen_height,4):
                pygame.draw.rect(self.surface,(0,0,0,40),(0,sy,self.screen_width,2))
            base_x=160;base_y=80
            for t,line,col,style in d['static_lines']:
                if elapsed>=t:
                    font=d['font_big'] if style=='big' else d['font_mono']
                    age=elapsed-t
                    off_x=random.randint(-2,2) if age<0.15 else 0
                    txt=font.render(line,True,col)
                    self.surface.blit(txt,(base_x+off_x,base_y+d['static_lines'].index((t,line,col,style))*36))
            red_base_y=base_y+len(d['static_lines'])*36+30
            for i,(t,line,col) in enumerate(d['red_lines']):
                if elapsed>=t:
                    age=elapsed-t
                    if age<0.3:
                        flash=int(255*(1-age/0.3))
                        flash_surf=pygame.Surface((self.screen_width,60),pygame.SRCALPHA)
                        flash_surf.fill((flash//3,0,0,flash//2))
                        self.surface.blit(flash_surf,(0,red_base_y+i*60-5))
                        off_x=random.randint(-8,8)
                    else:
                        off_x=0
                    pulse=0.85+0.15*abs(math.sin(elapsed*4+i))
                    r=int(col[0]*pulse);g=0;b=0
                    txt=d['font_xl'].render(line,True,(r,g,b))
                    self.surface.blit(txt,(base_x+off_x,red_base_y+i*60))
            if elapsed<3.5 and int(elapsed*2)%2==0:
                shown=sum(1 for t,_,_,_ in d['static_lines'] if elapsed>=t)
                cur=d['font_mono'].render('█',True,(0,200,0))
                self.surface.blit(cur,(base_x,base_y+(shown)*36))
            if elapsed<3.5:
                self.thinking=True
                self.eyeLheight_next=int(self.eyeLheight_default*0.5)
                self.eyeRheight_next=int(self.eyeRheight_default*0.5)
            elif elapsed<4.3:
                self.thinking=False;self.surprised=True
            elif elapsed>=6.0:
                self.surprised=False;self.scared=True
        else:
            self.thinking=False;self.surprised=False;self.scared=False;return False
        return True

