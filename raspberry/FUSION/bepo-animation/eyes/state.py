"""
eyes/state.py — FUSION / RoboEyes
Mixin con stato, inizializzazione e setter di basso livello degli occhi.
Nessuna logica di mood/sequenza qui dentro: solo dati e piccoli helper.
"""

import pygame
from constants import BGCOLOR
from assets import load_image
from socket_bridge import start_socket_listener


class EyesStateMixin:
    def __init__(self, draw_surface, width=1024, height=600, frame_rate=50):
        self.surface = draw_surface
        self.screen_width = width
        self.screen_height = height
        self.frame_interval = 1000 / frame_rate
        self.fps_timer = pygame.time.get_ticks()
        self.tired=False;self.angry=False;self.happy=False
        self.surprised=False;self.sad=False;self.love=False
        self.scared=False;self.curious=False;self.cyclops=False
        self.bored=False;self.excited=False;self.sleepy=False
        self.dizzy=False;self.confused2=False;self.suspicious=False
        self.thinking=False;self.talking=False;self.furious=False
        self.idea=False;self.skeptical=False;self.smug=False
        self.waiting=False;self.focused=False;self.proud=False;self.nervous=False
        self.nervous_timer=0;self.nervous_phase=0.0
        self.proud_timer=0
        self.waiting_pulse=0.0
        self.eyeL_open=False;self.eyeR_open=False
        self.space_between_default=40
        self.space_between_current=self.space_between_default
        self.space_between_next=self.space_between_default
        self.eyeLwidth_default=220;self.eyeLheight_default=220
        self.eyeLwidth_current=self.eyeLwidth_default
        self.eyeLheight_current=1
        self.eyeLwidth_next=self.eyeLwidth_default
        self.eyeLheight_next=self.eyeLheight_default
        self.eyeLheight_offset=0
        self.eyeLborder_radius_default=60
        self.eyeLborder_radius_current=self.eyeLborder_radius_default
        self.eyeLborder_radius_next=self.eyeLborder_radius_default
        self.eyeRwidth_default=self.eyeLwidth_default
        self.eyeRheight_default=self.eyeLheight_default
        self.eyeRwidth_current=self.eyeRwidth_default
        self.eyeRheight_current=1
        self.eyeRwidth_next=self.eyeRwidth_default
        self.eyeRheight_next=self.eyeRheight_default
        self.eyeRheight_offset=0
        self.eyeRborder_radius_default=60
        self.eyeRborder_radius_current=self.eyeRborder_radius_default
        self.eyeRborder_radius_next=self.eyeRborder_radius_default
        self.eyeLx_default=(self.screen_width-(self.eyeLwidth_default+self.space_between_default+self.eyeRwidth_default))//2
        self.eyeLy_default=(self.screen_height-self.eyeLheight_default)//2
        self.eyeLx=self.eyeLx_default;self.eyeLy=self.eyeLy_default
        self.eyeLx_next=self.eyeLx;self.eyeLy_next=self.eyeLy
        self.eyeRx_default=self.eyeLx+self.eyeLwidth_current+self.space_between_default
        self.eyeRy_default=self.eyeLy
        self.eyeRx=self.eyeRx_default;self.eyeRy=self.eyeRy_default
        self.eyeRx_next=self.eyeRx;self.eyeRy_next=self.eyeRy
        self.eyelids_height_max=self.eyeLheight_default//2
        self.eyelids_tired_height=0;self.eyelids_tired_height_next=0
        self.eyelids_angry_height=0;self.eyelids_angry_height_next=0
        self.eyelids_happy_bottom_offset_max=(self.eyeLheight_default//2)+6
        self.eyelids_happy_bottom_offset=0;self.eyelids_happy_bottom_offset_next=0
        self.eyelids_surprised_top_offset=0;self.eyelids_surprised_top_offset_next=0
        self.eyelids_sad_height=0;self.eyelids_sad_height_next=0
        self.hFlicker=False;self.hFlicker_alternate=False;self.hFlicker_amplitude=4
        self.vFlicker=False;self.vFlicker_alternate=False;self.vFlicker_amplitude=20
        self.autoblinker=False;self.blink_interval=2000;self.blink_interval_variation=4000
        self.blink_timer=pygame.time.get_ticks()
        self.idle=False;self.idle_interval=5000;self.idle_interval_variation=5000
        self.idle_animation_timer=pygame.time.get_ticks()
        self.confused_anim=False;self.confused_animation_timer=0
        self.confused_animation_duration=500;self.confused_toggle=True
        self.laugh=False;self.laugh_animation_timer=0
        self.laugh_animation_duration=500;self.laugh_toggle=True
        self.wink_left=False;self.wink_right=False
        self.wink_timer=0;self.wink_duration=300
        self.spin_anim=False;self.spin_timer=0;self.spin_duration=2000
        self.shake_anim=False;self.shake_timer=0;self.shake_duration=500
        self.hearts_anim=False;self.hearts_timer=0;self.hearts_duration=1500
        self.look_anim=False;self.look_targets=[];self.look_idx=0;self.look_timer=0
        self.sleepy_timer=pygame.time.get_ticks()
        self.dizzy_angle=0.0;self.dizzy_timer=pygame.time.get_ticks()
        self.bored_blink_timer=pygame.time.get_ticks()
        self.talking_phase=0.0;self.talking_timer=pygame.time.get_ticks()
        self.thinking_timer=pygame.time.get_ticks()
        self.furious_phase=0.0;self.furious_timer=pygame.time.get_ticks()
        self.idea_phase=0.0;self.idea_timer=pygame.time.get_ticks()
        self.smug_phase=0.0
        self.sequence=None
        self.seq_timer=pygame.time.get_ticks()
        self.seq_phase=0.0
        self.seq_data={}
        self.next_mood=None
        # preload immagini
        self._img_au = None
        self._img_dvd = None
        self._slot_imgs = None
        start_socket_listener(self)


    def _get_img_au(self):
        if self._img_au is None:
            self._img_au = load_image("among_us.png")
        return self._img_au

    def _get_img_dvd(self):
        if self._img_dvd is None:
            self._img_dvd = load_image("dvd.png")
        return self._img_dvd

    def _get_slot_imgs(self):
        if self._slot_imgs is None:
            names = ["cherries.png","seven.png","diamond.png","bell.png","lemon.png","grapes.png","watermelon.png"]
            raw = [load_image(n) for n in names]
            self._slot_imgs = [pygame.transform.smoothscale(img,(90,90)) for img in raw]
        return self._slot_imgs


    def begin(self):
        self.clear_display()
        self.eyeLheight_current=1;self.eyeRheight_current=1

    def update(self):
        ct=pygame.time.get_ticks()
        if ct-self.fps_timer>=self.frame_interval:
            if self.next_mood is not None:
                self.setMood(self.next_mood);
                self.next_mood=None
                self.surface.fill((0, 0, 0, 0))
            self.drawEyes()
            self.fps_timer=ct


    def _reset_all_moods(self):
        self.tired=self.angry=self.happy=self.surprised=self.sad=False
        self.love=self.scared=self.bored=self.excited=self.sleepy=False
        self.dizzy=self.confused2=self.suspicious=self.thinking=False
        self.talking=self.furious=self.idea=self.skeptical=self.smug=False
        self.waiting=False;self.focused=False;self.proud=False;self.nervous=False
        self.setHFlicker(False,0);self.setVFlicker(False,0)
        self.eyeLwidth_next=self.eyeLwidth_default;self.eyeRwidth_next=self.eyeRwidth_default
        self.eyeLheight_next=self.eyeLheight_default;self.eyeRheight_next=self.eyeRheight_default
        self.eyeLborder_radius_next=self.eyeLborder_radius_default
        self.eyeRborder_radius_next=self.eyeRborder_radius_default
        self.eyeLy_next=self.eyeLy_default;self.eyeRy_next=self.eyeRy_default
        self.eyeLx_next=self.eyeLx_default;self.eyeRx_next=self.eyeRx_default


    def setAutoblinker(self,active,interval=2,variation=4):
        self.autoblinker=active;self.blink_interval=interval*1000
        self.blink_interval_variation=variation*1000

    def setIdleMode(self,active,interval=5,variation=5):
        self.idle=active;self.idle_interval=interval*1000
        self.idle_interval_variation=variation*1000

    def setCuriosity(self,v):self.curious=v
    def setCyclops(self,v):self.cyclops=v
    def setHFlicker(self,v,amplitude=4):self.hFlicker=v;self.hFlicker_amplitude=amplitude
    def setVFlicker(self,v,amplitude=20):self.vFlicker=v;self.vFlicker_amplitude=amplitude

    def getScreenConstraint_X(self):
        return self.screen_width-self.eyeLwidth_current-self.space_between_current-self.eyeRwidth_current
    def getScreenConstraint_Y(self):
        return self.screen_height-self.eyeLheight_default


    def close(self,left=True,right=True):
        if left:self.eyeLheight_next=1;self.eyeL_open=False
        if right:self.eyeRheight_next=1;self.eyeR_open=False
    def open_eyes(self,left=True,right=True):
        if left:self.eyeL_open=True
        if right:self.eyeR_open=True
    def blink(self,left=True,right=True):
        self.close(left,right);self.open_eyes(left,right)


    def draw_eye(self,x,y,width,height,border_radius,color):
        pygame.draw.rect(self.surface,color,pygame.Rect(x,y,width,height),border_radius=max(0,border_radius))

    def clear_display(self):self.surface.fill(BGCOLOR)

