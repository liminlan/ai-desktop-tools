"""悬浮球 / 悬浮条：常驻置顶的小控件，两种形态可随时切换。

- 圆形悬浮球：56px，占地小，放角落
- 悬浮条：横条带文字提示
左键单击 -> 进入框选取词；右键 -> 菜单；按住拖动 -> 移动位置。
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ..core.config import CFG
from . import theme

DRAG_THRESHOLD = 4


class FloatingWidget(QWidget):
    capture_requested = Signal()
    clipboard_requested = Signal()
    settings_requested = Signal()
    shape_toggle_requested = Signal()
    quit_requested = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("离线翻译")
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("单击：框选翻译　右键：菜单")

        self._busy = False
        self._press_pos: QPoint | None = None
        self._drag_offset = QPoint()
        self._dragged = False

        self._apply_shape()
        self._restore_pos()

    # ---------- 形态 ----------
    @property
    def shape_name(self) -> str:
        return str(CFG.get("ball.shape", "ball"))

    def _apply_shape(self) -> None:
        size = int(CFG.get("ball.size", 56))
        if self.shape_name == "ball":
            self.setFixedSize(size, size)
        else:
            self.setFixedSize(max(150, size * 3), max(38, int(size * 0.78)))

    def set_shape(self, shape: str) -> None:
        CFG.set("ball.shape", shape)
        self._apply_shape()
        self._restore_pos()
        self.update()

    def set_opacity(self, value: float) -> None:
        CFG.set("ball.opacity", value)
        self.setWindowOpacity(value)

    def set_busy(self, busy: bool, text: str = "") -> None:
        self._busy = busy
        if text:
            self.setToolTip(text)
        self.update()

    # ---------- 位置 ----------
    def _restore_pos(self) -> None:
        pos = CFG.get("ball.pos", [40, 320]) or [40, 320]
        x, y = int(pos[0]), int(pos[1])
        self.move(self._clamp(QPoint(x, y)))

    def _clamp(self, pos: QPoint) -> QPoint:
        screen = self.screen() or self.screen()
        if screen is None:
            return pos
        geo = screen.availableGeometry()
        x = max(geo.left(), min(pos.x(), geo.right() - self.width()))
        y = max(geo.top(), min(pos.y(), geo.bottom() - self.height()))
        return QPoint(x, y)

    def _save_pos(self) -> None:
        CFG.set("ball.pos", [self.x(), self.y()])

    def _maybe_snap(self) -> None:
        if not CFG.get("ball.edge_snap", True):
            return
        screen = self.screen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        margin = 8
        x, y = self.x(), self.y()
        if x - geo.left() < margin:
            x = geo.left() + margin
        if geo.right() - (x + self.width()) < margin:
            x = geo.right() - self.width() - margin
        if y - geo.top() < margin:
            y = geo.top() + margin
        if geo.bottom() - (y + self.height()) < margin:
            y = geo.bottom() - self.height() - margin
        self.move(x, y)

    # ---------- 绘制 ----------
    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        rect = self.rect().adjusted(2, 2, -2, -2)
        path = QPainterPath()
        radius = rect.height() / 2 if self.shape_name == "ball" else 16
        path.addRoundedRect(rect, radius, radius)

        # 米黄底 + 浅绿描边，忙碌时描边换亮绿
        painter.fillPath(path, QColor(theme.MILK if not self._busy else theme.GREEN_PALE))
        pen = QPen(QColor(theme.GREEN_DEEP if not self._busy else theme.GREEN_MID), 1.6)
        painter.setPen(pen)
        painter.drawPath(path)

        # 左侧深绿小圆点（品牌点）
        dot_r = 3.2
        if self.shape_name == "ball":
            dot_cx = rect.left() + rect.width() / 2
            dot_cy = rect.top() + rect.height() * 0.30
        else:
            dot_cx = rect.left() + 15
            dot_cy = rect.center().y()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.GREEN_DEEP))
        painter.drawEllipse(
            QPoint(int(dot_cx), int(dot_cy)), int(dot_r), int(dot_r)
        )

        painter.setPen(QColor(theme.GREEN_DARK))
        if self.shape_name == "ball":
            font = QFont(theme.FONT_FAMILY, 15, QFont.Bold)
            painter.setFont(font)
            body = QRect(rect.left(), int(rect.center().y() - 8), rect.width(), int(rect.height() * 0.6))
            painter.drawText(body, Qt.AlignHCenter | Qt.AlignVCenter, "译" if not self._busy else "…")
        else:
            font = QFont(theme.FONT_FAMILY, 10)
            painter.setFont(font)
            body = QRect(rect.left() + 26, rect.top(), rect.width() - 34, rect.height())
            painter.drawText(
                body, Qt.AlignLeft | Qt.AlignVCenter,
                "框中英文即译" if not self._busy else "识别中…",
            )
        painter.end()

    # ---------- 交互 ----------
    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._drag_offset = self._press_pos - self.pos()
            self._dragged = False
            event.accept()
        elif event.button() == Qt.RightButton:
            self._show_menu(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press_pos is None:
            return
        cur = event.globalPosition().toPoint()
        if not self._dragged and (cur - self._press_pos).manhattanLength() > DRAG_THRESHOLD:
            self._dragged = True
        if self._dragged:
            self.move(self._clamp(cur - self._drag_offset))
            event.accept()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() != Qt.LeftButton:
            return
        was_drag = self._dragged
        self._press_pos = None
        self._dragged = False
        if was_drag:
            self._maybe_snap()
            self._save_pos()
        else:
            self.capture_requested.emit()
        event.accept()

    def _show_menu(self, global_pos: QPoint) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.setStyleSheet(theme.MENU_QSS)
        act_capture = menu.addAction("框选翻译")
        act_clip = menu.addAction("翻译剪贴板")
        menu.addSeparator()
        other = "切换为悬浮条" if self.shape_name == "ball" else "切换为悬浮球"
        act_shape = menu.addAction(other)
        act_settings = menu.addAction("设置…")
        menu.addSeparator()
        act_quit = menu.addAction("退出")

        chosen = menu.exec(global_pos)
        if chosen == act_capture:
            self.capture_requested.emit()
        elif chosen == act_clip:
            self.clipboard_requested.emit()
        elif chosen == act_shape:
            self.shape_toggle_requested.emit()
        elif chosen == act_settings:
            self.settings_requested.emit()
        elif chosen == act_quit:
            self.quit_requested.emit()
