"""
eyes/moods.py — FUSION / RoboEyes
Mixin con setMood() (i mood "semplici", non le sequenze animate lunghe,
che vivono in sequences/) e le piccole animazioni one-shot (wink, spin,
shake, hearts, look_around, confused, laugh).
"""

import pygame
from constants import (
    TIRED, ANGRY, HAPPY, SURPRISED, SAD, LOVE, SCARED,
    BORED, EXCITED, SLEEPY, DIZZY, CONFUSED2, SUSPICIOUS,
    THINKING, TALKING, FURIOUS, IDEA, SKEPTICAL, SMUG,
    WAITING, FOCUSED, PROUD, NERVOUS,
)


class MoodsMixin:
    def setMood(self,mood):
        if mood >= 100:
            self._reset_all_moods()
            self.sequence=mood
            self.seq_timer=pygame.time.get_ticks()
            self.seq_phase=0.0
            self.seq_data={}
            return
        self.sequence=None
        self._reset_all_moods()
        ct=pygame.time.get_ticks()
        if mood==TIRED:self.tired=True
        elif mood==ANGRY:self.angry=True
        elif mood==HAPPY:self.happy=True
        elif mood==SURPRISED:self.surprised=True
        elif mood==SAD:self.sad=True
        elif mood==LOVE:self.love=True
        elif mood==SCARED:self.scared=True
        elif mood==BORED:self.bored=True;self.bored_blink_timer=ct
        elif mood==EXCITED:self.excited=True;self.setHFlicker(True,6);self.setVFlicker(True,4)
        elif mood==SLEEPY:self.sleepy=True;self.sleepy_timer=ct
        elif mood==DIZZY:self.dizzy=True;self.dizzy_timer=ct;self.dizzy_angle=0.0
        elif mood==CONFUSED2:self.confused2=True
        elif mood==SUSPICIOUS:
            self.suspicious=True
            self.eyeRwidth_next=int(self.eyeRwidth_default*0.6)
            self.eyeRheight_next=int(self.eyeRheight_default*0.45)
        elif mood==THINKING:self.thinking=True;self.thinking_timer=ct
        elif mood==TALKING:self.talking=True;self.talking_timer=ct
        elif mood==FURIOUS:
            self.furious=True;self.furious_timer=ct;self.furious_phase=0.0;self.angry=True
        elif mood==IDEA:
            self.idea=True;self.idea_timer=ct;self.idea_phase=0.0;self.happy=True
        elif mood==SKEPTICAL:
            self.skeptical=True
            self.eyeRheight_next=int(self.eyeRheight_default*0.5)
        elif mood==SMUG:
            self.smug=True;self.smug_phase=0.0;self.happy=True
        elif mood==WAITING:
            self.waiting=True
            self.eyeLheight_next=int(self.eyeLheight_default*0.75)
            self.eyeRheight_next=int(self.eyeRheight_default*0.75)
        elif mood==FOCUSED:
            self.focused=True
            self.eyeLheight_next=int(self.eyeLheight_default*0.35)
            self.eyeRheight_next=int(self.eyeRheight_default*0.35)
            self.eyeLwidth_next=int(self.eyeLwidth_default*1.05)
            self.eyeRwidth_next=int(self.eyeRwidth_default*1.05)
            self.eyeLborder_radius_next=18
            self.eyeRborder_radius_next=18
        elif mood==PROUD:
            self.proud=True;self.proud_timer=ct
            self.eyeLy_next=self.eyeLy_default-28
            self.eyeRy_next=self.eyeRy_default-28
            self.eyeLheight_next=int(self.eyeLheight_default*1.08)
            self.eyeRheight_next=int(self.eyeRheight_default*1.08)
            self.eyeLborder_radius_next=self.eyeLborder_radius_default+10
            self.eyeRborder_radius_next=self.eyeRborder_radius_default+10
        elif mood==NERVOUS:
            self.nervous=True;self.nervous_timer=ct;self.nervous_phase=0.0
            self.eyeLheight_next=int(self.eyeLheight_default*0.88)
            self.eyeRheight_next=int(self.eyeRheight_default*0.88)


    def anim_confused(self):self.confused_anim=True
    def anim_laugh(self):self.laugh=True
    def anim_wink(self,side='left'):
        if side=='left':self.wink_left=True
        else:self.wink_right=True
        self.wink_timer=pygame.time.get_ticks()
    def anim_spin(self):self.spin_anim=True;self.spin_timer=pygame.time.get_ticks()
    def anim_shake(self):self.shake_anim=True;self.shake_timer=pygame.time.get_ticks()
    def anim_hearts(self):self.hearts_anim=True;self.hearts_timer=pygame.time.get_ticks()
    def anim_look_around(self):
        self.look_anim=True;self.look_idx=0;self.look_timer=pygame.time.get_ticks()
        cx=self.getScreenConstraint_X()//2;cy=self.getScreenConstraint_Y()//2
        self.look_targets=[(cx,cy),(0,0),(cx,0),(cx,cy),(0,cy),(cx,cy)]

