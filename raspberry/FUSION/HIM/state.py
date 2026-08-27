#!/usr/bin/env python3
"""
pi_stato.py — Pubblica periodicamente lo stato del Raspberry Pi su MQTT.
Topic: pi/stato
Broker: localhost:1883 (il Pi stesso è il broker)

Dipendenze:
    pip install paho-mqtt psutil gpiozero

Avvio automatico (systemd):
    Vedi sezione in fondo al file.
"""

import json
import time
import socket
import logging
import threading
from datetime import datetime

import psutil
import paho.mqtt.client as mqtt

# ── Configurazione ────────────────────────────────────────────────────────────

BROKER_HOST   = "100.100.61.49"   # oppure "localhost" / "127.0.0.1"
BROKER_PORT   = 1883
TOPIC_STATO   = "pi/stato"
TOPIC_ALIVE   = "pi/alive"        # heartbeat booleano separato
INTERVALLO_S  = 5                 # secondi tra una pubblicazione e l'altra
QOS           = 0
RETAIN        = True              # l'ultimo stato resta disponibile ai nuovi subscriber

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("pi_stato")

# ── Lettura sensori ───────────────────────────────────────────────────────────

def _cpu_temp() -> float | None:
    """Temperatura CPU in °C (funziona su Pi con vcgencmd o thermal_zone)."""
    # Metodo 1: vcgencmd (Raspberry Pi OS)
    try:
        import subprocess
        out = subprocess.check_output(
            ["vcgencmd", "measure_temp"], text=True, timeout=2
        )
        return float(out.strip().replace("temp=", "").replace("'C", ""))
    except Exception:
        pass
    # Metodo 2: thermal_zone sysfs (generico Linux)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000, 1)
    except Exception:
        return None


def _gpu_temp() -> float | None:
    """Temperatura GPU VideoCore (solo Pi con vcgencmd)."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["vcgencmd", "measure_temp", "vc4"], text=True, timeout=2
        )
        return float(out.strip().replace("temp=", "").replace("'C", ""))
    except Exception:
        return None


def _ip_principale() -> str:
    """IP dell'interfaccia di default (non 127.0.0.1)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "N/A"


def _tutte_le_ip() -> dict[str, str]:
    """Dizionario interfaccia → primo IPv4 trovato."""
    risultato = {}
    for iface, addrs in psutil.net_if_addrs().items():
        for addr in addrs:
            if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                risultato[iface] = addr.address
                break
    return risultato


def _throttle_flags() -> dict[str, bool] | None:
    """Legge i flag di throttling del Pi via vcgencmd (under-voltage, freq cap, ecc.)."""
    try:
        import subprocess
        out = subprocess.check_output(
            ["vcgencmd", "get_throttled"], text=True, timeout=2
        )
        val = int(out.strip().replace("throttled=", ""), 16)
        return {
            "under_voltage_now":    bool(val & (1 << 0)),
            "freq_capped_now":      bool(val & (1 << 1)),
            "throttled_now":        bool(val & (1 << 2)),
            "temp_limit_now":       bool(val & (1 << 3)),
            "under_voltage_ever":   bool(val & (1 << 16)),
            "freq_capped_ever":     bool(val & (1 << 17)),
            "throttled_ever":       bool(val & (1 << 18)),
            "temp_limit_ever":      bool(val & (1 << 19)),
        }
    except Exception:
        return None


def _frequenza_cpu_mhz() -> list[float]:
    """Frequenza attuale per ogni core (MHz)."""
    try:
        freqs = psutil.cpu_freq(percpu=True)
        if freqs:
            return [round(f.current, 0) for f in freqs]
        freq = psutil.cpu_freq()
        return [round(freq.current, 0)] if freq else []
    except Exception:
        return []


def raccogli_stato() -> dict:
    """Assembla il dizionario di stato completo del Pi."""
    mem   = psutil.virtual_memory()
    swap  = psutil.swap_memory()
    disco = psutil.disk_usage("/")
    uptime_s = int(time.time() - psutil.boot_time())

    stato: dict = {
        # ── Timestamp ──────────────────────────────────────────────────────
        "ts":           datetime.utcnow().isoformat() + "Z",
        "uptime_s":     uptime_s,

        # ── Temperatura ────────────────────────────────────────────────────
        "temp":         _cpu_temp(),
        "temp_gpu":     _gpu_temp(),

        # ── CPU ────────────────────────────────────────────────────────────
        "cpu":          psutil.cpu_percent(interval=None),   # % uso (tutti i core)
        "cpu_cores":    psutil.cpu_count(logical=True),
        "cpu_per_core": psutil.cpu_percent(interval=None, percpu=True),
        "cpu_freq_mhz": _frequenza_cpu_mhz(),

        # ── RAM ────────────────────────────────────────────────────────────
        "ram_used":     round(mem.used / 1024**2, 1),        # MB
        "ram_total":    round(mem.total / 1024**2, 1),       # MB
        "ram_percent":  mem.percent,

        # ── Swap ───────────────────────────────────────────────────────────
        "swap_used":    round(swap.used / 1024**2, 1),       # MB
        "swap_total":   round(swap.total / 1024**2, 1),      # MB
        "swap_percent": swap.percent,

        # ── Disco (/) ──────────────────────────────────────────────────────
        "disk_used":    round(disco.used / 1024**3, 2),      # GB
        "disk_total":   round(disco.total / 1024**3, 2),     # GB
        "disk_percent": disco.percent,

        # ── Rete ───────────────────────────────────────────────────────────
        "ip":           _ip_principale(),
        "ip_all":       _tutte_le_ip(),

        # ── Throttling (solo Pi) ───────────────────────────────────────────
        "throttle":     _throttle_flags(),

        # ── Hostname ───────────────────────────────────────────────────────
        "hostname":     socket.gethostname(),
    }

    # Rimuovi None per JSON più pulito
    return {k: v for k, v in stato.items() if v is not None}


# ── MQTT ──────────────────────────────────────────────────────────────────────

_connesso = threading.Event()


def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        log.info("Connesso al broker MQTT %s:%d", BROKER_HOST, BROKER_PORT)
        _connesso.set()
        # LWT contrario: ora siamo online
        client.publish(TOPIC_ALIVE, payload="true", qos=1, retain=True)
    else:
        log.warning("Connessione fallita, rc=%d — riprovo…", rc)
        _connesso.clear()


def _on_disconnect(client, userdata, rc):
    log.warning("Disconnesso (rc=%d)", rc)
    _connesso.clear()


def crea_client() -> mqtt.Client:
    client = mqtt.Client(client_id="pi-stato-publisher", clean_session=True)

    # Last Will Testament: se il Pi sparisce, il broker pubblica "false"
    client.will_set(TOPIC_ALIVE, payload="false", qos=1, retain=True)

    client.on_connect    = _on_connect
    client.on_disconnect = _on_disconnect
    return client


def loop_pubblicazione(client: mqtt.Client):
    """Pubblica lo stato ogni INTERVALLO_S secondi."""
    # Prima lettura CPU (il primo cpu_percent() restituisce sempre 0)
    psutil.cpu_percent(interval=None)
    psutil.cpu_percent(interval=None, percpu=True)
    time.sleep(1)

    while True:
        if _connesso.is_set():
            try:
                stato = raccogli_stato()
                payload = json.dumps(stato, ensure_ascii=False)
                result = client.publish(TOPIC_STATO, payload=payload, qos=QOS, retain=RETAIN)
                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    log.info("Pubblicato su %s — cpu=%.1f%% temp=%s°C",
                             TOPIC_STATO,
                             stato.get("cpu", 0),
                             stato.get("temp", "N/A"))
                else:
                    log.warning("Pubblicazione fallita, rc=%d", result.rc)
            except Exception as e:
                log.error("Errore durante la raccolta dati: %s", e)
        else:
            log.debug("Non connesso, attendo…")

        time.sleep(INTERVALLO_S)


def main():
    client = crea_client()

    log.info("Connessione a %s:%d …", BROKER_HOST, BROKER_PORT)
    client.connect_async(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()                 # thread MQTT in background

    # Aspetta connessione (max 30 s)
    if not _connesso.wait(timeout=30):
        log.error("Timeout connessione MQTT. Verificare broker e rete.")

    try:
        loop_pubblicazione(client)
    except KeyboardInterrupt:
        log.info("Interruzione richiesta — esco.")
    finally:
        client.publish(TOPIC_ALIVE, payload="false", qos=1, retain=True)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
