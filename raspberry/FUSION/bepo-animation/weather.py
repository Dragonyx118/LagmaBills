"""
weather.py — FUSION / RoboEyes
Recupero meteo (posizione via IP + Open-Meteo) usato da sequences/weather.py.
Identico all'originale: in caso di errore di rete ritorna un meteo casuale
di fallback così l'animazione funziona comunque offline.
"""

import random
import urllib.request
import json


def get_gps_weather():
    try:
        url = "http://ip-api.com/json/?fields=lat,lon,city"
        req = urllib.request.urlopen(url, timeout=3)
        data = json.loads(req.read())
        lat = data.get("lat", 44.4)
        lon = data.get("lon", 8.9)
        city = data.get("city", "ROBOT CITY")
        wurl = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weathercode&wind_speed_unit=ms"
        wreq = urllib.request.urlopen(wurl, timeout=3)
        wdata = json.loads(wreq.read())
        temp_c = wdata["current"]["temperature_2m"]
        wcode = wdata["current"]["weathercode"]
        if wcode == 0: kind = "sunny"; label = "SUNNY"
        elif wcode in (1, 2, 3): kind = "cloud"; label = "CLOUDY"
        elif wcode in range(51, 68): kind = "rain"; label = "RAINY"
        elif wcode in range(71, 78): kind = "snow"; label = "SNOWY"
        elif wcode in range(80, 100): kind = "storm"; label = "STORMY"
        else: kind = "cloud"; label = "CLOUDY"
        color_map = {"sunny": (255, 220, 0), "rain": (100, 160, 255), "cloud": (180, 180, 180),
                     "storm": (120, 80, 200), "snow": (220, 240, 255)}
        col = color_map.get(kind, (180, 180, 180))
        return (label, f"{temp_c:.0f}°C", col, kind, city.upper())
    except Exception:
        weathers = [
            ("SUNNY", "28°C", (255, 220, 0), "sunny"),
            ("RAINY", "14°C", (100, 160, 255), "rain"),
            ("CLOUDY", "18°C", (180, 180, 180), "cloud"),
            ("STORMY", "11°C", (120, 80, 200), "storm"),
            ("SNOWY", "-2°C", (220, 240, 255), "snow"),
        ]
        w = random.choice(weathers)
        return (w[0], w[1], w[2], w[3], "ROBOT CITY")
