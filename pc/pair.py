"""Pair this PC with the tablet (once): makes the shared secret and writes the tablet's config over USB.

    python pc/pair.py [--remote your-home.duckdns.org]

Run it with the tablet plugged in and booted into Android (USB debugging on, rooted). It
  * creates pc/secret.txt (64 hex characters) if there is none - keep it private, it signs every pen/key packet;
  * writes /sdcard/rosetta/pc.conf for the Rosetta Screen app (Android, hardware-decoded wireless screen);
  * writes /root/pc.conf inside the tablet's Linux (PC mode of the Linux desktop).
--remote is your home address for using the app away from home (forward UDP 5600-5601 to this PC).
"""
import argparse, os, secrets, shutil, socket, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def adb_path():
    p = shutil.which('adb') or (r'C:\adb\adb.exe' if os.path.exists(r'C:\adb\adb.exe') else None)
    if not p:
        sys.exit('adb not found: install Android platform-tools and put adb on PATH')
    return p


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 9)); return s.getsockname()[0]
    finally:
        s.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--remote', default='', help='home address (DNS name or public IP) for use away from home')
    a = ap.parse_args()
    sp = os.path.join(HERE, 'secret.txt')
    if not os.path.exists(sp):
        open(sp, 'w').write(secrets.token_hex(32) + '\n')
        print('made a new shared secret in', sp)
    secret = open(sp).read().strip()
    ip = lan_ip()
    conf = 'host=%s\nport=5600\nvideo_port=5700\n%ssecret=%s\n' % (ip, ('remote=%s\n' % a.remote) if a.remote else '', secret)
    adb = adb_path()
    tmp = tempfile.NamedTemporaryFile('w', delete=False, suffix='.conf', newline='\n'); tmp.write(conf); tmp.close()
    try:
        subprocess.run([adb, 'shell', 'mkdir -p /sdcard/rosetta'], check=True)
        subprocess.run([adb, 'push', tmp.name, '/sdcard/rosetta/pc.conf'], check=True, stdout=subprocess.DEVNULL)
        subprocess.run([adb, 'shell', "su -c 'cp /sdcard/rosetta/pc.conf /data/local/alpine/root/pc.conf && "
                                       "chmod 600 /data/local/alpine/root/pc.conf'"], check=False)
    finally:
        os.unlink(tmp.name)
    print('paired: the tablet now talks to %s%s' % (ip, (' (and %s when away)' % a.remote) if a.remote else ''))
    print('next: start_rosetta_screen.bat here, then WIRELESS SCREEN on the tablet')


if __name__ == '__main__':
    main()
