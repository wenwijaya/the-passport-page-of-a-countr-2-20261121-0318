# The Passport Page of a Country That Isn't There.
# A program that draws one invented passport spread to /output/entry.png.
# Python 3.13 stdlib only. No network, no file reads, no clocks, no
# randomness: two runs produce identical bytes.
#
# The country: the Republic of Veldoria, a small tidal-harbour republic.
# The holder: Mara Elisabeth Voss, born 17 Apr 1996 in Port Meridian.
# Passport issued 14 Mar 2024, expires 13 Mar 2034. Every stamp falls
# inside that window and tells one trip after another; the telling
# paperwork detail is the tide table: Veldoria can only be entered by
# ferry, within two hours of high water.
import math
import os
import struct
import zlib

SCALE = 2          # supersampling factor: work buffer is 2048x2048
W, H = 1024 * SCALE, 1024 * SCALE
OUT_W, OUT_H = 1024, 1024


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def blend(a, b, t):
    """Blend colour b over a by t (0..1). Colours are (r, g, b)."""
    return (round(a[0] + (b[0] - a[0]) * t),
            round(a[1] + (b[1] - a[1]) * t),
            round(a[2] + (b[2] - a[2]) * t))


class Canvas:
    """An RGB canvas with a per-pixel alpha mask (0 = transparent)."""

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = bytearray(w * h * 3)
        self.al = bytearray(w * h)

    def fill(self, colour):
        r, g, b = colour
        self.px[:] = bytes((r, g, b)) * (self.w * self.h)
        self.al[:] = b"\xff" * (self.w * self.h)

    def plot(self, x, y, colour, alpha=255):
        x, y = int(round(x)), int(round(y))
        if x < 0 or y < 0 or x >= self.w or y >= self.h:
            return
        i = (y * self.w + x) * 3
        a = alpha / 255.0
        if a >= 1.0:
            self.px[i], self.px[i + 1], self.px[i + 2] = colour
            self.al[y * self.w + x] = 255
        elif a > 0.0:
            o = (self.px[i], self.px[i + 1], self.px[i + 2])
            c = blend(o, colour, a)
            self.px[i], self.px[i + 1], self.px[i + 2] = c
            old = self.al[y * self.w + x]
            self.al[y * self.w + x] = min(255, old + alpha)

    def disc(self, cx, cy, r, colour, alpha=255):
        r = int(round(r))
        if r <= 0:
            self.plot(int(round(cx)), int(round(cy)), colour, alpha)
            return
        for dy in range(-r, r + 1):
            dx = int(math.sqrt(r * r - dy * dy))
            for x in range(cx - dx, cx + dx + 1):
                self.plot(x, cy + dy, colour, alpha)

    def hline(self, x0, x1, y, colour, alpha=255):
        x0, x1, y = int(round(x0)), int(round(x1)), int(round(y))
        if y < 0 or y >= self.h:
            return
        x0, x1 = max(0, x0), min(self.w - 1, x1)
        if x0 > x1:
            return
        i = (y * self.w + x0) * 3
        n = x1 - x0 + 1
        if alpha >= 255:
            self.px[i:i + n * 3] = bytes(colour) * n
            self.al[y * self.w + x0:y * self.w + x1 + 1] = b"\xff" * n
        else:
            for x in range(x0, x1 + 1):
                self.plot(x, y, colour, alpha)

    def rect(self, x0, y0, x1, y1, colour, alpha=255):
        x0, y0 = int(round(x0)), int(round(y0))
        x1, y1 = int(round(x1)), int(round(y1))
        for y in range(max(0, y0), min(self.h, y1 + 1)):
            self.hline(x0, x1, y, colour, alpha)

    def line(self, x0, y0, x1, y1, colour, width=1.0, alpha=255):
        """A thick line: stamps discs along the Bresenham path."""
        x0, y0, x1, y1 = int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1))
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        r = max(0.5, width / 2.0)
        x, y = x0, y0
        while True:
            self.disc(x, y, r, colour, alpha)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def polyline(self, pts, colour, width=1.0, alpha=255, closed=False):
        ps = list(pts)
        if closed and len(ps) > 1:
            ps = ps + [ps[0]]
        for a, b in zip(ps, ps[1:]):
            self.line(a[0], a[1], b[0], b[1], colour, width, alpha)

    def circle(self, cx, cy, r, colour, width=1.0, alpha=255):
        steps = max(24, int(2 * math.pi * r / 3))
        pts = []
        for i in range(steps + 1):
            t = 2 * math.pi * i / steps
            pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
        self.polyline(pts, colour, width, alpha)

    def fill_circle(self, cx, cy, r, colour, alpha=255):
        r = int(round(r))
        for dy in range(-r, r + 1):
            dx = int(math.sqrt(r * r - dy * dy))
            self.hline(cx - dx, cx + dx, cy + dy, colour, alpha)

    def fill_poly(self, pts, colour, alpha=255):
        """Scanline polygon fill (pts: list of (x, y))."""
        if len(pts) < 3:
            return
        ys = [p[1] for p in pts]
        y0, y1 = int(math.ceil(min(ys))), int(math.floor(max(ys)))
        n = len(pts)
        for y in range(max(0, y0), min(self.h - 1, y1) + 1):
            xs = []
            for i in range(n):
                x0, yy0 = pts[i]
                x1, yy1 = pts[(i + 1) % n]
                if (yy0 <= y < yy1) or (yy1 <= y < yy0):
                    t = (y - yy0) / (yy1 - yy0) if yy1 != yy0 else 0.0
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for a, b in zip(xs[0::2], xs[1::2]):
                self.hline(int(math.ceil(a)), int(math.floor(b)), y, colour, alpha)

    def ellipse(self, cx, cy, rx, ry, colour, alpha=255):
        steps = max(24, int(2 * math.pi * max(rx, ry) / 3))
        pts = []
        for i in range(steps + 1):
            t = 2 * math.pi * i / steps
            pts.append((cx + rx * math.cos(t), cy + ry * math.sin(t)))
        self.fill_poly(pts, colour, alpha)

    def blit(self, src, dx, dy, alpha=255):
        """Blit src canvas onto this one at offset (dx, dy)."""
        for sy in range(src.h):
            ty = dy + sy
            if ty < 0 or ty >= self.h:
                continue
            for sx in range(src.w):
                sa = src.al[sy * src.w + sx]
                if sa == 0:
                    continue
                tx = dx + sx
                if tx < 0 or tx >= self.w:
                    continue
                a = (sa / 255.0) * (alpha / 255.0)
                i = (ty * self.w + tx) * 3
                j = (sy * src.w + sx) * 3
                o = (self.px[i], self.px[i + 1], self.px[i + 2])
                c = blend(o, (src.px[j], src.px[j + 1], src.px[j + 2]), a)
                self.px[i], self.px[i + 1], self.px[i + 2] = c

    def rotated(self, deg):
        """A new canvas holding this one rotated by deg (nearest neighbour)."""
        th = math.radians(deg)
        c, s = math.cos(th), math.sin(th)
        nw = int(abs(self.w * c) + abs(self.h * s)) + 2
        nh = int(abs(self.w * s) + abs(self.h * c)) + 2
        out = Canvas(nw, nh)
        cx0, cy0 = self.w / 2.0, self.h / 2.0
        cx1, cy1 = nw / 2.0, nh / 2.0
        for y in range(nh):
            for x in range(nw):
                rx = (x - cx1) * c + (y - cy1) * s + cx0
                ry = -(x - cx1) * s + (y - cy1) * c + cy0
                ix, iy = int(round(rx)), int(round(ry))
                if 0 <= ix < self.w and 0 <= iy < self.h:
                    sa = self.al[iy * self.w + ix]
                    if sa:
                        j = (iy * self.w + ix) * 3
                        i = (y * nw + x) * 3
                        out.px[i], out.px[i + 1], out.px[i + 2] = (
                            self.px[j], self.px[j + 1], self.px[j + 2])
                        out.al[y * nw + x] = sa
        return out


def downsample(src):
    """Average each 2x2 block of the 2048 buffer into one 1024 pixel."""
    out = bytearray(OUT_W * OUT_H * 3)
    sw = src.w
    for y in range(OUT_H):
        for x in range(OUT_W):
            i0 = ((2 * y) * sw + 2 * x) * 3
            i1 = i0 + 3
            i2 = ((2 * y + 1) * sw + 2 * x) * 3
            i3 = i2 + 3
            o = (y * OUT_W + x) * 3
            for k in range(3):
                out[o + k] = (src.px[i0 + k] + src.px[i1 + k] +
                              src.px[i2 + k] + src.px[i3 + k]) // 4
    return bytes(out)


def write_png(path, rgb, w, h):
    raw = b"".join(b"\x00" + rgb[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(png)
    return len(png)

# ---------------------------------------------------------------- font
# A single-stroke geometric lettering drawn as polylines on a 5-wide by
# 9-tall grid (y = 0 top, y = 9 baseline). One coherent face for the
# whole document: headings, data, stamps and the machine-readable strip.
FONT = {
    "A": [[(0, 9), (2.5, 0), (5, 9)], [(1.3, 5.5), (3.7, 5.5)]],
    "B": [[(0, 9), (0, 0)], [(0, 0), (3, 0), (4.5, 1.5), (3, 4.5), (0, 4.5)],
          [(0, 4.5), (3, 4.5), (4.5, 6), (4.5, 7.5), (3, 9), (0, 9)]],
    "C": [[(5, 1.5), (4, 0), (1, 0), (0, 1.5), (0, 7.5), (1, 9), (4, 9), (5, 7.5)]],
    "D": [[(0, 9), (0, 0)], [(0, 0), (3, 0), (5, 2), (5, 7), (3, 9), (0, 9)]],
    "E": [[(0, 9), (0, 0), (5, 0)], [(0, 4.5), (4, 4.5)], [(0, 9), (5, 9)]],
    "F": [[(0, 9), (0, 0), (5, 0)], [(0, 4.5), (4, 4.5)]],
    "G": [[(5, 1.5), (4, 0), (1, 0), (0, 1.5), (0, 7.5), (1, 9), (4, 9),
           (5, 7.5), (5, 4.5), (3, 4.5)]],
    "H": [[(0, 9), (0, 0)], [(5, 9), (5, 0)], [(0, 4.5), (5, 4.5)]],
    "I": [[(1, 0), (4, 0)], [(2.5, 0), (2.5, 9)], [(1, 9), (4, 9)]],
    "J": [[(1, 0), (4, 0)], [(3.5, 0), (3.5, 7), (2.5, 9), (0.5, 9), (0, 7.5)]],
    "K": [[(0, 9), (0, 0)], [(4.5, 0), (0, 4.5)], [(1.5, 3.5), (4.5, 9)]],
    "L": [[(0, 9), (0, 0)], [(0, 9), (5, 9)]],
    "M": [[(0, 9), (0, 0)], [(0, 0), (2.5, 4.5), (5, 0)], [(5, 9), (5, 0)]],
    "N": [[(0, 9), (0, 0)], [(0, 0), (5, 9)], [(5, 9), (5, 0)]],
    "O": [[(1, 0), (4, 0), (5, 1.5), (5, 7.5), (4, 9), (1, 9), (0, 7.5), (0, 1.5), (1, 0)]],
    "P": [[(0, 9), (0, 0)], [(0, 0), (3.5, 0), (5, 1.5), (5, 3), (3.5, 4.5), (0, 4.5)]],
    "Q": [[(1, 0), (4, 0), (5, 1.5), (5, 7.5), (4, 9), (1, 9), (0, 7.5), (0, 1.5), (1, 0)],
          [(3.5, 6.5), (5, 9)]],
    "R": [[(0, 9), (0, 0)], [(0, 0), (3.5, 0), (5, 1.5), (5, 3), (3.5, 4.5), (0, 4.5)],
          [(2.5, 4.5), (5, 9)]],
    "S": [[(4.5, 1), (3.5, 0), (1.5, 0), (0.5, 1), (0.5, 3), (2.5, 4.5), (4.5, 4.5),
           (5, 6), (5, 7.5), (4, 9), (1.5, 9), (0.5, 8)]],
    "T": [[(0, 0), (5, 0)], [(2.5, 0), (2.5, 9)]],
    "U": [[(0, 0), (0, 7), (1, 9), (4, 9), (5, 7), (5, 0)]],
    "V": [[(0, 0), (2.5, 9), (5, 0)]],
    "W": [[(0, 0), (1.2, 9), (2.5, 4), (3.8, 9), (5, 0)]],
    "X": [[(0, 0), (5, 9)], [(5, 0), (0, 9)]],
    "Y": [[(0, 0), (2.5, 4.5), (5, 0)], [(2.5, 4.5), (2.5, 9)]],
    "Z": [[(0, 0), (5, 0), (0, 9), (5, 9)]],
    "0": [[(1, 0), (4, 0), (5, 1.5), (5, 7.5), (4, 9), (1, 9), (0, 7.5), (0, 1.5), (1, 0)],
          [(4.5, 1), (0.5, 8)]],
    "1": [[(1, 0), (2.5, 0)], [(2.5, 0), (2.5, 9)], [(1, 9), (4, 9)]],
    "2": [[(0.5, 2), (1.5, 0), (3.5, 0), (5, 1.5), (5, 4), (0, 9), (5, 9)]],
    "3": [[(0.5, 1), (1.5, 0), (3.5, 0), (4.5, 1), (4.5, 3), (3, 4.5)],
          [(3, 4.5), (4.5, 6), (4.5, 8), (3.5, 9), (1.5, 9), (0.5, 8)]],
    "4": [[(0, 6), (3.5, 0), (3.5, 9)], [(0, 6), (5, 6)]],
    "5": [[(5, 0), (0, 0), (0, 4.5), (3.5, 4.5), (5, 6), (5, 7.5), (4, 9), (1, 9), (0, 8)]],
    "6": [[(4.5, 0.5), (3, 0), (1, 0), (0, 1.5), (0, 7.5), (1, 9), (4, 9),
           (5, 7.5), (5, 5), (4, 4.5), (1, 4.5), (0, 5.5)]],
    "7": [[(0, 0), (5, 0), (2.5, 9)]],
    "8": [[(1.5, 0), (3.5, 0), (4.5, 1), (4.5, 3), (3.5, 4.5), (1.5, 4.5),
           (0.5, 3), (0.5, 1), (1.5, 0)],
          [(1.5, 4.5), (3.5, 4.5), (4.5, 6), (4.5, 8), (3.5, 9), (1.5, 9),
           (0.5, 8), (0.5, 6), (1.5, 4.5)]],
    "9": [[(0.5, 8.5), (2, 9), (4, 9), (5, 7.5), (5, 1.5), (4, 0), (1, 0),
           (0, 1.5), (0, 4), (1, 4.5), (4, 4.5), (5, 3.5)]],
    ".": [[(2, 8), (3, 8), (3, 9), (2, 9), (2, 8)]],
    ",": [[(2.5, 8), (2.5, 9), (1.5, 10.5)]],
    "-": [[(0.5, 4.5), (4.5, 4.5)]],
    "/": [[(0.5, 9), (4.5, 0)]],
    ":": [[(2, 2.5), (3, 2.5), (3, 3.5), (2, 3.5), (2, 2.5)],
          [(2, 6.5), (3, 6.5), (3, 7.5), (2, 7.5), (2, 6.5)]],
    "(": [[(4, 0), (2.5, 1.5), (2.5, 7.5), (4, 9)]],
    ")": [[(1, 0), (2.5, 1.5), (2.5, 7.5), (1, 9)]],
    "'": [[(3, 0), (2.5, 2)]],
    '"': [[(1.5, 0), (1, 2)], [(3.5, 0), (3, 2)]],
    "<": [[(4.5, 0), (0.5, 4.5), (4.5, 9)]],
    ">": [[(0.5, 0), (4.5, 4.5), (0.5, 9)]],
    "&": [[(4, 1), (3, 0), (1, 0), (0, 1.5), (0, 3), (2, 4.5), (4.5, 4.5), (5, 6),
           (4, 9), (2, 9), (1, 8), (2.5, 6.5), (5, 2)]],
    "+": [[(2.5, 1.5), (2.5, 7.5)], [(0.5, 4.5), (4.5, 4.5)]],
    "=": [[(0.5, 3), (4.5, 3)], [(0.5, 6), (4.5, 6)]],
    "!": [[(2.5, 0), (2.5, 6)], [(2, 7.5), (3, 7.5), (3, 8.5), (2, 8.5), (2, 7.5)]],
    "?": [[(1, 1), (2, 0), (4, 0), (5, 1), (5, 3), (3, 4.5), (2.5, 5.5), (2.5, 6.5)],
          [(2, 7.5), (3, 7.5), (3, 8.5), (2, 8.5), (2, 7.5)]],
    "*": [[(2.5, 1), (2.5, 8)], [(0.5, 3), (4.5, 6)], [(4.5, 3), (0.5, 6)]],
    " ": [],
}

ADVANCE = 6.0   # font units per character
LINE_H = 11.0   # font units per line


def text_width(s, scale):
    return len(s) * ADVANCE * scale


def draw_text(cv, x, y, s, string, colour, alpha=255, align="left",
              tracking=0.0, width=None):
    """Draw string with its top at y. scale s = buffer px per font unit.
    width overrides stroke width (default ~0.13 of cap height)."""
    wdt = width if width is not None else max(1.0, s * 1.15)
    total = text_width(string, s) + tracking * max(0, len(string) - 1)
    if align == "center":
        x -= total / 2.0
    elif align == "right":
        x -= total
    cx = x
    for ch in string:
        glyph = FONT.get(ch.upper(), FONT.get("?", []))
        for stroke in glyph:
            pts = [(cx + px * s, y + py * s) for px, py in stroke]
            cv.polyline(pts, colour, wdt, alpha)
        cx += ADVANCE * s + tracking
    return total


# ---------------------------------------------------------------- helpers
def star_points(cx, cy, r_out, r_in, n=5, rot=-math.pi / 2):
    pts = []
    for i in range(2 * n):
        r = r_out if i % 2 == 0 else r_in
        t = rot + i * math.pi / n
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts


def guilloche(cv, x0, y0, x1, y1, colour, alpha=26, amp=3.0, waves=9.0, step=2.0):
    """Faint wavy security lines across a rectangle."""
    h = y1 - y0
    rows = int(h / 14)
    for r in range(rows + 1):
        yc = y0 + r * 14
        pts = []
        x = x0
        while x <= x1:
            t = (x - x0) / max(1, (x1 - x0))
            pts.append((x, yc + amp * math.sin(2 * math.pi * waves * t + r * 0.9)))
            x += step
        cv.polyline(pts, colour, 1.0, alpha)


def speckle(cv, x0, y0, x1, y1, n, colour, alpha=10, seed=1234567):
    """Deterministic sparse paper grain."""
    s = seed
    for _ in range(n):
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        x = x0 + s % max(1, (x1 - x0))
        s = (1103515245 * s + 12345) & 0x7FFFFFFF
        y = y0 + s % max(1, (y1 - y0))
        cv.plot(x, y, colour, alpha)


def draw_emblem(cv, cx, cy, r, ink, alpha=255):
    """Coat of arms of Veldoria: ring, three peaks, waves, one star."""
    cv.circle(cx, cy, r, ink, 2.2, alpha)
    cv.circle(cx, cy, r * 0.86, ink, 1.2, alpha)
    # three mountain peaks
    cv.fill_poly([(cx - r * 0.62, cy + r * 0.30), (cx - r * 0.34, cy - r * 0.34),
                  (cx - r * 0.08, cy + r * 0.30)], ink, alpha)
    cv.fill_poly([(cx - r * 0.22, cy + r * 0.30), (cx + r * 0.06, cy - r * 0.52),
                  (cx + r * 0.34, cy + r * 0.30)], ink, alpha)
    cv.fill_poly([(cx + r * 0.20, cy + r * 0.30), (cx + r * 0.42, cy - r * 0.18),
                  (cx + r * 0.62, cy + r * 0.30)], ink, alpha)
    # two wave lines under the peaks
    for k, yy in enumerate((0.42, 0.56)):
        pts = []
        x = cx - r * 0.62
        while x <= cx + r * 0.62:
            t = (x - (cx - r * 0.62)) / (r * 1.24)
            pts.append((x, cy + r * yy + 2.0 * math.sin(2 * math.pi * 2.5 * t)))
            x += 2.0
        cv.polyline(pts, ink, 1.4, alpha)
    cv.fill_poly(star_points(cx, cy - r * 0.62, r * 0.13, r * 0.055), ink, alpha)


# ---------------------------------------------------------------- portrait
def draw_portrait(cv, x0, y0, w, h):
    """A flat, engraved-style passport portrait of the holder.

    Drawn in a plain frontal pose so the face stays symmetrical and
    reads as a document photograph rather than a sketch."""
    cx = x0 + w / 2.0
    # photo background: pale blue-grey, lighter at the top
    for yy in range(int(y0), int(y0 + h)):
        t = (yy - y0) / h
        cv.hline(int(x0), int(x0 + w), yy,
                 blend((168, 182, 190), (140, 156, 166), t))
    # faint security rosette behind the head
    cv.circle(cx, y0 + h * 0.40, w * 0.30, (120, 138, 148), 1.2, 70)
    cv.circle(cx, y0 + h * 0.40, w * 0.24, (120, 138, 148), 1.0, 55)
    skin = (232, 195, 154)
    skin_sh = (214, 172, 128)
    hair = (74, 50, 38)
    hair_hi = (96, 66, 50)
    jacket = (46, 64, 83)
    shirt = (245, 242, 234)
    # shoulders / jacket
    cv.fill_poly([(x0 + w * 0.02, y0 + h), (x0 + w * 0.10, y0 + h * 0.74),
                  (cx - w * 0.16, y0 + h * 0.68), (cx + w * 0.16, y0 + h * 0.68),
                  (x0 + w * 0.90, y0 + h * 0.74), (x0 + w * 0.98, y0 + h)],
                 jacket)
    # shirt V and collar
    cv.fill_poly([(cx - w * 0.13, y0 + h * 0.69), (cx, y0 + h * 0.99),
                  (cx + w * 0.13, y0 + h * 0.69)], shirt)
    cv.polyline([(cx - w * 0.13, y0 + h * 0.69), (cx, y0 + h * 0.99),
                 (cx + w * 0.13, y0 + h * 0.69)], (200, 196, 186), 1.5)
    # neck (short, tucked under the chin)
    cv.fill_poly([(cx - w * 0.05, y0 + h * 0.52), (cx + w * 0.05, y0 + h * 0.52),
                  (cx + w * 0.08, y0 + h * 0.70), (cx - w * 0.08, y0 + h * 0.70)],
                 skin_sh)
    # head
    hy, hr = y0 + h * 0.38, w * 0.26
    cv.ellipse(cx, hy, hr * 0.86, hr, skin)
    # jaw taper: small chin wedge
    cv.fill_poly([(cx - hr * 0.62, hy + hr * 0.45), (cx + hr * 0.62, hy + hr * 0.45),
                  (cx + hr * 0.30, hy + hr * 0.88), (cx - hr * 0.30, hy + hr * 0.88)],
                 skin)
    cv.ellipse(cx, hy + hr * 0.72, hr * 0.30, hr * 0.10, skin_sh, 70)
    # hair: mass over the crown, side part, gathered bun at the back
    cv.fill_poly([(cx - hr * 0.92, hy - hr * 0.10), (cx - hr * 0.88, hy - hr * 0.85),
                  (cx - hr * 0.30, hy - hr * 1.12), (cx + hr * 0.45, hy - hr * 1.08),
                  (cx + hr * 0.92, hy - hr * 0.55), (cx + hr * 0.95, hy + hr * 0.15),
                  (cx + hr * 0.78, hy - hr * 0.28), (cx + hr * 0.30, hy - hr * 0.72),
                  (cx - hr * 0.45, hy - hr * 0.66), (cx - hr * 0.80, hy - hr * 0.30)],
                 hair)
    cv.fill_circle(cx + hr * 0.82, hy - hr * 0.68, hr * 0.30, hair)  # bun
    cv.polyline([(cx - hr * 0.55, hy - hr * 0.80), (cx - hr * 0.10, hy - hr * 0.98),
                 (cx + hr * 0.40, hy - hr * 0.88)], hair_hi, 2.0)
    # ears
    cv.ellipse(cx - hr * 0.86, hy + hr * 0.10, hr * 0.10, hr * 0.16, skin)
    cv.ellipse(cx + hr * 0.86, hy + hr * 0.10, hr * 0.10, hr * 0.16, skin)
    # brows
    cv.polyline([(cx - hr * 0.52, hy - hr * 0.12), (cx - hr * 0.18, hy - hr * 0.20)],
                (58, 40, 30), 2.2)
    cv.polyline([(cx + hr * 0.18, hy - hr * 0.20), (cx + hr * 0.52, hy - hr * 0.12)],
                (58, 40, 30), 2.2)
    # eyes
    for sgn in (-1, 1):
        ex = cx + sgn * hr * 0.34
        cv.ellipse(ex, hy + hr * 0.02, hr * 0.13, hr * 0.055, (250, 248, 244))
        cv.fill_circle(ex, hy + hr * 0.02, hr * 0.055, (52, 40, 34))
        cv.polyline([(ex - hr * 0.14, hy - hr * 0.02), (ex, hy - hr * 0.07),
                     (ex + hr * 0.14, hy - hr * 0.02)], (58, 40, 30), 1.6)
    # nose
    cv.polyline([(cx + hr * 0.02, hy + hr * 0.12), (cx - hr * 0.02, hy + hr * 0.38),
                 (cx + hr * 0.08, hy + hr * 0.44)], skin_sh, 1.6)
    # lips
    cv.polyline([(cx - hr * 0.20, hy + hr * 0.62), (cx, hy + hr * 0.58),
                 (cx + hr * 0.20, hy + hr * 0.62)], (178, 110, 96), 2.0)
    cv.polyline([(cx - hr * 0.16, hy + hr * 0.66), (cx, hy + hr * 0.69),
                 (cx + hr * 0.16, hy + hr * 0.66)], (178, 110, 96), 1.6)
    # soft cheek shading
    cv.ellipse(cx - hr * 0.55, hy + hr * 0.42, hr * 0.14, hr * 0.08, (226, 178, 140), 60)
    cv.ellipse(cx + hr * 0.55, hy + hr * 0.42, hr * 0.14, hr * 0.08, (226, 178, 140), 60)


# ---------------------------------------------------------------- MRZ
MRZ_VALUES = {chr(ord("0") + i): i for i in range(10)}
MRZ_VALUES.update({chr(ord("A") + i): 10 + i for i in range(26)})
MRZ_VALUES["<"] = 0


def mrz_check(s):
    total = 0
    for i, ch in enumerate(s):
        total += MRZ_VALUES[ch] * (7, 3, 1)[i % 3]
    return str(total % 10)


def mrz_lines():
    """ICAO TD3 machine-readable zone for this passport."""
    doc = "VLD482916"
    dob = "960417"
    exp = "340313"
    line1 = ("P<VLDVOSS<<MARA<ELISABETH" + "<" * 19)[:44]
    personal = "<<<<<<<<<<<<<<"  # 14 filler chars; its check digit is 0
    line2 = (doc + mrz_check(doc) + "VLD" + dob + mrz_check(dob) + "F" +
             exp + mrz_check(exp) + personal + mrz_check(personal))
    comp = (doc + mrz_check(doc) + "VLD" + dob + mrz_check(dob) + exp +
            mrz_check(exp) + personal + mrz_check(personal))
    line2 += mrz_check(comp)
    return line1[:44], line2[:44]


# ---------------------------------------------------------------- stamps
def rect_stamp(w, h, lines, ink, border_w=3.0, alpha=205):
    """A rectangular ink stamp on its own transparent sprite."""
    cv = Canvas(w, h)
    # border drawn as outline via four thick lines
    cv.line(6, 6, w - 7, 6, ink, border_w, alpha)
    cv.line(6, h - 7, w - 7, h - 7, ink, border_w, alpha)
    cv.line(6, 6, 6, h - 7, ink, border_w, alpha)
    cv.line(w - 7, 6, w - 7, h - 7, ink, border_w, alpha)
    y = 16
    for text, scale in lines:
        s = scale
        tw = text_width(text, s)
        draw_text(cv, (w - tw) / 2, y, s, text, ink, alpha)
        y += int(11 * s) + 4
    return cv


def circle_stamp(d, top, mid, bottom, date, ink, alpha=205):
    """A round border-control stamp on its own transparent sprite."""
    cv = Canvas(d, d)
    c = d / 2.0
    cv.circle(c, c, d / 2 - 6, ink, 3.0, alpha)
    cv.circle(c, c, d / 2 - 14, ink, 1.5, alpha)
    s = 2.6
    draw_text(cv, c, c - 58, s, top, ink, alpha, align="center")
    draw_text(cv, c, c - 30, s, mid, ink, alpha, align="center")
    draw_text(cv, c, c + 6, 3.4, date, ink, alpha, align="center")
    draw_text(cv, c, c + 40, s, bottom, ink, alpha, align="center")
    for sgn in (-1, 1):
        cv.fill_poly(star_points(c + sgn * (d / 2 - 40), c, 7, 3), ink, alpha)
    return cv


def visa_sticker(x0, y0, w, h, cv):
    """The Kestrelia visa: a pale sticker with a gold border."""
    cv.rect(x0, y0, x0 + w, y0 + h, (223, 232, 216))
    cv.line(x0 + 3, y0 + 3, x0 + w - 3, y0 + 3, (184, 155, 74), 2.0)
    cv.line(x0 + 3, y0 + h - 3, x0 + w - 3, y0 + h - 3, (184, 155, 74), 2.0)
    cv.line(x0 + 3, y0 + 3, x0 + 3, y0 + h - 3, (184, 155, 74), 2.0)
    cv.line(x0 + w - 3, y0 + 3, x0 + w - 3, y0 + h - 3, (184, 155, 74), 2.0)
    ink = (38, 52, 44)
    draw_emblem(cv, x0 + 30, y0 + 32, 17, (140, 116, 52), 220)
    draw_text(cv, x0 + 58, y0 + 12, 3.0, "VISA", ink, 255)
    draw_text(cv, x0 + 58, y0 + 48, 1.9, "KINGDOM OF", ink, 230)
    draw_text(cv, x0 + 58, y0 + 70, 1.9, "KESTRELIA", ink, 230)
    cv.line(x0 + 14, y0 + 98, x0 + w - 14, y0 + 98, ink, 1.5, 200)
    lab = (96, 104, 96)
    rows = [("TYPE", "C - MULTIPLE ENTRY"),
            ("VALID", "09 NOV 2024 - 08 MAY 2025"),
            ("STAY", "90 DAYS"),
            ("NO.", "KST-7741-09"),
            ("ISSUED", "PORT MERIDIAN, 05 NOV 2024")]
    y = y0 + 110
    for lab_t, val in rows:
        draw_text(cv, x0 + 14, y, 1.5, lab_t, lab, 230)
        draw_text(cv, x0 + 14, y + 17, 1.8, val, ink, 245)
        y += 42
    draw_text(cv, x0 + 14, y0 + h - 20, 1.5, "NOT VALID FOR EMPLOYMENT",
              (120, 40, 32), 230)


def signature(cv, x, y, scale, ink=(42, 52, 66), alpha=235):
    """A flowing holder's signature: 'M. Voss' as one ink squiggle."""
    pts = [(0, 6), (6, -6), (12, 8), (18, -4), (24, 6), (30, -2),
           (34, 4), (40, 2), (46, -6), (52, 6), (58, -4), (64, 4),
           (70, 0), (78, -2), (84, 4)]
    cv.polyline([(x + px * scale, y + py * scale) for px, py in pts], ink, 2.4, alpha)
    cv.polyline([(x + 8 * scale, y + 10 * scale), (x + 84 * scale, y + 10 * scale)],
                ink, 1.4, 200)


# ---------------------------------------------------------------- composition
# All layout coordinates below are in final-image pixels (1024 square);
# they are multiplied by S = SCALE for the supersampled work buffer.
S = SCALE
INK = (31, 42, 58)
LABEL = (107, 98, 82)
PAPER = (243, 236, 218)
PAPER_DK = (232, 224, 205)
RULE = (138, 122, 90)


def left_page(cv):
    # page body
    cv.rect(24 * S, 150 * S, 512 * S, 874 * S, PAPER)
    cv.line(34 * S, 160 * S, 502 * S, 160 * S, RULE, 1.5, 160)
    cv.line(34 * S, 864 * S, 502 * S, 864 * S, RULE, 1.5, 160)
    cv.line(34 * S, 160 * S, 34 * S, 864 * S, RULE, 1.5, 160)
    cv.line(502 * S, 160 * S, 502 * S, 864 * S, RULE, 1.5, 160)
    guilloche(cv, 40 * S, 166 * S, 496 * S, 858 * S, (190, 172, 128))
    speckle(cv, 40 * S, 166 * S, 496 * S, 858 * S, 900, (120, 104, 70), 8)
    # header: emblem + country + document title
    draw_emblem(cv, 268 * S, 208 * S, 26 * S, INK, 235)
    draw_text(cv, 268 * S, 244 * S, 4.9, "REPUBLIC OF VELDORIA", INK, 255,
              align="center")
    draw_text(cv, 268 * S, 272 * S, 3.3, "PASSPORT", INK, 245, align="center")
    draw_text(cv, 268 * S, 292 * S, 2.0, "PASSEPORT", LABEL, 230, align="center",
              tracking=2.0)
    cv.line(60 * S, 310 * S, 476 * S, 310 * S, RULE, 1.5, 180)
    # portrait in its frame
    cv.rect(56 * S, 330 * S, 196 * S, 530 * S, (150, 164, 172))
    draw_portrait(cv, 60 * S, 334 * S, 132 * S, 192 * S)
    cv.line(56 * S, 330 * S, 196 * S, 330 * S, INK, 2.0, 220)
    cv.line(56 * S, 530 * S, 196 * S, 530 * S, INK, 2.0, 220)
    cv.line(56 * S, 330 * S, 56 * S, 530 * S, INK, 2.0, 220)
    cv.line(196 * S, 330 * S, 196 * S, 530 * S, INK, 2.0, 220)
    # holder's signature under the portrait
    signature(cv, 60 * S, 542 * S, 3.0)
    draw_text(cv, 126 * S, 566 * S, 1.5, "HOLDER'S SIGNATURE", LABEL, 220,
              align="center")
    # data fields
    def field(x, y, label, value, vscale=2.65, sep=250):
        draw_text(cv, x * S, y * S, 1.55, label, LABEL, 230)
        draw_text(cv, x * S, (y + 13) * S, vscale, value, INK, 255)
        cv.line(x * S, (y + 30) * S, (x + sep) * S, (y + 30) * S,
                (190, 176, 140), 1.0, 120)

    field(212, 330, "TYPE", "P", sep=70)
    field(300, 330, "CODE", "VLD", sep=70)
    field(388, 330, "PASSPORT NO.", "VLD482916", sep=100)
    field(212, 372, "SURNAME", "VOSS")
    field(212, 406, "GIVEN NAMES", "MARA ELISABETH")
    field(212, 440, "NATIONALITY", "VELDORIAN")
    field(212, 474, "DATE OF BIRTH", "17 APR 1996")
    field(212, 508, "PLACE OF BIRTH", "PORT MERIDIAN")
    field(212, 542, "SEX", "F")
    field(212, 576, "DATE OF ISSUE", "14 MAR 2024")
    field(212, 610, "DATE OF EXPIRY", "13 MAR 2034")
    field(212, 644, "AUTHORITY", "MINISTRY OF THE INTERIOR", vscale=2.4)
    # machine-readable zone
    cv.rect(44 * S, 700 * S, 492 * S, 836 * S, PAPER_DK)
    cv.line(44 * S, 700 * S, 492 * S, 700 * S, RULE, 1.5, 160)
    mrz1, mrz2 = mrz_lines()
    draw_text(cv, 268 * S, 716 * S, 3.33, mrz1, (20, 24, 31), 255, align="center")
    draw_text(cv, 268 * S, 752 * S, 3.33, mrz2, (20, 24, 31), 255, align="center")
    draw_text(cv, 492 * S, 850 * S, 1.6, "11", LABEL, 200, align="right")


def right_page(cv):
    cv.rect(512 * S, 150 * S, 1000 * S, 874 * S, PAPER)
    cv.line(522 * S, 160 * S, 990 * S, 160 * S, RULE, 1.5, 160)
    cv.line(522 * S, 864 * S, 990 * S, 864 * S, RULE, 1.5, 160)
    cv.line(522 * S, 160 * S, 522 * S, 864 * S, RULE, 1.5, 160)
    cv.line(990 * S, 160 * S, 990 * S, 864 * S, RULE, 1.5, 160)
    guilloche(cv, 528 * S, 166 * S, 984 * S, 858 * S, (190, 172, 128))
    speckle(cv, 528 * S, 166 * S, 984 * S, 858 * S, 900, (120, 104, 70), 8)
    draw_text(cv, 756 * S, 176 * S, 3.3, "VISAS", INK, 245, align="center")
    draw_text(cv, 980 * S, 180 * S, 1.8, "P. 12", LABEL, 220, align="right")
    cv.line(540 * S, 202 * S, 972 * S, 202 * S, RULE, 1.5, 180)
    # Kestrelia visa sticker
    visa_sticker(540 * S, 214 * S, 224 * S, 190 * S, cv)
    # round Veldoria border-control stamp
    stamp = circle_stamp(300, "BORDER", "CONTROL", "VELDORIA", "09 NOV 2024",
                         (43, 76, 155))
    cv.blit(stamp.rotated(-8), 800 * S, 214 * S)
    # rectangular entry / exit stamps
    ald = rect_stamp(420, 128, [("ALDERMARK", 3.4), ("ENTRY - 02 JUN 2024", 2.6),
                                ("PORT MERIDIAN", 2.2)], (43, 76, 155))
    cv.blit(ald.rotated(-10), 540 * S, 428 * S)
    tal = rect_stamp(420, 128, [("TALVERIA", 3.4), ("EXIT - 02 OCT 2024", 2.6),
                                ("PORT MERIDIAN", 2.2)], (107, 63, 160))
    cv.blit(tal.rotated(7), 762 * S, 428 * S)
    fer = rect_stamp(420, 128, [("ENTRY BY FERRY ONLY", 2.8),
                                ("SEE TIDE TABLE", 2.8)], (176, 58, 46))
    cv.blit(fer.rotated(-4), 540 * S, 514 * S)
    kes = rect_stamp(420, 112, [("KESTRELIA", 3.2), ("ENTRY 09 NOV 2024", 2.6)],
                     (46, 107, 79))
    cv.blit(kes.rotated(12), 762 * S, 520 * S)
    # tide table: the paperwork detail that reveals the country
    cv.rect(540 * S, 610 * S, 960 * S, 820 * S, (238, 232, 214))
    cv.line(540 * S, 610 * S, 960 * S, 610 * S, RULE, 2.0, 200)
    cv.line(540 * S, 820 * S, 960 * S, 820 * S, RULE, 2.0, 200)
    cv.line(540 * S, 610 * S, 540 * S, 820 * S, RULE, 2.0, 200)
    cv.line(960 * S, 610 * S, 960 * S, 820 * S, RULE, 2.0, 200)
    draw_text(cv, 750 * S, 624 * S, 2.4, "HARBOURMASTER - PORT MERIDIAN", INK,
              245, align="center")
    draw_text(cv, 750 * S, 648 * S, 1.7, "TIDE TABLE - ISSUED WITH THIS PASSPORT",
              LABEL, 230, align="center")
    draw_text(cv, 750 * S, 664 * S, 1.7, "14 MAR 2024", LABEL, 230, align="center")
    cv.line(560 * S, 684 * S, 940 * S, 684 * S, RULE, 1.2, 160)
    for i, row in enumerate([("HIGH WATER", "06:42", "2.1 M"),
                             ("LOW WATER", "12:58", "0.4 M"),
                             ("HIGH WATER", "19:05", "2.0 M")]):
        y = 696 + i * 30
        draw_text(cv, 560 * S, y * S, 2.2, row[0], INK, 245)
        draw_text(cv, 800 * S, y * S, 2.2, row[1], INK, 245)
        draw_text(cv, 900 * S, y * S, 2.2, row[2], INK, 245)
    cv.line(560 * S, 790 * S, 940 * S, 790 * S, RULE, 1.2, 160)
    draw_text(cv, 750 * S, 798 * S, 1.7,
              "FERRIES SAIL WITHIN 2 HOURS OF HIGH WATER", (120, 40, 32), 235,
              align="center")
    draw_text(cv, 756 * S, 845 * S, 1.5,
              "THIS PASSPORT REMAINS THE PROPERTY OF THE REPUBLIC OF VELDORIA",
              LABEL, 200, align="center")


def build():
    cv = Canvas(W, H)
    # desk: deep slate gradient with a soft shadow under the spread
    for yy in range(H):
        t = yy / H
        cv.hline(0, W - 1, yy, blend((38, 45, 52), (20, 25, 30), t))
    for yy in range(0, H, 7):
        cv.hline(0, W - 1, yy, (255, 255, 255), 3)
    for k in range(14):
        cv.rect((24 - k) * S, (874 + 4 + k) * S, (1000 + k) * S,
                (874 + 6 + k) * S, (0, 0, 0), 26 - k)
    # the open spread
    left_page(cv)
    right_page(cv)
    # centre gutter shadow + top edge highlight
    cv.rect(508 * S, 150 * S, 516 * S, 874 * S, (60, 48, 32), 70)
    cv.rect(506 * S, 150 * S, 508 * S, 874 * S, (60, 48, 32), 40)
    cv.line(24 * S, 150 * S, 1000 * S, 150 * S, (255, 246, 220), 1.5, 90)
    cv.line(24 * S, 874 * S, 1000 * S, 874 * S, (0, 0, 0), 2.0, 120)
    return cv


def main():
    try:
        cv = build()
        rgb = downsample(cv)
        size = write_png("/output/entry.png", rgb, OUT_W, OUT_H)
    except Exception as exc:  # never leave the gate without an image
        print("render failed: %r" % (exc,))
        cv = Canvas(W, H)
        cv.fill(PAPER)
        draw_text(cv, 512 * S, 480 * S, 6.0, "REPUBLIC OF VELDORIA", INK,
                  255, align="center")
        draw_text(cv, 512 * S, 540 * S, 3.0, "PASSPORT", INK, 255, align="center")
        size = write_png("/output/entry.png", downsample(cv), OUT_W, OUT_H)
    print("wrote /output/entry.png (%d bytes)" % size)


if __name__ == "__main__":
    main()
