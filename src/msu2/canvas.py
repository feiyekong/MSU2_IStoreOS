"""RGB565 帧缓冲 + 压缩编码（与 Windows 程序 Screen_Date_Process 完全一致）

编码格式（每 128 像素 = 256 字节为一页）：
  02 04 + 4字节底色       设置本页底色（打包两个相邻像素：高16位=偶数像素，低16位=奇数像素）
  04 k  + 4字节颜色       仅对与底色不同的第 k 项重新写入
  02 03 08 01 00 00       提交本页
"""
from collections import Counter

from . import font

# 常用颜色（RGB565）
BLACK = 0x0000
WHITE = 0xFFFF
RED = 0xF800
GREEN = 0x07E0
BLUE = 0x001F
YELLOW = 0xFFE0
CYAN = 0x07FF
MAGENTA = 0xF81F
ORANGE = 0xFD20
GRAY = 0x8410
DGRAY = 0x4208


def rgb(r, g, b):
    return ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | ((b & 0xF8) >> 3)


def di(v):
    """32 位值按大端拆成 4 字节"""
    return bytes([(v >> 24) & 255, (v >> 16) & 255, (v >> 8) & 255, v & 255])


class Canvas(object):
    def __init__(self, w=160, h=80):
        self.w = w
        self.h = h
        self.px = [0] * (w * h)

    # ---------- 绘图 ----------
    def clear(self, c=BLACK):
        self.px = [c] * (self.w * self.h)

    def pixel(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            self.px[y * self.w + x] = c

    def rect(self, x, y, w, h, c):
        x0 = max(0, x)
        y0 = max(0, y)
        x1 = min(self.w, x + w)
        y1 = min(self.h, y + h)
        for yy in range(y0, y1):
            base = yy * self.w
            for xx in range(x0, x1):
                self.px[base + xx] = c

    def frame_rect(self, x, y, w, h, c):
        self.rect(x, y, w, 1, c)
        self.rect(x, y + h - 1, w, 1, c)
        self.rect(x, y, 1, h, c)
        self.rect(x + w - 1, y, 1, h, c)

    def hline(self, x, y, w, c):
        self.rect(x, y, w, 1, c)

    def vline(self, x, y, h, c):
        self.rect(x, y, 1, h, c)

    # ---------- 文字 ----------
    def text_w(self, s, scale=1, spacing=1):
        if not s:
            return 0
        return len(s) * (font.GW * scale + spacing) - spacing

    def text(self, x, y, s, c, scale=1, spacing=1, bg=None):
        cx = x
        for ch in s:
            if ch == "\u00b0":
                g = font.get("C2")
            else:
                g = font.get(ch)
            for ry in range(font.GH):
                row = g[ry]
                for rx in range(font.GW):
                    if row[rx]:
                        if scale == 1:
                            self.pixel(cx + rx, y + ry, c)
                        else:
                            self.rect(cx + rx * scale, y + ry * scale, scale, scale, c)
                    elif bg is not None:
                        if scale == 1:
                            self.pixel(cx + rx, y + ry, bg)
                        else:
                            self.rect(cx + rx * scale, y + ry * scale, scale, scale, bg)
            cx += font.GW * scale + spacing
        return cx

    # ---------- 图形 ----------
    def bar(self, x, y, w, h, frac, fg, bg=DGRAY, border=None):
        frac = 0.0 if frac < 0 else (1.0 if frac > 1 else frac)
        self.rect(x, y, w, h, bg)
        fill = int(round(w * frac))
        if fill > 0:
            self.rect(x, y, fill, h, fg)
        if border is not None:
            self.frame_rect(x, y, w, h, border)

    def graph(self, x, y, w, h, values, vmax, color, bg=BLACK, grid=None):
        """柱状/折线图：values 为最近若干采样值"""
        self.rect(x, y, w, h, bg)
        if grid is not None:
            for gy in range(y, y + h, max(1, h // 2)):
                self.hline(x, gy, w, grid)
        if not values:
            return
        vals = values[-w:]
        vmax = max(vmax, 1e-9)
        n = len(vals)
        for i, v in enumerate(vals):
            bh = int(round((min(v, vmax) / vmax) * (h - 1)))
            if bh > 0:
                self.rect(x + i, y + h - bh, 1, bh, color)


    # ---------- 直线与图标 ----------
    def line(self, x0, y0, x1, y1, c, w=1):
        """Bresenham 直线（用于画图标斜线）"""
        dx = abs(x1 - x0)
        dy = -abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.rect(x0, y0, w, w, c)
            if x0 == x1 and y0 == y1:
                break
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    # 16x16 位图图标（逐像素设计，左右对称；'#' 为亮点）
    ICON_DOWN = (
        "................",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        "...##..##..##...",
        "....##.##.##....",
        ".....######.....",
        "......####......",
        ".......##.......",
        "................",
        ".##..........##.",
        ".##..........##.",
        ".##..........##.",
        ".##############.",
        "................",
    )
    ICON_UP = (
        "................",
        ".......##.......",
        ".....######.....",
        "....##.##.##....",
        "...##..##..##...",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        ".......##.......",
        "................",
        ".##..........##.",
        ".##..........##.",
        ".##..........##.",
        ".##############.",
        "................",
    )

    def _blit_bits(self, art, x, y, c, scale=1):
        for dy, row in enumerate(art):
            for dx, ch in enumerate(row):
                if ch == "#":
                    if scale == 1:
                        self.pixel(x + dx, y + dy, c)
                    else:
                        self.rect(x + dx * scale, y + dy * scale, scale, scale, c)

    def icon_download(self, x, y, s=16, c=WHITE):
        """下载图标：向下箭头 + 底部托盘"""
        self._blit_bits(self.ICON_DOWN, x, y, c)

    def icon_upload(self, x, y, s=16, c=WHITE):
        """上传图标：向上箭头 + 底部托盘"""
        self._blit_bits(self.ICON_UP, x, y, c)

    # ---------- 编码 ----------
    def encode(self):
        """按设备协议编码整帧（100 页）"""
        out = bytearray()
        px = self.px
        total = self.w * self.h
        for p in range(0, total, 128):
            page = px[p:p + 128]
            cmps = [(page[2 * k] << 16) | page[2 * k + 1] for k in range(64)]
            bg = Counter(cmps).most_common(1)[0][0]
            out += bytes((2, 4))
            out += di(bg)
            for k, v in enumerate(cmps):
                if v != bg:
                    out += bytes((4, k))
                    out += di(v)
            out += bytes((2, 3, 8, 1, 0, 0))
        return bytes(out)
