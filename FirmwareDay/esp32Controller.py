#!/usr/bin/env python3
# drone_client.py - Client Windows per drone_mqtt_bridge
# Dipendenze: pip install paho-mqtt  (tkinter è già nella stdlib)

import tkinter as tk
from tkinter import ttk, scrolledtext
import json
import threading
import time
import paho.mqtt.client as mqtt

# ── Configurazione ────────────────────────────────
BROKER_DEFAULT = "100.100.61.49"   # IP del Raspberry Pi sulla rete del drone
PORT           = 1883

TOPIC_CMD    = "drone/cmd/rpyt"
TOPIC_STOP   = "drone/cmd/stop"
TOPIC_STATUS = "drone/status/bridge"
TOPIC_PING   = "drone/cmd/ping"
TOPIC_PONG   = "drone/status/pong"
TOPIC_PARAM  = "drone/cmd/param"

# ── App ───────────────────────────────────────────
class DroneClient(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Drone MQTT Client")
        self.resizable(False, False)

        self.client = None
        self.connected = False
        self._ping_time = None

        self._build_ui()

    # ── UI ────────────────────────────────────────
    def _build_ui(self):
        pad = {"padx": 8, "pady": 4}

        # --- Connessione ---
        conn_frame = ttk.LabelFrame(self, text="Connessione")
        conn_frame.grid(row=0, column=0, columnspan=2, sticky="ew", **pad)

        ttk.Label(conn_frame, text="IP Raspberry:").grid(row=0, column=0, **pad)
        self.broker_var = tk.StringVar(value=BROKER_DEFAULT)
        ttk.Entry(conn_frame, textvariable=self.broker_var, width=18).grid(row=0, column=1, **pad)

        self.btn_connect = ttk.Button(conn_frame, text="Connetti", command=self._toggle_connect)
        self.btn_connect.grid(row=0, column=2, **pad)

        self.status_lbl = ttk.Label(conn_frame, text="● Disconnesso", foreground="red")
        self.status_lbl.grid(row=0, column=3, **pad)

        self.btn_ping = ttk.Button(conn_frame, text="Ping", command=self._ping, state="disabled")
        self.btn_ping.grid(row=0, column=4, **pad)

        self.ping_lbl = ttk.Label(conn_frame, text="")
        self.ping_lbl.grid(row=0, column=5, **pad)

        # --- Comandi volo ---
        fly_frame = ttk.LabelFrame(self, text="Comandi volo  (roll/pitch/yaw: gradi float  |  thrust: 0-65535)")
        fly_frame.grid(row=1, column=0, columnspan=2, sticky="ew", **pad)

        labels = ["Roll", "Pitch", "Yaw", "Thrust"]
        defaults = [0, 0, 0, 0]
        self.fly_vars = []
        for i, (lbl, val) in enumerate(zip(labels, defaults)):
            ttk.Label(fly_frame, text=lbl + ":").grid(row=0, column=i*2, **pad)
            v = tk.StringVar(value=str(val))
            ttk.Entry(fly_frame, textvariable=v, width=8).grid(row=0, column=i*2+1, **pad)
            self.fly_vars.append(v)

        self.btn_send = ttk.Button(fly_frame, text="Invia RPYT", command=self._send_rpyt, state="disabled")
        self.btn_send.grid(row=0, column=8, padx=12, pady=4)

        self.btn_stop = ttk.Button(fly_frame, text="⛔  STOP", command=self._send_stop, state="disabled")
        self.btn_stop.grid(row=0, column=9, padx=4, pady=4)

        # --- Slider thrust rapido ---
        thrust_frame = ttk.LabelFrame(self, text="Thrust rapido")
        thrust_frame.grid(row=2, column=0, columnspan=2, sticky="ew", **pad)

        self.thrust_slider = tk.Scale(
            thrust_frame, from_=0, to=65535, orient="horizontal",
            length=400, command=self._on_slider
        )
        self.thrust_slider.grid(row=0, column=0, **pad)
        self.thrust_val_lbl = ttk.Label(thrust_frame, text="0")
        self.thrust_val_lbl.grid(row=0, column=1, **pad)
        ttk.Button(thrust_frame, text="Applica", command=self._apply_slider).grid(row=0, column=2, **pad)

        # --- Parametri ---
        param_frame = ttk.LabelFrame(self, text="Scrivi parametro CRTP  (es. ring / effect / uint8 / 6)")
        param_frame.grid(row=3, column=0, columnspan=2, sticky="ew", **pad)

        param_labels = ["Group", "Name", "Type", "Value"]
        param_defaults = ["ring", "effect", "uint8", "6"]
        self.param_vars = []
        widths = [10, 12, 8, 8]
        for i, (lbl, val, w) in enumerate(zip(param_labels, param_defaults, widths)):
            ttk.Label(param_frame, text=lbl + ":").grid(row=0, column=i*2, **pad)
            v = tk.StringVar(value=val)
            ttk.Entry(param_frame, textvariable=v, width=w).grid(row=0, column=i*2+1, **pad)
            self.param_vars.append(v)

        self.btn_param = ttk.Button(param_frame, text="Invia parametro", command=self._send_param, state="disabled")
        self.btn_param.grid(row=0, column=8, padx=12, pady=4)

        # --- Preset parametri comuni ---
        preset_frame = ttk.LabelFrame(self, text="Preset LED ring")
        preset_frame.grid(row=4, column=0, columnspan=2, sticky="ew", **pad)

        presets = [
            ("Spegni LED", "ring", "effect", "uint8", "0"),
            ("Rotazione colore", "ring", "effect", "uint8", "6"),
            ("Doppio spin", "ring", "effect", "uint8", "7"),
            ("Lampeggio", "ring", "effect", "uint8", "8"),
        ]
        for i, (name, g, n, t, v) in enumerate(presets):
            ttk.Button(
                preset_frame, text=name,
                command=lambda g=g, n=n, t=t, v=v: self._send_param_direct(g, n, t, v)
            ).grid(row=0, column=i, **pad)

        # --- Log ---
        log_frame = ttk.LabelFrame(self, text="Log")
        log_frame.grid(row=5, column=0, columnspan=2, sticky="ew", **pad)

        self.log = scrolledtext.ScrolledText(log_frame, height=10, width=72, state="disabled", font=("Consolas", 9))
        self.log.grid(row=0, column=0, **pad)
        ttk.Button(log_frame, text="Pulisci", command=self._clear_log).grid(row=0, column=1, padx=4, sticky="n")

    # ── Connessione MQTT ──────────────────────────
    def _toggle_connect(self):
        if self.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        broker = self.broker_var.get().strip()
        self._log(f"Connessione a {broker}:{PORT} ...")
        self.client = mqtt.Client(client_id="drone_win_client")
        self.client.on_connect    = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message    = self._on_message
        try:
            self.client.connect(broker, PORT, keepalive=10)
            self.client.loop_start()
        except Exception as e:
            self._log(f"[ERRORE] {e}")

    def _disconnect(self):
        if self.client:
            self.client.publish(TOPIC_STOP, "")
            self.client.disconnect()
        self.connected = False
        self._set_connected(False)

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            client.subscribe(TOPIC_STATUS)
            client.subscribe(TOPIC_PONG)
            self.after(0, lambda: self._set_connected(True))
            self.after(0, lambda: self._log("[+] Connesso al broker MQTT"))
        else:
            self.after(0, lambda: self._log(f"[!] Connessione fallita (rc={rc})"))

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        self.after(0, lambda: self._set_connected(False))
        self.after(0, lambda: self._log("[!] Disconnesso"))

    def _on_message(self, client, userdata, msg):
        topic   = msg.topic
        payload = msg.payload.decode("utf-8", errors="replace")
        if topic == TOPIC_PONG and self._ping_time:
            rtt = (time.time() - self._ping_time) * 1000
            self._ping_time = None
            self.after(0, lambda: self.ping_lbl.config(text=f"{rtt:.0f} ms"))
            self.after(0, lambda: self._log(f"[PONG] RTT = {rtt:.1f} ms"))
        elif topic == TOPIC_STATUS:
            self.after(0, lambda: self._log(f"[STATUS] {payload}"))

    def _set_connected(self, state: bool):
        color   = "green"  if state else "red"
        text    = "● Connesso" if state else "● Disconnesso"
        btn_txt = "Disconnetti" if state else "Connetti"
        wstate  = "normal" if state else "disabled"
        self.status_lbl.config(text=text, foreground=color)
        self.btn_connect.config(text=btn_txt)
        for w in (self.btn_send, self.btn_stop, self.btn_param, self.btn_ping):
            w.config(state=wstate)

    # ── Invii MQTT ────────────────────────────────
    def _send_rpyt(self):
        try:
            payload = json.dumps({
                "roll":   float(self.fly_vars[0].get()),
                "pitch":  float(self.fly_vars[1].get()),
                "yaw":    float(self.fly_vars[2].get()),
                "thrust": int(self.fly_vars[3].get()),
            })
            self.client.publish(TOPIC_CMD, payload)
            self._log(f"[CMD] {payload}")
        except ValueError as e:
            self._log(f"[ERRORE] Valore non valido: {e}")

    def _send_stop(self):
        self.client.publish(TOPIC_STOP, "")
        self._log("[STOP] Motori fermati")

    def _send_param(self):
        try:
            g = self.param_vars[0].get().strip()
            n = self.param_vars[1].get().strip()
            t = self.param_vars[2].get().strip()
            v = self.param_vars[3].get().strip()
            self._send_param_direct(g, n, t, v)
        except Exception as e:
            self._log(f"[ERRORE] {e}")

    def _send_param_direct(self, group, name, ttype, value):
        if not self.connected:
            self._log("[!] Non connesso")
            return
        try:
            val = float(value) if ttype == "float" else int(value)
        except ValueError:
            val = value
        payload = json.dumps({"group": group, "name": name, "type": ttype, "value": val})
        self.client.publish(TOPIC_PARAM, payload)
        self._log(f"[PARAM] {payload}")

    def _ping(self):
        ts = str(time.time()).encode()
        self._ping_time = time.time()
        self.client.publish(TOPIC_PING, ts)
        self._log("[PING] inviato...")

    # ── Slider ────────────────────────────────────
    def _on_slider(self, val):
        self.thrust_val_lbl.config(text=val)

    def _apply_slider(self):
        self.fly_vars[3].set(str(self.thrust_slider.get()))
        self._send_rpyt()

    # ── Log ───────────────────────────────────────
    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log.config(state="normal")
        self.log.insert("end", f"[{ts}] {msg}\n")
        self.log.see("end")
        self.log.config(state="disabled")

    def _clear_log(self):
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

# ── Entry point ───────────────────────────────────
if __name__ == "__main__":
    app = DroneClient()
    app.mainloop()