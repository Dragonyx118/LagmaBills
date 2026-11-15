"""
constants.py — FUSION / RoboEyes
Colori, costanti MOOD/SEQ e mappe nome→costante condivise da
mqtt_bridge.py, socket_bridge.py e dal resto dell'app.
"""

BGCOLOR = (0, 0, 0)
MAINCOLOR = (255, 255, 255)

# ── MOOD (valori < 100) ──────────────────────────────────────────
DEFAULT = 0; TIRED = 1; ANGRY = 2; HAPPY = 3; SURPRISED = 4
SAD = 5; LOVE = 7; SCARED = 8
BORED = 10; EXCITED = 11; SLEEPY = 12; DIZZY = 13; CONFUSED2 = 14
SUSPICIOUS = 15; THINKING = 16; TALKING = 17; FURIOUS = 18; IDEA = 19
SKEPTICAL = 20; SMUG = 21; WAITING = 22; FOCUSED = 23; PROUD = 24; NERVOUS = 25

# ── SEQUENZE (valori >= 100) ─────────────────────────────────────
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
SEQ_WAKEWORD   = 124   # animazione "Hey Nova"

# ── Mappa nome testuale → costante, condivisa da MQTT e socket ───
# (usata da robot/face via MQTT e dal listener socket su porta 9876)
MOOD_MAP = {
    'default': DEFAULT, 'tired': TIRED, 'angry': ANGRY, 'happy': HAPPY,
    'surprised': SURPRISED, 'sad': SAD, 'love': LOVE, 'scared': SCARED,
    'bored': BORED, 'excited': EXCITED, 'sleepy': SLEEPY, 'dizzy': DIZZY,
    'confused': CONFUSED2, 'suspicious': SUSPICIOUS, 'thinking': THINKING,
    'talking': TALKING, 'furious': FURIOUS, 'idea': IDEA,
    'skeptical': SKEPTICAL, 'smug': SMUG,
    'waiting': WAITING, 'focused': FOCUSED, 'proud': PROUD, 'nervous': NERVOUS,
    'sleep': SEQ_SLEEP, 'butterfly': SEQ_BUTTERFLY, 'sneeze': SEQ_SNEEZE,
    'glitch': SEQ_GLITCH, 'stargazing': SEQ_STARGAZING, 'hiccup': SEQ_HICCUP,
    'daydream': SEQ_DAYDREAM, 'loading': SEQ_LOADING,
    'matrix': SEQ_MATRIX, 'pingpong': SEQ_PINGPONG, 'countdown': SEQ_COUNTDOWN,
    'tetris': SEQ_TETRIS, 'disco': SEQ_DISCO, 'typewriter': SEQ_TYPEWRITER,
    'pacman': SEQ_PACMAN, 'reboot': SEQ_REBOOT,
    'snake': SEQ_SNAKE, 'dvd': SEQ_DVD, 'hacker': SEQ_HACKER,
    'weather': SEQ_WEATHER, 'amongus': SEQ_AMONGUS, 'newsticker': SEQ_NEWSTICKER,
    'slot': SEQ_SLOT, 'ultrakill': SEQ_ULTRAKILL,
    # ── WAKEWORD ──────────────────────────────────────────────────
    'wakeword_start': SEQ_WAKEWORD,   # attiva animazione ascolto
    'wakeword_end':   DEFAULT,        # torna a idle
}

# Variante con prefisso "seq_" usata dal topic MQTT robot/face
# (manteniamo entrambe le mappe per compatibilità totale col codice originale)
MQTT_MOOD_MAP = {
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

EMOTION_MAP = {
    'happy':    HAPPY,
    'sad':      SAD,
    'angry':    ANGRY,
    'neutral':  DEFAULT,
    'surprise': SURPRISED,
    'fear':     SCARED,
    'disgust':  FURIOUS,
}

# ── Idle: quali mood/sequenze può scegliere a caso il loop idle ──
IDLE_EVENTS = [
    TIRED, BORED, SLEEPY, THINKING, TALKING, SUSPICIOUS, SKEPTICAL, WAITING,
    SEQ_SLEEP, SEQ_BUTTERFLY, SEQ_SNEEZE, SEQ_GLITCH, SEQ_STARGAZING,
    SEQ_HICCUP, SEQ_DAYDREAM, SEQ_LOADING, SEQ_MATRIX, SEQ_PINGPONG,
    SEQ_COUNTDOWN, SEQ_TETRIS, SEQ_DISCO, SEQ_TYPEWRITER, SEQ_PACMAN,
    SEQ_REBOOT, SEQ_SNAKE, SEQ_DVD, SEQ_HACKER, SEQ_WEATHER,
    SEQ_AMONGUS, SEQ_NEWSTICKER, SEQ_SLOT, SEQ_ULTRAKILL,
    # SEQ_WAKEWORD NON è nell'idle — si attiva solo da wakeword.py
]

IDLE_EVENT_DURATIONS = {
    TIRED: 3, BORED: 4, SLEEPY: 4, THINKING: 3, TALKING: 3,
    SUSPICIOUS: 3, SKEPTICAL: 3, WAITING: 4,
    SEQ_SLEEP: 8, SEQ_BUTTERFLY: 6, SEQ_SNEEZE: 4, SEQ_GLITCH: 5,
    SEQ_STARGAZING: 6, SEQ_HICCUP: 5, SEQ_DAYDREAM: 6, SEQ_LOADING: 6,
    SEQ_MATRIX: 6, SEQ_PINGPONG: 7, SEQ_COUNTDOWN: 8, SEQ_TETRIS: 8,
    SEQ_DISCO: 6, SEQ_TYPEWRITER: 9, SEQ_PACMAN: 7, SEQ_REBOOT: 9,
    SEQ_SNAKE: 9, SEQ_DVD: 8, SEQ_HACKER: 8, SEQ_WEATHER: 8,
    SEQ_AMONGUS: 10, SEQ_NEWSTICKER: 9, SEQ_SLOT: 7, SEQ_ULTRAKILL: 9,
}
