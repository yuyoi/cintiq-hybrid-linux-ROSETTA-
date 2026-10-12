"""AES-256-CTR with Windows' own crypto (CNG / bcrypt.dll): no extra Python packages.

Counter block for block i of a packet = iv[:12] + i as a 32-bit big-endian number, which is exactly what Java's
"AES/CTR/NoPadding" does when its IV ends in four zero bytes (it counts the whole block up big-endian).
"""
import ctypes, struct
from ctypes import wintypes as wt

_bc = ctypes.WinDLL('bcrypt')
_bc.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(ctypes.c_void_p), wt.LPCWSTR, wt.LPCWSTR, wt.ULONG]
_bc.BCryptSetProperty.argtypes = [ctypes.c_void_p, wt.LPCWSTR, ctypes.c_void_p, wt.ULONG, wt.ULONG]
_bc.BCryptGenerateSymmetricKey.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p, wt.ULONG,
                                           ctypes.c_char_p, wt.ULONG, wt.ULONG]
_bc.BCryptEncrypt.argtypes = [ctypes.c_void_p, ctypes.c_char_p, wt.ULONG, ctypes.c_void_p, ctypes.c_void_p, wt.ULONG,
                              ctypes.c_char_p, wt.ULONG, ctypes.POINTER(wt.ULONG), wt.ULONG]


class AESCTR:
    def __init__(self, key):
        assert len(key) == 32
        self.alg = ctypes.c_void_p()
        if _bc.BCryptOpenAlgorithmProvider(ctypes.byref(self.alg), 'AES', None, 0):
            raise OSError('BCryptOpenAlgorithmProvider failed')
        mode = ctypes.create_unicode_buffer('ChainingModeECB')
        if _bc.BCryptSetProperty(self.alg, 'ChainingMode', mode, ctypes.sizeof(mode), 0):
            raise OSError('BCryptSetProperty failed')
        self.key = ctypes.c_void_p()
        if _bc.BCryptGenerateSymmetricKey(self.alg, ctypes.byref(self.key), None, 0, key, 32, 0):
            raise OSError('BCryptGenerateSymmetricKey failed')

    def keystream(self, iv12, nbytes):
        nblocks = (nbytes + 15) // 16
        ctr = b''.join(iv12 + struct.pack('>I', i) for i in range(nblocks))
        out = ctypes.create_string_buffer(len(ctr)); got = wt.ULONG()
        if _bc.BCryptEncrypt(self.key, ctr, len(ctr), None, None, 0, out, len(ctr), ctypes.byref(got), 0):
            raise OSError('BCryptEncrypt failed')
        return out.raw[:nbytes]

    def crypt(self, iv12, data):
        ks = self.keystream(iv12, len(data))
        return (int.from_bytes(data, 'little') ^ int.from_bytes(ks, 'little')).to_bytes(len(data), 'little')


if __name__ == '__main__':                     # known-answer test: NIST SP 800-38A F.5.5 (CTR-AES256)
    k = bytes.fromhex('603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4')
    iv = bytes.fromhex('f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff')
    pt = bytes.fromhex('6bc1bee22e409f96e93d7e117393172a')
    a = AESCTR(k)
    # the NIST counter does not start at 0, so check block 0 with its exact counter block via ECB
    ks = ctypes.create_string_buffer(16); got = wt.ULONG()
    _bc.BCryptEncrypt(a.key, iv, 16, None, None, 0, ks, 16, ctypes.byref(got), 0)
    ct = bytes(x ^ y for x, y in zip(pt, ks.raw))
    print('NIST CTR-AES256 block 1 ok:', ct.hex() == '601ec313775789a5b7a7f504bbf3d228')
