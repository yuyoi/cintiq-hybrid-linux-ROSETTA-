# Watch the visible framebuffer page at (60, 60) and send a UDP note to the PC the moment it flips black <-> white.
import fcntl, mmap, os, socket, struct, sys, time
pc = (sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 5610)
secs = float(sys.argv[3]) if len(sys.argv) > 3 else 30
fd = os.open('/dev/graphics/fb0', os.O_RDONLY)
b = bytearray(160); fcntl.ioctl(fd, 0x4600, b); v = struct.unpack('<40I', bytes(b))
m = mmap.mmap(fd, v[2] * v[3] * 4, mmap.MAP_SHARED, mmap.PROT_READ)
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
last = None; end = time.time() + secs; n = 0
while time.time() < end:
    b2 = bytearray(160); fcntl.ioctl(fd, 0x4600, b2); yoff = struct.unpack_from('<I', b2, 20)[0]
    o = ((yoff + 60) * v[2] + 60) * 4
    lum = sum(m[o:o + 3]) > 380
    if last is not None and lum != last:
        s.sendto(b'flip', pc); n += 1
    last = lum
    time.sleep(0.002)
print('flips sent', n)
