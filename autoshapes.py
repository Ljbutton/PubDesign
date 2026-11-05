"""Publisher AutoShapes (MSO shape type ids) and their outlines."""
import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QPainterPath, QPolygonF

# (spt, name, gallery section)
SHAPES = [
    (1, "Rectangle", "Basic Shapes"),
    (2, "Rounded Rectangle", "Basic Shapes"),
    (3, "Oval", "Basic Shapes"),
    (5, "Triangle", "Basic Shapes"),
    (6, "Right Triangle", "Basic Shapes"),
    (4, "Diamond", "Basic Shapes"),
    (7, "Parallelogram", "Basic Shapes"),
    (9, "Hexagon", "Basic Shapes"),
    (10, "Octagon", "Basic Shapes"),
    (11, "Plus", "Basic Shapes"),
    (74, "Heart", "Basic Shapes"),
    (73, "Lightning Bolt", "Basic Shapes"),
    (13, "Right Arrow", "Block Arrows"),
    (66, "Left Arrow", "Block Arrows"),
    (68, "Up Arrow", "Block Arrows"),
    (67, "Down Arrow", "Block Arrows"),
    (15, "Pentagon Arrow", "Block Arrows"),
    (55, "Chevron", "Block Arrows"),
    (12, "5-Point Star", "Stars and Banners"),
    (58, "8-Point Star", "Stars and Banners"),
    (59, "16-Point Star", "Stars and Banners"),
]
NAMES = {s: n for s, n, _ in SHAPES}
SUPPORTED = set(NAMES) | {20, 202, 75}

LIGHTNING = [(8458, 0), (0, 3923), (7564, 8416), (4993, 9720), (12197, 13904), (9987, 14934), (21600, 21600),
             (14768, 12911), (16558, 12016), (11030, 6840), (12831, 6120)]


def _poly(pts, w, h):
    p = QPainterPath()
    p.addPolygon(QPolygonF([QPointF(x * w, y * h) for x, y in pts]))
    p.closeSubpath()
    return p


def _star(n, inner, w, h):
    pts = []
    for i in range(2 * n):
        r = 0.5 if i % 2 == 0 else 0.5 * inner
        a = -math.pi / 2 + i * math.pi / n
        pts.append((0.5 + r * math.cos(a), 0.5 + r * math.sin(a)))
    return _poly(pts, w, h)


def outline(spt, w, h):
    """QPainterPath of the shape in a w × h box (local coordinates)."""
    if spt in (1, 202, 75, 0):
        p = QPainterPath()
        p.addRect(QRectF(0, 0, w, h))
        return p
    if spt == 3:
        p = QPainterPath()
        p.addEllipse(QRectF(0, 0, w, h))
        return p
    if spt == 2:
        r = min(abs(w), abs(h)) * 3600 / 21600
        p = QPainterPath()
        p.addRoundedRect(QRectF(0, 0, w, h), r, r)
        return p
    if spt == 4:
        return _poly([(.5, 0), (1, .5), (.5, 1), (0, .5)], w, h)
    if spt == 5:
        return _poly([(.5, 0), (1, 1), (0, 1)], w, h)
    if spt == 6:
        return _poly([(0, 0), (1, 1), (0, 1)], w, h)
    if spt == 7:
        return _poly([(.25, 0), (1, 0), (.75, 1), (0, 1)], w, h)
    if spt == 9:
        return _poly([(.25, 0), (.75, 0), (1, .5), (.75, 1), (.25, 1), (0, .5)], w, h)
    if spt == 10:
        a = 0.293
        return _poly([(a, 0), (1 - a, 0), (1, a), (1, 1 - a), (1 - a, 1), (a, 1), (0, 1 - a), (0, a)], w, h)
    if spt == 11:
        a = .25
        return _poly([(a, 0), (1 - a, 0), (1 - a, a), (1, a), (1, 1 - a), (1 - a, 1 - a), (1 - a, 1), (a, 1),
                      (a, 1 - a), (0, 1 - a), (0, a), (a, a)], w, h)
    if spt == 12:
        return _star(5, 0.38, w, h)
    if spt == 58:
        return _star(8, 0.765, w, h)
    if spt == 59:
        return _star(16, 0.75, w, h)
    if spt == 13:
        return _poly([(0, .25), (.75, .25), (.75, 0), (1, .5), (.75, 1), (.75, .75), (0, .75)], w, h)
    if spt == 66:
        return _poly([(1, .25), (.25, .25), (.25, 0), (0, .5), (.25, 1), (.25, .75), (1, .75)], w, h)
    if spt == 68:
        return _poly([(.25, 1), (.25, .25), (0, .25), (.5, 0), (1, .25), (.75, .25), (.75, 1)], w, h)
    if spt == 67:
        return _poly([(.25, 0), (.25, .75), (0, .75), (.5, 1), (1, .75), (.75, .75), (.75, 0)], w, h)
    if spt == 15:
        return _poly([(0, 0), (.75, 0), (1, .5), (.75, 1), (0, 1)], w, h)
    if spt == 55:
        return _poly([(0, 0), (.75, 0), (1, .5), (.75, 1), (0, 1), (.25, .5)], w, h)
    if spt == 73:
        return _poly([(x / 21600, y / 21600) for x, y in LIGHTNING], w, h)
    if spt == 74:
        p = QPainterPath()
        p.moveTo(.5 * w, h)
        p.cubicTo(.1 * w, .72 * h, -.02 * w, .45 * h, .02 * w, .25 * h)
        p.cubicTo(.07 * w, .02 * h, .4 * w, -.06 * h, .5 * w, .1 * h)
        p.cubicTo(.6 * w, -.06 * h, .93 * w, .02 * h, .98 * w, .25 * h)
        p.cubicTo(1.02 * w, .45 * h, .9 * w, .72 * h, .5 * w, h)
        p.closeSubpath()
        return p
    p = QPainterPath()
    p.addRect(QRectF(0, 0, w, h))
    return p
