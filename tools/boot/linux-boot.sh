#!/sbin/busybox sh
# Linux boot mode (runs inside the SOS ramdisk). Display = native Xorg on fb0 (fbpush), or Xvfb mirrored into fb0 as fallback.
B=/sbin/busybox
umask 022
LOG=/tmp/lb.log
exec >$LOG 2>&1
set -x
$B --install -s /sbin
export PATH=/sbin:$PATH
MISC=/dev/block/platform/sdhci-tegra.3/by-name/MSC
UDA=/dev/block/platform/sdhci-tegra.3/by-name/UDA
R=/data/local/alpine

# 1. clear the bootloader recovery command so the NEXT boot is Android
$B dd if=/dev/zero of=$MISC bs=2048 count=1

# 2. USB gadget -> adb
G=/sys/class/android_usb/android0
echo 0 > $G/enable
echo @VID@ > $G/idVendor
echo @PID@ > $G/idProduct
echo adb > $G/functions
echo Wacom > $G/iManufacturer
echo LinuxMode > $G/iProduct
echo 1 > $G/enable
/sbin/adbd &

# 3. data partition
$B mkdir -p /data
$B mount -t ext4 -o rw,noatime $UDA /data
$B mkdir -p /data/local
$B cp $LOG /data/local/linux-boot.log 2>/dev/null

# (watchdog is its own init service: /sbin/wdog.sh)
[ -e $R/bin/busybox ] || { echo "no alpine rootfs"; $B cp $LOG /data/local/linux-boot.log; $B sync; exit 1; }

# 4. chroot mounts
$B mount -o bind /dev $R/dev
$B mount -t devpts devpts $R/dev/pts
$B mount -t proc proc $R/proc
$B mount -t sysfs sysfs $R/sys
$B mount -t tmpfs tmpfs $R/tmp
echo "nameserver 8.8.8.8" > $R/etc/resolv.conf
rm -f $R/root/pcmode            # stale PC-mode flag from older builds would disable touch

# 4b. speed: run the CPUs flat out (Krita is software-rendered); harmless if a knob is missing
for c in /sys/devices/system/cpu/cpu[0-9]*; do echo 1 > $c/online 2>/dev/null; echo performance > $c/cpufreq/scaling_governor 2>/dev/null; done

# 4c. memory: the Tegra graphics driver pre-fills three 233 MB page pools (~700 MB) that nothing here uses; give it back
N=/sys/module/nvmap_handle/parameters
echo 0 > $N/enable_page_pools 2>/dev/null; echo 1 > $N/shrink_page_pools 2>/dev/null

# 5. backlight
echo 255 > /sys/class/backlight/pwm-backlight/brightness

# 6. mirror: copy Xvfb's screen into fb0 (mode set + mmap write + pan is what reaches the panel)
cat > $R/tmp/mirror.py <<'EOF'
import fcntl, os, struct, mmap, time
log = open('/tmp/mirror.log', 'w')
def L(m):
    log.write('%s\n' % m); log.flush()
fd = os.open('/dev/graphics/fb0', os.O_RDWR)
b = bytearray(160); fcntl.ioctl(fd, 0x4600, b); v = list(struct.unpack('<40I', bytes(b)))
v[4] = 0; v[5] = 0; v[6] = 32; v[21] = 0
v[8:20] = [16, 8, 0, 8, 8, 0, 0, 8, 0, 24, 8, 0]
fcntl.ioctl(fd, 0x4601, bytearray(struct.pack('<40I', *v)))
fcntl.ioctl(fd, 0x4611, 0)
W, H = v[0], v[1]
size = W * H * 4
fb = mmap.mmap(fd, v[2] * v[3] * 4)
pan = bytearray(struct.pack('<40I', *v))
fb[0:size] = b'\x00\x00\x00\xff' * (W * H)     # solid black first
fcntl.ioctl(fd, 0x4606, pan)
L('fb ready %s' % v[0:8])
while not os.path.exists('/tmp/Xvfb_screen0'):
    time.sleep(0.2)
time.sleep(1)
f = open('/tmp/Xvfb_screen0', 'rb')
xm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
hs = struct.unpack('>I', xm[0:4])[0]
ncol = struct.unpack('>I', xm[76:80])[0]
bpl = struct.unpack('>I', xm[48:52])[0]
off = hs + ncol * 12
L('xwd header=%d ncolors=%d bytes_per_line=%d off=%d len=%d' % (hs, ncol, bpl, off, len(xm)))
n = 0
while True:
    try:
        if not os.path.exists('/tmp/mirror.pause'):      # PC mode: ffmpeg owns the framebuffer
            fb[0:size] = xm[off:off + size]
        fcntl.ioctl(fd, 0x4606, pan)
    except Exception as e:
        if n < 3: L('copy: %r' % (e,))
        n += 1
    time.sleep(0.04)
EOF
# (the mirror is started by go.sh only when the native X server can't start)

# 6a. native X: real Xorg on fb0 with the Wacom driver (true pen pressure). Xorg leaves the alpha byte at 0, which
# this panel shows as transparent, so fbpush copies only the changed areas to page 1 with alpha on and shows page 1.
cat > $R/tmp/xorg-native.conf <<'EOF'
Section "ServerFlags"
  Option "AutoAddDevices" "false"
  Option "DontVTSwitch" "true"
  Option "BlankTime" "0"
  Option "StandbyTime" "0"
  Option "SuspendTime" "0"
  Option "OffTime" "0"
EndSection
Section "Device"
  Identifier "fb"
  Driver "fbdev"
  Option "fbdev" "/dev/graphics/fb0"
  Option "ShadowFB" "true"
  #ROTATE#
EndSection
Section "Monitor"
  Identifier "m"
EndSection
Section "Screen"
  Identifier "s"
  Device "fb"
  Monitor "m"
  DefaultDepth 24
EndSection
Section "InputDevice"
  Identifier "pen"
  Driver "wacom"
  Option "Device" "/dev/input/event9"
  Option "Type" "stylus"
EndSection
Section "ServerLayout"
  Identifier "l"
  Screen "s"
  InputDevice "pen" "SendCoreEvents"
EndSection
EOF
cat > $R/tmp/fbpush.py <<'EOF'
# Native-X display pusher. Xorg (fbdev) renders into framebuffer page 0, but leaves the alpha byte at 0, which this
# panel shows as transparent (black). Copy only what X reports as changed (DAMAGE) onto page 1 with alpha forced on,
# and keep the panel on page 1. Idle = no copying at all.
import fcntl, mmap, os, select, struct, sys, time
import numpy as np
from Xlib import display
from Xlib.ext import damage

log = open('/tmp/fbpush.log', 'w')
def L(m):
    log.write('%s %s\n' % (time.strftime('%H:%M:%S'), m)); log.flush()

fd = os.open('/dev/graphics/fb0', os.O_RDWR)
b = bytearray(160); fcntl.ioctl(fd, 0x4600, b); v = list(struct.unpack('<40I', bytes(b)))
W, H, VW, VH = v[0], v[1], v[2], v[3]
fbm = mmap.mmap(fd, VW * VH * 4)
px = np.frombuffer(fbm, dtype=np.uint32).reshape(VH, VW)
src, dst = px[0:H, 0:W], px[H:2 * H, 0:W]
ALPHA = np.uint32((0xff << v[17]) if v[18] else 0xff000000)
v[4] = 0; v[5] = H
panb = bytearray(struct.pack('<40I', *v))
L('fb %dx%d virtual %dx%d red@%d alpha@%d' % (W, H, VW, VH, v[8], v[17]))

# X can be started rotated (fbdev "Rotate" option); DAMAGE and the pointer then use the rotated screen's coordinates
ROT = 'normal'
try: ROT = open('/root/rotation').read().strip()
except OSError: pass
def l2p(x, y):
    if ROT == 'CW': return W - 1 - y, x
    if ROT == 'CCW': return y, H - 1 - x
    if ROT == 'UD': return W - 1 - x, H - 1 - y
    return x, y
def prect(x, y, w, h):
    if ROT not in ('CW', 'CCW', 'UD'): return x, y, w, h
    xa, ya = l2p(x, y); xb, yb = l2p(x + w - 1, y + h - 1)
    return min(xa, xb), min(ya, yb), abs(xa - xb) + 1, abs(ya - yb) + 1
L('rotation %s' % ROT)

def copy(x, y, w, h):
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
    if x1 > x0 and y1 > y0:
        np.bitwise_or(src[y0:y1, x0:x1], ALPHA, out=dst[y0:y1, x0:x1])

def show():
    fcntl.ioctl(fd, 0x4606, panb)

# switch the panel to this framebuffer: mode set (Xorg leaves activate at 16), unblank, then show page 1
v2 = v[:]; v2[4] = 0; v2[5] = 0; v2[21] = 0
fcntl.ioctl(fd, 0x4601, bytearray(struct.pack('<40I', *v2)))
fcntl.ioctl(fd, 0x4611, 0)

d = display.Display(sys.argv[1] if len(sys.argv) > 1 else ':1')
root = d.screen().root
d.damage_query_version()             # DAMAGE needs the version handshake before any other request
dmg = root.damage_create(damage.DamageReportDeltaRectangles)
d.flush()
copy(0, 0, W, H); show()
prev = []                     # last tick's rects are copied once more: Xorg's shadow may land in page 0 just after the event
cur = (0, 0)
paused = False
n_ticks = n_px = 0; t_stat = time.time()
while True:
    select.select([d], [], [], 0.016)
    rects = []
    while d.pending_events():
        e = d.next_event()
        if type(e).__name__ == 'DamageNotify':   # python-xlib registers its own copy of the class, so no isinstance
            a = e.area; rects.append(prect(a.x, a.y, a.width, a.height))
    if rects:
        d.damage_subtract(dmg)
    p = root.query_pointer()          # the software cursor is not reported by DAMAGE
    pc = l2p(p.root_x, p.root_y)
    if pc != cur:
        rects += [(cur[0] - 40, cur[1] - 40, 80, 80), (pc[0] - 40, pc[1] - 40, 80, 80)]
        cur = pc
    if os.path.exists('/tmp/mirror.pause'):   # PC mode: the video player owns the framebuffer
        paused = True; prev = []; continue
    if paused:
        paused = False; copy(0, 0, W, H); show(); continue
    todo = rects + prev
    if len(todo) > 300:
        todo = [(0, 0, W, H)]
    for r in todo:
        copy(*r); n_px += r[2] * r[3]
    if todo:
        show()
    prev = rects
    n_ticks += 1
    if time.time() - t_stat > 30:
        L('ticks %d copied %.1f Mpx' % (n_ticks, n_px / 1e6)); n_ticks = n_px = 0; t_stat = time.time()
EOF

# 6b. touch + pen -> X mouse via XTEST
cat > $R/tmp/touch.py <<'EOF'
import fcntl, math, os, select, struct, sys, time
from Xlib import X, XK, display
from Xlib.ext import xtest
LOG = open('/tmp/touch.log', 'w')
def L(m):
    LOG.write('%s\n' % m); LOG.flush()
W, H = 1920, 1080
SWAP = os.path.exists('/tmp/touch.swap')
FLIPX = os.path.exists('/tmp/touch.flipx')
FLIPY = os.path.exists('/tmp/touch.flipy')
NATIVE = os.path.exists('/tmp/native-x')     # real Xorg: the Wacom X driver owns the pen (true pressure)
ROT = 'normal'                               # native X may be started rotated (/root/rotation: normal CW UD CCW)
if NATIVE:
    try: ROT = open('/root/rotation').read().strip()
    except OSError: pass
LW, LH = (H, W) if ROT in ('CW', 'CCW') else (W, H)   # size of the (rotated) X screen
def p2l(px, py):
    # panel pixel -> X screen pixel (inverse of fbpush's l2p)
    if ROT == 'CW': return py, W - 1 - px
    if ROT == 'CCW': return H - 1 - py, px
    if ROT == 'UD': return W - 1 - px, H - 1 - py
    return px, py
def move(p):
    x, y = p2l(p[0], p[1]); xtest.fake_input(d, X.MotionNotify, 0, x=x, y=y)
import json
_cal = {}
def getcal(kind):
    p = '/root/calib_%s.json' % kind
    try:
        mt = os.stat(p).st_mtime
        c = _cal.get(kind)
        if not c or c[0] != mt:
            _cal[kind] = (mt, json.load(open(p))); L('calib loaded %s %s' % (kind, _cal[kind][1]))
        return _cal[kind][1]
    except Exception:
        return None
def solve3(A, b):
    M = [A[i][:] + [b[i]] for i in range(3)]
    for i in range(3):
        p = max(range(i, 3), key=lambda r: abs(M[r][i])); M[i], M[p] = M[p], M[i]
        for r in range(3):
            if r != i:
                f = M[r][i] / M[i][i]
                M[r] = [M[r][k] - f * M[i][k] for k in range(4)]
    return [M[i][3] / M[i][i] for i in range(3)]
def fit(pts, tgt):
    S = [[0.0] * 3 for _ in range(3)]; bx = [0.0] * 3; by = [0.0] * 3
    for (x, y), (tx, ty) in zip(pts, tgt):
        v = (float(x), float(y), 1.0)
        for i in range(3):
            for j in range(3): S[i][j] += v[i] * v[j]
            bx[i] += v[i] * tx; by[i] += v[i] * ty
    return solve3(S, bx) + solve3(S, by)
TARGETS = [(100, 100), (1820, 100), (1820, 980), (100, 980), (960, 540)]
CAL = {'on': False, 'kind': None, 'pts': [], 'held': False, 'win': None, 'gc': None}
def cal_draw():
    n = len(CAL['pts']); tx, ty = p2l(*TARGETS[n]); w = CAL['win']; g = CAL['gc']
    w.fill_rectangle(g['bg'], 0, 0, LW, LH)               # repaint the whole screen so no old target is left behind
    for k in range(-60, 61, 10):                       # 120 px aiming grid, 10 px cells
        w.line(g['grid'], tx + k, ty - 60, tx + k, ty + 60); w.line(g['grid'], tx - 60, ty + k, tx + 60, ty + k)
    for r in (10, 30):                                 # 20 px and 60 px boxes around the point
        w.rectangle(g['fine'], tx - r, ty - r, 2 * r, 2 * r)
    for a, b in ((-110, -5), (5, 110)):                # bold crosshair with an open centre so the exact point stays visible
        w.line(g['bold'], tx + a, ty, tx + b, ty); w.line(g['bold'], tx, ty + a, tx, ty + b)
    w.fill_rectangle(g['fine'], tx - 1, ty - 1, 3, 3)  # centre dot
    try: w.draw_text(g['fine'], tx + 14 if tx < LW // 2 else tx - 60, ty + 80 if ty < LH // 2 else ty - 72, '%d / %d' % (n + 1, len(TARGETS)))
    except Exception: pass
    d.flush()
def cal_start(kind):
    scr = d.screen()
    win = scr.root.create_window(0, 0, LW, LH, 0, scr.root_depth, X.InputOutput, X.CopyFromParent,
                                 background_pixel=0x0a0c0e, override_redirect=1)
    gc = {'bold': win.create_gc(foreground=0xf0b12a, line_width=3), 'fine': win.create_gc(foreground=0xf0b12a, line_width=1),
          'grid': win.create_gc(foreground=0xffffff, line_width=2), 'bg': win.create_gc(foreground=0x0a0c0e)}
    win.map(); win.configure(stack_mode=X.Above)
    CAL.update(on=True, kind=kind, pts=[], held=True, win=win, gc=gc)   # held: a pen already touching must lift before the first tap counts
    L('calibration start %s' % kind); cal_draw()
def cal_finish():
    coef = fit(CAL['pts'], TARGETS)
    json.dump(coef, open('/root/calib_%s.json' % CAL['kind'], 'w'))
    L('calibration done %s raw=%s coef=%s' % (CAL['kind'], CAL['pts'], coef))
    CAL['win'].destroy(); d.flush(); CAL['on'] = False
def cal_step(dv):
    if dv.down and not CAL['held']:
        CAL['held'] = True; CAL['pts'].append((dv.x, dv.y))
        if len(CAL['pts']) == len(TARGETS): cal_finish()
        else: cal_draw()
    elif not dv.down:
        CAL['held'] = False
_off = {}
def getoff(kind):
    p = '/root/offset_%s.txt' % kind
    try:
        mt = os.stat(p).st_mtime
        c = _off.get(kind)
        if not c or c[0] != mt:
            a = open(p).read().split()
            _off[kind] = (mt, int(a[0]), int(a[1]))
            L('offset %s = %s' % (kind, a))
        return _off[kind][1], _off[kind][2]
    except Exception:
        return 0, 0
def find(name):
    for blk in open('/proc/bus/input/devices').read().split('\n\n'):
        if name in blk:
            for ln in blk.splitlines():
                if 'Handlers=' in ln:
                    for t in ln.replace('=', ' ').split():
                        if t.startswith('event'): return '/dev/input/' + t
def absinfo(fd, code):
    b = bytearray(24)
    fcntl.ioctl(fd, 0x80184540 + code, b)
    return struct.unpack('<6i', bytes(b))
d = None
for _ in range(60):
    try:
        d = display.Display(':0'); break
    except Exception:
        time.sleep(1)
L('display %r' % (d,))
class Dev:
    def __init__(s, name, kind):
        s.kind = kind; s.path = find(name)
        s.fd = os.open(s.path, os.O_RDONLY | os.O_NONBLOCK)
        s.rng = {}
        for c in (0, 1, 0x35, 0x36):
            try: s.rng[c] = absinfo(s.fd, c)
            except Exception: pass
        L('%s %s ranges %s' % (name, s.path, s.rng))
        s.x = s.y = 0; s.down = False; s.slot = 0; s.tid = -1; s.prox = False; s.btn3 = False
        s.changed = False
        s.pressure = 0; s.tiltx = 0; s.tilty = 0; s.eraser = False; s.sent_range = False
        s.x1 = s.y1 = 0; s.tid1 = -1
        s.gest = False; s.gref = 0.0; s.gpx = s.gpy = 0; s.gest_block = False
        s.arng = {}
        for code in (24, 0x1a, 0x1b):
            try: s.arng[code] = absinfo(s.fd, code)
            except Exception: pass
    def scale_xy(s, x, y):
        cx, cy = (0x35, 0x36) if (0x35 in s.rng and s.rng[0x35][2] > 0) else (0, 1)
        if cx not in s.rng or cy not in s.rng: return None
        ox, oy = getoff(s.kind)
        c = getcal(s.kind)
        if c and not CAL['on']:
            px = c[0] * x + c[1] * y + c[2]; py = c[3] * x + c[4] * y + c[5]
            return max(0, min(W - 1, int(px) + ox)), max(0, min(H - 1, int(py) + oy))
        x0, x1 = s.rng[cx][1], s.rng[cx][2]; y0, y1 = s.rng[cy][1], s.rng[cy][2]
        fx = (x - x0) / float(max(1, x1 - x0)); fy = (y - y0) / float(max(1, y1 - y0))
        if SWAP: fx, fy = fy, fx
        if FLIPX: fx = 1 - fx
        if FLIPY: fy = 1 - fy
        return max(0, min(W - 1, int(fx * W) + ox)), max(0, min(H - 1, int(fy * H) + oy))
    def scale(s):
        return s.scale_xy(s.x, s.y)
devs = []
for _i in range(120):
    if _i == 0: L('devices: %s' % [ln.strip() for ln in open('/proc/bus/input/devices') if ln.startswith('N:')])
    try:
        if not any(x.kind == 'pen' for x in devs) and find('Wacom ISDv5 307 Pen'):
            devs.append(Dev('Wacom ISDv5 307 Pen', 'pen'))
        if not any(x.kind == 'touch' for x in devs) and find('Wacom ISDv5 309 Finger'):
            devs.append(Dev('Wacom ISDv5 309 Finger', 'touch'))
    except Exception as e:
        L('init error %r' % (e,))
    if len(devs) == 2: break
    time.sleep(1)
if not devs:
    L('no devices found'); sys.exit(1)

import subprocess
KEYMAP = {102: 'toggle_kbd', 194: 'toggle_kbd', 115: 'ctrl+z', 114: 'ctrl+shift+z',
          224: 'less', 225: 'greater', 217: 'e', 139: 'b', 158: 'pc_toggle'}
class KeyDev:
    def __init__(s, name, path):
        s.kind = 'key'; s.name = name; s.path = path
        s.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        L('key device %s %s' % (name, path))
for nm in ('gpio-keys', 'asterix_input'):
    try:
        p = find(nm)
        if p: devs.append(KeyDev(nm, p))
    except Exception as e:
        L('key dev %s: %r' % (nm, e))
def loadmap():
    m = dict(KEYMAP)
    try:
        for ln in open('/root/keymap.txt'):
            ln = ln.split('#')[0].strip()
            if ln:
                k, a = ln.split(None, 1)
                m[int(k)] = a.strip()
    except Exception:
        pass
    return m
import hmac, hashlib, socket
_pc = {'mt': 0, 'cfg': None}
_usock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_seq = [0]
def pcmode():
    return os.path.exists('/tmp/pcmode')      # tmpfs: always off after a reboot
def pccfg():
    try:
        mt = os.stat('/root/pc.conf').st_mtime
        if mt != _pc['mt']:
            c = {}
            for ln in open('/root/pc.conf'):
                ln = ln.split('#')[0].strip()
                if '=' in ln:
                    k, v = ln.split('=', 1); c[k.strip()] = v.strip()
            _pc['cfg'] = (c['host'], int(c.get('port', 5600)), c['secret'].encode()); _pc['mt'] = mt
            L('pc.conf loaded for %s:%s' % (c['host'], c.get('port', 5600)))
    except Exception as e:
        if _pc['cfg'] is None: L('pc.conf: %r' % (e,))
    return _pc['cfg']
def pcsend(payload):
    cfg = pccfg()
    if not cfg: return
    tag = hmac.new(cfg[2], payload, hashlib.sha256).digest()[:8]
    try: _usock.sendto(payload + tag, (cfg[0], cfg[1]))
    except Exception: pass
def nextseq():
    _seq[0] = max(_seq[0] + 1, int(time.time() * 1000) & 0xFFFFFFFF)
    return _seq[0]
def send_key(action):
    pcsend(b'K' + struct.pack('<I', nextseq()) + action.encode()[:24].ljust(24, b'\0'))
def send_pen(dv):
    p = dv.scale()
    if not p: return
    inrange = dv.prox or dv.down
    if not inrange and not dv.sent_range: return
    pr = dv.arng.get(24); pm = pr[2] if pr and pr[2] > 0 else 2047
    press = min(1023, int(dv.pressure * 1023 / float(pm))) if dv.down else 0
    def tilt(v, code):
        r = dv.arng.get(code)
        if not r or r[2] <= r[1]: return 0
        return int(max(-90, min(90, (v - r[1]) * 180.0 / (r[2] - r[1]) - 90)))
    flags = (1 if inrange else 0) | (2 if dv.down else 0) | (4 if dv.btn3 else 0) | (8 if dv.eraser else 0)
    nx = int(p[0] * 65535 / float(W - 1)); ny = int(p[1] * 65535 / float(H - 1))
    pcsend(b'P' + struct.pack('<IBHHHbb', nextseq(), flags, nx, ny, press, tilt(dv.tiltx, 0x1a), tilt(dv.tilty, 0x1b)))
    dv.sent_range = inrange
def send_touch(dv):
    # PC mode: one finger -> real Windows touch on the PC (tap = click, drag = drag/scroll).
    # Palm safety: while the pen is near the screen fingers are ignored (and a touch in progress is lifted).
    pen = [x for x in devs if x.kind == 'pen']
    down = dv.down and not (pen and (pen[0].prox or pen[0].down))
    if not down and not dv.sent_range: return
    p = dv.scale()
    if not p: return
    nx = int(p[0] * 65535 / float(W - 1)); ny = int(p[1] * 65535 / float(H - 1))
    pcsend(b'T' + struct.pack('<IBHH', nextseq(), 1 if down else 0, nx, ny))
    dv.sent_range = down
_gk = {'mt': None, 'pid': 0, 'map': {}}
def gamekey(code, v):
    # A game can ask for the raw hardware keys as held keys (press AND release) by writing /tmp/gamekeys.txt:
    # first line its pid, then "<linux key code> <X keysym>" lines. Ignored once that process is gone.
    try: mt = os.stat('/tmp/gamekeys.txt').st_mtime
    except OSError: return False
    try:
        if _gk['mt'] != mt:
            ln = open('/tmp/gamekeys.txt').read().split('\n')
            _gk.update(mt=mt, pid=int(ln[0]), map=dict((int(a), b) for a, b in (l.split() for l in ln[1:] if l.strip())))
        if not os.path.exists('/proc/%d' % _gk['pid']): return False
        ks = _gk['map'].get(code)
        if not ks: return False
        if v == 2: return True                                   # auto-repeat: the key is simply still held
        kc = d.keysym_to_keycode(XK.string_to_keysym(ks))
        if kc:
            xtest.fake_input(d, X.KeyPress if v else X.KeyRelease, kc); d.sync()
        else:
            subprocess.Popen(['xdotool', 'keydown' if v else 'keyup', ks])
        return True
    except Exception as e:
        L('gamekey %r' % (e,)); return False
def keyact(name, c):
    L('KEY %s code=%d' % (name, c))
    a = loadmap().get(c)
    try:
        if a == 'pc_toggle':
            subprocess.Popen(['/root/pcmode.sh'])
        elif a == 'toggle_kbd':
            if pcmode(): send_key('osk')        # PC mode: open the PC's on-screen keyboard
            else: subprocess.Popen(['/root/keys.sh'])
        elif a and pcmode():
            send_key(a)
        elif a:
            subprocess.Popen(['xdotool', 'key', a])
    except Exception as e:
        L('keyact %r' % (e,))
btn = {1: False, 2: False, 3: False}
pen_logs = [0]
def press(b, on):
    if btn[b] != on:
        xtest.fake_input(d, X.ButtonPress if on else X.ButtonRelease, b); btn[b] = on
gest_logs = [0]
def glog(m):
    if gest_logs[0] < 50:
        gest_logs[0] += 1; L(m)
def keytap(name):
    kc = d.keysym_to_keycode(XK.string_to_keysym(name))
    if not kc: glog('no keycode %s' % name); return
    xtest.fake_input(d, X.KeyPress, kc); xtest.fake_input(d, X.KeyRelease, kc)
def zoom(sign):
    # dir 1 = pinch out (zoom in, '+'), -1 = pinch in (zoom out, '-')
    if sign > 0:
        sc = d.keysym_to_keycode(XK.string_to_keysym('Shift_L'))
        if sc: xtest.fake_input(d, X.KeyPress, sc)
        keytap('plus')
        if sc: xtest.fake_input(d, X.KeyRelease, sc)
        glog('zoom +')
    else:
        keytap('minus'); glog('zoom -')
def gesture(dv):
    if dv.kind != 'touch': return
    both = dv.down and dv.tid1 != -1
    if not both:
        if dv.gest:
            press(2, False); dv.gest = False; dv.gest_block = True; glog('gesture end')
        if not dv.down and dv.tid1 == -1: dv.gest_block = False
        return
    dist = math.hypot(dv.x - dv.x1, dv.y - dv.y1)
    if not dv.gest:
        dv.gest = True; press(1, False)            # stop single-finger emulation
        p = dv.scale_xy((dv.x + dv.x1) / 2.0, (dv.y + dv.y1) / 2.0)
        if p:
            move(p)
            dv.gpx, dv.gpy = p
        press(2, True)                             # middle button = pan
        dv.gref = dist
        glog('gesture start')
        return
    p = dv.scale_xy((dv.x + dv.x1) / 2.0, (dv.y + dv.y1) / 2.0)
    if p:
        move(p); dv.gpx, dv.gpy = p
    if dv.gref > 0:
        if dist > dv.gref * 1.12: dv.gref = dist; zoom(1)
        elif dist < dv.gref * 0.88: dv.gref = dist; zoom(-1)
def handle(dv, t, c, v):
    if dv.kind == 'key':
        if t == 1 and gamekey(c, v): return
        if t == 1 and v == 1: keyact(dv.name, c)
        return
    if t == 3:
        if dv.kind == 'touch':
            if c == 0x2f: dv.slot = v
            elif dv.slot == 0:
                if c == 0x39: dv.tid = v; dv.down = v != -1
                elif c == 0x35 or c == 0: dv.x = v
                elif c == 0x36 or c == 1: dv.y = v
            elif dv.slot == 1:
                if c == 0x39: dv.tid1 = v
                elif c == 0x35 or c == 0: dv.x1 = v
                elif c == 0x36 or c == 1: dv.y1 = v
        else:
            if c == 0: dv.x = v
            elif c == 1: dv.y = v
            elif c == 24:
                if (v > 0) != dv.down and pen_logs[0] < 300:
                    pen_logs[0] += 1; L('pen pressure=%d' % v)
                dv.down = v > 0
                dv.pressure = v
            elif c == 0x1a: dv.tiltx = v
            elif c == 0x1b: dv.tilty = v
        dv.changed = True
    elif t == 1:
        if dv.kind == 'pen':
            if pen_logs[0] < 300:
                pen_logs[0] += 1; L('pen key c=0x%x v=%d' % (c, v))
            if c == 0x14a: dv.down = bool(v)
            elif c == 0x14b: dv.btn3 = bool(v)
            elif c == 0x140: dv.prox = bool(v)
            elif c == 0x141: dv.eraser = bool(v); dv.prox = dv.prox or bool(v)
        elif c == 0x14a and dv.kind == 'touch':
            dv.down = bool(v)
    elif t == 0 and c == 0:
        if CAL['on']:
            if dv.kind == CAL['kind']: cal_step(dv)
            return
        if pcmode():
            if dv.kind == 'pen': send_pen(dv)      # real pressure/tilt pen on the PC
            elif dv.kind == 'touch': send_touch(dv) # finger = Windows touch (ignored while the pen is near)
            dv.changed = False
            return
        if NATIVE and dv.kind == 'pen':
            dv.changed = False; return              # the Wacom X driver moves/clicks the pen itself
        gesture(dv)
        if dv.kind == 'touch' and (dv.gest or dv.gest_block):
            d.sync(); dv.changed = False; return    # two fingers: no single-finger pointer
        p = dv.scale()
        if p:
            move(p)
        press(1, dv.down)
        if dv.kind == 'pen': press(3, dv.btn3)
        d.sync()
        dv.changed = False
def pen_ctm():
    # native X: turn the pen calibration + nudge (raw -> screen px) into the X "Coordinate Transformation Matrix",
    # which acts on the 0..1 range the Wacom driver maps the raw axes to
    pen = [x for x in devs if x.kind == 'pen']
    if not pen or 0 not in pen[0].rng or 1 not in pen[0].rng: return
    (_, x0, x1, _, _, _), (_, y0, y1, _, _, _) = pen[0].rng[0], pen[0].rng[1]
    rx, ry = float(max(1, x1 - x0)), float(max(1, y1 - y0))
    c = getcal('pen'); ox, oy = getoff('pen')
    if not c: c = [W / rx, 0.0, -x0 * W / rx, 0.0, H / ry, -y0 * H / ry]
    P = [[c[0] * rx, c[1] * ry, c[0] * x0 + c[1] * y0 + c[2] + ox],
         [c[3] * rx, c[4] * ry, c[3] * x0 + c[4] * y0 + c[5] + oy], [0.0, 0.0, 1.0]]
    R = {'CW': [[0, 1, 0], [-1, 0, W - 1], [0, 0, 1]], 'CCW': [[0, -1, H - 1], [1, 0, 0], [0, 0, 1]],
         'UD': [[-1, 0, W - 1], [0, -1, H - 1], [0, 0, 1]]}.get(ROT, [[1, 0, 0], [0, 1, 0], [0, 0, 1]])
    RP = [[sum(R[i][k] * P[k][j] for k in range(3)) for j in range(3)] for i in range(3)]
    m = [RP[0][0] / LW, RP[0][1] / LW, RP[0][2] / LW, RP[1][0] / LH, RP[1][1] / LH, RP[1][2] / LH, 0, 0, 1]
    r = subprocess.call(['xinput', 'set-prop', 'pen', 'Coordinate Transformation Matrix'] + ['%.6f' % f for f in m])
    L('pen ctm %s rc=%s' % (['%.4f' % f for f in m], r))
def ctm_sig():
    sig = []
    for f in ('/root/calib_pen.json', '/root/offset_pen.txt'):
        try: sig.append(os.stat(f).st_mtime)
        except OSError: sig.append(0)
    return sig
last_sig = None; t_sig = 0
n = 0
while True:
    r, _, _ = select.select([x.fd for x in devs], [], [], 1.0)
    if NATIVE and not CAL['on'] and time.time() - t_sig > 1:
        t_sig = time.time(); sg = ctm_sig()
        if sg != last_sig:
            last_sig = sg
            try: pen_ctm()
            except Exception as e: L('pen ctm %r' % (e,))
    if not CAL['on']:
        for k in ('pen', 'touch'):
            fp = '/root/calib_start_%s' % k
            if os.path.exists(fp):
                try: os.remove(fp); cal_start(k)
                except Exception as e: L('cal start %r' % (e,))
    for x in devs:
        if x.fd in r:
            try: data = os.read(x.fd, 16 * 64)
            except OSError: continue
            for i in range(0, len(data) - 15, 16):
                sec, usec, t, c, v = struct.unpack('<llHHi', data[i:i + 16])
                handle(x, t, c, v)
                n += 1
                if n < 30 and x.kind != 'key': L('%s t=%d c=%d v=%d' % (x.kind, t, c, v))
EOF

# 7. virtual X server with coloured test terminals (position proof) and a real shell
# 6c. sshd over USB (optional): put your public key in /data/local/ssh/authorized_keys, then
#     adb forward tcp:2222 tcp:2222 && ssh -p 2222 root@127.0.0.1
# It listens on 127.0.0.1 only, key login only.
if [ -s /data/local/ssh/authorized_keys ] && [ -x $R/usr/sbin/sshd ]; then
  mkdir -p $R/root/.ssh
  cp /data/local/ssh/authorized_keys $R/root/.ssh/authorized_keys
  chmod 700 $R/root/.ssh
  chmod 600 $R/root/.ssh/authorized_keys
  cat > $R/etc/ssh/sshd_config.usb <<'EOS'
Port 2222
ListenAddress 127.0.0.1
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
AuthorizedKeysFile /root/.ssh/authorized_keys
PidFile /tmp/sshd.pid
StrictModes no
Subsystem sftp internal-sftp
EOS
  $B chroot $R /usr/bin/ssh-keygen -A >/dev/null 2>&1
  mkdir -p $R/var/empty
  chmod 755 $R/var/empty
  $B chroot $R /usr/sbin/sshd -f /etc/ssh/sshd_config.usb -E /tmp/sshd.log &
fi

# 6d. Wi-Fi (script lives on UDA so it can change without a reflash)
[ -f /data/local/wifi.sh ] && $B sh /data/local/wifi.sh $B $R &

cat > $R/tmp/go.sh <<'EOS'
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME=/root
rm -f /tmp/native-x
if [ ! -f /root/use-xvfb ]; then              # touch /root/use-xvfb to force the old virtual-screen mode
  ROT=$(cat /root/rotation 2>/dev/null); case "$ROT" in CW|CCW|UD) ;; *) ROT=normal ;; esac
  if [ $ROT = normal ]; then sed '/#ROTATE#/d' /tmp/xorg-native.conf > /tmp/xorg-run.conf
  else sed "s/#ROTATE#/Option \"Rotate\" \"$ROT\"/" /tmp/xorg-native.conf > /tmp/xorg-run.conf; fi
  Xorg :0 -config /tmp/xorg-run.conf -noreset -nolisten tcp -sharevts -novtswitch -logfile /tmp/Xorg.log > /tmp/xorg.out 2>&1 &
  i=0; while [ $i -lt 40 ] && [ ! -S /tmp/.X11-unix/X0 ]; do sleep 0.25; i=$((i+1)); done
fi
if [ -S /tmp/.X11-unix/X0 ]; then
  python3 /tmp/fbpush.py :0 > /tmp/fbpush.out 2>&1 &
  sleep 2
  if kill -0 $! 2>/dev/null; then touch /tmp/native-x; else pkill -x Xorg; sleep 1; fi   # pusher died: fall back below
fi
if [ ! -f /tmp/native-x ]; then
  pkill -x Xorg; rm -f /tmp/.X0-lock /tmp/.X11-unix/X0
  Xvfb :0 -screen 0 1920x1080x24 -fbdir /tmp -nolisten tcp > /tmp/xvfb.out 2>&1 &
  python3 /tmp/mirror.py > /tmp/mirror.out 2>&1 &
  sleep 3
fi
export DISPLAY=:0
sh /root/session.sh
python3 /tmp/touch.py > /tmp/touch.out 2>&1 &
wait
EOS
$B chroot $R /bin/sh /tmp/go.sh &

# 8. save logs repeatedly while it runs
i=0
while [ $i -lt 40 ]; do
  $B sleep 5
  $B cp $LOG /data/local/linux-boot.log
  $B cp $R/tmp/mirror.log /data/local/linux-mirror.log 2>/dev/null
  $B cp $R/tmp/xvfb.out /data/local/linux-xvfb.out 2>/dev/null
  $B cp $R/tmp/touch.log /data/local/linux-touch.log 2>/dev/null
  $B cp $R/tmp/Xorg.log /data/local/linux-xorg.log 2>/dev/null
  $B cp $R/tmp/fbpush.log /data/local/linux-fbpush.log 2>/dev/null
  $B cp $R/tmp/touch.out /data/local/linux-touch.out 2>/dev/null
  $B chmod 666 /data/local/linux-*.log /data/local/linux-*.out 2>/dev/null
  $B sync
  i=$((i+1))
done
wait
