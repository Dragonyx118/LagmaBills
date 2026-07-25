#!/usr/bin/env python3
"""
robot_monitor.py — Raspberry Pi reader per ESP32 Sensori (0x09) + ESP32 Motori (0x08)
Legge e stampa in tempo reale TUTTI i dati del robot.

Dipendenze:
    pip install smbus2 --break-system-packages

Uso:
    python3 robot_monitor.py
    python3 robot_monitor.py --bus 1        # default bus=1
    python3 robot_monitor.py --interval 0.1 # refresh ogni 100ms (default 200ms)
"""
#pip install smbus2 --break-system-packages
#python3 robot_monitor.py

import smbus2
import struct
import time
import argparse
import os
import sys
from dataclasses import dataclass, field

# ── INDIRIZZI I2C ────────────────────────────────────────────────
ADDR_MOTORI   = 0x08   # ESP32 motori
ADDR_SENSORI  = 0x09   # ESP32 sensori + braccio

# ── DIMENSIONI BUFFER ────────────────────────────────────────────
LEN_MOTORI   = 20   # 4x int32 encoder + vel + stato + 2 padding
LEN_SENSORI  = 26   # 6x uint16 US + 6x int16 IMU + 1 TCRT + 1 pad

# ── DESCRIZIONE STATO MOTORI ─────────────────────────────────────
STATO_MOTORI = {0: "FERMO", 1: "IN MOTO", 2: "ROTAZIONE PRECISA"}

# ────────────────────────────────────────────────────────────────
#  DATACLASS STATO COMPLETO ROBOT
# ────────────────────────────────────────────────────────────────

@dataclass
class StatoMotori:
    enc_fl:   int  = 0      # tick encoder Anteriore Sinistro
    enc_fr:   int  = 0      # tick encoder Anteriore Destro
    enc_rl:   int  = 0      # tick encoder Posteriore Sinistro
    enc_rr:   int  = 0      # tick encoder Posteriore Destro
    velocita: int  = 0      # 0-255
    stato:    int  = 0      # 0=stop 1=moto 2=rot.precisa
    ok:       bool = False  # lettura I2C riuscita

    @property
    def stato_str(self):
        return STATO_MOTORI.get(self.stato, f"?({self.stato})")

    @property
    def enc_medio(self):
        return (abs(self.enc_fl) + abs(self.enc_fr) +
                abs(self.enc_rl) + abs(self.enc_rr)) / 4.0

    def dir_ruote(self):
        def d(v):
            if v > 2:  return "AVANTI  ▲"
            if v < -2: return "INDIETRO▼"
            return             "FERMO   ■"
        return {
            "FL": d(self.enc_fl),
            "FR": d(self.enc_fr),
            "RL": d(self.enc_rl),
            "RR": d(self.enc_rr),
        }


@dataclass
class StatoSensori:
    # Ultrasuoni cm (9999 = timeout / nessun ostacolo)
    us_fronte:   int   = 9999
    us_retro:    int   = 9999
    us_sinistra: int   = 9999
    us_destra:   int   = 9999
    us_cliff_f:  int   = 9999
    us_cliff_r:  int   = 9999

    # IMU MPU-6050
    acc_x:  float = 0.0   # g
    acc_y:  float = 0.0
    acc_z:  float = 0.0
    gyro_x: float = 0.0   # gradi/s
    gyro_y: float = 0.0
    gyro_z: float = 0.0

    # Line sensor TCRT5000 (bit0=SX bit1=CEN bit2=DX)
    tcrt_mask:   int  = 0
    tcrt_sx:     bool = False
    tcrt_centro: bool = False
    tcrt_dx:     bool = False

    # Servo — il Pi conosce le posizioni perché le ha scritte lui
    servo_pos: list = field(default_factory=lambda: [90, 90, 90, 90, 90, 120])

    ok: bool = False

    @property
    def ostacolo_vicino(self):
        lati = [self.us_fronte, self.us_retro, self.us_sinistra, self.us_destra]
        return any(v < 20 for v in lati if v != 9999)

    @property
    def cliff_rilevato(self):
        return any(v > 50 and v != 9999
                   for v in [self.us_cliff_f, self.us_cliff_r])

    def linea_str(self):
        sx  = "█" if self.tcrt_sx     else "░"
        cen = "█" if self.tcrt_centro else "░"
        dx  = "█" if self.tcrt_dx     else "░"
        return f"SX:{sx} CEN:{cen} DX:{dx}"


@dataclass
class StatoRobot:
    motori:  StatoMotori  = field(default_factory=StatoMotori)
    sensori: StatoSensori = field(default_factory=StatoSensori)
    ts:      float        = 0.0

# ────────────────────────────────────────────────────────────────
#  LETTURA I2C
# ────────────────────────────────────────────────────────────────

def leggi_motori(bus: smbus2.SMBus) -> StatoMotori:
    m = StatoMotori()
    try:
        raw = bus.read_i2c_block_data(ADDR_MOTORI, 0, LEN_MOTORI)
        m.enc_fl, m.enc_fr, m.enc_rl, m.enc_rr = struct.unpack_from('<4i', bytes(raw), 0)
        m.velocita = raw[16]
        m.stato    = raw[17]
        m.ok       = True
    except OSError:
        pass
    return m


def leggi_sensori(bus: smbus2.SMBus) -> StatoSensori:
    s = StatoSensori()
    try:
        raw = bus.read_i2c_block_data(ADDR_SENSORI, 0, LEN_SENSORI)
        b = bytes(raw)

        # 6x ultrasuoni uint16
        (s.us_fronte, s.us_retro, s.us_sinistra,
         s.us_destra, s.us_cliff_f, s.us_cliff_r) = struct.unpack_from('<6H', b, 0)

        # 6x IMU int16 (divisi per 100)
        ax, ay, az, gx, gy, gz = struct.unpack_from('<6h', b, 12)
        s.acc_x  = ax / 100.0
        s.acc_y  = ay / 100.0
        s.acc_z  = az / 100.0
        s.gyro_x = gx / 100.0
        s.gyro_y = gy / 100.0
        s.gyro_z = gz / 100.0

        # TCRT bitmask
        s.tcrt_mask   = raw[24]
        s.tcrt_sx     = bool(s.tcrt_mask & 0x01)
        s.tcrt_centro = bool(s.tcrt_mask & 0x02)
        s.tcrt_dx     = bool(s.tcrt_mask & 0x04)

        s.ok = True
    except OSError:
        pass
    return s

# ────────────────────────────────────────────────────────────────
#  STAMPA
# ────────────────────────────────────────────────────────────────

def fmt_us(v):
    return "  ---" if v == 9999 else f"{v:4d}cm"

def warn(v):
    return " ⚠" if v != 9999 and v < 20 else "  "

SEP = "─" * 58

def stampa_stato(stato: StatoRobot):
    os.system('clear')
    m = stato.motori
    s = stato.sensori
    ora = time.strftime('%H:%M:%S')

    print(f"╔{SEP}╗")
    print(f"║{'ROBOT MONITOR':^58}║")
    print(f"║{'aggiornamento: ' + ora:^58}║")
    print(f"╚{SEP}╝")
    print()

    # ── MOTORI ───────────────────────────────────────────────────
    print(f"┌── MOTORI  ESP32 addr 0x08 {'OK ✓' if m.ok else '❌ non risponde':>30}─┐")
    if m.ok:
        dirs = m.dir_ruote()
        print(f"│  Stato     : {m.stato_str:<20}  Vel: {m.velocita:3d}/255     │")
        print(f"│  Enc.medio : {m.enc_medio:8.1f} tick totali               │")
        print( "│                                                          │")
        print(f"│  FL (Ant.SX)  enc: {m.enc_fl:+8d}   {dirs['FL']}        │")
        print(f"│  FR (Ant.DX)  enc: {m.enc_fr:+8d}   {dirs['FR']}        │")
        print(f"│  RL (Post.SX) enc: {m.enc_rl:+8d}   {dirs['RL']}        │")
        print(f"│  RR (Post.DX) enc: {m.enc_rr:+8d}   {dirs['RR']}        │")
    else:
        print( "│  Nessun dato disponibile                                 │")
    print(f"└{SEP}┘")
    print()

    # ── SENSORI ──────────────────────────────────────────────────
    print(f"┌── SENSORI  ESP32 addr 0x09 {'OK ✓' if s.ok else '❌ non risponde':>29}─┐")
    if s.ok:
        print( "│  ULTRASUONI                                              │")
        print(f"│            FRONTE  : {fmt_us(s.us_fronte)}{warn(s.us_fronte)}                        │")
        print(f"│  SX: {fmt_us(s.us_sinistra)}{warn(s.us_sinistra)}   [robot]   DX: {fmt_us(s.us_destra)}{warn(s.us_destra)}        │")
        print(f"│            RETRO   : {fmt_us(s.us_retro)}{warn(s.us_retro)}                        │")
        print(f"│  Cliff  FRONTE: {fmt_us(s.us_cliff_f)}   RETRO: {fmt_us(s.us_cliff_r)}               │")

        alerts = []
        if s.ostacolo_vicino: alerts.append("⚠  OSTACOLO VICINO (<20 cm)")
        if s.cliff_rilevato:  alerts.append("⚠  BORDO RILEVATO")
        for a in alerts:
            print(f"│  {a:<56}│")

        print( "│                                                          │")
        print( "│  ACCELEROMETRO (g)                                       │")
        print(f"│  X: {s.acc_x:+7.3f}   Y: {s.acc_y:+7.3f}   Z: {s.acc_z:+7.3f}              │")
        print( "│  GIROSCOPIO (°/s)                                        │")
        print(f"│  X: {s.gyro_x:+7.3f}   Y: {s.gyro_y:+7.3f}   Z: {s.gyro_z:+7.3f}              │")

        print( "│                                                          │")
        print(f"│  LINE SENSOR TCRT5000:  {s.linea_str()}   mask: 0x{s.tcrt_mask:02X}      │")

        print( "│                                                          │")
        print( "│  SERVO BRACCIO (gradi inviati dal Pi)                    │")
        nomi = ["Base  ","Spalla","Gomito","Polso R","Polso P","Pinza  "]
        riga1 = "  ".join(f"{nomi[i]}:{s.servo_pos[i]:3d}°" for i in range(3))
        riga2 = "  ".join(f"{nomi[i]}:{s.servo_pos[i]:3d}°" for i in range(3, 6))
        print(f"│  {riga1}                    │")
        print(f"│  {riga2}                  │")
    else:
        print( "│  Nessun dato disponibile                                 │")
    print(f"└{SEP}┘")
    print()
    print("  Ctrl+C per uscire")

# ────────────────────────────────────────────────────────────────
#  MAIN
# ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Robot monitor I2C")
    parser.add_argument("--bus",      type=int,   default=1,   help="Bus I2C (default 1)")
    parser.add_argument("--interval", type=float, default=0.2, help="Secondi tra le letture (default 0.2)")
    args = parser.parse_args()

    try:
        bus = smbus2.SMBus(args.bus)
    except Exception as e:
        print(f"ERRORE apertura bus I2C {args.bus}: {e}")
        sys.exit(1)

    stato = StatoRobot()
    print(f"Bus I2C {args.bus} aperto. Lettura in corso... (Ctrl+C per uscire)")
    time.sleep(0.5)

    try:
        while True:
            stato.motori  = leggi_motori(bus)
            stato.sensori = leggi_sensori(bus)
            stato.ts      = time.time()
            stampa_stato(stato)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nMonitor fermato.")
    finally:
        bus.close()


if __name__ == "__main__":
    main()