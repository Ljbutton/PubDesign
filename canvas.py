"""Page canvas: graphics items for every object kind, plus rendering helpers."""
import math

from PySide6.QtCore import Qt, QRectF, QPointF, QSizeF, Signal, QByteArray, QBuffer, QIODevice
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap,
                           QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument, QTextOption,
                           QTransform, QPolygonF)
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsObject, QGraphicsRectItem, QGraphicsScene,
                               QGraphicsTextItem, QStyleOptionGraphicsItem)

from pubmodel import Item, Para, Run
from pub_import import path_points
import autoshapes

TEXT_PAD = 2.88  # Publisher's default text-box inset (0.04 in)
HANDLE = 7.0
_DEV72 = None


def dev72():
    """A 72-dpi paint device so that 1 typographic point == 1 scene unit."""
    global _DEV72
    if _DEV72 is None:
        img = QImage(4, 4, QImage.Format_ARGB32)
        dpm = round(72 / 0.0254)
        img.setDotsPerMeterX(dpm)
        img.setDotsPerMeterY(dpm)
        _DEV72 = img
    return _DEV72


def qcolor(c):
    return QColor(*c) if c is not None else None


def tup(c):
    return (c.red(), c.green(), c.blue())


ALIGN_TO_QT = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight, "justify": Qt.AlignJustify}


def qt_to_align(a):
    if a & Qt.AlignHCenter:
        return "center"
    if a & Qt.AlignRight:
        return "right"
    if a & Qt.AlignJustify:
        return "justify"
    return "left"


def char_format(run):
    cf = QTextCharFormat()
    cf.setFontFamilies([run.font])
    cf.setFontPointSize(max(run.size, 1))
    cf.setFontWeight(QFont.Bold if run.bold else QFont.Normal)
    cf.setFontItalic(run.italic)
    cf.setFontUnderline(run.underline)
    cf.setForeground(QBrush(QColor(*run.color)))
    return cf


def fill_document(doc, paras):
    doc.clear()
    cur = QTextCursor(doc)
    cur.beginEditBlock()
    if not paras:
        paras = [Para([Run("")])]
    for i, p in enumerate(paras):
        bf = QTextBlockFormat()
        bf.setAlignment(ALIGN_TO_QT.get(p.align, Qt.AlignLeft))
        runs = p.runs or [Run("")]
        if i == 0:
            cur.setBlockFormat(bf)
        else:
            cur.insertBlock(bf, char_format(runs[0]))
        cur.setBlockCharFormat(char_format(runs[0]))
        cur.setCharFormat(char_format(runs[0]))
        for r in runs:
            if r.text:
                cur.insertText(r.text.replace("\n", " "), char_format(r))
    cur.endEditBlock()


def read_document(doc):
    paras = []
    block = doc.begin()
    while block.isValid():
        runs = []
        it = block.begin()
        while not it.atEnd():
            frag = it.fragment()
            if frag.isValid():
                runs.append(run_from_format(frag.charFormat(), frag.text().replace(" ", "\n")))
            it += 1
        if not runs:
            runs = [run_from_format(block.charFormat(), "")]
        paras.append(Para(runs, qt_to_align(block.blockFormat().alignment())))
        block = block.next()
    return paras


def run_from_format(cf, text):
    fams = cf.fontFamilies()
    fam = fams[0] if fams else (cf.font().family() or "Calibri")
    size = cf.fontPointSize() or cf.font().pointSizeF() or 12
    col = cf.foreground().color() if cf.foreground().style() != Qt.NoBrush else QColor(0, 0, 0)
    return Run(text, font=fam, size=round(size, 2), bold=cf.fontWeight() >= QFont.DemiBold,
               italic=cf.fontItalic(), underline=cf.fontUnderline(), color=tup(col))


def svg_path(d, view, w, h):
    path = QPainterPath()
    vx, vy, vw, vh = view
    sx = w / (vw or 1)
    sy = h / (vh or 1)
    for poly in path_points(d, steps=12):
        if len(poly) < 2:
            continue
        path.moveTo((poly[0][0] - vx) * sx, (poly[0][1] - vy) * sy)
        for x, y in poly[1:]:
            path.lineTo((x - vx) * sx, (y - vy) * sy)
    return path


class TextChild(QGraphicsTextItem):
    def __init__(self, shape):
        super().__init__(shape)
        self.shape_item = shape
        self.document().documentLayout().setPaintDevice(dev72())
        self.document().setDocumentMargin(0)
        opt = self.document().defaultTextOption()
        opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(opt)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.document().contentsChanged.connect(shape.relayout_text)

    def focusOutEvent(self, ev):
        super().focusOutEvent(ev)
        if ev.reason() != Qt.PopupFocusReason:
            self.shape_item.end_edit()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.clearFocus()
            self.shape_item.end_edit()
            return
        super().keyPressEvent(ev)


class ShapeItem(QGraphicsObject):
    """One page object. Geometry: pos() = top-left, (w, h) = size, rotation about centre."""
    committed = Signal()
    editingChanged = Signal(bool)

    H_TL, H_T, H_TR, H_R, H_BR, H_B, H_BL, H_L, H_ROT, H_P1, H_P2 = range(11)

    def __init__(self, item: Item, editable=True):
        super().__init__()
        self.kind = item.kind
        self.w = item.w
        self.h = item.h
        self.fill = item.fill
        self.stroke = item.stroke
        self.stroke_width = item.stroke_width
        self.valign = item.valign
        self.image = item.image
        self.image_name = item.image_name
        self.path_d = item.path_d
        self.view = item.view
        self.spt = getattr(item, "spt", 0)
        self.pixmap = None
        self.editable = editable
        self.export_mode = not editable
        self._drag = None
        self.text = None
        if self.kind == "image" and self.image:
            img = QImage.fromData(self.image)
            self.pixmap = QPixmap.fromImage(img) if not img.isNull() else None
        if editable:
            self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable |
                          QGraphicsItem.ItemSendsGeometryChanges | QGraphicsItem.ItemIsFocusable)
            self.setAcceptHoverEvents(True)
        if self.kind == "text":
            self.text = TextChild(self)
            fill_document(self.text.document(), item.paras)
            self.setFlag(QGraphicsItem.ItemClipsChildrenToShape, True)
        self.setPos(item.x, item.y)
        self.setRotation(item.rotation)
        self._update_origin()
        self.relayout_text()

    # ---- model -----------------------------------------------------------
    def to_model(self):
        it = Item(kind=self.kind, x=self.pos().x(), y=self.pos().y(), w=self.w, h=self.h,
                  rotation=self.rotation(), fill=self.fill, stroke=self.stroke, stroke_width=self.stroke_width,
                  valign=self.valign, image=self.image, image_name=self.image_name,
                  path_d=self.path_d, view=self.view, spt=self.spt)
        if self.kind == "text":
            it.paras = read_document(self.text.document())
        return it

    # ---- geometry --------------------------------------------------------
    def _update_origin(self):
        if self.kind == "line":
            self.setTransformOriginPoint(0, 0)
        else:
            self.setTransformOriginPoint(self.w / 2, self.h / 2)

    def local_rect(self):
        return QRectF(0, 0, self.w, self.h).normalized()

    def boundingRect(self):
        pad = max(self.stroke_width, 1) / 2 + (HANDLE + 18 if self.isSelected() else 2)
        return self.local_rect().adjusted(-pad, -pad, pad, pad)

    def shape(self):
        p = QPainterPath()
        r = self.local_rect()
        if self.kind == "line":
            stroker = QPainterPath()
            stroker.moveTo(0, 0)
            stroker.lineTo(self.w, self.h)
            from PySide6.QtGui import QPainterPathStroker
            s = QPainterPathStroker()
            s.setWidth(max(self.stroke_width, 8))
            p = s.createStroke(stroker)
        else:
            p.addRect(r)
        if self.isSelected() and self.editable:
            for hr in self.handle_rects().values():
                p.addRect(hr)
        return p

    def set_geometry(self, x, y, w, h):
        self.prepareGeometryChange()
        self.w, self.h = w, h
        self._update_origin()
        self.setPos(x, y)
        self.relayout_text()
        self.update()

    def relayout_text(self):
        if self.text is None:
            return
        tw = max(self.w - 2 * TEXT_PAD, 4)
        self.text.setTextWidth(tw)
        dh = self.text.document().size().height()
        avail = self.h - 2 * TEXT_PAD
        y = TEXT_PAD
        if self.valign == "middle":
            y = TEXT_PAD + (avail - dh) / 2
        elif self.valign == "bottom":
            y = TEXT_PAD + avail - dh
        self.text.setPos(TEXT_PAD, max(y, TEXT_PAD) if self.valign != "top" else TEXT_PAD)
        self.update()

    def overflowing(self):
        return self.text is not None and self.text.document().size().height() > self.h - 2 * TEXT_PAD + 0.5

    # ---- painting --------------------------------------------------------
    def paint(self, painter, option, widget=None):
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        r = QRectF(0, 0, self.w, self.h)
        pen = QPen(QColor(*self.stroke), self.stroke_width) if self.stroke else Qt.NoPen
        if pen != Qt.NoPen:
            pen.setJoinStyle(Qt.MiterJoin)
        brush = QBrush(QColor(*self.fill)) if self.fill else Qt.NoBrush
        k = self.kind
        if k == "rect" or k == "text":
            painter.setPen(pen)
            painter.setBrush(brush)
            painter.drawRect(r.normalized())
        elif k == "ellipse":
            painter.setPen(pen)
            painter.setBrush(brush)
            painter.drawEllipse(r.normalized())
        elif k == "line":
            lp = QPen(QColor(*(self.stroke or (0, 0, 0))), self.stroke_width)
            lp.setCapStyle(Qt.FlatCap)
            painter.setPen(lp)
            painter.drawLine(QPointF(0, 0), QPointF(self.w, self.h))
        elif k == "path":
            painter.setPen(pen)
            painter.setBrush(brush)
            painter.drawPath(svg_path(self.path_d, self.view, self.w, self.h))
        elif k == "auto":
            painter.setPen(pen)
            painter.setBrush(brush)
            painter.drawPath(autoshapes.outline(self.spt, self.w, self.h))
        elif k == "image":
            if self.pixmap:
                painter.drawPixmap(r.normalized(), self.pixmap, QRectF(self.pixmap.rect()))
            else:
                painter.setPen(QPen(QColor(150, 150, 150), 1, Qt.DashLine))
                painter.setBrush(QColor(235, 235, 235))
                painter.drawRect(r.normalized())
                painter.drawText(r.normalized(), Qt.AlignCenter, "Picture")
            if self.stroke:
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(r.normalized())
        if self.export_mode:
            return
        sel = self.isSelected()
        sc = self.scene()
        show_bounds = getattr(sc, "show_boundaries", True) if sc is not None else True
        if k == "text" and not sel and not self.fill and not self.stroke and show_bounds:
            p = QPen(QColor(150, 150, 150, 120), 0, Qt.DotLine)
            p.setCosmetic(True)
            painter.setPen(p)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(r.normalized())
        if sel:
            p = QPen(QColor(30, 120, 230), 0, Qt.DashLine)
            p.setCosmetic(True)
            painter.setPen(p)
            painter.setBrush(Qt.NoBrush)
            if k != "line":
                painter.drawRect(r.normalized())
            painter.setPen(QPen(QColor(30, 120, 230), 0))
            for hid, hr in self.handle_rects().items():
                painter.setBrush(QColor(255, 255, 255))
                if hid == self.H_ROT:
                    painter.drawEllipse(hr)
                    top = QPointF(self.w / 2, min(0, self.h))
                    painter.drawLine(QPointF(hr.center().x(), hr.bottom()), top)
                else:
                    painter.drawRect(hr)
            if self.overflowing():
                br = r.normalized()
                box = QRectF(br.right() - 14, br.bottom() + 4, 14, 14)
                painter.setBrush(QColor(220, 60, 50))
                painter.setPen(Qt.NoPen)
                painter.drawRect(box)
                painter.setPen(QPen(QColor(255, 255, 255), 1.5))
                painter.drawLine(QPointF(box.center().x(), box.top() + 3), QPointF(box.center().x(), box.bottom() - 3))
                painter.drawLine(QPointF(box.left() + 3, box.center().y()), QPointF(box.right() - 3, box.center().y()))

    def handle_scale(self):
        sc = self.scene()
        if sc and sc.views():
            m = sc.views()[0].transform().m11()
            return 1 / max(m, 0.05)
        return 1.0

    def handle_rects(self):
        s = HANDLE * self.handle_scale()
        hs = s / 2
        if self.kind == "line":
            return {self.H_P1: QRectF(-hs, -hs, s, s), self.H_P2: QRectF(self.w - hs, self.h - hs, s, s)}
        r = QRectF(0, 0, self.w, self.h).normalized()
        pts = {
            self.H_TL: r.topLeft(), self.H_T: QPointF(r.center().x(), r.top()), self.H_TR: r.topRight(),
            self.H_R: QPointF(r.right(), r.center().y()), self.H_BR: r.bottomRight(),
            self.H_B: QPointF(r.center().x(), r.bottom()), self.H_BL: r.bottomLeft(),
            self.H_L: QPointF(r.left(), r.center().y()),
        }
        out = {k: QRectF(p.x() - hs, p.y() - hs, s, s) for k, p in pts.items()}
        out[self.H_ROT] = QRectF(r.center().x() - hs, r.top() - 3.2 * s - hs, s, s)
        return out

    def handle_at(self, local_pos):
        if not (self.isSelected() and self.editable):
            return None
        for hid, hr in self.handle_rects().items():
            if hr.adjusted(-2, -2, 2, 2).contains(local_pos):
                return hid
        return None

    # ---- interaction -----------------------------------------------------
    def hoverMoveEvent(self, ev):
        h = self.handle_at(ev.pos())
        cursors = {self.H_TL: Qt.SizeFDiagCursor, self.H_BR: Qt.SizeFDiagCursor, self.H_TR: Qt.SizeBDiagCursor,
                   self.H_BL: Qt.SizeBDiagCursor, self.H_T: Qt.SizeVerCursor, self.H_B: Qt.SizeVerCursor,
                   self.H_L: Qt.SizeHorCursor, self.H_R: Qt.SizeHorCursor, self.H_ROT: Qt.CrossCursor,
                   self.H_P1: Qt.SizeAllCursor, self.H_P2: Qt.SizeAllCursor}
        if h is not None:
            self.setCursor(cursors[h])
        elif self.text is not None and self.text.textInteractionFlags() & Qt.TextEditorInteraction:
            self.setCursor(Qt.IBeamCursor)
        else:
            self.setCursor(Qt.SizeAllCursor if self.isSelected() else Qt.ArrowCursor)
        super().hoverMoveEvent(ev)

    def mousePressEvent(self, ev):
        h = self.handle_at(ev.pos())
        if h is not None and ev.button() == Qt.LeftButton:
            self._drag = (h, QRectF(0, 0, self.w, self.h), self.sceneTransform(), self.pos(), self.rotation(),
                          ev.scenePos())
            ev.accept()
            return
        self._drag = None
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if not self._drag:
            super().mouseMoveEvent(ev)
            return
        h, r0, t0, pos0, rot0, sp0 = self._drag
        sp = ev.scenePos()
        if h == self.H_ROT:
            c = t0.map(QPointF(r0.width() / 2, r0.height() / 2))
            ang = math.degrees(math.atan2(sp.y() - c.y(), sp.x() - c.x())) + 90
            if ev.modifiers() & Qt.ShiftModifier:
                ang = round(ang / 15) * 15
            self.setRotation(ang % 360)
            return
        if h in (self.H_P1, self.H_P2):
            p1 = pos0
            p2 = pos0 + QPointF(r0.width(), r0.height())
            if ev.modifiers() & Qt.ShiftModifier:
                other = p2 if h == self.H_P1 else p1
                dx, dy = sp.x() - other.x(), sp.y() - other.y()
                ang = round(math.degrees(math.atan2(dy, dx)) / 45) * 45
                ln = math.hypot(dx, dy)
                sp = QPointF(other.x() + ln * math.cos(math.radians(ang)), other.y() + ln * math.sin(math.radians(ang)))
            if h == self.H_P1:
                p1 = sp
            else:
                p2 = sp
            self.set_geometry(p1.x(), p1.y(), p2.x() - p1.x(), p2.y() - p1.y())
            return
        inv, ok = t0.inverted()
        lp = inv.map(sp)
        x0, y0, x1, y1 = r0.left(), r0.top(), r0.right(), r0.bottom()
        if h in (self.H_TL, self.H_L, self.H_BL):
            x0 = min(lp.x(), x1 - 2)
        if h in (self.H_TR, self.H_R, self.H_BR):
            x1 = max(lp.x(), x0 + 2)
        if h in (self.H_TL, self.H_T, self.H_TR):
            y0 = min(lp.y(), y1 - 2)
        if h in (self.H_BL, self.H_B, self.H_BR):
            y1 = max(lp.y(), y0 + 2)
        keep = (self.kind == "image") != bool(ev.modifiers() & Qt.ShiftModifier)
        if keep and h in (self.H_TL, self.H_TR, self.H_BL, self.H_BR) and r0.width() > 0 and r0.height() > 0:
            ratio = r0.width() / r0.height()
            nw, nh = x1 - x0, y1 - y0
            if nw / nh > ratio:
                nw = nh * ratio
            else:
                nh = nw / ratio
            if h in (self.H_TL, self.H_BL):
                x0 = x1 - nw
            else:
                x1 = x0 + nw
            if h in (self.H_TL, self.H_TR):
                y0 = y1 - nh
            else:
                y1 = y0 + nh
        fixed_local = QPointF(r0.left() if x0 == r0.left() else r0.right(),
                              r0.top() if y0 == r0.top() else r0.bottom())
        fixed_scene = t0.map(fixed_local)
        nw, nh = x1 - x0, y1 - y0
        self.prepareGeometryChange()
        self.w, self.h = nw, nh
        self._update_origin()
        self.setPos(pos0)
        new_fixed_local = fixed_local - QPointF(x0, y0)
        now = self.mapToScene(new_fixed_local)
        self.setPos(self.pos() + (fixed_scene - now))
        self.relayout_text()
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._drag:
            self._drag = None
            self.committed.emit()
            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if self.kind == "text" and self.editable:
            self.begin_edit(ev.scenePos())
            return
        super().mouseDoubleClickEvent(ev)

    def is_editing(self):
        return self.text is not None and bool(self.text.textInteractionFlags() & Qt.TextEditorInteraction)

    def begin_edit(self, scene_pos=None):
        if self.text is None:
            return
        self.setFlag(QGraphicsItem.ItemIsMovable, False)
        self.text.setTextInteractionFlags(Qt.TextEditorInteraction)
        self.text.setFocus(Qt.MouseFocusReason)
        cur = self.text.textCursor()
        if scene_pos is not None:
            p = self.text.mapFromScene(scene_pos)
            pos = self.text.document().documentLayout().hitTest(p, Qt.FuzzyHit)
            if pos >= 0:
                cur.setPosition(pos)
        else:
            cur.select(QTextCursor.Document)
        self.text.setTextCursor(cur)
        self.editingChanged.emit(True)

    def end_edit(self):
        if self.text is None or not self.is_editing():
            return
        cur = self.text.textCursor()
        cur.clearSelection()
        self.text.setTextCursor(cur)
        self.text.setTextInteractionFlags(Qt.NoTextInteraction)
        self.setFlag(QGraphicsItem.ItemIsMovable, True)
        self.editingChanged.emit(False)
        self.committed.emit()

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedChange:
            self.prepareGeometryChange()
            if not value:
                self.end_edit()
        return super().itemChange(change, value)


class PageScene(QGraphicsScene):
    def __init__(self, doc_w, doc_h, show_guides=True, export=False, margin=36):
        super().__init__()
        self.doc_w, self.doc_h = doc_w, doc_h
        self.export = export
        self.show_guides = show_guides
        self.show_boundaries = True
        self.margin = margin
        pad = max(doc_w, doc_h) * 0.6 + 200
        self.setSceneRect(-pad, -pad, doc_w + 2 * pad, doc_h + 2 * pad)
        self.setItemIndexMethod(QGraphicsScene.NoIndex)
        self.setBackgroundBrush(QColor(232, 233, 237) if not export else QColor(255, 255, 255))

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        page = QRectF(0, 0, self.doc_w, self.doc_h)
        if not self.export:
            painter.fillRect(page.translated(3, 3), QColor(0, 0, 0, 40))
        painter.fillRect(page, QColor(255, 255, 255))

    def drawForeground(self, painter, rect):
        if self.export or not self.show_guides:
            return
        m = self.margin
        p = QPen(QColor(120, 160, 230, 150), 0, Qt.DashLine)
        p.setCosmetic(True)
        painter.setPen(p)
        painter.setBrush(Qt.NoBrush)
        painter.drawRect(QRectF(m, m, self.doc_w - 2 * m, self.doc_h - 2 * m))
        p2 = QPen(QColor(150, 150, 150, 120), 0)
        p2.setCosmetic(True)
        painter.setPen(p2)
        painter.drawRect(QRectF(0, 0, self.doc_w, self.doc_h))

    def shapes(self):
        """Shape items in paint order (bottom first)."""
        items = [i for i in self.items() if isinstance(i, ShapeItem)]
        items.sort(key=lambda i: i.zValue())
        return items


def build_scene(page, doc, export=True, show_guides=False, margin=36):
    sc = PageScene(doc.width, doc.height, show_guides=show_guides, export=export, margin=margin)
    for z, it in enumerate(page.items):
        si = ShapeItem(it, editable=not export)
        si.setZValue(z)
        sc.addItem(si)
    return sc


def render_page(painter, page, doc, target=None):
    sc = build_scene(page, doc, export=True)
    src = QRectF(0, 0, doc.width, doc.height)
    sc.render(painter, target or src, src)
    sc.clear()


def page_image(page, doc, width_px):
    scale = width_px / doc.width
    img = QImage(max(int(round(doc.width * scale)), 1), max(int(round(doc.height * scale)), 1), QImage.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    render_page(p, page, doc, QRectF(0, 0, img.width(), img.height()))
    p.end()
    return img


def item_to_png(item, scale=4.0):
    """Rasterise one item (used for shapes the .pub format cannot hold natively)."""
    from pubmodel import Item as _I
    w = max(abs(item.w), 1)
    h = max(abs(item.h), 1)
    pad = item.stroke_width
    img = QImage(int((w + 2 * pad) * scale), int((h + 2 * pad) * scale), QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(scale, scale)
    p.translate(pad, pad)
    clone = _I(**{**item.__dict__})
    clone.rotation = 0
    clone.x = clone.y = 0
    si = ShapeItem(clone, editable=False)
    si.paint(p, QStyleOptionGraphicsItem(), None)
    p.end()
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba), pad


def image_to_png(data):
    img = QImage.fromData(data)
    if img.isNull():
        return None
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)
