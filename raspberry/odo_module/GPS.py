# Installa le librerie necessarie
#pip install pyserial pynmea2

# Controlla su quale porta è connesso il GPS
#ls /dev/tty*
# Di solito è /dev/ttyAMA0 o /dev/ttyUSB0
#sudo raspi-config
# → Interface Options → Serial Port
# → "login shell over serial" = NO
# → "serial port hardware" = YES
#NEO-6M          Raspberry Pi
#──────          ────────────
#VCC      →      Pin 1  (3.3V)
#GND      →      Pin 6  (GND)
#TX       →      Pin 8 d
#RX       →      Pin 10 

import serial
import pynmea2
import csv
import time
from datetime import datetime

PORTA   = "/dev/ttyS0"
BAUD    = 9600
CSV_OUT = "tracciato_gps.csv"

def salva_posizione(writer, lat, lon, alt, velocita, satelliti, timestamp):
    writer.writerow({
        'timestamp' : timestamp,
        'latitudine': round(lat, 6),
        'longitudine': round(lon, 6),
        'altitudine': alt,
        'velocita_nodi': velocita,
        'satelliti': satelliti
    })

def main():
    campi = ['timestamp', 'latitudine', 'longitudine', 'altitudine', 'velocita_nodi', 'satelliti']

    with open(CSV_OUT, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=campi)
        writer.writeheader()

        ultima_gga = {}  # buffer per incrociare RMC e GGA

        try:
            ser = serial.Serial(PORTA, BAUD, timeout=1)
            print(f"GPS connesso. Logging su '{CSV_OUT}'...\n")

            while True:
                linea = ser.readline().decode('ascii', errors='replace').strip()
                if not linea.startswith('$'):
                    continue

                try:
                    msg = pynmea2.parse(linea)

                    if isinstance(msg, pynmea2.GGA) and msg.gps_qual > 0:
                        ultima_gga = {
                            'lat': msg.latitude,
                            'lon': msg.longitude,
                            'alt': msg.altitude,
                            'sat': msg.num_sats
                        }

                    elif isinstance(msg, pynmea2.RMC) and msg.status == 'A' and ultima_gga:
                        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        salva_posizione(
                            writer,
                            ultima_gga['lat'],
                            ultima_gga['lon'],
                            ultima_gga['alt'],
                            msg.spd_over_grnd,
                            ultima_gga['sat'],
                            now
                        )
                        csvfile.flush()  # scrivi subito su disco

                        print(f"{now} | Lat: {ultima_gga['lat']:.6f} | Lon: {ultima_gga['lon']:.6f} | "
                              f"Alt: {ultima_gga['alt']}m | Vel: {msg.spd_over_grnd:.1f} kn | "
                              f"Sat: {ultima_gga['sat']}")

                except pynmea2.ParseError:
                    pass

        except KeyboardInterrupt:
            print(f"\nLogging terminato. Dati salvati in '{CSV_OUT}'")
            ser.close()

if __name__ == "__main__":
    main()