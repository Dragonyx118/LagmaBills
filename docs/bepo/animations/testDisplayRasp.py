import spidev
import RPi.GPIO as GPIO
import time
import struct
from PIL import Image

# Pin
DC_PIN  = 24
RST_PIN = 25

GPIO.setmode(GPIO.BCM)
GPIO.setup(DC_PIN, GPIO.OUT)
GPIO.setup(RST_PIN, GPIO.OUT)

spi = spidev.SpiDev()
spi.open(0, 1)  # CE1 = GPIO7
spi.max_speed_hz = 32000000
spi.mode = 0

def send_command(cmd):
    GPIO.output(DC_PIN, 0)
    spi.writebytes([cmd])

def send_data(data):
    GPIO.output(DC_PIN, 1)
    spi.writebytes2(data)

def reset():
    GPIO.output(RST_PIN, 1)
    time.sleep(0.1)
    GPIO.output(RST_PIN, 0)
    time.sleep(0.1)
    GPIO.output(RST_PIN, 1)
    time.sleep(0.1)

def init_display():
    reset()

    send_command(0x01)  # Software reset
    time.sleep(0.12)

    send_command(0x11)  # Sleep out
    time.sleep(0.12)

    # ST7796S init
    send_command(0xF0)
    send_data([0xC3])
    send_command(0xF0)
    send_data([0x96])

    send_command(0x36)  # Memory access control
    send_data([0x48])   # landscape 480x320

    send_command(0x3A)  # Pixel format
    send_data([0x55])   # 16 bit RGB565

    send_command(0xB4)  # Display inversion
    send_data([0x01])

    send_command(0xB7)  # Entry mode
    send_data([0xC6])

    send_command(0xE8)
    send_data([0x40, 0x8A, 0x00, 0x00, 0x29, 0x19, 0xA5, 0x33])

    send_command(0xC1)
    send_data([0x06])
    send_command(0xC2)
    send_data([0xA7])
    send_command(0xC5)
    send_data([0x18])

    send_command(0xE0)  # Gamma positivo
    send_data([0xF0,0x09,0x0B,0x06,0x04,0x15,0x2F,0x54,0x42,0x3C,0x17,0x14,0x18,0x1B])
    send_command(0xE1)  # Gamma negativo
    send_data([0xF0,0x09,0x0B,0x06,0x04,0x03,0x2D,0x43,0x42,0x3B,0x16,0x14,0x17,0x1B])

    send_command(0xF0)
    send_data([0x3C])
    send_command(0xF0)
    send_data([0x69])

    send_command(0x29)  # Display on
    time.sleep(0.05)

def set_window(x, y, w, h):
    send_command(0x2A)
    send_data([(x>>8)&0xFF, x&0xFF, ((x+w-1)>>8)&0xFF, (x+w-1)&0xFF])
    send_command(0x2B)
    send_data([(y>>8)&0xFF, y&0xFF, ((y+h-1)>>8)&0xFF, (y+h-1)&0xFF])
    send_command(0x2C)

def image_to_rgb565(path):
    img = Image.open(path).convert('RGB')
    img = img.resize((480, 320), Image.LANCZOS)
    data = bytearray()
    for r, g, b in img.getdata():
        rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        data += struct.pack('>H', rgb565)
    return bytes(data)

def show_image(path):
    print(f"Caricamento {path}...")
    data = image_to_rgb565(path)
    set_window(0, 0, 480, 320)
    GPIO.output(DC_PIN, 1)
    # Manda in chunk da 4096 byte
    chunk = 4096
    for i in range(0, len(data), chunk):
        spi.writebytes2(data[i:i+chunk])
    print("Fatto!")

# Main
init_display()
show_image("immagine.jpg")  # metti qui il nome del tuo file

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    GPIO.cleanup()