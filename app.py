"""PubDesign – desktop publishing with a Publisher-style interface and native .pub files."""
import copy
import math
import os
import sys
import traceback
import re

from PySide6.QtCore import Qt, QRectF, QPointF, QSizeF, QSize, QTimer, QMarginsF, QSettings, QUrl, QMimeData, QEvent
from PySide6.QtGui import (QAction, QColor, QFont, QIcon, QImage, QKeySequence, QPainter, QPageSize, QPageLayout, QPdfWriter,
                           QPixmap, QTextCursor, QDesktopServices, QTextCharFormat, QTextBlockFormat, QPen,
                           QGuiApplication, QCursor)
from PySide6.QtWidgets import (QApplication, QMainWindow, QGraphicsView, QFileDialog, QMessageBox, QListWidget,
                               QListWidgetItem, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
                               QFontComboBox, QDoubleSpinBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QToolButton, QMenu, QSpinBox, QStatusBar, QCheckBox, QScrollArea, QFrame, QSlider,
                               QStackedWidget, QSplitter, QProgressDialog, QSizePolicy, QTabWidget, QLineEdit)
from PySide6.QtPrintSupport import QPrinter, QPrintDialog, QPrinterInfo

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from pubmodel import Document, Page, Item, Para, Run
from canvas import (PageScene, ShapeItem, page_image, render_page, item_to_png, image_to_png,
                    qt_to_align, ALIGN_TO_QT)
import docio
import templates
import icons
from ribbon import (Ribbon, ColorMenu, ShapeMenu, Ruler, TitleBar, large_button, small_button, RIBBON_QSS,
                    ACCENT, ACCENT_DARK, CHROME)
from pubwriter import write_pub
from pubreader import read_pub, is_own_file
from pub_import import import_pub, ImportError_, find_soffice, find_pubconv, can_import
import updater
import anim

APP = "PubDesign"
VERSION = updater.local_version()
OPEN_FILTER = ("Publisher Files (*.pub);;All supported (*.pub *.pubdesign *.pagecraft);;"
               "PubDesign backups (*.pubdesign *.pagecraft)")
SAVE_FILTER = "Publisher Files (*.pub);;PubDesign backup (*.pubdesign)"


def unit_factor(unit):
    return {"in": 72.0, "mm": 72 / 25.4, "px": 1.0, "pt": 1.0}.get(unit, 72.0)


def image_bytes(img):
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(ba)


def asset(name):
    return os.path.join(HERE, "assets", name)


def app_icon():
    if os.path.exists(asset("PubDesign.ico")):
        ic = QIcon(asset("PubDesign.ico"))
        if os.path.exists(asset("logo.png")):
            ic.addFile(asset("logo.png"))
        return ic
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(7, 117, 104))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, 60, 60, 12, 12)
    p.setBrush(QColor(255, 255, 255))
    p.drawRect(16, 12, 32, 40)
    p.setBrush(QColor(240, 186, 60))
    p.drawRect(20, 16, 24, 10)
    p.setBrush(QColor(7, 117, 104))
    for i in range(4):
        p.drawRect(20, 30 + i * 5, 24 if i < 3 else 14, 2)
    p.end()
    return QIcon(pm)


def snap45(a, b):
    dx, dy = b.x() - a.x(), b.y() - a.y()
    ang = round(math.degrees(math.atan2(dy, dx)) / 45) * 45
    ln = math.hypot(dx, dy)
    return QPointF(a.x() + ln * math.cos(math.radians(ang)), a.y() + ln * math.sin(math.radians(ang)))


# ---------------------------------------------------------------------------
# workspace view
# ---------------------------------------------------------------------------
class PageView(QGraphicsView):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFrameShape(QFrame.NoFrame)
        self._create_start = None
        self._preview = None

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self.editor.update_rulers()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.editor.update_rulers()

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.ControlModifier:
            f = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
            self.editor.zoom_smooth(self.editor.zoom_target() * f)
            return
        super().wheelEvent(ev)

    # ---- one place decides the mouse pointer for the page (items never set their own) ----
    def refresh_cursor(self, pos=None):
        vp = self.viewport()
        if pos is None:
            pos = vp.mapFromGlobal(QCursor.pos())
        ed = self.editor
        if getattr(ed, "painter_fmt", None) is not None:
            c = Qt.PointingHandCursor
        elif getattr(ed, "tool", "select") != "select":
            c = Qt.CrossCursor
        else:
            c = self._select_cursor(pos)
        if not vp.testAttribute(Qt.WA_SetCursor) or vp.cursor().shape() != c:
            vp.setCursor(c)

    def _select_cursor(self, pos):
        sc = self.scene()
        if sc is None or not self.viewport().rect().contains(pos):
            return Qt.ArrowCursor
        sp = self.mapToScene(pos)
        # resize/rotate handles of selected objects come first (they stick out past the object)
        for it in sc.selectedItems():
            if isinstance(it, ShapeItem):
                h = it.handle_at(it.mapFromScene(sp))
                if h is not None:
                    return ShapeItem.HANDLE_CURSORS[h]
        shape = self._shape_at(pos)
        if shape is None or not getattr(shape, "editable", False):
            return Qt.ArrowCursor
        if shape.text is not None and shape.is_editing():
            return Qt.IBeamCursor
        return Qt.SizeAllCursor if shape.isSelected() else Qt.ArrowCursor

    def enterEvent(self, ev):
        super().enterEvent(ev)
        self.refresh_cursor()

    def _shape_at(self, pos):
        item = self.itemAt(pos)
        while item is not None and not isinstance(item, ShapeItem):
            item = item.parentItem()
        return item

    def mousePressEvent(self, ev):
        ed = self.editor
        if ed.painter_fmt is not None and ev.button() == Qt.LeftButton:
            item = self._shape_at(ev.position().toPoint())
            if item is not None:
                ed.apply_painter(item)
                return
            ed.cancel_painter()
        if ed.tool != "select" and ev.button() == Qt.LeftButton:
            self._create_start = self.mapToScene(ev.position().toPoint())
            pen = QPen(QColor(7, 117, 104), 0, Qt.DashLine)
            pen.setCosmetic(True)
            s = self._create_start
            if ed.tool == "line":
                self._preview = self.scene().addLine(s.x(), s.y(), s.x(), s.y(), pen)
            else:
                self._preview = self.scene().addRect(QRectF(s, QSizeF(0, 0)), pen)
            self._preview.setZValue(1e9)
            return
        super().mousePressEvent(ev)
        if ev.button() == Qt.LeftButton:
            # keep the pointer that matches what is being dragged (handle, move, text)
            self.refresh_cursor(ev.position().toPoint())

    def _drag_end(self, sp, mods):
        s = self._create_start
        if self.editor.tool == "line":
            return snap45(s, sp) if mods & Qt.ShiftModifier else sp
        if mods & Qt.ShiftModifier:
            d = max(abs(sp.x() - s.x()), abs(sp.y() - s.y()))
            return QPointF(s.x() + math.copysign(d, sp.x() - s.x() or 1), s.y() + math.copysign(d, sp.y() - s.y() or 1))
        return sp

    def mouseMoveEvent(self, ev):
        sp = self.mapToScene(ev.position().toPoint())
        self.editor.show_cursor_pos(sp)
        if self._create_start is not None and self._preview is not None:
            end = self._drag_end(sp, ev.modifiers())
            if self.editor.tool == "line":
                self._preview.setLine(self._create_start.x(), self._create_start.y(), end.x(), end.y())
            else:
                self._preview.setRect(QRectF(self._create_start, end).normalized())
            return
        super().mouseMoveEvent(ev)
        if not ev.buttons():
            self.refresh_cursor(ev.position().toPoint())

    def mouseReleaseEvent(self, ev):
        if self._create_start is not None:
            end = self._drag_end(self.mapToScene(ev.position().toPoint()), ev.modifiers())
            start = self._create_start
            self._create_start = None
            if self._preview is not None:
                self.scene().removeItem(self._preview)
                self._preview = None
            self.editor.create_from_drag(start, end)
            self.refresh_cursor()
            return
        super().mouseReleaseEvent(ev)
        self.editor.checkpoint()
        self.refresh_cursor(ev.position().toPoint())

    def contextMenuEvent(self, ev):
        item = self._shape_at(ev.pos())
        ed = self.editor
        if item is not None and not item.isSelected():
            ed.scene.clearSelection()
            item.setSelected(True)
        m = QMenu(self)
        if item is not None:
            m.addAction(icons.icon("cut", 16), "Cut", ed.cut)
            m.addAction(icons.icon("copy", 16), "Copy", ed.copy)
        m.addAction(icons.icon("paste", 16), "Paste", ed.paste)
        if item is not None:
            m.addAction("Delete Object", ed.delete_selected)
            m.addSeparator()
            m.addAction(icons.icon("forward", 16), "Bring to Front", lambda: ed.restack("front"))
            m.addAction(icons.icon("backward", 16), "Send to Back", lambda: ed.restack("back"))
            m.addSeparator()
            if item.kind == "image":
                m.addAction(icons.icon("change_pic", 16), "Change Picture…", ed.change_picture)
            m.addAction("Format Object…", ed.format_object_dialog)
        else:
            m.addSeparator()
            m.addAction(icons.icon("page_add", 16), "Insert Page", ed.add_page)
            m.addAction(icons.icon("textbox", 16), "Draw Text Box", lambda: ed.set_tool("text"))
        m.exec(ev.globalPos())

    def dragEnterEvent(self, ev):
        if ev.mimeData().hasUrls() or ev.mimeData().hasImage():
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):
        ev.acceptProposedAction()

    def dropEvent(self, ev):
        md = ev.mimeData()
        pos = self.mapToScene(ev.position().toPoint())
        for url in md.urls():
            path = url.toLocalFile()
            ext = os.path.splitext(path)[1].lower()
            if ext in (".pub", ".pubdesign", ".pagecraft"):
                self.editor.open_path(path)
                return
            if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tif", ".tiff"):
                with open(path, "rb") as f:
                    self.editor.insert_picture_data(f.read(), os.path.basename(path), pos)
        if md.hasImage() and not md.hasUrls():
            self.editor.insert_picture_data(image_bytes(QImage(md.imageData())), "pasted.png", pos)


# ---------------------------------------------------------------------------
# Backstage (File tab)
# ---------------------------------------------------------------------------
BACKSTAGE_QSS = f"""
#BackNav {{ background: #f3f3f3; border-right: 1px solid #e3e3e3; }}
#BackNav QToolButton {{ color: #242424; background: transparent; border: none; border-left: 3px solid transparent;
    text-align: left; padding: 7px 14px 7px 13px; font-size: 10pt; }}
#BackNav QToolButton:hover {{ background: #e8e8e8; }}
#BackNav QToolButton:checked {{ background: #e3e3e3; border-left: 3px solid {ACCENT}; font-weight: 600; }}
#BackNav #BackBtn {{ border: none; padding: 6px 12px; }}
#BackNav QFrame#NavSep {{ background: #dcdcdc; max-height: 1px; min-height: 1px; margin: 6px 18px; }}
#BackBody, #BackBody > QWidget {{ background: #fafafa; }}
#BackTitle {{ font-size: 21pt; font-weight: 400; color: #242424; }}
#Greeting {{ font-size: 18pt; font-weight: 400; color: #242424; }}
#SectionHead {{ font-size: 14pt; color: #242424; }}
#Tile {{ border: 1px solid #ddd; background: #fff; padding: 6px; font-size: 9pt; border-radius: 4px; }}
#Tile:hover {{ border-color: {ACCENT}; background: #f1f8f7; }}
#HomeTile {{ border: none; background: transparent; padding: 10px 6px 8px 6px; font-size: 9pt; color: #242424;
    border-radius: 4px; }}
#HomeTile:hover {{ background: #ebebeb; }}
#LinkBtn {{ border: none; background: transparent; color: {ACCENT}; font-size: 9.5pt; font-weight: 600; }}
#LinkBtn:hover {{ text-decoration: underline; }}
#Pill {{ border: 1px solid #8a8a8a; background: #ffffff; color: #242424; border-radius: 14px; padding: 0px 16px;
    font-size: 10pt; min-height: 28px; max-height: 28px; }}
#Pill:hover {{ background: #f0f0f0; }}
#Pill:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
#FileSearch {{ border: 1px solid #8a8a8a; border-radius: 3px; padding: 5px 8px 5px 30px; background: white;
    font-size: 9.5pt; }}
#FileSearch:focus {{ border: 1px solid {ACCENT}; }}
#ColHead {{ color: #444; font-size: 9pt; }}
#FileList {{ border: none; background: transparent; outline: none; }}
#FileList::item {{ border-bottom: 1px solid #e3e3e3; }}
#FileList::item:hover {{ background: #f0f0f0; }}
#FileList::item:selected {{ background: #e6f2f0; }}
#BigAction {{ border: 1px solid #e1e1e1; background: #ffffff; padding: 10px; font-size: 10.5pt; text-align: left;
    border-radius: 6px; }}
#BigAction:hover {{ border-color: {ACCENT}; background: #f1f8f7; }}
"""


class Backstage(QWidget):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        self.setAttribute(Qt.WA_StyledBackground, True)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        nav = QWidget()
        nav.setObjectName("BackNav")
        nav.setAttribute(Qt.WA_StyledBackground, True)
        nav.setFixedWidth(170)
        nv = QVBoxLayout(nav)
        nv.setContentsMargins(0, 10, 0, 10)
        nv.setSpacing(0)
        back = QToolButton()
        back.setObjectName("BackBtn")
        back.setIcon(icons.icon("bs_back", 32))
        back.setIconSize(QSize(26, 26))
        back.setToolTip("Back to your publication (Esc)")
        back.setCursor(Qt.PointingHandCursor)
        back.clicked.connect(editor.close_backstage)
        nv.addWidget(back)
        nv.addSpacing(14)
        self.body = QStackedWidget()
        self.body.setObjectName("BackBody")
        self.buttons = {}

        def sep():
            f = QFrame()
            f.setObjectName("NavSep")
            nv.addWidget(f)

        def item(key, label, icon_name):
            b = QToolButton()
            b.setText("  " + label)
            b.setIcon(icons.icon(icon_name, 20))
            b.setIconSize(QSize(18, 18))
            b.setCheckable(key not in ("save", "close"))
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, k=key: self.show_page(k))
            nv.addWidget(b)
            self.buttons[key] = b

        for key, label, ic in [("home", "Home", "bs_home"), ("new", "New", "bs_new"), ("open", "Open", "bs_open")]:
            item(key, label, ic)
        sep()
        for key, label, ic in [("info", "Info", "bs_info"), ("save", "Save", "bs_save"),
                               ("saveas", "Save As", "bs_saveas"), ("print", "Print", "bs_print"),
                               ("export", "Export", "bs_export"), ("close", "Close", "bs_close")]:
            item(key, label, ic)
        nv.addStretch()
        sep()
        item("options", "Options", "bs_options")
        h.addWidget(nav)
        h.addWidget(self.body, 1)
        self.pages = {"home": self._home_page(), "info": self._info_page(), "new": self._new_page(),
                      "open": self._open_page(), "saveas": self._saveas_page(), "print": self._print_page(),
                      "export": self._export_page(), "options": self._options_page()}
        for w in self.pages.values():
            self.body.addWidget(w)
        self.setStyleSheet(BACKSTAGE_QSS)

    def _page(self, title):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(40, 26, 40, 20)
        t = QLabel(title)
        t.setObjectName("BackTitle")
        v.addWidget(t)
        v.addSpacing(12)
        return w, v

    def _big(self, icon_name, title, desc, slot):
        b = QToolButton()
        b.setObjectName("BigAction")
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setIcon(icons.icon(icon_name, 32))
        b.setIconSize(QSize(32, 32))
        b.setText(f"  {title}\n  {desc}")
        b.setMinimumWidth(460)
        b.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        b.clicked.connect(slot)
        return b

    def _info_page(self):
        w, v = self._page("Info")
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setTextFormat(Qt.RichText)
        self.info_label.setStyleSheet("font-size:10.5pt; color:#333")
        v.addWidget(self.info_label)
        v.addSpacing(10)
        v.addWidget(self._big("size", "Page Setup", "Change the page size, orientation and margin guides.",
                              lambda: (self.editor.close_backstage(), self.editor.page_setup_dialog())))
        v.addStretch()
        return w

    # ---------------- Options ----------------
    def _options_page(self):
        w, v = self._page("Options")
        head = QLabel("Updates")
        head.setObjectName("SectionHead")
        v.addWidget(head)
        v.addWidget(self._big("bs_new", "Check for Updates", "Get the newest version of PubDesign from GitHub.",
                              self.editor.check_for_updates))
        self.auto_chk = QCheckBox("Check for updates automatically when PubDesign starts")
        self.auto_chk.setChecked(self.editor.settings.value("auto_update", True, type=bool))
        self.auto_chk.toggled.connect(lambda on: self.editor.settings.setValue("auto_update", on))
        v.addWidget(self.auto_chk)
        v.addSpacing(18)
        head = QLabel("Window")
        head.setObjectName("SectionHead")
        v.addWidget(head)
        self.anim_chk = QCheckBox("Play animations (smooth transitions, sliding menus and zoom)")
        self.anim_chk.setChecked(self.editor.settings.value("animations", True, type=bool))

        def anim_toggled(on):
            self.editor.settings.setValue("animations", on)
            anim.set_enabled(on)
            anim.enable_menu_effects()
        self.anim_chk.toggled.connect(anim_toggled)
        v.addWidget(self.anim_chk)
        self.classic_chk = QCheckBox("Use the standard Windows title bar (takes effect next time PubDesign starts)")
        self.classic_chk.setChecked(self.editor.settings.value("classic_titlebar", False, type=bool))
        self.classic_chk.toggled.connect(lambda on: self.editor.settings.setValue("classic_titlebar", on))
        v.addWidget(self.classic_chk)
        v.addSpacing(18)
        head = QLabel("About")
        head.setObjectName("SectionHead")
        v.addWidget(head)
        self.about_label = QLabel()
        self.about_label.setStyleSheet("color:#444; font-size:10pt")
        v.addWidget(self.about_label)
        v.addWidget(self._big("bs_info", "About PubDesign", "Version, licenses and the project page.",
                              self.editor.about))
        v.addStretch()
        return w

    # ---------------- Home (like the Office start page) ----------------
    def _home_page(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.setContentsMargins(0, 0, 0, 0)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        outer.addWidget(sa)
        inner = QWidget()
        sa.setWidget(inner)
        v = QVBoxLayout(inner)
        v.setContentsMargins(48, 20, 48, 20)
        v.setSpacing(6)
        self.greeting = QLabel()
        self.greeting.setObjectName("Greeting")
        v.addWidget(self.greeting)
        v.addSpacing(10)

        # "New" strip
        hr = QHBoxLayout()
        self.new_toggle = QToolButton()
        self.new_toggle.setIcon(icons.icon("bs_chevron", 16))
        self.new_toggle.setIconSize(QSize(14, 14))
        self.new_toggle.setAutoRaise(True)
        self.new_toggle.setCursor(Qt.PointingHandCursor)
        hr.addWidget(self.new_toggle)
        nh = QLabel("New")
        nh.setObjectName("SectionHead")
        hr.addWidget(nh)
        hr.addStretch()
        more = self._link("More templates", lambda: self.show_page("new"))
        hr.addWidget(more)
        v.addLayout(hr)
        self.tiles = QWidget()
        th = QHBoxLayout(self.tiles)
        th.setContentsMargins(0, 4, 0, 4)
        th.setSpacing(6)

        def tile(name, doc, slot):
            b = QToolButton()
            b.setObjectName("HomeTile")
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            h = 92
            wpx = max(int(h * doc.width / doc.height), 40)
            if wpx > 150:
                wpx, h = 150, int(150 * doc.height / doc.width)
            img = page_image(doc.pages[0], doc, wpx)
            frame = QPixmap(wpx + 2, 94)
            frame.fill(Qt.transparent)
            pp = QPainter(frame)
            pp.fillRect(0, 94 - (h + 2), wpx + 2, h + 2, QColor(200, 200, 200))
            pp.drawImage(1, 94 - (h + 1), img)
            pp.end()
            b.setIcon(QIcon(frame))
            b.setIconSize(QSize(wpx + 2, 94))
            b.setText(name)
            b.setFixedWidth(140)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(slot)
            return b

        th.addWidget(tile("Blank publication", templates.blank(612, 792),
                          lambda: self.editor.new_from(templates.blank(612, 792))))
        for name, desc, fn in templates.STARTERS:
            b = tile(name, fn(), lambda _=False, f=fn: self.editor.new_from(f()))
            b.setToolTip(desc)
            th.addWidget(b)
        th.addStretch()
        self.tile_buttons = [th.itemAt(i).widget() for i in range(th.count()) if th.itemAt(i).widget()]
        self.tiles.installEventFilter(self)
        ts = self.tiles
        v.addWidget(ts)
        self.new_toggle.clicked.connect(lambda: (ts.setVisible(not ts.isVisible()),
                                                 self.new_toggle.setIcon(icons.icon(
                                                     "bs_chevron" if ts.isVisible() else "bs_arrow", 16))))
        v.addSpacing(16)

        # Recent / Pinned + search
        fr = QHBoxLayout()
        fr.setSpacing(10)
        self.pill_recent = self._pill("Recent")
        self.pill_pinned = self._pill("Pinned")
        self.pill_recent.setChecked(True)
        for pbtn in (self.pill_recent, self.pill_pinned):
            pbtn.clicked.connect(self._pill_clicked)
            fr.addWidget(pbtn)
        fr.addStretch()
        self.file_search = QLineEdit()
        self.file_search.setObjectName("FileSearch")
        self.file_search.setPlaceholderText("Search for a file")
        self.file_search.setFixedWidth(420)
        self.file_search.setClearButtonEnabled(True)
        si = QLabel(self.file_search)
        si.setPixmap(icons.icon("bs_search", 16).pixmap(15, 15))
        si.move(9, 8)
        self.file_search.textChanged.connect(lambda _: self.refresh_home_files())
        fr.addWidget(self.file_search)
        v.addLayout(fr)
        v.addSpacing(8)
        ch = QHBoxLayout()
        ch.setContentsMargins(8, 0, 8, 0)
        n1 = QLabel("Name")
        n1.setObjectName("ColHead")
        n2 = QLabel("Date modified")
        n2.setObjectName("ColHead")
        n2.setFixedWidth(150)
        ch.addWidget(n1)
        ch.addStretch()
        ch.addWidget(n2)
        v.addLayout(ch)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#e3e3e3")
        v.addWidget(line)
        self.file_list = QListWidget()
        self.file_list.setObjectName("FileList")
        self.file_list.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.file_list.customContextMenuRequested.connect(self._file_menu)
        self.file_list.itemClicked.connect(self._file_clicked)
        v.addWidget(self.file_list)
        mr = QHBoxLayout()
        mr.addStretch()
        mr.addWidget(self._link("More publications", lambda: self.show_page("open")))
        v.addLayout(mr)
        v.addStretch()
        return w

    def eventFilter(self, obj, ev):
        # like Office: show as many template tiles as fit on one row
        if obj is getattr(self, "tiles", None) and ev.type() == QEvent.Resize:
            avail = obj.width()
            used = 0
            for b in self.tile_buttons:
                used += b.width() + 6
                b.setVisible(used <= avail)
        return super().eventFilter(obj, ev)

    def _link(self, text, slot):
        b = QToolButton()
        b.setObjectName("LinkBtn")
        b.setText(text + "  ")
        b.setIcon(icons.icon("bs_arrow", 16))
        b.setIconSize(QSize(16, 16))
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        b.setLayoutDirection(Qt.RightToLeft)
        b.setCursor(Qt.PointingHandCursor)
        b.clicked.connect(slot)
        return b

    def _pill(self, text):
        b = QPushButton(text)
        b.setObjectName("Pill")
        b.setCheckable(True)
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _pill_clicked(self):
        src = self.sender()
        for pbtn in (self.pill_recent, self.pill_pinned):
            pbtn.setChecked(pbtn is src)
        self.refresh_home_files()

    def _pinned(self):
        r = self.editor.settings.value("pinned", [])
        if isinstance(r, str):
            r = [r]
        return [p for p in (r or []) if os.path.exists(p)]

    def _set_pinned(self, paths):
        self.editor.settings.setValue("pinned", paths)

    def _file_menu(self, pos):
        li = self.file_list.itemAt(pos)
        if li is None or not li.data(Qt.UserRole):
            return
        path = li.data(Qt.UserRole)
        pinned = self._pinned()
        m = QMenu(self)
        m.addAction("Open", lambda: self.editor.open_path(path))
        if path in pinned:
            m.addAction("Unpin from list", lambda: (self._set_pinned([p for p in pinned if p != path]),
                                                    self.refresh_home_files()))
        else:
            m.addAction("Pin to list", lambda: (self._set_pinned([path] + pinned), self.refresh_home_files()))
        m.addAction("Open file location",
                    lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path))))
        m.addSeparator()
        m.addAction("Remove from list", lambda: self._forget(path))
        m.exec(self.file_list.mapToGlobal(pos))

    def _forget(self, path):
        ed = self.editor
        ed.settings.setValue("recent", [p for p in ed.recent_files() if p != path])
        self._set_pinned([p for p in self._pinned() if p != path])
        self.refresh_home_files()

    def _file_clicked(self, li):
        path = li.data(Qt.UserRole)
        if path:
            self.editor.open_path(path)

    @staticmethod
    def _where(path):
        d = os.path.dirname(path)
        home = os.path.expanduser("~")
        if os.path.normcase(d).startswith(os.path.normcase(home)):
            d = d[len(home):].lstrip("\\/")
        parts = [p for p in re.split(r"[\\/]+", d) if p]
        return " » ".join(parts) if parts else d

    @staticmethod
    def _when(path):
        import datetime
        try:
            t = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        except OSError:
            return ""
        now = datetime.datetime.now()
        if t.date() == now.date():
            return t.strftime("%I:%M %p").lstrip("0")
        if t.year == now.year:
            return f"{t.strftime('%B')} {t.day}"
        return f"{t.strftime('%B')} {t.day}, {t.year}"

    def refresh_home(self):
        import datetime
        hour = datetime.datetime.now().hour
        self.greeting.setText("Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening")
        self.refresh_home_files()

    def refresh_home_files(self):
        self.file_list.clear()
        paths = self._pinned() if self.pill_pinned.isChecked() else self.editor.recent_files()
        q = self.file_search.text().strip().lower()
        if q:
            paths = [p for p in paths if q in os.path.basename(p).lower()]
        pinned = set(self._pinned())
        for p in paths:
            row = QWidget()
            row.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            h = QHBoxLayout(row)
            h.setContentsMargins(8, 8, 8, 8)
            h.setSpacing(12)
            ic = QLabel()
            ic.setPixmap(icons.icon("bs_pubfile", 32).pixmap(30, 30))
            h.addWidget(ic)
            tv = QVBoxLayout()
            tv.setSpacing(1)
            nm = QLabel(os.path.basename(p) + ("   📌" if p in pinned else ""))
            nm.setStyleSheet("font-size:10.5pt; color:#242424; background:transparent")
            wh = QLabel(self._where(p))
            wh.setStyleSheet("font-size:8.5pt; color:#555; background:transparent")
            tv.addWidget(nm)
            tv.addWidget(wh)
            h.addLayout(tv)
            h.addStretch()
            dt = QLabel(self._when(p))
            dt.setStyleSheet("font-size:9pt; color:#333; background:transparent")
            dt.setFixedWidth(150)
            h.addWidget(dt)
            li = QListWidgetItem()
            li.setData(Qt.UserRole, p)
            li.setToolTip(p)
            li.setSizeHint(QSize(100, 56))
            self.file_list.addItem(li)
            self.file_list.setItemWidget(li, row)
        if not paths:
            msg = ("No pinned publications yet. Right-click a recent file and choose Pin to list."
                   if self.pill_pinned.isChecked() else
                   "No matching files." if q else "Publications you open or save will show up here.")
            li = QListWidgetItem(msg)
            li.setFlags(Qt.NoItemFlags)
            li.setSizeHint(QSize(100, 48))
            self.file_list.addItem(li)
        self.file_list.setFixedHeight(sum(self.file_list.sizeHintForRow(i) for i in range(self.file_list.count())) + 4)

    def refresh_info(self):
        ed = self.editor
        uf = unit_factor(ed.doc.unit)
        name = os.path.basename(ed.path) if ed.path else "Publication1 (not saved yet)"
        reader = "built in ✓" if find_pubconv() else ("through LibreOffice ✓" if find_soffice() else "<b>not available</b>")
        self.info_label.setText(
            f"<b style='font-size:14pt'>{name}</b><br>{ed.path or ''}<br><br>"
            f"PubDesign version {VERSION}<br>"
            f"Pages: {len(ed.doc.pages)}<br>"
            f"Page size: {round(ed.doc.width / uf, 2):g} × {round(ed.doc.height / uf, 2):g} {ed.doc.unit}<br><br>"
            f"Publications are saved in Microsoft Publisher format (.pub).<br>"
            f"Reader for files made in Microsoft Publisher: <span style=color:#077568>{reader}</span>")

    def _new_page(self):
        w, v = self._page("New")
        tabs = QTabWidget()
        v.addWidget(tabs, 1)
        inner = QWidget()
        g = QGridLayout(inner)
        g.setSpacing(16)

        def tile(name, doc, slot):
            b = QToolButton()
            b.setObjectName("Tile")
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setIcon(QIcon(QPixmap.fromImage(page_image(doc.pages[0], doc, 150))))
            b.setIconSize(QSize(150, min(int(150 * doc.height / doc.width), 194)))
            b.setText(name)
            b.setMinimumWidth(176)
            b.clicked.connect(slot)
            return b
        bd = templates.blank(612, 792)
        g.addWidget(tile("Blank 8.5 × 11\"", bd, lambda: self.editor.new_from(templates.blank(612, 792))), 0, 0)
        for i, (name, desc, fn) in enumerate(templates.STARTERS, start=1):
            g.addWidget(tile(f"{name}\n{desc}", fn(), lambda _=False, f=fn: self.editor.new_from(f())), i // 5, i % 5)
        g.setRowStretch(10, 1)
        g.setColumnStretch(10, 1)
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setWidget(inner)
        tabs.addTab(sa, "Featured")
        bw = QWidget()
        bv = QVBoxLayout(bw)
        lst = QListWidget()
        for cat, name, ww, hh, unit in templates.SIZES:
            li = QListWidgetItem(f"{cat}  —  {name}")
            li.setData(Qt.UserRole, (ww, hh, unit))
            lst.addItem(li)
        lst.setCurrentRow(0)
        lst.itemDoubleClicked.connect(lambda li: self.editor.new_from(templates.blank(*li.data(Qt.UserRole))))
        bv.addWidget(lst)
        cb = QPushButton("Create")
        cb.clicked.connect(lambda: self.editor.new_from(templates.blank(*lst.currentItem().data(Qt.UserRole))))
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(cb)
        bv.addLayout(row)
        tabs.addTab(bw, "Blank Page Sizes")
        return w

    def _open_page(self):
        w, v = self._page("Open")
        v.addWidget(self._big("open", "Browse", "Open a Publisher (.pub) file from your computer.",
                              lambda: self.editor.open_doc()))
        v.addWidget(self._big("picture", "Open a Publisher file as pictures",
                              "Exact look of every page, for complex files (not editable).", self.editor.open_pictures))
        v.addSpacing(14)
        lab = QLabel("Recent")
        lab.setStyleSheet("font-size:12pt; color:#333")
        v.addWidget(lab)
        self.recent = QListWidget()
        self.recent.setStyleSheet("QListWidget { border: none; font-size: 10pt; } QListWidget::item { padding: 6px; }"
                                  "QListWidget::item:hover { background:#f1f8f7; }")
        self.recent.itemClicked.connect(lambda li: self.editor.open_path(li.data(Qt.UserRole)))
        v.addWidget(self.recent, 1)
        return w

    def refresh_recent(self):
        self.recent.clear()
        self.recent.setIconSize(QSize(28, 28))
        for p in self.editor.recent_files():
            li = QListWidgetItem(icons.icon("pub", 32), f"{os.path.basename(p)}\n{os.path.dirname(p)}")
            li.setData(Qt.UserRole, p)
            self.recent.addItem(li)
        if not self.recent.count():
            self.recent.addItem("Files you open or save will show up here.")

    def _saveas_page(self):
        w, v = self._page("Save As")
        v.addWidget(self._big("pub", "Publisher File (*.pub)", "Standard format, opens in Microsoft Publisher.",
                              lambda: self.editor.save_as("pub")))
        v.addWidget(self._big("save", "PubDesign Backup (*.pubdesign)", "PubDesign's own backup format.",
                              lambda: self.editor.save_as("pubdesign")))
        v.addWidget(self._big("pdf", "PDF (*.pdf)", "For printing and sharing. Anyone can open it.",
                              self.editor.export_pdf))
        v.addStretch()
        return w

    # ---------------- Print (Publisher-style: settings on the left, live preview on the right) -----------
    def _print_page(self):
        w, v = self._page("Print")
        row = QHBoxLayout()
        row.setSpacing(28)
        left = QWidget()
        left.setFixedWidth(310)
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(6)

        top = QHBoxLayout()
        self.print_btn = QToolButton()
        self.print_btn.setObjectName("BigAction")
        self.print_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        self.print_btn.setIcon(icons.icon("print", 32))
        self.print_btn.setIconSize(QSize(40, 40))
        self.print_btn.setText("Print")
        self.print_btn.setFixedSize(100, 92)
        self.print_btn.clicked.connect(self.do_print)
        top.addWidget(self.print_btn)
        cb = QVBoxLayout()
        cb.setSpacing(4)
        cb.addWidget(QLabel("Copies of print job:"))
        self.copies = QSpinBox()
        self.copies.setRange(1, 999)
        self.copies.setFixedWidth(80)
        cb.addWidget(self.copies)
        self.collate = QCheckBox("Collated")
        self.collate.setChecked(True)
        cb.addWidget(self.collate)
        top.addLayout(cb)
        top.addStretch()
        lv.addLayout(top)

        def head(text):
            l = QLabel(text)
            l.setStyleSheet("font-size:12pt; color:#222; padding-top:10px; border-bottom:1px solid #ddd")
            lv.addWidget(l)

        head("Printer")
        self.printer_combo = QComboBox()
        self.printer_combo.currentIndexChanged.connect(self._printer_changed)
        lv.addWidget(self.printer_combo)
        links = QHBoxLayout()
        for text, fn in [("Add a printer", lambda: QDesktopServices.openUrl(QUrl("ms-settings:printers"))),
                         ("More settings (Windows print window)", self.editor.print_doc)]:
            b = QToolButton()
            b.setText(text)
            b.setAutoRaise(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(f"QToolButton {{ color:{ACCENT}; border:none; padding:0; }}"
                            "QToolButton:hover { text-decoration: underline; }")
            b.clicked.connect(fn)
            links.addWidget(b)
        links.addStretch()
        lv.addLayout(links)

        head("Settings")
        self.range_combo = QComboBox()
        self.range_combo.addItems(["Print All Pages", "Print Current Page", "Custom Print"])
        lv.addWidget(self.range_combo)
        self.range_edit = QLineEdit()
        self.range_edit.setPlaceholderText("Pages, e.g. 1-3, 5")
        self.range_edit.setVisible(False)
        lv.addWidget(self.range_edit)
        self.fit_combo = QComboBox()
        self.fit_combo.addItems(["Fit to Paper", "Actual Size"])
        lv.addWidget(self.fit_combo)
        self.paper_combo = QComboBox()
        lv.addWidget(self.paper_combo)
        self.orient_combo = QComboBox()
        self.orient_combo.addItems(["Portrait Orientation", "Landscape Orientation"])
        lv.addWidget(self.orient_combo)
        self.duplex_combo = QComboBox()
        self.duplex_combo.addItems(["Print One Sided", "Print on Both Sides (flip on long edge)",
                                    "Print on Both Sides (flip on short edge)"])
        lv.addWidget(self.duplex_combo)
        self.color_combo = QComboBox()
        self.color_combo.addItems(["Color", "Grayscale"])
        lv.addWidget(self.color_combo)
        self.print_msg = QLabel()
        self.print_msg.setWordWrap(True)
        self.print_msg.setStyleSheet("color:#a33; padding-top:6px")
        lv.addWidget(self.print_msg)
        lv.addStretch()
        row.addWidget(left, 0, Qt.AlignTop)

        # preview
        right = QFrame()
        right.setStyleSheet("QFrame { background:#e6e6e6; border-radius:6px; }")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(12, 12, 12, 8)
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumSize(300, 300)
        self.preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        rv.addWidget(self.preview, 1)
        nav = QHBoxLayout()
        nav.addStretch()
        self.pv_prev = QToolButton()
        self.pv_prev.setText("◀")
        self.pv_prev.setAutoRaise(True)
        self.pv_prev.clicked.connect(lambda: self._pv_step(-1))
        self.pv_label = QLabel()
        self.pv_label.setStyleSheet("background:transparent; color:#333; padding:0 10px")
        self.pv_next = QToolButton()
        self.pv_next.setText("▶")
        self.pv_next.setAutoRaise(True)
        self.pv_next.clicked.connect(lambda: self._pv_step(1))
        for x in (self.pv_prev, self.pv_label, self.pv_next):
            nav.addWidget(x)
        nav.addStretch()
        rv.addLayout(nav)
        row.addWidget(right, 1)
        v.addLayout(row, 1)

        self.pv_pos = 0
        for c in (self.range_combo, self.fit_combo, self.paper_combo, self.orient_combo, self.color_combo):
            c.currentIndexChanged.connect(self._print_settings_changed)
        self.range_edit.textChanged.connect(self._print_settings_changed)
        self._fill_printers()
        return w

    def _fill_printers(self):
        self.printer_combo.blockSignals(True)
        self.printer_combo.clear()
        try:
            infos = QPrinterInfo.availablePrinters()
            default = QPrinterInfo.defaultPrinterName()
        except Exception:
            infos, default = [], ""
        for info in infos:
            self.printer_combo.addItem(icons.icon("print", 16), info.printerName(), info.printerName())
        last = self.editor.settings.value("last_printer", "") or default
        i = self.printer_combo.findData(last)
        if i < 0:
            i = self.printer_combo.findData(default)
        self.printer_combo.setCurrentIndex(max(i, 0))
        if not infos:
            self.printer_combo.addItem("No printer found")
        self.printer_combo.blockSignals(False)
        self._printer_changed()

    def _printer_changed(self, *_):
        name = self.printer_combo.currentData()
        self.print_btn.setEnabled(bool(name))
        self.print_msg.setText("" if name else "Windows didn't report any printers. Click 'Add a printer'.")
        # paper sizes the printer supports
        keep = self.paper_combo.currentText()
        self.paper_combo.blockSignals(True)
        self.paper_combo.clear()
        doc = self.editor.doc
        self.paper_combo.addItem(f"Publication size ({_fmt_size(doc)})", None)
        sizes = []
        if name:
            try:
                sizes = QPrinterInfo.printerInfo(name).supportedPageSizes()
            except Exception:
                sizes = []
        if not sizes:
            sizes = [QPageSize(QPageSize.Letter), QPageSize(QPageSize.Legal), QPageSize(QPageSize.Tabloid),
                     QPageSize(QPageSize.A4), QPageSize(QPageSize.A3)]
        seen = set()
        for ps in sizes:
            if ps.name() in seen:
                continue
            seen.add(ps.name())
            self.paper_combo.addItem(ps.name(), ps)
        i = self.paper_combo.findText(keep)
        if i < 0:
            # Publisher's default: the paper that matches the publication, otherwise the publication size
            i = 0
            for j in range(1, self.paper_combo.count()):
                sz = self.paper_combo.itemData(j).size(QPageSize.Point)
                if {round(sz.width()), round(sz.height())} == {round(doc.width), round(doc.height)}:
                    i = j
                    break
        self.paper_combo.setCurrentIndex(i)
        self.paper_combo.blockSignals(False)
        self._print_settings_changed()

    def _selected_pages(self):
        ed = self.editor
        n = len(ed.doc.pages)
        mode = self.range_combo.currentIndex()
        if mode == 0:
            return list(range(n))
        if mode == 1:
            return [ed.page_index]
        out = []
        for part in self.range_edit.text().replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                if "-" in part:
                    a, b = part.split("-", 1)
                    a, b = int(a or 1), int(b or n)
                    out += list(range(min(a, b), max(a, b) + 1))
                else:
                    out.append(int(part))
            except ValueError:
                continue
        return [p - 1 for p in out if 1 <= p <= n] or list(range(n))

    def _paper_points(self):
        """Paper size in points for the current settings, oriented."""
        doc = self.editor.doc
        ps = self.paper_combo.currentData()
        if ps is None:
            w, h = doc.width, doc.height
        else:
            sz = ps.size(QPageSize.Point)
            w, h = sz.width(), sz.height()
        land = self.orient_combo.currentIndex() == 1
        if (w > h) != land:
            w, h = h, w
        return w, h

    def _print_settings_changed(self, *_):
        self.range_edit.setVisible(self.range_combo.currentIndex() == 2)
        self.pv_pos = min(self.pv_pos, max(len(self._selected_pages()) - 1, 0))
        self.refresh_preview()

    def _pv_step(self, d):
        self.pv_pos = max(0, min(self.pv_pos + d, len(self._selected_pages()) - 1))
        self.refresh_preview()

    def refresh_preview(self):
        ed = self.editor
        if not hasattr(self, "paper_combo"):
            return
        if self.paper_combo.count():
            self.paper_combo.setItemText(0, f"Publication size ({_fmt_size(ed.doc)})")
        pages = self._selected_pages()
        self.pv_pos = max(0, min(self.pv_pos, len(pages) - 1))
        idx = pages[self.pv_pos]
        pw, ph = self._paper_points()
        # fit the paper into the preview area
        avail_w = max(self.preview.width() - 30, 200)
        avail_h = max(self.preview.height() - 30, 200)
        dpr = self.devicePixelRatioF()
        z = min(avail_w / pw, avail_h / ph)
        img = QImage(int(pw * z * dpr) + 8, int(ph * z * dpr) + 8, QImage.Format_ARGB32)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        paper = QRectF(2, 2, pw * z, ph * z)
        p.fillRect(paper.translated(3, 3), QColor(0, 0, 0, 40))
        p.fillRect(paper, QColor(255, 255, 255))
        doc = ed.doc
        if self.fit_combo.currentIndex() == 0:
            m = 0.25 * 72 * z  # typical unprintable edge
            s = min((paper.width() - 2 * m) / doc.width, (paper.height() - 2 * m) / doc.height)
        else:
            s = z
        tw, th = doc.width * s, doc.height * s
        target = QRectF(paper.center().x() - tw / 2, paper.center().y() - th / 2, tw, th)
        p.save()
        p.setClipRect(paper)
        render_page(p, doc.pages[idx], doc, target)
        p.restore()
        if tw > paper.width() + 0.5 or th > paper.height() + 0.5:
            self.print_msg.setText("The publication is bigger than the paper, so its edges will be cut off. "
                                   "Choose 'Fit to Paper' or a larger paper size.")
        elif self.printer_combo.currentData():
            self.print_msg.setText("")
        p.end()
        if self.color_combo.currentIndex() == 1:
            g = img.convertToFormat(QImage.Format_Grayscale8).convertToFormat(QImage.Format_ARGB32)
            # keep the transparent surround
            for_alpha = img.convertToFormat(QImage.Format_Alpha8)
            g.setAlphaChannel(for_alpha)
            g.setDevicePixelRatio(dpr)
            img = g
        self.preview.setPixmap(QPixmap.fromImage(img))
        self.pv_label.setText(f"Page {idx + 1}   ({self.pv_pos + 1} of {len(pages)} to print)")
        self.pv_prev.setEnabled(self.pv_pos > 0)
        self.pv_next.setEnabled(self.pv_pos < len(pages) - 1)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if hasattr(self, "pages") and self.body.currentWidget() is self.pages.get("print"):
            QTimer.singleShot(0, self.refresh_preview)

    def do_print(self):
        ed = self.editor
        name = self.printer_combo.currentData()
        if not name:
            return
        ed.settings.setValue("last_printer", name)
        printer = QPrinter(QPrinterInfo.printerInfo(name), QPrinter.HighResolution)
        pw, ph = self._paper_points()
        ps = self.paper_combo.currentData()
        if ps is None:
            ps = QPageSize(QSizeF(min(pw, ph), max(pw, ph)), QPageSize.Point, "", QPageSize.FuzzyMatch)
        printer.setPageSize(ps)
        printer.setPageOrientation(QPageLayout.Landscape if pw > ph else QPageLayout.Portrait)
        printer.setDuplex([QPrinter.DuplexNone, QPrinter.DuplexLongSide, QPrinter.DuplexShortSide]
                          [self.duplex_combo.currentIndex()])
        printer.setColorMode(QPrinter.GrayScale if self.color_combo.currentIndex() == 1 else QPrinter.Color)
        printer.setDocName(os.path.basename(ed.path) if ed.path else "Publication1")
        copies = self.copies.value()
        printer.setCollateCopies(self.collate.isChecked())
        manual = 1
        printer.setCopyCount(copies)
        if copies > 1 and not printer.supportsMultipleCopies():
            printer.setCopyCount(1)
            manual = copies
        pages = self._selected_pages()
        if manual > 1:
            pages = [p for p in pages for _ in range(manual)] if not self.collate.isChecked() else pages * manual
        ed.close_backstage()
        ok = print_pages(ed.doc, printer, pages, fit=self.fit_combo.currentIndex() == 0)
        ed.statusBar().showMessage(f"Sent {len(pages)} page(s) to {name}" if ok else "Printing failed", 6000)

    def _export_page(self):
        w, v = self._page("Export")
        v.addWidget(self._big("pdf", "Create PDF", "Best for print shops and email.", self.editor.export_pdf))
        v.addWidget(self._big("image", "Save as Picture (PNG / JPG)", "For social media, websites and slides.",
                              self.editor.export_image))
        v.addWidget(self._big("save", "PubDesign Backup", "PubDesign's own backup format.",
                              lambda: self.editor.save_as("pubdesign")))
        v.addStretch()
        return w

    def show_page(self, key, animate=True):
        ed = self.editor
        if key == "save":
            ed.close_backstage()
            ed.save()
            return
        if key == "close":
            ed.close_backstage()
            ed.close_document()
            return
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        if key == "info":
            self.refresh_info()
        elif key == "open":
            self.refresh_recent()
        elif key == "home":
            self.refresh_home()
        elif key == "options":
            self.about_label.setText(f"PubDesign {VERSION}  ·  github.com/{updater.REPO}")
        if animate:
            anim.switch_stack_widget(self.body, self.pages[key], dy=22, duration=anim.NORMAL)
        else:
            self.body.setCurrentWidget(self.pages[key])
        if key == "print":
            self.orient_combo.blockSignals(True)
            self.orient_combo.setCurrentIndex(1 if ed.doc.width > ed.doc.height else 0)
            self.orient_combo.blockSignals(False)
            self.pv_pos = 0
            self._fill_printers()
            QTimer.singleShot(0, self.refresh_preview)


# ---------------------------------------------------------------------------
# dialogs
# ---------------------------------------------------------------------------
class PageSetupDialog(QDialog):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Page Setup")
        f = QFormLayout(self)
        self.preset = QComboBox()
        self.preset.addItem("Custom")
        for cat, name, w, h, unit in templates.SIZES:
            self.preset.addItem(name, (w, h, unit))
        f.addRow("Page size", self.preset)
        self.unit = QComboBox()
        self.unit.addItems(["in", "mm", "px"])
        self.unit.setCurrentText(getattr(doc, "unit", "in"))
        self.w, self.h, self.m = QDoubleSpinBox(), QDoubleSpinBox(), QDoubleSpinBox()
        for s in (self.w, self.h, self.m):
            s.setRange(0, 20000)
            s.setDecimals(2)
        uf = unit_factor(self.unit.currentText())
        self.w.setValue(doc.width / uf)
        self.h.setValue(doc.height / uf)
        self.m.setValue(getattr(doc, "margin", 36) / uf)
        f.addRow("Width", self.w)
        f.addRow("Height", self.h)
        f.addRow("Margin guides", self.m)
        f.addRow("Units", self.unit)
        self.scale = QCheckBox("Scale existing objects to fit the new size")
        self.scale.setChecked(True)
        f.addRow(self.scale)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)
        self.preset.currentIndexChanged.connect(self._preset)
        self._last = self.unit.currentText()
        self.unit.currentTextChanged.connect(self._unit)

    def _preset(self, i):
        d = self.preset.itemData(i)
        if d:
            w, h, unit = d
            self.unit.setCurrentText(unit)
            uf = unit_factor(unit)
            self.w.setValue(w / uf)
            self.h.setValue(h / uf)

    def _unit(self, u):
        a, b = unit_factor(self._last), unit_factor(u)
        for s in (self.w, self.h, self.m):
            s.setValue(s.value() * a / b)
        self._last = u

    def values(self):
        uf = unit_factor(self.unit.currentText())
        return (self.w.value() * uf, self.h.value() * uf, self.m.value() * uf, self.unit.currentText(),
                self.scale.isChecked())


class FormatDialog(QDialog):
    """Format Object: size, position, rotation and line weight."""

    def __init__(self, shape, unit, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Format Object")
        self.uf = unit_factor(unit)
        f = QFormLayout(self)
        self.fields = {}
        for key, label, val, lo, hi in [("x", "Horizontal position", shape.pos().x() / self.uf, -10000, 10000),
                                        ("y", "Vertical position", shape.pos().y() / self.uf, -10000, 10000),
                                        ("w", "Width", shape.w / self.uf, -10000, 10000),
                                        ("h", "Height", shape.h / self.uf, -10000, 10000),
                                        ("rot", "Rotation", shape.rotation(), -360, 360),
                                        ("lw", "Line weight", shape.stroke_width, 0.25, 100)]:
            s = QDoubleSpinBox()
            s.setRange(lo, hi)
            s.setDecimals(3 if key in "xywh" else 2)
            s.setValue(val)
            s.setSuffix(f" {unit}" if key in "xywh" else ("°" if key == "rot" else " pt"))
            f.addRow(label, s)
            self.fields[key] = s
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def values(self):
        g = {k: s.value() for k, s in self.fields.items()}
        for k in "xywh":
            g[k] *= self.uf
        return g


def _thumb_icon(img):
    """Page thumbnail icon that keeps its true colours when selected (no blue tint)."""
    pm = QPixmap.fromImage(img)
    ic = QIcon()
    for mode in (QIcon.Normal, QIcon.Selected, QIcon.Active):
        ic.addPixmap(pm, mode)
    return ic


# ---------------------------------------------------------------------------
# window frame (resize edges for the custom title bar)
# ---------------------------------------------------------------------------
class WindowFrame(QWidget):
    """Thin border around the window that resizes it, used with the custom title bar."""
    GRIP = 5

    def __init__(self, win, frameless):
        super().__init__()
        self.win = win
        self.frameless = frameless
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("WindowFrame")
        self.lay = QVBoxLayout(self)
        self.lay.setSpacing(0)
        self.sync()
        if frameless:
            # the resize cursor set on this border is inherited by everything inside it, so clear it
            # as soon as the pointer moves onto any other part of the window
            QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Enter, QEvent.MouseMove) and self.testAttribute(Qt.WA_SetCursor) \
                and isinstance(obj, QWidget) and obj is not self and self.isAncestorOf(obj):
            self.unsetCursor()
        return False

    def leaveEvent(self, ev):
        self.unsetCursor()
        super().leaveEvent(ev)

    def sync(self):
        m = self.GRIP if (self.frameless and not self.win.isMaximized() and not self.win.isFullScreen()) else 0
        self.lay.setContentsMargins(m, m, m, m)
        if not m:
            self.unsetCursor()
        self.setStyleSheet(f"#WindowFrame {{ background: {CHROME}; border: {1 if m else 0}px solid #b9b9b9; }}")

    def _edges(self, pos):
        if not self.frameless or self.win.isMaximized():
            return Qt.Edges()
        g = self.GRIP + 2
        e = Qt.Edges()
        if pos.x() <= g:
            e |= Qt.LeftEdge
        if pos.x() >= self.width() - g:
            e |= Qt.RightEdge
        if pos.y() <= g:
            e |= Qt.TopEdge
        if pos.y() >= self.height() - g:
            e |= Qt.BottomEdge
        return e

    def mouseMoveEvent(self, ev):
        e = self._edges(ev.position().toPoint())
        if e in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            self.setCursor(Qt.SizeFDiagCursor)
        elif e in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            self.setCursor(Qt.SizeBDiagCursor)
        elif e & (Qt.LeftEdge | Qt.RightEdge):
            self.setCursor(Qt.SizeHorCursor)
        elif e & (Qt.TopEdge | Qt.BottomEdge):
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(ev)

    def mousePressEvent(self, ev):
        e = self._edges(ev.position().toPoint())
        if e and ev.button() == Qt.LeftButton and self.win.windowHandle() is not None:
            self.win.windowHandle().startSystemResize(e)
            return
        super().mousePressEvent(ev)


# ---------------------------------------------------------------------------
# main window
# ---------------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(app_icon())
        self.settings = QSettings("PubDesign", "PubDesign")
        self.doc = templates.blank(612, 792)
        self.page_index = 0
        self.path = None
        self.dirty = False
        self.tool = "select"
        self.tool_spt = 1
        self.snap = docio.Snapshotter()
        self.history = []
        self.hpos = -1
        self.clip = None
        self._loading = False
        self._suspend = False
        self.show_guides = True
        self.show_boundaries = True
        self.scene = None
        self.painter_fmt = None

        self.frameless = not self.settings.value("classic_titlebar", False, type=bool)
        if self.frameless:
            self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.frame = WindowFrame(self, self.frameless)
        self.setCentralWidget(self.frame)
        self.titlebar = TitleBar(self, self.frameless, asset("logo.png") if os.path.exists(asset("logo.png")) else None)
        self.frame.lay.addWidget(self.titlebar)
        self.stack = QStackedWidget()
        self.frame.lay.addWidget(self.stack, 1)
        editor = QWidget()
        ev = QVBoxLayout(editor)
        ev.setContentsMargins(0, 0, 0, 0)
        ev.setSpacing(0)
        self.ribbon = Ribbon()
        self.ribbon.fileClicked.connect(self.open_backstage)
        ev.addWidget(self.ribbon)
        self.msgbar = self._build_msgbar()
        ev.addWidget(self.msgbar)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setHandleWidth(1)
        self.nav = self._build_nav()
        self.split.addWidget(self.nav)
        work = QWidget()
        g = QGridLayout(work)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(0)
        self.view = PageView(self)
        self.hruler = Ruler(Qt.Horizontal, self)
        self.vruler = Ruler(Qt.Vertical, self)
        corner = QWidget()
        corner.setFixedSize(Ruler.THICK, Ruler.THICK)
        corner.setStyleSheet("background:#e8e8e8")
        g.addWidget(corner, 0, 0)
        g.addWidget(self.hruler, 0, 1)
        g.addWidget(self.vruler, 1, 0)
        g.addWidget(self.view, 1, 1)
        self.split.addWidget(work)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([160, 1200])
        ev.addWidget(self.split, 1)
        self.stack.addWidget(editor)
        self._build_status()
        self.backstage = Backstage(self)
        self.stack.addWidget(self.backstage)
        self._build_shortcuts()
        self._build_ribbon()
        self._build_command_search()
        self.setStyleSheet(RIBBON_QSS)
        self.resize(1400, 900)
        self.load_document(self.doc, None)
        self.checker = updater.UpdateChecker()
        self.checker.available.connect(self._update_available)
        self.checker.upToDate.connect(self._up_to_date)
        self.checker.failed.connect(self._update_failed)
        self._manual_check = False
        self._ready_setup = None
        self.downloader = None
        if updater.FROZEN:
            self.downloader = updater.SetupDownloader()
            self.downloader.ready.connect(self._update_downloaded)
            self.downloader.failed.connect(lambda e: None)
        if self.settings.value("auto_update", True, type=bool):
            QTimer.singleShot(2500, self.checker.check)

    # ================= updates =================
    def _build_msgbar(self):
        bar = QFrame()
        bar.setStyleSheet("QFrame { background:#fff4ce; border-bottom:1px solid #e8d48a; }"
                          "QLabel { color:#333; } QPushButton { padding:3px 12px; }")
        h = QHBoxLayout(bar)
        h.setContentsMargins(12, 4, 8, 4)
        self.msg_label = QLabel()
        h.addWidget(self.msg_label, 1)
        self.msg_btn = QPushButton("Update now")
        self.msg_btn.clicked.connect(self.install_update)
        h.addWidget(self.msg_btn)
        close = QToolButton()
        close.setText("✕")
        close.setAutoRaise(True)
        close.clicked.connect(lambda: bar.setVisible(False))
        h.addWidget(close)
        bar.setVisible(False)
        return bar

    def check_for_updates(self):
        self._manual_check = True
        self.statusBar().showMessage("Checking for updates…", 4000)
        self.checker.check()

    def _update_available(self, version, notes):
        self._pending_version = version
        txt = f"<b>UPDATE AVAILABLE</b> &nbsp; PubDesign {version} is ready (you have {VERSION})."
        if notes:
            txt += f" &nbsp; <span style='color:#555'>{notes}</span>"
        self.msg_label.setText(txt)
        if not self.msgbar.isVisible():
            anim.animate_height(self.msgbar, True)
        if self.downloader is not None and self._ready_setup is None:
            # get it ready in the background; it installs when PubDesign closes
            self.downloader.start()
        if self._manual_check:
            self._manual_check = False
            self.close_backstage()

    def _update_downloaded(self, path, version):
        self._ready_setup = path
        self.msg_label.setText(f"<b>UPDATE READY</b> &nbsp; PubDesign {version} is downloaded. It installs "
                               "automatically when you close PubDesign, or click Restart now.")
        self.msg_btn.setText("Restart now")
        if not self.msgbar.isVisible():
            anim.animate_height(self.msgbar, True)

    def _up_to_date(self, v):
        if self._manual_check:
            self._manual_check = False
            QMessageBox.information(self, APP, f"You're up to date. PubDesign {v} is the newest version.")

    def _update_failed(self, err):
        if self._manual_check:
            self._manual_check = False
            QMessageBox.warning(self, APP, f"Couldn't check for updates. Check your internet connection.\n\n{err}")

    def install_update(self):
        if not self.maybe_save():
            return
        if updater.FROZEN and self._ready_setup and os.path.exists(self._ready_setup):
            updater.launch_setup(self._ready_setup, relaunch=True)
            self._ready_setup = None
            self.dirty = False
            QApplication.quit()
            return
        prog = QProgressDialog("Downloading update…", None, 0, 100, self)
        prog.setWindowTitle(APP)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)
        prog.show()

        def progress(done, total):
            prog.setValue(int(done * 100 / total) if total else 50)
            QApplication.processEvents()
        try:
            if updater.FROZEN:
                new = updater.install_exe_update(progress)
            else:
                new = updater.install_update(progress)
        except Exception as e:
            prog.close()
            QMessageBox.critical(self, APP, f"The update couldn't be installed:\n{e}\n\nPubDesign wasn't changed.")
            return
        prog.close()
        self.dirty = False
        if updater.FROZEN:
            QMessageBox.information(self, APP, f"PubDesign will close and install version {new}. A small progress window "
                                    "shows the install, then PubDesign reopens by itself.")
        else:
            QMessageBox.information(self, APP, f"PubDesign {new} is installed. PubDesign will now restart.")
            updater.restart()
        QApplication.quit()

    # ================= construction =================
    def _build_nav(self):
        w = QWidget()
        w.setMinimumWidth(120)
        w.setMaximumWidth(260)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        head = QLabel("  Pages")
        head.setStyleSheet("background:#f3f3f3; color:#444; padding:5px; border-bottom:1px solid #ddd; font-weight:600")
        v.addWidget(head)
        self.pages_list = QListWidget()
        self.pages_list.setViewMode(QListWidget.IconMode)
        self.pages_list.setFlow(QListWidget.TopToBottom)
        self.pages_list.setWrapping(False)
        self.pages_list.setMovement(QListWidget.Static)
        self.pages_list.setResizeMode(QListWidget.Adjust)
        self.pages_list.setIconSize(QSize(110, 140))
        self.pages_list.setSpacing(6)
        self.pages_list.setStyleSheet(
            "QListWidget { background:#e9e9e9; border:none; }"
            "QListWidget::item { color:#333; border:2px solid transparent; padding:2px; }"
            f"QListWidget::item:selected {{ background:#d5e9e6; border:2px solid {ACCENT}; color:{ACCENT}; }}")
        self.pages_list.currentRowChanged.connect(self._page_clicked)
        self.pages_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.pages_list.customContextMenuRequested.connect(self._pages_menu)
        v.addWidget(self.pages_list, 1)
        return w

    def _pages_menu(self, pos):
        m = QMenu(self)
        m.addAction(icons.icon("page_add", 16), "Insert Page", self.add_page)
        m.addAction(icons.icon("page_dup", 16), "Insert Duplicate Page", self.duplicate_page)
        m.addAction(icons.icon("page_del", 16), "Delete", self.delete_page)
        m.addSeparator()
        m.addAction("Move Up", lambda: self.move_page(-1))
        m.addAction("Move Down", lambda: self.move_page(1))
        m.exec(self.pages_list.mapToGlobal(pos))

    def _shortcut(self, seq, slot):
        a = QAction(self)
        a.setShortcut(QKeySequence(seq))
        a.setShortcutContext(Qt.WindowShortcut)
        a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _build_shortcuts(self):
        S = self._shortcut
        S(QKeySequence.New, lambda: self.open_backstage("new"))
        S(QKeySequence.Open, lambda: self.open_doc())
        S(QKeySequence.Save, self.save)
        S("F12", lambda: self.save_as(None))
        S(QKeySequence.Print, lambda: self.open_backstage("print"))
        S(QKeySequence.Undo, self.undo)
        S(QKeySequence.Redo, self.redo)
        S(QKeySequence.Cut, self.cut)
        S(QKeySequence.Copy, self.copy)
        S(QKeySequence.Paste, self.paste)
        S("Ctrl+D", self.duplicate)
        S(QKeySequence.Delete, self.delete_selected)
        S(QKeySequence.SelectAll, self.select_all)
        S(QKeySequence.Bold, lambda: self.toggle_char("bold"))
        S(QKeySequence.Italic, lambda: self.toggle_char("italic"))
        S(QKeySequence.Underline, lambda: self.toggle_char("underline"))
        S("Ctrl+Shift+>", lambda: self.bump_size(1))
        S("Ctrl+Shift+<", lambda: self.bump_size(-1))
        S("Ctrl+]", lambda: self.bump_size(1))
        S("Ctrl+[", lambda: self.bump_size(-1))
        S("Ctrl+L", lambda: self.apply_align("left"))
        S("Ctrl+E", lambda: self.apply_align("center"))
        S("Ctrl+R", lambda: self.apply_align("right"))
        S("Ctrl+J", lambda: self.apply_align("justify"))
        S("Ctrl+Shift+N", self.add_page)
        S("Ctrl+Shift+C", self.start_painter)
        S("F9", self.zoom_100)
        S("Alt+Q", lambda: (self.titlebar.search.setFocus(), self.titlebar.search.selectAll()))
        S("Ctrl+F1", lambda: self.ribbon.toggle_collapsed())
        S("Ctrl+Shift+L", self.whole_page)
        S("Ctrl+=", lambda: self.zoom_smooth(self.zoom_target() * 1.25))
        S("Ctrl+-", lambda: self.zoom_smooth(self.zoom_target() / 1.25))

    def _build_ribbon(self):
        R = self.ribbon
        T = self.titlebar
        T.add_qat("save", self.save, "Save (Ctrl+S)")
        T.add_qat("undo", self.undo, "Undo (Ctrl+Z)")
        T.add_qat("redo", self.redo, "Redo (Ctrl+Y)")
        share = QToolButton()
        share.setObjectName("ShareBtn")
        share.setText("  Export  ")
        share.setIcon(icons.icon("export", 16))
        share.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        share.setPopupMode(QToolButton.InstantPopup)
        share.setStyleSheet(f"#ShareBtn {{ background:{ACCENT}; color:white; border:none; border-radius:5px; "
                            f"padding:4px 10px; font-size:9pt; }} #ShareBtn:hover {{ background:{ACCENT_DARK}; }}"
                            "#ShareBtn::menu-indicator { image:none; }")
        sm_ = QMenu(self)
        sm_.addAction(icons.icon("pdf", 16), "Create PDF", self.export_pdf)
        sm_.addAction(icons.icon("image", 16), "Save as Picture", self.export_image)
        sm_.addAction(icons.icon("print", 16), "Print", lambda: self.open_backstage("print"))
        sm_.addSeparator()
        sm_.addAction(icons.icon("save", 16), "Save a backup copy (.pubdesign)", lambda: self.save_as("pubdesign"))
        share.setMenu(sm_)
        R.right.addWidget(share)

        # ---------------- Home ----------------
        home = R.add_page("Home")
        g = home.group("Clipboard")
        g.add(large_button("Paste", "paste", self.paste))
        self.painter_btn = small_button("Format Painter", "painter", self.start_painter, checkable=True,
                                        tip="Format Painter (Ctrl+Shift+C): copy formatting to another object")
        g.column(small_button("Cut", "cut", self.cut), small_button("Copy", "copy", self.copy), self.painter_btn)

        g = home.group("Font")
        self.font_box = QFontComboBox()
        self.font_box.setFixedWidth(150)
        self.font_box.setCurrentFont(QFont(self.settings.value("font", "Calibri")))
        self.font_box.currentFontChanged.connect(lambda f: self.apply_char(font=f.family()))
        self.size_box = QComboBox()
        self.size_box.setEditable(True)
        self.size_box.addItems([str(s) for s in [8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 48, 54, 60,
                                                 72, 96, 120, 144]])
        self.size_box.setFixedWidth(58)
        self.size_box.setEditText(str(self.settings.value("size", 14)))
        self.size_box.lineEdit().returnPressed.connect(self._size_entered)
        self.size_box.activated.connect(lambda i: self._size_entered())
        self.b_btn = small_button("", None, lambda: self.toggle_char("bold"), checkable=True, tip="Bold (Ctrl+B)",
                                  text_visible=False)
        self.i_btn = small_button("", None, lambda: self.toggle_char("italic"), checkable=True, tip="Italic (Ctrl+I)",
                                  text_visible=False)
        self.u_btn = small_button("", None, lambda: self.toggle_char("underline"), checkable=True,
                                  tip="Underline (Ctrl+U)", text_visible=False)
        for b, t in ((self.b_btn, "B"), (self.i_btn, "I"), (self.u_btn, "U")):
            b.setToolButtonStyle(Qt.ToolButtonTextOnly)
            b.setText(t)
            f = QFont("Georgia", 10)
            f.setBold(t == "B")
            f.setItalic(t == "I")
            f.setUnderline(t == "U")
            b.setFont(f)
            b.setFixedWidth(26)
        fc_menu = ColorMenu(none_text="Automatic")
        fc_menu.picked.connect(lambda c: self.apply_char(color=c or (0, 0, 0)))
        self.fontcolor_btn = small_button("", "fontcolor", None, menu=fc_menu, tip="Font Color", text_visible=False)
        g.column([self.font_box, self.size_box,
                  small_button("", "grow", lambda: self.bump_size(1), tip="Increase Font Size (Ctrl+Shift+>)",
                               text_visible=False),
                  small_button("", "shrink", lambda: self.bump_size(-1), tip="Decrease Font Size (Ctrl+Shift+<)",
                               text_visible=False)],
                 [self.b_btn, self.i_btn, self.u_btn, self.fontcolor_btn])

        g = home.group("Paragraph")
        self.align_btns = {}
        row = []
        for key, ic, tip in [("left", "al", "Align Left (Ctrl+L)"), ("center", "ac", "Center (Ctrl+E)"),
                             ("right", "ar", "Align Right (Ctrl+R)"), ("justify", "aj", "Justify (Ctrl+J)")]:
            b = small_button("", ic, lambda _=False, k=key: self.apply_align(k), checkable=True, tip=tip,
                             text_visible=False)
            self.align_btns[key] = b
            row.append(b)
        g.column([small_button("", "bullets", self.toggle_bullets, tip="Bullets", text_visible=False)], row)

        g = home.group("Objects")
        g.add(large_button("Draw Text\nBox", "textbox", lambda: self.set_tool("text"),
                           tip="Draw a text box: click and drag on the page"))
        g.add(large_button("Pictures", "picture", self.insert_picture, tip="Insert a picture from your computer"))
        g.add(large_button("Shapes", "shapes", None, menu=self._shape_menu(self.pick_shape_tool)))

        g = home.group("Arrange", self.format_object_dialog, "Format Object (size, position, rotation)")
        g.column(self._forward_btn(), self._backward_btn(), self._align_btn())
        g.column(self._rotate_btn(), small_button("Select All", "selectall", self.select_all))

        # ---------------- Insert ----------------
        ins = R.add_page("Insert")
        g = ins.group("Pages")
        pm = QMenu(self)
        pm.addAction(icons.icon("page_add", 16), "Insert Blank Page", self.add_page)
        pm.addAction(icons.icon("page_dup", 16), "Insert Duplicate Page", self.duplicate_page)
        pm.addSeparator()
        pm.addAction(icons.icon("page_del", 16), "Delete Page", self.delete_page)
        g.add(large_button("Page", "page_add", self.add_page, menu=pm, tip="Insert a page after this one"))
        g = ins.group("Illustrations")
        g.add(large_button("Pictures", "picture", self.insert_picture))
        g.add(large_button("Shapes", "shapes", None, menu=self._shape_menu(self.pick_shape_tool)))
        g = ins.group("Text")
        g.add(large_button("Draw Text\nBox", "textbox", lambda: self.set_tool("text")))

        # ---------------- Page Design ----------------
        pd = R.add_page("Page Design")
        g = pd.group("Page Setup", self.page_setup_dialog, "Page Setup")
        mm = QMenu(self)
        for label, inch in [("None", 0), ("Narrow (0.25\")", 0.25), ("Moderate (0.5\")", 0.5), ("Wide (1\")", 1.0)]:
            mm.addAction(label, lambda _=False, v=inch: self.set_margins(v * 72))
        mm.addSeparator()
        mm.addAction("Custom Margins…", self.page_setup_dialog)
        g.add(large_button("Margins", "margins", None, menu=mm))
        om = QMenu(self)
        om.addAction("Portrait", lambda: self.set_orientation("portrait"))
        om.addAction("Landscape", lambda: self.set_orientation("landscape"))
        g.add(large_button("Orientation", "orient", None, menu=om))
        szm = QMenu(self)
        last_cat = None
        for cat, name, w, h, unit in templates.SIZES:
            if cat != last_cat:
                szm.addSection(cat)
                last_cat = cat
            szm.addAction(name, lambda _=False, a=(w, h, unit): self.set_page_size(*a))
        szm.addSeparator()
        szm.addAction("Page Setup…", self.page_setup_dialog)
        g.add(large_button("Size", "size", None, menu=szm))
        g = pd.group("Page Background")
        bgm = ColorMenu(none_text="No Background", more_text="More Colors…", parent=self)
        bgm.picked.connect(self.set_background)
        g.add(large_button("Background", "background", None, menu=bgm))
        g = pd.group("Pages")
        g.column(small_button("Insert Page", "page_add", self.add_page),
                 small_button("Duplicate Page", "page_dup", self.duplicate_page),
                 small_button("Delete Page", "page_del", self.delete_page))
        g.column(small_button("Move Page Up", None, lambda: self.move_page(-1)),
                 small_button("Move Page Down", None, lambda: self.move_page(1)))

        # ---------------- View ----------------
        vw = R.add_page("View")
        g = vw.group("Show")
        self.chk_bounds = QCheckBox("Boundaries")
        self.chk_guides = QCheckBox("Guides")
        self.chk_rulers = QCheckBox("Rulers")
        self.chk_nav = QCheckBox("Page Navigation")
        for c in (self.chk_bounds, self.chk_guides, self.chk_rulers, self.chk_nav):
            c.setChecked(True)
        self.chk_bounds.toggled.connect(self.toggle_boundaries)
        self.chk_guides.toggled.connect(self.toggle_guides)
        self.chk_rulers.toggled.connect(self.toggle_rulers)
        self.chk_nav.toggled.connect(self.nav.setVisible)
        g.column(self.chk_bounds, self.chk_guides)
        g.column(self.chk_rulers, self.chk_nav)
        g = vw.group("Zoom")
        g.add(large_button("100%", "zoom100", self.zoom_100, tip="Actual size (F9)"))
        g.add(large_button("Whole\nPage", "zoom_page", self.whole_page, tip="Whole page (Ctrl+Shift+L)"))
        g.add(large_button("Page\nWidth", "zoom_width", self.page_width))
        g.column(small_button("Zoom In", "zoom_in", lambda: self.zoom_smooth(self.zoom_target() * 1.25)),
                 small_button("Zoom Out", "zoom_out", lambda: self.zoom_smooth(self.zoom_target() / 1.25)))

        # ---------------- contextual: Shape Format ----------------
        sf = R.add_page("Shape Format", contextual=True)
        g = sf.group("Insert Shapes")
        g.add(large_button("Shapes", "shapes", None, menu=self._shape_menu(self.pick_shape_tool)))
        g.add(large_button("Change\nShape", "shapes", None, menu=self._shape_menu(self.change_shape, lines=False)))
        g = sf.group("Shape Styles")
        g.column(self._fill_btn(), self._outline_btn(), self._weight_btn())
        g = sf.group("Arrange", self.format_object_dialog, "Format Object (size, position, rotation)")
        g.column(self._forward_btn(), self._backward_btn(), self._align_btn())
        g.column(self._rotate_btn())
        g = sf.group("Size")
        self.size_fields_shape = self._size_fields(g)

        # ---------------- contextual: Text Box ----------------
        tf = R.add_page("Text Box", contextual=True)
        g = tf.group("Text Box Styles")
        g.column(self._fill_btn(), self._outline_btn(), self._weight_btn())
        g = tf.group("Alignment")
        self.valign_btns = {}
        for key, ic, label in [("top", "vtop", "Top"), ("middle", "vmid", "Middle"), ("bottom", "vbot", "Bottom")]:
            b = large_button(label, ic, lambda _=False, k=key: self.apply_shape(valign=k), checkable=True)
            self.valign_btns[key] = b
            g.add(b)
        g = tf.group("Arrange", self.format_object_dialog, "Format Object (size, position, rotation)")
        g.column(self._forward_btn(), self._backward_btn(), self._align_btn())
        g.column(self._rotate_btn())
        g = tf.group("Size")
        self.size_fields_text = self._size_fields(g)

        # ---------------- contextual: Picture Format ----------------
        pf = R.add_page("Picture Format", contextual=True)
        g = pf.group("Insert")
        g.add(large_button("Change\nPicture", "change_pic", self.change_picture))
        g.add(large_button("Reset\nSize", "reset", self.reset_picture_size))
        g = pf.group("Picture Styles")
        g.column(self._outline_btn("Picture Border"), self._weight_btn())
        g = pf.group("Arrange", self.format_object_dialog, "Format Object (size, position, rotation)")
        g.column(self._forward_btn(), self._backward_btn(), self._align_btn())
        g.column(self._rotate_btn())
        g = pf.group("Size")
        self.size_fields_pic = self._size_fields(g)
        R.tabs.setCurrentIndex(0)

    def _shape_menu(self, slot, lines=True):
        m = ShapeMenu(self)
        m.picked.connect(slot)
        return m

    def _forward_btn(self):
        m = QMenu(self)
        m.addAction("Bring Forward", lambda: self.restack("up"))
        m.addAction("Bring to Front", lambda: self.restack("front"))
        return small_button("Bring Forward", "forward", lambda: self.restack("up"), menu=m)

    def _backward_btn(self):
        m = QMenu(self)
        m.addAction("Send Backward", lambda: self.restack("down"))
        m.addAction("Send to Back", lambda: self.restack("back"))
        return small_button("Send Backward", "backward", lambda: self.restack("down"), menu=m)

    def _align_btn(self):
        m = QMenu(self)
        for name, key in [("Align Left", "l"), ("Align Center", "c"), ("Align Right", "r"), (None, None),
                          ("Align Top", "t"), ("Align Middle", "m"), ("Align Bottom", "b"), (None, None),
                          ("Center on Page", "page")]:
            if name is None:
                m.addSeparator()
            else:
                m.addAction(name, lambda _=False, k=key: self.align(k))
        return small_button("Align", "align", None, menu=m)

    def _rotate_btn(self):
        m = QMenu(self)
        m.addAction("Rotate Right 90°", lambda: self.rotate_by(90))
        m.addAction("Rotate Left 90°", lambda: self.rotate_by(-90))
        m.addAction("Clear Rotation", lambda: self.rotate_by(None))
        m.addSeparator()
        m.addAction("Flip Horizontal", lambda: self.flip("h"))
        m.addAction("Flip Vertical", lambda: self.flip("v"))
        m.addSeparator()
        m.addAction("More Rotation Options…", self.format_object_dialog)
        return small_button("Rotate", "rotate", None, menu=m)

    def _fill_btn(self, label="Shape Fill"):
        m = ColorMenu(none_text="No Fill", more_text="More Fill Colors…", parent=self)
        m.picked.connect(lambda c: self.apply_shape(fill=c))
        return small_button(label, "fill", None, menu=m)

    def _outline_btn(self, label="Shape Outline"):
        m = ColorMenu(none_text="No Outline", more_text="More Outline Colors…", parent=self)
        m.picked.connect(lambda c: self.apply_shape(stroke=c))
        return small_button(label, "outline", None, menu=m)

    def _weight_btn(self):
        m = QMenu(self)
        for wv in [0.25, 0.5, 0.75, 1, 1.5, 2.25, 3, 4.5, 6, 8, 12]:
            m.addAction(f"{wv:g} pt", lambda _=False, v=wv: self.apply_shape(stroke_width=v))
        return small_button("Weight", "weight", None, menu=m)

    def _size_fields(self, g):
        hs, ws = QDoubleSpinBox(), QDoubleSpinBox()
        for s in (hs, ws):
            s.setRange(0.01, 100000)
            s.setDecimals(2)
            s.setKeyboardTracking(False)
            s.setFixedWidth(96)
            s.valueChanged.connect(self._size_edited)
        g.column([QLabel("Height "), hs], [QLabel("Width  "), ws])
        return hs, ws

    def _build_status(self):
        sb = QStatusBar()
        sb.setStyleSheet("QStatusBar { background:#f3f3f3; border-top:1px solid #ddd; } QLabel { color:#444; }")
        self.setStatusBar(sb)
        self.page_label = QLabel()
        self.pos_label = QLabel()
        self.objsize_label = QLabel()
        for w in (self.page_label, self.pos_label, self.objsize_label):
            w.setContentsMargins(8, 0, 8, 0)
            sb.addWidget(w)
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(10, 400)
        self.zoom_slider.setFixedWidth(140)
        self.zoom_slider.valueChanged.connect(self._slider_zoom)
        self.zoom_pct = QLabel("100%")
        self.zoom_pct.setFixedWidth(42)
        fit = small_button("", "zoom_page", self.whole_page, tip="Whole Page (Ctrl+Shift+L)", text_visible=False)
        zo = small_button("−", None, lambda: self.zoom_smooth(self.zoom_target() / 1.1), tip="Zoom Out")
        zi = small_button("+", None, lambda: self.zoom_smooth(self.zoom_target() * 1.1), tip="Zoom In")
        for w in (fit, zo, self.zoom_slider, zi, self.zoom_pct):
            sb.addPermanentWidget(w)

    # ================= document lifecycle =================
    def load_document(self, doc, path, fresh_history=True):
        self.doc = doc
        for attr, default in (("unit", "in"), ("margin", 36)):
            if not hasattr(self.doc, attr):
                setattr(self.doc, attr, default)
        self.path = path
        self.page_index = 0
        if fresh_history:
            self.history = []
            self.hpos = -1
        self.show_page(0)
        if fresh_history:
            self._push_history()
            self.dirty = False
        self.refresh_pages()
        self.update_title()
        if path:
            self.add_recent(path)
        QTimer.singleShot(0, self.whole_page)

    def new_from(self, doc):
        if not self.maybe_save():
            return
        self.close_backstage()
        self.load_document(doc, None)

    def close_document(self):
        if self.maybe_save():
            self.load_document(templates.blank(612, 792), None)

    def show_page(self, idx):
        idx = max(0, min(idx, len(self.doc.pages) - 1))
        self.page_index = idx
        old = self.scene
        if old is not None:
            try:
                old.selectionChanged.disconnect(self.selection_changed)
            except Exception:
                pass
        sc = PageScene(self.doc.width, self.doc.height, show_guides=self.show_guides, margin=self.doc.margin)
        sc.show_boundaries = self.show_boundaries
        for z, it in enumerate(self.doc.pages[idx].items):
            self._add_shape(sc, it, z)
        self.scene = sc
        sc.selectionChanged.connect(self.selection_changed)
        sc.selectionChanged.connect(lambda: QTimer.singleShot(0, self.view.refresh_cursor))
        self.view.setScene(sc)
        if old is not None:
            old.deleteLater()
        self.page_label.setText(f"Page: {idx + 1} of {len(self.doc.pages)}")
        self.selection_changed()

    def _add_shape(self, sc, it, z):
        si = ShapeItem(it)
        si.setZValue(z)
        si.committed.connect(self.checkpoint)
        si.editingChanged.connect(lambda on: self.sync_toolbar())
        si.editingChanged.connect(lambda on: QTimer.singleShot(0, self.view.refresh_cursor))
        if si.text is not None:
            si.text.document().cursorPositionChanged.connect(lambda *_: self.sync_toolbar())
        sc.addItem(si)
        return si

    def sync_from_scene(self):
        if self.scene is None:
            return
        try:
            self.doc.pages[self.page_index].items = [s.to_model() for s in self.scene.shapes()]
        except RuntimeError:
            pass

    def _push_history(self):
        s = self.snap.snap(self.doc)
        if self.hpos >= 0 and self.history[self.hpos][0] == s:
            return False
        self.history = self.history[:self.hpos + 1]
        self.history.append((s, self.page_index))
        if len(self.history) > 200:
            self.history.pop(0)
        self.hpos = len(self.history) - 1
        return True

    def checkpoint(self):
        if self._loading:
            return
        self.sync_from_scene()
        if self._push_history():
            self.dirty = True
            self.update_title()
            QTimer.singleShot(0, self.refresh_current_thumb)
        self.selection_changed()

    def undo(self):
        ed = self.editing_shape()
        if ed:
            ed.text.document().undo()
            return
        self.checkpoint()
        if self.hpos > 0:
            self.hpos -= 1
            self._restore()

    def redo(self):
        ed = self.editing_shape()
        if ed:
            ed.text.document().redo()
            return
        if self.hpos < len(self.history) - 1:
            self.hpos += 1
            self._restore()

    def _restore(self):
        s, pi = self.history[self.hpos]
        self.doc = self.snap.restore(s)
        self._loading = True
        self.show_page(min(pi, len(self.doc.pages) - 1))
        self._loading = False
        self.refresh_pages()
        self.dirty = True
        self.update_title()

    def update_title(self):
        name = os.path.basename(self.path) if self.path else "Publication1"
        self.setWindowTitle(f"{'*' if self.dirty else ''}{name} - {APP}")
        self.titlebar.set_title(f"{'*' if self.dirty else ''}{name}  -  {APP}")

    def changeEvent(self, ev):
        if ev.type() == ev.Type.WindowStateChange:
            self.frame.sync()
            self.titlebar.sync_max_icon()
        super().changeEvent(ev)

    # ================= command search (title bar) =================
    def _build_command_search(self):
        cmds = {}
        R = self.ribbon
        for ti in range(R.stack.count()):
            page = R.stack.widget(ti)
            for b in page.findChildren(QToolButton):
                if not b.property("ribbon"):
                    continue
                name = (b.text() or "").replace("▾", "").replace("\n", " ").strip()
                if len(name) <= 4 or name in ("Top", "Middle", "Bottom", "Page", "Size", "Center"):
                    name = (b.toolTip() or name).replace("\n", " ").strip()
                name = name.split(" (")[0].strip()
                if name and name not in cmds:
                    cmds[name] = ("button", ti, b)
        for name, fn in [("Save", self.save), ("Save As", lambda: self.save_as("pub")), ("Open", self.open_doc),
                         ("New", lambda: self.open_backstage("new")), ("Print", lambda: self.open_backstage("print")),
                         ("Create PDF", self.export_pdf), ("Save as Picture", self.export_image),
                         ("Page Setup", self.page_setup_dialog), ("Check for Updates", self.check_for_updates),
                         ("Insert Page", self.add_page), ("Delete Page", self.delete_page),
                         ("Undo", self.undo), ("Redo", self.redo), ("Bold", lambda: self.toggle_char("bold")),
                         ("Italic", lambda: self.toggle_char("italic")), ("Underline", lambda: self.toggle_char("underline")),
                         ("Collapse the Ribbon", self.ribbon.toggle_collapsed), ("About PubDesign", self.about)]:
            cmds.setdefault(name, ("call", fn))
        self._commands = cmds
        from PySide6.QtWidgets import QCompleter
        comp = QCompleter(sorted(cmds), self)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        comp.setMaxVisibleItems(12)
        self.titlebar.search.setCompleter(comp)
        comp.activated.connect(self._run_command)
        self.titlebar.search.returnPressed.connect(lambda: self._run_command(self.titlebar.search.text()))

    def _run_command(self, name):
        key = next((k for k in self._commands if k.lower() == name.strip().lower()), None)
        if key is None:
            matches = [k for k in self._commands if name.strip().lower() in k.lower()]
            key = matches[0] if matches else None
        QTimer.singleShot(0, self.titlebar.search.clear)
        if key is None:
            self.statusBar().showMessage(f"No command named '{name}'.", 4000)
            return
        cmd = self._commands[key]
        self.view.setFocus()
        if cmd[0] == "call":
            cmd[1]()
            return
        _, ti, b = cmd
        if self.ribbon.tabs.isTabVisible(ti):
            self.ribbon.tabs.setCurrentIndex(ti)
        if b.menu() is not None and b.popupMode() == QToolButton.InstantPopup:
            QTimer.singleShot(0, b.showMenu)
        else:
            QTimer.singleShot(0, b.click)

    # ================= pages =================
    def refresh_pages(self):
        self.pages_list.blockSignals(True)
        self.pages_list.clear()
        for i, p in enumerate(self.doc.pages):
            img = page_image(p, self.doc, 110)
            li = QListWidgetItem(_thumb_icon(img), str(i + 1))
            li.setTextAlignment(Qt.AlignHCenter)
            self.pages_list.addItem(li)
        self.pages_list.setCurrentRow(self.page_index)
        self.pages_list.blockSignals(False)
        self.page_label.setText(f"Page: {self.page_index + 1} of {len(self.doc.pages)}")

    def refresh_current_thumb(self):
        if self.pages_list.count() != len(self.doc.pages):
            self.refresh_pages()
            return
        img = page_image(self.doc.pages[self.page_index], self.doc, 110)
        self.pages_list.item(self.page_index).setIcon(_thumb_icon(img))

    def _page_clicked(self, row):
        if row < 0 or row == self.page_index:
            return
        self.checkpoint()
        self.show_page(row)

    def _page_op(self, fn):
        self.checkpoint()
        fn()
        self.checkpoint()
        self.refresh_pages()

    def add_page(self):
        def f():
            self.doc.pages.insert(self.page_index + 1, Page())
            self.show_page(self.page_index + 1)
        self._page_op(f)

    def duplicate_page(self):
        def f():
            self.doc.pages.insert(self.page_index + 1, copy.deepcopy(self.doc.pages[self.page_index]))
            self.show_page(self.page_index + 1)
        self._page_op(f)

    def delete_page(self):
        if len(self.doc.pages) == 1:
            QMessageBox.information(self, APP, "A publication needs at least one page.")
            return
        self.sync_from_scene()
        if self.doc.pages[self.page_index].items and \
                QMessageBox.question(self, APP, "Delete this page and everything on it?") != QMessageBox.Yes:
            return

        def f():
            del self.doc.pages[self.page_index]
            self.show_page(min(self.page_index, len(self.doc.pages) - 1))
        self._page_op(f)

    def move_page(self, d):
        j = self.page_index + d
        if not (0 <= j < len(self.doc.pages)):
            return

        def f():
            p = self.doc.pages
            p[self.page_index], p[j] = p[j], p[self.page_index]
            self.show_page(j)
        self._page_op(f)

    def resize_doc(self, w, h, scale=True, unit=None, margin=None):
        self.checkpoint()
        if scale:
            s = min(w / self.doc.width, h / self.doc.height)
            ox, oy = (w - self.doc.width * s) / 2, (h - self.doc.height * s) / 2
            for p in self.doc.pages:
                for it in p.items:
                    it.x, it.y = it.x * s + ox, it.y * s + oy
                    it.w, it.h = it.w * s, it.h * s
                    it.stroke_width = max(it.stroke_width * s, 0.25)
                    for pa in it.paras:
                        for r in pa.runs:
                            r.size = max(round(r.size * s, 1), 1)
        self.doc.width, self.doc.height = w, h
        if unit:
            self.doc.unit = unit
        if margin is not None:
            self.doc.margin = margin
        self.show_page(self.page_index)
        self.checkpoint()
        self.refresh_pages()
        self.whole_page()

    def set_page_size(self, w, h, unit):
        self.resize_doc(w, h, True, unit)

    def set_orientation(self, o):
        w, h = self.doc.width, self.doc.height
        if (o == "landscape") == (w > h):
            return
        self.checkpoint()
        self.doc.width, self.doc.height = h, w
        self.show_page(self.page_index)
        self.checkpoint()
        self.refresh_pages()
        self.whole_page()

    def set_margins(self, m):
        self.checkpoint()
        self.doc.margin = m
        self.show_page(self.page_index)
        self.dirty = True
        self.update_title()

    def page_setup_dialog(self):
        dlg = PageSetupDialog(self.doc, self)
        if dlg.exec() == QDialog.Accepted:
            w, h, m, unit, scale = dlg.values()
            self.resize_doc(w, h, scale, unit, m)

    def set_background(self, c):
        """Page background is a full-page rectangle at the very back (it survives in .pub files)."""
        shapes = self.scene.shapes()
        bg = None
        if shapes:
            s = shapes[0]
            if s.kind == "rect" and s.stroke is None and abs(s.pos().x()) < 1 and abs(s.pos().y()) < 1 \
                    and abs(s.w - self.doc.width) < 1 and abs(s.h - self.doc.height) < 1 and s.rotation() == 0:
                bg = s
        if c is None:
            if bg is not None:
                self.scene.removeItem(bg)
                bg.deleteLater()
        elif bg is not None:
            bg.fill = c
            bg.update()
        else:
            for s in shapes:
                s.setZValue(s.zValue() + 1)
            self._add_shape(self.scene, Item(kind="rect", x=0, y=0, w=self.doc.width, h=self.doc.height, fill=c), 0)
        self.checkpoint()

    # ================= tools =================
    def set_tool(self, t):
        if self.editing_shape() and t != "select":
            self.editing_shape().end_edit()
        self.tool = t
        self.view.setDragMode(QGraphicsView.RubberBandDrag if t == "select" else QGraphicsView.NoDrag)
        self.view.refresh_cursor()
        if t != "select":
            self.statusBar().showMessage("Click and drag on the page to draw. Hold Shift for even proportions.", 6000)

    def pick_shape_tool(self, spt):
        if spt == 20:
            self.set_tool("line")
        else:
            self.tool_spt = spt
            self.set_tool("shape")

    def default_run(self):
        return Run("", font=self.settings.value("font", "Calibri"), size=float(self.settings.value("size", 14) or 14))

    def create_from_drag(self, a, b):
        t = self.tool
        r = QRectF(a, b).normalized()
        small = r.width() < 4 and r.height() < 4
        if t == "line":
            if small:
                b = QPointF(a.x() + 144, a.y())
            it = Item(kind="line", x=a.x(), y=a.y(), w=b.x() - a.x(), h=b.y() - a.y(), stroke=(0, 0, 0),
                      stroke_width=0.75)
        else:
            if small:
                r = QRectF(a.x(), a.y(), 216 if t == "text" else 108, 72 if t == "text" else 108)
            if t == "text":
                it = Item(kind="text", x=r.x(), y=r.y(), w=r.width(), h=r.height(), paras=[Para([self.default_run()])])
            else:
                spt = self.tool_spt
                kind = {1: "rect", 3: "ellipse"}.get(spt, "auto")
                it = Item(kind=kind, x=r.x(), y=r.y(), w=r.width(), h=r.height(), fill=(68, 114, 196),
                          stroke=(47, 82, 143), stroke_width=1)
                it.spt = spt if kind == "auto" else 0
        si = self._add_shape(self.scene, it, self._top_z() + 1)
        self.set_tool("select")
        self.scene.clearSelection()
        si.setSelected(True)
        self.checkpoint()
        if t == "text":
            si.begin_edit()

    def _top_z(self):
        s = self.scene.shapes()
        return s[-1].zValue() if s else 0

    def insert_picture(self):
        path, _ = QFileDialog.getOpenFileName(self, "Insert Picture", self.settings.value("picdir", ""),
                                              "Pictures (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff)")
        if not path:
            return
        self.settings.setValue("picdir", os.path.dirname(path))
        with open(path, "rb") as f:
            self.insert_picture_data(f.read(), os.path.basename(path))

    def _norm_picture(self, data, name):
        img = QImage.fromData(data)
        if img.isNull():
            QMessageBox.warning(self, APP, "That picture could not be read.")
            return None, None, None
        if not (data[:8] == b"\x89PNG\r\n\x1a\n" or data[:2] == b"\xff\xd8"):
            data = image_bytes(img)
            name = os.path.splitext(name)[0] + ".png"
        return data, name, img

    def insert_picture_data(self, data, name, at=None):
        data, name, img = self._norm_picture(data, name)
        if data is None:
            return
        W, H = self.doc.width, self.doc.height
        w, h = img.width() * 0.75, img.height() * 0.75
        s = min(1.0, W * 0.6 / w, H * 0.6 / h)
        w, h = w * s, h * s
        x, y = ((W - w) / 2, (H - h) / 2) if at is None else (at.x() - w / 2, at.y() - h / 2)
        si = self._add_shape(self.scene, Item(kind="image", x=x, y=y, w=w, h=h, image=data, image_name=name),
                             self._top_z() + 1)
        self.scene.clearSelection()
        si.setSelected(True)
        self.checkpoint()

    def change_picture(self):
        sel = [s for s in self.selected() if s.kind == "image"]
        if not sel:
            return
        path, _ = QFileDialog.getOpenFileName(self, "Change Picture", self.settings.value("picdir", ""),
                                              "Pictures (*.png *.jpg *.jpeg *.gif *.bmp *.webp *.tif *.tiff)")
        if not path:
            return
        with open(path, "rb") as f:
            data, name, img = self._norm_picture(f.read(), os.path.basename(path))
        if data is None:
            return
        s = sel[0]
        s.image, s.image_name = data, name
        s.pixmap = QPixmap.fromImage(img)
        s.set_geometry(s.pos().x(), s.pos().y(), s.w, s.w * img.height() / max(img.width(), 1))
        self.checkpoint()

    def reset_picture_size(self):
        for s in self.selected():
            if s.kind == "image" and s.pixmap:
                s.set_geometry(s.pos().x(), s.pos().y(), s.pixmap.width() * 0.75, s.pixmap.height() * 0.75)
        self.checkpoint()

    def change_shape(self, spt):
        if spt == 20:
            return
        for s in self.selected():
            if s.kind in ("rect", "ellipse", "auto"):
                s.kind = {1: "rect", 3: "ellipse"}.get(spt, "auto")
                s.spt = 0 if s.kind != "auto" else spt
                s.update()
        self.checkpoint()

    # ================= format painter =================
    def start_painter(self):
        sel = self.selected()
        if not sel:
            self.painter_btn.setChecked(False)
            self.statusBar().showMessage("Select an object first, then click Format Painter.", 5000)
            return
        s = sel[0]
        cf, bf = self.current_char_format()
        self.painter_fmt = dict(fill=s.fill, stroke=s.stroke, stroke_width=s.stroke_width,
                                char=QTextCharFormat(cf) if cf is not None else None,
                                align=qt_to_align(bf.alignment()) if bf is not None else None)
        self.painter_btn.setChecked(True)
        self.view.refresh_cursor()
        self.statusBar().showMessage("Click the object to apply the formatting to. Esc cancels.", 8000)

    def cancel_painter(self):
        self.painter_fmt = None
        self.painter_btn.setChecked(False)
        self.view.refresh_cursor()

    def apply_painter(self, target):
        f = self.painter_fmt
        if target.kind != "line":
            target.fill = f["fill"]
        if f["stroke"] is not None or target.kind != "line":
            target.stroke = f["stroke"]
        target.stroke_width = f["stroke_width"]
        if target.kind == "text" and f["char"] is not None:
            cur = QTextCursor(target.text.document())
            cur.select(QTextCursor.Document)
            cur.mergeCharFormat(f["char"])
            if f["align"]:
                bf = QTextBlockFormat()
                bf.setAlignment(ALIGN_TO_QT[f["align"]])
                cur.mergeBlockFormat(bf)
        target.prepareGeometryChange()
        target.relayout_text()
        target.update()
        self.cancel_painter()
        self.scene.clearSelection()
        target.setSelected(True)
        self.checkpoint()

    # ================= selection & toolbar sync =================
    def selected(self):
        try:
            if self.scene is None:
                return []
            return [i for i in self.scene.selectedItems() if isinstance(i, ShapeItem)]
        except RuntimeError:
            return []

    def editing_shape(self):
        try:
            if self.scene is not None:
                for s in self.scene.shapes():
                    if s.is_editing():
                        return s
        except RuntimeError:
            pass
        return None

    def selection_changed(self):
        sel = self.selected()
        kinds = {s.kind for s in sel}
        ctx = []
        if kinds & {"rect", "ellipse", "auto", "line", "path"}:
            ctx.append("Shape Format")
        if "text" in kinds:
            ctx.append("Text Box")
        if "image" in kinds:
            ctx.append("Picture Format")
        self.ribbon.set_contextual(ctx)
        self._suspend = True
        uf = unit_factor(self.doc.unit)
        if len(sel) == 1:
            s = sel[0]
            r = s.mapRectToScene(s.local_rect())
            self.pos_label.setText(f"Position: {s.pos().x() / uf:.2f}, {s.pos().y() / uf:.2f} {self.doc.unit}")
            self.objsize_label.setText(f"Size: {abs(s.w) / uf:.2f} × {abs(s.h) / uf:.2f} {self.doc.unit}")
            for hs, ws in (self.size_fields_shape, self.size_fields_text, self.size_fields_pic):
                hs.setSuffix(f" {self.doc.unit}")
                ws.setSuffix(f" {self.doc.unit}")
                hs.setValue(abs(s.h) / uf)
                ws.setValue(abs(s.w) / uf)
            self.hruler.highlight = (r.left(), r.right())
            self.vruler.highlight = (r.top(), r.bottom())
        else:
            self.objsize_label.setText(f"{len(sel)} objects selected" if sel else "")
            self.hruler.highlight = self.vruler.highlight = None
        self._suspend = False
        self.update_rulers()
        self.sync_toolbar()

    def _size_edited(self):
        if self._suspend:
            return
        sel = self.selected()
        if len(sel) != 1:
            return
        sp = self.sender()
        uf = unit_factor(self.doc.unit)
        s = sel[0]
        for hs, ws in (self.size_fields_shape, self.size_fields_text, self.size_fields_pic):
            if sp is hs:
                s.set_geometry(s.pos().x(), s.pos().y(), s.w, hs.value() * uf * (1 if s.h >= 0 else -1))
            elif sp is ws:
                s.set_geometry(s.pos().x(), s.pos().y(), ws.value() * uf * (1 if s.w >= 0 else -1), s.h)
        self.checkpoint()

    def current_char_format(self):
        ed = self.editing_shape()
        if ed:
            return ed.text.textCursor().charFormat(), ed.text.textCursor().blockFormat()
        for s in self.selected():
            if s.kind == "text":
                cur = QTextCursor(s.text.document())
                cur.movePosition(QTextCursor.NextCharacter)
                return cur.charFormat(), cur.blockFormat()
        return None, None

    def sync_toolbar(self):
        cf, bf = self.current_char_format()
        if cf is not None:
            self.font_box.blockSignals(True)
            self.size_box.blockSignals(True)
            fams = cf.fontFamilies()
            self.font_box.setCurrentFont(QFont(fams[0] if fams else cf.font().family()))
            self.size_box.setEditText(f"{cf.fontPointSize():g}")
            self.font_box.blockSignals(False)
            self.size_box.blockSignals(False)
            self.b_btn.setChecked(cf.fontWeight() >= QFont.DemiBold)
            self.i_btn.setChecked(cf.fontItalic())
            self.u_btn.setChecked(cf.fontUnderline())
            a = qt_to_align(bf.alignment())
            for k, b in self.align_btns.items():
                b.setChecked(k == a)
        sel = self.selected()
        if sel and sel[0].kind == "text":
            for k, b in self.valign_btns.items():
                b.setChecked(k == sel[0].valign)

    # ================= text formatting =================
    def _text_targets(self):
        ed = self.editing_shape()
        if ed:
            return [(ed, ed.text.textCursor(), True)]
        out = []
        for s in self.selected():
            if s.kind == "text":
                cur = QTextCursor(s.text.document())
                cur.select(QTextCursor.Document)
                out.append((s, cur, False))
        return out

    def apply_char(self, **kw):
        targets = self._text_targets()
        if not targets:
            if "font" in kw:
                self.settings.setValue("font", kw["font"])
            if "size" in kw:
                self.settings.setValue("size", kw["size"])
            return
        for s, cur, live in targets:
            cf = QTextCharFormat()
            if "font" in kw:
                cf.setFontFamilies([kw["font"]])
            if "size" in kw:
                cf.setFontPointSize(kw["size"])
            if "bold" in kw:
                cf.setFontWeight(QFont.Bold if kw["bold"] else QFont.Normal)
            if "italic" in kw:
                cf.setFontItalic(kw["italic"])
            if "underline" in kw:
                cf.setFontUnderline(kw["underline"])
            if "color" in kw:
                cf.setForeground(QColor(*kw["color"]))
            cur.mergeCharFormat(cf)
            if live:
                if not cur.hasSelection() and cur.block().length() <= 1:
                    cur.mergeBlockCharFormat(cf)
                s.text.setTextCursor(cur)
            s.relayout_text()
        if not any(live for _, _, live in targets):
            self.checkpoint()
        self.sync_toolbar()

    def toggle_char(self, what):
        cf, _ = self.current_char_format()
        if cf is None:
            return
        cur = {"bold": cf.fontWeight() >= QFont.DemiBold, "italic": cf.fontItalic(),
               "underline": cf.fontUnderline()}[what]
        self.apply_char(**{what: not cur})

    def _size_entered(self):
        try:
            v = float(self.size_box.currentText().replace(",", "."))
        except ValueError:
            return
        if 1 <= v <= 1600:
            self.apply_char(size=v)

    def bump_size(self, d):
        cf, _ = self.current_char_format()
        if cf is None:
            return
        steps = [6, 7, 8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40, 48, 54, 60, 72, 96, 120, 144, 200]
        cur = cf.fontPointSize() or 12
        nxt = next((s for s in steps if s > cur + 0.01), cur + 10) if d > 0 else \
            next((s for s in reversed(steps) if s < cur - 0.01), max(cur - 1, 1))
        self.apply_char(size=nxt)

    def apply_align(self, a):
        for s, cur, live in self._text_targets():
            bf = QTextBlockFormat()
            bf.setAlignment(ALIGN_TO_QT[a])
            cur.mergeBlockFormat(bf)
            s.relayout_text()
        if not self.editing_shape():
            self.checkpoint()
        self.sync_toolbar()

    def toggle_bullets(self):
        for s, cur, live in self._text_targets():
            doc = s.text.document()
            if live:
                start, end = (cur.selectionStart(), cur.selectionEnd()) if cur.hasSelection() else (cur.position(),) * 2
            else:
                start, end = 0, doc.characterCount()
            blocks = []
            b = doc.findBlock(start)
            while b.isValid() and b.position() <= end:
                blocks.append(b)
                b = b.next()
            all_bulleted = all(bl.text().startswith("• ") for bl in blocks)
            ec = QTextCursor(doc)
            ec.beginEditBlock()
            for bl in blocks:
                ec.setPosition(bl.position())
                if all_bulleted:
                    ec.movePosition(QTextCursor.NextCharacter, QTextCursor.KeepAnchor, 2)
                    ec.removeSelectedText()
                else:
                    ec.insertText("• ")
            ec.endEditBlock()
            s.relayout_text()
        if not self.editing_shape():
            self.checkpoint()

    # ================= shape formatting =================
    def apply_shape(self, **kw):
        sel = self.selected()
        if not sel:
            return
        for s in sel:
            for k, v in kw.items():
                if (k == "valign" and s.kind != "text") or (k == "fill" and s.kind == "line"):
                    continue
                setattr(s, k, v)
            if s.kind == "line" and s.stroke is None:
                s.stroke = (0, 0, 0)
            s.prepareGeometryChange()
            s.relayout_text()
            s.update()
        self.checkpoint()
        self.sync_toolbar()

    def restack(self, how):
        sel = self.selected()
        if not sel:
            return
        shapes = self.scene.shapes()
        selset = set(sel)
        if how == "front":
            order = [s for s in shapes if s not in selset] + [s for s in shapes if s in selset]
        elif how == "back":
            order = [s for s in shapes if s in selset] + [s for s in shapes if s not in selset]
        else:
            order = list(shapes)
            idxs = [i for i, s in enumerate(order) if s in selset]
            if how == "up":
                for i in reversed(idxs):
                    if i + 1 < len(order) and order[i + 1] not in selset:
                        order[i], order[i + 1] = order[i + 1], order[i]
            else:
                for i in idxs:
                    if i - 1 >= 0 and order[i - 1] not in selset:
                        order[i], order[i - 1] = order[i - 1], order[i]
        for z, s in enumerate(order):
            s.setZValue(z)
        self.checkpoint()

    def align(self, how):
        sel = self.selected()
        if not sel:
            return
        rects = {s: s.mapRectToScene(s.local_rect()) for s in sel}
        if how == "page" or len(sel) == 1:
            ref = QRectF(0, 0, self.doc.width, self.doc.height)
        else:
            ref = rects[sel[0]]
            for r in rects.values():
                ref = ref.united(r)
        for s, r in rects.items():
            dx = dy = 0
            if how == "l":
                dx = ref.left() - r.left()
            elif how in ("c", "page"):
                dx = ref.center().x() - r.center().x()
            elif how == "r":
                dx = ref.right() - r.right()
            if how == "t":
                dy = ref.top() - r.top()
            elif how in ("m", "page"):
                dy = ref.center().y() - r.center().y()
            elif how == "b":
                dy = ref.bottom() - r.bottom()
            s.moveBy(dx, dy)
        self.checkpoint()

    def rotate_by(self, deg):
        for s in self.selected():
            s.setRotation(0 if deg is None else (s.rotation() + deg) % 360)
        self.checkpoint()

    def flip(self, axis):
        for s in self.selected():
            if s.kind == "line":
                if axis == "h":
                    s.set_geometry(s.pos().x() + s.w, s.pos().y(), -s.w, s.h)
                else:
                    s.set_geometry(s.pos().x(), s.pos().y() + s.h, s.w, -s.h)
            elif s.kind in ("rect", "ellipse", "auto", "image"):
                s.setRotation((180 - s.rotation()) % 360 if axis == "v" else (-s.rotation()) % 360)
        self.checkpoint()

    def format_object_dialog(self):
        sel = self.selected()
        if len(sel) != 1:
            return
        s = sel[0]
        dlg = FormatDialog(s, self.doc.unit, self)
        if dlg.exec() == QDialog.Accepted:
            v = dlg.values()
            s.set_geometry(v["x"], v["y"], v["w"], v["h"])
            s.setRotation(v["rot"])
            s.stroke_width = v["lw"]
            s.update()
            self.checkpoint()

    # ================= clipboard =================
    def _items_json(self, shapes):
        tmp = Document(width=self.doc.width, height=self.doc.height, pages=[Page(items=[s.to_model() for s in shapes])])
        return self.snap.snap(tmp)

    def copy(self):
        ed = self.editing_shape()
        if ed:
            cur = ed.text.textCursor()
            if cur.hasSelection():
                QGuiApplication.clipboard().setText(cur.selectedText().replace(" ", "\n").replace(" ", "\n"))
            return
        sel = sorted(self.selected(), key=lambda s: s.zValue())
        if not sel:
            return
        self.clip = self._items_json(sel)
        md = QMimeData()
        md.setData("application/x-pubdesign-items", self.clip.encode())
        txt = "\n\n".join("\n".join(p.text for p in s.to_model().paras) for s in sel if s.kind == "text")
        if txt:
            md.setText(txt)
        QGuiApplication.clipboard().setMimeData(md)

    def cut(self):
        ed = self.editing_shape()
        if ed:
            cur = ed.text.textCursor()
            if cur.hasSelection():
                QGuiApplication.clipboard().setText(cur.selectedText().replace(" ", "\n"))
                cur.removeSelectedText()
            return
        self.copy()
        self.delete_selected()

    def paste(self):
        ed = self.editing_shape()
        md = QGuiApplication.clipboard().mimeData()
        if ed:
            if md.hasText():
                ed.text.textCursor().insertText(md.text())
            return
        data = None
        if md.hasFormat("application/x-pubdesign-items"):
            data = bytes(md.data("application/x-pubdesign-items")).decode()
        elif self.clip and not md.hasImage() and not md.hasText():
            data = self.clip
        if data:
            tmp = self.snap.restore(data)
            self.scene.clearSelection()
            for it in tmp.pages[0].items:
                it.x += 12
                it.y += 12
                self._add_shape(self.scene, it, self._top_z() + 1).setSelected(True)
            self.checkpoint()
            return
        if md.hasImage():
            img = QImage(md.imageData())
            if not img.isNull():
                self.insert_picture_data(image_bytes(img), "pasted.png")
                return
        if md.hasText() and md.text().strip():
            run = self.default_run()
            paras = [Para([Run(line, run.font, run.size)]) for line in md.text().splitlines()]
            it = Item(kind="text", x=72, y=72, w=min(self.doc.width - 144, 360), h=max(40, 20 * len(paras)), paras=paras)
            si = self._add_shape(self.scene, it, self._top_z() + 1)
            self.scene.clearSelection()
            si.setSelected(True)
            self.checkpoint()

    def duplicate(self):
        sel = sorted(self.selected(), key=lambda s: s.zValue())
        if not sel:
            return
        tmp = self.snap.restore(self._items_json(sel))
        self.scene.clearSelection()
        for it in tmp.pages[0].items:
            it.x += 12
            it.y += 12
            self._add_shape(self.scene, it, self._top_z() + 1).setSelected(True)
        self.checkpoint()

    def delete_selected(self):
        ed = self.editing_shape()
        if ed:
            cur = ed.text.textCursor()
            if cur.hasSelection():
                cur.removeSelectedText()
            else:
                cur.deleteChar()
            return
        sel = self.selected()
        if not sel:
            return
        for s in sel:
            self.scene.removeItem(s)
            s.deleteLater()
        self.checkpoint()

    def select_all(self):
        ed = self.editing_shape()
        if ed:
            cur = ed.text.textCursor()
            cur.select(QTextCursor.Document)
            ed.text.setTextCursor(cur)
            return
        for s in self.scene.shapes():
            s.setSelected(True)

    def keyPressEvent(self, ev):
        if self.painter_fmt is not None and ev.key() == Qt.Key_Escape:
            self.cancel_painter()
            return
        if self.stack.currentIndex() == 1 and ev.key() == Qt.Key_Escape:
            self.close_backstage()
            return
        if not self.editing_shape() and self.selected() and \
                ev.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 10 if ev.modifiers() & Qt.ShiftModifier else 1
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(ev.key(), 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(ev.key(), 0)
            for s in self.selected():
                s.moveBy(dx, dy)
            QTimer.singleShot(400, self.checkpoint)
            return
        if ev.key() == Qt.Key_Escape:
            self.scene.clearSelection()
            self.set_tool("select")
            return
        if ev.key() in (Qt.Key_PageDown, Qt.Key_PageUp) and not self.editing_shape():
            j = self.page_index + (1 if ev.key() == Qt.Key_PageDown else -1)
            if 0 <= j < len(self.doc.pages):
                self.checkpoint()
                self.show_page(j)
                self.pages_list.setCurrentRow(j)
            return
        super().keyPressEvent(ev)

    # ================= view =================
    def zoom_factor_display(self):
        return self.view.transform().m11() * 72 / QApplication.primaryScreen().logicalDotsPerInch()

    def zoom_smooth(self, z):
        """Glide to a zoom level (Office-style) instead of jumping."""
        z = max(0.03, min(z, 16))
        cur = self.view.transform().m11()
        if not anim.enabled_for(self.view) or abs(z - cur) < 1e-4:
            self.set_zoom(z)
            return
        a = getattr(self, "_zoom_anim", None)
        if a is not None:
            a.stop()
        from PySide6.QtCore import QVariantAnimation, QEasingCurve
        a = QVariantAnimation(self)
        a.setStartValue(float(cur))
        a.setEndValue(float(z))
        a.setDuration(140)
        a.setEasingCurve(QEasingCurve.OutCubic)
        a.valueChanged.connect(lambda v: self.set_zoom(float(v)))
        self._zoom_anim = a
        self._zoom_target = z
        a.start()

    def zoom_target(self):
        a = getattr(self, "_zoom_anim", None)
        if a is not None and a.state() == a.State.Running:
            return self._zoom_target
        return self.view.transform().m11()

    def set_zoom(self, z):
        z = max(0.03, min(z, 16))
        self.view.setTransform(self.view.transform().fromScale(z, z))
        pct = round(self.zoom_factor_display() * 100)
        self.zoom_pct.setText(f"{pct}%")
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(max(10, min(400, pct)))
        self.zoom_slider.blockSignals(False)
        if self.scene is not None:
            for s in self.scene.shapes():
                s.prepareGeometryChange()
        self.update_rulers()

    def _slider_zoom(self, v):
        self.set_zoom(v / 100 * QApplication.primaryScreen().logicalDotsPerInch() / 72)

    def zoom_100(self):
        self.zoom_smooth(QApplication.primaryScreen().logicalDotsPerInch() / 72)

    def whole_page(self):
        vp = self.view.viewport().rect()
        if vp.width() < 50:
            return
        self.set_zoom(min((vp.width() - 40) / self.doc.width, (vp.height() - 40) / self.doc.height))
        self.view.centerOn(self.doc.width / 2, self.doc.height / 2)

    def page_width(self):
        vp = self.view.viewport().rect()
        self.set_zoom((vp.width() - 40) / self.doc.width)
        self.view.centerOn(self.doc.width / 2, self.view.mapToScene(vp.center()).y())

    def toggle_guides(self, on):
        self.show_guides = on
        if self.scene:
            self.scene.show_guides = on
            self.scene.update()

    def toggle_boundaries(self, on):
        self.show_boundaries = on
        if self.scene:
            self.scene.show_boundaries = on
            self.scene.update()

    def toggle_rulers(self, on):
        self.hruler.setVisible(on)
        self.vruler.setVisible(on)

    def update_rulers(self):
        if hasattr(self, "hruler"):
            self.hruler.update()
            self.vruler.update()

    def show_cursor_pos(self, sp):
        self.hruler.cursor_pos = sp.x()
        self.vruler.cursor_pos = sp.y()
        self.update_rulers()
        if not self.selected():
            uf = unit_factor(self.doc.unit)
            self.pos_label.setText(f"Position: {sp.x() / uf:.2f}, {sp.y() / uf:.2f} {self.doc.unit}")

    # ================= backstage =================
    def open_backstage(self, page="home"):
        if not isinstance(page, str):
            page = "home"
        self.checkpoint()
        if self.stack.currentIndex() == 1:
            self.backstage.show_page(page)
            return

        def change():
            self.stack.setCurrentIndex(1)
            self.backstage.show_page(page, animate=False)
        # File menu slides in from the left, like Office
        anim.transition(self.stack, change, dx=-90, duration=anim.NORMAL)

    def close_backstage(self):
        if self.stack.currentIndex() == 0:
            return
        anim.transition(self.stack, lambda: self.stack.setCurrentIndex(0), dx=60, duration=anim.FAST)

    # ================= files =================
    def recent_files(self):
        r = self.settings.value("recent", [])
        if isinstance(r, str):
            r = [r]
        return [p for p in (r or []) if os.path.exists(p)]

    def add_recent(self, path):
        r = [p for p in self.recent_files() if os.path.normcase(p) != os.path.normcase(path)]
        self.settings.setValue("recent", ([path] + r)[:12])

    def maybe_save(self):
        if not self.dirty:
            return True
        name = os.path.basename(self.path) if self.path else "Publication1"
        r = QMessageBox.question(self, APP, f"Do you want to save changes to {name}?",
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if r == QMessageBox.Save:
            return self.save()
        return r == QMessageBox.Discard

    def open_doc(self, skip_check=False):
        if not skip_check and not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Publication", self.settings.value("dir", ""), OPEN_FILTER)
        if path:
            self.open_path(path, checked=True)

    def open_pictures(self):
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open Publisher File as Pictures", self.settings.value("dir", ""),
                                              "Publisher Files (*.pub)")
        if path:
            self.open_path(path, checked=True, mode="pictures")

    def _run_busy(self, fn, text):
        """Run fn in a background thread while a progress window keeps PubDesign responsive
        (so Windows doesn't flag it as 'Not Responding'). Re-raises fn's exception."""
        import threading
        from PySide6.QtCore import QEventLoop
        box = {}

        def work():
            try:
                box["result"] = fn()
            except BaseException as e:  # noqa: B036 - handed back to the UI thread
                box["error"] = e
        t = threading.Thread(target=work, daemon=True)
        prog = QProgressDialog(text, None, 0, 0, self)
        prog.setWindowTitle(APP)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(300)
        prog.setCancelButton(None)
        t.start()
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(lambda: (not t.is_alive()) and loop.quit())
        timer.start(50)
        if t.is_alive():
            loop.exec()
        timer.stop()
        prog.close()
        if "error" in box:
            raise box["error"]
        return box.get("result")

    def _read_pub(self, path, mode):
        """PubDesign-made .pub -> native reader; Publisher-made -> bundled Publisher reader (LibreOffice if
        that fails and it is installed; PubDesign's native reader as a last resort)."""
        if mode == "pictures":
            return import_pub(path, mode="pictures"), None
        if is_own_file(path):
            return read_pub(path), None
        if can_import():
            try:
                return import_pub(path), "Opened a file made in Microsoft Publisher."
            except ImportError_:
                pass
        try:
            return read_pub(path), ("This Publisher file was read with PubDesign's simple reader. Tables, grouped "
                                    "objects and WordArt may be missing.")
        except Exception:
            raise ImportError_("PubDesign couldn't read this Publisher file. It may be damaged or made in a very "
                               "old version of Publisher (97 or earlier).")

    def open_path(self, path, checked=False, mode="editable"):
        if not checked and not self.maybe_save():
            return
        self.settings.setValue("dir", os.path.dirname(path))
        ext = os.path.splitext(path)[1].lower()
        try:
            if ext == ".pub":
                msg = "Opening…" if is_own_file(path) else \
                    "Opening a Microsoft Publisher file…"
                doc, note = self._run_busy(lambda: self._read_pub(path, mode), msg)
                self.close_backstage()
                self.load_document(doc, path if mode != "pictures" else None)
                if note:
                    self.statusBar().showMessage(note, 15000)
            else:
                doc = docio.load_backup(path)
                self.close_backstage()
                self.load_document(doc, path)
        except ImportError_ as e:
            self._lo_missing(str(e))
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, APP, f"Could not open the file:\n{e}")

    def _lo_missing(self, msg):
        box = QMessageBox(self)
        box.setWindowTitle(APP)
        box.setIcon(QMessageBox.Warning)
        box.setText(msg)
        if "LibreOffice" not in msg:
            box.addButton(QMessageBox.Ok)
            box.exec()
            return
        inst = box.addButton("Install LibreOffice for me", QMessageBox.ActionRole) if os.name == "nt" else None
        dl = box.addButton("Open download page", QMessageBox.ActionRole)
        box.addButton(QMessageBox.Close)
        box.exec()
        if inst is not None and box.clickedButton() == inst:
            import subprocess
            subprocess.Popen(["cmd.exe", "/c", "title Installing LibreOffice & winget install -e --id "
                              "TheDocumentFoundation.LibreOffice --accept-source-agreements "
                              "--accept-package-agreements & echo. & echo Done - you can close this window "
                              "and open the file again in PubDesign. & pause"],
                             creationflags=0x00000010)  # new console window
        elif box.clickedButton() == dl:
            QDesktopServices.openUrl(QUrl("https://www.libreoffice.org/download/download-libreoffice/"))

    def save(self):
        if self.path and self.path.lower().endswith(".pub") and os.path.exists(self.path) \
                and not is_own_file(self.path):
            r = QMessageBox.question(
                self, APP, f"{os.path.basename(self.path)} was made in Microsoft Publisher.\n\n"
                           "Saving replaces it with PubDesign's version. Anything PubDesign doesn't support "
                           "(such as tables or WordArt) was converted when the file was opened.\n\n"
                           "Replace the original? Choose No to save a copy instead.",
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                return False
            if r == QMessageBox.No:
                return self.save_as("pub")
        if self.path and self.path.lower().endswith((".pubdesign", ".pagecraft")):
            return self._write_backup(self.path if self.path.lower().endswith(".pubdesign")
                                      else os.path.splitext(self.path)[0] + ".pubdesign")
        if self.path and self.path.lower().endswith(".pub"):
            return self._write_pub(self.path)
        return self.save_as("pub")

    def save_as(self, fmt=None):
        self.checkpoint()
        self.close_backstage()
        base = os.path.splitext(self.path)[0] if self.path else \
            os.path.join(self.settings.value("dir", "") or os.path.expanduser("~/Documents"), "Publication1")
        ext = "pubdesign" if fmt == "pubdesign" else "pub"
        filt = SAVE_FILTER if ext == "pub" else "PubDesign backup (*.pubdesign);;Publisher Files (*.pub)"
        path, chosen = QFileDialog.getSaveFileName(self, "Save As", f"{base}.{ext}", filt)
        if not path:
            return False
        self.settings.setValue("dir", os.path.dirname(path))
        if not path.lower().endswith((".pub", ".pubdesign")):
            path += ".pubdesign" if chosen.lower().startswith("pubdesign") else ".pub"
        if path.lower().endswith(".pubdesign"):
            return self._write_backup(path)
        return self._write_pub(path)

    def _write_backup(self, path):
        self.checkpoint()
        try:
            docio.save_backup(self.doc, path)
        except Exception as e:
            QMessageBox.critical(self, APP, f"Could not save:\n{e}")
            return False
        self._saved(path)
        return True

    def pub_ready_doc(self):
        d = copy.deepcopy(self.doc)
        for p in d.pages:
            new = []
            for it in p.items:
                if it.kind == "path":
                    png, pad = item_to_png(it)
                    new.append(Item(kind="image", x=it.x - pad, y=it.y - pad, w=it.w + 2 * pad, h=it.h + 2 * pad,
                                    rotation=it.rotation, image=png, image_name="shape.png"))
                    continue
                if it.kind == "image" and not (it.image[:8] == b"\x89PNG\r\n\x1a\n" or it.image[:2] == b"\xff\xd8"):
                    conv = image_to_png(it.image)
                    if conv is None:
                        continue
                    it.image = conv
                new.append(it)
            p.items = new
        return d

    def _write_pub(self, path):
        self.checkpoint()
        try:
            write_pub(self.pub_ready_doc(), path, title=os.path.splitext(os.path.basename(path))[0])
        except Exception as e:
            traceback.print_exc()
            QMessageBox.critical(self, APP, f"Could not save the Publisher file:\n{e}")
            return False
        self._saved(path)
        return True

    def _saved(self, path):
        self.path = path
        self.dirty = False
        self.update_title()
        self.add_recent(path)
        self.statusBar().showMessage(f"Saved {os.path.basename(path)}", 4000)

    def export_pdf(self):
        self.checkpoint()
        self.close_backstage()
        base = os.path.splitext(self.path)[0] if self.path else os.path.join(self.settings.value("dir", ""), "Publication1")
        path, _ = QFileDialog.getSaveFileName(self, "Create PDF", base + ".pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            export_pdf(self.doc, path)
        except Exception as e:
            QMessageBox.critical(self, APP, f"Could not export:\n{e}")
            return
        self.statusBar().showMessage(f"Created {os.path.basename(path)}", 5000)
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def export_image(self):
        self.checkpoint()
        self.close_backstage()
        dlg = QDialog(self)
        dlg.setWindowTitle("Save as Picture")
        f = QFormLayout(dlg)
        fmt = QComboBox()
        fmt.addItems(["PNG", "JPG"])
        f.addRow("Format", fmt)
        res = QSpinBox()
        res.setRange(36, 1200)
        res.setValue(72 if self.doc.unit == "px" else 300)
        res.setSuffix(" dpi")
        f.addRow("Resolution", res)
        info = QLabel()
        f.addRow(info)

        def upd():
            info.setText(f"{round(self.doc.width * res.value() / 72)} × {round(self.doc.height * res.value() / 72)} pixels")
        res.valueChanged.connect(upd)
        upd()
        which = QComboBox()
        which.addItems(["Current page", "All pages"])
        f.addRow("Pages", which)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        f.addRow(bb)
        if dlg.exec() != QDialog.Accepted:
            return
        ext = fmt.currentText().lower()
        base = os.path.splitext(self.path)[0] if self.path else os.path.join(self.settings.value("dir", ""), "Publication1")
        path, _ = QFileDialog.getSaveFileName(self, "Save as Picture", f"{base}.{ext}", f"{fmt.currentText()} (*.{ext})")
        if not path:
            return
        pages = [self.page_index] if which.currentIndex() == 0 else list(range(len(self.doc.pages)))
        stem, e = os.path.splitext(path)
        for i in pages:
            img = page_image(self.doc.pages[i], self.doc, self.doc.width * res.value() / 72)
            dpm = round(res.value() / 0.0254)
            img.setDotsPerMeterX(dpm)
            img.setDotsPerMeterY(dpm)
            if ext == "jpg":
                img = img.convertToFormat(QImage.Format_RGB32)
            img.save(path if len(pages) == 1 else f"{stem}_page{i + 1}{e}", None, 95)
        self.statusBar().showMessage("Picture saved", 5000)

    def print_doc(self):
        self.checkpoint()
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(QSizeF(self.doc.width, self.doc.height), QPageSize.Point, "", QPageSize.ExactMatch))
        printer.setFromTo(1, len(self.doc.pages))
        if QPrintDialog(printer, self).exec() != QDialog.Accepted:
            return
        self.close_backstage()
        print_pages(self.doc, printer)

    def about(self):
        box = QMessageBox(self)
        box.setWindowTitle(f"About {APP}")
        if os.path.exists(asset("logo.png")):
            box.setIconPixmap(QPixmap(asset("logo.png")).scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        box.setText(f"<b>{APP} {VERSION}</b><br>Desktop publishing with Microsoft Publisher (.pub) files.<br><br>"
                    "PubDesign reads and writes .pub files with its own reverse-engineered engine. Files made "
                    "in Microsoft Publisher open with the built-in libmspub reader (MPL 2.0) from the "
                    "LibreOffice project.<br><br>"
                    f"<a href='https://github.com/{updater.REPO}'>github.com/{updater.REPO}</a>")
        box.exec()
        return
        QMessageBox.about(self, f"About {APP}",
                          f"<b>{APP} {VERSION}</b><br>Desktop publishing with Microsoft Publisher (.pub) files.<br><br>"
                          "PubDesign reads and writes .pub files with its own reverse-engineered engine. Files made "
                          "in Microsoft Publisher are opened through free LibreOffice when it is installed.")

    def closeEvent(self, ev):
        if self.maybe_save():
            ev.accept()
            if updater.FROZEN and self._ready_setup and os.path.exists(self._ready_setup):
                # install the downloaded update quietly now that PubDesign is closing
                try:
                    updater.launch_setup(self._ready_setup, relaunch=False)
                except Exception:
                    pass
                self._ready_setup = None
        else:
            ev.ignore()


# ---------------------------------------------------------------------------
def export_pdf(doc, path):
    w = QPdfWriter(path)
    w.setPageSize(QPageSize(QSizeF(doc.width, doc.height), QPageSize.Point, "", QPageSize.ExactMatch))
    w.setPageMargins(QMarginsF(0, 0, 0, 0))
    w.setResolution(72)
    w.setTitle(os.path.splitext(os.path.basename(path))[0])
    w.setCreator(APP)
    p = QPainter(w)
    for i, page in enumerate(doc.pages):
        if i:
            w.newPage()
        render_page(p, page, doc, QRectF(0, 0, doc.width, doc.height))
    p.end()


def print_pages(doc, printer, pages=None, fit=True):
    if pages is None:
        first, last = printer.fromPage() or 1, printer.toPage() or len(doc.pages)
        pages = list(range(first - 1, last))
    p = QPainter()
    if not p.begin(printer):
        return False
    res = printer.resolution()
    paint = printer.pageLayout().paintRectPixels(res)
    full = printer.pageLayout().fullRectPixels(res)
    for n, i in enumerate(pages):
        if n:
            printer.newPage()
        if fit:
            s = min(paint.width() / doc.width, paint.height() / doc.height)
            tw, th = doc.width * s, doc.height * s
            x, y = (paint.width() - tw) / 2, (paint.height() - th) / 2
        else:
            s = res / 72.0
            tw, th = doc.width * s, doc.height * s
            x, y = (full.width() - tw) / 2 - paint.x(), (full.height() - th) / 2 - paint.y()
        render_page(p, doc.pages[i], doc, QRectF(x, y, tw, th))
    p.end()
    return True


def _fmt_size(doc):
    unit = getattr(doc, "unit", "in")
    if unit == "mm":
        return f"{doc.width / 72 * 25.4:.0f} x {doc.height / 72 * 25.4:.0f} mm"
    if unit == "px":
        return f"{doc.width:.0f} x {doc.height:.0f} px"
    return f"{doc.width / 72:g} x {doc.height / 72:g} in"


def selftest():
    """Used by the build server: start the app, write and read a .pub, open a Publisher-made file with the
    bundled reader and draw a WMF picture. Exit 0 on success; details go to %TEMP%\\pubdesign_selftest.txt."""
    import tempfile
    from pubreader import read_pub as _rp
    import pub_import as PI
    app = QApplication(sys.argv)
    report = []
    ok = True
    try:
        w = MainWindow()
        w.new_from(templates.flyer())
        p = os.path.join(tempfile.gettempdir(), "pubdesign_selftest.pub")
        good = w._write_pub(p) and len(_rp(p).pages[0].items) == len(templates.flyer().pages[0].items)
        report.append(f"write/read .pub: {'OK' if good else 'FAILED'}")
        ok &= bool(good)
        w.dirty = False
        tool = PI.find_pubconv()
        report.append(f"pubconv: {tool}")
        if getattr(sys, "frozen", False) and os.name == "nt":
            ok &= tool is not None
            # Publisher-made file through the bundled reader
            fodg_dir = tempfile.mkdtemp()
            import pubwriter
            fodg = PI.pubconv_to_fodg(pubwriter.TEMPLATE, fodg_dir)
            pages = len(PI.FodgReader(fodg).document().pages) if fodg else 0
            report.append(f"Publisher file via pubconv: {pages} page(s) {PI.last_pubconv_error}")
            ok &= pages >= 1
            # WMF clip art through GDI+
            wmf = os.path.join(os.path.dirname(tool), "test.wmf")
            with open(wmf, "rb") as f:
                png = PI.metafile_to_png_native(f.read(), "wmf", 300, 240, fodg_dir)
            img = QImage.fromData(png) if png else QImage()
            clear = drawn = 0
            if not img.isNull():
                for y in range(0, img.height(), 4):
                    for x in range(0, img.width(), 4):
                        a = img.pixelColor(x, y).alpha()
                        clear += a == 0
                        drawn += a > 200
            report.append(f"WMF picture: {img.width()}x{img.height()} transparent={clear} drawn={drawn}")
            ok &= (not img.isNull()) and drawn > 20 and clear > 20
    except Exception:
        report.append(traceback.format_exc())
        ok = False
    report.append(f"SELFTEST {'OK' if ok else 'FAILED'} {VERSION}")
    text = "\n".join(report)
    print(text)
    try:
        with open(os.path.join(tempfile.gettempdir(), "pubdesign_selftest.txt"), "w", encoding="utf-8") as f:
            f.write(text + "\n")
    except OSError:
        pass
    sys.exit(0 if ok else 1)


def log_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "PubDesign")
    os.makedirs(d, exist_ok=True)
    return d


_crash_file = None


def install_crash_logging():
    """Write errors to %LOCALAPPDATA%\\PubDesign\\crash.log and show them instead of closing silently."""
    global _crash_file
    import faulthandler
    import datetime
    try:
        path = os.path.join(log_dir(), "crash.log")
        if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
            os.replace(path, path + ".old")
        _crash_file = open(path, "a", encoding="utf-8", buffering=1)
        _crash_file.write(f"\n=== PubDesign {VERSION} started {datetime.datetime.now():%Y-%m-%d %H:%M:%S} ===\n")
        faulthandler.enable(file=_crash_file, all_threads=True)
        if sys.stderr is None:      # windowed build: send stray output to the log
            sys.stderr = _crash_file
        if sys.stdout is None:
            sys.stdout = _crash_file
    except Exception:
        _crash_file = None

    def hook(etype, value, tb):
        text = "".join(traceback.format_exception(etype, value, tb))
        try:
            if _crash_file:
                _crash_file.write(text)
        except Exception:
            pass
        try:
            QMessageBox.critical(QApplication.activeWindow(), APP,
                                 f"Something went wrong, but PubDesign kept running.\n\n{value}\n\n"
                                 f"Details were saved to {os.path.join(log_dir(), 'crash.log')}")
        except Exception:
            pass
    sys.excepthook = hook
    import threading

    def thread_hook(a):  # background threads: log only (no windows outside the UI thread)
        try:
            if _crash_file:
                _crash_file.write("".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))
        except Exception:
            pass
    threading.excepthook = thread_hook


def main():
    if "--selftest" in sys.argv:
        selftest()
    install_crash_logging()
    if hasattr(Qt, "HighDpiScaleFactorRoundingPolicy"):
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    updater.mark_running()
    app = QApplication(sys.argv)
    app.setApplicationName(APP)
    app.setStyle("Fusion")
    f = app.font()
    f.setFamily("Segoe UI")
    app.setFont(f)
    app.setWindowIcon(app_icon())
    anim.set_enabled(QSettings("PubDesign", "PubDesign").value("animations", True, type=bool))
    anim.enable_menu_effects()
    win = MainWindow()
    anim.fade_in_window(win)
    win.show()
    args = [x for x in sys.argv[1:] if not x.startswith("-")]
    if args and os.path.exists(args[0]):
        win.open_path(args[0], checked=True)
    else:
        win.open_backstage("home")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
