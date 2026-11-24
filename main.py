#!/usr/bin/env python3
"""The Map of Widdershins Isle.

Draws one 1024x1024 treasure map of a fictional island, in pure Python
standard library, and writes it to /output/entry.png.

The map is the hand-drawn chart of Captain Barnaby Widdershins, who buried
the Widow's Dowry on the island he named after himself and then drew this
map as a reminder to himself -- because he knew he would forget where he
put it. His corrections, crossed-out digs and notes to self are part of
the map.

Deterministic: every wobble, blotch and wave comes from fixed seeds, so two
runs write byte-identical PNGs. No network, no third-party code.
"""

import math
import os
import struct
import zlib

W = 1024
H = 1024

# ---------------------------------------------------------------- palette
PAPER = (233, 214, 169)      # old parchment
PAPER_DARK = (214, 190, 140)  # blotch tint
PAPER_LIGHT = (242, 226, 188)
INK = (43, 29, 18)           # iron-gall ink brown-black
INK_SOFT = (74, 54, 34)
RED = (168, 50, 38)          # the X, and other emphatic bits
SEA_BLUE = (84, 110, 122)    # faded sea-ink blue-grey
LAND = (219, 198, 141)       # sand
LAND_GREEN = (172, 182, 118)  # scrub wash
SAND = (232, 212, 160)

OUT = os.environ.get("MAKEFUN_OUTPUT_DIR", "/output")
OUT_PATH = os.path.join(OUT, "entry.png")


# ---------------------------------------------------------------- hashing
def _hash01(a, b, c):
    """Deterministic pseudo-random in [0, 1) from three integers."""
    n = (int(a) * 374761393 + int(b) * 668265263 + int(c) * 974634211) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n = (n ^ (n >> 16)) & 0xFFFFFFFF
    return (n & 0xFFFF) / 65536.0


def _wob(a, b, c, amp):
    return (_hash01(a, b, c) - 0.5) * 2.0 * amp


# ---------------------------------------------------------------- canvas
class Canvas:
    def __init__(self, w, h, base):
        self.w = w
        self.h = h
        self.px = bytearray(bytes(base)) * (w * h)

    def _off(self, x, y):
        return (y * self.w + x) * 3

    def blend(self, x, y, color, alpha):
        if x < 0 or y < 0 or x >= self.w or y >= self.h:
            return
        o = self._off(x, y)
        a = alpha
        if a >= 1.0:
            self.px[o] = color[0]
            self.px[o + 1] = color[1]
            self.px[o + 2] = color[2]
        elif a > 0.0:
            ia = 1.0 - a
            self.px[o] = int(color[0] * a + self.px[o] * ia + 0.5)
            self.px[o + 1] = int(color[1] * a + self.px[o + 1] * ia + 0.5)
            self.px[o + 2] = int(color[2] * a + self.px[o + 2] * ia + 0.5)

    def disc(self, cx, cy, r, color, alpha=1.0):
        r = float(r)
        x0 = max(0, int(math.floor(cx - r)))
        x1 = min(self.w - 1, int(math.ceil(cx + r)))
        y0 = max(0, int(math.floor(cy - r)))
        y1 = min(self.h - 1, int(math.ceil(cy + r)))
        r2 = r * r
        for y in range(y0, y1 + 1):
            dy = y - cy
            for x in range(x0, x1 + 1):
                dx = x - cx
                if dx * dx + dy * dy <= r2:
                    self.blend(x, y, color, alpha)

    def line(self, x0, y0, x1, y1, width, color, alpha=1.0):
        """Thick line drawn as stamped discs along the segment."""
        dx = x1 - x0
        dy = y1 - y0
        length = math.hypot(dx, dy)
        if length < 0.01:
            self.disc(x0, y0, width / 2.0, color, alpha)
            return
        step = max(0.6, width / 3.0)
        n = max(1, int(length / step))
        r = width / 2.0
        for i in range(n + 1):
            t = i / n
            self.disc(x0 + dx * t, y0 + dy * t, r, color, alpha)

    def polyline(self, pts, width, color, alpha=1.0, closed=False):
        pts = list(pts)
        if closed and len(pts) > 1:
            pts = pts + [pts[0]]
        for i in range(len(pts) - 1):
            self.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1],
                      width, color, alpha)

    def ellipse(self, cx, cy, rx, ry, color, alpha=1.0):
        x0 = max(0, int(math.floor(cx - rx)))
        x1 = min(self.w - 1, int(math.ceil(cx + rx)))
        y0 = max(0, int(math.floor(cy - ry)))
        y1 = min(self.h - 1, int(math.ceil(cy + ry)))
        for y in range(y0, y1 + 1):
            ny = (y - cy) / ry
            for x in range(x0, x1 + 1):
                nx = (x - cx) / rx
                if nx * nx + ny * ny <= 1.0:
                    self.blend(x, y, color, alpha)

    def ring(self, cx, cy, r, width, color, alpha=1.0):
        steps = max(48, int(2 * math.pi * r / 2.0))
        for i in range(steps + 1):
            a = 2 * math.pi * i / steps
            self.disc(cx + r * math.cos(a), cy + r * math.sin(a),
                      width / 2.0, color, alpha)

    def arc(self, cx, cy, r, a0, a1, width, color, alpha=1.0):
        steps = max(8, int(abs(a1 - a0) * r / 2.0))
        for i in range(steps + 1):
            a = a0 + (a1 - a0) * i / steps
            self.disc(cx + r * math.cos(a), cy + r * math.sin(a),
                      width / 2.0, color, alpha)

    def fill_polygon(self, pts, color, alpha=1.0):
        """Scanline fill (even-odd) for a simple polygon."""
        if len(pts) < 3:
            return
        ymin = max(0, int(math.floor(min(p[1] for p in pts))))
        ymax = min(self.h - 1, int(math.ceil(max(p[1] for p in pts))))
        edges = []
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            if y0 == y1:
                continue
            edges.append((x0, y0, x1, y1))
        for y in range(ymin, ymax + 1):
            xs = []
            yc = y + 0.5
            for (x0, y0, x1, y1) in edges:
                if (y0 <= yc < y1) or (y1 <= yc < y0):
                    t = (yc - y0) / (y1 - y0)
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                x0 = max(0, int(math.ceil(xs[i])))
                x1 = min(self.w - 1, int(math.floor(xs[i + 1])))
                for x in range(x0, x1 + 1):
                    self.blend(x, y, color, alpha)

    def point_in_polygon(self, x, y, pts):
        inside = False
        n = len(pts)
        j = n - 1
        for i in range(n):
            xi, yi = pts[i]
            xj, yj = pts[j]
            if ((yi > y) != (yj > y)) and \
               (x < (xj - xi) * (y - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside


# ---------------------------------------------------------------- stroke font
# Hand-lettered capitals on a 4-wide x 6-tall grid; each glyph is a list of
# strokes, each stroke a space-separated list of "x,y" points.
_GLYPHS = {
    "A": ["0,6 2,0 4,6", "1.1,3.9 2.9,3.9"],
    "B": ["0,0 0,6", "0,0 2.6,0 3.6,1.2 2.6,3 0,3",
          "0,3 2.6,3 3.6,4.2 2.6,6 0,6"],
    "C": ["3.6,1.2 2.2,0 0.8,0.8 0,2.5 0,4 0.8,5.4 2.2,6 3.6,5"],
    "D": ["0,0 0,6", "0,0 2.4,0 4,1.5 4,4.5 2.4,6 0,6"],
    "E": ["0,0 0,6", "0,0 3.6,0", "0,3 2.8,3", "0,6 3.6,6"],
    "F": ["0,0 0,6", "0,0 3.6,0", "0,3 2.8,3"],
    "G": ["3.6,1.2 2.2,0 0.8,0.8 0,2.5 0,4 0.8,5.4 2.2,6 3.6,5 3.6,3.4 2,3.4"],
    "H": ["0,0 0,6", "4,0 4,6", "0,3 4,3"],
    "I": ["2,0 2,6", "0.7,0 3.3,0", "0.7,6 3.3,6"],
    "J": ["3.2,0 3.2,4.8 2.2,6 0.8,6 0.2,5"],
    "K": ["0,0 0,6", "3.8,0 0.8,3.1", "1.6,2.9 3.8,6"],
    "L": ["0,0 0,6", "0,6 3.6,6"],
    "M": ["0,6 0,0 2,3.2 4,0 4,6"],
    "N": ["0,6 0,0 4,6 4,0"],
    "O": ["1,0 3,0 4,1.8 4,4.2 3,6 1,6 0,4.2 0,1.8 1,0"],
    "P": ["0,0 0,6", "0,0 2.6,0 3.6,1.2 2.6,3 0,3"],
    "Q": ["1,0 3,0 4,1.8 4,4.2 3,6 1,6 0,4.2 0,1.8 1,0", "2.6,4.2 4,6"],
    "R": ["0,0 0,6", "0,0 2.6,0 3.6,1.2 2.6,3 0,3", "1.8,3 3.8,6"],
    "S": ["3.6,0.9 2.2,0 0.8,0.8 0.6,2.2 1.6,3.2 3,3.8 3.4,4.8 2.2,6 0.8,5.2"],
    "T": ["0,0 4,0", "2,0 2,6"],
    "U": ["0,0 0,4.6 1,6 3,6 4,4.6 4,0"],
    "V": ["0,0 2,6 4,0"],
    "W": ["0,0 1,6 2,3 3,6 4,0"],
    "X": ["0,0 4,6", "4,0 0,6"],
    "Y": ["0,0 2,3 4,0", "2,3 2,6"],
    "Z": ["0,0 4,0 0,6 4,6"],
    "0": ["1,0 3,0 4,1.8 4,4.2 3,6 1,6 0,4.2 0,1.8 1,0"],
    "1": ["1.2,1 2,0 2,6", "0.7,6 3.3,6"],
    "2": ["0.6,1.4 1.6,0 3,0 3.8,1.4 3.8,2.4 0.6,6 3.8,6"],
    "3": ["0.6,0.9 2,0 3.2,0.9 3.2,2.4 2,3 3.2,3.6 3.2,5.1 2,6 0.6,5.1"],
    "4": ["3,0 0.6,4.4 3.6,4.4", "2.6,0 2.6,6"],
    "5": ["3.6,0 0.6,0 0.6,2.6 2.6,2.6 3.6,3.6 3.6,5 2,6 0.6,5.4"],
    "6": ["3.4,1 2,0 0.8,1.2 0.5,3.4 1,5.4 2.5,6 3.5,4.8 3.5,3.6 2,3 1,4"],
    "7": ["0.6,0 3.6,0 2,6"],
    "8": ["1.4,0 2.6,0 3.4,1 3.4,2.2 2,3 0.6,2.2 0.6,1 1.4,0",
          "2,3 3.4,3.8 3.4,5 2.6,6 1.4,6 0.6,5 0.6,3.8 2,3"],
    "9": ["0.6,5 2,6 3.4,4.8 3.6,2.6 3,0.8 1.6,0 0.6,1 0.6,2.4 2,3 3.4,2.4"],
    ".": ["DOT 2,5.8"],
    ",": ["2,5.4 1.5,6.6"],
    "'": ["2.2,0 1.8,1.6"],
    "-": ["0.6,3 3.4,3"],
    "!": ["2,0 2,4.4", "DOT 2,5.8"],
    "?": ["1,1.2 2,0 3,0 3.6,1 2.6,2.6 2,3.4 2,4.4", "DOT 2,5.8"],
    ":": ["DOT 2,2.2", "DOT 2,5"],
    "(": ["3,0.6 2,1.6 2,4.4 3,5.4"],
    ")": ["1,0.6 2,1.6 2,4.4 1,5.4"],
    "&": ["2.8,0.4 1.6,0 0.8,0.8 0.8,2.2 2,3.2 3.4,4.4 3.4,5.4 2.2,6 1,5.6",
          "0.8,2.2 2.6,1.2 3.4,2.2 2.6,3.2 1.2,4.4 0.8,5.2"],
}

ADVANCE = 5.2  # glyph grid units per character, including spacing


def _parse_glyph(strokes):
    out = []
    for s in strokes:
        pts = []
        for tok in s.split():
            if tok == "DOT":
                pts.append("DOT")
                continue
            x, y = tok.split(",")
            pts.append((float(x), float(y)))
        out.append(pts)
    return out


_GLYPH_CACHE = {ch: _parse_glyph(st) for ch, st in _GLYPHS.items()}


def text_width(text, size):
    """Width in px of `text` at cap-height `size`."""
    s = size / 6.0
    return len(text) * ADVANCE * s


def draw_text(cv, cx, top, text, size, color, align="center", alpha=1.0,
              seed=7):
    """Draw uppercase text; (cx, top) anchors the cap-height box.

    align: center / left / right relative to cx. Each glyph gets a tiny
    deterministic wobble so the lettering feels hand-inked, never typed.
    """
    s = size / 6.0
    w = text_width(text, size)
    if align == "center":
        x = cx - w / 2.0
    elif align == "right":
        x = cx - w
    else:
        x = cx
    lw = max(1.6, size * 0.09)
    for ci, ch in enumerate(text):
        ch = ch.upper()
        if ch == " ":
            x += ADVANCE * s
            continue
        strokes = _GLYPH_CACHE.get(ch)
        if strokes is None:
            x += ADVANCE * s
            continue
        # per-glyph baseline wobble (hand-lettered feel)
        gy = _wob(ci, seed, 11, 0.22) * s
        gx = _wob(ci, seed, 23, 0.12) * s
        for si, pts in enumerate(strokes):
            if pts and pts[0] == "DOT":
                dx, dy = pts[1]
                cv.disc(x + gx + dx * s, top + gy + dy * s,
                        max(1.3, lw * 0.75), color, alpha)
                continue
            wpts = []
            for pi, (px, py) in enumerate(pts):
                jx = _wob(ci * 31 + si * 7 + pi, seed, 5, 0.16) * s
                jy = _wob(ci * 31 + si * 7 + pi, seed, 9, 0.16) * s
                wpts.append((x + gx + (px * s + jx), top + gy + (py * s + jy)))
            cv.polyline(wpts, lw, color, alpha)
        x += ADVANCE * s


def draw_label(cv, cx, top, lines, size, color=INK, gap=None, seed=7):
    """One or more centered text lines; returns the bottom y."""
    if gap is None:
        gap = size * 0.32
    y = top
    for ln in lines:
        draw_text(cv, cx, y, ln, size, color, seed=seed)
        y += size + gap
    return y

# ---------------------------------------------------------------- the map
# Island coastline: a blobby, walkable island, slightly tilted, with a bay
# cut into its north-east shore and a broad beach on the south.
ISLAND = [
    (296, 700), (258, 560), (272, 430), (318, 330), (392, 282),
    (470, 252), (556, 258), (624, 296), (688, 282), (742, 330),
    (782, 402), (748, 448), (700, 470), (716, 540), (742, 620),
    (690, 690), (606, 748), (516, 772), (428, 762), (352, 736),
]


def _centroid(pts):
    return (sum(p[0] for p in pts) / len(pts),
            sum(p[1] for p in pts) / len(pts))


def _shrink(pts, f):
    cx, cy = _centroid(pts)
    return [(cx + (x - cx) * f, cy + (y - cy) * f) for (x, y) in pts]


def draw_parchment(cv):
    # soft blotches: darker and lighter washes, all seeded
    for i in range(26):
        cx = _hash01(i, 3, 1) * W
        cy = _hash01(i, 3, 2) * H
        rx = 90 + _hash01(i, 5, 1) * 160
        ry = 70 + _hash01(i, 5, 2) * 130
        col = PAPER_DARK if i % 2 == 0 else PAPER_LIGHT
        cv.ellipse(cx, cy, rx, ry, col, alpha=0.10 + _hash01(i, 7, 1) * 0.08)
    # a few coffee-ring stains out at sea, for character
    for i, (cx, cy, r) in enumerate([(120, 850, 46), (920, 830, 38),
                                     (880, 90, 30)]):
        cv.ring(cx, cy, r, 3.0, (150, 110, 60), alpha=0.16)
        cv.ring(cx, cy, r - 7, 1.6, (150, 110, 60), alpha=0.10)


def draw_sea_marks(cv):
    # scattered wave squiggles out at sea
    for i in range(26):
        cx = 30 + _hash01(i, 13, 1) * 964
        cy = 30 + _hash01(i, 13, 2) * 964
        if cv.point_in_polygon(cx, cy, ISLAND):
            continue
        if abs(cx - 512) < 260 and cy < 170:
            continue  # keep the title clear
        ln = 14 + _hash01(i, 17, 1) * 16
        pts = []
        for k in range(5):
            t = k / 4.0
            pts.append((cx - ln / 2 + ln * t,
                        cy + math.sin(t * math.pi * 2) * 3.0))
        cv.polyline(pts, 1.8, SEA_BLUE, alpha=0.55)


def draw_land(cv):
    cv.fill_polygon(ISLAND, LAND)
    # scrub-green washes, kept well inside the coastline
    for (cx, cy, rx, ry) in [(470, 480, 120, 80), (580, 600, 130, 70),
                             (380, 620, 90, 60), (620, 380, 90, 60)]:
        cv.ellipse(cx, cy, rx, ry, LAND_GREEN, alpha=0.28)
    # sand stipple
    for i in range(420):
        cx = 260 + _hash01(i, 29, 1) * 520
        cy = 260 + _hash01(i, 29, 2) * 520
        if cv.point_in_polygon(cx, cy, ISLAND):
            cv.disc(cx, cy, 1.1, INK_SOFT, alpha=0.14)
    # coastline: heavy ink, then a lighter echo line just inside
    cv.polyline(ISLAND, 4.5, INK, closed=True)
    cv.polyline(_shrink(ISLAND, 0.965), 1.6, INK, alpha=0.75, closed=True)
    # hatch ticks pointing out to sea along the coast
    n = len(ISLAND)
    for i in range(n):
        x0, y0 = ISLAND[i]
        x1, y1 = ISLAND[(i + 1) % n]
        seg = math.hypot(x1 - x0, y1 - y0)
        steps = max(1, int(seg / 26))
        for k in range(steps):
            t = (k + 0.5) / steps
            px = x0 + (x1 - x0) * t
            py = y0 + (y1 - y0) * t
            # outward normal (polygon winds clockwise in screen coords)
            nx, ny = (y1 - y0) / seg, -(x1 - x0) / seg
            cv.line(px, py, px + nx * 7, py + ny * 7, 1.4, INK, alpha=0.6)


def draw_river(cv):
    # one river, winding from the volcano's foot to the south beach
    pts = [(505, 375), (482, 420), (470, 470), (482, 520), (470, 570),
           (486, 620), (470, 670), (492, 715), (486, 748)]
    cv.polyline(pts, 3.0, SEA_BLUE, alpha=0.8)


def draw_hills(cv):
    for (cx, cy, sc) in [(420, 470, 1.0), (600, 540, 0.85), (560, 660, 0.9),
                         (380, 400, 0.7)]:
        cv.arc(cx - 12 * sc, cy, 12 * sc, math.pi, 2 * math.pi, 2.0, INK)
        cv.arc(cx + 12 * sc, cy, 12 * sc, math.pi, 2 * math.pi, 2.0, INK)


def draw_palm(cv, x, y, sc=1.0):
    # leaning trunk
    cv.polyline([(x, y), (x + 4 * sc, y - 26 * sc), (x + 10 * sc, y - 44 * sc)],
                3.0, INK)
    tx, ty = x + 10 * sc, y - 44 * sc
    for ang in (-160, -120, -80, -40, -10):
        a = math.radians(ang)
        ex = tx + 26 * sc * math.cos(a)
        ey = ty + 26 * sc * math.sin(a) * 0.7 + 6 * sc
        mx = tx + 13 * sc * math.cos(a)
        my = ty + 13 * sc * math.sin(a) * 0.7 - 4 * sc
        cv.polyline([(tx, ty), (mx, my), (ex, ey)], 2.0, INK)
    # three coconuts
    for (dx, dy) in [(2, 2), (8, 4), (5, 8)]:
        cv.disc(tx + dx * sc, ty + dy * sc, 2.2 * sc, INK)


def draw_volcano(cv):
    cx, cy = 505, 330
    cv.fill_polygon([(cx - 52, cy + 42), (cx - 14, cy - 34), (cx + 12, cy - 34),
                     (cx + 52, cy + 42)], (196, 172, 120))
    cv.polyline([(cx - 52, cy + 42), (cx - 14, cy - 34), (cx + 12, cy - 34),
                 (cx + 52, cy + 42)], 3.0, INK)
    # crater + smoke curls
    cv.arc(cx - 1, cy - 34, 13, math.pi, 2 * math.pi, 2.6, INK)
    cv.polyline([(cx - 6, cy - 52), (cx + 4, cy - 66), (cx - 4, cy - 80)],
                2.0, INK_SOFT, alpha=0.8)
    # the volcano is asleep: Z z z, drifting off to its left
    draw_text(cv, 452, 246, "Z", 26, INK_SOFT, seed=31)
    draw_text(cv, 436, 266, "z", 20, INK_SOFT, seed=32)
    draw_text(cv, 422, 284, "z", 16, INK_SOFT, seed=33)


def draw_dug_holes(cv):
    # three holes Barnaby already dug, with his shovel stuck in the last one
    for (hx, hy) in [(360, 548), (386, 563), (348, 575)]:
        cv.ellipse(hx, hy, 10, 6, (60, 42, 24), alpha=0.85)
        cv.ellipse(hx + 14, hy + 5, 7, 3.5, (150, 118, 70), alpha=0.8)
    cv.line(378, 555, 402, 515, 3.0, INK)
    cv.polyline([(402, 515), (410, 503), (418, 515)], 2.6, INK)


def draw_barrel(cv, x, y):
    cv.fill_polygon([(x - 12, y - 16), (x + 12, y - 16), (x + 14, y + 16),
                     (x - 14, y + 16)], (150, 104, 58))
    cv.polyline([(x - 12, y - 16), (x + 12, y - 16), (x + 14, y + 16),
                 (x - 14, y + 16)], 2.2, INK)
    cv.line(x - 13, y - 6, x + 13, y - 6, 2.0, INK)
    cv.line(x - 13, y + 6, x + 13, y + 6, 2.0, INK)


def draw_chest(cv, x, y):
    cv.fill_polygon([(x - 18, y - 4), (x + 18, y - 4), (x + 18, y + 16),
                     (x - 18, y + 16)], (146, 100, 52))
    cv.arc(x, y - 4, 18, math.pi, 2 * math.pi, 2.4, INK)
    cv.polyline([(x - 18, y - 4), (x + 18, y - 4), (x + 18, y + 16),
                 (x - 18, y + 16)], 2.4, INK)
    cv.line(x, y - 20, x, y + 16, 2.4, INK)
    cv.disc(x, y + 6, 3.4, (212, 178, 90))


def draw_x(cv, x, y):
    cv.line(x - 26, y - 26, x + 26, y + 26, 9.0, RED)
    cv.line(x + 26, y - 26, x - 26, y + 26, 9.0, RED)
    cv.line(x - 26, y - 26, x + 26, y + 26, 3.0, (120, 30, 22))
    cv.line(x + 26, y - 26, x - 26, y + 26, 3.0, (120, 30, 22))


def draw_route(cv):
    # the dotted path Barnaby walked, from his landing to his last guess
    path = [(300, 695), (330, 640), (345, 560), (400, 500), (480, 440),
            (560, 420), (600, 430), (612, 438)]
    # walk the path stamping dots
    for i in range(len(path) - 1):
        x0, y0 = path[i]
        x1, y1 = path[i + 1]
        seg = math.hypot(x1 - x0, y1 - y0)
        steps = int(seg / 11)
        for k in range(steps):
            t = (k + 0.5) / steps
            cv.disc(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, 2.6,
                    INK_SOFT, alpha=0.9)


def draw_compass(cv):
    cx, cy, r = 140, 265, 52
    cv.ring(cx, cy, r, 2.6, INK)
    cv.ring(cx, cy, r - 10, 1.4, INK, alpha=0.7)
    # eight points: long for the cardinals, short for the rest
    for i in range(8):
        a = math.radians(i * 45 - 90)
        ln = r - 4 if i % 2 == 0 else (r - 4) * 0.62
        tipx, tipy = cx + ln * math.cos(a), cy + ln * math.sin(a)
        w = 9 if i % 2 == 0 else 6
        px, py = math.cos(a + math.pi / 2), math.sin(a + math.pi / 2)
        base = [(cx + px * w, cy + py * w), (cx - px * w, cy - py * w)]
        if i % 2 == 0:
            cv.fill_polygon([(tipx, tipy), base[0], base[1]], INK, alpha=0.9)
        else:
            cv.polyline([(tipx, tipy), base[0], (cx, cy), base[1],
                         (tipx, tipy)], 1.6, INK)
    cv.disc(cx, cy, 4.5, INK)
    draw_text(cv, cx, cy - r - 26, "N", 24, INK, seed=41)
    draw_text(cv, cx, cy + r + 8, "(PROBABLY)", 15, INK_SOFT, seed=42)


def draw_ship(cv):
    # a little galleon, sails full, heading for the island
    x, y = 880, 250
    cv.fill_polygon([(x - 42, y), (x + 42, y), (x + 28, y + 20),
                     (x - 28, y + 20)], (146, 100, 52))
    cv.polyline([(x - 42, y), (x + 42, y), (x + 28, y + 20), (x - 28, y + 20)],
                2.4, INK)
    cv.line(x - 8, y, x - 8, y - 52, 2.6, INK)
    cv.line(x + 14, y, x + 14, y - 40, 2.6, INK)
    cv.fill_polygon([(x - 8, y - 50), (x - 8, y - 6), (x - 38, y - 6)],
                    PAPER_LIGHT, alpha=0.95)
    cv.polyline([(x - 8, y - 50), (x - 8, y - 6), (x - 38, y - 6)], 2.0, INK)
    cv.fill_polygon([(x + 14, y - 38), (x + 14, y - 6), (x + 38, y - 6)],
                    PAPER_LIGHT, alpha=0.95)
    cv.polyline([(x + 14, y - 38), (x + 14, y - 6), (x + 38, y - 6)], 2.0, INK)
    cv.polyline([(x - 8, y - 52), (x + 8, y - 48), (x - 8, y - 44)], 2.0, RED)
    for (wx, wy) in [(x - 40, y + 28), (x, y + 30), (x + 40, y + 28)]:
        cv.arc(wx, wy, 10, math.pi * 1.15, math.pi * 1.85, 1.8, SEA_BLUE,
               alpha=0.7)


def draw_serpent(cv):
    # a sea serpent, minding its own business in the western sea
    x, y = 100, 600
    for i, (dx, dy, r) in enumerate([(0, 0, 15), (42, -12, 13), (84, 2, 14),
                                     (126, -10, 12)]):
        cv.arc(x + dx, y + dy, r, math.pi, 2 * math.pi, 2.2, SEA_BLUE)
    cv.disc(x + 148, y - 22, 11, SEA_BLUE)
    cv.disc(x + 152, y - 26, 2.0, INK)
    cv.polyline([(x + 156, y - 32), (x + 168, y - 40), (x + 162, y - 26)],
                1.8, SEA_BLUE)
    draw_text(cv, 130, 668, "NESSIE ON HOLIDAY", 16, SEA_BLUE, seed=51)


def draw_kraken(cv):
    # the kraken: friendly, mostly -- south-east sea
    x, y = 880, 780
    cv.ellipse(x, y, 26, 20, SEA_BLUE, alpha=0.9)
    cv.disc(x - 9, y - 4, 2.4, PAPER)
    cv.disc(x + 9, y - 4, 2.4, PAPER)
    cv.disc(x - 9, y - 4, 1.2, INK)
    cv.disc(x + 9, y - 4, 1.2, INK)
    for i, dx in enumerate([-22, -11, 0, 11, 22]):
        pts = []
        for k in range(6):
            t = k / 5.0
            pts.append((x + dx + math.sin(t * 3 + i) * 8 * t,
                        y + 16 + t * 34))
        cv.polyline(pts, 3.2, SEA_BLUE)


def draw_mermaid(cv):
    # a mermaid on her rock, keeping score of the promises made to her
    x, y = 898, 492
    cv.ellipse(x, y + 16, 34, 14, (120, 104, 78))
    cv.polyline([(x - 34, y + 16), (x - 30, y + 4), (x + 30, y + 4),
                 (x + 34, y + 16)], 2.2, INK)
    cv.polyline([(x - 2, y + 2), (x - 16, y + 22), (x - 26, y + 30)], 3.0,
                SEA_BLUE)
    cv.polyline([(x - 26, y + 30), (x - 34, y + 22), (x - 30, y + 32)], 2.2,
                SEA_BLUE)
    cv.disc(x, y - 6, 7, (214, 178, 140))
    cv.arc(x, y - 2, 12, math.pi, 2 * math.pi, 2.2, INK)  # hair
    cv.disc(x - 3, y - 7, 1.1, INK)
    cv.disc(x + 3, y - 7, 1.1, INK)


def draw_gulls(cv):
    for (x, y, sc) in [(740, 330, 1.0), (782, 306, 0.8), (700, 300, 0.7)]:
        cv.arc(x - 7 * sc, y, 7 * sc, math.pi * 1.15, math.pi * 1.85, 1.8, INK)
        cv.arc(x + 7 * sc, y, 7 * sc, math.pi * 1.15, math.pi * 1.85, 1.8, INK)


def draw_title(cv):
    draw_text(cv, 512, 40, "WIDDERSHINS ISLE", 54, INK, seed=61)
    # double rule under the title
    cv.line(212, 112, 812, 112, 2.4, INK)
    cv.line(252, 118, 772, 118, 1.2, INK, alpha=0.7)
    draw_text(cv, 512, 130, "BEING THE TRUE & FAITHFUL CHART OF", 20,
              INK_SOFT, seed=62)
    draw_text(cv, 512, 156,
              "CAPT. BARNABY WIDDERSHINS, WHO BURIED THE TREASURE & FORGOT WHERE",
              16, INK_SOFT, seed=63)


def draw_labels(cv):
    # leader dot + name, for each place a sailor could actually find
    def dot(x, y):
        cv.disc(x, y, 3.2, RED)

    # 1. Barnaby's Landing -- where the dotted route begins
    dot(298, 698)
    draw_label(cv, 268, 742, ["BARNABY'S", "LANDING"], 27, seed=71)
    draw_palm(cv, 300, 650, 0.9)
    # 2. Doubloon Beach -- south shore, two palms
    dot(520, 770)
    draw_label(cv, 520, 806, ["DOUBLOON BEACH"], 27, seed=72)
    draw_palm(cv, 470, 745, 0.9)
    draw_palm(cv, 590, 750, 0.85)
    # 3. The Already-Dug Holes -- west, with the shovel; stacked narrow
    # so the label fits the thin strip of sea west of the island
    dot(352, 540)
    draw_label(cv, 165, 458, ["THE", "ALREADY", "DUG HOLES"], 22, seed=73)
    draw_text(cv, 165, 552, "NOTHING (TWICE)", 14, INK_SOFT, seed=74)
    # 4. Mt. Snore -- the volcano that sleeps through everything
    dot(505, 330)
    draw_label(cv, 505, 190, ["MT. SNORE"], 28, seed=75)
    # 5. Gull Bluff -- east cliffs
    dot(738, 412)
    draw_label(cv, 860, 348, ["GULL BLUFF"], 27, seed=76)
    # 6. Rum Barrel Bay -- north bay, barrel washed up on the beach
    dot(640, 300)
    draw_label(cv, 670, 240, ["RUM BARREL BAY"], 26, seed=77)
    draw_barrel(cv, 668, 318)
    # 7. The Widow's Dowry -- the X, Barnaby's last and shakiest guess
    draw_x(cv, 620, 440)
    draw_chest(cv, 668, 478)
    draw_label(cv, 620, 510, ["THE WIDOW'S", "DOWRY"], 28, RED, seed=78)
    draw_text(cv, 620, 592, "300 DOUBLOONS - MABEL'S - DO RETURN", 15,
              INK_SOFT, seed=79)
    # 8. Mermaid's Rock -- offshore east
    dot(898, 490)
    cv.line(872, 612, 895, 508, 1.6, INK_SOFT, alpha=0.8)
    draw_label(cv, 872, 620, ["MERMAID'S ROCK"], 24, seed=80)
    # 9. The Kraken -- offshore south-east
    dot(880, 762)
    draw_label(cv, 880, 850, ["THE KRAKEN"], 26, seed=81)
    draw_text(cv, 880, 884, "(FRIENDLY, MOSTLY)", 15, SEA_BLUE, seed=82)


def draw_margin_notes(cv):
    # the finder's note, bottom left -- signed by the captain himself
    draw_text(cv, 40, 896, "TO WHOEVER FINDS THIS MAP -", 16, INK_SOFT,
              align="left", seed=93)
    draw_text(cv, 40, 918, "THE TREASURE IS REAL.", 16, INK_SOFT,
              align="left", seed=94)
    draw_text(cv, 40, 940, "THE DIRECTIONS ARE MOSTLY TRUE.", 16, INK_SOFT,
              align="left", seed=95)
    draw_text(cv, 40, 962, "- BARNABY WIDDERSHINS, CAPT. (RET.)", 16,
              INK_SOFT, align="left", seed=96)
    draw_text(cv, 40, 984, "DRAWN FROM MEMORY - WHICH IS THE PROBLEM", 16,
              INK_SOFT, align="left", seed=97)
    # scale bar, bottom right
    x0, y0 = 660, 946
    cv.line(x0, y0, x0 + 200, y0, 2.4, INK)
    for dx in (0, 100, 200):
        cv.line(x0 + dx, y0 - 6, x0 + dx, y0 + 6, 2.0, INK)
    draw_text(cv, x0, y0 + 12, "0", 15, INK, seed=91)
    draw_text(cv, x0 + 200, y0 + 12, "100 PACES", 15, INK, align="right",
              seed=92)
    draw_text(cv, x0 + 100, y0 + 34, "(GIVE OR TAKE)", 13, INK_SOFT,
              seed=98)


def finish_parchment(cv):
    """Vignette + paper grain, in one final pass over the pixels."""
    cx, cy = W / 2.0, H / 2.0
    maxd = math.hypot(cx, cy)
    # 128x128 grain tile, seeded; values are signed offsets in [-5, 5]
    # (kept small on purpose: heavy grain blows the 1 MiB PNG cap)
    tile = [int((_hash01(i % 128, i // 128, 101) - 0.5) * 10)
            for i in range(128 * 128)]
    for y in range(H):
        row = y * W * 3
        dy = (y - cy) / maxd
        for x in range(W):
            dx = (x - cx) / maxd
            d = math.sqrt(dx * dx + dy * dy)
            vig = 1.0
            if d > 0.62:
                vig = 1.0 - (d - 0.62) * 0.55
            g = tile[(y % 128) * 128 + (x % 128)]
            o = row + x * 3
            for c in range(3):
                v = int(cv.px[o + c] * vig + g + 0.5)
                cv.px[o + c] = 0 if v < 0 else (255 if v > 255 else v)

# ---------------------------------------------------------------- PNG output
def _png_chunk(typ, data):
    chunk = struct.pack(">I", len(data)) + typ + data
    chunk += struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
    return chunk


def _filter_row(row, prev, ftype):
    """PNG scanline filter; row and prev are bytes of equal length."""
    n = len(row)
    out = bytearray(n)
    if ftype == 0:
        return bytes(row)
    if ftype == 1:
        for i in range(n):
            a = row[i - 3] if i >= 3 else 0
            out[i] = (row[i] - a) & 0xFF
    elif ftype == 2:
        for i in range(n):
            out[i] = (row[i] - prev[i]) & 0xFF
    elif ftype == 3:
        for i in range(n):
            a = row[i - 3] if i >= 3 else 0
            out[i] = (row[i] - ((a + prev[i]) >> 1)) & 0xFF
    else:  # Paeth
        for i in range(n):
            a = row[i - 3] if i >= 3 else 0
            b = prev[i]
            c = prev[i - 3] if i >= 3 else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            out[i] = (row[i] - pr) & 0xFF
    return bytes(out)


def _filter_score(data):
    # sum of |byte - 128| on a stride-3 sample: smaller means the filtered
    # row compresses better (sampling keeps this fast in pure Python)
    return sum(abs(b - 128) for b in data[::3])


def write_png(cv, path):
    ihdr = struct.pack(">IIBBBBB", cv.w, cv.h, 8, 2, 0, 0, 0)
    raw = bytearray()
    prev = bytes(cv.w * 3)
    for y in range(cv.h):
        row = bytes(cv.px[y * cv.w * 3:(y + 1) * cv.w * 3])
        best = None
        best_score = None
        best_type = 0
        for ftype in (0, 1, 2, 4):  # None, Sub, Up, Paeth (Average rarely wins)
            cand = _filter_row(row, prev, ftype)
            sc = _filter_score(cand)
            if best_score is None or sc < best_score:
                best, best_score, best_type = cand, sc, ftype
        raw.append(best_type)
        raw += best
        prev = row
    # level 9: smallest file, still fast enough at this size
    idat = zlib.compress(bytes(raw), 9)
    png = (b"\x89PNG\r\n\x1a\n"
           + _png_chunk(b"IHDR", ihdr)
           + _png_chunk(b"IDAT", idat)
           + _png_chunk(b"IEND", b""))
    with open(path, "wb") as f:
        f.write(png)
    # the grader collects outputs as another user: world-readable, always
    os.chmod(path, 0o644)
    return len(png)


# ---------------------------------------------------------------- main
def build():
    cv = Canvas(W, H, PAPER)
    draw_parchment(cv)
    draw_sea_marks(cv)
    draw_land(cv)
    draw_hills(cv)
    draw_volcano(cv)
    draw_river(cv)
    draw_dug_holes(cv)
    draw_route(cv)
    draw_compass(cv)
    draw_ship(cv)
    draw_serpent(cv)
    draw_kraken(cv)
    draw_mermaid(cv)
    draw_gulls(cv)
    draw_title(cv)
    draw_labels(cv)
    draw_margin_notes(cv)
    finish_parchment(cv)
    return cv


def main():
    # umask 022 so anything this program opens is world-readable by default
    os.umask(0o022)
    # never chmod the grader-provided output directory itself: it is
    # root-owned and merely writable, and chmod on it fails the run.
    os.makedirs(OUT, exist_ok=True)
    cv = build()
    size = write_png(cv, OUT_PATH)
    print(f"wrote {OUT_PATH} ({size} bytes)")


if __name__ == "__main__":
    main()
