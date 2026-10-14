"""Wireless Cintiq - PC side. Receives authenticated pen/key packets over UDP and injects a real Windows pen.

Packet (little endian), followed by an 8-byte truncated HMAC-SHA256 tag over the payload:
  'P' seq:u32 flags:u8 x:u16 y:u16 pressure:u16 tiltx:i8 tilty:i8
       flags: bit0 in-range, bit1 contact, bit2 barrel button, bit3 eraser
       x,y: 0..65535 across the mapped region; pressure 0..1023; tilt -90..90 degrees
  'T' seq:u32 down:u8 x:u16 y:u16                         one finger
  'M' seq:u32 n:u8 then n x (id:u8 x:u16 y:u16)           every finger that is down (none = all lifted)
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
      'less': 0xBC, 'greater': 0xBE, 'bracketleft': 0xDB, 'bracketright': 0xDD,
      'backspace': 0x08, 'tab': 0x09, 'delete': 0x2E, 'home': 0x24, 'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22,
      'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28}
EXTENDED = {0x2E, 0x24, 0x23, 0x21, 0x22, 0x25, 0x26, 0x27, 0x28}       # arrows & co. are "extended" keys, not keypad ones


def vk_for(name):
    n = name.lower()
    if n in VK: return VK[n], (n in ('greater', 'less'))
    if len(n) == 1 and n.isalnum(): return ord(n.upper()), False
    return None, False


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wt.WORD), ('wScan', wt.WORD), ('dwFlags', wt.DWORD), ('time', wt.DWORD), ('dwExtraInfo', ctypes.c_size_t)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wt.LONG), ('dy', wt.LONG), ('mouseData', wt.DWORD), ('dwFlags', wt.DWORD), ('time', wt.DWORD),
                ('dwExtraInfo', ctypes.c_size_t)]


class INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]
    _anonymous_ = ('u',)
    _fields_ = [('type', wt.DWORD), ('u', _U)]


def type_char(cp):
    """One character from the tablet keyboard. Letters and digits go as real keys (so app shortcuts work too),
    everything else (æ ø å, € ...) as Unicode, which doesn't depend on the PC's keyboard layout."""
    ch = chr(cp)
    if ch.isascii() and (ch.isalnum() or ch == ' '):
        return send_keys(('shift+' + ch.lower()) if ch.isupper() else ('space' if ch == ' ' else ch))
    units = [cp] if cp < 0x10000 else [0xD800 + ((cp - 0x10000) >> 10), 0xDC00 + ((cp - 0x10000) & 0x3FF)]
    ins = (INPUT * (2 * len(units)))()
    for i, u in enumerate(units):
        for j, up in enumerate((0, 2)):                                 # KEYEVENTF_UNICODE, then with KEYEVENTF_KEYUP
            k = ins[2 * i + j]; k.type = 1; k.ki.wScan = u; k.ki.dwFlags = 4 | up
    user32.SendInput(len(ins), ins, ctypes.sizeof(INPUT))
    return True


def toggle_osk():
    """Windows' on-screen keyboard: CreateProcess is refused for osk.exe (error 740), so open it through the shell and
    close it with a window message (taskkill is denied too)."""
    user32.FindWindowW.restype = ctypes.c_void_p
    user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_ssize_t]
    h = user32.FindWindowW('OSKMainClass', None)
    if h:
        user32.PostMessageW(h, 0x0112, 0xF060, 0)                   # WM_SYSCOMMAND, SC_CLOSE
    else:
        os.startfile('osk.exe')


def send_keys(action):
    """action like 'ctrl+shift+z' -> press/release with modifiers."""
    if action.lower() == 'osk':
        toggle_osk()
        return True
    if action.startswith('u:'):                                         # a typed character, as a hex code point
        return type_char(int(action[2:], 16))
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
        user32.keybd_event(vk, 0, 1 if vk in EXTENDED else 0, 0); down.append((vk, shifted))
    for vk, _ in reversed(down):
        user32.keybd_event(vk, 0, (1 if vk in EXTENDED else 0) | 2, 0)
    return True


class FocusWatch:
    """Where the PC's focused text box is (UI Automation, through focuswatch.exe), so the tablet keyboard can pop up
    by itself. Without it (build failed) the keyboard still works from the tablet's Menu key."""
    def __init__(self):
        self.edit = None                 # (left, top, right, bottom) of the focused text box, or None
        self.changed = 0                 # bumps on every change
        exe = self.build()
        if exe:
            self.p = subprocess.Popen([exe, str(os.getpid())], stdout=subprocess.PIPE, text=True, creationflags=0x08000000)
            import threading
            threading.Thread(target=self.read, daemon=True).start()

    @staticmethod
    def build():
        here = os.path.dirname(os.path.abspath(__file__))
        src, exe = os.path.join(here, 'focuswatch.cs'), os.path.join(here, 'focuswatch.exe')
        if os.path.exists(exe) and os.path.getmtime(exe) >= os.path.getmtime(src):
            return exe
        fw = os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Microsoft.NET', 'Framework64', 'v4.0.30319')
        refs = ['/r:' + os.path.join(fw, 'WPF', d) for d in ('UIAutomationClient.dll', 'UIAutomationTypes.dll', 'WindowsBase.dll')]
        try:
            r = subprocess.run([os.path.join(fw, 'csc.exe'), '/nologo', '/optimize', '/out:' + exe] + refs + [src],
                               capture_output=True, text=True)
        except OSError as e:
            print('auto keyboard off (no C# compiler: %s)' % e, flush=True); return None
        if r.returncode:
            print('auto keyboard off (focuswatch build failed):', r.stdout[-300:], flush=True); return None
        return exe

    def read(self):
        for ln in self.p.stdout:
            f = ln.split()
            self.edit = tuple(int(v) for v in f[1:5]) if len(f) == 5 and f[0] == '1' else None
            self.changed += 1


class Pen:
    def __init__(self, region):
        self.dev = user32.CreateSyntheticPointerDevice(PT_PEN, 1, POINTER_FEEDBACK_DEFAULT)
        if not self.dev:
            raise OSError('CreateSyntheticPointerDevice failed: %d' % ctypes.get_last_error())
        self.rx, self.ry, self.rw, self.rh = region
        self.in_range = False
        self.contact = False
        self.frame = 0
        self.barrel = False
        self.tool = None

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
        # eraser end: "inverted" while hovering, "inverted + eraser" while touching (what Windows Ink apps look for)
        pf = (PEN_INVERTED | (PEN_ERASER if contact else 0)) if eraser else 0
        pressure = min(1024, pressure)
        tool = 'eraser' if eraser else 'tip'
        if inrange and tool != self.tool:
            print('pen tool:', tool, flush=True); self.tool = tool
        want = barrel and inrange
        if want != self.barrel:
            # side button = right mouse button, like the Wacom driver (held = held, so right-drag works too);
            # the cursor is already where the pen is
            user32.mouse_event(0x0008 if want else 0x0010, 0, 0, 0, 0)            # RIGHTDOWN / RIGHTUP
            self.barrel = want
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
            TAP[:] = [time.monotonic(), x, y]
        elif contact:
            self.inject(F_UPDATE | F_INRANGE | F_INCONTACT | F_FIRST, pf, x, y, max(pressure, 1), tx, ty)
        elif self.contact:
            self.inject(F_UP | F_INRANGE, pf, x, y, 0, tx, ty); self.contact = False
        else:
            self.inject(F_UPDATE | F_INRANGE, pf, x, y, 0, tx, ty)


class Touch:
    """The tablet's fingers as real Windows touch contacts, up to 10 at once: tap = click, drag, pinch zoom,
    two-finger pan / rotate. Every frame names all fingers that are down, so a lost packet costs nothing."""
    MAX = 10

    def __init__(self, region):
        self.dev = user32.CreateSyntheticPointerDevice(PT_TOUCH, self.MAX, POINTER_FEEDBACK_DEFAULT)
        if not self.dev:
            raise OSError('CreateSyntheticPointerDevice(touch) failed: %d' % ctypes.get_last_error())
        self.rx, self.ry, self.rw, self.rh = region
        self.down = {}                 # finger id -> (x, y) screen pixels
        self.primary = None            # the gesture's first finger
        self.frame = 0; self.last = 0.0

    def inject(self, items):
        arr = (POINTER_TYPE_INFO * len(items))()
        self.frame += 1
        for pi, (pid, x, y, fl) in zip(arr, items):
            pi.type = PT_TOUCH
            t = pi.touchInfo
            t.pointerInfo.pointerType = PT_TOUCH; t.pointerInfo.pointerId = pid; t.pointerInfo.frameId = self.frame
            t.pointerInfo.pointerFlags = fl | (F_PRIMARY if pid == self.primary else 0)
            t.pointerInfo.ptPixelLocation.x = x; t.pointerInfo.ptPixelLocation.y = y
            t.touchMask = TOUCH_MASK_CONTACTAREA
            t.rcContact.left, t.rcContact.top, t.rcContact.right, t.rcContact.bottom = x - 4, y - 4, x + 4, y + 4
        if not user32.InjectSyntheticPointerInput(self.dev, arr, len(items)):
            print('touch inject failed', ctypes.get_last_error(), file=sys.stderr)
        self.last = time.monotonic()

    def update(self, contacts):
        """contacts: {finger id: (nx, ny)} for every finger down right now (0..65535 across the picture)."""
        now = {pid: (self.rx + int(nx / 65535.0 * (self.rw - 1)), self.ry + int(ny / 65535.0 * (self.rh - 1)))
               for pid, (nx, ny) in contacts.items() if pid < self.MAX}
        if now and not self.down:
            self.primary = min(now)
            TAP[:] = [time.monotonic()] + list(now[self.primary])
        items = [(pid, x, y, (F_UPDATE if pid in self.down else F_DOWN) | F_INRANGE | F_INCONTACT) for pid, (x, y) in now.items()]
        items += [(pid, x, y, F_UP) for pid, (x, y) in self.down.items() if pid not in now]
        if items:
            self.inject(items)
        self.down = now
        if not now:
            self.primary = None

    def keepalive(self):
        # Windows cancels a touch contact that stops reporting, so fingers resting still are re-sent
        if self.down and time.monotonic() - self.last > 0.05:
            self.inject([(pid, x, y, F_UPDATE | F_INRANGE | F_INCONTACT) for pid, (x, y) in self.down.items()])


PEN_UNTIL = [0.0]        # monotonic time until which the pen "owns" the cursor
TAP = [0.0, 0, 0]        # last pen or finger touch-down from the tablet: time, x, y (screen pixels)


class AutoKeyboard:
    """Pops the tablet's keyboard up when a tap from the tablet puts the PC's focus in a text box (or lands in the one
    that has it), and back down when the focus leaves text. The PC's own mouse and keyboard never trigger it."""
    def __init__(self, ctl, port):
        self.fw, self.ctl, self.to = FocusWatch(), ctl, ('127.0.0.1', port)
        self.seen, self.tap, self.shown = 0, 0.0, False

    def send(self, show, bottom=0):
        self.ctl.sendto(('kbd %d %d' % (show, bottom)).encode(), self.to)
        self.shown = bool(show)

    def check(self, region):
        rx, ry, rw, rh = region
        e, now = self.fw.edit, time.monotonic()
        inside = e and rx <= (e[0] + e[2]) // 2 < rx + rw and ry <= (e[1] + e[3]) // 2 < ry + rh
        bottom = max(0, min(65535, int((e[3] - ry) * 65535 / rh))) if inside else 0
        if self.fw.changed != self.seen:                      # the focus moved
            self.seen = self.fw.changed
            if inside and now - TAP[0] < 2.0:
                self.send(1, bottom)
            elif self.shown and not inside:
                self.send(0)
        if TAP[0] != self.tap and now - TAP[0] > 0.25:       # a tap that didn't move the focus: was it in the text box?
            self.tap = TAP[0]
            if inside and e[0] - 8 <= TAP[1] <= e[2] + 8 and e[1] - 8 <= TAP[2] <= e[3] + 8:
                self.send(1, bottom)


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


def other_monitor(mode):
    """The screen the tablet's Search key flips to: the main screen (mirror) <-> the extended one."""
    return 'second' if mode in ('primary', '1') else 'primary'


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
    ctl = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)          # tells wireless_cintiq.py to switch screens / keyboard
    kb = AutoKeyboard(ctl, a.port + 2)
    mode = a.monitor
    last = -1
    stats = [0, 0]
    t0 = time.time()
    s.settimeout(0.05)
    while True:
        try:
            kb.check((pen.rx, pen.ry, pen.rw, pen.rh))
        except OSError:
            pass
        try:
            data, addr = s.recvfrom(512)
        except socket.timeout:
            touch.keepalive(); continue
        if (a.allow != 'any' and addr[0] != a.allow) or len(data) < 6 + 8:   # 'any': the HMAC tag is the gate
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
        elif kind == b'T' and len(payload) >= 10:              # one finger (the Linux bridge)
            down, x, y = struct.unpack_from('<BHH', payload, 5)
            touch.update({0: (x, y)} if down & 1 else {})
            PEN_UNTIL[0] = time.monotonic() + a.hold          # a finger on the tablet also keeps the PC mouse out
            stats[0] += 1
        elif kind == b'M' and len(payload) >= 6:               # all fingers (the Android app)
            n = min(payload[5], (len(payload) - 6) // 5)
            touch.update({payload[6 + 5 * i]: struct.unpack_from('<HH', payload, 7 + 5 * i) for i in range(n)})
            PEN_UNTIL[0] = time.monotonic() + a.hold
            stats[0] += 1
        elif kind == b'K':
            act = payload[5:29].split(b'\0')[0].decode('utf-8', 'ignore')
            if not act.startswith('u:'):                       # typed text is never logged (passwords)
                print('key', act, flush=True)
            if act == 'screen':                                 # pen + touch follow; the streamer switches the picture
                mode = other_monitor(mode)
                pen.rx, pen.ry, pen.rw, pen.rh = touch.rx, touch.ry, touch.rw, touch.rh = region_for(mode)
                ctl.sendto(('screen ' + mode).encode(), ('127.0.0.1', a.port + 2))
                print('screen ->', mode, (pen.rx, pen.ry, pen.rw, pen.rh), flush=True)
            else:
                try:
                    send_keys(act)
                except Exception as e:                         # a key action must never take the pen down with it
                    print('key action failed: %r' % (e,), flush=True)
        if time.time() - t0 > 30:
            print('packets ok=%d bad=%d' % tuple(stats), flush=True); t0 = time.time()


if __name__ == '__main__':
    main()

