#!/usr/bin/env python3
#pip install smbus2 flask psutil --break-system-packages
#python3 robot_monitor_web.py               # normale con I2C
#python3 robot_monitor_web.py --demo        # test senza hardware (simula i dati)
#python3 robot_monitor_web.py --port 8080   # porta diversa

"""
robot_monitor_web.py — Dashboard web per robot con ESP32 (motori 0x08, sensori 0x09)
Serve una pagina HTML con aggiornamento in tempo reale via Server-Sent Events (SSE).

Dipendenze:
    pip install smbus2 flask psutil --break-system-packages

Avvio:
    python3 robot_monitor_web.py
    python3 robot_monitor_web.py --bus 1 --port 5000
    python3 robot_monitor_web.py --demo        # modalità demo senza I2C (per test)

Apri nel browser: http://<IP_RASPBERRY>:5000
"""

import argparse
import json
import math
import os
import platform
import re
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field

# ── DIPENDENZE OPZIONALI ─────────────────────────────────────────
try:
    import smbus2
    HAS_I2C = True
except ImportError:
    HAS_I2C = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from flask import Flask, Response, render_template_string

# ── INDIRIZZI I2C ────────────────────────────────────────────────
ADDR_MOTORI  = 0x08
ADDR_SENSORI = 0x09
LEN_MOTORI   = 20
LEN_SENSORI  = 26

STATO_STR = {0: "FERMO", 1: "IN MOTO", 2: "ROT.PRECISA"}

# ─────────────────────────────────────────────────────────────────
#  DATACLASS STATO
# ─────────────────────────────────────────────────────────────────

@dataclass
class StatoMotori:
    enc_fl: int = 0; enc_fr: int = 0
    enc_rl: int = 0; enc_rr: int = 0
    velocita: int = 0; stato: int = 0
    ok: bool = False; hz: float = 0.0

@dataclass
class StatoSensori:
    us_fronte: int = 9999; us_retro: int = 9999
    us_sinistra: int = 9999; us_destra: int = 9999
    us_cliff_f: int = 9999; us_cliff_r: int = 9999
    acc_x: float = 0.0; acc_y: float = 0.0; acc_z: float = 0.0
    gyro_x: float = 0.0; gyro_y: float = 0.0; gyro_z: float = 0.0
    tcrt_mask: int = 0
    tcrt_sx: bool = False; tcrt_centro: bool = False; tcrt_dx: bool = False
    servo_pos: list = field(default_factory=lambda: [90, 90, 90, 90, 90, 120])
    ok: bool = False; hz: float = 0.0

@dataclass
class StatoSistema:
    cpu_pct: float = 0.0
    cpu_temp: float = 0.0
    ram_used_mb: float = 0.0
    ram_total_mb: float = 0.0
    ram_pct: float = 0.0
    disk_used_gb: float = 0.0
    disk_total_gb: float = 0.0
    disk_pct: float = 0.0
    uptime_s: int = 0
    hostname: str = ""
    ip_wifi: str = ""
    ip_eth: str = ""
    ssid: str = ""
    freq_mhz: float = 0.0
    load1: float = 0.0; load5: float = 0.0; load15: float = 0.0
    throttled: bool = False
    ok: bool = False

motori  = StatoMotori()
sensori = StatoSensori()
sistema = StatoSistema()
lock_m  = threading.Lock()
lock_s  = threading.Lock()
lock_sys = threading.Lock()
stop_ev = threading.Event()

# ─────────────────────────────────────────────────────────────────
#  THREAD I2C — MOTORI
# ─────────────────────────────────────────────────────────────────

def thread_motori(bus, interval):
    last = time.perf_counter()
    while not stop_ev.is_set():
        now = time.perf_counter()
        try:
            raw = bus.read_i2c_block_data(ADDR_MOTORI, 0, LEN_MOTORI)
            enc_fl, enc_fr, enc_rl, enc_rr = struct.unpack_from('<4i', bytes(raw), 0)
            hz = 1.0 / max(now - last, 1e-6); last = now
            with lock_m:
                motori.enc_fl = enc_fl; motori.enc_fr = enc_fr
                motori.enc_rl = enc_rl; motori.enc_rr = enc_rr
                motori.velocita = raw[16]; motori.stato = raw[17]
                motori.ok = True; motori.hz = hz
        except OSError:
            with lock_m:
                motori.ok = False
        stop_ev.wait(max(0.0, interval - (time.perf_counter() - now)))

# ─────────────────────────────────────────────────────────────────
#  THREAD I2C — SENSORI
# ─────────────────────────────────────────────────────────────────

def thread_sensori(bus, interval):
    last = time.perf_counter()
    while not stop_ev.is_set():
        now = time.perf_counter()
        try:
            raw = bus.read_i2c_block_data(ADDR_SENSORI, 0, LEN_SENSORI)
            b   = bytes(raw)
            us  = struct.unpack_from('<6H', b, 0)
            imu = struct.unpack_from('<6h', b, 12)
            tcrt = raw[24]
            hz = 1.0 / max(now - last, 1e-6); last = now
            with lock_s:
                (sensori.us_fronte, sensori.us_retro, sensori.us_sinistra,
                 sensori.us_destra, sensori.us_cliff_f, sensori.us_cliff_r) = us
                sensori.acc_x  = imu[0]/100.0; sensori.acc_y = imu[1]/100.0; sensori.acc_z = imu[2]/100.0
                sensori.gyro_x = imu[3]/100.0; sensori.gyro_y = imu[4]/100.0; sensori.gyro_z = imu[5]/100.0
                sensori.tcrt_mask = tcrt
                sensori.tcrt_sx = bool(tcrt & 1); sensori.tcrt_centro = bool(tcrt & 2); sensori.tcrt_dx = bool(tcrt & 4)
                sensori.ok = True; sensori.hz = hz
        except OSError:
            with lock_s:
                sensori.ok = False
        stop_ev.wait(max(0.0, interval - (time.perf_counter() - now)))

# ─────────────────────────────────────────────────────────────────
#  THREAD DEMO (senza hardware reale)
# ─────────────────────────────────────────────────────────────────

def thread_demo():
    t = 0.0
    while not stop_ev.is_set():
        t += 0.1
        with lock_m:
            motori.enc_fl = int(math.sin(t) * 500)
            motori.enc_fr = int(math.sin(t + 0.1) * 500)
            motori.enc_rl = int(math.sin(t + 0.2) * 500)
            motori.enc_rr = int(math.sin(t + 0.3) * 500)
            motori.velocita = int(abs(math.sin(t)) * 200)
            motori.stato = int(t) % 3
            motori.ok = True; motori.hz = 50.0
        with lock_s:
            sensori.us_fronte  = max(5, int(50 + math.sin(t * 0.7) * 40))
            sensori.us_retro   = max(5, int(80 + math.cos(t * 0.5) * 30))
            sensori.us_sinistra = max(5, int(30 + math.sin(t * 1.1) * 20))
            sensori.us_destra  = max(5, int(40 + math.cos(t * 0.9) * 30))
            sensori.us_cliff_f = max(5, int(10 + abs(math.sin(t * 2)) * 5))
            sensori.us_cliff_r = max(5, int(12 + abs(math.cos(t * 1.5)) * 4))
            sensori.acc_x  = round(math.sin(t * 0.3), 2)
            sensori.acc_y  = round(math.cos(t * 0.2), 2)
            sensori.acc_z  = round(9.81 + math.sin(t * 0.1) * 0.05, 2)
            sensori.gyro_x = round(math.sin(t) * 5, 1)
            sensori.gyro_y = round(math.cos(t * 1.2) * 3, 1)
            sensori.gyro_z = round(math.sin(t * 0.8) * 2, 1)
            sensori.tcrt_mask = int(t * 2) % 8
            sensori.tcrt_sx = bool(sensori.tcrt_mask & 1)
            sensori.tcrt_centro = bool(sensori.tcrt_mask & 2)
            sensori.tcrt_dx = bool(sensori.tcrt_mask & 4)
            sensori.servo_pos = [
                int(90 + math.sin(t * 0.5) * 45),
                int(90 + math.cos(t * 0.4) * 30),
                int(90 + math.sin(t * 0.6) * 40),
                int(90 + math.cos(t * 0.7) * 20),
                int(90 + math.sin(t * 0.3) * 30),
                int(120 + math.cos(t * 0.8) * 30),
            ]
            sensori.ok = True; sensori.hz = 33.0
        stop_ev.wait(0.1)

# ─────────────────────────────────────────────────────────────────
#  THREAD SISTEMA
# ─────────────────────────────────────────────────────────────────

def _get_wifi_ssid():
    try:
        out = subprocess.check_output(['iwgetid', '-r'], stderr=subprocess.DEVNULL, timeout=2).decode().strip()
        return out if out else ""
    except Exception:
        return ""

def _get_ip(iface):
    if not HAS_PSUTIL:
        return ""
    addrs = psutil.net_if_addrs().get(iface, [])
    for a in addrs:
        if a.family == socket.AF_INET:
            return a.address
    return ""

def _get_throttled():
    try:
        out = subprocess.check_output(['vcgencmd', 'get_throttled'], stderr=subprocess.DEVNULL, timeout=2).decode()
        val = int(out.strip().split('=')[1], 16)
        return bool(val & 0x000F)
    except Exception:
        return False

def _get_cpu_temp():
    # Prova psutil
    if HAS_PSUTIL:
        try:
            temps = psutil.sensors_temperatures()
            for key in ('cpu_thermal', 'coretemp', 'k10temp', 'acpitz'):
                if key in temps and temps[key]:
                    return temps[key][0].current
        except Exception:
            pass
    # Fallback: file di sistema Raspberry Pi
    try:
        with open('/sys/class/thermal/thermal_zone0/temp') as f:
            return int(f.read().strip()) / 1000.0
    except Exception:
        return 0.0

def thread_sistema(interval):
    boot_time = psutil.boot_time() if HAS_PSUTIL else time.time()
    while not stop_ev.is_set():
        try:
            s = StatoSistema()
            s.hostname = socket.gethostname()
            if HAS_PSUTIL:
                s.cpu_pct = psutil.cpu_percent(interval=None)
                mem = psutil.virtual_memory()
                s.ram_used_mb  = mem.used / 1024**2
                s.ram_total_mb = mem.total / 1024**2
                s.ram_pct      = mem.percent
                disk = psutil.disk_usage('/')
                s.disk_used_gb  = disk.used / 1024**3
                s.disk_total_gb = disk.total / 1024**3
                s.disk_pct      = disk.percent
                try:
                    la = os.getloadavg()
                    s.load1, s.load5, s.load15 = la
                except Exception:
                    pass
                try:
                    freq = psutil.cpu_freq()
                    s.freq_mhz = freq.current if freq else 0.0
                except Exception:
                    pass
                # Interfacce di rete
                for iface in ('wlan0', 'wlp2s0', 'wlp3s0'):
                    ip = _get_ip(iface)
                    if ip:
                        s.ip_wifi = ip
                        break
                for iface in ('eth0', 'enp2s0', 'eno1'):
                    ip = _get_ip(iface)
                    if ip:
                        s.ip_eth = ip
                        break
            s.cpu_temp  = _get_cpu_temp()
            s.uptime_s  = int(time.time() - boot_time)
            s.ssid      = _get_wifi_ssid()
            s.throttled = _get_throttled()
            s.ok        = True
            with lock_sys:
                sistema.__dict__.update(s.__dict__)
        except Exception as e:
            with lock_sys:
                sistema.ok = False
        stop_ev.wait(interval)

# ─────────────────────────────────────────────────────────────────
#  SSE — STREAM DATI
# ─────────────────────────────────────────────────────────────────

def sse_stream():
    """Genera un flusso SSE con tutti i dati ogni 200ms."""
    while not stop_ev.is_set():
        with lock_m:
            m = asdict(motori)
        with lock_s:
            s = asdict(sensori)
        with lock_sys:
            sys_d = asdict(sistema)

        payload = {"motori": m, "sensori": s, "sistema": sys_d, "ts": time.time()}
        yield f"data: {json.dumps(payload)}\n\n"
        time.sleep(0.2)

# ─────────────────────────────────────────────────────────────────
#  HTML DASHBOARD
# ─────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Robot Monitor</title>
<style>
  :root{
    --bg:#0d1117;--surface:#161b22;--surface2:#21262d;
    --border:#30363d;--text:#e6edf3;--muted:#8b949e;
    --green:#3fb950;--red:#f85149;--yellow:#d29922;--blue:#58a6ff;
    --orange:#ffa657;--purple:#bc8cff;--teal:#39d353;
    --font:'JetBrains Mono','Fira Mono','Consolas',monospace;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--bg);color:var(--text);font-family:var(--font);font-size:13px;line-height:1.5}
  header{background:var(--surface);border-bottom:1px solid var(--border);padding:12px 20px;display:flex;align-items:center;gap:16px;position:sticky;top:0;z-index:10}
  header h1{font-size:15px;font-weight:600;color:var(--text)}
  .badge{font-size:11px;padding:2px 8px;border-radius:20px;background:var(--surface2);border:1px solid var(--border);color:var(--muted)}
  .badge.live{border-color:var(--green);color:var(--green)}
  .badge.demo{border-color:var(--yellow);color:var(--yellow)}
  #ts{margin-left:auto;color:var(--muted);font-size:11px}

  main{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:12px;padding:16px}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px}
  .card-title{font-size:11px;font-weight:600;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:10px;display:flex;align-items:center;gap:6px}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--muted)}
  .dot.ok{background:var(--green);box-shadow:0 0 6px var(--green)}
  .dot.err{background:var(--red);box-shadow:0 0 6px var(--red)}

  /* metriche */
  .metric-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .metric{background:var(--surface2);border-radius:6px;padding:8px 10px}
  .metric .label{font-size:10px;color:var(--muted);margin-bottom:2px}
  .metric .value{font-size:18px;font-weight:600}

  /* barre */
  .bar-row{display:flex;align-items:center;gap:8px;margin-bottom:6px}
  .bar-row .lbl{width:60px;font-size:11px;color:var(--muted);flex-shrink:0}
  .bar-wrap{flex:1;height:6px;background:var(--surface2);border-radius:3px;overflow:hidden}
  .bar-fill{height:100%;border-radius:3px;transition:width .3s ease}
  .bar-row .val{width:44px;text-align:right;font-size:11px}

  /* encoder */
  .enc-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
  .enc-box{background:var(--surface2);border-radius:6px;padding:8px}
  .enc-box .lbl{font-size:10px;color:var(--muted)}
  .enc-box .num{font-size:16px;font-weight:600;font-variant-numeric:tabular-nums}

  /* ultrasuoni */
  .us-layout{display:grid;grid-template-areas:'.. fr .''sl . dr''.. rr .';grid-template-columns:1fr 80px 1fr;gap:6px;text-align:center;margin:4px 0}
  .us-box{background:var(--surface2);border-radius:6px;padding:6px 4px}
  .us-box .lbl{font-size:9px;color:var(--muted)}
  .us-box .val{font-size:14px;font-weight:600}
  .us-fr{grid-area:fr}.us-sl{grid-area:sl;align-self:center}.us-dr{grid-area:dr;align-self:center}.us-rr{grid-area:rr}
  .robot-icon{grid-area:. / . / . / .;background:var(--surface2);border:1px solid var(--border);border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:24px;color:var(--muted)}
  .warn{color:var(--red) !important}

  /* tcrt */
  .tcrt-dots{display:flex;gap:10px;justify-content:center;margin:8px 0}
  .tcrt-d{width:28px;height:28px;border-radius:50%;background:var(--surface2);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;font-size:9px;color:var(--muted);transition:all .2s}
  .tcrt-d.active{background:#d29922;border-color:#d29922;color:#000;box-shadow:0 0 8px #d29922}

  /* servo */
  .servo-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
  .servo-box{background:var(--surface2);border-radius:6px;padding:6px;text-align:center}
  .servo-box .slbl{font-size:9px;color:var(--muted)}
  .servo-arc-wrap{position:relative;width:50px;height:30px;margin:4px auto}
  .servo-arc-wrap svg{width:50px;height:30px}

  /* imu */
  .imu-row{display:flex;gap:6px;margin-bottom:4px}
  .imu-axis{flex:1;background:var(--surface2);border-radius:5px;padding:5px;text-align:center}
  .imu-axis .albl{font-size:9px;color:var(--muted)}
  .imu-axis .aval{font-size:13px;font-weight:600}

  /* sistema */
  .net-row{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid var(--border);font-size:12px}
  .net-row:last-child{border-bottom:none}
  .net-lbl{color:var(--muted)}

  .chip{display:inline-block;padding:1px 6px;border-radius:4px;font-size:10px;font-weight:600}
  .chip.ok{background:rgba(63,185,80,.15);color:var(--green);border:1px solid rgba(63,185,80,.3)}
  .chip.warn{background:rgba(210,153,34,.15);color:var(--yellow);border:1px solid rgba(210,153,34,.3)}
  .chip.err{background:rgba(248,81,73,.15);color:var(--red);border:1px solid rgba(248,81,73,.3)}

  #uptime{color:var(--blue)}
  footer{text-align:center;padding:12px;color:var(--muted);font-size:10px;border-top:1px solid var(--border)}
</style>
</head>
<body>

<header>
  <h1>&#x25B6; Robot Monitor</h1>
  <span id="badge-live" class="badge">connecting...</span>
  <span id="badge-hz" class="badge">0 fps</span>
  <span id="ts">--:--:--</span>
</header>

<main>

  <!-- MOTORI -->
  <div class="card">
    <div class="card-title"><span class="dot" id="dot-mot"></span> Motori I2C 0x08 <span id="hz-mot" style="margin-left:auto;font-size:10px;color:var(--muted)"></span></div>
    <div style="margin-bottom:10px">
      <div class="metric-grid">
        <div class="metric"><div class="label">Stato</div><div class="value" id="stato-lbl" style="font-size:13px">---</div></div>
        <div class="metric"><div class="label">Velocità</div><div class="value" id="vel"></div></div>
      </div>
    </div>
    <div class="bar-row">
      <span class="lbl">Velocità</span>
      <div class="bar-wrap"><div class="bar-fill" id="vel-bar" style="background:var(--blue)"></div></div>
      <span class="val" id="vel-val">0/255</span>
    </div>
    <div style="margin-top:10px">
      <div class="enc-grid">
        <div class="enc-box"><div class="lbl">FL Ant.SX</div><div class="num" id="enc-fl">0</div></div>
        <div class="enc-box"><div class="lbl">FR Ant.DX</div><div class="num" id="enc-fr">0</div></div>
        <div class="enc-box"><div class="lbl">RL Post.SX</div><div class="num" id="enc-rl">0</div></div>
        <div class="enc-box"><div class="lbl">RR Post.DX</div><div class="num" id="enc-rr">0</div></div>
      </div>
    </div>
  </div>

  <!-- ULTRASUONI -->
  <div class="card">
    <div class="card-title"><span class="dot" id="dot-sen"></span> Ultrasuoni <span id="hz-sen" style="margin-left:auto;font-size:10px;color:var(--muted)"></span></div>
    <div class="us-layout">
      <div></div>
      <div class="us-box us-fr"><div class="lbl">FRONTE</div><div class="val" id="us-fr">---</div></div>
      <div></div>
      <div class="us-box us-sl"><div class="lbl">SX</div><div class="val" id="us-sl">---</div></div>
      <div class="robot-icon">&#x25A6;</div>
      <div class="us-box us-dr"><div class="lbl">DX</div><div class="val" id="us-dr">---</div></div>
      <div></div>
      <div class="us-box us-rr"><div class="lbl">RETRO</div><div class="val" id="us-rr">---</div></div>
      <div></div>
    </div>
    <div style="display:flex;gap:8px;margin-top:8px">
      <div class="us-box" style="flex:1"><div class="lbl">Cliff F</div><div class="val" id="us-clf">---</div></div>
      <div class="us-box" style="flex:1"><div class="lbl">Cliff R</div><div class="val" id="us-clr">---</div></div>
    </div>
    <div id="alert-box" style="margin-top:8px;display:none;padding:6px 10px;border-radius:5px;font-size:11px;background:rgba(248,81,73,.12);border:1px solid rgba(248,81,73,.3);color:var(--red)"></div>
  </div>

  <!-- IMU -->
  <div class="card">
    <div class="card-title">IMU MPU-6050</div>
    <div style="font-size:10px;color:var(--muted);margin-bottom:6px">Accelerometro (g)</div>
    <div class="imu-row">
      <div class="imu-axis"><div class="albl">X</div><div class="aval" id="acc-x">0.00</div></div>
      <div class="imu-axis"><div class="albl">Y</div><div class="aval" id="acc-y">0.00</div></div>
      <div class="imu-axis"><div class="albl">Z</div><div class="aval" id="acc-z">0.00</div></div>
    </div>
    <div style="font-size:10px;color:var(--muted);margin:8px 0 6px">Giroscopio (°/s)</div>
    <div class="imu-row">
      <div class="imu-axis"><div class="albl">X</div><div class="aval" id="gyr-x">0.0</div></div>
      <div class="imu-axis"><div class="albl">Y</div><div class="aval" id="gyr-y">0.0</div></div>
      <div class="imu-axis"><div class="albl">Z</div><div class="aval" id="gyr-z">0.0</div></div>
    </div>
    <!-- mini inclinometro visuale -->
    <div style="margin-top:12px;text-align:center">
      <svg id="incl-svg" viewBox="-50 -50 100 100" width="100" height="100" style="display:inline-block">
        <circle cx="0" cy="0" r="48" fill="none" stroke="#30363d" stroke-width="1"/>
        <circle cx="0" cy="0" r="32" fill="none" stroke="#30363d" stroke-width=".5" stroke-dasharray="4 4"/>
        <circle id="incl-dot" cx="0" cy="0" r="8" fill="var(--blue)" opacity=".85"/>
        <line id="incl-arm" x1="0" y1="0" x2="0" y2="-40" stroke="var(--blue)" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
    </div>
  </div>

  <!-- LINE SENSOR + SERVO -->
  <div class="card">
    <div class="card-title">Line sensor TCRT5000</div>
    <div class="tcrt-dots">
      <div class="tcrt-d" id="tcrt-sx">SX</div>
      <div class="tcrt-d" id="tcrt-cen">CEN</div>
      <div class="tcrt-d" id="tcrt-dx">DX</div>
    </div>
    <div style="text-align:center;font-size:10px;color:var(--muted);margin-bottom:12px">Mask: <span id="tcrt-mask">0x00</span></div>
    <div class="card-title" style="margin-top:4px">Servo braccio</div>
    <div class="servo-grid" id="servo-grid"></div>
  </div>

  <!-- CPU / RAM / DISCO -->
  <div class="card">
    <div class="card-title">&#x2699; Sistema Raspberry Pi</div>
    <div class="bar-row">
      <span class="lbl">CPU</span>
      <div class="bar-wrap"><div class="bar-fill" id="bar-cpu" style="background:var(--purple)"></div></div>
      <span class="val" id="val-cpu">0%</span>
    </div>
    <div class="bar-row">
      <span class="lbl">RAM</span>
      <div class="bar-wrap"><div class="bar-fill" id="bar-ram" style="background:var(--blue)"></div></div>
      <span class="val" id="val-ram">0%</span>
    </div>
    <div class="bar-row">
      <span class="lbl">Disco</span>
      <div class="bar-wrap"><div class="bar-fill" id="bar-disk" style="background:var(--orange)"></div></div>
      <span class="val" id="val-disk">0%</span>
    </div>
    <div style="margin-top:12px" class="metric-grid">
      <div class="metric">
        <div class="label">Temperatura CPU</div>
        <div class="value" id="cpu-temp" style="color:var(--orange)">0°C</div>
      </div>
      <div class="metric">
        <div class="label">Frequenza</div>
        <div class="value" id="cpu-freq" style="font-size:14px">0 MHz</div>
      </div>
    </div>
    <div style="margin-top:8px" class="metric-grid">
      <div class="metric">
        <div class="label">RAM usata</div>
        <div class="value" id="ram-detail" style="font-size:13px">0/0 MB</div>
      </div>
      <div class="metric">
        <div class="label">Disco usato</div>
        <div class="value" id="disk-detail" style="font-size:13px">0/0 GB</div>
      </div>
    </div>
  </div>

  <!-- RETE + INFO SISTEMA -->
  <div class="card">
    <div class="card-title">&#x1F4BB; Info sistema</div>
    <div class="net-row"><span class="net-lbl">Hostname</span><span id="sys-host">---</span></div>
    <div class="net-row"><span class="net-lbl">WiFi (wlan0)</span><span id="sys-wifi">---</span></div>
    <div class="net-row"><span class="net-lbl">Ethernet (eth0)</span><span id="sys-eth">---</span></div>
    <div class="net-row"><span class="net-lbl">SSID</span><span id="sys-ssid">---</span></div>
    <div class="net-row"><span class="net-lbl">Uptime</span><span id="uptime">---</span></div>
    <div class="net-row">
      <span class="net-lbl">Load avg</span>
      <span id="load-avg" style="font-size:11px">---</span>
    </div>
    <div class="net-row">
      <span class="net-lbl">Throttling</span>
      <span id="throttled">---</span>
    </div>
  </div>

  <!-- LOAD AVG CHART -->
  <div class="card" style="grid-column:span 2">
    <div class="card-title">Storico CPU</div>
    <div style="position:relative;width:100%;height:160px"><canvas id="cpu-chart"></canvas></div>
  </div>

</main>
<footer>robot_monitor_web.py &mdash; aggiornamento ogni 200ms via SSE</footer>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
// ── Chart.js storico CPU ──────────────────────────────────────
const MAX_PTS = 120;
const cpuHistory = Array(MAX_PTS).fill(0);
const tempHistory = Array(MAX_PTS).fill(0);
const cpuCtx = document.getElementById('cpu-chart');
const cpuChart = new Chart(cpuCtx, {
  type: 'line',
  data: {
    labels: Array(MAX_PTS).fill(''),
    datasets: [
      { label: 'CPU %', data: cpuHistory, borderColor: '#bc8cff', backgroundColor: 'rgba(188,140,255,.1)', borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3 },
      { label: 'Temp °C', data: tempHistory, borderColor: '#ffa657', backgroundColor: 'rgba(255,166,87,.08)', borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3, yAxisID: 'y2' }
    ]
  },
  options: {
    responsive: true, maintainAspectRatio: false, animation: false,
    plugins: { legend: { display: false } },
    scales: {
      x: { display: false },
      y:  { min: 0, max: 100, grid: { color: '#21262d' }, ticks: { color: '#8b949e', font: { size: 10 } } },
      y2: { position: 'right', min: 0, max: 100, grid: { drawOnChartArea: false }, ticks: { color: '#ffa657', font: { size: 10 } } }
    }
  }
});

// ── Servo SVG ────────────────────────────────────────────────
const SERVO_NAMES = ['Base','Spalla','Gomito','PolsoR','PolsoP','Pinza'];
const sg = document.getElementById('servo-grid');
SERVO_NAMES.forEach((n, i) => {
  sg.innerHTML += `<div class="servo-box">
    <div class="slbl">${n}</div>
    <div class="servo-arc-wrap">
      <svg viewBox="0 0 50 30" xmlns="http://www.w3.org/2000/svg">
        <path d="M5,28 A20,20 0 0,1 45,28" fill="none" stroke="#30363d" stroke-width="2" stroke-linecap="round"/>
        <line id="srv${i}" x1="25" y1="28" x2="25" y2="10" stroke="#58a6ff" stroke-width="2.5" stroke-linecap="round"/>
      </svg>
    </div>
    <div style="font-size:11px;font-weight:600" id="sval${i}">90°</div>
  </div>`;
});

function updateServo(i, deg) {
  const line = document.getElementById('srv' + i);
  if (!line) return;
  const rad = ((deg - 90) * Math.PI) / 180;
  const x2 = 25 + 18 * Math.sin(rad);
  const y2 = 28 - 18 * Math.cos(rad);
  line.setAttribute('x2', x2.toFixed(1));
  line.setAttribute('y2', y2.toFixed(1));
  document.getElementById('sval' + i).textContent = deg + '°';
}

// ── helpers ──────────────────────────────────────────────────
function setBar(id, pct) {
  const el = document.getElementById(id);
  if (!el) return;
  el.style.width = Math.min(100, pct).toFixed(1) + '%';
  if (pct > 85) el.style.background = 'var(--red)';
  else if (pct > 60) el.style.background = 'var(--yellow)';
}
function fmtUptime(s) {
  const d = Math.floor(s/86400), h = Math.floor((s%86400)/3600),
        m = Math.floor((s%3600)/60), sec = s%60;
  if (d > 0) return `${d}g ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  return `${m}m ${sec}s`;
}
function fmtUs(v) { return v === 9999 ? '---' : v + ' cm'; }
function warnClass(v, thr) { return (v !== 9999 && v < thr) ? 'warn' : ''; }

let lastTs = 0, fpsCnt = 0, fpsTimer = Date.now();

// ── SSE ──────────────────────────────────────────────────────
const evs = new EventSource('/events');

evs.onopen = () => {
  document.getElementById('badge-live').className = 'badge live';
  document.getElementById('badge-live').textContent = 'LIVE';
};
evs.onerror = () => {
  document.getElementById('badge-live').className = 'badge err';
  document.getElementById('badge-live').textContent = 'disconnesso';
};

evs.onmessage = (e) => {
  const d = JSON.parse(e.data);
  const m = d.motori, s = d.sensori, sys = d.sistema;

  // FPS
  fpsCnt++;
  const now = Date.now();
  if (now - fpsTimer >= 1000) {
    document.getElementById('badge-hz').textContent = fpsCnt + ' fps';
    fpsCnt = 0; fpsTimer = now;
  }
  document.getElementById('ts').textContent = new Date(d.ts*1000).toLocaleTimeString('it-IT');

  // ── MOTORI ──
  const dotM = document.getElementById('dot-mot');
  dotM.className = 'dot ' + (m.ok ? 'ok' : 'err');
  document.getElementById('hz-mot').textContent = m.ok ? m.hz.toFixed(0)+'Hz' : 'NO RESP';
  document.getElementById('stato-lbl').textContent = ['FERMO','IN MOTO','ROT.PRECISA'][m.stato] || '?';
  document.getElementById('vel').textContent = m.velocita;
  const velPct = (m.velocita/255)*100;
  document.getElementById('vel-bar').style.width = velPct+'%';
  document.getElementById('vel-val').textContent = m.velocita+'/255';
  document.getElementById('enc-fl').textContent = (m.enc_fl >= 0 ? '+':'')+m.enc_fl;
  document.getElementById('enc-fr').textContent = (m.enc_fr >= 0 ? '+':'')+m.enc_fr;
  document.getElementById('enc-rl').textContent = (m.enc_rl >= 0 ? '+':'')+m.enc_rl;
  document.getElementById('enc-rr').textContent = (m.enc_rr >= 0 ? '+':'')+m.enc_rr;

  // ── SENSORI ──
  const dotS = document.getElementById('dot-sen');
  dotS.className = 'dot ' + (s.ok ? 'ok' : 'err');
  document.getElementById('hz-sen').textContent = s.ok ? s.hz.toFixed(0)+'Hz' : 'NO RESP';

  ['fr','retro','sinistra','destra'].forEach((k,i) => {
    const val = [s.us_fronte, s.us_retro, s.us_sinistra, s.us_destra][i];
    const ids = ['us-fr','us-rr','us-sl','us-dr'][i];
    const el = document.getElementById(ids);
    el.textContent = fmtUs(val);
    el.className = 'val ' + warnClass(val, 20);
  });
  document.getElementById('us-clf').textContent = fmtUs(s.us_cliff_f);
  document.getElementById('us-clr').textContent = fmtUs(s.us_cliff_r);

  // Alert
  const alerts = [];
  if ([s.us_fronte,s.us_retro,s.us_sinistra,s.us_destra].some(v=>v!==9999&&v<20))
    alerts.push('⚠ OSTACOLO < 20cm');
  if ([s.us_cliff_f,s.us_cliff_r].some(v=>v>50&&v!==9999))
    alerts.push('⚠ BORDO RILEVATO');
  const ab = document.getElementById('alert-box');
  ab.style.display = alerts.length ? 'block' : 'none';
  ab.textContent = alerts.join('  ');

  // IMU
  document.getElementById('acc-x').textContent = s.acc_x.toFixed(2);
  document.getElementById('acc-y').textContent = s.acc_y.toFixed(2);
  document.getElementById('acc-z').textContent = s.acc_z.toFixed(2);
  document.getElementById('gyr-x').textContent = s.gyro_x.toFixed(1);
  document.getElementById('gyr-y').textContent = s.gyro_y.toFixed(1);
  document.getElementById('gyr-z').textContent = s.gyro_z.toFixed(1);

  // Inclinometro
  const ax = Math.max(-1, Math.min(1, s.acc_x));
  const ay = Math.max(-1, Math.min(1, s.acc_y));
  const px = ax * 36, py = ay * 36;
  document.getElementById('incl-dot').setAttribute('cx', px.toFixed(1));
  document.getElementById('incl-dot').setAttribute('cy', py.toFixed(1));
  document.getElementById('incl-arm').setAttribute('x2', px.toFixed(1));
  document.getElementById('incl-arm').setAttribute('y2', py.toFixed(1));

  // TCRT
  document.getElementById('tcrt-sx').className = 'tcrt-d' + (s.tcrt_sx ? ' active':'');
  document.getElementById('tcrt-cen').className = 'tcrt-d' + (s.tcrt_centro ? ' active':'');
  document.getElementById('tcrt-dx').className = 'tcrt-d' + (s.tcrt_dx ? ' active':'');
  document.getElementById('tcrt-mask').textContent = '0x'+s.tcrt_mask.toString(16).padStart(2,'0').toUpperCase();

  // Servo
  (s.servo_pos||[]).forEach((deg, i) => updateServo(i, deg));

  // ── SISTEMA ──
  setBar('bar-cpu', sys.cpu_pct);
  document.getElementById('val-cpu').textContent = sys.cpu_pct.toFixed(0)+'%';
  setBar('bar-ram', sys.ram_pct);
  document.getElementById('val-ram').textContent = sys.ram_pct.toFixed(0)+'%';
  setBar('bar-disk', sys.disk_pct);
  document.getElementById('val-disk').textContent = sys.disk_pct.toFixed(0)+'%';

  const t = sys.cpu_temp;
  const tc = document.getElementById('cpu-temp');
  tc.textContent = t.toFixed(1)+'°C';
  tc.style.color = t > 80 ? 'var(--red)' : t > 65 ? 'var(--yellow)' : 'var(--orange)';

  document.getElementById('cpu-freq').textContent = sys.freq_mhz.toFixed(0)+' MHz';
  document.getElementById('ram-detail').textContent = sys.ram_used_mb.toFixed(0)+'/'+sys.ram_total_mb.toFixed(0)+' MB';
  document.getElementById('disk-detail').textContent = sys.disk_used_gb.toFixed(1)+'/'+sys.disk_total_gb.toFixed(0)+' GB';

  document.getElementById('sys-host').textContent = sys.hostname||'---';
  document.getElementById('sys-wifi').textContent = sys.ip_wifi||'non connesso';
  document.getElementById('sys-eth').textContent  = sys.ip_eth||'non connesso';
  document.getElementById('sys-ssid').textContent = sys.ssid||'---';
  document.getElementById('uptime').textContent   = fmtUptime(sys.uptime_s);
  document.getElementById('load-avg').textContent =
    sys.load1.toFixed(2)+' / '+sys.load5.toFixed(2)+' / '+sys.load15.toFixed(2);
  const thr = document.getElementById('throttled');
  thr.innerHTML = sys.throttled
    ? '<span class="chip warn">THROTTLED</span>'
    : '<span class="chip ok">OK</span>';

  // Chart storico
  cpuHistory.push(sys.cpu_pct);
  cpuHistory.shift();
  tempHistory.push(sys.cpu_temp);
  tempHistory.shift();
  cpuChart.update('none');
};
</script>
</body>
</html>"""

# ─────────────────────────────────────────────────────────────────
#  FLASK APP
# ─────────────────────────────────────────────────────────────────

app = Flask(__name__)

@app.route('/')
def index():
    return HTML

@app.route('/events')
def events():
    return Response(sse_stream(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@app.route('/api/data')
def api_data():
    with lock_m:
        m = asdict(motori)
    with lock_s:
        s = asdict(sensori)
    with lock_sys:
        sys_d = asdict(sistema)
    return {"motori": m, "sensori": s, "sistema": sys_d}

# ─────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Robot Monitor Web Dashboard")
    parser.add_argument("--bus",        type=int,   default=1,    help="Bus I2C (default 1)")
    parser.add_argument("--port",       type=int,   default=5000, help="Porta HTTP (default 5000)")
    parser.add_argument("--motori-hz",  type=float, default=50.0)
    parser.add_argument("--sensori-hz", type=float, default=33.0)
    parser.add_argument("--demo",       action="store_true",      help="Modalità demo senza hardware I2C")
    args = parser.parse_args()

    if not HAS_PSUTIL:
        print("[WARN] psutil non trovato: installa con  pip install psutil --break-system-packages")

    if args.demo:
        print("[DEMO] Avvio in modalità demo (nessun hardware I2C richiesto)")
        td = threading.Thread(target=thread_demo, daemon=True, name="demo")
        td.start()
    else:
        if not HAS_I2C:
            print("ERRORE: smbus2 non installato. Usa:  pip install smbus2 --break-system-packages")
            sys.exit(1)
        try:
            bus = smbus2.SMBus(args.bus)
        except Exception as e:
            print(f"ERRORE apertura I2C bus {args.bus}: {e}")
            print("Suggerimento: prova --demo per testare senza hardware")
            sys.exit(1)

        threading.Thread(target=thread_motori,  args=(bus, 1.0/args.motori_hz),  daemon=True).start()
        threading.Thread(target=thread_sensori, args=(bus, 1.0/args.sensori_hz), daemon=True).start()

    threading.Thread(target=thread_sistema, args=(2.0,), daemon=True).start()

    local_ip = socket.gethostbyname(socket.gethostname())
    print(f"\n  Dashboard disponibile su:")
    print(f"    http://localhost:{args.port}")
    print(f"    http://{local_ip}:{args.port}")
    print(f"\n  Ctrl+C per fermare\n")

    try:
        app.run(host='0.0.0.0', port=args.port, threaded=True, use_reloader=False)
    except KeyboardInterrupt:
        print("\nChiusura...")
    finally:
        stop_ev.set()

if __name__ == "__main__":
    main()