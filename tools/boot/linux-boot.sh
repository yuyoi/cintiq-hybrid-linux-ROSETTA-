#!/sbin/busybox sh
# Linux boot mode (runs inside the SOS ramdisk). Display = Xvfb mirrored into the Tegra fb0.
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
        fb[0:size] = xm[off:off + size]
        fcntl.ioctl(fd, 0x4606, pan)
    except Exception as e:
        if n < 3: L('copy: %r' % (e,))
        n += 1
    time.sleep(0.04)
EOF
$B chroot $R /bin/sh -c 'PATH=/usr/bin:/bin:/usr/sbin:/sbin; python3 /tmp/mirror.py' &

# 6b. touch + pen -> X mouse via XTEST
cat > $R/tmp/touch.py <<'EOF'
import fcntl, os, select, struct, sys, time
from Xlib import X, display
from Xlib.ext import xtest
LOG = open('/tmp/touch.log', 'w')
def L(m):
    LOG.write('%s\n' % m); LOG.flush()
W, H = 1920, 1080
SWAP = os.path.exists('/tmp/touch.swap')
FLIPX = os.path.exists('/tmp/touch.flipx')
FLIPY = os.path.exists('/tmp/touch.flipy')
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
    tx, ty = TARGETS[len(CAL['pts'])]; w = CAL['win']; gc = CAL['gc']
    w.clear_area(0, 0, W, H)
    w.line(gc, tx - 70, ty, tx + 70, ty); w.line(gc, tx, ty - 70, tx, ty + 70)
    w.arc(gc, tx - 35, ty - 35, 70, 70, 0, 360 * 64)
    d.flush()
def cal_start(kind):
    scr = d.screen()
    win = scr.root.create_window(0, 0, W, H, 0, scr.root_depth, X.InputOutput, X.CopyFromParent,
                                 background_pixel=0x0a0c0e, override_redirect=1)
    gc = win.create_gc(foreground=0xf0b12a, line_width=3)
    win.map(); win.configure(stack_mode=X.Above)
    CAL.update(on=True, kind=kind, pts=[], held=False, win=win, gc=gc)
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
    def scale(s):
        cx, cy = (0x35, 0x36) if (0x35 in s.rng and s.rng[0x35][2] > 0) else (0, 1)
        if cx not in s.rng or cy not in s.rng: return None
        ox, oy = getoff(s.kind)
        c = getcal(s.kind)
        if c and not CAL['on']:
            px = c[0] * s.x + c[1] * s.y + c[2]; py = c[3] * s.x + c[4] * s.y + c[5]
            return max(0, min(W - 1, int(px) + ox)), max(0, min(H - 1, int(py) + oy))
        x0, x1 = s.rng[cx][1], s.rng[cx][2]; y0, y1 = s.rng[cy][1], s.rng[cy][2]
        fx = (s.x - x0) / float(max(1, x1 - x0)); fy = (s.y - y0) / float(max(1, y1 - y0))
        if SWAP: fx, fy = fy, fx
        if FLIPX: fx = 1 - fx
        if FLIPY: fy = 1 - fy
        return max(0, min(W - 1, int(fx * W) + ox)), max(0, min(H - 1, int(fy * H) + oy))
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
          224: 'less', 225: 'greater', 217: 'e', 139: 'b', 158: 'Escape'}
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
def keyact(name, c):
    L('KEY %s code=%d' % (name, c))
    a = loadmap().get(c)
    try:
        if a == 'toggle_kbd':
            subprocess.Popen(['/root/keys.sh'])
        elif a:
            subprocess.Popen(['xdotool', 'key', a])
    except Exception as e:
        L('keyact %r' % (e,))
btn = {1: False, 3: False}
pen_logs = [0]
def press(b, on):
    if btn[b] != on:
        xtest.fake_input(d, X.ButtonPress if on else X.ButtonRelease, b); btn[b] = on
def handle(dv, t, c, v):
    if dv.kind == 'key':
        if t == 1 and v == 1: keyact(dv.name, c)
        return
    if t == 3:
        if dv.kind == 'touch':
            if c == 0x2f: dv.slot = v
            elif dv.slot == 0:
                if c == 0x39: dv.tid = v; dv.down = v != -1
                elif c == 0x35 or c == 0: dv.x = v
                elif c == 0x36 or c == 1: dv.y = v
        else:
            if c == 0: dv.x = v
            elif c == 1: dv.y = v
            elif c == 24:
                if (v > 0) != dv.down and pen_logs[0] < 300:
                    pen_logs[0] += 1; L('pen pressure=%d' % v)
                dv.down = v > 0
        dv.changed = True
    elif t == 1:
        if dv.kind == 'pen':
            if pen_logs[0] < 300:
                pen_logs[0] += 1; L('pen key c=0x%x v=%d' % (c, v))
            if c == 0x14a: dv.down = bool(v)
            elif c == 0x14b: dv.btn3 = bool(v)
            elif c == 0x140: dv.prox = bool(v)
        elif c == 0x14a and dv.kind == 'touch':
            dv.down = bool(v)
    elif t == 0 and c == 0:
        if CAL['on']:
            if dv.kind == CAL['kind']: cal_step(dv)
            return
        p = dv.scale()
        if p:
            xtest.fake_input(d, X.MotionNotify, 0, x=p[0], y=p[1])
        press(1, dv.down)
        if dv.kind == 'pen': press(3, dv.btn3)
        d.sync()
        dv.changed = False
n = 0
while True:
    r, _, _ = select.select([x.fd for x in devs], [], [], 1.0)
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
cat > $R/tmp/go.sh <<'EOS'
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export HOME=/root
Xvfb :0 -screen 0 1920x1080x24 -fbdir /tmp -nolisten tcp > /tmp/xvfb.out 2>&1 &
sleep 3
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
  $B cp $R/tmp/touch.out /data/local/linux-touch.out 2>/dev/null
  $B chmod 666 /data/local/linux-*.log /data/local/linux-*.out 2>/dev/null
  $B sync
  i=$((i+1))
done
wait
