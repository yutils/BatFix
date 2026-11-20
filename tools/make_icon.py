# -*- coding: utf-8 -*-
"""
Generate src/BatFix.ico (multi-size, PNG-in-ICO) and doc/BatFix_图标.png
using only the Python standard library.

Design: blue rounded tile + white terminal prompt ">_" + green check badge,
i.e. "a batch file, fixed". Vector-ish signed-distance drawing means every
size stays crisp instead of being a blurry downscale of one bitmap.

Run:  python tools/make_icon.py
"""
import os, math, struct, zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, 'src')
DOC = os.path.join(ROOT, 'doc')
os.makedirs(SRC, exist_ok=True)
os.makedirs(DOC, exist_ok=True)

TOP = (59, 130, 246)      # #3B82F6
BOTTOM = (29, 78, 216)    # #1D4ED8
WHITE = (255, 255, 255)
GREEN = (34, 197, 94)     # #22C55E


def sd_round_box(px, py, x0, y0, x1, y1, r):
    cx, cy = (x0 + x1) * .5, (y0 + y1) * .5
    qx = abs(px - cx) - ((x1 - x0) * .5 - r)
    qy = abs(py - cy) - ((y1 - y0) * .5 - r)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def sd_seg(px, py, ax, ay, bx, by):
    vx, vy = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    length = vx * vx + vy * vy
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / length)) if length else 0.0
    return math.hypot(wx - t * vx, wy - t * vy)


def sd_circle(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) - r


def cov(d, aa):
    v = 0.5 - d / aa
    return 0.0 if v < 0 else (1.0 if v > 1 else v)


def mix(c1, c2, a):
    return tuple(int(round(c1[i] * (1 - a) + c2[i] * a)) for i in range(3))


def render(size):
    rows = []
    aa = 1.0 / size
    for j in range(size):
        y = (j + .5) / size
        row = []
        for i in range(size):
            x = (i + .5) / size
            a_bg = cov(sd_round_box(x, y, .02, .02, .98, .98, .22), aa)
            if a_bg <= 0:
                row.append((0, 0, 0, 0))
                continue
            t = max(0.0, min(1.0, (y - .02) / .96))
            col = tuple(int(round(TOP[k] * (1 - t) + BOTTOM[k] * t)) for k in range(3))
            w = .043
            d_prompt = min(
                sd_seg(x, y, .26, .30, .48, .50) - w,
                sd_seg(x, y, .48, .50, .26, .70) - w,
                sd_seg(x, y, .55, .70, .77, .70) - w)
            col = mix(col, WHITE, cov(d_prompt, aa))
            if size >= 32:                       # badge would be mud at 16px
                col = mix(col, WHITE, cov(sd_circle(x, y, .76, .26, .172), aa))
                col = mix(col, GREEN, cov(sd_circle(x, y, .76, .26, .150), aa))
                tw = .018
                d_tick = min(
                    sd_seg(x, y, .695, .265, .745, .315) - tw,
                    sd_seg(x, y, .745, .315, .825, .205) - tw)
                col = mix(col, WHITE, cov(d_tick, aa))
            row.append((col[0], col[1], col[2], int(round(a_bg * 255))))
        rows.append(row)
    return rows


def chunk(tag, payload):
    return (struct.pack('>I', len(payload)) + tag + payload +
            struct.pack('>I', zlib.crc32(tag + payload) & 0xffffffff))


def to_png(rows):
    size = len(rows)
    raw = bytearray()
    for row in rows:
        raw.append(0)                            # filter: none
        for r, g, b, a in row:
            raw += bytes((r, g, b, a))
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(bytes(raw), 9)) +
            chunk(b'IEND', b''))


def to_ico(images):
    n = len(images)
    head = struct.pack('<HHH', 0, 1, n)
    entries = bytearray()
    body = bytearray()
    offset = 6 + 16 * n
    for size, data in images:
        wb = 0 if size >= 256 else size
        entries += struct.pack('<BBBBHHII', wb, wb, 0, 0, 1, 32, len(data), offset)
        body += data
        offset += len(data)
    return head + bytes(entries) + bytes(body)


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = []
    for s in sizes:
        rows = render(s)
        images.append((s, to_png(rows)))
        if s == 256:
            with open(os.path.join(DOC, 'BatFix_图标.png'), 'wb') as f:
                f.write(to_png(rows))
    with open(os.path.join(SRC, 'BatFix.ico'), 'wb') as f:
        f.write(to_ico(images))
    print('generated src/BatFix.ico with sizes: %s' % sizes)
    print('preview: doc/BatFix_图标.png (256x256)')


if __name__ == '__main__':
    main()
