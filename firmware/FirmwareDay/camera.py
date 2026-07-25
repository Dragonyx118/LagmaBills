#!/usr/bin/env python3
# stream_camera.py - Stream MJPEG leggero via HTTP con Flask
import subprocess
import threading
from flask import Flask, Response

app = Flask(__name__)

frame_condition = threading.Condition()
current_frame = b''

def capture_frames():
    global current_frame
    cmd = [
        'rpicam-vid', '-t', '0', '--codec', 'mjpeg',
        '--width', '640', '--height', '480',
        '--framerate', '18',
        '--quality', '50',
        '-o', '-', '--nopreview'
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=16384)
    buf = b''
    while True:
        chunk = proc.stdout.read(16384)
        if not chunk:
            break
        buf += chunk
        while True:
            start = buf.find(b'\xff\xd8')
            if start == -1:
                break
            end = buf.find(b'\xff\xd9', start)
            if end == -1:
                break
            frame = buf[start:end+2]
            with frame_condition:
                current_frame = frame
                frame_condition.notify_all()
            buf = buf[end+2:]

def generate():
    while True:
        with frame_condition:
            frame_condition.wait()
            frame = current_frame
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/stream')
def stream():
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return '<html><body><img src="/stream" style="width:100%"></body></html>'

if __name__ == '__main__':
    t = threading.Thread(target=capture_frames, daemon=True)
    t.start()
    print("[*] Stream leggero su http://LagmaBills.local:8080")
    app.run(host='0.0.0.0', port=8080, threaded=True)