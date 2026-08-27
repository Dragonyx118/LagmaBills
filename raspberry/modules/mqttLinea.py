#!/usr/bin/env python3
"""
════════════════════════════════════════════════════════════════
  INSEGUI LINEA — Raspberry Pi (broker MQTT)
  Ruote Mecanum | 3 sensori TCRT5000 sull'ESP32 sensori

  Topic IN  : robot/sensori/tcrt   → {"sx":0/1, "cen":0/1, "dx":0/1}
  Topic OUT : robot/motori/cmd     → {"cmd":"mecanum", "vx":..., "vy":..., "vr":...}
              robot/motori/cmd     → {"cmd":"stop"}

  Logica TCRT (1 = nero = linea rilevata):
  ┌─────┬───────┬─────┬──────────────────────────────────────┐
  │ SX  │  CEN  │ DX  │ Azione                               │
  ├─────┼───────┼─────┼──────────────────────────────────────┤
  │  0  │   1   │  0  │ CENTRATO → vai avanti                │
  │  0  │   0   │  1  │ LINEA A DX → ruota destra (vr>0)    │
  │  1  │   0   │  0  │ LINEA A SX → ruota sinistra (vr<0)  │
  │  1  │   1   │  0  │ LEGGERMENTE A SX → correzione lieve  │
  │  0  │   1   │  1  │ LEGGERMENTE A DX → correzione lieve  │
  │  1  │   1   │  1  │ INCROCIO → vai avanti                │
  │  0  │   0   │  0  │ LINEA PERSA → comportamento recovery │
  │  1  │   0   │  1  │ RUMORE → ignora                      │
  └─────┴───────┴─────┴──────────────────────────────────────┘

  Il comando mecanum usa:
    vx = movimento laterale (non usato qui, rimane 0)
    vy = avanti/indietro  (positivo = avanti)
    vr = rotazione        (positivo = destra, negativo = sinistra)

  NOTA: setMotoriCorrected() nell'ESP32 motori inverte già FL e RL,
  quindi da qui mandiamo valori logici normali senza preoccuparcene.
════════════════════════════════════════════════════════════════
"""

import json
import time
import logging
import paho.mqtt.client as mqtt

# ── CONFIGURAZIONE ───────────────────────────────────────────────

MQTT_BROKER   = "localhost"   # il Raspberry è il broker
MQTT_PORT     = 1883
MQTT_CLIENT   = "line_follower_pi"

TOPIC_TCRT    = "robot/sensori/tcrt"
TOPIC_CMD     = "robot/motori/cmd"
TOPIC_LOG     = "robot/follower/log"

# ── VELOCITÀ ─────────────────────────────────────────────────────

VEL_AVANTI        = 120   # velocità base in avanti  (0–255)
VEL_CORREZIONE    = 60    # componente di rotazione per correzioni lievi
VEL_CORREZIONE_F  = 110   # rotazione forte (linea tutta da un lato)
VEL_RECOVERY      = 80    # velocità rotazione nella recovery

# Quanti cicli di rotazione fare durante la recovery prima di fermarsi.
# Ogni ciclo dura ~LOOP_HZ ms → 30 cicli a 20Hz = 1.5 s di ricerca.
RECOVERY_MAX_CICLI = 30
LOOP_HZ            = 20  # frequenza del loop principale (Hz)

# ── LOGGING ──────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S"
)
log = logging.getLogger("follower")

# ═════════════════════════════════════════════════════════════════

class LineFollower:
    """Controller principale insegui-linea via MQTT."""

    def __init__(self):
        self.client = mqtt.Client(client_id=MQTT_CLIENT)
        self.client.on_connect    = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message    = self._on_message

        # Ultimo stato TCRT ricevuto
        self.tcrt = {"sx": 0, "cen": 0, "dx": 0}
        self.tcrt_updated = False   # flag: nuovo dato disponibile

        # Stato recovery
        self.recovery_cicli   = 0
        self.recovery_dir     = None   # "dx" o "sx" — ultima direzione nota

        self.running = True

    # ── MQTT ─────────────────────────────────────────────────────

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            log.info("MQTT connesso al broker %s:%d", MQTT_BROKER, MQTT_PORT)
            client.subscribe(TOPIC_TCRT)
            log.info("Sottoscritto a '%s'", TOPIC_TCRT)
            self._publog("line_follower online")
        else:
            log.error("Connessione MQTT fallita, rc=%d", rc)

    def _on_disconnect(self, client, userdata, rc):
        log.warning("MQTT disconnesso (rc=%d), riconnessione automatica...", rc)

    def _on_message(self, client, userdata, msg):
        """Callback per ogni messaggio MQTT ricevuto."""
        if msg.topic == TOPIC_TCRT:
            try:
                dati = json.loads(msg.payload.decode())
                self.tcrt = {
                    "sx":  int(dati.get("sx",  0)),
                    "cen": int(dati.get("cen", 0)),
                    "dx":  int(dati.get("dx",  0)),
                }
                self.tcrt_updated = True
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("Payload TCRT non valido: %s — %s", msg.payload, e)

    # ── PUBLISH COMANDI ───────────────────────────────────────────

    def _invia_mecanum(self, vx: int, vy: int, vr: int):
        """Invia un comando mecanum all'ESP32 motori."""
        payload = json.dumps({"cmd": "mecanum", "vx": vx, "vy": vy, "vr": vr})
        self.client.publish(TOPIC_CMD, payload)

    def _invia_stop(self):
        """Ferma tutti i motori."""
        self.client.publish(TOPIC_CMD, json.dumps({"cmd": "stop"}))

    def _publog(self, msg: str):
        self.client.publish(TOPIC_LOG, msg)

    # ── LOGICA INSEGUI LINEA ──────────────────────────────────────

    def _aggiorna_recovery_dir(self, sx: int, dx: int):
        """Memorizza l'ultima direzione valida per la recovery."""
        if dx and not sx:
            self.recovery_dir = "dx"
        elif sx and not dx:
            self.recovery_dir = "sx"

    def _step(self):
        """
        Esegue un singolo ciclo di controllo.
        Chiamato a ~LOOP_HZ Hz dal loop principale.
        """
        if not self.tcrt_updated:
            # Nessun dato nuovo → mantieni stato precedente (non fermare)
            return

        self.tcrt_updated = False
        sx  = self.tcrt["sx"]
        cen = self.tcrt["cen"]
        dx  = self.tcrt["dx"]
        mask = (sx << 2) | (cen << 1) | dx

        log.debug("TCRT mask=0b%03b  sx=%d cen=%d dx=%d", mask, sx, cen, dx)

        # ── Aggiorna direzione recovery prima di decidere ──────────
        self._aggiorna_recovery_dir(sx, dx)

        # ── Decisione in base alla maschera ────────────────────────

        if mask == 0b010:
            # 0b010 — Solo centro: CENTRATO → avanti
            log.debug("→ CENTRATO")
            self.recovery_cicli = 0
            self._invia_mecanum(0, VEL_AVANTI, 0)

        elif mask == 0b001:
            # 0b001 — Solo destra: linea a destra → ruota destra (vr positivo)
            log.debug("→ DEVIA DX (forte)")
            self.recovery_cicli = 0
            self._invia_mecanum(0, VEL_AVANTI // 2, VEL_CORREZIONE_F)

        elif mask == 0b100:
            # 0b100 — Solo sinistra: linea a sinistra → ruota sinistra (vr negativo)
            log.debug("→ DEVIA SX (forte)")
            self.recovery_cicli = 0
            self._invia_mecanum(0, VEL_AVANTI // 2, -VEL_CORREZIONE_F)

        elif mask == 0b011:
            # 0b011 — Centro + destra: leggermente a destra → correzione lieve
            log.debug("→ LIEVE DX")
            self.recovery_cicli = 0
            self._invia_mecanum(0, VEL_AVANTI, VEL_CORREZIONE)

        elif mask == 0b110:
            # 0b110 — Sinistra + centro: leggermente a sinistra → correzione lieve
            log.debug("→ LIEVE SX")
            self.recovery_cicli = 0
            self._invia_mecanum(0, VEL_AVANTI, -VEL_CORREZIONE)

        elif mask == 0b111:
            # 0b111 — Tutti: incrocio o linea larga → vai avanti
            log.debug("→ INCROCIO / linea larga")
            self.recovery_cicli = 0
            self._invia_mecanum(0, VEL_AVANTI, 0)

        elif mask == 0b101:
            # 0b101 — Sinistra + destra senza centro: rumore → ignora
            log.debug("→ RUMORE, ignoro")
            pass

        elif mask == 0b000:
            # 0b000 — Nessun sensore: LINEA PERSA → recovery
            self._recovery()

    def _recovery(self):
        """
        Strategia di recovery: ruota nella direzione dell'ultima
        linea vista fino a ritrovarla, poi si ferma dopo RECOVERY_MAX_CICLI.
        """
        if self.recovery_cicli == 0:
            log.warning("LINEA PERSA — inizio recovery (dir=%s)", self.recovery_dir)
            self._publog("linea persa - recovery")

        self.recovery_cicli += 1

        if self.recovery_cicli > RECOVERY_MAX_CICLI:
            # Linea non ritrovata → STOP
            log.error("Recovery fallita dopo %d cicli → STOP", RECOVERY_MAX_CICLI)
            self._publog("recovery fallita - STOP")
            self._invia_stop()
            return

        # Ruota verso l'ultima direzione vista
        if self.recovery_dir == "dx":
            self._invia_mecanum(0, 0, VEL_RECOVERY)
        else:
            # default: ruota sinistra se non abbiamo info
            self._invia_mecanum(0, 0, -VEL_RECOVERY)

    # ── LOOP PRINCIPALE ──────────────────────────────────────────

    def avvia(self):
        """Connette al broker e avvia il loop di controllo."""
        self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=15)
        self.client.loop_start()   # thread MQTT in background

        log.info("Line follower avviato. CTRL+C per fermare.")
        periodo = 1.0 / LOOP_HZ

        try:
            while self.running:
                t0 = time.monotonic()
                self._step()
                elapsed = time.monotonic() - t0
                sleep_t = max(0.0, periodo - elapsed)
                time.sleep(sleep_t)

        except KeyboardInterrupt:
            log.info("Interruzione da tastiera — stop.")

        finally:
            self._invia_stop()
            time.sleep(0.2)
            self.client.loop_stop()
            self.client.disconnect()
            log.info("Disconnesso. Uscita.")


# ═════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Insegui linea MQTT — Ruote Mecanum")
    parser.add_argument("--broker",        default=MQTT_BROKER,        help="IP/hostname broker MQTT")
    parser.add_argument("--port",    type=int, default=MQTT_PORT,      help="Porta broker MQTT")
    parser.add_argument("--vel",     type=int, default=VEL_AVANTI,     help="Velocità avanti (0-255)")
    parser.add_argument("--corr",    type=int, default=VEL_CORREZIONE, help="Forza correzione lieve (0-255)")
    parser.add_argument("--corr-f",  type=int, default=VEL_CORREZIONE_F, help="Forza correzione forte (0-255)")
    parser.add_argument("--debug",   action="store_true",              help="Abilita log DEBUG")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Aggiorna costanti con i parametri da linea di comando
    MQTT_BROKER       = args.broker
    MQTT_PORT         = args.port
    VEL_AVANTI        = args.vel
    VEL_CORREZIONE    = args.corr
    VEL_CORREZIONE_F  = args.corr_f

    follower = LineFollower()
    follower.avvia()