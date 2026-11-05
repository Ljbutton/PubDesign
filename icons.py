"""Hand-drawn ribbon icons (no external assets)."""
import math

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

INK = QColor(68, 72, 80)
TEAL = QColor(7, 117, 104)
BLUE = QColor(43, 121, 208)
ORANGE = QColor(232, 120, 52)
GOLD = QColor(240, 186, 60)
RED = QColor(210, 58, 52)
PAPER = QColor(255, 255, 255)
LIGHT = QColor(200, 214, 230)

_cache = {}


def icon(name, size=32):
    key = (name, size)
    if key in _cache:
        return _cache[key]
    ic = QIcon()
    for scale in (1, 2):
        pm = QPixmap(size * scale, size * scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.scale(size * scale / 32.0, size * scale / 32.0)
        fn = DRAW.get(name, _unknown)
        fn(p)
        p.end()
        pm.setDevicePixelRatio(scale)
        ic.addPixmap(pm)
    _cache[key] = ic
    return ic


def pen(c=INK, w=1.6):
    pn = QPen(c, w)
    pn.setJoinStyle(Qt.RoundJoin)
    pn.setCapStyle(Qt.RoundCap)
    return pn


def poly(p, pts, fill=None, c=INK, w=1.6):
    p.setPen(pen(c, w))
    p.setBrush(fill if fill is not None else Qt.NoBrush)
    p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in pts]))


def page(p, x=7, y=4, w=18, h=24, fold=5):
    poly(p, [(x, y), (x + w - fold, y), (x + w, y + fold), (x + w, y + h), (x, y + h)], PAPER)
    p.drawLine(QPointF(x + w - fold, y), QPointF(x + w - fold, y + fold))
    p.drawLine(QPointF(x + w - fold, y + fold), QPointF(x + w, y + fold))


def lines(p, x, y, w, n, gap=3.2, c=INK):
    p.setPen(pen(c, 1.3))
    for i in range(n):
        p.drawLine(QPointF(x, y + i * gap), QPointF(x + (w if i < n - 1 else w * 0.65), y + i * gap))


def _unknown(p):
    p.setPen(pen())
    p.drawRect(QRectF(6, 6, 20, 20))


def d_paste(p):
    poly(p, [(6, 6), (22, 6), (22, 28), (6, 28)], QColor(214, 170, 110))
    p.setBrush(LIGHT)
    p.drawRoundedRect(QRectF(10, 3, 8, 6), 1.5, 1.5)
    page(p, 13, 12, 15, 17, 4)
    lines(p, 16, 19, 8, 3)


def d_cut(p):
    p.setPen(pen(INK, 1.8))
    p.drawLine(QPointF(10, 4), QPointF(21, 21))
    p.drawLine(QPointF(22, 4), QPointF(11, 21))
    p.setBrush(Qt.NoBrush)
    p.setPen(pen(BLUE, 2))
    p.drawEllipse(QRectF(5, 20, 8, 8))
    p.drawEllipse(QRectF(19, 20, 8, 8))


def d_copy(p):
    page(p, 5, 3, 15, 19, 4)
    page(p, 12, 10, 15, 19, 4)
    lines(p, 15, 18, 8, 3)


def d_painter(p):
    p.setPen(pen())
    p.setBrush(GOLD)
    p.drawRoundedRect(QRectF(5, 4, 20, 9), 2, 2)
    p.setBrush(Qt.NoBrush)
    p.drawLine(QPointF(25, 8), QPointF(28, 8))
    p.drawLine(QPointF(28, 8), QPointF(28, 16))
    p.drawLine(QPointF(28, 16), QPointF(16, 16))
    p.drawLine(QPointF(16, 16), QPointF(16, 19))
    p.setBrush(INK)
    p.drawRect(QRectF(14, 19, 4, 10))


def d_textbox(p):
    p.setPen(pen(INK, 1.4))
    p.setBrush(PAPER)
    p.drawRect(QRectF(4, 6, 24, 20))
    p.setPen(pen(BLUE, 1.3))
    for x, y in [(4, 6), (28, 6), (4, 26), (28, 26), (16, 6), (16, 26)]:
        p.setBrush(PAPER)
        p.drawRect(QRectF(x - 1.6, y - 1.6, 3.2, 3.2))
    f = QFont("Arial", 11, QFont.Bold)
    p.setFont(f)
    p.setPen(INK)
    p.drawText(QRectF(4, 6, 24, 20), Qt.AlignCenter, "A")


def d_picture(p):
    p.setPen(pen())
    p.setBrush(QColor(214, 234, 248))
    p.drawRect(QRectF(4, 6, 24, 20))
    poly(p, [(6, 24), (13, 13), (18, 20), (21, 16), (26, 24)], QColor(84, 160, 92), QColor(60, 120, 70), 1.2)
    p.setBrush(GOLD)
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(19, 9, 5, 5))


def d_shapes(p):
    p.setPen(pen())
    p.setBrush(QColor(120, 170, 225))
    p.drawRect(QRectF(4, 12, 13, 14))
    p.setBrush(QColor(240, 150, 110))
    p.drawEllipse(QRectF(14, 4, 14, 14))
    poly(p, [(22, 16), (29, 28), (15, 28)], GOLD)


def d_line(p):
    p.setPen(pen(INK, 2))
    p.drawLine(QPointF(5, 27), QPointF(27, 5))


def d_page_add(p):
    page(p, 6, 4, 17, 23)
    p.setPen(pen(TEAL, 2.4))
    p.drawLine(QPointF(24, 18), QPointF(24, 30))
    p.drawLine(QPointF(18, 24), QPointF(30, 24))


def d_page_dup(p):
    page(p, 4, 3, 15, 20, 4)
    page(p, 12, 9, 15, 20, 4)


def d_page_del(p):
    page(p, 6, 4, 17, 23)
    p.setPen(pen(RED, 2.4))
    p.drawLine(QPointF(19, 19), QPointF(29, 29))
    p.drawLine(QPointF(29, 19), QPointF(19, 29))


def d_forward(p):
    p.setPen(pen())
    p.setBrush(LIGHT)
    p.drawRect(QRectF(4, 12, 16, 16))
    p.setBrush(BLUE)
    p.drawRect(QRectF(12, 4, 16, 16))


def d_backward(p):
    p.setPen(pen())
    p.setBrush(BLUE)
    p.drawRect(QRectF(12, 4, 16, 16))
    p.setBrush(LIGHT)
    p.drawRect(QRectF(4, 12, 16, 16))


def d_align(p):
    p.setPen(pen(INK, 1.8))
    p.drawLine(QPointF(5, 3), QPointF(5, 29))
    p.setPen(pen())
    p.setBrush(BLUE)
    p.drawRect(QRectF(5, 7, 20, 7))
    p.setBrush(LIGHT)
    p.drawRect(QRectF(5, 18, 13, 7))


def d_rotate(p):
    p.setPen(pen(INK, 1.8))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(6, 6, 20, 20), 30 * 16, 280 * 16)
    poly(p, [(24, 3), (27, 11), (19, 10)], INK, INK, 1)


def d_group(p):
    p.setPen(pen(BLUE, 1.2))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(3, 3, 26, 26))
    p.setPen(pen())
    p.setBrush(LIGHT)
    p.drawRect(QRectF(7, 7, 11, 11))
    p.setBrush(GOLD)
    p.drawEllipse(QRectF(14, 14, 11, 11))


def d_select(p):
    poly(p, [(9, 4), (9, 26), (14, 21), (18, 29), (21, 28), (17, 20), (24, 20)], INK, INK, 1)


def d_bullets(p):
    p.setPen(Qt.NoPen)
    p.setBrush(INK)
    for i in range(3):
        p.drawEllipse(QRectF(4, 6 + i * 8, 4, 4))
    lines(p, 12, 8, 16, 3, 8)


def _align_lines(p, mode):
    p.setPen(pen(INK, 1.8))
    ws = [22, 14, 22, 16]
    for i, w in enumerate(ws):
        y = 7 + i * 6
        if mode == "left":
            x0 = 5
        elif mode == "right":
            x0 = 27 - w
        elif mode == "center":
            x0 = 16 - w / 2
        else:
            x0, w = 5, 22
        p.drawLine(QPointF(x0, y), QPointF(x0 + w, y))


def d_al(p):
    _align_lines(p, "left")


def d_ac(p):
    _align_lines(p, "center")


def d_ar(p):
    _align_lines(p, "right")


def d_aj(p):
    _align_lines(p, "justify")


def _font_glyph(p, txt, extra):
    f = QFont("Arial", 16, QFont.Bold)
    p.setFont(f)
    p.setPen(INK)
    p.drawText(QRectF(0, 4, 22, 26), Qt.AlignCenter, txt)
    extra(p)


def d_grow(p):
    _font_glyph(p, "A", lambda p: poly(p, [(22, 12), (30, 12), (26, 5)], TEAL, TEAL, 1))


def d_shrink(p):
    _font_glyph(p, "A", lambda p: poly(p, [(22, 6), (30, 6), (26, 13)], TEAL, TEAL, 1))


def d_fontcolor(p):
    f = QFont("Arial", 15, QFont.Bold)
    p.setFont(f)
    p.setPen(INK)
    p.drawText(QRectF(0, 0, 32, 24), Qt.AlignCenter, "A")


def d_fill(p):
    poly(p, [(8, 12), (17, 3), (26, 12), (17, 21)], PAPER)
    p.setBrush(QColor(110, 110, 110))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QRectF(24, 13, 5, 7))


def d_outline(p):
    poly(p, [(6, 22), (20, 8), (24, 12), (10, 26), (5, 27)], PAPER)
    p.drawLine(QPointF(17, 11), QPointF(21, 15))


def d_weight(p):
    p.setPen(Qt.NoPen)
    p.setBrush(INK)
    for i, h in enumerate([1, 2, 3.5, 5.5]):
        p.drawRect(QRectF(4, 5 + i * 6.5, 24, h))


def d_margins(p):
    page(p, 6, 3, 20, 26, 0.01)
    p.setPen(QPen(BLUE, 1.2, Qt.DashLine))
    p.drawRect(QRectF(10, 7, 12, 18))


def d_orient(p):
    page(p, 4, 6, 14, 20, 4)
    page(p, 13, 14, 16, 12, 4)


def d_size(p):
    page(p, 8, 5, 16, 22, 4)
    p.setPen(pen(TEAL, 1.6))
    p.drawLine(QPointF(4, 5), QPointF(4, 27))
    p.drawLine(QPointF(8, 30), QPointF(24, 30))


def d_background(p):
    p.setPen(pen())
    p.setBrush(QColor(140, 190, 230))
    p.drawRect(QRectF(6, 4, 20, 25))
    p.setBrush(PAPER)
    p.drawRect(QRectF(10, 9, 12, 9))


def d_guides(p):
    page(p, 6, 3, 20, 26, 0.01)
    p.setPen(QPen(TEAL, 1.2, Qt.DashLine))
    p.drawLine(QPointF(12, 3), QPointF(12, 29))
    p.drawLine(QPointF(6, 12), QPointF(26, 12))


def d_zoom_page(p):
    page(p, 8, 3, 16, 22, 4)
    p.setPen(pen(TEAL, 2))
    p.drawLine(QPointF(4, 29), QPointF(28, 29))


def d_zoom_width(p):
    page(p, 5, 6, 22, 22, 4)
    p.setPen(pen(TEAL, 2))
    poly(p, [(5, 3), (9, 1), (9, 5)], TEAL, TEAL, 1)
    poly(p, [(27, 3), (23, 1), (23, 5)], TEAL, TEAL, 1)


def d_zoom100(p):
    p.setPen(pen())
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(4, 4, 18, 18))
    p.setPen(pen(INK, 3))
    p.drawLine(QPointF(19, 19), QPointF(28, 28))
    f = QFont("Arial", 7, QFont.Bold)
    p.setFont(f)
    p.setPen(INK)
    p.drawText(QRectF(4, 4, 18, 18), Qt.AlignCenter, "100")


def d_zoom_in(p):
    d_zoom100(p) if False else None
    p.setPen(pen())
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(4, 4, 18, 18))
    p.setPen(pen(INK, 3))
    p.drawLine(QPointF(19, 19), QPointF(28, 28))
    p.setPen(pen(INK, 2))
    p.drawLine(QPointF(9, 13), QPointF(17, 13))
    p.drawLine(QPointF(13, 9), QPointF(13, 17))


def d_zoom_out(p):
    p.setPen(pen())
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(4, 4, 18, 18))
    p.setPen(pen(INK, 3))
    p.drawLine(QPointF(19, 19), QPointF(28, 28))
    p.setPen(pen(INK, 2))
    p.drawLine(QPointF(9, 13), QPointF(17, 13))


def d_vtop(p):
    p.setPen(pen())
    p.setBrush(PAPER)
    p.drawRect(QRectF(5, 4, 22, 24))
    lines(p, 9, 9, 14, 2, 4)


def d_vmid(p):
    p.setPen(pen())
    p.setBrush(PAPER)
    p.drawRect(QRectF(5, 4, 22, 24))
    lines(p, 9, 14, 14, 2, 4)


def d_vbot(p):
    p.setPen(pen())
    p.setBrush(PAPER)
    p.drawRect(QRectF(5, 4, 22, 24))
    lines(p, 9, 20, 14, 2, 4)


def d_change_pic(p):
    d_picture(p)
    p.setPen(pen(TEAL, 2))
    p.setBrush(PAPER)
    p.drawEllipse(QRectF(18, 18, 12, 12))
    p.drawLine(QPointF(21, 24), QPointF(27, 24))
    poly(p, [(25, 21), (28, 24), (25, 27)], None, TEAL, 1.6)


def d_reset(p):
    d_picture(p)
    p.setPen(pen(RED, 2))
    p.setBrush(Qt.NoBrush)
    p.drawArc(QRectF(17, 17, 12, 12), 60 * 16, 270 * 16)


def d_save(p):
    poly(p, [(5, 4), (24, 4), (28, 8), (28, 28), (5, 28)], TEAL, TEAL.darker(130), 1.4)
    p.setPen(Qt.NoPen)
    p.setBrush(PAPER)
    p.drawRect(QRectF(10, 4, 12, 8))
    p.drawRect(QRectF(9, 17, 15, 11))


def d_undo(p):
    p.setPen(pen(INK, 2.4))
    p.setBrush(Qt.NoBrush)
    path = QPainterPath(QPointF(8, 13))
    path.cubicTo(QPointF(16, 6), QPointF(28, 10), QPointF(25, 22))
    p.drawPath(path)
    poly(p, [(4, 8), (12, 7), (8, 16)], INK, INK, 1)


def d_redo(p):
    p.save()
    p.translate(32, 0)
    p.scale(-1, 1)
    d_undo(p)
    p.restore()


def d_new(p):
    page(p, 7, 3, 18, 26)


def d_open(p):
    poly(p, [(3, 8), (12, 8), (14, 11), (27, 11), (27, 27), (3, 27)], GOLD, QColor(170, 120, 30), 1.4)
    poly(p, [(6, 15), (30, 15), (27, 27), (3, 27)], QColor(250, 210, 110), QColor(170, 120, 30), 1.4)


def d_print(p):
    p.setPen(pen())
    p.setBrush(PAPER)
    p.drawRect(QRectF(9, 3, 14, 9))
    p.setBrush(QColor(150, 155, 165))
    p.drawRoundedRect(QRectF(3, 11, 26, 12), 2, 2)
    p.setBrush(PAPER)
    p.drawRect(QRectF(9, 19, 14, 10))


def d_export(p):
    page(p, 5, 3, 18, 25)
    p.setPen(pen(TEAL, 2.4))
    p.drawLine(QPointF(15, 18), QPointF(29, 18))
    poly(p, [(25, 13), (30, 18), (25, 23)], TEAL, TEAL, 1)


def d_pdf(p):
    page(p, 6, 3, 20, 26)
    p.setPen(Qt.NoPen)
    p.setBrush(RED)
    p.drawRect(QRectF(3, 16, 20, 9))
    f = QFont("Arial", 7, QFont.Bold)
    p.setFont(f)
    p.setPen(PAPER)
    p.drawText(QRectF(3, 16, 20, 9), Qt.AlignCenter, "PDF")


def d_image(p):
    d_picture(p)


def d_pub(p):
    p.setPen(Qt.NoPen)
    p.setBrush(TEAL)
    p.drawRoundedRect(QRectF(3, 6, 18, 20), 2, 2)
    page(p, 13, 3, 16, 24, 4)
    f = QFont("Arial", 11, QFont.Bold)
    p.setFont(f)
    p.setPen(PAPER)
    p.drawText(QRectF(3, 6, 12, 20), Qt.AlignCenter, "P")


def d_close(p):
    p.setPen(pen(INK, 2.4))
    p.drawLine(QPointF(8, 8), QPointF(24, 24))
    p.drawLine(QPointF(24, 8), QPointF(8, 24))


def d_back(p):
    p.setPen(pen(PAPER, 2.2))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(3, 3, 26, 26))
    p.drawLine(QPointF(10, 16), QPointF(23, 16))
    p.drawLine(QPointF(10, 16), QPointF(15, 11))
    p.drawLine(QPointF(10, 16), QPointF(15, 21))


def d_selectall(p):
    p.setPen(QPen(BLUE, 1.4, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(3, 3, 26, 26))
    p.setPen(pen())
    p.setBrush(LIGHT)
    p.drawRect(QRectF(8, 8, 9, 9))
    p.setBrush(GOLD)
    p.drawEllipse(QRectF(15, 15, 10, 10))


def d_info(p):
    p.setPen(pen(PAPER, 2))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(4, 4, 24, 24))
    f = QFont("Georgia", 14, QFont.Bold)
    p.setFont(f)
    p.drawText(QRectF(4, 4, 24, 24), Qt.AlignCenter, "i")


def d_flip_h(p):
    poly(p, [(14, 6), (14, 26), (4, 26)], LIGHT)
    poly(p, [(18, 6), (18, 26), (28, 26)], BLUE)


# ---- thin outline icons for the File menu (modern Office style) ----
LINE = QColor(50, 50, 50)


def _ln(p, w=2.0):
    pn = QPen(LINE, w)
    pn.setJoinStyle(Qt.RoundJoin)
    pn.setCapStyle(Qt.RoundCap)
    p.setPen(pn)
    p.setBrush(Qt.NoBrush)


def d_bs_back(p):
    _ln(p, 2.0)
    p.drawEllipse(QRectF(3, 3, 26, 26))
    p.drawLine(QPointF(9.5, 16), QPointF(22.5, 16))
    p.drawPolyline(QPolygonF([QPointF(14.5, 11), QPointF(9.5, 16), QPointF(14.5, 21)]))


def d_bs_home(p):
    _ln(p)
    p.drawPolyline(QPolygonF([QPointF(4, 15), QPointF(16, 4.5), QPointF(28, 15)]))
    p.drawPolyline(QPolygonF([QPointF(7.5, 12.5), QPointF(7.5, 27.5), QPointF(13, 27.5), QPointF(13, 19.5),
                              QPointF(19, 19.5), QPointF(19, 27.5), QPointF(24.5, 27.5), QPointF(24.5, 12.5)]))


def d_bs_new(p):
    _ln(p)
    p.drawEllipse(QRectF(4, 4, 24, 24))
    p.drawLine(QPointF(16, 10), QPointF(16, 22))
    p.drawLine(QPointF(10, 16), QPointF(22, 16))


def d_bs_open(p):
    _ln(p)
    p.drawPolyline(QPolygonF([QPointF(4, 25), QPointF(4, 7), QPointF(12, 7), QPointF(14.5, 10),
                              QPointF(25, 10), QPointF(25, 14)]))
    p.drawPolygon(QPolygonF([QPointF(4, 25.5), QPointF(8.5, 14.5), QPointF(29, 14.5), QPointF(24.5, 25.5)]))


def d_bs_info(p):
    _ln(p)
    p.drawEllipse(QRectF(4, 4, 24, 24))
    p.drawLine(QPointF(16, 14.5), QPointF(16, 22.5))
    p.setPen(Qt.NoPen)
    p.setBrush(LINE)
    p.drawEllipse(QPointF(16, 10), 1.6, 1.6)


def d_bs_save(p):
    _ln(p)
    p.drawPolygon(QPolygonF([QPointF(5, 5), QPointF(23, 5), QPointF(27, 9), QPointF(27, 27), QPointF(5, 27)]))
    p.drawPolyline(QPolygonF([QPointF(10, 5), QPointF(10, 11), QPointF(21, 11), QPointF(21, 5)]))
    p.drawPolyline(QPolygonF([QPointF(9, 27), QPointF(9, 18), QPointF(23, 18), QPointF(23, 27)]))


def d_bs_saveas(p):
    _ln(p)
    p.drawPolyline(QPolygonF([QPointF(16, 27), QPointF(5, 27), QPointF(5, 5), QPointF(23, 5), QPointF(27, 9),
                              QPointF(27, 13)]))
    p.drawPolyline(QPolygonF([QPointF(10, 5), QPointF(10, 11), QPointF(21, 11), QPointF(21, 5)]))
    p.drawPolyline(QPolygonF([QPointF(9, 27), QPointF(9, 18), QPointF(16, 18)]))
    p.drawPolygon(QPolygonF([QPointF(19, 28), QPointF(19.5, 24.5), QPointF(27.5, 16.5), QPointF(30.5, 19.5),
                             QPointF(22.5, 27.5)]))


def d_bs_print(p):
    _ln(p)
    p.drawPolyline(QPolygonF([QPointF(9, 11), QPointF(9, 4), QPointF(23, 4), QPointF(23, 11)]))
    p.drawRoundedRect(QRectF(4, 11, 24, 12), 2.5, 2.5)
    p.drawRect(QRectF(9, 18, 14, 10))


def d_bs_export(p):
    _ln(p)
    p.drawPolyline(QPolygonF([QPointF(20, 18), QPointF(20, 27), QPointF(5, 27), QPointF(5, 5), QPointF(15, 5),
                              QPointF(20, 10), QPointF(20, 13)]))
    p.drawLine(QPointF(13, 15.5), QPointF(29, 15.5))
    p.drawPolyline(QPolygonF([QPointF(25, 11.5), QPointF(29, 15.5), QPointF(25, 19.5)]))


def d_bs_close(p):
    _ln(p)
    p.drawRoundedRect(QRectF(4, 6, 24, 20), 2, 2)


def d_bs_options(p):
    _ln(p, 1.8)
    path = QPainterPath()
    n = 8
    for i in range(n * 2):
        a = math.pi * i / n
        r = 12 if i % 2 == 0 else 9.5
        pt = QPointF(16 + r * math.cos(a), 16 + r * math.sin(a))
        if i == 0:
            path.moveTo(pt)
        else:
            path.lineTo(pt)
    path.closeSubpath()
    p.drawPath(path)
    p.drawEllipse(QPointF(16, 16), 4, 4)


def d_bs_search(p):
    _ln(p, 2.2)
    p.drawEllipse(QRectF(5, 5, 15, 15))
    p.drawLine(QPointF(18, 18), QPointF(27, 27))


def d_bs_arrow(p):
    pn = QPen(TEAL.darker(110), 2.2)
    pn.setCapStyle(Qt.RoundCap)
    pn.setJoinStyle(Qt.RoundJoin)
    p.setPen(pn)
    p.drawLine(QPointF(5, 16), QPointF(27, 16))
    p.drawPolyline(QPolygonF([QPointF(20, 9), QPointF(27, 16), QPointF(20, 23)]))


def d_bs_chevron(p):
    _ln(p, 2.2)
    p.drawPolyline(QPolygonF([QPointF(9, 12), QPointF(16, 19), QPointF(23, 12)]))


def d_bs_pubfile(p):
    # document with a small teal PubDesign badge (recent files list)
    poly(p, [(8, 3), (21, 3), (27, 9), (27, 29), (8, 29)], PAPER, QColor(140, 140, 140), 1.2)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(200, 225, 220))
    p.drawRect(QRectF(13, 9, 10, 4))
    p.drawRect(QRectF(13, 16, 10, 2))
    p.drawRect(QRectF(13, 21, 7, 2))
    p.setBrush(TEAL)
    p.drawRoundedRect(QRectF(2, 15, 13, 13), 2.5, 2.5)
    p.setPen(QPen(PAPER, 1))
    f = QFont("Segoe UI", 8, QFont.Bold)
    p.setFont(f)
    p.drawText(QRectF(2, 15, 13, 13), Qt.AlignCenter, "P")


DRAW = {k[2:]: v for k, v in globals().items() if k.startswith("d_")}
