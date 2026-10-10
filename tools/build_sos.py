#!/usr/bin/env python3
"""Build the Linux-mode recovery image from YOUR OWN stock recovery (SOS) dump.

Nothing from Wacom/NVIDIA ships in this repo: the kernel is copied out of your own dump, and only the ramdisk is
replaced (init.rc, a busybox, our boot scripts). Header, kernel and load addresses stay byte-identical.

    python build_sos.py --sos backups/SOS.img --busybox work/busybox --out work/sos_linux.img --vid 0531 --pid 2001
"""
import argparse, gzip, hashlib, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
BOOT = os.path.join(HERE, 'boot')


def parse_newc(raw):
    i, files = 0, []
    while True:
        h = raw[i:i + 110]
        if h[:6] != b'070701':
            raise SystemExit('not a newc cpio ramdisk (is this really a stock SOS dump?)')
        f = [int(h[6 + 8 * k:14 + 8 * k], 16) for k in range(13)]
        mode, fs, nsz = f[1], f[6], f[11]
        name = raw[i + 110:i + 110 + nsz - 1].decode()
        ds = (i + 110 + nsz + 3) & ~3
        data = raw[ds:ds + fs]
        i = (ds + fs + 3) & ~3
        if name == 'TRAILER!!!':
            return files
        files.append([name, mode, data])


def build_newc(files):
    out = bytearray()
    for ino, (name, mode, data) in enumerate(files + [['TRAILER!!!', 0, b'']], 1):
        nm = name.encode() + b'\0'
        nl = 2 if (mode & 0o170000) == 0o040000 else 1
        out += b'070701' + b''.join(b'%08X' % v for v in (ino, mode, 0, 0, nl, 0, len(data), 0, 0, 0, 0, len(nm), 0)) + nm
        out += b'\0' * (-len(out) % 4)
        out += data
        out += b'\0' * (-len(out) % 4)
    return bytes(out)


INIT_RC = """on early-init
    start ueventd

on init
    export PATH /sbin:/system/bin:/system/xbin
    export ANDROID_ROOT /system
    export ANDROID_DATA /data
    export EXTERNAL_STORAGE /sdcard

    symlink /system/etc /etc

    mkdir /sdcard
    mkdir /system
    mkdir /data
    mkdir /cache
    mkdir /misc
    mkdir /cdrom
    mkdir /fallback
    mkdir /udisk
    mount /tmp /tmp tmpfs

on boot
    ifup lo
    hostname localhost
    domainname localdomain
    start wdog
    start linux

service ueventd /sbin/ueventd
    critical

service linux /sbin/busybox sh /sbin/linux-boot.sh
    oneshot

service wdog /sbin/busybox sh /sbin/wdog.sh
    oneshot

service recovery /sbin/recovery
    disabled
"""


def build(sos, busybox, out, vid, pid):
    img = open(sos, 'rb').read()
    if img[:8] != b'ANDROID!':
        raise SystemExit('%s is not an Android boot image' % sos)
    ks, ka, rs, ra, ss, sa, ta, ps = struct.unpack('<8I', img[8:40])
    kernel = img[ps:ps + ks]
    roff = ps + ((ks + ps - 1) // ps) * ps
    files = parse_newc(gzip.decompress(img[roff:roff + rs]))
    byname = {f[0]: f for f in files}
    for need in ('init', 'sbin/adbd', 'sbin/ueventd', 'init.rc', 'default.prop'):
        if need not in byname:
            raise SystemExit('stock ramdisk lacks %s, so this is not the expected SOS layout' % need)

    prop = byname['default.prop'][2].decode()
    prop = prop.replace('ro.secure=1', 'ro.secure=0').replace('ro.debuggable=0', 'ro.debuggable=1')
    prop = prop.replace('persist.sys.usb.config=mtp', 'persist.sys.usb.config=adb')
    byname['default.prop'][2] = prop.encode()
    byname['init.rc'][2] = INIT_RC.encode()
    byname['sbin'][1] = 0o040755          # stock is 0750; adb's shell user must be able to reach /sbin

    files = [f for f in files if f[0] not in ('sbin/busybox', 'sbin/linux-boot.sh', 'sbin/wdog.sh', 'system/bin/sh')]
    files.append(['sbin/busybox', 0o100755, open(busybox, 'rb').read()])
    boot = open(os.path.join(BOOT, 'linux-boot.sh'), 'rb').read().replace(b'\r\n', b'\n')
    boot = boot.replace(b'@VID@', vid.encode()).replace(b'@PID@', pid.encode())
    files.append(['sbin/linux-boot.sh', 0o100755, boot])
    files.append(['sbin/wdog.sh', 0o100755, open(os.path.join(BOOT, 'wdog.sh'), 'rb').read().replace(b'\r\n', b'\n')])
    if 'system/bin' not in byname:
        files.append(['system/bin', 0o040755, b''])
    files.append(['system/bin/sh', 0o120777, b'/sbin/busybox'])

    rd = gzip.compress(build_newc(files), 9, mtime=0)
    hdr = bytearray(img[:ps])
    struct.pack_into('<I', hdr, 16, len(rd))
    sha = hashlib.sha1()
    for blob in (kernel, rd, b''):
        sha.update(blob)
        sha.update(struct.pack('<I', len(blob)))
    hdr[576:576 + 20] = sha.digest()
    hdr[576 + 20:576 + 32] = b'\0' * 12
    pad = lambda b: b + b'\0' * (-len(b) % ps)
    res = bytes(hdr) + pad(kernel) + pad(rd)
    if len(res) > 8 * 1024 * 1024:
        raise SystemExit('image is %d bytes; the SOS partition holds 8 MiB' % len(res))
    open(out, 'wb').write(res)
    chk = open(out, 'rb').read()
    assert chk[:8] == b'ANDROID!' and chk[ps:ps + ks] == kernel
    print('built %s: %d bytes, kernel identical, sha256 %s' % (out, len(res), hashlib.sha256(res).hexdigest()))
    return out


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--sos', required=True)
    ap.add_argument('--busybox', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--vid', default='0531')
    ap.add_argument('--pid', default='2001')
    a = ap.parse_args()
    build(a.sos, a.busybox, a.out, a.vid, a.pid)
