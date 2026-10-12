"""Wireless Cintiq - PC side. Receives authenticated pen/key packets over UDP and injects a real Windows pen.

Packet (little endian), followed by an 8-byte truncated HMAC-SHA256 tag over the payload:
  'P' seq:u32 flags:u8 x:u16 y:u16 pressure:u16 tiltx:i8 tilty:i8
       flags: bit0 in-range, bit1 contact, bit2 barrel button, bit3 eraser
       x,y: 0..65535 across the mapped region; pressure 0..1023; tilt -90..90 degrees
  'K' seq:u32 action:24 bytes (utf-8, NUL padded), e.g. 'ctrl+z'

Only datagrams from ALLOW_IP with a valid tag and a rising sequence number are accepted.
Usage: python pen_injector.py [--bind IP] [--port N] [--allow IP] [--monitor primary|virtual] [--secret-file F]
"""
import argparse, ctypes, hashlib, hmac, os, socket, struct, subprocess, sys, time
from ctypes import wintypes as wt

PT_TOUCH, PT_PEN = 2, 3
F_PRIMARY = 0x2000
TOUCH_MASK_CONTACTAREA = 0x1
POINTER_FEEDBACK_DEFAULT = 1
F_NEW, F_INRANGE, F_INCONTACT, F_FIRST, F_DOWN, F_UPDATE, F_UP = 0x1, 0x2, 0x4, 0x10, 0x10000, 0x20000, 0x40000
PEN_BARREL, PEN_INVERTED, PEN_ERASER = 0x1, 0x2, 0x4
MASK_PRESSURE, MASK_TILTX, MASK_TILTY = 0x1, 0x4, 0x8


class POINTER_INFO(ctypes.Structure):
    _fields_ = [('pointerType', wt.DWORD), ('pointerId', ctypes.c_uint32), ('frameId', ctypes.c_uint32),
                ('pointerFlags', wt.DWORD), ('sourceDevice', wt.HANDLE), ('hwndTarget', wt.HWND),
                ('ptPixelLocation', wt.POINT), ('ptHimetricLocation', wt.POINT),
                ('ptPixelLocationRaw', wt.POINT), ('ptHimetricLocationRaw', wt.POINT),
                ('dwTime', wt.DWORD), ('historyCount', ctypes.c_uint32), ('InputData', ctypes.c_int32),
                ('dwKeyStates', wt.DWORD), ('PerformanceCount', ctypes.c_uint64), ('ButtonChangeType', ctypes.c_int)]


class POINTER_PEN_INFO(ctypes.Structure):
    _fields_ = [('pointerInfo', POINTER_INFO), ('penFlags', wt.DWORD), ('penMask', wt.DWORD),
                ('pressure', ctypes.c_uint32), ('rotation', ctypes.c_uint32),
                ('tiltX', ctypes.c_int32), ('tiltY', ctypes.c_int32)]


class POINTER_TOUCH_INFO(ctypes.Structure):
    _fields_ = [('pointerInfo', POINTER_INFO), ('touchFlags', wt.DWORD), ('touchMask', wt.DWORD),
                ('rcContact', wt.RECT), ('rcContactRaw', wt.RECT),
                ('orientation', ctypes.c_uint32), ('pressure', ctypes.c_uint32)]


class _U(ctypes.Union):
    _fields_ = [('touchInfo', POINTER_TOUCH_INFO), ('penInfo', POINTER_PEN_INFO)]


class POINTER_TYPE_INFO(ctypes.Structure):
    _anonymous_ = ('u',)
    _fields_ = [('type', wt.DWORD), ('u', _U)]


user32 = ctypes.WinDLL('user32', use_last_error=True)
user32.CreateSyntheticPointerDevice.restype = wt.HANDLE
user32.CreateSyntheticPointerDevice.argtypes = [wt.DWORD, ctypes.c_ulong, ctypes.c_int]
user32.InjectSyntheticPointerInput.restype = wt.BOOL
user32.InjectSyntheticPointerInput.argtypes = [wt.HANDLE, ctypes.POINTER(POINTER_TYPE_INFO), ctypes.c_uint32]

VK = {'ctrl': 0x11, 'shift': 0x10, 'alt': 0x12, 'esc': 0x1B, 'escape': 0x1B, 'enter': 0x0D, 'space': 0x20,
      'less': 0xBC, 'greater': 0xBE, 'bracketleft': 0xDB, 'bracketright': 0xDD}


def vk_for(name):
    n = name.lower()
    if n in VK: return VK[n], (n in ('greater', 'less'))
    if len(n) == 1 and n.isalnum(): return ord(n.upper()), False
    return None, False


def send_keys(action):
    """action like 'ctrl+shift+z' -> press/release with modifiers."""
    if action.lower() == 'osk':        # toggle the Windows on-screen keyboard
        if subprocess.run(['taskkill', '/im', 'osk.exe'], capture_output=True).returncode != 0:
            subprocess.Popen(['osk.exe'])
        return True
    parts = action.lower().split('+')
    seq = []
    for p in parts:
        vk, shifted = vk_for(p)
        if vk is None: return False
        seq.append((vk, shifted))
    down = []
    for vk, shifted in seq:
        if shifted and 0x10 not in [d for d, _ in down]:
            user32.keybd_event(0x10, 0, 0, 0); down.append((0x10, False))
        user32.keybd_event(vk, 0, 0, 0); down.append((vk, shifted))
    for vk, _ in reversed(down):
        user32.keybd_event(vk, 0, 2, 0)
    return True


class Pen:
    def __init__(self, region):
        self.dev = user32.CreateSyntheticPointerDevice(PT_PEN, 1, POINTER_FEEDBACK_DEFAULT)
        if not self.dev:
            raise OSError('CreateSyntheticPointerDevice failed: %d' % ctypes.get_last_error())
        self.rx, self.ry, self.rw, self.rh = region
        self.in_range = False
        self.contact = False
        self.frame = 0

    def inject(self, flags, penflags, x, y, pressure, tx, ty):
        pi = POINTER_TYPE_INFO()
        pi.type = PT_PEN
        p = pi.penInfo
        p.pointerInfo.pointerType = PT_PEN
        p.pointerInfo.pointerId = 0
        self.frame += 1
        p.pointerInfo.frameId = self.frame
        p.pointerInfo.pointerFlags = flags
        p.pointerInfo.ptPixelLocation.x = x
        p.pointerInfo.ptPixelLocation.y = y
        p.penFlags = penflags
        p.penMask = MASK_PRESSURE | MASK_TILTX | MASK_TILTY
        p.pressure = pressure
        p.tiltX = tx
        p.tiltY = ty
        if not user32.InjectSyntheticPointerInput(self.dev, ctypes.byref(pi), 1):
            print('inject failed', ctypes.get_last_error(), file=sys.stderr)

    def update(self, inrange, contact, barrel, eraser, nx, ny, pressure, tx, ty):
        x = self.rx + int(nx / 65535.0 * (self.rw - 1))
        y = self.ry + int(ny / 65535.0 * (self.rh - 1))
        pf = (PEN_BARREL if barrel else 0) | ((PEN_INVERTED | PEN_ERASER) if eraser else 0)
        pressure = min(1024, pressure)
        if inrange and not self.in_range:
            self.inject(F_NEW | F_INRANGE | F_UPDATE, pf, x, y, 0, tx, ty); self.in_range = True
        if not inrange:
            if self.contact:
                self.inject(F_UP | F_INRANGE, pf, x, y, 0, tx, ty); self.contact = False
            if self.in_range:
                self.inject(F_UPDATE, pf, x, y, 0, tx, ty); self.in_range = False
            return
        if contact and not self.contact:
            self.inject(F_DOWN | F_INRANGE | F_INCONTACT | F_FIRST, pf, x, y, max(pressure, 1), tx, ty); self.contact = True
        elif contact:
            self.inject(F_UPDATE | F_INRANGE | F_INCONTACT | F_FIRST, pf, x, y, max(pressure, 1), tx, ty)
        elif self.contact:
            self.inject(F_UP | F_INRANGE, pf, x, y, 0, tx, ty); self.contact = False
        else:
            self.inject(F_UPDATE | F_INRANGE, pf, x, y, 0, tx, ty)


class Touch:
    """One finger from the tablet as a real Windows touch contact (tap = click, drag = drag/scroll)."""
    def __init__(self, region):
        self.dev = user32.CreateSyntheticPointerDevice(PT_TOUCH, 1, POINTER_FEEDBACK_DEFAULT)
        if not self.dev:
            raise OSError('CreateSyntheticPointerDevice(touch) failed: %d' % ctypes.get_last_error())
        self.rx, self.ry, self.rw, self.rh = region
        self.contact = False; self.frame = 0; self.x = self.y = 0; self.last = 0.0

    def inject(self, flags):
        pi = POINTER_TYPE_INFO(); pi.type = PT_TOUCH
        t = pi.touchInfo
        t.pointerInfo.pointerType = PT_TOUCH; t.pointerInfo.pointerId = 0
        self.frame += 1; t.pointerInfo.frameId = self.frame
        t.pointerInfo.pointerFlags = flags
        t.pointerInfo.ptPixelLocation.x = self.x; t.pointerInfo.ptPixelLocation.y = self.y
        t.touchMask = TOUCH_MASK_CONTACTAREA
        t.rcContact.left, t.rcContact.top, t.rcContact.right, t.rcContact.bottom = self.x - 4, self.y - 4, self.x + 4, self.y + 4
        if not user32.InjectSyntheticPointerInput(self.dev, ctypes.byref(pi), 1):
            print('touch inject failed', ctypes.get_last_error(), file=sys.stderr)
        self.last = time.monotonic()

    def update(self, down, nx, ny):
        self.x = self.rx + int(nx / 65535.0 * (self.rw - 1)); self.y = self.ry + int(ny / 65535.0 * (self.rh - 1))
        if down and not self.contact:
            self.inject(F_DOWN | F_INRANGE | F_INCONTACT | F_PRIMARY); self.contact = True
            print('touch down at', self.x, self.y, 'from', nx, ny, flush=True)
        elif down:
            self.inject(F_UPDATE | F_INRANGE | F_INCONTACT | F_PRIMARY)
        elif self.contact:
            self.inject(F_UP | F_PRIMARY); self.contact = False

    def keepalive(self):
        # Windows cancels a touch contact that stops reporting, so a finger resting still is re-sent
        if self.contact and time.monotonic() - self.last > 0.05:
            self.inject(F_UPDATE | F_INRANGE | F_INCONTACT | F_PRIMARY)


PEN_UNTIL = [0.0]        # monotonic time until which the pen "owns" the cursor


def start_mouse_priority(hold):
    """While the pen is active, swallow the PC's physical mouse (events not flagged injected) so the two can't fight."""
    import threading
    class MSLL(ctypes.Structure):
        _fields_ = [('x', ctypes.c_long), ('y', ctypes.c_long), ('data', wt.DWORD), ('flags', wt.DWORD),
                    ('time', wt.DWORD), ('extra', ctypes.c_size_t)]
    proc_t = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wt.WPARAM, wt.LPARAM)
    user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, proc_t, ctypes.c_void_p, wt.DWORD]
    user32.SetWindowsHookExW.restype = ctypes.c_void_p

    def cb(code, wparam, lparam):
        if code >= 0 and time.monotonic() < PEN_UNTIL[0]:
            if not (ctypes.cast(lparam, ctypes.POINTER(MSLL)).contents.flags & 1):   # LLMHF_INJECTED
                return 1
        return user32.CallNextHookEx(None, code, wparam, lparam)
    keep = proc_t(cb)

    def loop():
        k32 = ctypes.WinDLL('kernel32', use_last_error=True)
        k32.GetModuleHandleW.restype = ctypes.c_void_p
        h = user32.SetWindowsHookExW(14, keep, k32.GetModuleHandleW(None), 0)   # WH_MOUSE_LL
        if not h:
            print('mouse priority: hook failed, error', ctypes.get_last_error(), flush=True); return
        print('mouse priority: on', flush=True)
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
    threading.Thread(target=loop, daemon=True).start()
    return hold


def region_for(mode):
    if mode == 'virtual':
        return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77), user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))
    import monitors                                    # primary / second / N: one monitor of an extended desktop
    return monitors.pick(mode)[1:5]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--bind', default='0.0.0.0')
    ap.add_argument('--port', type=int, default=5600)
    ap.add_argument('--allow', required=True, help='only accept datagrams from this IP')
    ap.add_argument('--monitor', default='primary', help='primary, second, a monitor number, or virtual (all screens)')
    ap.add_argument('--no-mouse-priority', action='store_true', help='let the PC mouse move the cursor while the pen is active')
    ap.add_argument('--hold', type=float, default=3.0, help='seconds after the last pen packet that the PC mouse stays ignored')
    ap.add_argument('--secret-file', default=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'secret.txt'))
    a = ap.parse_args()
    secret = open(a.secret_file, 'rb').read().strip()
    # per-process DPI awareness so pixel coordinates are real pixels
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception: pass
    pen = Pen(region_for(a.monitor))
    touch = Touch(region_for(a.monitor))
    if not a.no_mouse_priority:
        start_mouse_priority(a.hold)
    print('region', (pen.rx, pen.ry, pen.rw, pen.rh), 'listening', a.bind, a.port, 'allow', a.allow, flush=True)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((a.bind, a.port))
    last = -1
    stats = [0, 0]
    t0 = time.time()
    s.settimeout(0.05)
    while True:
        try:
            data, addr = s.recvfrom(512)
        except socket.timeout:
            touch.keepalive(); continue
        if (a.allow != 'any' and addr[0] != a.allow) or len(data) < 9 + 8:   # 'any': the HMAC tag is the gate
            continue
        payload, tag = data[:-8], data[-8:]
        if not hmac.compare_digest(hmac.new(secret, payload, hashlib.sha256).digest()[:8], tag):
            stats[1] += 1
            continue
        seq = struct.unpack_from('<I', payload, 1)[0]
        if seq <= last and last - seq < 1000000:
            continue
        last = seq
        kind = payload[:1]
        if kind == b'P' and len(payload) >= 14:
            flags, x, y, pr, tx, ty = struct.unpack_from('<BHHHbb', payload, 5)
            pen.update(bool(flags & 1), bool(flags & 2), bool(flags & 4), bool(flags & 8), x, y, pr, tx, ty)
            stats[0] += 1
            PEN_UNTIL[0] = time.monotonic() + a.hold
        elif kind == b'T' and len(payload) >= 10:
            down, x, y = struct.unpack_from('<BHH', payload, 5)
            touch.update(bool(down & 1), x, y)
            PEN_UNTIL[0] = time.monotonic() + a.hold          # a finger on the tablet also keeps the PC mouse out
            stats[0] += 1
        elif kind == b'K':
            act = payload[5:29].split(b'\0')[0].decode('utf-8', 'ignore')
            print('key', act, flush=True)
            send_keys(act)
        if time.time() - t0 > 30:
            print('packets ok=%d bad=%d' % tuple(stats), flush=True); t0 = time.time()


if __name__ == '__main__':
    main()

