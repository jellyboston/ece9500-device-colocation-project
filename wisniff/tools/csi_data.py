import sys, re, time, threading, collections
import numpy as np
import serial
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

BAUD, WIN = 921600, 300
ports = sys.argv[1:]
if not ports:
    sys.exit("usage: python tools/csi_viewer.py COM5 [COM6]")

bufs = {p: collections.deque(maxlen=WIN) for p in ports}
stop = threading.Event()

def reader(port):
    ser = serial.Serial(port, BAUD, timeout=1)
    name = re.sub(r"\W", "_", port)
    with open(f"csi_{name}_{int(time.time())}.csv", "w") as log:
        while not stop.is_set():
            line = ser.readline().decode(errors="ignore").strip()
            if line.startswith("#"):
                print(port, line)
            elif line.startswith("CSI,"):
                log.write(line + "\n")
                try:
                    bufs[port].append(np.array(line.split(",")[6:], dtype=float))
                except ValueError:
                    pass

for p in ports:
    threading.Thread(target=reader, args=(p,), daemon=True).start()

fig, axes = plt.subplots(len(ports), 1, figsize=(10, 3.5 * len(ports)), squeeze=False)
images = []
for ax, p in zip(axes[:, 0], ports):
    im = ax.imshow(np.zeros((64, 10)), aspect="auto", origin="lower", vmin=0, vmax=60)
    ax.set_title(p); ax.set_xlabel("frame"); ax.set_ylabel("subcarrier")
    images.append(im)

def update(_):
    for im, p in zip(images, ports):
        rows = list(bufs[p])
        if not rows:
            continue
        rows = [r for r in rows if len(r) == len(rows[-1])]   # one frame type only
        im.set_data(np.array(rows).T)
        im.set_extent((0, len(rows), 0, len(rows[-1])))
    return images

ani = FuncAnimation(fig, update, interval=200, cache_frame_data=False)
plt.tight_layout(); plt.show()
stop.set()
