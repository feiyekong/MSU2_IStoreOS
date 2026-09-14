#!/usr/bin/env python3
"""把页面渲染成放大 PNG 预览图（不需要 PIL，纯标准库）

用法：
  cd /mnt/mmc1-4/msu2d/src
  python3 ../tools/preview.py --out /tmp/preview --scale 4
"""
import argparse
import os
import struct
import sys
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from msu2 import canvas as C          # noqa: E402
from msu2 import pages                # noqa: E402
from msu2.metrics import Metrics      # noqa: E402


def write_png(path, w, h, rows):
    raw = b"".join(b"\x00" + bytes(r) for r in rows)

    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)


def rgb565_to_rgb888(v):
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return ((r * 255) // 31, (g * 255) // 63, (b * 255) // 31)


def save_canvas_png(cv, path, scale=4):
    w = cv.w * scale
    h = cv.h * scale
    rows = []
    for y in range(cv.h):
        row = bytearray()
        base = y * cv.w
        for x in range(cv.w):
            r, g, b = rgb565_to_rgb888(cv.px[base + x])
            row += bytes([r, g, b]) * scale
        for _ in range(scale):
            rows.append(row)
    write_png(path, w, h, rows)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="/tmp/preview")
    ap.add_argument("--scale", type=int, default=4)
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    m = Metrics()
    m.pick_wan()
    m.cpu_percent()
    hist = {"rx": [], "tx": [], "interval": 1.0}
    # 造一些历史数据，让曲线看得出效果
    for i in range(120):
        import math
        hist["rx"].append(200000 + 150000 * abs(math.sin(i / 9.0)))
        hist["tx"].append(40000 + 30000 * abs(math.sin(i / 5.0)))

    out = []
    cv = C.Canvas(160, 80)
    pages.render_net(cv, m, hist)
    out.append(save_canvas_png(cv, os.path.join(args.out, "page_net.png"), args.scale))

    cv = C.Canvas(160, 80)
    pages.render_sys(cv, m, hist)
    out.append(save_canvas_png(cv, os.path.join(args.out, "page_sys.png"), args.scale))

    cv = C.Canvas(160, 80)
    pages.render_clock(cv, m, hist)
    out.append(save_canvas_png(cv, os.path.join(args.out, "page_clock.png"), args.scale))

    for p in out:
        print(p, os.path.getsize(p), "字节")


if __name__ == "__main__":
    main()
