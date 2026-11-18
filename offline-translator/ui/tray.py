"""托盘图标与菜单。"""
from __future__ import annotations

from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QSystemTrayIcon

from . import theme


def make_icon(size: int = 64) -> QIcon:
    """代码画图标：米黄圆 + 浅绿描边 + 深绿"译"字。免得到处找图片素材。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    rect = QRect(3, 3, size - 6, size - 6)
    painter.setBrush(QColor(theme.MILK))
    painter.setPen(QColor(theme.GREEN_DEEP))
    painter.drawEllipse(rect)
    painter.setPen(QColor(theme.GREEN_DEEP))
    font = QFont(theme.FONT_FAMILY, int(size * 0.42), QFont.Bold)
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignCenter, "译")
    painter.end()
    return QIcon(pm)


class Tray(QSystemTrayIcon):
    capture_requested = Signal()
    clipboard_requested = Signal()
    shape_toggle_requested = Signal()
    settings_requested = Signal()
    quit_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(make_icon(), parent)
        self.setToolTip("离线翻译悬浮窗")
        menu = self._build_menu()
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _build_menu(self):
        from PySide6.QtWidgets import QMenu

        menu = QMenu()
        menu.setStyleSheet(theme.MENU_QSS)
        self.act_capture = menu.addAction("框选翻译")
        self.act_clip = menu.addAction("翻译剪贴板")
        menu.addSeparator()
        self.act_shape = menu.addAction("切换悬浮形态")
        self.act_settings = menu.addAction("设置…")
        menu.addSeparator()
        self.act_quit = menu.addAction("退出")

        self.act_capture.triggered.connect(self.capture_requested.emit)
        self.act_clip.triggered.connect(self.clipboard_requested.emit)
        self.act_shape.triggered.connect(self.shape_toggle_requested.emit)
        self.act_settings.triggered.connect(self.settings_requested.emit)
        self.act_quit.triggered.connect(self.quit_requested.emit)
        return menu

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self.capture_requested.emit()
