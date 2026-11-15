"""
sequences/typewriter.py — FUSION / RoboEyes
Animazione idle SEQ_TYPEWRITER. Mixin con un solo metodo: _run_typewriter_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class TypewriterSequenceMixin:
    def _run_typewriter_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        messages=["BORED...","CALCULATING...","NOTHING TO DO","SEND HELP PLZ","ERROR 404:","FUN NOT FOUND","> _"]
        if 'font' not in self.seq_data:
            self.seq_data['font']=pygame.font.SysFont('monospace',32,bold=True)
            self.seq_data['full']=' '.join(messages)
            self.seq_data['cursor_timer']=0.0
        font=self.seq_data['font']
        full=self.seq_data['full']
        chars_per_sec=12
        nchars=min(len(full),int(elapsed*chars_per_sec))
        visible=full[:nchars]
        self.seq_data['cursor_timer']+=self.frame_interval/1000.0
        cursor='|' if int(self.seq_data['cursor_timer']*2)%2==0 else ' '
        line_w=self.screen_width-80
        words=visible+cursor
        lines=[]
        current=''
        for ch in words:
            test=current+ch
            if font.size(test)[0]>line_w:
                lines.append(current);current=ch
            else:
                current=test
        lines.append(current)
        for li,line in enumerate(lines[-4:]):
            txt=font.render(line,True,(0,220,0))
            self.surface.blit(txt,(40,self.eyeLy_default+160+li*38))
        pygame.draw.rect(self.surface,(0,80,0),(34,self.eyeLy_default+150,self.screen_width-68,4*38+16),2,border_radius=4)
        self.eyeLy_next=self.eyeLy_default+20;self.eyeRy_next=self.eyeRy_default+20
        self.eyeLheight_next=int(self.eyeLheight_default*0.55);self.eyeRheight_next=int(self.eyeRheight_default*0.55)
        if elapsed>8.0:return False
        return True

