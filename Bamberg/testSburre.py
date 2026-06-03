import socket
import struct
import time
import subprocess

DRONE_IP   = '192.168.43.42'
DRONE_PORT = 2390
LOCAL_PORT = 2399

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', LOCAL_PORT))

def ping_ip(ip):
    """Ping ICMP normale - funziona come dal terminale."""
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '1', ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception:
        return False

def invia_comando_reale():
    """
    Invia un comando thrust=0 reale.
    Stesso pacchetto del controller, quello che funziona.
    """
    header = (0x03 << 4) | 0
    data = struct.pack('<fffH', 0.0, 0.0, 0.0, 0)
    pkt = bytes([header]) + data
    cksum = sum(pkt) & 0xff
    sock.sendto(pkt + bytes([cksum]), (DRONE_IP, DRONE_PORT))

def ascolta_telemetria(secondi=4):
    """
    Dopo aver inviato un comando reale, il drone
    inizia a mandare pacchetti di telemetria.
    Li raccogliamo e analizziamo.
    """
    sock.settimeout(0.3)
    pacchetti_per_porta = {}
    fine = time.time() + secondi

    while time.time() < fine:
        # Continua a mandare comandi per mantenere la sessione attiva
        invia_comando_reale()
        try:
            data, _ = sock.recvfrom(1024)
            if len(data) >= 1:
                header = data[0]
                port   = (header >> 4) & 0x0F
                if port not in pacchetti_per_porta:
                    pacchetti_per_porta[port] = data
        except socket.timeout:
            pass

    return pacchetti_per_porta

# Mappa porte CRTP -> sensori/funzioni
PORTE_CRTP = {
    0:  "Commander (comandi volo)",
    2:  "Parameters",
    5:  "Log / Telemetria",
    6:  "Localization",
    8:  "Platform",
    15: "Link Control",
}

# Sensori deducibili dai log ricevuti
SENSORI_DA_PORT = {
    5: "IMU / MPU6050 (sempre presente se vola)",
}

def controlla_hardware():
    print("\n" + "="*55)
    print("   CONTROLLO HARDWARE ESP-DRONE")
    print("="*55)
    print(f"Drone IP: {DRONE_IP}:{DRONE_PORT}\n")

    # Step 1: ping ICMP
    print("Step 1 - Ping IP...")
    if ping_ip(DRONE_IP):
        print(f"  ✓ {DRONE_IP} raggiungibile via ping\n")
    else:
        print(f"  ✗ {DRONE_IP} NON raggiungibile")
        print("  → Controlla che il Raspberry sia connesso")
        print("    al Wi-Fi del drone (ESP-DRONE_XXXX, pass: 12345678)")
        sock.close()
        return

    # Step 2: invio comando reale e ascolto telemetria
    print("Step 2 - Invio comandi e ascolto telemetria (4 sec)...")
    pacchetti = ascolta_telemetria(secondi=4)

    if not pacchetti:
        print("  ✗ Nessun pacchetto ricevuto dal drone")
        print("  → Il drone è raggiungibile via ping ma non")
        print("    sta mandando telemetria CRTP.")
        print("  → Prova ad avviare prima l'APP ESP-Drone")
        print("    per inizializzare la sessione, poi rilancia.")
    else:
        print(f"  ✓ Ricevuti pacchetti su {len(pacchetti)} porte CRTP diverse\n")
        print("  Porte attive rilevate:")
        for port, data in sorted(pacchetti.items()):
            nome = PORTE_CRTP.get(port, f"Porta sconosciuta {port}")
            print(f"    Porta {port:2d} → {nome}")
            print(f"             Dati raw: {data.hex()}")

    # Step 3: riepilogo sensori e modalità
    print("\n" + "="*55)
    print("   SENSORI E MODALITA' DISPONIBILI")
    print("="*55)

    ha_imu   = any(p in pacchetti for p in [5, 0])
    ha_baro  = False  # non deducibile senza sessione CRTP completa
    ha_flow  = False  # stesso motivo
    ha_tof   = False  # stesso motivo

    # Se riceviamo qualcosa il drone vola -> MPU6050 presente
    if ha_imu or pacchetti:
        print("\n  MPU6050  (IMU base)          : ✓ PRESENTE (drone risponde)")
        print("  MS5611   (barometro)         : ? non verificabile via UDP semplice")
        print("  PMW3901  (ottico flow)       : ? non verificabile via UDP semplice")
        print("  VL53L1X  (TOF laser)         : ? non verificabile via UDP semplice")
        print("  HMC5883  (bussola)           : ? non verificabile via UDP semplice")
    else:
        print("\n  Nessun sensore verificabile (drone non risponde)")

    print("\n  Modalità di volo:")
    print("  Stabilize         : ✓ sempre disponibile se il drone vola")
    print("  Height-Hold       : dipende da MS5611 - verifica con cfclient")
    print("  Position-Hold     : dipende da MS5611+PMW3901+VL53L1X - verifica con cfclient")

    print("\n" + "="*55)
    print("  Per verifica definitiva dei sensori:")
    print("  1. Installa cfclient sul PC")
    print("  2. Connettiti al drone")
    print("  3. Vai su Log Blocks -> vedrai tutti i sensori attivi")
    print("="*55 + "\n")

    sock.close()

if __name__ == "__main__":
    controlla_hardware()