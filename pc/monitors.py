"""List the PC's monitors in physical pixels (the process must be per-monitor DPI aware first)."""
import ctypes
from ctypes import wintypes as wt


class MONITORINFOEXW(ctypes.Structure):
    _fields_ = [('cbSize', wt.DWORD), ('rcMonitor', wt.RECT), ('rcWork', wt.RECT), ('dwFlags', wt.DWORD),
                ('szDevice', wt.WCHAR * 32)]


def dpi_aware():
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception: pass


def monitors():
    """[(number, device, x, y, w, h, primary)], primary first, then left to right. Numbers start at 1."""
    user32 = ctypes.windll.user32
    found = []
    proc_t = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, ctypes.POINTER(wt.RECT), wt.LPARAM)

    def cb(hmon, hdc, rect, data):
        mi = MONITORINFOEXW(); mi.cbSize = ctypes.sizeof(MONITORINFOEXW)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        r = mi.rcMonitor
        found.append((mi.szDevice, r.left, r.top, r.right - r.left, r.bottom - r.top, bool(mi.dwFlags & 1)))
        return True

    user32.EnumDisplayMonitors(None, None, proc_t(cb), 0)
    found.sort(key=lambda m: (not m[5], m[1], m[2]))
    return [(i + 1,) + m for i, m in enumerate(found)]


def pick(which):
    """'primary', 'second' or a number -> (device, x, y, w, h)."""
    ms = monitors()
    if which in ('primary', '1') or not ms:
        m = ms[0]
    elif which == 'second':
        m = ms[1] if len(ms) > 1 else ms[0]
    else:
        n = int(which)
        if n > len(ms):
            raise SystemExit('monitor %d not found; this PC has %d (run with --list-monitors)' % (n, len(ms)))
        m = ms[n - 1]
    return m[1:6]


if __name__ == '__main__':
    dpi_aware()
    for m in monitors():
        print('%d  %s  %dx%d at %d,%d%s' % (m[0], m[1], m[4], m[5], m[2], m[3], '  (primary)' if m[6] else ''))
