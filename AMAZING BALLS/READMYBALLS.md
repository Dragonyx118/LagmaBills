# 🤖 Robot Arm - Guida Completa

## Architettura del sistema

```
┌─────────────────────────────────────────────────────────┐
│  Smartphone / PC (Browser)                              │
│  └── Web Dashboard (index.html)                         │
└─────────────────────┬───────────────────────────────────┘
                      │ HTTP REST (WiFi)
┌─────────────────────▼───────────────────────────────────┐
│  Raspberry Pi                                           │
│  └── robot_arm_server.py (Flask, porta 5000)            │
└─────────────────────┬───────────────────────────────────┘
                      │ I2C (GPIO 2/3, bus 1)
┌─────────────────────▼───────────────────────────────────┐
│  ESP32                                                  │
│  ├── I2C slave (GPIO 16/17) ← RPi                       │
│  └── I2C master (GPIO 21/22) → PCA9685                  │
└─────────────────────┬───────────────────────────────────┘
                      │ PWM (16 canali)
┌─────────────────────▼───────────────────────────────────┐
│  PCA9685 Servo Driver                                   │
│  ├── CH0 → Servo 0: Base    (MG996R)                    │
│  ├── CH1 → Servo 1: Spalla  (MG996R)                    │
│  ├── CH2 → Servo 2: Gomito  (MG996R)                    │
│  ├── CH3 → Servo 3: Polso P (SG90)                      │
│  ├── CH4 → Servo 4: Polso R (SG90)                      │
│  └── CH5 → Servo 5: Gripper (SG90)                      │
└─────────────────────────────────────────────────────────┘
```

---

## Schema di collegamento

### ESP32 → PCA9685 (Bus I2C Master)
| ESP32   | PCA9685 |
|---------|---------|
| GPIO 21 (SDA) | SDA |
| GPIO 22 (SCL) | SCL |
| 3.3V    | VCC     |
| GND     | GND     |
| 5V ext  | V+      |  ← alimentazione servo (≥2A)

### Raspberry Pi → ESP32 (Bus I2C)
| RPi GPIO | ESP32   |
|----------|---------|
| GPIO 2 (SDA, pin 3) | GPIO 17 |
| GPIO 3 (SCL, pin 5) | GPIO 16 |
| GND (pin 6)         | GND     |

> ⚠️ **Importante:** RPi usa 3.3V su I2C, ESP32 è 3.3V compatibile → collegamento diretto OK.

### Alimentazione servo
```
Alimentatore 5V 3A ──► V+ PCA9685 (pin barilotto o morsetti)
                   └──► GND comune (ESP32, RPi, PCA9685)
```

---

## Installazione ESP32

### Librerie Arduino IDE necessarie
- `Adafruit PWM Servo Driver Library` (by Adafruit)
- `Wire` (inclusa)

### Passi
1. Apri Arduino IDE
2. Installa librerie via Library Manager
3. Seleziona board: **ESP32 Dev Module**
4. Carica `robot_arm_esp32.ino`

---

## Installazione Raspberry Pi

### Abilita I2C
```bash
sudo raspi-config
# → Interface Options → I2C → Enable
```

### Dipendenze Python
```bash
pip install flask flask-cors smbus2
```

### Avvio server
```bash
python3 robot_arm_server.py
```

### Avvio automatico al boot (systemd)
```bash
sudo nano /etc/systemd/system/robotarm.service
```
```ini
[Unit]
Description=Robot Arm Server
After=network.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/robot_arm/robot_arm_server.py
WorkingDirectory=/home/pi/robot_arm
Restart=always
User=pi

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl enable robotarm
sudo systemctl start robotarm
```

---

## Dashboard Web

Apri il browser e vai su:
```
http://<IP_RASPBERRY>:5000/
```

Oppure apri `index.html` localmente e imposta l'IP del RPi nella variabile `API` in cima allo script.

---

## API REST completa

| Metodo | Endpoint | Body | Descrizione |
|--------|----------|------|-------------|
| GET | `/status` | — | Stato corrente |
| POST | `/servo/<0-5>` | `{"angle": 90}` | Muovi servo singolo |
| POST | `/move_all` | `{"angles": [90,150,35,140,85,80]}` | Muovi tutti |
| POST | `/home` | — | Posizione HOME |
| POST | `/speed` | `{"speed": 50}` | Velocità (1-100) |
| POST | `/save_step` | — | Salva posizione corrente |
| POST | `/run_sequence` | — | Esegui sequenza |
| POST | `/reset_sequence` | — | Cancella sequenza |
| GET | `/sequence` | — | Lista step salvati |
| POST | `/preset/<nome>` | — | Esegui preset |
| GET | `/presets` | — | Lista preset disponibili |
| POST | `/pick` | `{"waist_angle": 90}` | Sequenza pick automatica |
| POST | `/place` | `{"waist_angle": 0}` | Sequenza place automatica |

### Preset disponibili
- `home` — posizione di riposo
- `pick_ready` — pronto per raccogliere
- `pick_open` — pinza aperta
- `pick_close` — pinza chiusa
- `place_ready` — pronto per depositare
- `place_drop` — rilascia oggetto
- `wave` — posizione laterale
- `rest` — braccio abbassato

### Esempio curl
```bash
# Muovi il servo base a 45°
curl -X POST http://192.168.1.10:5000/servo/0 -H "Content-Type: application/json" -d '{"angle":45}'

# Esegui sequenza pick
curl -X POST http://192.168.1.10:5000/pick -d '{"waist_angle": 90}'
```

---

## Protocollo I2C ESP32 (per sviluppatori)

| Byte 0 (cmd) | Payload | Azione |
|---|---|---|
| `0x01` | `[id, angolo]` | Muovi servo singolo |
| `0x02` | `[a0,a1,a2,a3,a4,a5]` | Muovi tutti |
| `0x03` | — | HOME |
| `0x04` | — | Richiedi stato (read) |
| `0x05` | `[velocità 1-100]` | Imposta velocità |
| `0x06` | — | Salva step corrente |
| `0x07` | — | Esegui sequenza |
| `0x08` | — | Reset sequenza |

---

## Troubleshooting

**I2C non trovato:**
```bash
i2cdetect -y 1   # deve mostrare 0x08 (ESP32)
```

**Servo tremano:**
- Verifica alimentazione (almeno 2A per MG996R)
- Aumenta `speedDelay` nell'ESP32

**Connessione dashboard fallisce:**
- Verifica IP RPi
- Controlla firewall: `sudo ufw allow 5000`
