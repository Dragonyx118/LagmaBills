#!/usr/bin/env python3
# default: motori 50Hz, sensori 33Hz, display 10Hz
#python3 robot_monitor.py

# oppure personalizzato
#python3 robot_monitor.py --motori-hz 100 --sensori-hz 50 --display-hz 20

"""
robot_monitor.py — lettura I2C multi-thread per ESP32 Motori (0x08) + Sensori (0x09)

  Thread motori  → legge 0x08 ogni ~20ms  (50 Hz)
  Thread sensori → legge 0x09 ogni ~30ms  (~33 Hz)
  Thread display → stampa ogni 100ms      (10 Hz, non blocca le letture)

Dipendenze:
    pip install smbus2 --break-system-packages

Uso:
    python3 robot_monitor.py
    python3 robot_monitor.py --bus 1
    python3 robot_monitor.py --motori-hz 50 --sensori-hz 33 --display-hz 10
"""

import smbus2
import struct
import time
import threading
import argparse
import os
import sys
from dataclasses import dataclass, field

# ── INDIRIZZI ────────────────────────────────────────────────────
ADDR_MOTORI  = 0x08
ADDR_SENSORI = 0x09
LEN_MOTORI   = 20
LEN_SENSORI  = 26

STATO_STR = {0: "FERMO", 1: "IN MOTO", 2: "ROT.PRECISA"}

# ────────────────────────────────────────────────────────────────
#  DATI CONDIVISI (protetti da lock)
# ────────────────────────────────────────────────────────────────

@dataclass
class StatoMotori:
    enc_fl:   int   = 0
    enc_fr:   int   = 0
    enc_rl:   int   = 0
    enc_rr:   int   = 0
    velocita: int   = 0
    stato:    int   = 0
    ok:       bool  = False
    hz:       float = 0.0   # frequenza di lettura effettiva

@dataclass
class StatoSensori:
    us_fronte:   int   = 9999
    us_retro:    int   = 9999
    us_sinistra: int   = 9999
    us_destra:   int   = 9999
    us_cliff_f:  int   = 9999
    us_cliff_r:  int   = 9999
    acc_x:  float = 0.0
    acc_y:  float = 0.0
    acc_z:  float = 0.0
    gyro_x: float = 0.0
    gyro_y: float = 0.0
    gyro_z: float = 0.0
    tcrt_mask:   int  = 0
    tcrt_sx:     bool = False
    tcrt_centro: bool = False
    tcrt_dx:     bool = False
    servo_pos: list = field(default_factory=lambda: [90, 90, 90, 90, 90, 120])
    ok:  bool  = False
    hz:  float = 0.0

# Stato globale + lock
motori  = StatoMotori()
sensori = StatoSensori()
lock_m  = threading.Lock()
lock_s  = threading.Lock()
stop_ev = threading.Event()

# ────────────────────────────────────────────────────────────────
#  THREAD LETTURA MOTORI
# ────────────────────────────────────────────────────────────────

def thread_motori(bus: smbus2.SMBus, interval: float):
    last = time.perf_counter()
    while not stop_ev.is_set():
        now = time.perf_counter()
        try:
            raw = bus.read_i2c_block_data(ADDR_MOTORI, 0, LEN_MOTORI)
            enc_fl, enc_fr, enc_rl, enc_rr = struct.unpack_from('<4i', bytes(raw), 0)
            vel   = raw[16]
            stato = raw[17]
            hz    = 1.0 / max(now - last, 1e-6)
            last  = now
            with lock_m:
                motori.enc_fl   = enc_fl
                motori.enc_fr   = enc_fr
                motori.enc_rl   = enc_rl
                motori.enc_rr   = enc_rr
                motori.velocita = vel
                motori.stato    = stato
                motori.ok       = True
                motori.hz       = hz
        except OSError:
            with lock_m:
                motori.ok = False

        elapsed = time.perf_counter() - now
        sleep_t = max(0.0, interval - elapsed)
        stop_ev.wait(sleep_t)

# ────────────────────────────────────────────────────────────────
#  THREAD LETTURA SENSORI
# ────────────────────────────────────────────────────────────────

def thread_sensori(bus: smbus2.SMBus, interval: float):
    last = time.perf_counter()
    while not stop_ev.is_set():
        now = time.perf_counter()
        try:
            raw = bus.read_i2c_block_data(ADDR_SENSORI, 0, LEN_SENSORI)
            b   = bytes(raw)
            us  = struct.unpack_from('<6H', b, 0)
            imu = struct.unpack_from('<6h', b, 12)
            tcrt = raw[24]
            hz   = 1.0 / max(now - last, 1e-6)
            last = now
            with lock_s:
                (sensori.us_fronte, sensori.us_retro, sensori.us_sinistra,
                 sensori.us_destra, sensori.us_cliff_f, sensori.us_cliff_r) = us
                sensori.acc_x  = imu[0] / 100.0
                sensori.acc_y  = imu[1] / 100.0
                sensori.acc_z  = imu[2] / 100.0
                sensori.gyro_x = imu[3] / 100.0
                sensori.gyro_y = imu[4] / 100.0
                sensori.gyro_z = imu[5] / 100.0
                sensori.tcrt_mask   = tcrt
                sensori.tcrt_sx     = bool(tcrt & 0x01)
                sensori.tcrt_centro = bool(tcrt & 0x02)
                sensori.tcrt_dx     = bool(tcrt & 0x04)
                sensori.ok  = True
                sensori.hz  = hz
        except OSError:
            with lock_s:
                sensori.ok = False

        elapsed = time.perf_counter() - now
        stop_ev.wait(max(0.0, interval - elapsed))

# ────────────────────────────────────────────────────────────────
#  DISPLAY
# ────────────────────────────────────────────────────────────────

def fmt_us(v):
    return "  ---" if v == 9999 else f"{v:4d}cm"

def warn(v):
    return "⚠" if v != 9999 and v < 20 else " "

def dir_str(v):
    if v > 2:  return "▲ AV "
    if v < -2: return "▼ IN "
    return             "■ ---"

SEP = "─" * 56

def display_loop(interval: float):
    while not stop_ev.is_set():
        t0 = time.perf_counter()

        # Snapshot atomico
        with lock_m:
            m_snap = StatoMotori(**motori.__dict__)
        with lock_s:
            s_snap = StatoSensori(**sensori.__dict__)

        os.system('clear')
        ora = time.strftime('%H:%M:%S')

        print(f"╔{SEP}╗")
        print(f"║{'  ROBOT MONITOR   ' + ora:^56}║")
        print(f"╚{SEP}╝")

        # ── MOTORI ───────────────────────────────────────────────
        stato_lbl = STATO_STR.get(m_snap.stato, "?")
        ok_lbl    = f"OK {m_snap.hz:4.0f}Hz" if m_snap.ok else "❌ NO RESP"
        print(f"\n┌── MOTORI 0x08  [{ok_lbl}] {'':>20}─┐")
        if m_snap.ok:
            print(f"│  Stato: {stato_lbl:<14}  Velocità: {m_snap.velocita:3d}/255         │")
            print( "│                                                        │")
            print(f"│  FL Ant.SX  enc:{m_snap.enc_fl:+9d}   {dir_str(m_snap.enc_fl)}              │")
            print(f"│  FR Ant.DX  enc:{m_snap.enc_fr:+9d}   {dir_str(m_snap.enc_fr)}              │")
            print(f"│  RL Post.SX enc:{m_snap.enc_rl:+9d}   {dir_str(m_snap.enc_rl)}              │")
            print(f"│  RR Post.DX enc:{m_snap.enc_rr:+9d}   {dir_str(m_snap.enc_rr)}              │")
        else:
            print( "│  Nessun dato                                           │")
        print(f"└{SEP}┘")

        # ── SENSORI ──────────────────────────────────────────────
        ok_lbl2 = f"OK {s_snap.hz:4.0f}Hz" if s_snap.ok else "❌ NO RESP"
        print(f"\n┌── SENSORI 0x09  [{ok_lbl2}] {'':>19}─┐")
        if s_snap.ok:
            # Ultrasuoni
            uf = fmt_us(s_snap.us_fronte);   wf = warn(s_snap.us_fronte)
            ur = fmt_us(s_snap.us_retro);    wr = warn(s_snap.us_retro)
            ul = fmt_us(s_snap.us_sinistra); wl = warn(s_snap.us_sinistra)
            ud = fmt_us(s_snap.us_destra);   wd = warn(s_snap.us_destra)
            print( "│  ULTRASUONI                                            │")
            print(f"│          FRONTE : {uf} {wf}                              │")
            print(f"│  SX: {ul} {wl}  [bot]  DX: {ud} {wd}              │")
            print(f"│          RETRO  : {ur} {wr}                              │")
            print(f"│  Cliff F: {fmt_us(s_snap.us_cliff_f)}    Cliff R: {fmt_us(s_snap.us_cliff_r)}           │")

            alerts = []
            if any(v < 20 for v in [s_snap.us_fronte, s_snap.us_retro,
                                     s_snap.us_sinistra, s_snap.us_destra] if v != 9999):
                alerts.append("⚠  OSTACOLO < 20cm")
            if any(v > 50 and v != 9999 for v in [s_snap.us_cliff_f, s_snap.us_cliff_r]):
                alerts.append("⚠  BORDO RILEVATO")
            for a in alerts:
                print(f"│  {a:<54}│")

            # IMU
            print( "│                                                        │")
            print( "│  IMU MPU-6050                                          │")
            print(f"│  Acc  X:{s_snap.acc_x:+6.2f}g  Y:{s_snap.acc_y:+6.2f}g  Z:{s_snap.acc_z:+6.2f}g        │")
            print(f"│  Gyro X:{s_snap.gyro_x:+6.1f}°/s Y:{s_snap.gyro_y:+6.1f}°/s Z:{s_snap.gyro_z:+6.1f}°/s   │")

            # TCRT
            sx  = "█" if s_snap.tcrt_sx     else "░"
            cen = "█" if s_snap.tcrt_centro else "░"
            dx  = "█" if s_snap.tcrt_dx     else "░"
            print( "│                                                        │")
            print(f"│  LINE TCRT:  SX:{sx} CEN:{cen} DX:{dx}   mask:0x{s_snap.tcrt_mask:02X}           │")

            # Servo
            nomi = ["Base","Spalla","Gomito","PolsoR","PolsoP","Pinza"]
            r1 = "  ".join(f"{nomi[i]}:{s_snap.servo_pos[i]:3d}°" for i in range(3))
            r2 = "  ".join(f"{nomi[i]}:{s_snap.servo_pos[i]:3d}°" for i in range(3, 6))
            print( "│                                                        │")
            print(f"│  SERVO:  {r1}                   │")
            print(f"│          {r2}                 │")
        else:
            print( "│  Nessun dato                                           │")
        print(f"└{SEP}┘")
        print("\n  Ctrl+C per uscire")

        elapsed = time.perf_counter() - t0
        stop_ev.wait(max(0.0, interval - elapsed))

# ────────────────────────────────────────────────────────────────
#  MAIN
# ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Robot monitor I2C multi-thread")
    parser.add_argument("--bus",        type=int,   default=1,    help="Bus I2C (default 1)")
    parser.add_argument("--motori-hz",  type=float, default=50.0, help="Hz lettura motori (default 50)")
    parser.add_argument("--sensori-hz", type=float, default=33.0, help="Hz lettura sensori (default 33)")
    parser.add_argument("--display-hz", type=float, default=10.0, help="Hz refresh display (default 10)")
    args = parser.parse_args()

    try:
        bus = smbus2.SMBus(args.bus)
    except Exception as e:
        print(f"ERRORE apertura I2C bus {args.bus}: {e}")
        sys.exit(1)

    t_mot = threading.Thread(
        target=thread_motori,
        args=(bus, 1.0 / args.motori_hz),
        daemon=True, name="motori"
    )
    t_sen = threading.Thread(
        target=thread_sensori,
        args=(bus, 1.0 / args.sensori_hz),
        daemon=True, name="sensori"
    )

    t_mot.start()
    t_sen.start()

    try:
        display_loop(1.0 / args.display_hz)
    except KeyboardInterrupt:
        print("\nChiusura...")
    finally:
        stop_ev.set()
        t_mot.join(timeout=1)
        t_sen.join(timeout=1)
        bus.close()
        print("Monitor fermato.")


if __name__ == "__main__":
    main()
