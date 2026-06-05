#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║          MQTT ROBOT TESTER — ESP32 Motori + Sensori             ║
║  Broker (Tailscale PC): 100.100.61.49:1883                      ║
║                                                                  ║
║  MOTORI  → robot/motori/cmd       (esp32_motori)                ║
║  SENSORI → robot/sensori/cmd      (esp32_sensori)               ║
╚══════════════════════════════════════════════════════════════════╝

Installa:  pip install paho-mqtt
Uso:       python mqtt_robot_tester.py
"""

import json, threading, time, sys

try:
    import paho.mqtt.client as mqtt
except ImportError:
    print("Installa paho-mqtt:  pip install paho-mqtt")
    sys.exit(1)

BROKER_HOST = "192.168.137.120"
BROKER_PORT = 1883

TOPIC_MOT_CMD  = "robot/motori/cmd"
TOPIC_MOT_STAT = "robot/motori/stato"
TOPIC_SEN_CMD   = "robot/sensori/cmd"
TOPIC_SEN_DIST  = "robot/sensori/distanze"
TOPIC_SEN_IMU   = "robot/sensori/imu"
TOPIC_SEN_TCRT  = "robot/sensori/tcrt"
TOPIC_SEN_SERVO = "robot/sensori/servo"
TOPIC_SEN_RELE  = "robot/sensori/rele"
TOPIC_SEN_STAT  = "robot/sensori/stato"

tel_mot  = {}
tel_dist = {}
tel_imu  = {}
tel_tcrt = {}
tel_servo= {}
tel_rele = {}
mode = "mot"

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print(f"\n[MQTT] Connesso a {BROKER_HOST}:{BROKER_PORT}")
        for t in [TOPIC_MOT_STAT, TOPIC_SEN_DIST, TOPIC_SEN_IMU,
                  TOPIC_SEN_TCRT, TOPIC_SEN_SERVO, TOPIC_SEN_RELE,
                  TOPIC_SEN_STAT, "robot/motori/log", "robot/sensori/log"]:
            client.subscribe(t)
    else:
        print(f"\n[MQTT] Connessione fallita rc={rc}")

def on_disconnect(client, userdata, rc, properties=None, reason=None):
    print(f"\n[MQTT] Disconnesso rc={rc}")

def on_message(client, userdata, msg):
    global tel_mot, tel_dist, tel_imu, tel_tcrt, tel_servo, tel_rele
    try:
        data = json.loads(msg.payload.decode())
    except Exception:
        data = {}
    t = msg.topic
    if t == TOPIC_MOT_STAT:    tel_mot   = data
    elif t == TOPIC_SEN_DIST:  tel_dist  = data
    elif t == TOPIC_SEN_IMU:   tel_imu   = data
    elif t == TOPIC_SEN_TCRT:  tel_tcrt  = data
    elif t == TOPIC_SEN_SERVO: tel_servo = data
    elif t == TOPIC_SEN_RELE:  tel_rele  = data
    elif "log" in msg.topic:
        print(f"\n[LOG] {msg.payload.decode()}")

def send_mot(client, payload):
    msg = json.dumps(payload)
    client.publish(TOPIC_MOT_CMD, msg)
    print(f"\n[TX->MOT] {msg}")

def send_sen(client, payload):
    msg = json.dumps(payload)
    client.publish(TOPIC_SEN_CMD, msg)
    print(f"\n[TX->SEN] {msg}")

def mot(client, c, **kw): send_mot(client, {"cmd": c, **kw})
def sen(client, c, **kw): send_sen(client, {"cmd": c, **kw})

def print_tel_motori():
    if not tel_mot:
        print("\n[INFO] Nessuna telemetria motori.")
        return
    d = tel_mot
    online = "ONLINE" if d.get("online") else "OFFLINE"
    print(f"\n-- Motori [{online}] Vel:{d.get('vel','?')} Stato:{d.get('stato','?')}")
    print(f"   ENC  FL:{d.get('fl',0):6}  FR:{d.get('fr',0):6}  RL:{d.get('rl',0):6}  RR:{d.get('rr',0):6}")
    print(f"   PWM  FL:{d.get('vfl',0):4}  FR:{d.get('vfr',0):4}  RL:{d.get('vrl',0):4}  RR:{d.get('vrr',0):4}")

def print_tel_sensori():
    print("\n-- Distanze")
    if tel_dist:
        for k, v in tel_dist.items():
            bar = "#" * min(int(v / 5), 30) if isinstance(v, (int,float)) and v < 9999 else ""
            print(f"   {k:<10}: {str(v):>5} cm  {bar}")
    else:
        print("   (nessun dato)")
    print("\n-- IMU")
    if tel_imu:
        print(f"   ACC  X:{tel_imu.get('ax',0):6.2f}  Y:{tel_imu.get('ay',0):6.2f}  Z:{tel_imu.get('az',0):6.2f} g")
        print(f"   GYRO X:{tel_imu.get('gx',0):6.2f}  Y:{tel_imu.get('gy',0):6.2f}  Z:{tel_imu.get('gz',0):6.2f} dps")
    print("\n-- TCRT")
    if tel_tcrt:
        sx,cen,dx = tel_tcrt.get("sx",0),tel_tcrt.get("cen",0),tel_tcrt.get("dx",0)
        print(f"   [{'###' if sx else '   '}|{'###' if cen else '   '}|{'###' if dx else '   '}]  SX/CEN/DX")
    print("\n-- Servo braccio")
    nomi = ["Base","Spalla","Gomito","Polso-V","Polso-R","Pinza"]
    if tel_servo:
        for i,nome in enumerate(nomi):
            v = tel_servo.get(f"s{i}","?")
            bar = "-"*int(v/6) if isinstance(v,int) else ""
            print(f"   CH{i} {nome:<8}: {str(v):>3}  {bar}")
    print("\n-- Rele")
    if tel_rele:
        print(f"   Pompa: {'ON' if tel_rele.get('rele') else 'off'}")

def test_base(client, v=150):
    print("\n[TEST] Motori base")
    mot(client,"velocita",val=v); time.sleep(0.2)
    mot(client,"avanti");  time.sleep(1.5)
    mot(client,"stop");    time.sleep(0.5)
    mot(client,"indietro");time.sleep(1.5)
    mot(client,"stop")

def test_rotazioni(client, v=120):
    print("\n[TEST] Rotazioni")
    mot(client,"velocita",val=v); time.sleep(0.2)
    mot(client,"ruota_dx"); time.sleep(1.0)
    mot(client,"stop");     time.sleep(0.5)
    mot(client,"ruota_sx"); time.sleep(1.0)
    mot(client,"stop")

def test_laterali(client, v=150):
    print("\n[TEST] Laterali")
    mot(client,"velocita",val=v); time.sleep(0.2)
    mot(client,"destra");   time.sleep(1.0)
    mot(client,"stop");     time.sleep(0.5)
    mot(client,"sinistra"); time.sleep(1.0)
    mot(client,"stop")

def test_singoli(client, v=120):
    print("\n[TEST] Motori singoli")
    for m in ["fl","fr","rl","rr"]:
        print(f"  -> {m.upper()}")
        mot(client,m,val=v); time.sleep(0.8)
        mot(client,m,val=0); time.sleep(0.3)

def test_braccio(client):
    print("\n[TEST] Braccio: HOME -> singoli -> RIPOSO")
    sen(client,"home"); time.sleep(1.5)
    for ch in range(6):
        sen(client,"servo",ch=ch,ang=45); time.sleep(0.5)
    sen(client,"home"); time.sleep(1.5)
    sen(client,"riposo")

HELP_MOT = """
=== MODALITA': MOTORI ===
  w/avanti  s/indietro  a/sinistra  d/destra
  q/ruota_sx  e/ruota_dx  x/stop
  diag_avanti_dx  diag_avanti_sx  diag_indietro_dx  diag_indietro_sx
  vel <0-255>
  fl/fr/rl/rr <-255..255>    sx/dx/ant/post/diag1/diag2 <v>
  tutti <v>    set <fl> <fr> <rl> <rr>
  mecanum <vx> <vy> <vr>    reset_enc
  test_base  test_rotazioni  test_laterali  test_singoli
  tel -> telemetria    mode sen -> cambia modalita'"""

HELP_SEN = """
=== MODALITA': SENSORI ===
  SERVO:
    s0..s5 <0-180>          (es: s2 90)
    r0..r5 <delta>          (es: r1 -15)
    set <s0> <s1> <s2> <s3> <s4> <s5>   (usa -1 per invariato)
    home    riposo    get_stato
  RELE':
    rele on / rele off
  TEST:
    test_braccio
  tel -> telemetria    mode mot -> cambia modalita'"""

def main():
    global mode

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="robot_tester_pc")
    client.on_connect    = on_connect
    client.on_disconnect = on_disconnect
    client.on_message    = on_message

    print(f"[MQTT] Connessione a {BROKER_HOST}:{BROKER_PORT}...")
    try:
        client.connect(BROKER_HOST, BROKER_PORT, keepalive=30)
    except Exception as e:
        print(f"[ERRORE] {e}")
        sys.exit(1)

    client.loop_start()
    time.sleep(1.0)
    print(HELP_MOT)
    print("\n>>> Modalita' attiva: MOTORI  (cambia con 'mode sen')")

    vel_corrente = 150

    try:
        while True:
            try:
                raw = input(f"\n[{mode.upper()}]> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not raw:
                continue
            parts = raw.split()
            p0 = parts[0].lower()

            if p0 in ("quit","exit"): break
            if p0 in ("help","h","?"): print(HELP_MOT if mode=="mot" else HELP_SEN); continue
            if p0 == "mode" and len(parts) > 1:
                mode = parts[1].lower()
                print(f">>> Modalita': {'MOTORI' if mode=='mot' else 'SENSORI'}")
                print(HELP_MOT if mode=="mot" else HELP_SEN); continue
            if p0 == "tel":
                print_tel_motori() if mode=="mot" else print_tel_sensori(); continue

            if mode == "mot":
                if p0 in ("w","avanti"):     mot(client,"avanti")
                elif p0 in ("s","indietro"): mot(client,"indietro")
                elif p0 in ("a","sinistra"): mot(client,"sinistra")
                elif p0 in ("d","destra"):   mot(client,"destra")
                elif p0 in ("q","ruota_sx"): mot(client,"ruota_sx")
                elif p0 in ("e","ruota_dx"): mot(client,"ruota_dx")
                elif p0 in ("x","stop"):     mot(client,"stop")
                elif p0 in ("diag_avanti_dx","diag_avanti_sx",
                            "diag_indietro_dx","diag_indietro_sx"): mot(client,p0)
                elif p0 == "vel":
                    if len(parts)<2: print("[ERR] vel <0-255>")
                    else:
                        vel_corrente = max(0,min(255,int(parts[1])))
                        mot(client,"velocita",val=vel_corrente)
                elif p0 in ("fl","fr","rl","rr"):
                    if len(parts)<2: print(f"[ERR] {p0} <v>")
                    else: mot(client,p0,val=max(-255,min(255,int(parts[1]))))
                elif p0 in ("sx","dx","ant","post","diag1","diag2"):
                    if len(parts)<2: print(f"[ERR] {p0} <v>")
                    else: mot(client,p0,val=max(-255,min(255,int(parts[1]))))
                elif p0=="tutti":
                    if len(parts)<2: print("[ERR] tutti <v>")
                    else: mot(client,"tutti",val=max(-255,min(255,int(parts[1]))))
                elif p0=="set":
                    if len(parts)<5: print("[ERR] set <fl> <fr> <rl> <rr>")
                    else:
                        fl,fr,rl,rr=[max(-255,min(255,int(x))) for x in parts[1:5]]
                        mot(client,"set",fl=fl,fr=fr,rl=rl,rr=rr)
                elif p0=="mecanum":
                    if len(parts)<4: print("[ERR] mecanum <vx> <vy> <vr>")
                    else: mot(client,"mecanum",vx=int(parts[1]),vy=int(parts[2]),vr=int(parts[3]))
                elif p0=="reset_enc": mot(client,"reset_enc")
                elif p0=="test_base":      threading.Thread(target=test_base,args=(client,vel_corrente),daemon=True).start()
                elif p0=="test_rotazioni": threading.Thread(target=test_rotazioni,args=(client,vel_corrente),daemon=True).start()
                elif p0=="test_laterali":  threading.Thread(target=test_laterali,args=(client,vel_corrente),daemon=True).start()
                elif p0=="test_singoli":   threading.Thread(target=test_singoli,args=(client,vel_corrente),daemon=True).start()
                else: print(f"[?] '{raw}'  (digita 'help')")

            elif mode == "sen":
                if len(p0)==2 and p0[0]=='s' and '0'<=p0[1]<='5':
                    ch=int(p0[1])
                    if len(parts)<2: print(f"[ERR] {p0} <0-180>")
                    else: sen(client,"servo",ch=ch,ang=max(0,min(180,int(parts[1]))))
                elif len(p0)==2 and p0[0]=='r' and '0'<=p0[1]<='5':
                    ch=int(p0[1])
                    if len(parts)<2: print(f"[ERR] {p0} <delta>")
                    else: sen(client,"servo_rel",ch=ch,delta=int(parts[1]))
                elif p0=="set":
                    if len(parts)<7: print("[ERR] set <s0> <s1> <s2> <s3> <s4> <s5>  (-1=invariato)")
                    else:
                        payload={"cmd":"set"}
                        for i in range(6):
                            v=int(parts[i+1])
                            if v!=-1: payload[f"s{i}"]=max(0,min(180,v))
                        send_sen(client,payload)
                elif p0=="home":      sen(client,"home")
                elif p0=="riposo":    sen(client,"riposo")
                elif p0=="get_stato": sen(client,"get_stato")
                elif p0=="rele":
                    if len(parts)<2: print("[ERR] rele on|off")
                    else: sen(client,"rele",val=1 if parts[1].lower()=="on" else 0)
                elif p0=="test_braccio": threading.Thread(target=test_braccio,args=(client,),daemon=True).start()
                else: print(f"[?] '{raw}'  (digita 'help')")

    finally:
        print("\n[MQTT] Stop motori e disconnessione...")
        mot(client,"stop")
        time.sleep(0.3)
        client.loop_stop()
        client.disconnect()
        print("Ciao!")

if __name__ == "__main__":
    main()