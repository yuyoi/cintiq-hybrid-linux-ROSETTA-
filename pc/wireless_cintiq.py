"""Wireless Cintiq, PC side: starts the pen injector and streams your screen to the tablet. Ctrl+C stops both.

    python wireless_cintiq.py --tablet-ip 192.168.1.220 [--res 1280x720] [--fps 30] [--bind <this PC's LAN ip>]
    python wireless_cintiq.py --client android [--monitor second]     (Rosetta Screen app, hardware decoding)

On the tablet, tap PC on the taskbar (or press the Back button) to see this PC and draw on it with the pen.
Needs: Windows 10+, Python 3, ffmpeg (winget install Gyan.FFmpeg). The first run triggers a Windows Firewall
prompt for Python: allow it on PRIVATE networks only.
"""
import argparse, ctypes, hashlib, hmac, os, queue, shutil, socket, struct, subprocess, sys, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))


def find_ffmpeg():
    p = shutil.which('ffmpeg')
    if p:
        return p
    base = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WinGet', 'Packages')
    for root, _, files in os.walk(base):
        if 'ffmpeg.exe' in files:
            return os.path.join(root, 'ffmpeg.exe')
    sys.exit('ffmpeg not found. Install it with:  winget install Gyan.FFmpeg')


def dda_output(ff, w, h):
    """ddagrab output index (GPU capture) whose picture is w x h, or None. Output 0 is normally the primary."""
    import re
    for idx in range(1, 6):
        r = subprocess.run([ff, '-hide_banner', '-init_hw_device', 'd3d11va', '-filter_complex',
                            'ddagrab=output_idx=%d:framerate=5' % idx, '-frames:v', '1', '-f', 'null', '-'],
                           capture_output=True, text=True, timeout=20)
        m = re.search(r'Video: .*?d3d11.*?, (\d+)x(\d+)', r.stderr)
        if m and (int(m.group(1)), int(m.group(2))) == (w, h):
            return idx
    return None


class AndroidSender:
    """Feeds the Rosetta Screen app: whole H.264 frames, cut at access-unit delimiters, AES-256-CTR encrypted and sent
    as numbered fragments ("W" packets).

    The app finds us through its signed "H" hello packets (port + 1) - broadcast at home, or to the home address when
    away. Video goes back out of the same socket to exactly where the hello came from, which is the path the tablet's
    router has just opened, so it also works from another network (with UDP port + 0 and + 1 forwarded at home)."""
    MTU = 1400

    def __init__(self, bind, hello_port, video_port, secret, target=None):
        self.video_port, self.secret = video_port, secret
        self.target = (target, video_port) if target else None
        import aesctr
        self.aes = aesctr.AESCTR(hashlib.sha256(secret + b'|video').digest())
        self.session = os.urandom(6)                                   # new keystream space every run
        self.hello = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.hello.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 << 20)
        if hasattr(socket, 'SIO_UDP_CONNRESET'):                     # Windows: a vanished app port must not kill recvfrom
            self.hello.ioctl(socket.SIO_UDP_CONNRESET, False)
        self.hello.bind(('0.0.0.0', hello_port))                      # all interfaces: the app's hellos are broadcasts
        self.seq = 0
        self.frame_id = 0
        threading.Thread(target=self._hellos, daemon=True).start()

    def _hellos(self):
        while True:
            try:
                data, addr = self.hello.recvfrom(256)
            except OSError:
                continue
            if len(data) < 13 or data[:1] != b'H':
                continue
            if not hmac.compare_digest(hmac.new(self.secret, data[:-8], hashlib.sha256).digest()[:8], data[-8:]):
                continue
            self.seq = max(self.seq + 1, int(time.time() * 1000) & 0xFFFFFFFF)
            reply = b'A' + struct.pack('<I', self.seq)
            self.hello.sendto(reply + hmac.new(self.secret, reply, hashlib.sha256).digest()[:8], addr)   # "here I am"
            if addr != self.target:
                print('Rosetta Screen app at %s:%d' % addr, flush=True)
                self.target = addr

    def send_frame(self, frame):
        if not self.target:
            return
        self.frame_id = (self.frame_id + 1) & 0xFFFFFFFF
        n = (len(frame) + self.MTU - 1) // self.MTU
        for i in range(n):
            iv = self.session + struct.pack('<IH', self.frame_id, i)
            body = self.aes.crypt(iv, frame[i * self.MTU:(i + 1) * self.MTU])
            try:
                self.hello.sendto(b'W' + self.session + struct.pack('<IHH', self.frame_id, i, n) + body, self.target)
            except OSError:
                return

    def pump(self, pipe):
        """Read ffmpeg's raw H.264 and send each access unit the moment it is complete (next delimiter, or a 3 ms gap)."""
        AUD = b'\x00\x00\x00\x01\x09'
        chunks = queue.Queue()

        def reader():
            while True:
                b = pipe.read1(1 << 20) if hasattr(pipe, 'read1') else pipe.read(65536)
                chunks.put(b)
                if not b:
                    return
        threading.Thread(target=reader, daemon=True).start()
        buf = b''
        while True:
            try:
                b = chunks.get(timeout=0.003)
            except queue.Empty:
                if buf.startswith(AUD):
                    self.send_frame(buf); buf = b''
                continue
            if not b:
                return
            buf += b
            while True:                                            # every complete unit up to the last delimiter
                j = buf.find(AUD, 1)
                if j < 0:
                    break
                if buf.startswith(AUD):
                    self.send_frame(buf[:j])
                buf = buf[j:]


def lan_ip(tablet_ip):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((tablet_ip, 9))
        return s.getsockname()[0]
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tablet-ip', default=None, help='Linux mode: the tablet address; Android app: optional (it says hello)')
    ap.add_argument('--client', choices=['linux', 'android'], default='linux',
                    help='linux = the tablet Linux player; android = the Rosetta Screen app (hardware decoder, lower delay)')
    ap.add_argument('--res', default='1920x1080')
    ap.add_argument('--fps', type=int, default=None, help='default 24 for Linux (CPU decoding), 60 for the Android app')
    ap.add_argument('--bitrate', default=None, help='default 7M for Linux, 12M for the Android app')
    ap.add_argument('--bind', default=None)
    ap.add_argument('--monitor', default='primary', help='primary, second or a monitor number (tablet as an extended screen)')
    ap.add_argument('--list-monitors', action='store_true')
    ap.add_argument('--no-mouse-priority', action='store_true')
    ap.add_argument('--port', type=int, default=5600)
    ap.add_argument('--video-port', type=int, default=5700)
    a = ap.parse_args()

    import monitors
    monitors.dpi_aware()
    if a.list_monitors:
        for m in monitors.monitors():
            print('%d  %s  %dx%d at %d,%d%s' % (m[0], m[1], m[4], m[5], m[2], m[3], '  (primary)' if m[6] else ''))
        return
    dev, mx, my, w, h = monitors.pick(a.monitor)
    android = a.client == 'android'
    if not android and not a.tablet_ip:
        sys.exit('--tablet-ip is needed for the Linux player')
    a.fps = a.fps or (60 if android else 24)
    a.bitrate = a.bitrate or ('12M' if android else '7M')
    bind = a.bind or lan_ip(a.tablet_ip or '8.8.8.8')       # the interface that routes outwards = our LAN address
    ff = find_ffmpeg()
    print('PC %s | monitor %s %s %dx%d at %d,%d | tablet %s' % (bind, a.monitor, dev, w, h, mx, my, a.tablet_ip), flush=True)

    inj = subprocess.Popen([sys.executable, '-u', os.path.join(HERE, 'pen_injector.py'),
                            '--bind', bind, '--port', str(a.port), '--allow', 'any' if android else a.tablet_ip, '--monitor', a.monitor] + (['--no-mouse-priority'] if a.no_mouse_priority else []))
    gop = str(a.fps)
    # ddagrab = GPU desktop duplication: gdigrab tops out near 16 fps on a 4K screen, which is what made it lag
    vf = 'ddagrab=0:framerate=%d:draw_mouse=1,hwdownload,format=bgra,scale=%s:flags=bicubic,format=yuv420p' % (a.fps, a.res.replace('x', ':'))
    out_idx = None if a.monitor in ('primary', '1') else dda_output(ff, w, h)
    if a.monitor in ('primary', '1'):
        src = ['-init_hw_device', 'd3d11va', '-filter_complex', vf]
    elif out_idx is not None:                       # GPU capture of the extended screen: fastest, lowest latency
        sc = '' if (w, h) == tuple(int(v) for v in a.res.split('x')) else 'scale=%s:flags=bicubic,' % a.res.replace('x', ':')
        src = ['-init_hw_device', 'd3d11va', '-filter_complex',
               'ddagrab=output_idx=%d:framerate=%d:draw_mouse=1,hwdownload,format=bgra,%sformat=yuv420p' % (out_idx, a.fps, sc)]
    else:
        # extended screen: grab exactly that monitor's area; a 1920x1080 monitor goes over 1:1 with no scaling
        sc = '' if (w, h) == tuple(int(v) for v in a.res.split('x')) else 'scale=%s:flags=bicubic,' % a.res.replace('x', ':')
        src = ['-f', 'gdigrab', '-framerate', str(a.fps), '-draw_mouse', '1', '-offset_x', str(mx), '-offset_y', str(my),
               '-video_size', '%dx%d' % (w, h), '-i', 'desktop', '-vf', sc + 'format=yuv420p']
    enc = ['-c:v', 'libx264', '-threads', '4', '-preset', 'veryfast', '-tune', 'zerolatency', '-profile:v', 'baseline', '-bf', '0', '-g', gop,
           # Linux player: intra-refresh (no keyframe bursts). Android app: the Tegra hardware decoder needs real IDR keyframes
           '-x264-params', ('repeat-headers=1:scenecut=0:sliced-threads=1:aud=1:keyint=%d' % a.fps) if android else
                           'repeat-headers=1:scenecut=0:intra-refresh=1:keyint=15:sliced-threads=1',
           '-b:v', a.bitrate, '-maxrate', a.bitrate, '-bufsize', '1M']
    if android:
        secret = open(os.path.join(HERE, 'secret.txt'), 'rb').read().strip()
        sender = AndroidSender(bind, a.port + 1, a.video_port, secret, a.tablet_ip)
        vid = subprocess.Popen([ff, '-hide_banner', '-loglevel', 'warning'] + src + enc + ['-flush_packets', '1', '-f', 'h264', '-'],
                               stdout=subprocess.PIPE, bufsize=0)
        threading.Thread(target=sender.pump, args=(vid.stdout,), daemon=True).start()
        print('streaming %s @%d fps for the Rosetta Screen app (waiting for its hello on %s:%d)  |  pen injector on %s:%d' %
              (a.res, a.fps, bind, a.port + 1, bind, a.port), flush=True)
    else:
        vid = subprocess.Popen([ff, '-hide_banner', '-loglevel', 'warning'] + src + enc + [
            '-flush_packets', '1', '-muxdelay', '0', '-muxpreload', '0', '-f', 'mpegts', 'udp://%s:%d?pkt_size=1316' % (a.tablet_ip, a.video_port)])
        print('streaming %s @%d fps to udp://%s:%d  |  pen injector listening on %s:%d' %
              (a.res, a.fps, a.tablet_ip, a.video_port, bind, a.port), flush=True)
    print('Press Ctrl+C to stop.', flush=True)
    try:
        while inj.poll() is None and vid.poll() is None:
            time.sleep(1)
        print('a component exited (injector=%s, stream=%s)' % (inj.poll(), vid.poll()))
    except KeyboardInterrupt:
        pass
    finally:
        for p in (inj, vid):
            if p.poll() is None:
                p.terminate()
        print('stopped.')


if __name__ == '__main__':
    main()


