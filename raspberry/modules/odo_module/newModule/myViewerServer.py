"""
mapViewerServer.py — v3 (GPS integrato)
LagmaBills — Visualizzatore web con:
  - Tab 1: Occupancy Grid (mappa locale encoder)
  - Tab 2: GPS Live (OpenStreetMap + traccia percorso)

Novità v3:
  - Thread gps_thread legge NEO-6M su seriale (/dev/ttyS0)
    e pubblica su robot/gps/posizione
  - Il viewer riceve i dati GPS via WebSocket e li mostra
    su mappa Leaflet (OpenStreetMap) con traccia e pannello dati
  - Fallback: se il GPS non è disponibile la tab mostra errore
    senza crashare il resto del server

Dipendenze: pip install paho-mqtt websockets pyserial pynmea2
Avvio: python3 mapViewerServer.py
Apri: http://<ip-raspberry>:8080
"""

import asyncio
import json
import threading
import time
import serial
import pynmea2
from http.server import HTTPServer, BaseHTTPRequestHandler
import paho.mqtt.client as mqtt
import websockets

MQTT_BROKER  = "localhost"
MQTT_PORT    = 1883
WS_PORT      = 8765
HTTP_PORT    = 8080

GPS_PORT     = "/dev/ttyS0"   # cambia in /dev/ttyUSB0 se usi adattatore USB
GPS_BAUD     = 9600
GPS_TOPIC    = "robot/gps/posizione"

latest_map   = None
latest_cliff = None
latest_nav   = None
latest_gps   = None          # ultimo fix GPS
map_lock     = threading.Lock()
ws_clients   = set()
ws_loop      = None
mqtt_pub_client = None

# ─── GPS THREAD ────────────────────────────────────────────────────────────────

def gps_thread():
    """
    Legge continuamente il modulo NEO-6M e pubblica ogni fix valido
    su robot/gps/posizione tramite MQTT.
    Formato payload:
      {"lat": float, "lon": float, "alt": float,
       "speed_kn": float, "satellites": int, "ts": float}
    """
    global mqtt_pub_client

    print(f"[GPS] Apertura porta {GPS_PORT} a {GPS_BAUD} baud...")
    try:
        ser = serial.Serial(GPS_PORT, GPS_BAUD, timeout=1)
    except Exception as e:
        print(f"[GPS] ERRORE apertura seriale: {e}")
        print("[GPS]  → Tab GPS mostrerà errore. Il resto del server funziona normalmente.")
        return

    print("[GPS] Porta aperta, in attesa di fix...")
    ultima_gga = {}

    while True:
        try:
            linea = ser.readline().decode("ascii", errors="replace").strip()
            if not linea.startswith("$"):
                continue
            msg = pynmea2.parse(linea)

            if isinstance(msg, pynmea2.GGA) and msg.gps_qual > 0:
                ultima_gga = {
                    "lat": msg.latitude,
                    "lon": msg.longitude,
                    "alt": float(msg.altitude) if msg.altitude else 0.0,
                    "sat": int(msg.num_sats)   if msg.num_sats  else 0,
                }

            elif isinstance(msg, pynmea2.RMC) and msg.status == "A" and ultima_gga:
                payload = {
                    "lat":        ultima_gga["lat"],
                    "lon":        ultima_gga["lon"],
                    "alt":        ultima_gga["alt"],
                    "speed_kn":   float(msg.spd_over_grnd) if msg.spd_over_grnd else 0.0,
                    "satellites": ultima_gga["sat"],
                    "ts":         time.time(),
                    "type":       "gps",
                }
                if mqtt_pub_client and mqtt_pub_client.is_connected():
                    mqtt_pub_client.publish(GPS_TOPIC, json.dumps(payload))

        except pynmea2.ParseError:
            pass
        except Exception as e:
            print(f"[GPS] Errore lettura: {e}")
            time.sleep(1)

# ─── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LagmaBills — Controllo</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Space+Grotesk:wght@300;600&display=swap');

  :root {
    --bg:      #0a0c10;
    --panel:   #10141c;
    --border:  #1e2535;
    --accent:  #00e5ff;
    --occ:     #ff4757;
    --free:    #1a2a1a;
    --robot:   #ffd32a;
    --text:    #c8d6e5;
    --dim:     #57606f;
    --cliff:   #ff6b35;
    --ok:      #2ed573;
    --warn:    #ffa502;
    --gps:     #7bed9f;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* ── HEADER ── */
  header {
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    padding: 0 16px;
    gap: 10px;
    height: 48px;
    flex-shrink: 0;
  }
  .logo { font-family: 'JetBrains Mono', monospace; font-weight: 700;
          font-size: 13px; color: var(--accent); letter-spacing: 2px; }
  .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--dim); transition: background .3s; }
  .dot.ok   { background: var(--ok);     box-shadow: 0 0 6px var(--ok); }
  .dot.live { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
  .dot.warn { background: var(--cliff);  box-shadow: 0 0 8px var(--cliff); }
  #status-text { font-size: 11px; color: var(--dim); font-family: 'JetBrains Mono', monospace; }
  .ml-auto { margin-left: auto; }
  .btn {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--dim);
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    padding: 4px 10px;
    cursor: pointer;
    border-radius: 3px;
    transition: all .2s;
  }
  .btn:hover     { border-color: var(--accent); color: var(--accent); }
  .btn.active    { border-color: var(--ok);     color: var(--ok); }
  .btn.danger    { border-color: var(--occ);    color: var(--occ); }
  .btn.goal-mode { border-color: var(--warn);   color: var(--warn); }
  #cliff-banner {
    display: none;
    background: var(--cliff);
    color: #fff;
    font-family: 'JetBrains Mono', monospace;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: 3px;
    padding: 0 16px;
    align-items: center;
    animation: blink 0.5s infinite alternate;
  }
  #cliff-banner.show { display: flex; }
  @keyframes blink { from{opacity:1} to{opacity:.4} }

  /* ── TABS ── */
  .tab-bar {
    background: var(--panel);
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 0;
    flex-shrink: 0;
  }
  .tab-btn {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--dim);
    font-family: 'JetBrains Mono', monospace;
    font-size: 11px;
    letter-spacing: 1px;
    padding: 8px 20px;
    cursor: pointer;
    transition: all .2s;
  }
  .tab-btn:hover  { color: var(--text); }
  .tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }

  /* ── CONTENT AREA ── */
  .tab-content { display: none; flex: 1; overflow: hidden; }
  .tab-content.active { display: flex; }

  /* ── OCCUPANCY TAB ── */
  #tab-occ {
    display: none;
    flex-direction: row;
  }
  #tab-occ.active { display: flex; }

  #canvas-wrap {
    position: relative;
    overflow: hidden;
    background: var(--bg);
    flex: 1;
    cursor: crosshair;
  }
  #canvas-wrap.goal-cursor { cursor: cell; }
  canvas { display: block; image-rendering: pixelated; }
  .scale-bar { position: absolute; bottom: 14px; left: 14px; display: flex; flex-direction: column; gap: 4px; }
  .scale-line { width: 80px; height: 3px; background: var(--text); border-radius: 2px; }
  .scale-label { font-size: 10px; font-family: 'JetBrains Mono', monospace; color: var(--text); opacity: .6; }
  #coords { position: absolute; bottom: 14px; right: 14px;
            font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--dim); text-align: right; }
  #goal-marker { position: absolute; width: 12px; height: 12px;
                 border: 2px solid var(--warn); border-radius: 50%;
                 transform: translate(-50%,-50%); pointer-events: none; display: none; }

  /* ── GPS TAB ── */
  #tab-gps {
    display: none;
    flex-direction: row;
  }
  #tab-gps.active { display: flex; }

  #map-leaflet {
    flex: 1;
    background: #1a1f2e;
  }

  /* Override Leaflet dark theme feel */
  .leaflet-container { background: #1a1f2e; }
  .leaflet-tile { filter: brightness(0.85) saturate(0.9); }

  /* Robot marker pulsante */
  .robot-pulse {
    width: 20px; height: 20px;
    border-radius: 50%;
    background: var(--robot);
    border: 3px solid #fff;
    box-shadow: 0 0 0 0 rgba(255, 211, 42, 0.7);
    animation: pulse-ring 1.5s infinite;
  }
  @keyframes pulse-ring {
    0%   { box-shadow: 0 0 0 0   rgba(255,211,42,.7); }
    70%  { box-shadow: 0 0 0 14px rgba(255,211,42,0); }
    100% { box-shadow: 0 0 0 0   rgba(255,211,42,0); }
  }

  /* ── SIDEBAR CONDIVISA ── */
  .sidebar {
    background: var(--panel);
    border-left: 1px solid var(--border);
    padding: 14px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    overflow-y: auto;
    font-size: 12px;
    width: 220px;
    flex-shrink: 0;
  }
  .sidebar h3 {
    font-size: 9px; letter-spacing: 2px; color: var(--dim);
    text-transform: uppercase; font-family: 'JetBrains Mono', monospace; margin-bottom: 8px;
  }
  .stat-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; }
  .stat-label { color: var(--dim); }
  .stat-value { font-family: 'JetBrains Mono', monospace; color: var(--text); }
  .accent  { color: var(--accent)  !important; }
  .warn    { color: var(--warn)    !important; }
  .okc     { color: var(--ok)      !important; }
  .dangerc { color: var(--occ)     !important; }
  .gpsc    { color: var(--gps)     !important; }

  .sensor-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
  .sensor-cell {
    background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 5px 7px;
  }
  .sensor-cell .slabel { font-size: 9px; color: var(--dim); letter-spacing: 1px; }
  .sensor-cell .sval   { font-family: 'JetBrains Mono', monospace; font-size: 13px; }
  .sensor-cell.near    { border-color: var(--occ); }
  .sensor-cell.mid     { border-color: var(--warn); }
  .cliff-cells { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
  .cliff-cell { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 5px 7px; text-align: center; }
  .cliff-cell .slabel { font-size: 9px; color: var(--dim); }
  .cliff-cell .sval   { font-family: 'JetBrains Mono', monospace; font-size: 12px; }
  .cliff-cell.danger  { border-color: var(--cliff); background: rgba(255,107,53,.1); }

  /* GPS data cards */
  .gps-card {
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 10px;
  }
  .gps-card .big-val {
    font-family: 'JetBrains Mono', monospace;
    font-size: 15px;
    color: var(--gps);
    font-weight: 700;
  }
  .gps-card .unit {
    font-size: 9px;
    color: var(--dim);
    letter-spacing: 1px;
  }
  .gps-badge {
    display: inline-block;
    background: rgba(123,237,159,.12);
    border: 1px solid var(--gps);
    color: var(--gps);
    font-family: 'JetBrains Mono', monospace;
    font-size: 9px;
    letter-spacing: 2px;
    padding: 2px 7px;
    border-radius: 3px;
    margin-bottom: 8px;
  }
  .no-fix {
    background: rgba(255,71,87,.1);
    border: 1px solid var(--occ);
    color: var(--occ);
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    letter-spacing: 1px;
    padding: 6px 10px;
    border-radius: 4px;
    text-align: center;
    margin-bottom: 4px;
  }
  .sat-bar { display: flex; gap: 2px; margin-top: 4px; }
  .sat-pip { width: 8px; height: 14px; background: var(--border); border-radius: 2px; transition: background .3s; }
  .sat-pip.active { background: var(--gps); }

  .nav-btns { display: flex; gap: 6px; flex-wrap: wrap; }
  .legend-item { display: flex; align-items: center; gap: 7px; margin-bottom: 6px; color: var(--dim); }
  .swatch { width: 12px; height: 12px; border-radius: 2px; flex-shrink: 0; }

  /* Clear track button */
  .btn-clear {
    width: 100%;
    margin-top: 6px;
    background: transparent;
    border: 1px solid var(--border);
    color: var(--dim);
    font-family: 'JetBrains Mono', monospace;
    font-size: 10px;
    padding: 5px;
    border-radius: 3px;
    cursor: pointer;
    transition: all .2s;
  }
  .btn-clear:hover { border-color: var(--warn); color: var(--warn); }
</style>
</head>
<body>

<header>
  <span class="logo">LAGMABILLS</span>
  <div class="dot" id="dot"></div>
  <span id="status-text">connessione...</span>
  <div id="cliff-banner">⚠ CLIFF</div>
  <div class="ml-auto" style="display:flex;gap:8px;align-items:center">
    <button class="btn" id="btn-start"     onclick="navCmd('start')">▶ START</button>
    <button class="btn danger" id="btn-stop" onclick="navCmd('stop')">■ STOP</button>
    <button class="btn" id="btn-goal-mode" onclick="toggleGoalMode()">◎ SET GOAL</button>
    <button class="btn" onclick="resetView()">⟳ RESET VISTA</button>
  </div>
</header>

<div class="tab-bar">
  <button class="tab-btn active" onclick="switchTab('occ', this)">◈ MAPPA LOCALE</button>
  <button class="tab-btn"        onclick="switchTab('gps', this)">⊕ GPS WORLD</button>
</div>

<!-- ══════════════════ TAB OCCUPANCY ══════════════════ -->
<div class="tab-content active" id="tab-occ">
  <div id="canvas-wrap">
    <canvas id="map-canvas"></canvas>
    <div class="scale-bar">
      <div class="scale-line" id="scale-line"></div>
      <div class="scale-label" id="scale-label">1 m</div>
    </div>
    <div id="coords">—</div>
    <div id="goal-marker"></div>
  </div>

  <div class="sidebar">
    <div>
      <h3>Robot</h3>
      <div class="stat-row"><span class="stat-label">X</span><span class="stat-value accent" id="pose-x">—</span></div>
      <div class="stat-row"><span class="stat-label">Y</span><span class="stat-value accent" id="pose-y">—</span></div>
      <div class="stat-row"><span class="stat-label">θ</span><span class="stat-value accent" id="pose-theta">—</span></div>
    </div>

    <div>
      <h3>Navigatore</h3>
      <div class="stat-row"><span class="stat-label">Modalità</span><span class="stat-value" id="nav-mode">—</span></div>
      <div class="stat-row"><span class="stat-label">Vx</span><span class="stat-value" id="nav-vx">—</span></div>
      <div class="stat-row"><span class="stat-label">Vy</span><span class="stat-value" id="nav-vy">—</span></div>
      <div class="stat-row"><span class="stat-label">Vr</span><span class="stat-value" id="nav-vr">—</span></div>
      <div class="stat-row"><span class="stat-label">Goal</span><span class="stat-value warn" id="nav-goal">—</span></div>
    </div>

    <div>
      <h3>Sensori (cm)</h3>
      <div class="sensor-grid">
        <div class="sensor-cell" id="sc-FRONTE"><div class="slabel">FRONTE</div><div class="sval" id="sv-FRONTE">—</div></div>
        <div class="sensor-cell" id="sc-RETRO"><div class="slabel">RETRO</div><div class="sval" id="sv-RETRO">—</div></div>
        <div class="sensor-cell" id="sc-SINISTRA"><div class="slabel">SX</div><div class="sval" id="sv-SINISTRA">—</div></div>
        <div class="sensor-cell" id="sc-DESTRA"><div class="slabel">DX</div><div class="sval" id="sv-DESTRA">—</div></div>
      </div>
    </div>

    <div>
      <h3>Cliff</h3>
      <div class="cliff-cells">
        <div class="cliff-cell" id="cliff-f-cell"><div class="slabel">CLIFF F</div><div class="sval" id="cliff-f-val">—</div></div>
        <div class="cliff-cell" id="cliff-r-cell"><div class="slabel">CLIFF R</div><div class="sval" id="cliff-r-val">—</div></div>
      </div>
      <button class="btn" style="width:100%;margin-top:6px" onclick="navCmd('reset_cliff')">↺ RESET CLIFF</button>
    </div>

    <div>
      <h3>Mappa</h3>
      <div class="stat-row"><span class="stat-label">Occupate</span><span class="stat-value dangerc" id="stat-occ">—</span></div>
      <div class="stat-row"><span class="stat-label">Libere</span><span class="stat-value okc" id="stat-free">—</span></div>
      <div class="stat-row"><span class="stat-label">Risoluz.</span><span class="stat-value">5 cm/cella</span></div>
      <div class="stat-row"><span class="stat-label">Dim.</span><span class="stat-value">10 × 10 m</span></div>
      <div class="stat-row"><span class="stat-label">Aggiorn.</span><span class="stat-value" id="stat-ts">—</span></div>
    </div>

    <div>
      <h3>Legenda</h3>
      <div class="legend-item"><div class="swatch" style="background:#ff4757"></div>Occupato</div>
      <div class="legend-item"><div class="swatch" style="background:#1a2a1a;border:1px solid #2a3a2a"></div>Libero</div>
      <div class="legend-item"><div class="swatch" style="background:#0a0c10;border:1px solid #1e2535"></div>Sconosciuto</div>
      <div class="legend-item"><div class="swatch" style="background:#ffd32a;border-radius:50%"></div>Robot</div>
      <div class="legend-item"><div class="swatch" style="background:#ff6b35;border-radius:50%"></div>Goal</div>
    </div>
  </div>
</div>

<!-- ══════════════════ TAB GPS ══════════════════ -->
<div class="tab-content" id="tab-gps">
  <div id="map-leaflet"></div>

  <div class="sidebar">
    <div>
      <div id="gps-fix-badge" class="no-fix">NO FIX</div>
      <h3>Posizione</h3>
      <div class="gps-card" style="margin-bottom:6px">
        <div class="unit">LATITUDINE</div>
        <div class="big-val" id="gps-lat">—</div>
      </div>
      <div class="gps-card">
        <div class="unit">LONGITUDINE</div>
        <div class="big-val" id="gps-lon">—</div>
      </div>
    </div>

    <div>
      <h3>Dati</h3>
      <div class="stat-row">
        <span class="stat-label">Quota</span>
        <span class="stat-value gpsc" id="gps-alt">— m</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Velocità</span>
        <span class="stat-value gpsc" id="gps-speed">— kn</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">km/h</span>
        <span class="stat-value gpsc" id="gps-speed-kmh">—</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Aggiorn.</span>
        <span class="stat-value" id="gps-ts">—</span>
      </div>
    </div>

    <div>
      <h3>Satelliti</h3>
      <div class="stat-row">
        <span class="stat-label">Agganciati</span>
        <span class="stat-value gpsc" id="gps-sat">—</span>
      </div>
      <div class="sat-bar" id="sat-bar">
        <!-- 12 pip generati da JS -->
      </div>
    </div>

    <div>
      <h3>Traccia</h3>
      <div class="stat-row">
        <span class="stat-label">Punti</span>
        <span class="stat-value" id="gps-track-pts">0</span>
      </div>
      <div class="stat-row">
        <span class="stat-label">Distanza</span>
        <span class="stat-value gpsc" id="gps-dist">0.00 m</span>
      </div>
      <button class="btn-clear" onclick="clearTrack()">✕ CANCELLA TRACCIA</button>
    </div>

    <div>
      <h3>Link esterno</h3>
      <a id="gmaps-link" href="#" target="_blank"
         style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--accent);text-decoration:none">
        ↗ Apri in Google Maps
      </a>
    </div>
  </div>
</div>

<script>
// ══════════════════ TAB SWITCHER ══════════════════
function switchTab(name, btn) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  btn.classList.add('active');

  if (name === 'occ' && mapData) resetView();
  if (name === 'gps') { setTimeout(() => leafletMap.invalidateSize(), 50); }
}

// ══════════════════ OCCUPANCY MAP ══════════════════
const canvas  = document.getElementById('map-canvas');
const ctx     = canvas.getContext('2d');
const wrap    = document.getElementById('canvas-wrap');

let mapData  = null;
let cellPx   = 4;
let offsetX  = 0, offsetY = 0;
let dragging = false, dragStart = null;
let goalMode = false;
let goalCell = null;

function resetView() {
  if (!mapData) return;
  const S = mapData.size;
  const W = wrap.clientWidth;
  const H = wrap.clientHeight;
  canvas.width  = W;
  canvas.height = H;
  cellPx  = Math.min(W, H) / S * 0.9;
  offsetX = (W - S * cellPx) / 2;
  offsetY = (H - S * cellPx) / 2;
  render();
}

function render() {
  if (!mapData) return;
  const S = mapData.size;
  const W = wrap.clientWidth;
  const H = wrap.clientHeight;
  canvas.width  = W;
  canvas.height = H;

  ctx.fillStyle = '#0a0c10';
  ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = '#1a2a1a';
  for (const [cx, cy] of mapData.free)
    ctx.fillRect(offsetX + cx * cellPx, offsetY + cy * cellPx, cellPx, cellPx);

  ctx.fillStyle = '#ff4757';
  for (const [cx, cy] of mapData.occupied)
    ctx.fillRect(offsetX + cx * cellPx, offsetY + cy * cellPx, cellPx, cellPx);

  if (cellPx >= 8) {
    ctx.strokeStyle = 'rgba(30,37,53,0.4)';
    ctx.lineWidth = 0.5;
    for (let i = 0; i <= S; i++) {
      ctx.beginPath(); ctx.moveTo(offsetX + i*cellPx, offsetY); ctx.lineTo(offsetX + i*cellPx, offsetY + S*cellPx); ctx.stroke();
      ctx.beginPath(); ctx.moveTo(offsetX, offsetY + i*cellPx); ctx.lineTo(offsetX + S*cellPx, offsetY + i*cellPx); ctx.stroke();
    }
  }

  const [rx, ry] = mapData.robot_cell;
  const theta    = mapData.robot_theta || 0;
  const rpx = offsetX + rx * cellPx + cellPx / 2;
  const rpy = offsetY + ry * cellPx + cellPx / 2;
  const rrad = Math.max(6, cellPx * 2);
  ctx.beginPath(); ctx.arc(rpx, rpy, rrad, 0, 2 * Math.PI);
  ctx.fillStyle = '#ffd32a'; ctx.strokeStyle = '#fff8'; ctx.lineWidth = 1.5;
  ctx.fill(); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(rpx, rpy);
  ctx.lineTo(rpx + Math.cos(theta) * rrad * 1.8, rpy + Math.sin(theta) * rrad * 1.8);
  ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke();

  if (goalCell) {
    const gpx = offsetX + goalCell.cx * cellPx + cellPx / 2;
    const gpy = offsetY + goalCell.cy * cellPx + cellPx / 2;
    ctx.beginPath(); ctx.arc(gpx, gpy, rrad * 0.8, 0, 2 * Math.PI);
    ctx.strokeStyle = '#ffa502'; ctx.lineWidth = 2; ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(gpx - rrad, gpy); ctx.lineTo(gpx + rrad, gpy);
    ctx.moveTo(gpx, gpy - rrad); ctx.lineTo(gpx, gpy + rrad);
    ctx.stroke();
  }

  const meterPx = (1.0 / mapData.cell_m) * cellPx;
  document.getElementById('scale-line').style.width = meterPx + 'px';
}

function updateStats(d) {
  document.getElementById('stat-occ').textContent  = d.occupied.length;
  document.getElementById('stat-free').textContent = d.free.length;
  const dt = new Date(d.ts * 1000);
  document.getElementById('stat-ts').textContent =
    dt.toLocaleTimeString('it-IT', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}

function updatePose(d) {
  const half = d.size * d.cell_m / 2;
  const wx = d.robot_cell[0] * d.cell_m - half;
  const wy = d.robot_cell[1] * d.cell_m - half;
  document.getElementById('pose-x').textContent     = wx.toFixed(3) + ' m';
  document.getElementById('pose-y').textContent     = wy.toFixed(3) + ' m';
  document.getElementById('pose-theta').textContent = ((d.robot_theta||0)*180/Math.PI).toFixed(1) + '°';
}

function updateSensors(sensors) {
  const NEAR = 20, MID = 50;
  for (const name of ['FRONTE','RETRO','SINISTRA','DESTRA']) {
    const val  = sensors[name];
    const el   = document.getElementById('sv-' + name);
    const cell = document.getElementById('sc-' + name);
    if (!el) continue;
    if (!val || val === 9999) { el.textContent = '---'; cell.className='sensor-cell ok'; continue; }
    el.textContent = val.toFixed(0);
    cell.className = 'sensor-cell ' + (val < NEAR ? 'near' : val < MID ? 'mid' : 'ok');
  }
}

function updateCliff(cliffData) {
  const cf = cliffData.cliff_f || false;
  const cr = cliffData.cliff_r || false;
  document.getElementById('cliff-f-val').textContent = cf ? '⚠ DIRUPO' : 'OK';
  document.getElementById('cliff-r-val').textContent = cr ? '⚠ DIRUPO' : 'OK';
  document.getElementById('cliff-f-cell').className = 'cliff-cell' + (cf ? ' danger' : '');
  document.getElementById('cliff-r-cell').className = 'cliff-cell' + (cr ? ' danger' : '');
  const banner = document.getElementById('cliff-banner');
  if (cf || cr) {
    banner.classList.add('show');
    document.getElementById('dot').className = 'dot warn';
  } else {
    banner.classList.remove('show');
  }
}

function updateNav(d) {
  if (!d) return;
  document.getElementById('nav-mode').textContent = d.mode || '—';
  document.getElementById('nav-vx').textContent   = d.vx !== undefined ? d.vx : '—';
  document.getElementById('nav-vy').textContent   = d.vy !== undefined ? d.vy : '—';
  document.getElementById('nav-vr').textContent   = d.vr !== undefined ? d.vr : '—';
  document.getElementById('nav-goal').textContent =
    d.goal ? `(${d.goal.x.toFixed(2)}, ${d.goal.y.toFixed(2)})` : 'none';
}

// Nav controls
function navCmd(cmd) {
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify({nav_cmd: cmd}));
}

function toggleGoalMode() {
  goalMode = !goalMode;
  document.getElementById('btn-goal-mode').className = 'btn' + (goalMode ? ' goal-mode' : '');
  wrap.className = goalMode ? 'goal-cursor' : '';
}

function setGoalAt(canvasX, canvasY) {
  if (!mapData) return;
  const cx = Math.floor((canvasX - offsetX) / cellPx);
  const cy = Math.floor((canvasY - offsetY) / cellPx);
  if (cx < 0 || cx >= mapData.size || cy < 0 || cy >= mapData.size) return;
  const half = mapData.size * mapData.cell_m / 2;
  const wx = cx * mapData.cell_m - half;
  const wy = cy * mapData.cell_m - half;
  goalCell = {cx, cy};
  if (ws && ws.readyState === WebSocket.OPEN)
    ws.send(JSON.stringify({nav_goal: {x: wx, y: wy}}));
  render();
  toggleGoalMode();
}

canvas.addEventListener('mousedown', e => {
  if (goalMode) { setGoalAt(e.clientX, e.clientY); return; }
  dragging = true;
  dragStart = {x: e.clientX - offsetX, y: e.clientY - offsetY};
});
window.addEventListener('mousemove', e => {
  if (dragging) {
    offsetX = e.clientX - dragStart.x;
    offsetY = e.clientY - dragStart.y;
    render();
  }
  if (mapData) {
    const cx = Math.floor((e.clientX - offsetX) / cellPx);
    const cy = Math.floor((e.clientY - offsetY) / cellPx);
    if (cx >= 0 && cx < mapData.size && cy >= 0 && cy < mapData.size) {
      const half = mapData.size * mapData.cell_m / 2;
      document.getElementById('coords').textContent =
        `(${(cx*mapData.cell_m-half).toFixed(2)}m, ${(cy*mapData.cell_m-half).toFixed(2)}m)`;
    }
  }
});
window.addEventListener('mouseup', () => dragging = false);
canvas.addEventListener('wheel', e => {
  e.preventDefault();
  const f = e.deltaY < 0 ? 1.2 : 0.8;
  const nc = Math.max(1, Math.min(32, cellPx * f));
  offsetX = Math.round(e.clientX - (e.clientX - offsetX) * (nc / cellPx));
  offsetY = Math.round(e.clientY - (e.clientY - offsetY) * (nc / cellPx));
  cellPx  = nc;
  render();
}, {passive: false});
window.addEventListener('resize', resetView);

// ══════════════════ GPS + LEAFLET ══════════════════
// Inizializza la mappa Leaflet centrata sull'Italia
const leafletMap = L.map('map-leaflet', {
  center: [45.4654, 9.1866],  // Milano come default
  zoom: 16,
  zoomControl: true,
});

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '© OpenStreetMap contributors',
  maxZoom: 19,
}).addTo(leafletMap);

// Marker robot pulsante
const robotIcon = L.divIcon({
  className: '',
  html: '<div class="robot-pulse"></div>',
  iconSize: [20, 20],
  iconAnchor: [10, 10],
});
let robotMarker = null;
let trackLine   = null;
let trackCoords = [];    // array di [lat, lon]
let totalDist   = 0;     // metri

// Satellite pip bar
const satBar = document.getElementById('sat-bar');
for (let i = 0; i < 12; i++) {
  const pip = document.createElement('div');
  pip.className = 'sat-pip';
  pip.id = 'sat-' + i;
  satBar.appendChild(pip);
}

function haversineM(lat1, lon1, lat2, lon2) {
  const R  = 6371000;
  const dL = (lat2 - lat1) * Math.PI / 180;
  const dO = (lon2 - lon1) * Math.PI / 180;
  const a  = Math.sin(dL/2)**2 + Math.cos(lat1*Math.PI/180)*Math.cos(lat2*Math.PI/180)*Math.sin(dO/2)**2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
}

function distStr(m) {
  return m >= 1000 ? (m/1000).toFixed(2) + ' km' : m.toFixed(1) + ' m';
}

function updateGPS(d) {
  const lat = d.lat, lon = d.lon;
  const alt = d.alt.toFixed(1);
  const kn  = d.speed_kn.toFixed(2);
  const kmh = (d.speed_kn * 1.852).toFixed(1);
  const sat = d.satellites;
  const ts  = new Date(d.ts * 1000).toLocaleTimeString('it-IT');

  // Badge fix
  const badge = document.getElementById('gps-fix-badge');
  badge.textContent = '✓ GPS FIX';
  badge.className   = 'gps-badge';

  document.getElementById('gps-lat').textContent       = lat.toFixed(6) + '°';
  document.getElementById('gps-lon').textContent       = lon.toFixed(6) + '°';
  document.getElementById('gps-alt').textContent       = alt + ' m';
  document.getElementById('gps-speed').textContent     = kn + ' kn';
  document.getElementById('gps-speed-kmh').textContent = kmh + ' km/h';
  document.getElementById('gps-sat').textContent       = sat;
  document.getElementById('gps-ts').textContent        = ts;

  // Sat bar
  for (let i = 0; i < 12; i++) {
    document.getElementById('sat-' + i).className = 'sat-pip' + (i < sat ? ' active' : '');
  }

  // Google Maps link
  document.getElementById('gmaps-link').href =
    `https://www.google.com/maps?q=${lat},${lon}`;

  // ── Leaflet ──
  const latlng = [lat, lon];

  if (!robotMarker) {
    robotMarker = L.marker(latlng, {icon: robotIcon}).addTo(leafletMap);
    leafletMap.setView(latlng, 18);
  } else {
    robotMarker.setLatLng(latlng);
  }

  // Traccia
  if (trackCoords.length > 0) {
    const prev = trackCoords[trackCoords.length - 1];
    totalDist += haversineM(prev[0], prev[1], latlng[0], latlng[1]);
  }
  trackCoords.push(latlng);

  if (trackLine) {
    leafletMap.removeLayer(trackLine);
  }
  trackLine = L.polyline(trackCoords, {
    color: '#7bed9f',
    weight: 3,
    opacity: 0.85,
  }).addTo(leafletMap);

  document.getElementById('gps-track-pts').textContent = trackCoords.length;
  document.getElementById('gps-dist').textContent      = distStr(totalDist);

  // Segui robot automaticamente
  leafletMap.panTo(latlng, {animate: true, duration: 0.5});
}

function clearTrack() {
  trackCoords = [];
  totalDist   = 0;
  if (trackLine) { leafletMap.removeLayer(trackLine); trackLine = null; }
  document.getElementById('gps-track-pts').textContent = '0';
  document.getElementById('gps-dist').textContent = '0.00 m';
}

// ══════════════════ WEBSOCKET ══════════════════
let ws, retryTimeout;

function connect() {
  ws = new WebSocket(`ws://${location.hostname}:${8765}`);

  ws.onopen = () => {
    document.getElementById('dot').className    = 'dot ok';
    document.getElementById('status-text').textContent = 'connesso';
  };

  ws.onmessage = (e) => {
    const d = JSON.parse(e.data);

    if (d.type === 'gps') {
      updateGPS(d);
      return;
    }
    if (d.type === 'nav') {
      updateNav(d);
      return;
    }
    if (d.type === 'cliff') {
      updateCliff(d);
      return;
    }

    // Occupancy map update
    mapData = d;
    document.getElementById('dot').className = 'dot live';
    setTimeout(() => document.getElementById('dot').className = 'dot ok', 300);
    document.getElementById('status-text').textContent = 'live';

    if (!mapData._initialized) {
      mapData._initialized = true;
      resetView();
    } else {
      render();
    }
    updateStats(d);
    updatePose(d);
    if (d.sensors) updateSensors(d.sensors);
    if (d.cliff)   updateCliff(d.cliff);
  };

  ws.onerror = () => {
    document.getElementById('status-text').textContent = 'errore WS';
  };
  ws.onclose = () => {
    document.getElementById('dot').className = 'dot';
    document.getElementById('status-text').textContent = 'disconnesso — riprovo...';
    retryTimeout = setTimeout(connect, 3000);
  };
}
connect();
</script>
</body>
</html>
"""

# ─── HTTP ──────────────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(HTML.encode())
    def log_message(self, fmt, *args):
        pass

def run_http():
    server = HTTPServer(("0.0.0.0", HTTP_PORT), Handler)
    print(f"[HTTP] http://0.0.0.0:{HTTP_PORT}")
    server.serve_forever()

# ─── WEBSOCKET ──────────────────────────────────────────────────────────────────

async def ws_handler(websocket):
    ws_clients.add(websocket)
    print(f"[WS] Client connesso: {websocket.remote_address}")
    try:
        with map_lock:
            if latest_map:
                await websocket.send(latest_map)
            if latest_gps:
                await websocket.send(latest_gps)
        async for raw in websocket:
            try:
                msg = json.loads(raw)
                if "nav_cmd" in msg and mqtt_pub_client:
                    mqtt_pub_client.publish("robot/nav/cmd", json.dumps({"cmd": msg["nav_cmd"]}))
                if "nav_goal" in msg and mqtt_pub_client:
                    mqtt_pub_client.publish("robot/nav/goal", json.dumps(msg["nav_goal"]))
            except Exception:
                pass
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        ws_clients.discard(websocket)

async def broadcast(payload: str):
    if ws_clients:
        await asyncio.gather(*[ws.send(payload) for ws in list(ws_clients)],
                             return_exceptions=True)

def run_ws():
    global ws_loop
    ws_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ws_loop)
    async def main():
        async with websockets.serve(ws_handler, "0.0.0.0", WS_PORT):
            print(f"[WS] ws://0.0.0.0:{WS_PORT}")
            await asyncio.Future()
    ws_loop.run_until_complete(main())

# ─── MQTT ──────────────────────────────────────────────────────────────────────

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        client.subscribe("robot/mappa/grid")
        client.subscribe("robot/cliff/stato")
        client.subscribe("robot/nav/stato")
        client.subscribe(GPS_TOPIC)
        print("[MQTT] Connesso, subscribed")

def on_message(client, userdata, msg):
    global latest_map, latest_gps

    payload = msg.payload.decode()

    if msg.topic == "robot/mappa/grid":
        with map_lock:
            latest_map = payload
        if ws_loop and ws_clients:
            asyncio.run_coroutine_threadsafe(broadcast(payload), ws_loop)

    elif msg.topic == GPS_TOPIC:
        try:
            d = json.loads(payload)
            d["type"] = "gps"
            out = json.dumps(d)
            with map_lock:
                latest_gps = out
            if ws_loop and ws_clients:
                asyncio.run_coroutine_threadsafe(broadcast(out), ws_loop)
        except Exception:
            pass

    elif msg.topic == "robot/cliff/stato":
        try:
            d = json.loads(payload)
            d["type"] = "cliff"
            if ws_loop and ws_clients:
                asyncio.run_coroutine_threadsafe(broadcast(json.dumps(d)), ws_loop)
        except Exception:
            pass

    elif msg.topic == "robot/nav/stato":
        try:
            d = json.loads(payload)
            d["type"] = "nav"
            if ws_loop and ws_clients:
                asyncio.run_coroutine_threadsafe(broadcast(json.dumps(d)), ws_loop)
        except Exception:
            pass

def run_mqtt():
    global mqtt_pub_client
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    mqtt_pub_client = client
    client.loop_forever()

# ─── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=== LagmaBills — Map Viewer Server v3 (GPS) ===")
    threads = [
        threading.Thread(target=run_http,   daemon=True, name="http"),
        threading.Thread(target=run_ws,     daemon=True, name="ws"),
        threading.Thread(target=run_mqtt,   daemon=True, name="mqtt"),
        threading.Thread(target=gps_thread, daemon=True, name="gps"),
    ]
    for t in threads:
        t.start()
    print(f"Apri → http://<ip-pi>:{HTTP_PORT}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[INFO] Chiusura.")