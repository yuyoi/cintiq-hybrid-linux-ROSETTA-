#!/usr/bin/env python3
"""Cintiq Companion Hybrid -> Linux. One-command installer (standard library only).

    python tools/install.py            install everything and boot Linux once (auto-returns to Android in ~4 min)
    python tools/install.py boot       boot the Linux desktop again
    python tools/install.py stay       Linux stays up until you power-cycle (no auto-return)
    python tools/install.py unstay     back to the safe 4-minute auto-return
    python tools/install.py restore    put your original recovery partition back
    options: --krita (also install Krita)  --yes (skip the confirmation)  --force (skip the model check)
"""
import argparse, hashlib, os, re, shutil, subprocess, sys, tempfile, time, urllib.request, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
WORK = os.path.join(REPO, 'work')
BACKUPS = os.path.join(REPO, 'backups')
SOS = '/dev/block/platform/sdhci-tegra.3/by-name/SOS'
BB_URL = 'https://busybox.net/downloads/binaries/1.31.0-defconfig-multiarch-musl/busybox-armv7l'
BB_SHA = 'cd04052b8b6885f75f50b2a280bfcbf849d8710c8e61d369c533acf307eda064'
ALPINE_BASE = 'https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/armv7/'
PACKAGES = ('python3 py3-xlib py3-pillow xvfb openbox tint2 feh xterm htop pcmanfm mousepad xdotool svkbd xrdb '
            'font-dejavu adwaita-icon-theme py3-xdg')
ADB = None


def say(msg=''):
    print(msg, flush=True)


def die(msg):
    say('\nERROR: ' + msg)
    sys.exit(1)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 20), b''):
            h.update(blk)
    return h.hexdigest()


def download(url, dest, sha=None):
    if os.path.exists(dest) and (sha is None or sha256(dest) == sha):
        return dest
    say('  downloading %s' % url)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, 'wb') as f:
        shutil.copyfileobj(r, f)
    if sha and sha256(dest) != sha:
        os.remove(dest)
        die('checksum mismatch for %s' % url)
    return dest


def find_adb():
    exe = 'adb.exe' if os.name == 'nt' else 'adb'
    p = shutil.which('adb')
    if p:
        return p
    local = os.path.join(WORK, 'platform-tools', exe)
    if not os.path.exists(local):
        plat = {'nt': 'windows', 'posix': 'linux'}.get(os.name, 'linux')
        if sys.platform == 'darwin':
            plat = 'darwin'
        say('adb not found - downloading Google platform-tools (%s)' % plat)
        z = download('https://dl.google.com/android/repository/platform-tools-latest-%s.zip' % plat,
                     os.path.join(WORK, 'platform-tools.zip'))
        zipfile.ZipFile(z).extractall(WORK)
    return local


def adb(*args, timeout=None, check=True):
    r = subprocess.run([ADB] + list(args), capture_output=True, timeout=timeout)
    out = (r.stdout + r.stderr).decode('utf-8', 'replace')
    if check and r.returncode not in (0, 255) and 'error:' in out.lower():
        die('adb %s failed:\n%s' % (' '.join(args), out))
    return out


def root(script, timeout=1800):
    """Run a shell script as root on the tablet. Returns its output; dies if it ends non-zero."""
    with tempfile.NamedTemporaryFile('w', suffix='.sh', delete=False, newline='\n') as t:
        t.write(script + '\necho __RC=$?\n')
    adb('push', t.name, '/data/local/tmp/ci_run.sh')
    os.unlink(t.name)
    out = adb('shell', 'su -c "sh /data/local/tmp/ci_run.sh"', timeout=timeout, check=False)
    m = re.search(r'__RC=(\d+)', out)
    if not m or m.group(1) != '0':
        die('a step failed on the tablet:\n%s' % out[-1500:])
    return out


def chroot(script, timeout=3600):
    """Run a shell script inside the Alpine chroot (pushed as a file: Android's root shell cannot do heredocs)."""
    with tempfile.NamedTemporaryFile('wb', suffix='.sh', delete=False) as t:
        t.write(script.replace('\r\n', '\n').encode())
    adb('push', t.name, '/data/local/tmp/ci_step.sh')
    os.unlink(t.name)
    return root('cp /data/local/tmp/ci_step.sh /data/local/alpine/tmp/ci_step.sh\n'
                '/data/local/bin/linux-start sh /tmp/ci_step.sh', timeout)


def push_text(local, remote):
    """Push a script with LF line endings, whatever git/Windows did to the checkout (CRLF breaks sh on the tablet)."""
    with tempfile.NamedTemporaryFile('wb', delete=False) as t:
        t.write(open(local, 'rb').read().replace(b'\r\n', b'\n'))
    adb('push', t.name, remote)
    os.unlink(t.name)


def wait_android(timeout=240):
    end = time.time() + timeout
    while time.time() < end:
        out = adb('devices', check=False)
        if '0123456789ABCDEF' in out:
            die('The tablet is in Linux mode. Choose START > "Return to Android" (or hold power ~10 s, then power on) and run again.')
        if re.search(r'\tdevice', out):
            if adb('shell', 'getprop sys.boot_completed', check=False).strip() == '1':
                return
        time.sleep(3)
    die('No tablet found on USB. Enable USB debugging, plug it in, accept the prompt on the tablet, then run again.')


def preflight(a):
    wait_android()
    model = adb('shell', 'getprop ro.product.model').strip()
    say('Device: %s' % model)
    if 'Cintiq Companion Hybrid' not in model and not a.force:
        die('This is for the Cintiq Companion Hybrid (DTH-A1300). Use --force only if you know what you are doing.')
    out = adb('shell', 'su -c id', check=False)
    if 'uid=0' not in out:
        die('Root is required (su did not return uid=0). See docs/ROOT.md. The Hybrid can be rooted with Towelroot.')
    say('Root: ok')


def confirm(a):
    if a.yes:
        return
    say('''
This will write ONE partition on your tablet: the recovery slot (SOS). Android is not touched, and your original
recovery is saved first so you can put it back with "restore". A normal power-on always boots Android.
Flashing partitions can brick a device; you do this at your own risk (see README, Risks and Recovery).
''')
    if input('Type YES to continue: ').strip() != 'YES':
        die('cancelled')


def flash(image):
    want = sha256(image)
    n = os.path.getsize(image)
    adb('push', image, '/sdcard/ci_sos.img')
    out = root('B=/data/local/bin/busybox\n'
               'S=%s\n$B dd if=/sdcard/ci_sos.img of=$S bs=4096 2>&1 | $B tail -n 1\n$B sync\n'
               'echo FLASHED=$($B dd if=$S bs=1 count=%d 2>/dev/null | $B sha256sum | $B cut -d" " -f1)\n'
           % (SOS, n))
    got = re.search(r'FLASHED=([0-9a-f]{64})', out)
    if not got or got.group(1) != want:
        die('verification FAILED (wrote %s, read back %s). Run "restore" before rebooting anything.' % (want, got and got.group(1)))
    say('  flashed and verified (sha256 %s...)' % want[:16])


def install(a):
    preflight(a)
    confirm(a)
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(BACKUPS, exist_ok=True)

    say('\n[1/7] Backing up your recovery (SOS), boot (LNX) and DTB partitions')
    for name, dev in (('SOS', 'mmcblk0p2'), ('LNX', 'mmcblk0p4'), ('DTB', 'mmcblk0p3')):
        dest = os.path.join(BACKUPS, name + '.img')
        if os.path.exists(dest):
            say('  %s.img already backed up' % name)
            continue
        root('dd if=/dev/block/%s of=/sdcard/ci_%s.img bs=1048576 && chmod 644 /sdcard/ci_%s.img' % (dev, name, name))
        adb('pull', '/sdcard/ci_%s.img' % name, dest)
        adb('shell', 'rm /sdcard/ci_%s.img' % name, check=False)
        say('  saved %s' % dest)

    say('\n[2/7] Downloading busybox and the Alpine Linux root filesystem')
    bb = download(BB_URL, os.path.join(WORK, 'busybox'), BB_SHA)
    yaml = urllib.request.urlopen(ALPINE_BASE + 'latest-releases.yaml', timeout=60).read().decode()
    m = re.search(r'file:\s*(alpine-minirootfs-[\d.]+-armv7\.tar\.gz).*?sha256:\s*([0-9a-f]{64})', yaml, re.S)
    if not m:
        die('could not read the Alpine release list')
    rootfs = download(ALPINE_BASE + m.group(1), os.path.join(WORK, m.group(1)), m.group(2))

    say('\n[3/7] Setting up Linux on the tablet')
    adb('push', bb, '/data/local/tmp/busybox')
    adb('push', rootfs, '/data/local/tmp/alpine.tar.gz')
    push_text(os.path.join(HERE, 'device', 'linux-start'), '/data/local/tmp/linux-start')
    root('mkdir -p /data/local/bin /data/local/alpine\n'
         'cp /data/local/tmp/busybox /data/local/bin/busybox && chmod 755 /data/local/bin/busybox\n'
         '/data/local/bin/busybox --install -s /data/local/bin\n'
         'cp /data/local/tmp/linux-start /data/local/bin/linux-start && chmod 755 /data/local/bin/linux-start\n'
         '[ -e /data/local/alpine/bin/busybox ] || /data/local/bin/busybox tar -xzf /data/local/tmp/alpine.tar.gz -C /data/local/alpine\n'
         'ls /data/local/alpine/bin/busybox')

    say('\n[4/7] Installing the desktop (needs the tablet on WiFi; a few minutes)')
    pk = PACKAGES + (' krita' if a.krita else '')
    out = chroot('apk update >/dev/null 2>&1; apk add --no-cache %s 2>&1 | tail -n 3; echo APK_DONE' % pk)
    if 'APK_DONE' not in out or 'ERROR' in out:
        die('package install failed (is the tablet connected to WiFi?):\n' + out[-800:])

    say('\n[5/7] Applying the Rosetta theme')
    push_text(os.path.join(REPO, 'theme', 'theme_install.sh'), '/data/local/tmp/theme_install.sh')
    out = root('cp /data/local/tmp/theme_install.sh /data/local/alpine/tmp/theme_install.sh\n'
               '/data/local/bin/linux-start sh /tmp/theme_install.sh')
    if 'THEME-INSTALLED' not in out:
        die('theme install failed:\n' + out[-800:])

    say('\n[6/7] Building and flashing the Linux boot image')
    ids = root('B=/data/local/bin/busybox; echo VID=$($B cat /sys/class/android_usb/android0/idVendor) '
               'PID=$($B cat /sys/class/android_usb/android0/idProduct)')
    mm = re.search(r'VID=([0-9a-fA-F]{4}) PID=([0-9a-fA-F]{4})', ids)
    vid, pid = (mm.group(1), mm.group(2)) if mm else ('0531', '2001')
    sys.path.insert(0, HERE)
    import build_sos
    img = build_sos.build(os.path.join(BACKUPS, 'SOS.img'), bb, os.path.join(WORK, 'sos_linux.img'), vid, pid)
    flash(img)
    root('rm -f /data/local/linux-stay.flag')

    say('\n[7/7] Booting Linux')
    boot_linux()
    say('''
Done. The tablet is booting the Linux desktop.
  - It returns to Android by itself after about 4 minutes (safe test mode).
  - To keep Linux up:   python tools/install.py stay
  - To leave Linux:     START menu > "Return to Android"  (or hold power ~10 s, then power on)
  - A normal power-on always boots Android.''')


def boot_linux():
    adb('reboot', 'recovery', check=False)


def main():
    global ADB
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', nargs='?', default='install', choices=['install', 'boot', 'stay', 'unstay', 'restore'])
    ap.add_argument('--krita', action='store_true')
    ap.add_argument('--yes', action='store_true')
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    ADB = find_adb()
    if a.cmd == 'install':
        install(a)
    elif a.cmd == 'boot':
        wait_android(); boot_linux(); say('Booting Linux.')
    elif a.cmd == 'stay':
        wait_android(); root('touch /data/local/linux-stay.flag'); say('Stay mode on: Linux will not auto-return. Run "boot".')
    elif a.cmd == 'unstay':
        wait_android(); root('rm -f /data/local/linux-stay.flag'); say('Stay mode off: auto-return after about 4 minutes.')
    elif a.cmd == 'restore':
        wait_android()
        p = os.path.join(BACKUPS, 'SOS.img')
        if not os.path.exists(p):
            die('no backup found at %s' % p)
        flash(p)
        say('Your original recovery partition is back.')


if __name__ == '__main__':
    main()
