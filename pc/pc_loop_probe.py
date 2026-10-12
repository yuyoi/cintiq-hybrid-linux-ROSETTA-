"""Delay of the PC half only: same capture + encode as wireless_cintiq.py, decoded again on this PC over loopback.

Flips a square on the chosen monitor and times when the decoded loopback video shows it.
    python pc_loop_probe.py [--monitor second] [--fps 24] [--extra "-x264-params ..."]
"""
import argparse, shlex, statistics, subprocess, threading, time, tkinter as tk
import monitors, wireless_cintiq as wc

ap = argparse.ArgumentParser()
ap.add_argument('--monitor', default='second'); ap.add_argument('--fps', type=int, default=24)
ap.add_argument('--flips', type=int, default=10); ap.add_argument('--extra', default='')
a = ap.parse_args()
monitors.dpi_aware()
dev, x, y, w, h = monitors.pick(a.monitor)
ff = wc.find_ffmpeg()
idx = wc.dda_output(ff, w, h)
src = ['-init_hw_device', 'd3d11va', '-filter_complex',
       'ddagrab=output_idx=%d:framerate=%d:draw_mouse=1,hwdownload,format=bgra,format=yuv420p' % (idx, a.fps)]
enc = [ff, '-hide_banner', '-loglevel', 'error'] + src + [
    '-c:v', 'libx264', '-threads', '4', '-preset', 'veryfast', '-tune', 'zerolatency', '-profile:v', 'baseline', '-bf', '0',
    '-g', str(a.fps), '-x264-params', 'repeat-headers=1:scenecut=0:intra-refresh=1:keyint=15:sliced-threads=1',
    '-b:v', '7M', '-maxrate', '7M', '-bufsize', '1M'] + shlex.split(a.extra) + [
    '-flush_packets', '1', '-muxdelay', '0', '-muxpreload', '0', '-f', 'mpegts', 'udp://127.0.0.1:5800?pkt_size=1316']
dec = [ff, '-hide_banner', '-loglevel', 'error', '-threads', '1', '-fflags', 'nobuffer', '-flags', 'low_delay', '-probesize', '64k',
       '-analyzeduration', '0', '-i', 'udp://127.0.0.1:5800?fifo_size=20000&overrun_nonfatal=1',
       '-vf', 'crop=8:8:56:56,format=gray', '-fps_mode', 'passthrough', '-f', 'rawvideo', 'pipe:1']
pd = subprocess.Popen(dec, stdout=subprocess.PIPE)
time.sleep(0.5)
pe = subprocess.Popen(enc)
root = tk.Tk(); root.overrideredirect(True); root.attributes('-topmost', True)
root.geometry('120x120+%d+%d' % (x, y))
box = tk.Frame(root, width=120, height=120, bg='black'); box.pack()
st = {'white': False, 't': 0.0, 'n': 0}; res = []


def reader():
    last = None
    while True:
        b = pd.stdout.read(64)
        if len(b) < 64: return
        lum = sum(b) / 64 > 128
        if last is not None and lum != last and st['t']:
            ms = (time.perf_counter() - st['t']) * 1000
            if ms < 900: res.append(ms); print('loopback saw flip after %4.0f ms' % ms, flush=True)
        last = lum


threading.Thread(target=reader, daemon=True).start()


def flip():
    st['white'] = not st['white']; box.configure(bg='white' if st['white'] else 'black'); root.update_idletasks()
    st['t'] = time.perf_counter(); st['n'] += 1
    root.after(1000 if st['n'] < a.flips + 3 else 1500, flip if st['n'] < a.flips + 3 else done)


def done():
    r = res[2:] or res
    print('PC-only median %.0f ms  best %.0f  worst %.0f  (%d flips)' % (statistics.median(r), min(r), max(r), len(r)) if r else 'nothing seen')
    pe.terminate(); pd.terminate(); root.destroy()


root.after(2500, flip); root.mainloop()
