"""Office-style ribbon, colour picker menus, shape gallery and rulers."""
from PySide6.QtCore import Qt, Signal, QSize, QRectF, QPointF
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QFont, QAction
from PySide6.QtWidgets import (QWidget, QFrame, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QToolButton, QStackedWidget, QMenu, QWidgetAction, QSizePolicy, QPushButton)

import icons
import autoshapes

ACCENT = "#077568"
ACCENT_DARK = "#055a50"

RIBBON_QSS = f"""
#RibbonBar {{ background: #f3f3f3; border-bottom: 1px solid #d6d6d6; }}
#RibbonTab {{ background: transparent; padding: 6px 14px 5px 14px; margin: 0 1px; border: 1px solid transparent;
    color: #333; font-size: 9.5pt; }}
#RibbonTab:checked {{ background: #ffffff; border: 1px solid #d6d6d6; border-bottom-color: #ffffff; color: {ACCENT}; }}
#RibbonTab:hover:!checked {{ background: #e6e6e6; }}
#RibbonTab[contextual="true"] {{ color: {ACCENT}; font-weight: 600; }}
#RibbonTab[contextual="true"]:!checked {{ background: #e3f1ef; }}
#RibbonPanel {{ background: #ffffff; border-top: 1px solid #d6d6d6; }}
#RibbonGroup {{ background: transparent; }}
#RibbonGroupTitle {{ color: #666; font-size: 8pt; }}
#RibbonSep {{ background: #e1e1e1; }}
QToolButton[ribbon="large"] {{ border: 1px solid transparent; border-radius: 2px; padding: 2px; font-size: 8.5pt; }}
QToolButton[ribbon="small"] {{ border: 1px solid transparent; border-radius: 2px; padding: 1px 3px; text-align: left; font-size: 8.5pt; }}
QToolButton[ribbon]:hover {{ background: #e5f1ef; border-color: #b7d9d4; }}
QToolButton[ribbon]:checked {{ background: #cfe6e2; border-color: #8cc4bb; }}
QToolButton[ribbon]:pressed {{ background: #b8dbd5; }}
QToolButton[ribbon]::menu-indicator {{ image: none; }}
QToolButton[ribbon]::menu-button {{ border: none; width: 12px; }}
#FileButton {{ background: {ACCENT}; color: white; border: none; padding: 6px 18px; font-size: 9.5pt; }}
#FileButton:hover {{ background: {ACCENT_DARK}; }}
#QAT QToolButton {{ border: none; padding: 2px; }}
#QAT QToolButton:hover {{ background: #e0e0e0; }}
"""


def large_button(text, icon_name=None, slot=None, menu=None, checkable=False, tip=None):
    b = QToolButton()
    b.setProperty("ribbon", "large")
    b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
    b.setIconSize(QSize(32, 32))
    if icon_name:
        b.setIcon(icons.icon(icon_name, 32))
    b.setText(text + (" ▾" if menu is not None and slot is None else ""))
    b.setMinimumWidth(52)
    b.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    if tip:
        b.setToolTip(tip)
    if menu is not None:
        b.setMenu(menu)
        b.setPopupMode(QToolButton.InstantPopup if slot is None else QToolButton.MenuButtonPopup)
    if slot:
        b.clicked.connect(slot)
    return b


def small_button(text, icon_name=None, slot=None, menu=None, checkable=False, tip=None, text_visible=True):
    b = QToolButton()
    b.setProperty("ribbon", "small")
    b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if text_visible and text else Qt.ToolButtonIconOnly)
    b.setIconSize(QSize(16, 16))
    if icon_name:
        b.setIcon(icons.icon(icon_name, 16))
    b.setText(text + (" ▾" if menu is not None and slot is None and text_visible and text else ""))
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setToolTip(tip or text)
    if menu is not None:
        b.setMenu(menu)
        b.setPopupMode(QToolButton.InstantPopup if slot is None else QToolButton.MenuButtonPopup)
    if slot:
        b.clicked.connect(slot)
    return b


class RibbonGroup(QWidget):
    def __init__(self, title):
        super().__init__()
        self.setObjectName("RibbonGroup")
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 2, 4, 1)
        v.setSpacing(0)
        self.body = QHBoxLayout()
        self.body.setSpacing(2)
        self.body.setContentsMargins(0, 0, 0, 0)
        v.addLayout(self.body, 1)
        t = QLabel(title)
        t.setObjectName("RibbonGroupTitle")
        t.setAlignment(Qt.AlignHCenter)
        v.addWidget(t)

    def add(self, w):
        self.body.addWidget(w)
        return w

    def column(self, *widgets, rows=3):
        col = QVBoxLayout()
        col.setSpacing(1)
        col.setContentsMargins(0, 0, 0, 0)
        for w in widgets:
            if isinstance(w, (list, tuple)):
                row = QHBoxLayout()
                row.setSpacing(1)
                for x in w:
                    row.addWidget(x)
                row.addStretch()
                col.addLayout(row)
            else:
                col.addWidget(w)
        col.addStretch()
        self.body.addLayout(col)


class RibbonPage(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("RibbonPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.h = QHBoxLayout(self)
        self.h.setContentsMargins(4, 3, 4, 2)
        self.h.setSpacing(0)
        self._first = True
        self.h.addStretch()

    def group(self, title):
        g = RibbonGroup(title)
        idx = self.h.count() - 1
        if not self._first:
            sep = QFrame()
            sep.setObjectName("RibbonSep")
            sep.setFixedWidth(1)
            self.h.insertWidget(idx, sep)
            idx += 1
        self._first = False
        self.h.insertWidget(idx, g)
        return g


class _Tabs:
    """Minimal tab-bar stand-in built from checkable buttons (never clips or scrolls)."""

    def __init__(self, layout, on_change):
        self.layout = layout
        self.buttons = []
        self.on_change = on_change
        self._cur = -1

    def addTab(self, title):
        b = QToolButton()
        b.setObjectName("RibbonTab")
        b.setText(title)
        b.setCheckable(True)
        b.setAutoRaise(True)
        i = len(self.buttons)
        b.clicked.connect(lambda _=False, k=i: self.setCurrentIndex(k))
        self.layout.addWidget(b)
        self.buttons.append(b)
        return i

    def setTabVisible(self, i, v):
        self.buttons[i].setVisible(v)

    def isTabVisible(self, i):
        return not self.buttons[i].isHidden()

    def setTabTextColor(self, i, c):
        self.buttons[i].setProperty("contextual", True)

    def tabText(self, i):
        return self.buttons[i].text()

    def count(self):
        return len(self.buttons)

    def currentIndex(self):
        return self._cur

    def setCurrentIndex(self, i):
        self._cur = i
        for k, b in enumerate(self.buttons):
            b.setChecked(k == i)
        self.on_change(i)


class Ribbon(QWidget):
    fileClicked = Signal()

    def __init__(self):
        super().__init__()
        self.setObjectName("RibbonBar")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top = QWidget()
        top.setObjectName("RibbonTabs")
        th = QHBoxLayout(top)
        th.setContentsMargins(0, 0, 0, 0)
        th.setSpacing(0)
        self.file_btn = QPushButton("File")
        self.file_btn.setObjectName("FileButton")
        self.file_btn.setCursor(Qt.PointingHandCursor)
        self.file_btn.clicked.connect(self.fileClicked)
        th.addWidget(self.file_btn)
        th.addSpacing(4)
        tabrow = QHBoxLayout()
        tabrow.setSpacing(0)
        th.addLayout(tabrow)
        th.addStretch()
        self.right = QHBoxLayout()
        th.addLayout(self.right)
        v.addWidget(top)
        self.stack = QStackedWidget()
        self.stack.setFixedHeight(100)
        v.addWidget(self.stack)
        self.tabs = _Tabs(tabrow, self.stack.setCurrentIndex)
        self.contextual = {}

    def add_page(self, title, contextual=False):
        page = RibbonPage()
        self.stack.addWidget(page)
        i = self.tabs.addTab(title)
        if contextual:
            self.tabs.setTabTextColor(i, QColor(ACCENT))
            self.tabs.setTabVisible(i, False)
            self.contextual[title] = i
        return page

    def set_contextual(self, visible_titles):
        cur = self.tabs.currentIndex()
        for title, i in self.contextual.items():
            self.tabs.setTabVisible(i, title in visible_titles)
        if cur in self.contextual.values() and not self.tabs.isTabVisible(cur):
            self.tabs.setCurrentIndex(0)

    def select(self, title):
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == title:
                self.tabs.setCurrentIndex(i)


# ---------------------------------------------------------------------------
# colour menu
# ---------------------------------------------------------------------------
THEME = [(255, 255, 255), (0, 0, 0), (231, 230, 230), (68, 84, 106), (68, 114, 196), (237, 125, 49),
         (165, 165, 165), (255, 192, 0), (91, 155, 213), (112, 173, 71)]
STANDARD = [(192, 0, 0), (255, 0, 0), (255, 192, 0), (255, 255, 0), (146, 208, 80), (0, 176, 80),
            (0, 176, 240), (0, 112, 192), (0, 32, 96), (112, 48, 160)]


def tint(c, f):
    r, g, b = c
    if f >= 0:
        return tuple(int(x + (255 - x) * f) for x in c)
    return tuple(int(x * (1 + f)) for x in c)


def swatch_icon(c, size=14):
    pm = QPixmap(size, size)
    pm.fill(QColor(*c))
    p = QPainter(pm)
    p.setPen(QColor(200, 200, 200))
    p.drawRect(0, 0, size - 1, size - 1)
    p.end()
    return QIcon(pm)


class ColorMenu(QMenu):
    picked = Signal(object)  # (r,g,b) or None

    def __init__(self, none_text="No Color", more_text="More Colors…", parent=None, extra_actions=()):
        super().__init__(parent)
        w = QWidget()
        g = QGridLayout(w)
        g.setContentsMargins(8, 6, 8, 6)
        g.setSpacing(2)
        lab = QLabel("Theme Colors")
        lab.setStyleSheet("color:#555; font-weight:600")
        g.addWidget(lab, 0, 0, 1, 10)
        for col, c in enumerate(THEME):
            g.addWidget(self._sw(c), 1, col)
            for row, f in enumerate([0.8, 0.6, 0.4, -0.25, -0.5]):
                g.addWidget(self._sw(tint(c, f)), 2 + row, col)
        lab2 = QLabel("Standard Colors")
        lab2.setStyleSheet("color:#555; font-weight:600")
        g.addWidget(lab2, 7, 0, 1, 10)
        for col, c in enumerate(STANDARD):
            g.addWidget(self._sw(c), 8, col)
        wa = QWidgetAction(self)
        wa.setDefaultWidget(w)
        self.addAction(wa)
        self.addSeparator()
        if none_text:
            self.addAction(none_text, lambda: self.picked.emit(None))
        for text, slot in extra_actions:
            if text == "-":
                self.addSeparator()
            elif isinstance(slot, QMenu):
                slot.setTitle(text)
                self.addMenu(slot)
            else:
                self.addAction(text, slot)
        self.addAction(more_text, self._more)

    def _sw(self, c):
        b = QToolButton()
        b.setFixedSize(18, 16)
        b.setStyleSheet(f"QToolButton {{ background: rgb{tuple(c)}; border: 1px solid #c8c8c8; }}"
                        f"QToolButton:hover {{ border: 2px solid #e08a00; }}")
        b.setToolTip("#%02X%02X%02X" % c)
        b.clicked.connect(lambda _=False, cc=c: (self.picked.emit(cc), self.close()))
        return b

    def _more(self):
        from PySide6.QtWidgets import QColorDialog
        c = QColorDialog.getColor(QColor(0, 0, 0), self.parentWidget(), "Colors")
        if c.isValid():
            self.picked.emit((c.red(), c.green(), c.blue()))


# ---------------------------------------------------------------------------
# shape gallery
# ---------------------------------------------------------------------------
def shape_icon(spt, size=22):
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(2, 2)
    p.translate(2, 2)
    s = size - 4
    if spt == 20:
        p.setPen(QPen(QColor(60, 60, 60), 1.6))
        p.drawLine(QPointF(0, s), QPointF(s, 0))
    else:
        p.setPen(QPen(QColor(60, 60, 60), 1.1))
        p.setBrush(QColor(255, 255, 255))
        p.drawPath(autoshapes.outline(spt, s, s * (0.75 if spt in (1, 2, 7, 13, 66, 15, 55) else 1)))
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


class ShapeMenu(QMenu):
    picked = Signal(int)  # spt; 20 = line

    def __init__(self, parent=None):
        super().__init__(parent)
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(8, 6, 8, 6)
        sections = [("Lines", [20])]
        order = []
        for spt, name, sec in autoshapes.SHAPES:
            if sec not in order:
                order.append(sec)
        for sec in order:
            sections.append((sec, [s for s, n, se in autoshapes.SHAPES if se == sec]))
        for title, spts in sections:
            lab = QLabel(title)
            lab.setStyleSheet("color:#444; font-weight:600; background:#f0f0f0; padding:2px")
            v.addWidget(lab)
            g = QGridLayout()
            g.setSpacing(2)
            g.setAlignment(Qt.AlignLeft)
            for i, spt in enumerate(spts):
                b = QToolButton()
                b.setIcon(shape_icon(spt))
                b.setIconSize(QSize(22, 22))
                b.setAutoRaise(True)
                b.setToolTip("Line" if spt == 20 else autoshapes.NAMES[spt])
                b.clicked.connect(lambda _=False, s=spt: (self.picked.emit(s), self.close()))
                g.addWidget(b, i // 8, i % 8)
            v.addLayout(g)
        wa = QWidgetAction(self)
        wa.setDefaultWidget(w)
        self.addAction(wa)


# ---------------------------------------------------------------------------
# rulers
# ---------------------------------------------------------------------------
class Ruler(QWidget):
    THICK = 20

    def __init__(self, orientation, editor):
        super().__init__()
        self.orientation = orientation
        self.editor = editor
        if orientation == Qt.Horizontal:
            self.setFixedHeight(self.THICK)
        else:
            self.setFixedWidth(self.THICK)
        self.highlight = None  # (start, end) in scene units
        self.cursor_pos = None

    def paintEvent(self, ev):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(240, 240, 240))
        view = self.editor.view
        doc = self.editor.doc
        horiz = self.orientation == Qt.Horizontal

        def to_px(v):
            pt = view.mapFromScene(QPointF(v, 0) if horiz else QPointF(0, v))
            return (pt.x() if horiz else pt.y()) + (view.frameWidth())

        length = doc.width if horiz else doc.height
        a, b = to_px(0), to_px(length)
        band = QRectF(a, 3, b - a, self.THICK - 6) if horiz else QRectF(3, a, self.THICK - 6, b - a)
        p.fillRect(band, QColor(255, 255, 255))
        if self.highlight:
            s, e = self.highlight
            sa, sb = to_px(s), to_px(e)
            hb = QRectF(sa, 3, sb - sa, self.THICK - 6) if horiz else QRectF(3, sa, self.THICK - 6, sb - sa)
            p.fillRect(hb, QColor(206, 230, 226))
        unit = getattr(doc, "unit", "in")
        if unit == "px":
            step, sub, label_div = 100.0, 10, 1
        elif unit == "mm":
            step, sub, label_div = 72 / 25.4 * 10, 10, 72 / 25.4 * 10 / 10
        else:
            step, sub, label_div = 72.0, 8, 72.0
        zoom = view.transform().m11()
        while step * zoom < 40:
            step *= 2
        px_per_sub = step * zoom / sub
        p.setPen(QPen(QColor(110, 110, 110), 1))
        f = QFont()
        f.setPointSizeF(7)
        p.setFont(f)
        start = -int(length / step) - 2
        end = int(length * 2 / step) + 4
        span = (self.width() if horiz else self.height())
        for i in range(start, end):
            base = i * step
            for j in range(sub):
                v = base + j * step / sub
                x = to_px(v)
                if x < -5 or x > span + 5:
                    continue
                if j == 0:
                    tick = self.THICK - 4
                elif sub % 2 == 0 and j == sub // 2:
                    tick = 8
                else:
                    tick = 4 if px_per_sub > 4 else 0
                if tick == 0:
                    continue
                if horiz:
                    p.drawLine(int(x), self.THICK - 1, int(x), self.THICK - 1 - tick)
                else:
                    p.drawLine(self.THICK - 1, int(x), self.THICK - 1 - tick, int(x))
                if j == 0:
                    if unit == "px":
                        txt = f"{int(round(base))}"
                    elif unit == "mm":
                        txt = f"{int(round(base / (72 / 25.4)))}"
                    else:
                        txt = f"{base / 72:g}"
                    if horiz:
                        p.drawText(int(x) + 2, 10, txt)
                    else:
                        p.save()
                        p.translate(10, int(x) + 2)
                        p.rotate(90)
                        p.drawText(0, 0, txt)
                        p.restore()
        if self.cursor_pos is not None:
            x = to_px(self.cursor_pos)
            p.setPen(QPen(QColor(7, 117, 104), 1, Qt.DashLine))
            if horiz:
                p.drawLine(int(x), 0, int(x), self.THICK)
            else:
                p.drawLine(0, int(x), self.THICK, int(x))
        p.setPen(QColor(200, 200, 200))
        if horiz:
            p.drawLine(0, self.THICK - 1, self.width(), self.THICK - 1)
        else:
            p.drawLine(self.THICK - 1, 0, self.THICK - 1, self.height())
        p.end()
