# -*- coding: utf-8 -*-
"""Convert BatFix --shot 24-bit BMP preview to PNG using only stdlib."""
import struct, zlib, binascii, sys, os

def chunk(t, p):
    return struct.pack('>I', len(p)) + t + p + struct.pack('>I', binascii.crc32(t + p) & 0xffffffff)

def convert(src, dst):
    d = open(src, 'rb').read()
    assert d[:2] == b'BM', 'not a BMP'
    off = struct.unpack_from('<I', d, 10)[0]
    w = struct.unpack_from('<i', d, 18)[0]
    h = struct.unpack_from('<i', d, 22)[0]
    bpp = struct.unpack_from('<H', d, 28)[0]
    comp = struct.unpack_from('<I', d, 30)[0]
    assert bpp == 24 and comp == 0, 'need uncompressed 24-bit BMP'
    topdown = h < 0
    h = abs(h)
    row = ((w * 3 + 3) // 4) * 4
    pix = d[off:off + row * h]
    raw = bytearray()
    for y in range(h):
        sy = y if topdown else (h - 1 - y)
        # BMP rows are padded to a 4-byte boundary; slice off the padding.
        line = pix[sy * row:sy * row + w * 3]
        rgb = bytearray(w * 3)
        rgb[0::3] = line[2::3]   # B -> R
        rgb[1::3] = line[1::3]   # G -> G
        rgb[2::3] = line[0::3]   # R -> B
        raw.append(0)            # filter: none
        raw += rgb
    png = b'\x89PNG\r\n\x1a\n'
    png += chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
    png += chunk(b'IDAT', zlib.compress(bytes(raw), 9))
    png += chunk(b'IEND', b'')
    open(dst, 'wb').write(png)
    print('%dx%d  %s (%d bytes)' % (w, h, dst, os.path.getsize(dst)))

if __name__ == '__main__':
    convert(sys.argv[1], sys.argv[2])
