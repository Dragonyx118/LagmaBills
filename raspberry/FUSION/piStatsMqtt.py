#!/usr/bin/env python3
"""
piStatsMqtt.py — LagmaBills
Pubblica periodicamente le statistiche del Raspberry Pi su MQTT
per il topbar dell'app LagmaIpp (CPU%, RAM%, RAM libera, temperatura).

Publish (retained):
  robot/pi/stats → {"cpu_pct": float, "ram_pct": float,
                     "ram_free_mb": float, "temp_c": float, "ts": float}

Dipendenze: pip install psutil paho-mqtt --break-system-packages
"""

import time
import json
import subprocess
import psutil
import paho.mqtt.client as mqtt

MQTT_BROKER = "localhost"
MQTT_PORT   = 1883
TOPIC       = "robot/pi/stats"
PUBLISH_INTERVAL_S = 2


def get_temp_c() -> float:
    try:
        out = subprocess.check_output(["vcgencmd", "measure_temp"]).decode()
        return float(out.replace("temp=", "").replace("'C\n", "").strip())
    except Exception as e:
        print(f"[piStats] Errore lettura temperatura: {e}")
        return -1.0


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="pi_stats")

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[piStats] Impossibile connettersi al broker: {e}")
        return

    client.loop_start()
    print(f"[piStats] Avviato, publish ogni {PUBLISH_INTERVAL_S}s su '{TOPIC}'")

    # "Riscalda" psutil: la prima chiamata a cpu_percent() ritorna sempre 0.0
    psutil.cpu_percent(interval=None)
    time.sleep(1)

    try:
        while True:
            mem = psutil.virtual_memory()
            payload = {
                "cpu_pct":     round(psutil.cpu_percent(interval=None), 1),
                "ram_pct":     round(mem.percent, 1),
                "ram_free_mb": round(mem.available / 1024 / 1024, 1),
                "temp_c":      get_temp_c(),
                "ts":          time.time(),
            }
            client.publish(TOPIC, json.dumps(payload), retain=True)
            time.sleep(PUBLISH_INTERVAL_S)
    except KeyboardInterrupt:
        print("\n[piStats] Interrotto")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
