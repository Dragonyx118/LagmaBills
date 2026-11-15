"""
sequences/weather.py — FUSION / RoboEyes
Animazione idle SEQ_WEATHER. Mixin con un solo metodo: _run_weather_sequence.
Per aggiungere una nuova animazione: copia questo file come modello,
cambia nome classe/metodo e registrala in sequences/__init__.py.
"""

import math
import random
import pygame
from weather import get_gps_weather


class WeatherSequenceMixin:
    def _run_weather_sequence(self, ct):
        elapsed = (ct - self.seq_timer) / 1000.0
        d=self.seq_data
        if 'font' not in d:
            d['font_big']=pygame.font.SysFont('monospace',80,bold=True)
            d['font']=pygame.font.SysFont('monospace',28)
            d['font_sm']=pygame.font.SysFont('monospace',20)
            d['wx']=None
            d['loading']=True
            def fetch_weather():
                result=get_gps_weather()
                d['wx']=result
                d['loading']=False
            import threading as _t
            _t.Thread(target=fetch_weather,daemon=True).start()
            d['drops']=[(random.randint(0,1024),random.randint(0,600),random.uniform(200,400)) for _ in range(60)]
            d['flakes']=[(random.randint(0,1024),random.randint(0,600),random.uniform(60,120),random.uniform(0,math.pi*2)) for _ in range(50)]
            d['font_loading']=pygame.font.SysFont('monospace',36,bold=True)
        if elapsed<7.0:
            if d['loading'] or d['wx'] is None:
                txt=d['font_loading'].render('Fetching weather...',True,(100,180,100))
                self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,self.screen_height//2-20))
                dots='.'*((int(elapsed*3)%3)+1)
                txt2=d['font_loading'].render(dots,True,(80,150,80))
                self.surface.blit(txt2,(self.screen_width//2-20,self.screen_height//2+30))
                return True
            label,temp,col,kind,city=d['wx']
            dt2=self.frame_interval/1000.0
            bg=pygame.Surface((self.screen_width,self.screen_height),pygame.SRCALPHA)
            bg.fill((col[0]//6,col[1]//6,col[2]//6,180))
            self.surface.blit(bg,(0,0))
            if kind=='sunny':
                cx2,cy2=820,120
                glow=int(180+40*abs(math.sin(elapsed*2)))
                pygame.draw.circle(self.surface,(glow,glow,0),(cx2,cy2),55)
                pygame.draw.circle(self.surface,(255,255,100),(cx2,cy2),42)
                for i in range(12):
                    a=i*math.pi/6+elapsed*0.3
                    x1=cx2+int(math.cos(a)*50);y1=cy2+int(math.sin(a)*50)
                    x2=cx2+int(math.cos(a)*72);y2=cy2+int(math.sin(a)*72)
                    pygame.draw.line(self.surface,(255,220,0),(x1,y1),(x2,y2),3)
                self.happy=True
            elif kind=='rain':
                for i,(rx,ry,spd) in enumerate(d['drops']):
                    ny2=ry+spd*dt2
                    if ny2>self.screen_height:ny2=0;rx=random.randint(0,self.screen_width)
                    d['drops'][i]=(rx,ny2,spd)
                    pygame.draw.line(self.surface,(100,160,255),(int(rx),int(ry)),(int(rx)-2,int(ny2)+14),2)
                self.scared=True
            elif kind=='cloud':
                for ci in range(3):
                    ox=int(math.sin(elapsed*0.3+ci)*30)+ci*280+100
                    oy=80+ci*30
                    for bx2,by2,br2 in [(-40,0,38),(0,-20,48),(45,0,38),(80,8,30),(-70,10,28)]:
                        pygame.draw.circle(self.surface,(210,210,210),(ox+bx2,oy+by2),br2)
            elif kind=='storm':
                for i,(rx,ry,spd) in enumerate(d['drops']):
                    ny2=ry+spd*1.8*dt2
                    if ny2>self.screen_height:ny2=0;rx=random.randint(0,self.screen_width)
                    d['drops'][i]=(rx,ny2,spd)
                    pygame.draw.line(self.surface,(120,80,200),(int(rx),int(ry)),(int(rx)-5,int(ny2)+18),2)
                if int(elapsed*3)%9==0:
                    lx=random.randint(200,800)
                    pts=[(lx,0),(lx-20,120),(lx+10,120),(lx-30,280)]
                    pygame.draw.lines(self.surface,(255,255,100),False,pts,4)
                self.scared=True
            elif kind=='snow':
                for i,(fx,fy,spd,rot) in enumerate(d['flakes']):
                    ny2=fy+spd*dt2
                    nx2=fx+math.sin(elapsed+rot)*0.8
                    if ny2>self.screen_height:ny2=0;nx2=random.randint(0,self.screen_width)
                    d['flakes'][i]=(nx2,ny2,spd,rot)
                    pygame.draw.circle(self.surface,(220,240,255),(int(nx2),int(ny2)),4)
                self.surprised=True
            txt=d['font_big'].render(temp,True,col)
            self.surface.blit(txt,(60,self.screen_height//2-60))
            txt2=d['font'].render(label,True,(220,220,220))
            self.surface.blit(txt2,(60,self.screen_height//2+40))
            city_txt=d['font_sm'].render(f'{city}  |  LIVE FORECAST',True,(120,120,120))
            self.surface.blit(city_txt,(60,self.screen_height-36))
        else:
            self.happy=False;self.scared=False;self.surprised=False;return False
        return True

