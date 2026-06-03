import smbus2
import time

ESP32_ADDR = 0x08
bus = smbus2.SMBus(1)  # I2C bus 1 del Raspberry

# Posizioni servo [0..5], valori 0-180
# Modifica questi valori dalla tua app
servo_positions = [90, 150, 35, 140, 85, 80]

def send_positions(positions):
    """Invia le 6 posizioni all'ESP32"""
    data = [int(p) for p in positions]
    try:
        bus.write_i2c_block_data(ESP32_ADDR, 0, data)
        print(f"Inviato: {data}")
    except Exception as e:
        print(f"Errore I2C: {e}")

def read_positions():
    """Legge le posizioni attuali dall'ESP32"""
    try:
        data = bus.read_i2c_block_data(ESP32_ADDR, 0, 6)
        return data
    except Exception as e:
        print(f"Errore lettura: {e}")
        return None

# Esempio: la tua app modifica servo_positions e poi chiama send_positions
# Puoi esporre queste funzioni via socket, HTTP, MQTT, ecc.

if __name__ == "__main__":
    # Test: muovi il servo 0 da 90 a 45 gradi
    servo_positions[0] = 45
    send_positions(servo_positions)
    time.sleep(2)
    
    # Leggi posizioni attuali
    current = read_positions()
    print(f"Posizioni attuali: {current}")