"""全屏框选遮罩：冻结画面 + 拖框选区 + 高清裁剪。

多屏和 DPI 的处理思路：
抓屏得到的是物理像素，窗口 geometry 是逻辑像素。这里把每个屏幕的抓图按"逻辑几何"
铺到遮罩上做背景，但真正裁剪时回到原始物理分辨率的 pixmap 上取，保证 OCR 拿到的是
最清晰的图，而不是被缩放到屏幕逻辑尺寸的模糊版本。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from . import theme

MIN_SIZE = 8


class CaptureOverlay(QWidget):
    selected = Signal(QImage, QRect)   # (裁剪图, 选区全局矩形)
    cancelled = Signal()

    def __init__(self) -> None:
        super().__init__(
            None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setCursor(Qt.CrossCursor)
        self.setMouseTracking(True)
        self.setWindowTitle("框选翻译")

        self._shots: list[tuple[QRect, QPixmap]] = []
        self._virtual = QRect()
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._selecting = False
        self._mouse = QPoint(0, 0)

    # ---------- 启动 ----------
    def start(self) -> None:
        self._grab_screens()
        self.setGeometry(self._virtual)
        self._origin = None
        self._current = None
        self._selecting = False
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        self.update()

    def _grab_screens(self) -> None:
        self._shots.clear()
        virtual = QRect()
        for screen in QGuiApplication.screens():
            geo = screen.geometry()
            virtual = virtual.united(geo) if not virtual.isNull() else QRect(geo)
            try:
                pm = screen.grabWindow(0)
            except Exception:
                pm = QPixmap()
            # 统一成"1 物理像素 = 1 pixmap 坐标"，避免 DPR 在裁剪时互相打架
            pm.setDevicePixelRatio(1.0)
            self._shots.append((QRect(geo), pm))
        self._virtual = virtual

    # ---------- 绘制 ----------
    def _paint_background(self, painter: QPainter) -> None:
        for geo, pm in self._shots:
            if pm.isNull():
                continue
            target = QRect(geo.topLeft() - self._virtual.topLeft(), geo.size())
            painter.drawPixmap(target, pm)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)

        self._paint_background(painter)

        sel = self._selection_rect()
        if not sel.isValid() or sel.isEmpty():
            painter.fillRect(self.rect(), QColor(29, 62, 53, 130))
        else:
            painter.fillRect(self.rect(), QColor(29, 62, 53, 130))
            # 选区内重新铺一遍清晰原图
            painter.save()
            painter.setClipRect(sel)
            self._paint_background(painter)
            painter.restore()

            pen = QPen(QColor(theme.GREEN_LIGHT), 2)
            painter.setPen(pen)
            painter.drawRect(sel.adjusted(0, 0, -1, -1))

            # 尺寸标签
            label = f"{sel.width()} × {sel.height()}"
            painter.setFont(QFont(theme.FONT_FAMILY, 9))
            fm = painter.fontMetrics()
            tw = fm.horizontalAdvance(label) + 14
            th = fm.height() + 8
            tag_rect = QRect(
                sel.left(), max(self.rect().top() + 4, sel.top() - th - 6), tw, th
            )
            path = QPainterPath()
            path.addRoundedRect(tag_rect, 6, 6)
            painter.fillPath(path, QColor(theme.GREEN_DEEP))
            painter.setPen(QColor(theme.MILK))
            painter.drawText(tag_rect, Qt.AlignCenter, label)

        if not self._selecting:
            self._paint_hint(painter)
            self._paint_crosshair(painter)

        painter.end()

    def _paint_hint(self, painter: QPainter) -> None:
        text = "拖动选择要翻译的英文区域　·　Esc 取消"
        painter.setFont(QFont(theme.FONT_FAMILY, 10))
        fm = painter.fontMetrics()
        w = fm.horizontalAdvance(text) + 32
        h = fm.height() + 18
        rect = QRect(
            (self.rect().width() - w) // 2, max(24, self.rect().height() // 22), w, h
        )
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        painter.fillPath(path, QColor(251, 247, 234, 236))
        painter.setPen(QPen(QColor(theme.GREEN_LIGHT), 1))
        painter.drawPath(path)
        painter.setPen(QColor(theme.GREEN_DARK))
        painter.drawText(rect, Qt.AlignCenter, text)

    def _paint_crosshair(self, painter: QPainter) -> None:
        pen = QPen(QColor(169, 201, 162, 130), 1, Qt.DashLine)
        painter.setPen(pen)
        painter.drawLine(0, self._mouse.y(), self.width(), self._mouse.y())
        painter.drawLine(self._mouse.x(), 0, self._mouse.x(), self.height())

    # ---------- 事件 ----------
    def _selection_rect(self) -> QRect:
        if self._origin is None or self._current is None:
            return QRect()
        return QRect(self._origin, self._current).normalized()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.RightButton:
            self._abort()
            return
        if event.button() == Qt.LeftButton:
            self._origin = event.position().toPoint()
            self._current = self._origin
            self._selecting = True
            self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._mouse = event.position().toPoint()
        if self._selecting and self._origin is not None:
            self._current = self._mouse
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton or not self._selecting:
            return
        self._selecting = False
        rect = self._selection_rect()
        if rect.width() < MIN_SIZE or rect.height() < MIN_SIZE:
            self._abort()
            return
        image = self._crop(rect)
        global_rect = QRect(rect.topLeft() + self._virtual.topLeft(), rect.size())
        self.hide()
        if image.isNull():
            self.cancelled.emit()
        else:
            self.selected.emit(image, global_rect)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self._abort()
            return
        super().keyPressEvent(event)

    def _abort(self) -> None:
        self.hide()
        self.cancelled.emit()

    # ---------- 裁剪 ----------
    def _crop(self, rect_logical: QRect) -> QImage:
        primary = QGuiApplication.primaryScreen()
        dpr = primary.devicePixelRatio() if primary else 1.0
        dpr = max(1.0, float(dpr))

        out = QImage(
            int(round(rect_logical.width() * dpr)),
            int(round(rect_logical.height() * dpr)),
            QImage.Format_RGB32,
        )
        out.fill(QColor("#FFFFFF"))
        painter = QPainter(out)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        for geo, pm in self._shots:
            if pm.isNull():
                continue
            inter = rect_logical.intersected(geo)
            if inter.isEmpty():
                continue
            sx = pm.width() / max(1, geo.width())
            sy = pm.height() / max(1, geo.height())
            src = QRect(
                int(round((inter.left() - geo.left()) * sx)),
                int(round((inter.top() - geo.top()) * sy)),
                max(1, int(round(inter.width() * sx))),
                max(1, int(round(inter.height() * sy))),
            )
            dst = QRect(
                int(round((inter.left() - rect_logical.left()) * dpr)),
                int(round((inter.top() - rect_logical.top()) * dpr)),
                max(1, int(round(inter.width() * dpr))),
                max(1, int(round(inter.height() * dpr))),
            )
            painter.drawPixmap(dst, pm, src)
        painter.end()
        return out


def qimage_to_bgr(image: QImage):
    """QImage -> numpy BGR（RapidOCR 吃的格式）。"""
    import numpy as np

    if image.isNull():
        return None
    converted = image.convertToFormat(QImage.Format_RGB888)
    w, h = converted.width(), converted.height()
    if w <= 0 or h <= 0:
        return None
    stride = converted.bytesPerLine()
    buf = converted.constBits()
    try:
        arr = np.frombuffer(buf, dtype=np.uint8, count=stride * h).reshape(h, stride)
    except TypeError:
        arr = np.array(buf).reshape(h, stride)
    rgb = arr[:, : w * 3].reshape(h, w, 3)
    return np.ascontiguousarray(rgb[:, :, ::-1])
