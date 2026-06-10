# L.A.G.M.A. B.I.L.L.S.

### *Land And Ground-to-Midair Agent — Built for Intelligent Linked Local Support*

![Platform](https://img.shields.io/badge/platform-ESP32%20%2F%20Raspberry%20Pi-red?style=flat&logo=raspberrypi&logoColor=white)
![Firmware](https://img.shields.io/badge/firmware-C%2FC%2B%2B%20%2F%20PlatformIO-00979D?style=flat&logo=platformio&logoColor=white)
![Python](https://img.shields.io/badge/raspberry-Python-3776AB?style=flat&logo=python&logoColor=white)
![MQTT](https://img.shields.io/badge/protocol-MQTT-660066?style=flat&logo=mqtt&logoColor=white)
![App](https://img.shields.io/badge/app-.NET%20MAUI-512BD4?style=flat&logo=dotnet&logoColor=white)
![KiCad](https://img.shields.io/badge/PCB-KiCad-314CB0?style=flat&logo=kicad&logoColor=white)
![AI](https://img.shields.io/badge/AI-Whisper%20%2F%20ONNX-FF6F00?style=flat&logo=openai&logoColor=white)
![License](https://img.shields.io/badge/license-Hippocratic%203.0-brightgreen?style=flat)

> A Mecanum-wheeled robot for civil protection, powered by a Raspberry Pi orchestrating two custom ESP32 PCBs, sensors, a robotic arm, and a drone companion over MQTT. It navigates autonomously, maps its environment, avoids obstacles, and is controlled via voice AI, a MAUI app, or browser dashboard.

---

## Repositories

| Repo                      | Contenuto                                               |
| ------------------------- | ------------------------------------------------------- |
| **lagmabills** *(questo)* | Firmware ESP32, codice Python Raspberry Pi, PCB (KiCad) |
| **lagmabills-app**        | App companion LagmaIpp (.NET MAUI, Windows + Android)   |

---

## Struttura del repository

```
lagmabills/
├── firmware/
│   ├── esp32_motori/          # Firmware PCBmotori (PlatformIO)
│   └── esp32_sensori/         # Firmware PCBsensori (PlatformIO)
├── raspberry/
│   ├── wakeword.py            # Wakeword detection + DOA + WebSocket stream
│   ├── odometria.py           # Odometria encoder Mecanum
│   ├── occupancyGrid.py       # Mappatura locale log-odds
│   ├── navigator.py           # Navigazione autonoma Potential Field
│   ├── GPS.py                 # Lettura NEO-6M → MQTT
│   ├── drone_mqtt_bridge.py   # Bridge MQTT → CRTP/UDP drone
│   ├── myViewerServer.py      # Dashboard web (HTTP + WebSocket + Leaflet)
│   └── streamCamera.py        # Stream MJPEG OV5647
├── pcb/
│   ├── PCBmotori/             # KiCad — ESP32 motori (4-layer)
│   ├── PCBsensori/            # KiCad — ESP32 sensori
│   └── PCBalim/               # KiCad — distribuzione alimentazione
└── docs/
    └── LAGMABILLS.pptx        # Presentazione progetto
```

---

## Hardware

| Componente                 | Descrizione                                                                  |
| -------------------------- | ---------------------------------------------------------------------------- |
| Raspberry Pi 4B (4GB)      | Cervello centrale, broker MQTT, Tailscale VPN                                |
| PCBmotori (ESP32, 4-layer) | 4× JGA25-370 Mecanum + encoder, 2× TB6612FNG, I2C slave `0x08`               |
| PCBsensori (ESP32)         | 6× HC-SR04, MPU-6050, 3× TCRT5000, PCA9685 → braccio 6DOF, I2C slave `0x09` |
| PCBalim                    | Distribuzione alimentazione custom, 2× LiPo 3S 5500mAh                       |
| ESP-Drone (ESP32-S2)       | Ricognizione aerea, CRTP/UDP `192.168.43.42:2390`                            |
| OV5647 CSI                 | Camera RPi, stream MJPEG su porta `8080`                                     |
| ReSpeaker 2-Mic HAT        | WM8960, wakeword ONNX, DOA GCC-PHAT                                          |
| NEO-6M GPS                 | Tracciamento posizione world frame                                           |
| Display 7" HDMI            | Faccia animata responsiva (RPi)                                              |
| Speaker Bluetooth          | Audio stereo, musica / sirene / TTS                                          |

---

## Architettura software

Tutto comunica via **MQTT** (Mosquitto su RPi, `localhost:1883`, accessibile anche via Tailscale).

```
              ┌─────────────────────────┐
              │  Mosquitto Broker (RPi) │
              └────────────┬────────────┘
     ┌──────────┬──────────┼──────────┬──────────┐
     │          │          │          │          │
odometria   occupancy   navigator  drone_bridge  GPS
     │        grid.py      .py        .py       .py
     │          │
  robot/     robot/
 motori/     mappa/
 stato       grid
```

**Topic principali:**

| Topic                    | Direzione   | Descrizione                     |
| ------------------------ | ----------- | ------------------------------- |
| `robot/motori/cmd`       | Pi → ESP32  | Comandi movimento               |
| `robot/motori/stato`     | ESP32 → Pi  | Encoder + PWM                   |
| `robot/sensori/distanze` | ESP32 → Pi  | Distanze HC-SR04 (cm)           |
| `robot/sensori/imu`      | ESP32 → Pi  | Accelerometro + giroscopio      |
| `robot/odometria`        | Pi → tutti  | Posa X, Y, θ                    |
| `robot/mappa/grid`       | Pi → viewer | Occupancy grid JSON             |
| `robot/cliff/stato`      | Pi → tutti  | Stato sensori cliff             |
| `robot/nav/cmd`          | app → Pi    | `start` / `stop` / `reset_goal` |
| `robot/nav/goal`         | app → Pi    | Goal `{x, y}` in world frame    |
| `drone/cmd/rpyt`         | app → Pi    | Roll, pitch, yaw, thrust        |
| `macchinina/audio/stop`  | server → Pi | Stop streaming audio            |

---

## Installazione (Raspberry Pi)

```bash
# Dipendenze Python
pip install paho-mqtt numpy sounddevice onnxruntime websockets \
            flask flask-socketio pyserial pynmea2 faster-whisper psutil

# Mosquitto broker
sudo apt install mosquitto mosquitto-clients
sudo systemctl enable mosquitto

# Driver ReSpeaker 2-Mic HAT
# Seguire istruzioni in docs/ o repo seeed-voicecard

# Avviare i moduli (esempio)
python3 raspberry/odometria.py &
python3 raspberry/occupancyGrid.py &
python3 raspberry/navigator.py &
python3 raspberry/GPS.py &
python3 raspberry/myViewerServer.py &
python3 raspberry/streamCamera.py &
```

**Dashboard web:** `http://<ip-pi>:8080`  
**Stream camera:** `http://<ip-pi>:8080/stream`  
**Accesso remoto:** `http://100.100.61.49:8080` (via Tailscale)

---

## Firmware ESP32 (PlatformIO)

Librerie richieste (`platformio.ini`):

```
PubSubClient
ArduinoJson
MPU6050_light
Adafruit PWM Servo Driver
Preferences
```

Le credenziali WiFi e broker MQTT vengono salvate in NVS e possono essere aggiornate via I2C dal Pi senza reflashare.

---

## Pipeline AI vocale

```
ReSpeaker mic → wakeword.py (hey_no_va.onnx)
    → DOA GCC-PHAT (stima direzione)
    → WebSocket stream PCM16 raw → ws://100.120.32.86:5000
    → Whisper STT → LLM → Piper TTS (voce "Miro" italiano)
    → audio risposta → Speaker Bluetooth
```

---

## Licenza

[Hippocratic License 3.0](https://firstdonoharm.dev/version/3/0/cl-eco-law-mil-sv.txt) (HL3-CL-ECO-LAW-MIL-SV) — © 2025 Dragonyx
