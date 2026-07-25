from PIL import Image

input_path = "v.gif"
output_path = "v_small.gif"

# Dimensione massima consigliata per ESP32
MAX_W = 160
MAX_H = 120

img = Image.open(input_path)
frames = []
durations = []

try:
    while True:
        frame = img.copy().convert("RGB")
        frame.thumbnail((MAX_W, MAX_H), Image.LANCZOS)
        frames.append(frame)
        durations.append(img.info.get("duration", 100))
        img.seek(img.tell() + 1)
except EOFError:
    pass

frames[0].save(
    output_path,
    save_all=True,
    append_images=frames[1:],
    loop=0,
    duration=durations,
    optimize=False
)

print(f"Salvato {output_path} con {len(frames)} frame")