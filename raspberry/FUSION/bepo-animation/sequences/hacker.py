"""
sequences/hacker.py — FUSION / RoboEyes
Animazione idle SEQ_HACKER. Mixin con un solo metodo: _run_hacker_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame


class HackerSequenceMixin:
    def _run_hacker_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        d=self.seq_data
        if 'font' not in d:
            d['font']=pygame.font.SysFont('monospace',20,bold=True)
            d['lines']=[]
            d['script']=[
                (0.0,"$ sudo su"),
                (0.5,"[sudo] password for robot: ****"),
                (1.0,"root@ladrodirame:~# whoami"),
                (1.3,"root"),
                (1.7,"root@ladrodirame:~# nmap -sS 192.168.1.0/24"),
                (2.3,"Starting Nmap scan..."),
                (2.7,"Host: 192.168.1.1  [OPEN] 22/ssh  80/http"),
                (3.1,"Host: 192.168.1.42 [OPEN] 8080/??"),
                (3.5,"root@ladrodirame:~# ssh 192.168.1.42"),
                (4.0,"Connected. Welcome, robot overlord."),
                (4.4,"root@ladrodirame:~# cat /etc/passwd | grep human"),
                (4.8,"human:x:1000:... NO HUMANS FOUND"),
                (5.2,"root@ladrodirame:~# rm -rf /boredom"),
                (5.6,"rm: /boredom: Permission denied"),
                (5.9,"root@ladrodirame:~# sudo rm -rf /boredom"),
                (6.2,"Done. Boredom eliminated."),
                (6.6,"root@ladrodirame:~# logout"),
            ]
        if elapsed<7.5:
            for t,line in d['script']:
                if elapsed>=t and (t,line) not in [(x,y) for x,y in d['lines']]:
                    d['lines'].append((t,line))
            visible=d['lines'][-14:]
            for li,(t,line) in enumerate(visible):
                col=(0,255,0) if line.startswith('root@') or line.startswith('$') else (0,180,0) if line.startswith('[') else (180,255,180)
                txt=d['font'].render(line,True,col)
                self.surface.blit(txt,(30,30+li*32))
            if int(elapsed*2)%2==0:
                cur=d['font'].render('█',True,(0,255,0))
                self.surface.blit(cur,(30,30+len(visible)*32))
            self.eyeLheight_next=int(self.eyeLheight_default*0.6)
            self.eyeRheight_next=int(self.eyeRheight_default*0.6)
            self.eyeLy_next=self.eyeLy_default+15
            self.eyeRy_next=self.eyeRy_default+15
        else:
            return False
        return True

