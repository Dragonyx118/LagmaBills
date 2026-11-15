"""
sequences/matrix.py — FUSION / RoboEyes
Animazione idle SEQ_MATRIX. Mixin con un solo metodo: _run_matrix_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class MatrixSequenceMixin:
    def _run_matrix_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if 'cols' not in self.seq_data:
            ncols=32
            self.seq_data['cols']=[random.randint(0,self.screen_height//18) for _ in range(ncols)]
            self.seq_data['ncols']=ncols
        if elapsed<5.0:
            if 'font' not in self.seq_data:
                self.seq_data['font']=pygame.font.SysFont('monospace',18,bold=True)
            font=self.seq_data['font']
            cols=self.seq_data['cols'];ncols=self.seq_data['ncols']
            col_w=self.screen_width//ncols
            for ci in range(ncols):
                nchars=random.randint(1,4)
                for j in range(nchars):
                    ch=chr(random.choice(list(range(0x30A0,0x30FF))+list(range(48,58))))
                    brightness=random.randint(80,255)
                    col_color=(0,brightness,0)
                    y=((cols[ci]+j)%((self.screen_height//18)+1))*18
                    txt=font.render(ch,True,col_color)
                    self.surface.blit(txt,(ci*col_w,y))
                cols[ci]=(cols[ci]+1)%((self.screen_height//18)+1)
            self.eyeLy_next=self.eyeLy_default;self.eyeRy_next=self.eyeRy_default
            self.eyeLx_next=self.eyeLx_default;self.eyeRx_next=self.eyeRx_default
        else:
            return False
        return True

