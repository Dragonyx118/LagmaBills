#!/usr/bin/env python3
"""
gps_mqtt.py — LagmaBills
Legge il GPS NEO-6M via seriale e pubblica su MQTT topic robot/gps

Topic publish: robot/gps
Payload: {"lat": float, "lon": float, "alt": float,
          "speed": float, "sat": int, "ts": float}

Dipendenze: pip install pyserial pynmea2 paho-mqtt
"""

import json
import time
import serial
import pynmea2
import paho.mqtt.client as mqtt

# ── CONFIGURAZIONE ───────────────────────────────────────────────
PORTA       = "/dev/ttyS0"
BAUD        = 9600
MQTT_BROKER = "100.100.61.49"
MQTT_PORT   = 1883
TOPIC       = "robot/gps"
CLIENT_ID   = "gps_publisher"

# ── MQTT ─────────────────────────────────────────────────────────
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=CLIENT_ID)

def on_connect(c, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"[GPS] MQTT connesso a {MQTT_BROKER}")
    else:
        print(f"[GPS] MQTT errore rc={rc}")

client.on_connect = on_connect

def main():
    client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    client.loop_start()

    ultima_gga = {}

    try:
        ser = serial.Serial(PORTA, BAUD, timeout=1)
        print(f"[GPS] Seriale aperta su {PORTA} @ {BAUD} baud")

        while True:
            linea = ser.readline().decode("ascii", errors="replace").strip()
            if not linea.startswith("$"):
                continue

            try:
                msg = pynmea2.parse(linea)

                # GGA: posizione + satelliti + altitudine
                if isinstance(msg, pynmea2.GGA) and msg.gps_qual > 0:
                    ultima_gga = {
                        "lat": msg.latitude,
                        "lon": msg.longitude,
                        "alt": float(msg.altitude) if msg.altitude else 0.0,
                        "sat": int(msg.num_sats)   if msg.num_sats  else 0,
                    }

                # RMC: velocità + validità fix
                elif isinstance(msg, pynmea2.RMC) and msg.status == "A" and ultima_gga:
                    payload = {
                        "lat":   ultima_gga["lat"],
                        "lon":   ultima_gga["lon"],
                        "alt":   ultima_gga["alt"],
                        "sat":   ultima_gga["sat"],
                        "speed": float(msg.spd_over_grnd) if msg.spd_over_grnd else 0.0,
                        "ts":    time.time(),
                    }
                    client.publish(TOPIC, json.dumps(payload))
                    print(f"[GPS] Lat:{payload['lat']:.6f} Lon:{payload['lon']:.6f} "
                          f"Alt:{payload['alt']:.1f}m Sat:{payload['sat']} "
                          f"Vel:{payload['speed']:.1f}kn")

            except pynmea2.ParseError:
                pass

    except KeyboardInterrupt:
        print("\n[GPS] Interruzione")
    finally:
        ser.close()
        client.loop_stop()
        client.disconnect()

if __name__ == "__main__":
    main()
