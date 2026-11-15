"""
sequences/reboot.py — FUSION / RoboEyes
Animazione idle SEQ_REBOOT. Mixin con un solo metodo: _run_reboot_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class RebootSequenceMixin:
    def _run_reboot_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if 'font' not in self.seq_data:
            self.seq_data['font']=pygame.font.SysFont('monospace',22,bold=False)
            self.seq_data['font_big']=pygame.font.SysFont('monospace',48,bold=True)
            self.seq_data['lines']=[
                (0.2,"Initiating shutdown sequence..."),
                (0.6,"Saving state to disk..."),
                (1.1,"Flushing buffers..."),
                (1.5,"OK"),
                (1.9,"Stopping services..."),
                (2.4,"eye_animator: stopped"),
                (2.7,"mood_engine: stopped"),
                (3.1,"Unmounting filesystems..."),
                (3.5,"OK"),
                (3.8,"See you soon :)"),
            ]
        font=self.seq_data['font']
        font_big=self.seq_data['font_big']
        if elapsed<4.5:
            visible_lines=[(t,l) for t,l in self.seq_data['lines'] if elapsed>=t]
            for li,(t,line) in enumerate(visible_lines[-10:]):
                col=(0,200,0) if line=='OK' else (180,180,180)
                txt=font.render(line,True,col)
                self.surface.blit(txt,(40,40+li*28))
            if visible_lines and int(elapsed*2)%2==0:
                cur=font.render('█',True,(0,200,0))
                self.surface.blit(cur,(40+font.size(visible_lines[-1][1])[0],40+(len(visible_lines)-1)*28))
            t_close=max(0,(elapsed-3.0)/1.5)
            self.eyeLheight_next=max(1,int(self.eyeLheight_default*(1-t_close)))
            self.eyeRheight_next=max(1,int(self.eyeRheight_default*(1-t_close)))
        elif elapsed<5.5:
            self.eyeLheight_next=1;self.eyeRheight_next=1
        elif elapsed<6.5:
            t=(elapsed-5.5)/1.0
            txt=font_big.render('BOOTING...',True,(0,180,0))
            self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,200))
            pygame.draw.rect(self.surface,(40,40,40),(200,320,624,28),border_radius=14)
            pygame.draw.rect(self.surface,(0,200,0),(200,320,int(624*t),28),border_radius=14)
            self.eyeLheight_next=int(self.eyeLheight_default*t)
            self.eyeRheight_next=int(self.eyeRheight_default*t)
        elif elapsed<7.5:
            self.happy=True
            txt=font_big.render('HELLO WORLD :)',True,(0,255,0))
            self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,240))
        else:
            self.happy=False;return False
        return True

