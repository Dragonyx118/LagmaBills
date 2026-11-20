import socket
import time

# Configurazione drone
DRONE_IP = '192.168.43.42'  # sostituisci con l'IP del tuo drone
DRONE_PORT = 2390
LOCAL_PORT = 2399

# Creo socket UDP
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('', LOCAL_PORT))
sock.settimeout(0.5)  # timeout per la ricezione

def leggi_batteria():
    """
    Invia pacchetto CRTP al drone e stampa i byte ricevuti.
    Serve per mappare quale byte è la batteria.
    """
    # Pacchetto di richiesta (header CRTP 0x20)
    pkt = b'\x20\x00\x00'
    sock.sendto(pkt, (DRONE_IP, DRONE_PORT))

    try:
        data, _ = sock.recvfrom(1024)
        print("Risposta dal drone:", data)

        # Se ci sono almeno 2 byte, prova a leggere come tensione mV
        if len(data) >= 2:
            voltage = data[0] + (data[1] << 8)
            print(f"Tensione stimata (mV): {voltage}")
        else:
            print("Pacchetto troppo corto per stimare batteria")

    except socket.timeout:
        print("Nessuna risposta dal drone")

if __name__ == "__main__":
    print("Inizio test batteria… Ctrl+C per uscire")
    try:
        while True:
            leggi_batteria()
            time.sleep(1)  # leggi ogni secondo
    except KeyboardInterrupt:
        print("Chiusura script")
        sock.close()
