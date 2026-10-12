"""Measure glass-to-glass delay of the tablet second screen.

Shows a 120x120 square in the top-left corner of the chosen monitor that flips black/white every second.
tablet_probe.py on the tablet watches that spot in its framebuffer and sends a UDP note the moment it flips;
this script prints the delay between its own flip and that note (one-way Wi-Fi time, ~2 ms, included).

    python latency_probe.py [--monitor second] [--flips 15]
"""
import argparse, socket, statistics, time, tkinter as tk
import monitors

ap = argparse.ArgumentParser()
ap.add_argument('--monitor', default='second')
ap.add_argument('--flips', type=int, default=15)
ap.add_argument('--port', type=int, default=5610)
a = ap.parse_args()
monitors.dpi_aware()
dev, x, y, w, h = monitors.pick(a.monitor)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); sock.bind(('0.0.0.0', a.port)); sock.setblocking(False)
root = tk.Tk(); root.overrideredirect(True); root.attributes('-topmost', True)
root.geometry('120x120+%d+%d' % (x, y))
box = tk.Frame(root, width=120, height=120, bg='black'); box.pack()
state = {'white': False, 'n': 0, 't': 0.0}; results = []


def flip():
    state['white'] = not state['white']
    box.configure(bg='white' if state['white'] else 'black'); root.update_idletasks()
    state['t'] = time.perf_counter(); state['n'] += 1
    if state['n'] <= a.flips:
        root.after(1000, flip)
    else:
        root.after(1500, finish)


def poll():
    try:
        while True:
            data, _ = sock.recvfrom(64)
            if state['t']:
                ms = (time.perf_counter() - state['t']) * 1000
                if ms < 900:
                    results.append(ms); print('flip %2d seen on tablet after %4.0f ms' % (state['n'], ms), flush=True)
    except BlockingIOError:
        pass
    root.after(2, poll)


def finish():
    if results:
        print('median %.0f ms   best %.0f ms   worst %.0f ms   (%d/%d flips seen)' %
              (statistics.median(results), min(results), max(results), len(results), a.flips))
    else:
        print('no flips seen - is tablet_probe.py running and PC mode on?')
    root.destroy()


root.after(1500, flip); root.after(2, poll); root.mainloop()
