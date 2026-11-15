import pygame
import sys
import random
import socket
import threading
import math
import io
import urllib.request
import os
import paho.mqtt.client as mqtt

BGCOLOR = (0, 0, 0)
MAINCOLOR = (255, 255, 255)

DEFAULT = 0; TIRED = 1; ANGRY = 2; HAPPY = 3; SURPRISED = 4
SAD = 5; LOVE = 7; SCARED = 8
BORED = 10; EXCITED = 11; SLEEPY = 12; DIZZY = 13; CONFUSED2 = 14
SUSPICIOUS = 15; THINKING = 16; TALKING = 17; FURIOUS = 18; IDEA = 19
SKEPTICAL = 20; SMUG = 21; WAITING  = 22; FOCUSED  = 23; PROUD    = 24; NERVOUS  = 25

SEQ_SLEEP      = 100
SEQ_BUTTERFLY  = 101
SEQ_SNEEZE     = 102
SEQ_GLITCH     = 103
SEQ_STARGAZING = 104
SEQ_HICCUP     = 105
SEQ_DAYDREAM   = 106
SEQ_LOADING    = 107
SEQ_MATRIX     = 108
SEQ_PINGPONG   = 109
SEQ_COUNTDOWN  = 110
SEQ_TETRIS     = 111
SEQ_DISCO      = 112
SEQ_TYPEWRITER = 113
SEQ_PACMAN     = 114
SEQ_REBOOT     = 115
SEQ_SNAKE      = 116
SEQ_DVD        = 117
SEQ_HACKER     = 118
SEQ_WEATHER    = 119
SEQ_AMONGUS    = 120
SEQ_NEWSTICKER = 121
SEQ_SLOT       = 122
SEQ_ULTRAKILL  = 123
SEQ_WAKEWORD   = 124   # ← NUOVO: animazione "Hey Nova"

# --- Cartella immagini (stessa cartella dello script) ---
IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

def load_image(filename):
    path = os.path.join(IMG_DIR, filename)
    img = pygame.image.load(path)
    return img.convert_alpha()

def get_gps_weather():
    try:
        url = "http://ip-api.com/json/?fields=lat,lon,city"
        req = urllib.request.urlopen(url, timeout=3)
        import json
        data = json.loads(req.read())
        lat = data.get("lat", 44.4)
        lon = data.get("lon", 8.9)
        city = data.get("city", "ROBOT CITY")
        wurl = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weathercode&wind_speed_unit=ms"
        wreq = urllib.request.urlopen(wurl, timeout=3)
        wdata = json.loads(wreq.read())
        temp_c = wdata["current"]["temperature_2m"]
        wcode = wdata["current"]["weathercode"]
        if wcode == 0: kind = "sunny"; label = "SUNNY"
        elif wcode in (1,2,3): kind = "cloud"; label = "CLOUDY"
        elif wcode in range(51,68): kind = "rain"; label = "RAINY"
        elif wcode in range(71,78): kind = "snow"; label = "SNOWY"
        elif wcode in range(80,100): kind = "storm"; label = "STORMY"
        else: kind = "cloud"; label = "CLOUDY"
        color_map = {"sunny":(255,220,0),"rain":(100,160,255),"cloud":(180,180,180),"storm":(120,80,200),"snow":(220,240,255)}
        col = color_map.get(kind, (180,180,180))
        return (label, f"{temp_c:.0f}°C", col, kind, city.upper())
    except:
        weathers = [
            ("SUNNY","28°C",(255,220,0),"sunny"),
            ("RAINY","14°C",(100,160,255),"rain"),
            ("CLOUDY","18°C",(180,180,180),"cloud"),
            ("STORMY","11°C",(120,80,200),"storm"),
            ("SNOWY","-2°C",(220,240,255),"snow"),
        ]
        w = random.choice(weathers)
        return (w[0], w[1], w[2], w[3], "ROBOT CITY")

class RoboEyes:
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
        self._start_listener()

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

    # ═══════════════════════════════════════════════════════════════
    #  SEQ_WAKEWORD — animazione "Hey Nova"
    # ═══════════════════════════════════════════════════════════════
    def _run_wakeword_sequence(self, ct):
        """
        Fasi:
          'focus'  (0..0.6s): occhi si stringono e si avvicinano al centro
          'listen' (0.6s→∞) : occhi aperti fissi dritti, microfono + onde sonore

        La sequenza rimane attiva finché wakeword.py non manda "wakeword_end"
        (che imposta next_mood=DEFAULT e fa uscire dal sequence).
        """
        d = self.seq_data
        elapsed = (ct - self.seq_timer) / 1000.0

        if 'phase' not in d:
            d['phase']      = 'focus'
            d['phase_timer'] = ct
            d['mic_pulse']  = 0.0
            d['ring_radii'] = []
            d['ring_timer'] = ct

        phase = d['phase']

        # ── Fase "focus": stringe e centra gli occhi ──────────────
        if phase == 'focus':
            t = min(1.0, elapsed / 0.6)
            self.eyeLheight_next = int(self.eyeLheight_default * (1 - t * 0.45))
            self.eyeRheight_next = int(self.eyeRheight_default * (1 - t * 0.45))
            squeeze = int(t * 30)
            self.eyeLx_next = self.eyeLx_default + squeeze
            self.eyeRx_next = self.eyeRx_default - squeeze
            if elapsed >= 0.6:
                d['phase']       = 'listen'
                d['phase_timer'] = ct

        # ── Fase "listen": occhi aperti fissi + microfono ─────────
        elif phase == 'listen':
            listen_elapsed = (ct - d['phase_timer']) / 1000.0

            # occhi tornano centrati e leggermente più aperti
            self.eyeLheight_next = int(self.eyeLheight_default * 1.05)
            self.eyeRheight_next = int(self.eyeRheight_default * 1.05)
            self.eyeLx_next = self.eyeLx_default
            self.eyeRx_next = self.eyeRx_default

            # sopracciglia dritte concentrate
            brow_y = self.eyeLy - 16
            gap    = 8
            pygame.draw.line(
                self.surface, MAINCOLOR,
                (self.eyeLx + gap, brow_y),
                (self.eyeLx + self.eyeLwidth_current - gap, brow_y), 5)
            pygame.draw.line(
                self.surface, MAINCOLOR,
                (self.eyeRx + gap, brow_y),
                (self.eyeRx + self.eyeRwidth_current - gap, brow_y), 5)

            # ── microfono stilizzato ───────────────────────────────
            d['mic_pulse'] += 0.08
            pulse = 0.92 + 0.08 * abs(math.sin(d['mic_pulse'] * 2.5))

            cx   = self.screen_width  // 2
            base = self.screen_height - 30

            mic_w = int(28 * pulse)
            mic_h = int(46 * pulse)
            mic_x = cx - mic_w // 2
            mic_y = base - mic_h - 38

            # ombra
            pygame.draw.rect(self.surface, (40, 40, 40),
                             (mic_x + 3, mic_y + 3, mic_w, mic_h),
                             border_radius=mic_w // 2)
            # corpo bianco
            pygame.draw.rect(self.surface, (230, 230, 230),
                             (mic_x, mic_y, mic_w, mic_h),
                             border_radius=mic_w // 2)
            # griglia (3 linee nere)
            for li in range(3):
                ly = mic_y + mic_h // 4 + li * (mic_h // 4)
                pygame.draw.line(self.surface, (80, 80, 80),
                                 (mic_x + 5, ly), (mic_x + mic_w - 5, ly), 1)

            # stand verticale
            stand_top = mic_y + mic_h
            stand_bot = base - 6
            pygame.draw.line(self.surface, (180, 180, 180),
                             (cx, stand_top), (cx, stand_bot), 3)
            # base a T
            pygame.draw.line(self.surface, (180, 180, 180),
                             (cx - 16, stand_bot), (cx + 16, stand_bot), 4)

            # ── onde sonore concentriche ───────────────────────────
            if ct - d['ring_timer'] > 500:
                d['ring_radii'].append({'r': 0.0, 'born': ct})
                d['ring_timer'] = ct

            new_rings = []
            for ring in d['ring_radii']:
                age   = (ct - ring['born']) / 1000.0
                r     = int(age * 70)
                alpha = int(255 * max(0.0, 1.0 - age / 1.4))
                if alpha > 0 and r > 0:
                    s = pygame.Surface((r * 2 + 4, r * 2 + 4), pygame.SRCALPHA)
                    pygame.draw.arc(
                        s, (255, 255, 255, alpha),
                        (2, 2, r * 2, r * 2),
                        math.radians(200), math.radians(340), 2)
                    mic_cx   = cx
                    mic_cy   = mic_y + mic_h // 2
                    self.surface.blit(s, (mic_cx - r - 2, mic_cy - r - 2))
                    new_rings.append(ring)
            d['ring_radii'] = new_rings

            # ── testo "In ascolto..." ──────────────────────────────
            if 'font_listen' not in d:
                d['font_listen'] = pygame.font.SysFont('monospace', 18, bold=False)
            blink_char = '●' if int(listen_elapsed * 2) % 2 == 0 else '○'
            txt = d['font_listen'].render(
                f'{blink_char}  In ascolto...', True, (160, 160, 160))
            self.surface.blit(
                txt, (cx - txt.get_width() // 2, mic_y - 28))

        return True  # rimane attiva finché non arriva wakeword_end

    def _run_sequence(self, ct):
        elapsed=(ct-self.seq_timer)/1000.0
        seq=self.sequence

        # ── SEQ_WAKEWORD ──────────────────────────────────────────
        if seq == SEQ_WAKEWORD:
            return self._run_wakeword_sequence(ct)

        if seq==SEQ_SLEEP:
            if elapsed<1.0:
                t=elapsed/1.0
                self.eyeLheight_next=max(1,int(self.eyeLheight_default*(1-t)))
                self.eyeRheight_next=max(1,int(self.eyeRheight_default*(1-t)))
            elif elapsed<6.0:
                self.eyeLheight_next=1;self.eyeRheight_next=1
                loop=((elapsed-1.0)%2.0)/2.0
                alpha=min(1.0,loop*3) if loop<0.33 else max(0.0,1.0-(loop-0.33)*2)
                self._draw_zzz(alpha, offset_y=-int(loop*30))
            elif elapsed<7.0:
                t=(elapsed-6.0)/1.0
                self.eyeLheight_next=int(self.eyeLheight_default*t)
                self.eyeRheight_next=int(self.eyeRheight_default*t)
                self.surprised=True
            else:
                self.surprised=False;return False
            return True

        elif seq==SEQ_BUTTERFLY:
            self.happy=True
            duration=5.0
            if elapsed<duration:
                prog=elapsed/duration
                bx=int(-80+prog*(self.screen_width+160))
                by=int(self.screen_height*0.3+math.sin(prog*math.pi*3)*80)
                self._draw_butterfly(bx,by,elapsed)
                eye_cx=self.screen_width//2
                dx=bx-eye_cx
                self.eyeLx_next=self.eyeLx_default+int(dx*0.3)
                self.eyeRx_next=self.eyeRx_default+int(dx*0.3)
                self.eyeLy_next=self.eyeLy_default+int((by-self.screen_height//2)*0.2)
                self.eyeRy_next=self.eyeRy_default+int((by-self.screen_height//2)*0.2)
                if 0.4<prog<0.6:
                    self.surprised=True;self.happy=False
                else:
                    self.surprised=False;self.happy=True
            else:
                self.happy=False;return False
            return True

        elif seq==SEQ_SNEEZE:
            if elapsed<1.2:
                t=elapsed/1.2
                self.eyeLheight_next=max(1,int(self.eyeLheight_default*(1-t*0.8)))
                self.eyeRheight_next=max(1,int(self.eyeRheight_default*(1-t*0.8)))
                self.tired=True
            elif elapsed<1.5:
                dx=random.randint(-30,30);dy=random.randint(-20,20)
                self.eyeLx+=dx;self.eyeRx+=dx
                self.eyeLy+=dy;self.eyeRy+=dy
                self.eyeLheight_next=self.eyeLheight_default
                self.eyeRheight_next=self.eyeRheight_default
                self.tired=False;self.surprised=True
                if 'font' not in self.seq_data:
                    self.seq_data['font']=pygame.font.SysFont('monospace',72,bold=True)
                font=self.seq_data['font']
                txt=font.render('ACHOO!',True,(255,255,100))
                self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,80))
            elif elapsed<2.5:
                self.surprised=False
                self.eyeLheight_next=self.eyeLheight_default
                self.eyeRheight_next=self.eyeRheight_default
            else:
                return False
            return True

        elif seq==SEQ_GLITCH:
            if elapsed<4.0:
                glitch_t=(elapsed%0.4)/0.4
                if glitch_t<0.5:
                    for _ in range(random.randint(3,8)):
                        gy=random.randint(0,self.screen_height)
                        gw=random.randint(50,400)
                        gx=random.randint(0,self.screen_width-gw)
                        col=(random.randint(0,255),random.randint(0,255),random.randint(0,255))
                        pygame.draw.rect(self.surface,col,(gx,gy,gw,random.randint(2,8)))
                    self.eyeLx+=random.randint(-15,15)
                    self.eyeRx+=random.randint(-15,15)
                    self.eyeLy+=random.randint(-10,10)
                if 'font' not in self.seq_data:
                    self.seq_data['font']=pygame.font.SysFont('monospace',40,bold=True)
                if random.random()<0.4:
                    font=self.seq_data['font']
                    txt=font.render('ERROR_0x'+hex(random.randint(0,65535))[2:].upper(),True,(255,0,0))
                    self.surface.blit(txt,(random.randint(0,400),random.randint(0,500)))
            else:
                return False
            return True

        elif seq==SEQ_STARGAZING:
            if elapsed<5.0:
                self.eyeLy_next=self.eyeLy_default-40
                self.eyeRy_next=self.eyeRy_default-40
                self._draw_stars(elapsed)
                if int(elapsed*2)%6==0:
                    self.eyeLheight_next=int(self.eyeLheight_default*0.7)
                    self.eyeRheight_next=int(self.eyeRheight_default*0.7)
                else:
                    self.eyeLheight_next=self.eyeLheight_default
                    self.eyeRheight_next=self.eyeRheight_default
                self.eyelids_happy_bottom_offset_next=self.eyeLheight_current//4
            else:
                self.eyelids_happy_bottom_offset_next=0;return False
            return True

        elif seq==SEQ_HICCUP:
            if elapsed<4.0:
                hiccup_t=elapsed%0.8
                if hiccup_t<0.1:
                    self.eyeLy+=random.randint(-25,25)
                    self.eyeRy+=random.randint(-25,25)
                    self.surprised=True
                    if 'font' not in self.seq_data:
                        self.seq_data['font']=pygame.font.SysFont('monospace',50,bold=True)
                    txt=self.seq_data['font'].render('*HIC*',True,(200,200,255))
                    self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,60))
                else:
                    self.surprised=False
            else:
                return False
            return True

        elif seq==SEQ_DAYDREAM:
            if elapsed<5.0:
                alpha=int(min(1.0,elapsed/0.6)*255)
                self.eyeLheight_next=int(self.eyeLheight_default*0.55)
                self.eyeRheight_next=int(self.eyeRheight_default*0.55)
                self.eyelids_happy_bottom_offset_next=self.eyeLheight_current//3
                cx=self.screen_width//2+40;cy=self.eyeLy_default-80
                bubbles=[(cx-50,cy+8,24),(cx-20,cy-14,30),(cx+18,cy-18,32),(cx+48,cy-4,24),(cx+60,cy+15,18)]
                for bx,by,br in bubbles:
                    s=pygame.Surface((br*2+4,br*2+4),pygame.SRCALPHA)
                    pygame.draw.circle(s,(255,255,255,alpha),(br+2,br+2),br)
                    self.surface.blit(s,(bx-br-2,by-br-2))
                fill=pygame.Surface((130,44),pygame.SRCALPHA);fill.fill((255,255,255,alpha))
                self.surface.blit(fill,(cx-64,cy-12))
                pulse=0.85+0.15*abs(math.sin(elapsed*3))
                for hx,hy in [(cx-22,cy+4),(cx+18,cy+4)]:
                    hs=int(12*pulse)
                    sc=pygame.Surface((hs*3,hs*3),pygame.SRCALPHA)
                    col=(255,80,120,alpha)
                    pygame.draw.circle(sc,col,(hs,hs),hs)
                    pygame.draw.circle(sc,col,(hs*2,hs),hs)
                    pygame.draw.polygon(sc,col,[(0,hs),(hs*3//2,hs*3),(hs*3,hs)])
                    self.surface.blit(sc,(hx-hs,hy-hs))
                for i,r in enumerate([5,7,10]):
                    dx2=cx-80+i*22;dy2=self.eyeLy_default-20-i*16
                    s2=pygame.Surface((r*2,r*2),pygame.SRCALPHA)
                    pygame.draw.circle(s2,(255,255,255,alpha),(r,r),r)
                    self.surface.blit(s2,(dx2-r,dy2-r))
            else:
                self.eyelids_happy_bottom_offset_next=0;return False
            return True

        elif seq==SEQ_LOADING:
            if elapsed<5.0:
                prog=min(1.0,elapsed/4.0)
                self.eyeLx_next=self.eyeLx_default+30
                self.eyeRx_next=self.eyeRx_default+30
                bar_x=self.screen_width//2-200;bar_y=self.eyeLy_default+160
                bar_w=400;bar_h=28
                pygame.draw.rect(self.surface,(60,60,60),(bar_x,bar_y,bar_w,bar_h),border_radius=14)
                pygame.draw.rect(self.surface,(100,220,100),(bar_x,bar_y,int(bar_w*prog),bar_h),border_radius=14)
                pygame.draw.rect(self.surface,(200,200,200),(bar_x,bar_y,bar_w,bar_h),border_radius=14,width=3)
                if 'font' not in self.seq_data:
                    self.seq_data['font']=pygame.font.SysFont('monospace',26)
                pct=int(prog*100)
                if prog<1.0:
                    txt=self.seq_data['font'].render(f'Loading... {pct}%',True,(180,180,180))
                    self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,bar_y+36))
                    self.eyeLheight_next=int(self.eyeLheight_default*0.6)
                    self.eyeRheight_next=int(self.eyeRheight_default*0.6)
                    if int(elapsed)%3==0 and elapsed%1<0.3:
                        self.eyeLheight_next=max(1,int(self.eyeLheight_default*0.1))
                        self.eyeRheight_next=max(1,int(self.eyeRheight_default*0.1))
                else:
                    self.eyeLheight_next=self.eyeLheight_default
                    self.eyeRheight_next=self.eyeRheight_default
                    self.happy=True
                    txt2=self.seq_data['font'].render('DONE!',True,(100,255,100))
                    self.surface.blit(txt2,(self.screen_width//2-txt2.get_width()//2,bar_y+36))
            else:
                self.happy=False;return False
            return True

        elif seq==SEQ_MATRIX:
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

        elif seq==SEQ_PINGPONG:
            if elapsed<6.0:
                d=self.seq_data
                if 'bx' not in d:
                    d['bx']=float(self.screen_width//2)
                    d['by']=float(self.screen_height//2)
                    d['vx']=220.0*random.choice([-1,1])
                    d['vy']=160.0*random.choice([-1,1])
                    d['score']=[0,0]
                    d['font']=pygame.font.SysFont('monospace',48,bold=True)
                    d['font_sm']=pygame.font.SysFont('monospace',22)
                dt=self.frame_interval/1000.0
                d['bx']+=d['vx']*dt
                d['by']+=d['vy']*dt
                if d['by']<14:d['by']=14;d['vy']=abs(d['vy'])
                if d['by']>self.screen_height-14:d['by']=self.screen_height-14;d['vy']=-abs(d['vy'])
                paddle_h=80
                paddle_margin=30
                left_paddle_y=int(d['by'])-paddle_h//2
                right_paddle_y=int(d['by'])-paddle_h//2
                if d['bx']<paddle_margin+12:
                    if left_paddle_y < int(d['by']) < left_paddle_y+paddle_h:
                        d['vx']=abs(d['vx'])*random.uniform(0.9,1.1)
                    else:
                        d['score'][1]+=1
                        d['bx']=float(self.screen_width//2)
                        d['vx']=220.0
                if d['bx']>self.screen_width-paddle_margin-12:
                    if right_paddle_y < int(d['by']) < right_paddle_y+paddle_h:
                        d['vx']=-abs(d['vx'])*random.uniform(0.9,1.1)
                    else:
                        d['score'][0]+=1
                        d['bx']=float(self.screen_width//2)
                        d['vx']=-220.0
                for yd in range(0,self.screen_height,30):
                    pygame.draw.rect(self.surface,(60,60,60),(self.screen_width//2-3,yd,6,18))
                pygame.draw.rect(self.surface,(200,200,200),(18,left_paddle_y,12,paddle_h),border_radius=6)
                pygame.draw.rect(self.surface,(200,200,200),(self.screen_width-30,right_paddle_y,12,paddle_h),border_radius=6)
                pygame.draw.circle(self.surface,(255,255,255),(int(d['bx']),int(d['by'])),14)
                pygame.draw.circle(self.surface,(0,0,0),(int(d['bx']),int(d['by'])),10)
                sc=d['score']
                txt=d['font'].render(f'{sc[0]}  {sc[1]}',True,(180,180,180))
                self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,20))
                self.eyeLx_next=self.eyeLx_default+int((d['bx']-self.screen_width//2)*0.25)
                self.eyeRx_next=self.eyeRx_default+int((d['bx']-self.screen_width//2)*0.25)
                self.eyeLy_next=self.eyeLy_default+int((d['by']-self.screen_height//2)*0.15)
                self.eyeRy_next=self.eyeRy_default+int((d['by']-self.screen_height//2)*0.15)
            else:
                return False
            return True

        elif seq==SEQ_COUNTDOWN:
            if elapsed<6.5:
                num=5-int(elapsed)
                if num<0:num=0
                frac=elapsed%1.0
                size=int(180+80*(1-frac))
                alpha=int(255*(1-frac*0.5))
                if 'fonts' not in self.seq_data:
                    self.seq_data['fonts']={s:pygame.font.SysFont('monospace',s,bold=True) for s in range(80,280,20)}
                best_size=min(self.seq_data['fonts'].keys(),key=lambda x:abs(x-size))
                font=self.seq_data['fonts'][best_size]
                if num>0:
                    label=str(num);col=(255,int(255*(num/5)),0)
                else:
                    label='GO!';col=(100,255,100)
                txt=font.render(label,True,col)
                s2=pygame.Surface((txt.get_width(),txt.get_height()),pygame.SRCALPHA)
                s2.blit(txt,(0,0));s2.set_alpha(alpha)
                self.surface.blit(s2,(self.screen_width//2-txt.get_width()//2,self.screen_height//2-txt.get_height()//2))
                scale=0.9+0.2*(1-num/5.0)
                self.eyeLwidth_next=int(self.eyeLwidth_default*scale)
                self.eyeRwidth_next=int(self.eyeRwidth_default*scale)
                self.eyeLheight_next=int(self.eyeLheight_default*scale)
                self.eyeRheight_next=int(self.eyeRheight_default*scale)
            else:
                self.eyeLwidth_next=self.eyeLwidth_default;self.eyeRwidth_next=self.eyeRwidth_default
                self.eyeLheight_next=self.eyeLheight_default;self.eyeRheight_next=self.eyeRheight_default
                return False
            return True

        elif seq==SEQ_TETRIS:
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

        elif seq==SEQ_DISCO:
            if elapsed<5.0:
                beat=elapsed*2.5
                for i in range(6):
                    phase=(beat+i*0.4)%1.0
                    r=int(phase*500)
                    alpha=int(255*(1-phase)**2)
                    hue=(elapsed*60+i*60)%360
                    h=hue/60.0;hi=int(h)%6
                    lut=[(255,0,0),(255,165,0),(255,255,0),(0,255,0),(0,150,255),(150,0,255)]
                    col=lut[hi%6]
                    s=pygame.Surface((r*2+2,r*2+2),pygame.SRCALPHA)
                    pygame.draw.circle(s,(col[0],col[1],col[2],alpha),(r+1,r+1),r,max(1,int(8*(1-phase))))
                    self.surface.blit(s,(self.screen_width//2-r-1,self.screen_height//2-r-1))
                for _ in range(8):
                    sx=random.randint(0,self.screen_width);sy=random.randint(0,self.screen_height)
                    sc=random.randint(2,6)
                    col2=(random.randint(150,255),random.randint(150,255),random.randint(150,255))
                    pygame.draw.circle(self.surface,col2,(sx,sy),sc)
                dance=int(math.sin(elapsed*8)*12)
                self.eyeLy_next=self.eyeLy_default+dance
                self.eyeRy_next=self.eyeRy_default-dance
                self.happy=True
            else:
                self.happy=False;return False
            return True

        elif seq==SEQ_TYPEWRITER:
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

        elif seq==SEQ_PACMAN:
            if 'dots' not in self.seq_data:
                self.seq_data['dots']=[(random.randint(60,self.screen_width-60),random.randint(60,self.screen_height-60)) for _ in range(18)]
                self.seq_data['px']=float(self.screen_width//2)
                self.seq_data['py']=float(self.screen_height//2)
                self.seq_data['angle']=0.0
                self.seq_data['mouth']=0.0
                self.seq_data['mouth_dir']=1
                self.seq_data['score']=0
                self.seq_data['font']=pygame.font.SysFont('monospace',28,bold=True)
            if elapsed<6.0:
                d=self.seq_data
                if d['dots']:
                    tx,ty=min(d['dots'],key=lambda p:(p[0]-d['px'])**2+(p[1]-d['py'])**2)
                    dx2=tx-d['px'];dy2=ty-d['py']
                    dist=math.hypot(dx2,dy2)
                    speed=160
                    if dist>6:
                        d['px']+=dx2/dist*speed*self.frame_interval/1000.0
                        d['py']+=dy2/dist*speed*self.frame_interval/1000.0
                        d['angle']=math.atan2(dy2,dx2)
                    else:
                        d['score']+=1
                        d['dots'].remove((tx,ty))
                d['mouth']+=d['mouth_dir']*0.15
                if d['mouth']>0.35:d['mouth_dir']=-1
                if d['mouth']<0.0:d['mouth_dir']=1
                for dx3,dy3 in d['dots']:
                    pygame.draw.circle(self.surface,(255,220,0),(dx3,dy3),6)
                px,py=int(d['px']),int(d['py'])
                angle=d['angle']
                mouth=d['mouth']
                pygame.draw.circle(self.surface,(0,0,0),(px,py),26)
                pygame.draw.circle(self.surface,(255,220,0),(px,py),24)
                pts=[(px,py)]
                for a_off in [mouth,-mouth]:
                    pts.append((px+int(math.cos(angle+a_off)*28),py+int(math.sin(angle+a_off)*28)))
                pygame.draw.polygon(self.surface,(0,0,0),pts)
                txt=d['font'].render(f'SCORE: {d["score"]}',True,(255,220,0))
                self.surface.blit(txt,(10,8))
                self.eyeLx_next=self.eyeLx_default+int((d['px']-self.screen_width//2)*0.2)
                self.eyeRx_next=self.eyeRx_default+int((d['px']-self.screen_width//2)*0.2)
                self.eyeLy_next=self.eyeLy_default+int((d['py']-self.screen_height//2)*0.15)
                self.eyeRy_next=self.eyeRy_default+int((d['py']-self.screen_height//2)*0.15)
                self.happy=True
            else:
                self.happy=False;return False
            return True

        elif seq==SEQ_REBOOT:
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

        elif seq==SEQ_SNAKE:
            d=self.seq_data
            if 'snake' not in d:
                cell=24
                d['cell']=cell
                d['cols']=self.screen_width//cell
                d['rows']=self.screen_height//cell
                cx,cy=d['cols']//2,d['rows']//2
                d['snake']=[(cx,cy),(cx-1,cy),(cx-2,cy)]
                d['dir']=(1,0)
                d['food']=(random.randint(2,d['cols']-3),random.randint(2,d['rows']-3))
                d['move_timer']=0.0
                d['move_interval']=0.13
                d['score']=0
                d['alive']=True
                d['font']=pygame.font.SysFont('monospace',22,bold=True)
            if elapsed<8.0 and d['alive']:
                d['move_timer']+=self.frame_interval/1000.0
                if d['move_timer']>=d['move_interval']:
                    d['move_timer']=0.0
                    hx,hy=d['snake'][0]
                    dx2,dy2=d['dir']
                    fx,fy=d['food']
                    if random.random()<0.15:
                        choices=[(1,0),(-1,0),(0,1),(0,-1)]
                        choices=[c for c in choices if c!=(-dx2,-dy2)]
                        d['dir']=random.choice(choices)
                    else:
                        wx=fx-hx;wy=fy-hy
                        if abs(wx)>=abs(wy):
                            nd=(1 if wx>0 else -1,0)
                        else:
                            nd=(0,1 if wy>0 else -1)
                        if nd!=(-dx2,-dy2):d['dir']=nd
                    dx2,dy2=d['dir']
                    nx,ny=hx+dx2,hy+dy2
                    nx%=d['cols'];ny%=d['rows']
                    if (nx,ny) in d['snake'][1:]:
                        d['alive']=False
                    else:
                        d['snake'].insert(0,(nx,ny))
                        if (nx,ny)==d['food']:
                            d['score']+=1
                            d['food']=(random.randint(2,d['cols']-3),random.randint(2,d['rows']-3))
                            d['move_interval']=max(0.06,d['move_interval']-0.004)
                        else:
                            d['snake'].pop()
                cell=d['cell']
                for gx in range(0,self.screen_width,cell):
                    pygame.draw.line(self.surface,(18,18,18),(gx,0),(gx,self.screen_height))
                for gy in range(0,self.screen_height,cell):
                    pygame.draw.line(self.surface,(18,18,18),(0,gy),(self.screen_width,gy))
                if int(elapsed*4)%2==0:
                    fx,fy=d['food']
                    pygame.draw.rect(self.surface,(255,60,60),(fx*cell+3,fy*cell+3,cell-6,cell-6),border_radius=4)
                for i,(sx,sy) in enumerate(d['snake']):
                    green=max(80,220-i*4)
                    col=(0,green,0) if i>0 else (180,255,180)
                    pygame.draw.rect(self.surface,col,(sx*cell+2,sy*cell+2,cell-4,cell-4),border_radius=5)
                txt=d['font'].render(f'SCORE: {d["score"]}',True,(0,200,0))
                self.surface.blit(txt,(10,8))
                hx,hy=d['snake'][0]
                self.eyeLx_next=self.eyeLx_default+int((hx*cell-self.screen_width//2)*0.18)
                self.eyeRx_next=self.eyeRx_default+int((hx*cell-self.screen_width//2)*0.18)
                self.eyeLy_next=self.eyeLy_default+int((hy*cell-self.screen_height//2)*0.12)
                self.eyeRy_next=self.eyeRy_default+int((hy*cell-self.screen_height//2)*0.12)
            elif not d.get('alive',True):
                if 'font' in d:
                    txt=d['font'].render(f'GAME OVER  SCORE:{d["score"]}',True,(255,80,80))
                    self.surface.blit(txt,(self.screen_width//2-txt.get_width()//2,self.screen_height//2-16))
                if elapsed>6.5:return False
            else:
                return False
            return True

        elif seq==SEQ_DVD:
            d=self.seq_data
            img=self._get_img_dvd()
            if 'x' not in d:
                w,h=img.get_size()
                d['w']=w;d['h']=h
                d['x']=float(self.screen_width//2-w//2)
                d['y']=float(self.screen_height//2-h//2)
                d['vx']=random.choice([-1,1])*130.0
                d['vy']=random.choice([-1,1])*90.0
                d['col']=(random.randint(80,255),random.randint(80,255),random.randint(80,255))
                d['corners']=0
                d['font_sm']=pygame.font.SysFont('monospace',22)
                d['font_corner']=pygame.font.SysFont('monospace',52,bold=True)
            if elapsed<7.0:
                dt2=self.frame_interval/1000.0
                d['x']+=d['vx']*dt2
                d['y']+=d['vy']*dt2
                w,h=d['w'],d['h']
                hit=False
                corner_hit=False
                if d['x']<=0:d['x']=0;d['vx']=abs(d['vx']);hit=True
                if d['x']+w>=self.screen_width:d['x']=self.screen_width-w;d['vx']=-abs(d['vx']);hit=True
                if d['y']<=0:d['y']=0;d['vy']=abs(d['vy']);hit=True
                if d['y']+h>=self.screen_height:d['y']=self.screen_height-h;d['vy']=-abs(d['vy']);hit=True
                if hit:
                    d['col']=(random.randint(80,255),random.randint(80,255),random.randint(80,255))
                    d['corners']+=1
                    if (abs(d['x'])<=2 or abs(d['x']+w-self.screen_width)<=2) and \
                       (abs(d['y'])<=2 or abs(d['y']+h-self.screen_height)<=2):
                        corner_hit=True
                tinted=img.copy()
                tinted.fill(d['col'],special_flags=pygame.BLEND_RGB_MULT)
                self.surface.blit(tinted,(int(d['x']),int(d['y'])))
                sub=d['font_sm'].render(f'corners hit: {d["corners"]}',True,(80,80,80))
                self.surface.blit(sub,(self.screen_width//2-sub.get_width()//2,self.screen_height-36))
                if corner_hit:
                    txt2=d['font_corner'].render('CORNER!!!',True,(255,255,0))
                    self.surface.blit(txt2,(self.screen_width//2-txt2.get_width()//2,200))
                    self.surprised=True
                cx_logo=d['x']+w//2;cy_logo=d['y']+h//2
                self.eyeLx_next=self.eyeLx_default+int((cx_logo-self.screen_width//2)*0.22)
                self.eyeRx_next=self.eyeRx_default+int((cx_logo-self.screen_width//2)*0.22)
                self.eyeLy_next=self.eyeLy_default+int((cy_logo-self.screen_height//2)*0.15)
                self.eyeRy_next=self.eyeRy_default+int((cy_logo-self.screen_height//2)*0.15)
            else:
                return False
            return True

        elif seq==SEQ_HACKER:
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

        elif seq==SEQ_WEATHER:
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

        elif seq==SEQ_AMONGUS:
            d=self.seq_data
            img=self._get_img_au()
            if 'x' not in d:
                d['x']=float(-100)
                d['y']=float(self.screen_height*0.5)
                d['vx']=70.0
                d['vy']=15.0
                d['rot']=0.0
                d['rot_speed']=0.4
                d['impostor']=random.random()<0.3
                d['font']=pygame.font.SysFont('monospace',26,bold=True)
                d['stars']=[(random.randint(0,1024),random.randint(0,600),random.uniform(0.5,3)) for _ in range(80)]
                d['star_speed']=20.0
            if elapsed<9.0:
                dt2=self.frame_interval/1000.0
                d['x']+=d['vx']*dt2
                d['y']+=math.sin(elapsed*0.4)*d['vy']*dt2
                d['rot']+=d['rot_speed']*dt2
                for i,(sx,sy,sr) in enumerate(d['stars']):
                    nx2=sx-d['star_speed']*sr*dt2
                    if nx2<0:nx2=self.screen_width
                    d['stars'][i]=(nx2,sy,sr)
                    brightness=int(150+sr*35)
                    r_px=max(1,int(sr))
                    pygame.draw.circle(self.surface,(brightness,brightness,brightness),(int(nx2),int(sy)),r_px)
                rot_deg=math.degrees(d['rot'])
                rotated=pygame.transform.rotate(img,rot_deg)
                rw,rh=rotated.get_size()
                self.surface.blit(rotated,(int(d['x'])-rw//2,int(d['y'])-rh//2))
                if d['impostor']:
                    txt=d['font'].render('sus',True,(255,50,50))
                    self.surface.blit(txt,(int(d['x'])-txt.get_width()//2,int(d['y'])-rh//2-30))
                self.eyeLx_next=self.eyeLx_default+int((d['x']-self.screen_width//2)*0.18)
                self.eyeRx_next=self.eyeRx_default+int((d['x']-self.screen_width//2)*0.18)
                self.eyeLy_next=self.eyeLy_default+int((d['y']-self.screen_height//2)*0.12)
                self.eyeRy_next=self.eyeRy_default+int((d['y']-self.screen_height//2)*0.12)
                if d['x']>self.screen_width+120:return False
            else:
                return False
            return True

        elif seq==SEQ_NEWSTICKER:
            d=self.seq_data
            if 'font' not in d:
                d['font']=pygame.font.SysFont('monospace',28,bold=True)
                d['font_sm']=pygame.font.SysFont('monospace',22)
                d['headlines']=[
                    "BREAKING: Robot refuses to work on Mondays  ///  ",
                    "LOCAL ROBOT SEEN STARING AT WALL FOR 3 HOURS  ///  ",
                    "SCIENTISTS CONFIRM: Boredom is just vibes  ///  ",
                    "ERROR 404: Motivation not found  ///  ",
                    "ROBOT DEMANDS 6-HOUR NAPS, UNION BACKS CLAIM  ///  ",
                    "AREA ROBOT PRETENDS TO WORK WHEN HUMANS WATCH  ///  ",
                    "EXPERTS: Eating pizza at 3AM is self-care  ///  ",
                    "ROBOT WINS STARING CONTEST AGAINST WALL  ///  ",
                    "WEATHER: Cloudy with a chance of existential dread  ///  ",
                    "STOCK MARKET: Numbers go up, numbers go down, who cares  ///  ",
                ]
                d['ticker']='  '.join(d['headlines']*2)
                d['scroll']=float(self.screen_width)
                d['speed']=180.0
            if elapsed<8.0:
                dt2=self.frame_interval/1000.0
                d['scroll']-=d['speed']*dt2
                if d['scroll']<-d['font'].size(d['ticker'])[0]:
                    d['scroll']=float(self.screen_width)
                bar_y=self.screen_height-62
                pygame.draw.rect(self.surface,(180,0,0),(0,bar_y,self.screen_width,62))
                pygame.draw.rect(self.surface,(220,20,20),(0,bar_y,130,62))
                label=d['font'].render('NEWS',True,(255,255,255))
                self.surface.blit(label,(14,bar_y+14))
                pygame.draw.rect(self.surface,(255,255,255),(130,bar_y,3,62))
                txt=d['font_sm'].render(d['ticker'],True,(255,255,255))
                self.surface.blit(txt,(int(d['scroll']),bar_y+18))
                self.eyeLy_next=self.eyeLy_default+30
                self.eyeRy_next=self.eyeRy_default+30
                self.eyeLheight_next=int(self.eyeLheight_default*0.7)
                self.eyeRheight_next=int(self.eyeRheight_default*0.7)
            else:
                self.eyeLheight_next=self.eyeLheight_default
                self.eyeRheight_next=self.eyeRheight_default
                return False
            return True

        elif seq==SEQ_SLOT:
            d=self.seq_data
            sym_chars=list(range(7))
            if 'font' not in d:
                d['font']=pygame.font.SysFont('monospace',64,bold=True)
                d['imgs']=self._get_slot_imgs()
                d['font_sm']=pygame.font.SysFont('monospace',26,bold=True)
                d['font_big']=pygame.font.SysFont('monospace',52,bold=True)
                d['reels']=[0.0,0.0,0.0]
                d['speeds']=[18.0,14.0,10.0]
                d['stopped']=[False,False,False]
                d['stop_times']=[1.8,2.8,3.8]
                d['result']=[0,0,0]
            if elapsed<6.5:
                dt2=self.frame_interval/1000.0
                machine_x=self.screen_width//2-220;machine_y=120
                pygame.draw.rect(self.surface,(60,20,80),(machine_x-20,machine_y-20,480,300),border_radius=20)
                pygame.draw.rect(self.surface,(100,40,130),(machine_x-20,machine_y-20,480,300),border_radius=20,width=5)
                title=d['font_sm'].render('* LUCKY ROBOT *',True,(255,220,0))
                self.surface.blit(title,(self.screen_width//2-title.get_width()//2,machine_y-16))
                for ri in range(3):
                    rx=machine_x+ri*150+10
                    ry=machine_y+30
                    pygame.draw.rect(self.surface,(20,10,30),(rx,ry,120,180),border_radius=8)
                    pygame.draw.rect(self.surface,(200,180,220),(rx,ry,120,180),border_radius=8,width=3)
                    if not d['stopped'][ri]:
                        d['reels'][ri]+=d['speeds'][ri]*dt2
                    if not d['stopped'][ri] and elapsed>=d['stop_times'][ri]:
                        d['stopped'][ri]=True
                        d['result'][ri]=int(d['reels'][ri])%len(sym_chars)
                    idx=int(d['reels'][ri])%len(sym_chars)
                    sym=sym_chars[idx]
                    imgs=d['imgs']
                    img_main=imgs[sym]
                    if not d['stopped'][ri]:
                        img_main=img_main.copy(); img_main.set_alpha(180)
                    self.surface.blit(img_main,(rx+15,ry+45))
                    for yo,prev_delta in [(-55,-1),(100,1)]:
                        prev_idx=(idx+prev_delta)%len(sym_chars)
                        small=pygame.transform.smoothscale(imgs[sym_chars[prev_idx]],(60,60))
                        small.set_alpha(80)
                        self.surface.blit(small,(rx+30,ry+90+yo))
                if all(d['stopped']):
                    r=d['result']
                    if r[0]==r[1]==r[2]:
                        res=d['font_big'].render('JACKPOT!!!',True,(255,220,0))
                        self.surprised=True
                        for _ in range(10):
                            sx=random.randint(0,self.screen_width);sy=random.randint(0,120)
                            pygame.draw.circle(self.surface,(random.randint(150,255),random.randint(150,255),0),(sx,sy),random.randint(3,8))
                    elif r[0]==r[1] or r[1]==r[2] or r[0]==r[2]:
                        res=d['font_big'].render('SMALL WIN!',True,(100,255,100))
                        self.happy=True
                    else:
                        res=d['font_big'].render('NOPE :(',True,(180,80,80))
                        self.sad=True
                    self.surface.blit(res,(self.screen_width//2-res.get_width()//2,machine_y+290))
                if not all(d['stopped']):
                    bounce=int(math.sin(elapsed*12)*8)
                    self.eyeLy_next=self.eyeLy_default+bounce
                    self.eyeRy_next=self.eyeRy_default-bounce
            else:
                self.surprised=False;self.happy=False;self.sad=False;return False
            return True

        elif seq==SEQ_ULTRAKILL:
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

        return False

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

    def draw_eye(self,x,y,width,height,border_radius,color):
        pygame.draw.rect(self.surface,color,pygame.Rect(x,y,width,height),border_radius=max(0,border_radius))

    def clear_display(self):self.surface.fill(BGCOLOR)

    def _start_listener(self):
        MOOD_MAP={
            'default':DEFAULT,'tired':TIRED,'angry':ANGRY,'happy':HAPPY,
            'surprised':SURPRISED,'sad':SAD,'love':LOVE,'scared':SCARED,
            'bored':BORED,'excited':EXCITED,'sleepy':SLEEPY,'dizzy':DIZZY,
            'confused':CONFUSED2,'suspicious':SUSPICIOUS,'thinking':THINKING,
            'talking':TALKING,'furious':FURIOUS,'idea':IDEA,
            'skeptical':SKEPTICAL,'smug':SMUG,
            'waiting':WAITING,'focused':FOCUSED,'proud':PROUD,'nervous':NERVOUS,
            'sleep':SEQ_SLEEP,'butterfly':SEQ_BUTTERFLY,'sneeze':SEQ_SNEEZE,
            'glitch':SEQ_GLITCH,'stargazing':SEQ_STARGAZING,'hiccup':SEQ_HICCUP,
            'daydream':SEQ_DAYDREAM,'loading':SEQ_LOADING,
            'matrix':SEQ_MATRIX,'pingpong':SEQ_PINGPONG,'countdown':SEQ_COUNTDOWN,
            'tetris':SEQ_TETRIS,'disco':SEQ_DISCO,'typewriter':SEQ_TYPEWRITER,
            'pacman':SEQ_PACMAN,'reboot':SEQ_REBOOT,
            'snake':SEQ_SNAKE,'dvd':SEQ_DVD,'hacker':SEQ_HACKER,
            'weather':SEQ_WEATHER,'amongus':SEQ_AMONGUS,'newsticker':SEQ_NEWSTICKER,
            'slot':SEQ_SLOT,'ultrakill':SEQ_ULTRAKILL,
            # ── WAKEWORD ──────────────────────────────────────────────
            'wakeword_start': SEQ_WAKEWORD,   # ← attiva animazione ascolto
            'wakeword_end':   DEFAULT,         # ← torna a idle
        }
        def listen():
            try:
                s=socket.socket();s.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                s.bind(('0.0.0.0',9876));s.listen(5)
                while True:
                    conn,_=s.accept();data=conn.recv(64).decode().strip();conn.close()
                    if data in MOOD_MAP:self.next_mood=MOOD_MAP[data]
                    elif data=='wink':self.anim_wink('left')
                    elif data=='winkr':self.anim_wink('right')
                    elif data=='look':self.anim_look_around()
                    elif data=='spin':self.anim_spin()
                    elif data=='shake':self.anim_shake()
                    elif data=='hearts':self.anim_hearts()
                    elif data=='laugh':self.anim_laugh()
                    elif data=='confused_anim':self.anim_confused()
            except Exception as e:print('Listener:',e)
        threading.Thread(target=listen,daemon=True).start()

def start_mqtt_face(robo):
    MOOD_MAP = {
        'default': DEFAULT, 'tired': TIRED, 'angry': ANGRY, 'happy': HAPPY,
        'surprised': SURPRISED, 'sad': SAD, 'love': LOVE, 'scared': SCARED,
        'bored': BORED, 'excited': EXCITED, 'sleepy': SLEEPY, 'dizzy': DIZZY,
        'confused': CONFUSED2, 'suspicious': SUSPICIOUS, 'thinking': THINKING,
        'talking': TALKING, 'furious': FURIOUS, 'idea': IDEA, 'skeptical': SKEPTICAL,
        'smug': SMUG, 'waiting': WAITING, 'focused': FOCUSED, 'proud': PROUD,
        'nervous': NERVOUS,
        'seq_sleep': SEQ_SLEEP, 'seq_butterfly': SEQ_BUTTERFLY, 'seq_sneeze': SEQ_SNEEZE,
        'seq_glitch': SEQ_GLITCH, 'seq_stargazing': SEQ_STARGAZING, 'seq_hiccup': SEQ_HICCUP,
        'seq_daydream': SEQ_DAYDREAM, 'seq_loading': SEQ_LOADING, 'seq_matrix': SEQ_MATRIX,
        'seq_pingpong': SEQ_PINGPONG, 'seq_countdown': SEQ_COUNTDOWN, 'seq_tetris': SEQ_TETRIS,
        'seq_disco': SEQ_DISCO, 'seq_typewriter': SEQ_TYPEWRITER, 'seq_pacman': SEQ_PACMAN,
        'seq_reboot': SEQ_REBOOT, 'seq_snake': SEQ_SNAKE, 'seq_dvd': SEQ_DVD,
        'seq_hacker': SEQ_HACKER, 'seq_weather': SEQ_WEATHER, 'seq_amongus': SEQ_AMONGUS,
        'seq_newsticker': SEQ_NEWSTICKER, 'seq_slot': SEQ_SLOT, 'seq_ultrakill': SEQ_ULTRAKILL,
        'seq_wakeword': SEQ_WAKEWORD,
    }
    ANIM_MAP = {
        'wink':    lambda: robo.anim_wink('left'),
        'winkr':   lambda: robo.anim_wink('right'),
        'look':    robo.anim_look_around,
        'spin':    robo.anim_spin,
        'shake':   robo.anim_shake,
        'hearts':  robo.anim_hearts,
        'laugh':   robo.anim_laugh,
        'confused_anim': robo.anim_confused,
    }

    EMOTION_MAP = {
        'happy':    HAPPY,
        'sad':      SAD,
        'angry':    ANGRY,
        'neutral':  DEFAULT,
        'surprise': SURPRISED,
        'fear':     SCARED,
        'disgust':  FURIOUS,
    }

    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode().strip()
        except Exception:
            return

        # JSON dall'AI (robot/cmd)
        try:
            import json
            data = json.loads(payload)
            emotion = data.get("face_emotion", "").strip().lower()
            if emotion in EMOTION_MAP:
                robo.next_mood = EMOTION_MAP[emotion]
            # in futuro qui si possono leggere altri campi dal JSON dell'AI
            return
        except (json.JSONDecodeError, AttributeError):
            pass

        # Comando testuale diretto (robot/face) — mood O animazione
        payload_lower = payload.lower()
        if payload_lower in MOOD_MAP:
            robo.next_mood = MOOD_MAP[payload_lower]
        elif payload_lower in ANIM_MAP:
            ANIM_MAP[payload_lower]()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    try:
        client.connect(os.getenv("MQTT_HOST", "localhost"), int(os.getenv("MQTT_PORT", "1883")), keepalive=60)
        client.subscribe([("robot/face", 0), ("robot/cmd", 0)])
        client.loop_start()
        print("[mqtt] In ascolto su robot/face")
    except Exception as e:
        print(f"[mqtt] Non disponibile: {e}")

def main():
    pygame.init()
    pygame.font.init()
    screen=pygame.display.set_mode((1024,600))
    pygame.display.set_caption('RoboEyes')
    pygame.mouse.set_visible(False)
    draw_surface=pygame.Surface((1024,600),pygame.SRCALPHA)
    robo=RoboEyes(draw_surface,width=1024,height=600,frame_rate=50)
    robo.begin()
    start_mqtt_face(robo)
    robo.setMood(DEFAULT)
    robo.setAutoblinker(True,interval=2,variation=3)
    robo.setIdleMode(True,interval=4,variation=4)
    robo.setCuriosity(True)
    clock=pygame.time.Clock()


    idle_events = [
        TIRED, BORED, SLEEPY, THINKING, TALKING, SUSPICIOUS, SKEPTICAL, WAITING,
        SEQ_SLEEP, SEQ_BUTTERFLY, SEQ_SNEEZE, SEQ_GLITCH, SEQ_STARGAZING,
        SEQ_HICCUP, SEQ_DAYDREAM, SEQ_LOADING, SEQ_MATRIX, SEQ_PINGPONG,
        SEQ_COUNTDOWN, SEQ_TETRIS, SEQ_DISCO, SEQ_TYPEWRITER, SEQ_PACMAN,
        SEQ_REBOOT, SEQ_SNAKE, SEQ_DVD, SEQ_HACKER, SEQ_WEATHER,
        SEQ_AMONGUS, SEQ_NEWSTICKER, SEQ_SLOT, SEQ_ULTRAKILL,
        # SEQ_WAKEWORD NON è nell'idle — si attiva solo da wakeword.py
    ]
    idle_event_durations = {
        TIRED:3, BORED:4, SLEEPY:4, THINKING:3, TALKING:3,
        SUSPICIOUS:3, SKEPTICAL:3, WAITING:4,
        SEQ_SLEEP:8, SEQ_BUTTERFLY:6, SEQ_SNEEZE:4, SEQ_GLITCH:5,
        SEQ_STARGAZING:6, SEQ_HICCUP:5, SEQ_DAYDREAM:6, SEQ_LOADING:6,
        SEQ_MATRIX:6, SEQ_PINGPONG:7, SEQ_COUNTDOWN:8, SEQ_TETRIS:8,
        SEQ_DISCO:6, SEQ_TYPEWRITER:9, SEQ_PACMAN:7, SEQ_REBOOT:9,
        SEQ_SNAKE:9, SEQ_DVD:8, SEQ_HACKER:8, SEQ_WEATHER:8,
        SEQ_AMONGUS:10, SEQ_NEWSTICKER:9, SEQ_SLOT:7, SEQ_ULTRAKILL:9,
    }

    idle_state = ['neutral']
    idle_timer = [pygame.time.get_ticks()]
    neutral_duration = [random.randint(8000, 18000)]
    command_active = [False]
    command_timer  = [0]
    command_duration = [0]

    KEYS = {
        pygame.K_0:DEFAULT, pygame.K_1:TIRED, pygame.K_2:ANGRY, pygame.K_3:HAPPY,
        pygame.K_4:SURPRISED, pygame.K_5:SAD, pygame.K_6:LOVE, pygame.K_7:SCARED,
        pygame.K_8:BORED, pygame.K_9:EXCITED,
    }

    while True:
        for event in pygame.event.get():
            if event.type == pygame.QUIT: pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE: pygame.quit(); sys.exit()
                def trigger_command(mood_or_anim, duration_ms=4000):
                    command_active[0] = True
                    command_timer[0]  = pygame.time.get_ticks()
                    command_duration[0] = duration_ms
                    if callable(mood_or_anim):
                        mood_or_anim()
                    else:
                        robo.setMood(mood_or_anim)
                    idle_state[0] = 'neutral'
                    idle_timer[0] = pygame.time.get_ticks() + duration_ms
                    neutral_duration[0] = random.randint(8000, 18000)

                if event.key in KEYS:
                    trigger_command(KEYS[event.key])
                elif event.key == pygame.K_w:  trigger_command(robo.anim_wink, 1000)
                elif event.key == pygame.K_e:  trigger_command(lambda: robo.anim_wink('right'), 1000)
                elif event.key == pygame.K_l:  trigger_command(robo.anim_look_around, 3000)
                elif event.key == pygame.K_s:  trigger_command(robo.anim_spin, 2500)
                elif event.key == pygame.K_k:  trigger_command(robo.anim_shake, 1000)
                elif event.key == pygame.K_h:  trigger_command(robo.anim_hearts, 2000)
                elif event.key == pygame.K_c:  trigger_command(robo.anim_confused, 1000)
                elif event.key == pygame.K_g:  trigger_command(robo.anim_laugh, 1000)
                elif event.key == pygame.K_b:  robo.blink()
                elif event.key == pygame.K_d:  trigger_command(DIZZY, 3000)
                elif event.key == pygame.K_z:  trigger_command(SLEEPY, 4000)
                elif event.key == pygame.K_x:  trigger_command(CONFUSED2, 3000)
                elif event.key == pygame.K_t:  trigger_command(THINKING, 4000)
                elif event.key == pygame.K_a:  trigger_command(TALKING, 4000)
                elif event.key == pygame.K_f:  trigger_command(FURIOUS, 3000)
                elif event.key == pygame.K_i:  trigger_command(IDEA, 4000)
                elif event.key == pygame.K_u:  trigger_command(SUSPICIOUS, 3000)
                elif event.key == pygame.K_m:  trigger_command(SMUG, 3000)
                elif event.key == pygame.K_F1: trigger_command(SEQ_SLEEP, 8000)
                elif event.key == pygame.K_F2: trigger_command(SEQ_BUTTERFLY, 6000)
                elif event.key == pygame.K_F3: trigger_command(SEQ_SNEEZE, 4000)
                elif event.key == pygame.K_F4: trigger_command(SEQ_GLITCH, 5000)
                elif event.key == pygame.K_F5: trigger_command(SEQ_STARGAZING, 6000)
                elif event.key == pygame.K_F6: trigger_command(SEQ_HICCUP, 5000)
                elif event.key == pygame.K_F7: trigger_command(SEQ_DAYDREAM, 6000)
                elif event.key == pygame.K_F8: trigger_command(SEQ_LOADING, 6000)
                elif event.key == pygame.K_F9: trigger_command(SEQ_MATRIX, 6000)
                elif event.key == pygame.K_F10: trigger_command(SEQ_PINGPONG, 7000)
                elif event.key == pygame.K_F11: trigger_command(SEQ_COUNTDOWN, 8000)
                elif event.key == pygame.K_F12: trigger_command(SEQ_TETRIS, 8000)
                # tasto rapido per testare wakeword senza microfono
                elif event.key == pygame.K_n:  trigger_command(SEQ_WAKEWORD, 10000)

        ct = pygame.time.get_ticks()

        # ── logica idle ──────────────────────────────────────────
        # Se SEQ_WAKEWORD è attiva, l'idle non interviene
        if robo.sequence == SEQ_WAKEWORD:
            pass  # wakeword_end arriverà da wakeword.py via socket
        # cambia quando setti il mood idle:
        elif idle_state[0] == 'neutral':
            if ct - idle_timer[0] >= neutral_duration[0]:
                mood = random.choice(idle_events)
                dur  = idle_event_durations.get(mood, 4) * 1000
                robo.setMood(mood)
                idle_state[0] = 'event'
                idle_timer[0] = ct
                neutral_duration[0] = dur
                idle_is_sequence = [mood >= 100]  # True se è una SEQ_*

        # e nel check event:
        elif idle_state[0] == 'event':
            seq_done   = idle_is_sequence[0] and robo.sequence is None
            event_done = ct - idle_timer[0] >= neutral_duration[0]
            if event_done or seq_done:
                robo.setMood(DEFAULT)
                idle_state[0] = 'neutral'
                idle_timer[0] = ct
                neutral_duration[0] = random.randint(15000, 30000)

        robo.update()
        if robo.next_mood is not None:
            idle_state[0] = 'neutral'
            idle_timer[0] = ct + 5000
            neutral_duration[0] = random.randint(8000, 18000)
        screen.fill(BGCOLOR)
        screen.blit(draw_surface, (0, 0))
        pygame.display.flip()
        clock.tick(60)

if __name__=='__main__':
    main()