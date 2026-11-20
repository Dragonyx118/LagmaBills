"""
eyes/drawing.py — FUSION / RoboEyes
Mixin con tutto il rendering: helper di disegno riutilizzati dalle
sequenze (zzz, farfalla, stelle), le "bolle" per i mood speciali
(thinking/talking/furious/idea) e drawEyes(), il metodo principale
chiamato ogni frame da update() (eyes/state.py).
"""

import math
import random
import pygame

from constants import MAINCOLOR, BGCOLOR


class DrawingMixin:
    def _draw_zzz(self, alpha, offset_y=0):
        font_sizes=[28,38,50]
        positions=[(self.screen_width//2+60, self.eyeLy_default-60+offset_y),
                   (self.screen_width//2+90, self.eyeLy_default-110+offset_y),
                   (self.screen_width//2+70, self.eyeLy_default-165+offset_y)]
        for i,(fx,fy) in enumerate(positions):
            size=font_sizes[i]
            a=int(alpha*min(1.0,(i+1)*0.4)*255)
            col=(200,200,255,a)
            s=pygame.Surface((size,size),pygame.SRCALPHA)
            pygame.draw.line(s,col,(0,0),(size,0),3)
            pygame.draw.line(s,col,(size,0),(0,size),3)
            pygame.draw.line(s,col,(0,size),(size,size),3)
            self.surface.blit(s,(fx,fy))

    def _draw_butterfly(self, x, y, phase, size=1.0):
        s=int(40*size)
        col=(255,120,200);col2=(255,200,80)
        wing_flap=int(math.sin(phase*8)*10)
        pygame.draw.ellipse(self.surface,col,(x-s-int(s*0.3),y-s//2+wing_flap,s,s//2+10))
        pygame.draw.ellipse(self.surface,col,(x+int(s*0.3),y-s//2+wing_flap,s,s//2+10))
        pygame.draw.ellipse(self.surface,col2,(x-s+5,y+5-wing_flap,int(s*0.7),s//3))
        pygame.draw.ellipse(self.surface,col2,(x+int(s*0.3),y+5-wing_flap,int(s*0.7),s//3))
        pygame.draw.ellipse(self.surface,(80,40,10),(x-4,y-s//2,8,s))
        pygame.draw.line(self.surface,(80,40,10),(x,y-s//2),(x-10,y-s//2-15),2)
        pygame.draw.line(self.surface,(80,40,10),(x,y-s//2),(x+10,y-s//2-15),2)
        pygame.draw.circle(self.surface,(255,80,80),(x-10,y-s//2-15),3)
        pygame.draw.circle(self.surface,(255,80,80),(x+10,y-s//2-15),3)

    def _draw_stars(self, phase):
        star_pos=[(100,80),(900,60),(200,500),(800,480),(500,50),(150,300),(850,350)]
        for i,(sx,sy) in enumerate(star_pos):
            flicker=abs(math.sin(phase*2+i*1.3))
            r=int(3+flicker*5)
            brightness=int(150+flicker*105)
            col=(brightness,brightness,int(brightness*0.8))
            pygame.draw.circle(self.surface,col,(sx,sy),r)
            for angle in [0,math.pi/2,math.pi,math.pi*3/2]:
                ex=sx+int(math.cos(angle)*(r+4)*flicker)
                ey=sy+int(math.sin(angle)*(r+4)*flicker)
                pygame.draw.line(self.surface,col,(sx,sy),(ex,ey),1)


    def draw_thinking_bubble(self, ct):
        elapsed=(ct-self.thinking_timer)/1000.0
        alpha=int(min(1.0,elapsed/0.5)*255)
        cx=self.screen_width//2;base_y=self.eyeLy-30
        for i,r in enumerate([6,9,13]):
            dot_x=cx-40+i*30;dot_y=base_y-15-i*18
            s=pygame.Surface((r*2,r*2),pygame.SRCALPHA)
            pygame.draw.circle(s,(255,255,255,alpha),(r,r),r)
            self.surface.blit(s,(dot_x-r,dot_y-r))
        cloud_y=base_y-105;cloud_cx=cx
        bubbles=[(cloud_cx-55,cloud_y+10,28),(cloud_cx-22,cloud_y-18,36),
                 (cloud_cx+18,cloud_y-22,38),(cloud_cx+52,cloud_y-5,28),
                 (cloud_cx+66,cloud_y+18,20),(cloud_cx-68,cloud_y+18,20)]
        for bx,by,br in bubbles:
            s=pygame.Surface((br*2+4,br*2+4),pygame.SRCALPHA)
            pygame.draw.circle(s,(255,255,255,alpha),(br+2,br+2),br)
            self.surface.blit(s,(bx-br-2,by-br-2))
        fill=pygame.Surface((150,52),pygame.SRCALPHA);fill.fill((255,255,255,alpha))
        self.surface.blit(fill,(cloud_cx-75,cloud_y-18))
        for i in range(3):
            dx=cloud_cx-24+i*24;dy=cloud_y+8
            ds=pygame.Surface((14,14),pygame.SRCALPHA)
            pygame.draw.circle(ds,(60,60,60,alpha),(7,7),7)
            self.surface.blit(ds,(dx-7,dy-7))

    def draw_talking_antenna(self, ct):
        self.talking_phase+=0.2
        cx=self.screen_width//2;base_x=cx+80;base_y=self.eyeLy
        ant_top_x=base_x+int(math.sin(self.talking_phase)*14)
        ant_top_y=base_y-75
        pygame.draw.line(self.surface,(255,255,255),(base_x,base_y),(ant_top_x,ant_top_y),5)
        pygame.draw.circle(self.surface,(0,0,0),(ant_top_x,ant_top_y),12)
        pygame.draw.circle(self.surface,(255,220,0),(ant_top_x,ant_top_y),10)
        for r in [18,30,44]:
            a=max(0,180-r*3)
            s=pygame.Surface((r*2+4,r*2+4),pygame.SRCALPHA)
            pygame.draw.circle(s,(255,220,0,a),(r+2,r+2),r,2)
            self.surface.blit(s,(ant_top_x-r-2,ant_top_y-r-2))

    def draw_furious_symbol(self, ct):
        self.furious_phase+=0.12
        pulse=0.88+0.12*abs(math.sin(self.furious_phase*3))
        sx=int(self.eyeRx+self.eyeRwidth_current*0.55);sy=int(self.eyeRy-55)
        size=int(42*pulse);col=(210,25,25);thick=5
        rect1=pygame.Rect(sx-size,sy-size//2,size,size)
        rect2=pygame.Rect(sx,sy-size//2,size,size)
        rect3=pygame.Rect(sx-size//2,sy+4,size,size//2+4)
        for rect in [rect1,rect2,rect3]:
            pygame.draw.arc(self.surface,(0,0,0),rect.inflate(6,6),math.pi*0.05,math.pi*0.95,thick+4)
        pygame.draw.arc(self.surface,col,rect1,math.pi*0.05,math.pi*0.95,thick)
        pygame.draw.arc(self.surface,col,rect2,math.pi*0.05,math.pi*0.95,thick)
        pygame.draw.arc(self.surface,col,rect3,math.pi*1.05,math.pi*1.95,thick)

    def draw_idea_bulb(self, ct):
        self.idea_phase+=0.07
        brightness=min(1.0,(ct-self.idea_timer)/400.0)
        glow=int((0.75+0.25*abs(math.sin(self.idea_phase*2)))*255*brightness)
        col=(glow,glow,int(glow*0.2))
        cx=self.screen_width//2;bulb_x=cx;bulb_y=self.eyeLy-95
        for r in [52,40,30]:
            a=int((1-(r-30)/22.0)*70*brightness)
            s=pygame.Surface((r*2,r*2),pygame.SRCALPHA)
            pygame.draw.circle(s,(glow,glow,0,a),(r,r),r)
            self.surface.blit(s,(bulb_x-r,bulb_y-r))
        pygame.draw.circle(self.surface,(0,0,0),(bulb_x,bulb_y),32)
        pygame.draw.circle(self.surface,col,(bulb_x,bulb_y),28)
        pygame.draw.lines(self.surface,(255,200,0),False,
            [(bulb_x-7,bulb_y+8),(bulb_x-3,bulb_y),(bulb_x+4,bulb_y+7),(bulb_x+8,bulb_y-2)],2)
        for dy,w in [(26,28),(34,22),(40,16)]:
            pygame.draw.rect(self.surface,(160,160,160),(bulb_x-w//2,bulb_y+dy,w,6),border_radius=2)
        for i in range(8):
            angle=i*(math.pi/4)+self.idea_phase*0.4
            x1=bulb_x+int(math.cos(angle)*34);y1=bulb_y+int(math.sin(angle)*34)
            x2=bulb_x+int(math.cos(angle)*50);y2=bulb_y+int(math.sin(angle)*50)
            pygame.draw.line(self.surface,(glow,glow,0),(x1,y1),(x2,y2),2)


    def drawEyes(self):
        ct=pygame.time.get_ticks()
        if self.sleepy:
            elapsed=(ct-self.sleepy_timer)/1000.0
            v=abs(math.sin(elapsed*0.8))
            self.eyeLheight_next=max(1,int(self.eyeLheight_default*(1-v*0.85)))
            self.eyeRheight_next=max(1,int(self.eyeRheight_default*(1-v*0.85)))
        if self.bored:
            self.eyeLheight_next=self.eyeLheight_default//3
            self.eyeRheight_next=self.eyeRheight_default//3
            if ct-self.bored_blink_timer>6000:
                self.blink();self.bored_blink_timer=ct
        if self.dizzy:
            self.dizzy_angle+=0.08;off=55
            self.eyeLx_next=self.eyeLx_default+int(math.cos(self.dizzy_angle)*off)
            self.eyeLy_next=self.eyeLy_default+int(math.sin(self.dizzy_angle)*off)
            self.eyeRx_next=self.eyeRx_default+int(math.cos(-self.dizzy_angle)*off)
            self.eyeRy_next=self.eyeRy_default+int(math.sin(-self.dizzy_angle)*off)
        if self.confused2:
            self.eyeLy_next=self.eyeLy_default-30;self.eyeRy_next=self.eyeRy_default+30
            self.eyeLheight_next=self.eyeLheight_default;self.eyeRheight_next=int(self.eyeRheight_default*0.7)
        if self.waiting:
            self.waiting_pulse+=0.04
            pulse=0.85+0.15*abs(math.sin(self.waiting_pulse))
            self.eyeLheight_next=int(self.eyeLheight_default*0.75*pulse)
            self.eyeRheight_next=int(self.eyeRheight_default*0.75*pulse)
            cx=self.screen_width//2; by=self.eyeLy_default-50
            blink_alpha=int((0.4+0.6*abs(math.sin(self.waiting_pulse*1.5)))*255)
            ant_surf=pygame.Surface((14,14),pygame.SRCALPHA)
            pygame.draw.circle(ant_surf,(255,180,0,blink_alpha),(7,7),7)
            pygame.draw.line(self.surface,MAINCOLOR,(cx,self.eyeLy_default),(cx,by),4)
            self.surface.blit(ant_surf,(cx-7,by-7))
        if self.focused:
            brow_y=self.eyeLy-18
            pygame.draw.line(self.surface,MAINCOLOR,
                (self.eyeLx+10, brow_y),(self.eyeLx+self.eyeLwidth_current-10, brow_y),6)
            pygame.draw.line(self.surface,MAINCOLOR,
                (self.eyeRx+10, brow_y),(self.eyeRx+self.eyeRwidth_current-10, brow_y),6)
        if self.proud:
            elapsed_p=(ct-self.proud_timer)/1000.0
            shimmer=int(200+55*abs(math.sin(elapsed_p*3)))
            for ex,ew in [(self.eyeLx, self.eyeLwidth_current),(self.eyeRx, self.eyeRwidth_current)]:
                s=pygame.Surface((ew//3, 14),pygame.SRCALPHA)
                s.fill((shimmer,shimmer,shimmer,160))
                self.surface.blit(s,(ex+ew//4, self.eyeLy+12))
        if self.nervous:
            self.nervous_phase+=0.18
            jitter=int(math.sin(self.nervous_phase*7)*5)
            self.eyeLx+=jitter;self.eyeRx+=jitter
            if int(self.nervous_phase*3)%14==0:
                side=random.choice([-1,1])
                self.eyeLx_next=self.eyeLx_default+side*60
                self.eyeRx_next=self.eyeRx_default+side*60
        if self.curious:
            self.eyeLheight_offset=16 if self.eyeLx_next<=20 else 0
            self.eyeRheight_offset=16 if self.eyeRx_next>=self.screen_width-self.eyeRwidth_current-20 else 0
        else:
            self.eyeLheight_offset=0;self.eyeRheight_offset=0

        self.eyeLheight_current=(self.eyeLheight_current+self.eyeLheight_next+self.eyeLheight_offset)//2
        self.eyeLy+=(self.eyeLheight_default-self.eyeLheight_current)//2
        self.eyeLy-=self.eyeLheight_offset//2
        self.eyeRheight_current=(self.eyeRheight_current+self.eyeRheight_next+self.eyeRheight_offset)//2
        self.eyeRy+=(self.eyeRheight_default-self.eyeRheight_current)//2
        self.eyeRy-=self.eyeRheight_offset//2
        if self.eyeL_open and self.eyeLheight_current<=1+self.eyeLheight_offset:
            self.eyeLheight_next=self.eyeLheight_default
        if self.eyeR_open and self.eyeRheight_current<=1+self.eyeRheight_offset:
            self.eyeRheight_next=self.eyeRheight_default
        self.eyeLwidth_current=(self.eyeLwidth_current+self.eyeLwidth_next)//2
        self.eyeRwidth_current=(self.eyeRwidth_current+self.eyeRwidth_next)//2
        self.space_between_current=(self.space_between_current+self.space_between_next)//2
        self.eyeLx=(self.eyeLx+self.eyeLx_next)//2
        self.eyeLy=(self.eyeLy+self.eyeLy_next)//2
        self.eyeRx_next=self.eyeLx_next+self.eyeLwidth_current+self.space_between_current
        self.eyeRy_next=self.eyeLy_next
        if not self.dizzy:
            self.eyeRx=(self.eyeRx+self.eyeRx_next)//2
            self.eyeRy=(self.eyeRy+self.eyeRy_next)//2
        else:
            self.eyeRx=(self.eyeRx+int(self.eyeRx_next))//2
            self.eyeRy=(self.eyeRy+int(self.eyeRy_next))//2
        self.eyeLborder_radius_current=(self.eyeLborder_radius_current+self.eyeLborder_radius_next)//2
        self.eyeRborder_radius_current=(self.eyeRborder_radius_current+self.eyeRborder_radius_next)//2

        if self.autoblinker and ct>=self.blink_timer and not self.bored and not self.sleepy and self.sequence is None:
            self.blink()
            self.blink_timer=ct+self.blink_interval+random.randint(0,self.blink_interval_variation)
        if self.laugh:
            if self.laugh_toggle:
                self.setVFlicker(True,10);self.laugh_animation_timer=ct;self.laugh_toggle=False
            elif ct>=self.laugh_animation_timer+self.laugh_animation_duration:
                self.setVFlicker(False,0);self.laugh_toggle=True;self.laugh=False
        if self.confused_anim:
            if self.confused_toggle:
                self.setHFlicker(True,40);self.confused_animation_timer=ct;self.confused_toggle=False
            elif ct>=self.confused_animation_timer+self.confused_animation_duration:
                self.setHFlicker(False,0);self.confused_toggle=True;self.confused_anim=False
        if self.wink_left:
            elapsed=ct-self.wink_timer
            if elapsed<self.wink_duration//2:self.eyeLheight_next=1;self.eyeL_open=False
            elif elapsed<self.wink_duration:self.eyeLheight_next=self.eyeLheight_default;self.eyeL_open=True
            else:self.wink_left=False
        if self.wink_right:
            elapsed=ct-self.wink_timer
            if elapsed<self.wink_duration//2:self.eyeRheight_next=1;self.eyeR_open=False
            elif elapsed<self.wink_duration:self.eyeRheight_next=self.eyeRheight_default;self.eyeR_open=True
            else:self.wink_right=False
        if self.spin_anim:
            elapsed=(ct-self.spin_timer)/1000.0;angle=elapsed*4;off=60
            self.eyeLx_next=self.eyeLx_default+int(math.cos(angle)*off)
            self.eyeLy_next=self.eyeLy_default+int(math.sin(angle)*off)
            self.eyeRx_next=self.eyeRx_default+int(math.cos(angle+0.5)*off)
            self.eyeRy_next=self.eyeRy_default+int(math.sin(angle+0.5)*off)
            if ct-self.spin_timer>self.spin_duration:
                self.spin_anim=False;self.eyeLx_next=self.eyeLx_default;self.eyeLy_next=self.eyeLy_default
        if self.shake_anim:
            elapsed=(ct-self.shake_timer)/1000.0
            dx=int(math.sin(elapsed*40)*20*max(0,1-elapsed/0.5))
            self.eyeLx+=dx;self.eyeRx+=dx
            if ct-self.shake_timer>self.shake_duration:self.shake_anim=False
        if self.hearts_anim:
            elapsed=(ct-self.hearts_timer)/1000.0
            f=0.85+0.15*abs(math.sin(elapsed*6))
            self.eyeLwidth_next=int(self.eyeLwidth_default*f);self.eyeRwidth_next=int(self.eyeRwidth_default*f)
            if ct-self.hearts_timer>self.hearts_duration:
                self.hearts_anim=False;self.eyeLwidth_next=self.eyeLwidth_default;self.eyeRwidth_next=self.eyeRwidth_default
        if self.look_anim and self.look_targets:
            if ct-self.look_timer>400:
                self.look_timer=ct
                if self.look_idx<len(self.look_targets):
                    self.eyeLx_next,self.eyeLy_next=self.look_targets[self.look_idx];self.look_idx+=1
                else:
                    self.look_anim=False
        if self.idle and ct>=self.idle_animation_timer and not self.look_anim and not self.spin_anim and not self.dizzy and self.sequence is None:
            self.eyeLx_next=random.randint(0,self.getScreenConstraint_X())
            self.eyeLy_next=random.randint(0,self.getScreenConstraint_Y())
            self.idle_animation_timer=ct+self.idle_interval+random.randint(0,self.idle_interval_variation)
        if self.hFlicker:
            d=self.hFlicker_amplitude if self.hFlicker_alternate else -self.hFlicker_amplitude
            self.eyeLx+=d;self.eyeRx+=d;self.hFlicker_alternate=not self.hFlicker_alternate
        if self.vFlicker:
            d=self.vFlicker_amplitude if self.vFlicker_alternate else -self.vFlicker_amplitude
            self.eyeLy+=d;self.eyeRy+=d;self.vFlicker_alternate=not self.vFlicker_alternate
        if self.cyclops:
            self.eyeRwidth_current=0;self.eyeRheight_current=0;self.space_between_current=0

        self.clear_display()
        self.draw_eye(self.eyeLx,self.eyeLy,self.eyeLwidth_current,self.eyeLheight_current,self.eyeLborder_radius_current,MAINCOLOR)
        if not self.cyclops:
            self.draw_eye(self.eyeRx,self.eyeRy,self.eyeRwidth_current,self.eyeRheight_current,self.eyeRborder_radius_current,MAINCOLOR)

        if self.tired:self.eyelids_tired_height_next=self.eyeLheight_current//2;self.eyelids_angry_height_next=0
        else:self.eyelids_tired_height_next=0
        if self.angry or self.furious:self.eyelids_angry_height_next=self.eyeLheight_current//2;self.eyelids_tired_height_next=0
        else:self.eyelids_angry_height_next=0
        if self.happy or self.idea or self.smug:self.eyelids_happy_bottom_offset_next=self.eyeLheight_current//2
        else:self.eyelids_happy_bottom_offset_next=0
        if self.surprised:self.eyelids_surprised_top_offset_next=-(self.eyeLheight_current//3)
        else:self.eyelids_surprised_top_offset_next=0
        if self.sad:self.eyelids_sad_height_next=self.eyeLheight_current//3
        else:self.eyelids_sad_height_next=0

        self.eyelids_tired_height=(self.eyelids_tired_height+self.eyelids_tired_height_next)//2
        if not self.cyclops:
            pygame.draw.polygon(self.surface,BGCOLOR,[(self.eyeLx,self.eyeLy-1),(self.eyeLx+self.eyeLwidth_current,self.eyeLy-1),(self.eyeLx,self.eyeLy+self.eyelids_tired_height-1)])
            pygame.draw.polygon(self.surface,BGCOLOR,[(self.eyeRx,self.eyeRy-1),(self.eyeRx+self.eyeRwidth_current,self.eyeRy-1),(self.eyeRx+self.eyeRwidth_current,self.eyeRy+self.eyelids_tired_height-1)])
        self.eyelids_angry_height=(self.eyelids_angry_height+self.eyelids_angry_height_next)//2
        if not self.cyclops:
            pygame.draw.polygon(self.surface,BGCOLOR,[(self.eyeLx,self.eyeLy-1),(self.eyeLx+self.eyeLwidth_current,self.eyeLy-1),(self.eyeLx+self.eyeLwidth_current,self.eyeLy+self.eyelids_angry_height-1)])
            pygame.draw.polygon(self.surface,BGCOLOR,[(self.eyeRx,self.eyeRy-1),(self.eyeRx+self.eyeRwidth_current,self.eyeRy-1),(self.eyeRx,self.eyeRy+self.eyelids_angry_height-1)])
        self.eyelids_happy_bottom_offset=(self.eyelids_happy_bottom_offset+self.eyelids_happy_bottom_offset_next)//2
        pygame.draw.rect(self.surface,BGCOLOR,(self.eyeLx-2,(self.eyeLy+self.eyeLheight_current)-self.eyelids_happy_bottom_offset+2,self.eyeLwidth_current+4,self.eyeLheight_default))
        if not self.cyclops:
            pygame.draw.rect(self.surface,BGCOLOR,(self.eyeRx-2,(self.eyeRy+self.eyeRheight_current)-self.eyelids_happy_bottom_offset+2,self.eyeRwidth_current+4,self.eyeRheight_default))
        self.eyelids_surprised_top_offset=(self.eyelids_surprised_top_offset+self.eyelids_surprised_top_offset_next)//2
        self.eyelids_sad_height=(self.eyelids_sad_height+self.eyelids_sad_height_next)//2
        if self.surprised:
            self.eyeLborder_radius_next=30;self.eyeRborder_radius_next=30
            self.eyeLwidth_next=int(self.eyeLwidth_default*1.1);self.eyeRwidth_next=int(self.eyeRwidth_default*1.1)
            self.eyeLheight_next=int(self.eyeLheight_default*1.15);self.eyeRheight_next=int(self.eyeRheight_default*1.15)
        if self.scared:
            self.eyeLwidth_next=int(self.eyeLwidth_default*1.2);self.eyeRwidth_next=int(self.eyeRwidth_default*1.2)
            self.eyeLheight_next=int(self.eyeLheight_default*1.2);self.eyeRheight_next=int(self.eyeRheight_default*1.2)
        if self.love:
            self.eyelids_happy_bottom_offset_next=self.eyeLheight_current//3
            self.eyeLborder_radius_next=self.eyeLborder_radius_default//2
            self.eyeRborder_radius_next=self.eyeRborder_radius_default//2
        if self.sad:
            pygame.draw.polygon(self.surface,BGCOLOR,[(self.eyeLx,self.eyeLy-1),(self.eyeLx+self.eyeLwidth_current//2,self.eyeLy-1),(self.eyeLx,self.eyeLy+self.eyelids_sad_height-1)])
            pygame.draw.polygon(self.surface,BGCOLOR,[(self.eyeRx+self.eyeRwidth_current//2,self.eyeRy-1),(self.eyeRx+self.eyeRwidth_current,self.eyeRy-1),(self.eyeRx+self.eyeRwidth_current,self.eyeRy+self.eyelids_sad_height-1)])
        if self.smug:
            self.smug_phase+=0.04
            offset=int(math.sin(self.smug_phase)*2)+18
            pygame.draw.polygon(self.surface,BGCOLOR,[(self.eyeLx,self.eyeLy-1),(self.eyeLx+self.eyeLwidth_current,self.eyeLy-1),(self.eyeLx,self.eyeLy+offset-1)])
        if self.suspicious:
            half=int(self.eyeRheight_current*0.5)
            pygame.draw.rect(self.surface,BGCOLOR,(self.eyeRx-2,self.eyeRy-2,self.eyeRwidth_current+4,half+2))
        if self.skeptical:
            half=int(self.eyeRheight_current*0.45)
            pygame.draw.rect(self.surface,BGCOLOR,(self.eyeRx-2,self.eyeRy-2,self.eyeRwidth_current+4,half+2))

        if self.thinking:self.draw_thinking_bubble(ct)
        if self.talking:self.draw_talking_antenna(ct)
        if self.furious:self.draw_furious_symbol(ct)
        if self.idea:self.draw_idea_bulb(ct)

        if self.sequence is not None:
            still_running=self._run_sequence(ct)
            if not still_running:
                self.sequence=None
        
        self._draw_mode_preview(ct)

