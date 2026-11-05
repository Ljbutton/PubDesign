"""Smooth transitions in the style of Microsoft Office (slide + fade, eased).

Everything here is cosmetic: when animations are turned off (File > Options) or a widget isn't
on screen yet, the change happens instantly.
"""
from PySide6.QtCore import QEasingCurve, QEvent, QVariantAnimation, Qt, QPointF
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QWidget

ENABLED = True
FAST = 170      # ribbon tabs, small things
NORMAL = 230    # pages
_running = {}   # host widget -> overlay (so a new switch replaces an unfinished one)


def set_enabled(on):
    global ENABLED
    ENABLED = bool(on)


def enabled_for(widget):
    return ENABLED and widget is not None and widget.isVisible() and widget.width() > 2 and widget.height() > 2


class _Overlay(QWidget):
    """Paints the old picture of a widget, then the new one sliding/fading in on top."""

    def __init__(self, host, old, new, dx, dy):
        super().__init__(host)
        self.old, self.new, self.dx, self.dy = old, new, dx, dy
        self.t = 0.0
        img = new.toImage()
        self.bg = img.pixelColor(max(img.width() - 3, 0), max(img.height() - 3, 0)) if not img.isNull() \
            else host.palette().window().color()
        self.setGeometry(host.rect())

    def paintEvent(self, ev):
        # Office style: the old view fades out quickly while the new one glides in and fades up,
        # so the two never look like a double exposure
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), self.bg)
        t = self.t
        p.setOpacity(max(0.0, 1.0 - t * 2.6))
        p.drawPixmap(0, 0, self.old)
        p.setOpacity(min(1.0, t * 1.35))
        k = 1.0 - t
        p.drawPixmap(QPointF(self.dx * k, self.dy * k), self.new)
        p.end()


def _settle():
    QApplication.sendPostedEvents(None, QEvent.LayoutRequest)
    QApplication.sendPostedEvents(None, QEvent.Polish)


def transition(host, change, dx=0, dy=0, duration=NORMAL):
    """Run change() (which updates what `host` shows), then animate from the old look to the new one.
    The new look slides in from (dx, dy) pixels away while fading in."""
    if not enabled_for(host):
        change()
        return
    prev = _running.pop(host, None)
    if prev is not None:
        prev[1].stop()
        prev[0].hide()
        prev[0].deleteLater()
    old = host.grab()
    change()
    _settle()
    new = host.grab()
    ov = _Overlay(host, old, new, dx, dy)
    ov.show()
    ov.raise_()
    a = QVariantAnimation(ov)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setDuration(duration)
    a.setEasingCurve(QEasingCurve.OutCubic)

    def step(v):
        ov.t = float(v)
        ov.update()

    def done():
        if _running.get(host, (None,))[0] is ov:
            _running.pop(host, None)
        ov.deleteLater()
    a.valueChanged.connect(step)
    a.finished.connect(done)
    _running[host] = (ov, a)
    a.start()


def switch_stack(stack, index, dx=0, dy=0, duration=NORMAL):
    if stack.currentIndex() == index:
        return
    transition(stack, lambda: stack.setCurrentIndex(index), dx, dy, duration)


def switch_stack_widget(stack, widget, dx=0, dy=0, duration=NORMAL):
    if stack.currentWidget() is widget:
        return
    transition(stack, lambda: stack.setCurrentWidget(widget), dx, dy, duration)


def animate_height(widget, show, duration=FAST, on_done=None):
    """Slide a widget open/closed by animating its maximum height."""
    if not enabled_for(widget.parentWidget()):
        widget.setVisible(show)
        widget.setMaximumHeight(16777215)
        if on_done:
            on_done()
        return
    full = max(widget.sizeHint().height(), 1)
    start = widget.height() if widget.isVisible() else 0
    end = full if show else 0
    widget.setMaximumHeight(start)
    widget.setVisible(True)
    a = QVariantAnimation(widget)
    a.setStartValue(start)
    a.setEndValue(end)
    a.setDuration(duration)
    a.setEasingCurve(QEasingCurve.OutCubic if show else QEasingCurve.InCubic)
    a.valueChanged.connect(lambda v: widget.setMaximumHeight(int(v)))

    def done():
        widget.setMaximumHeight(16777215)
        widget.setVisible(show)
        if on_done:
            on_done()
    a.finished.connect(done)
    a.start(QVariantAnimation.DeleteWhenStopped)


def fade_in_window(win, duration=180):
    if not ENABLED:
        return
    win.setWindowOpacity(0.0)
    a = QVariantAnimation(win)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.setDuration(duration)
    a.setEasingCurve(QEasingCurve.OutCubic)
    a.valueChanged.connect(lambda v: win.setWindowOpacity(float(v)))
    a.finished.connect(lambda: win.setWindowOpacity(1.0))
    a.start(QVariantAnimation.DeleteWhenStopped)


def enable_menu_effects():
    """Fade/slide menus, drop-downs and tooltips like Windows does."""
    for eff in (Qt.UI_AnimateMenu, Qt.UI_FadeMenu, Qt.UI_AnimateCombo, Qt.UI_AnimateTooltip, Qt.UI_FadeTooltip):
        QApplication.setEffectEnabled(eff, ENABLED)
