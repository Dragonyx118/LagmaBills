"""
mqtt_bridge.py — FUSION / RoboEyes
Collega la faccina al broker MQTT: ascolta robot/face (mood o
animazione per nome) e robot/cmd (JSON con face_emotion dall'AI).
Identico al comportamento originale, solo isolato dal resto.
"""

import os
import json

import paho.mqtt.client as mqtt

from constants import MQTT_MOOD_MAP, EMOTION_MAP


def start_mqtt_face(robo):
    ANIM_MAP = {
        'wink':    lambda: robo.anim_wink('left'),
        'winkr':   lambda: robo.anim_wink('right'),
        'look':    robo.anim_look_around,
        'spin':    robo.anim_spin,
        'shake':   robo.anim_shake,
        'hearts':  robo.anim_hearts,
        'laugh':   robo.anim_laugh,
        'confused_anim': robo.anim_confused,
    }

    def on_message(client, userdata, msg):
        try:
            payload = msg.payload.decode().strip()
        except Exception:
            return

        # JSON dall'AI (robot/cmd)
        try:
            data = json.loads(payload)
            emotion = data.get("face_emotion", "").strip().lower()
            if emotion in EMOTION_MAP:
                robo.next_mood = EMOTION_MAP[emotion]
            # in futuro qui si possono leggere altri campi dal JSON dell'AI
            return
        except (json.JSONDecodeError, AttributeError):
            pass

        # Comando testuale diretto (robot/face) — mood O animazione
        payload_lower = payload.lower()
        if payload_lower in MQTT_MOOD_MAP:
            robo.next_mood = MQTT_MOOD_MAP[payload_lower]
        elif payload_lower in ANIM_MAP:
            ANIM_MAP[payload_lower]()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = on_message
    try:
        client.connect(os.getenv("MQTT_HOST", "localhost"), int(os.getenv("MQTT_PORT", "1883")), keepalive=60)
        client.subscribe([("robot/face", 0), ("robot/cmd", 0)])
        client.loop_start()
        print("[mqtt] In ascolto su robot/face")
    except Exception as e:
        print(f"[mqtt] Non disponibile: {e}")
