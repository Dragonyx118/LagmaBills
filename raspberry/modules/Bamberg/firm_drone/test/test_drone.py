import socket, struct, time

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind('', 2399)
def invia(roll, pitch, yaw, thrust):
    header = (0x03 << 4) | 0
    data = struct.pack('<fffH',roll,-pitch,yaw,thrust)
    pkt = bytes([header])
    cksum = sum(b & 0xff for b in pkt) & 0xff
    sock.sendto(pkt+bytes([cksum]),('192.168.43.42',2390))
print("Invio...:D")

for i in range(50):
    invia(0.0, 0.0, 0.0, 40000)
    time.sleep(0.02)
invia(0.0, 0.0, 0.0, 0)
sock.close()
print("Fine :)")