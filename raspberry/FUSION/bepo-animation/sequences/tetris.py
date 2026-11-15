"""
sequences/tetris.py — FUSION / RoboEyes
Animazione idle SEQ_TETRIS. Mixin con un solo metodo: _run_tetris_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class TetrisSequenceMixin:
    def _run_tetris_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        if 'blocks' not in self.seq_data:
            colors=[(0,240,240),(240,240,0),(160,0,240),(0,240,0),(240,0,0),(0,0,240),(240,160,0)]
            self.seq_data['blocks']=[]
            self.seq_data['landed']=[]
            self.seq_data['colors']=colors
            self.seq_data['spawn']=0.0
            self.seq_data['score']=0
            self.seq_data['font']=pygame.font.SysFont('monospace',26,bold=True)
            bsize=36
            self.seq_data['bsize']=bsize
            self.seq_data['cols_n']=self.screen_width//bsize
            self.seq_data['rows_n']=self.screen_height//bsize
        if elapsed<7.0:
            d=self.seq_data
            bsize=d['bsize']
            dt=self.frame_interval/1000.0
            if elapsed-d['spawn']>0.7:
                d['spawn']=elapsed
                col=random.choice(d['colors'])
                shape=random.choice(['I','L','S','O'])
                bx=random.randint(1,d['cols_n']-4)*bsize
                d['blocks'].append({'x':float(bx),'y':float(-bsize),'col':col,'shape':shape,'vy':120+random.randint(0,60),'landed':False})
            new_blocks=[]
            for b in d['blocks']:
                b['y']+=b['vy']*dt
                if b['y']>=self.screen_height-bsize:
                    b['y']=self.screen_height-bsize
                    gx=int(b['x'])//bsize
                    gy=int(b['y'])//bsize
                    d['landed'].append({'gx':gx,'gy':gy,'col':b['col'],'shape':b['shape']})
                else:
                    new_blocks.append(b)
            d['blocks']=new_blocks
            from collections import defaultdict
            row_count=defaultdict(int)
            for lb in d['landed']:
                w=4 if lb['shape']=='I' else 2 if lb['shape'] in ('O','L','S') else 2
                for dx in range(w):
                    row_count[lb['gy']]+=1
            threshold=d['cols_n']//2
            full_rows=[ry for ry,cnt in row_count.items() if cnt>=threshold]
            if full_rows:
                d['score']+=len(full_rows)
                d['landed']=[lb for lb in d['landed'] if lb['gy'] not in full_rows]
                for ry in full_rows:
                    pygame.draw.rect(self.surface,(255,255,0),(0,ry*bsize,self.screen_width,bsize))
            for lb in d['landed']:
                x,y=lb['gx']*bsize,lb['gy']*bsize
                col=lb['col']
                pygame.draw.rect(self.surface,col,(x+1,y+1,bsize-2,bsize-2),border_radius=4)
            for b in d['blocks']:
                x,y=int(b['x']),int(b['y'])
                col=b['col']
                if b['shape']=='I':
                    pygame.draw.rect(self.surface,col,(x,y,bsize*4,bsize-2),border_radius=4)
                elif b['shape']=='O':
                    pygame.draw.rect(self.surface,col,(x,y,bsize*2,bsize*2-2),border_radius=4)
                elif b['shape']=='L':
                    pygame.draw.rect(self.surface,col,(x,y,bsize-2,bsize*2),border_radius=4)
                    pygame.draw.rect(self.surface,col,(x,y+bsize,bsize*2-2,bsize-2),border_radius=4)
                else:
                    pygame.draw.rect(self.surface,col,(x+bsize//2,y,bsize+bsize//2,bsize-2),border_radius=4)
                    pygame.draw.rect(self.surface,col,(x,y+bsize,bsize+bsize//2,bsize-2),border_radius=4)
            txt=d['font'].render(f'LINES: {d["score"]}',True,(200,200,200))
            self.surface.blit(txt,(10,8))
            self.eyeLy_next=self.eyeLy_default+25
            self.eyeRy_next=self.eyeRy_default+25
        else:
            return False
        return True

