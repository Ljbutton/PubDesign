"""Generates PubDesign's temporary logo: assets/logo.png, assets/PubDesign.ico, assets/wordmark.png."""
import io
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt, QRectF, QPointF, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import (QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPolygonF)

TEAL_TOP = QColor(16, 150, 132)
TEAL_BOT = QColor(5, 88, 78)
GOLD = QColor(246, 190, 59)
CORAL = QColor(239, 99, 81)
WHITE = QColor(255, 255, 255)
INK = QColor(7, 90, 80)


def draw_mark(p, s):
    """Logo mark in an s × s box."""
    p.setRenderHint(QPainter.Antialiasing)
    r = s * 0.22
    g = QLinearGradient(0, 0, 0, s)
    g.setColorAt(0, TEAL_TOP)
    g.setColorAt(1, TEAL_BOT)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(QRectF(s * 0.03, s * 0.03, s * 0.94, s * 0.94), r, r)
    # page with folded corner, slightly tilted
    p.save()
    p.translate(s * 0.5, s * 0.52)
    p.rotate(-6)
    w, h = s * 0.52, s * 0.64
    fold = s * 0.13
    x0, y0 = -w / 2, -h / 2
    shadow = QPainterPath()
    shadow.addRoundedRect(QRectF(x0 + s * 0.025, y0 + s * 0.03, w, h), s * 0.03, s * 0.03)
    p.setBrush(QColor(0, 0, 0, 55))
    p.drawPath(shadow)
    page = QPolygonF([QPointF(x0, y0), QPointF(x0 + w - fold, y0), QPointF(x0 + w, y0 + fold),
                      QPointF(x0 + w, y0 + h), QPointF(x0, y0 + h)])
    p.setBrush(WHITE)
    p.drawPolygon(page)
    p.setBrush(QColor(200, 225, 220))
    p.drawPolygon(QPolygonF([QPointF(x0 + w - fold, y0), QPointF(x0 + w - fold, y0 + fold), QPointF(x0 + w, y0 + fold)]))
    # layout blocks: header band, picture, text lines
    m = s * 0.06
    p.setBrush(GOLD)
    p.drawRoundedRect(QRectF(x0 + m, y0 + m * 1.1, w - 2 * m - fold * 0.7, s * 0.11), s * 0.015, s * 0.015)
    p.setBrush(CORAL)
    p.drawEllipse(QRectF(x0 + m, y0 + s * 0.24, s * 0.15, s * 0.15))
    p.setBrush(INK)
    lw = s * 0.035
    for i, frac in enumerate([1.0, 1.0, 0.75]):
        y = y0 + s * 0.25 + i * s * 0.06
        p.drawRoundedRect(QRectF(x0 + m + s * 0.19, y, (w - 2 * m - s * 0.19) * frac, lw), lw / 2, lw / 2)
    for i, frac in enumerate([1.0, 0.9, 0.6]):
        y = y0 + s * 0.44 + i * s * 0.06
        p.drawRoundedRect(QRectF(x0 + m, y, (w - 2 * m) * frac, lw), lw / 2, lw / 2)
    p.restore()


def mark_image(s):
    img = QImage(s, s, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    draw_mark(p, s)
    p.end()
    return img


def png_bytes(img):
    ba = QByteArray()
    b = QBuffer(ba)
    b.open(QIODevice.WriteOnly)
    img.save(b, "PNG")
    return bytes(ba)


def main(out):
    app = QGuiApplication(sys.argv)
    os.makedirs(out, exist_ok=True)
    big = mark_image(512)
    big.save(os.path.join(out, "logo.png"))
    from PIL import Image
    imgs = {}
    for sz in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        imgs[sz] = Image.open(io.BytesIO(png_bytes(mark_image(sz * 4).scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)))).convert("RGBA")
    imgs[256].save(os.path.join(out, "PubDesign.ico"), sizes=[(k, k) for k in sorted(imgs)],
                   append_images=[imgs[k] for k in sorted(imgs) if k != 256])
    # wordmark for README / about box
    W, H = 1260, 300
    wm = QImage(W, H, QImage.Format_ARGB32)
    wm.fill(Qt.transparent)
    p = QPainter(wm)
    p.setRenderHint(QPainter.Antialiasing)
    p.save()
    p.translate(20, 20)
    draw_mark(p, 260)
    p.restore()
    f = QFont("DejaVu Sans", 100, QFont.Bold)
    p.setFont(f)
    p.setPen(QColor(30, 36, 44))
    p.drawText(QRectF(310, 0, 520, H), Qt.AlignVCenter | Qt.AlignLeft, "Pub")
    fm_w = p.fontMetrics().horizontalAdvance("Pub")
    p.setPen(TEAL_BOT)
    p.drawText(QRectF(310 + fm_w, 0, 800, H), Qt.AlignVCenter | Qt.AlignLeft, "Design")
    p.end()
    wm.save(os.path.join(out, "wordmark.png"))
    print("logo written to", out)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "assets")
