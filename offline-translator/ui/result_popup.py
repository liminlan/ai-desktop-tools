"""翻译结果浮窗：米黄卡片 + 浅绿分区 + 深绿译文，跟随选区定位。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..core.config import CFG
from ..services.pipeline import PipelineResult
from . import theme

MARGIN = 14


class ResultPopup(QWidget):
    retranslate_requested = Signal()
    closed = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("翻译结果")

        self._result: PipelineResult | None = None
        self._anchor = QRect()
        self._show_source = True
        self._drag_origin: QPoint | None = None
        self._drag_start = QPoint()

        self._build_ui()
        self._apply_style()

    # ---------- 构建 ----------
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)

        self.card = QFrame(self)
        self.card.setObjectName("card")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(28)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(47, 93, 80, 60))
        self.card.setGraphicsEffect(shadow)
        outer.addWidget(self.card)

        body = QVBoxLayout(self.card)
        body.setContentsMargins(18, 14, 18, 14)
        body.setSpacing(10)

        # 顶栏
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = QLabel("英 → 中")
        self.title.setObjectName("Title")
        self.meta = QLabel("")
        self.meta.setObjectName("Meta")
        top.addWidget(self.title)
        top.addWidget(self.meta, 1, Qt.AlignLeft)
        self.btn_close = QPushButton("✕")
        self.btn_close.setObjectName("Close")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.clicked.connect(self.hide_and_close)
        top.addWidget(self.btn_close, 0, Qt.AlignTop)
        body.addLayout(top)

        # 原文
        self.src_box = QFrame()
        self.src_box.setObjectName("srcBox")
        src_layout = QVBoxLayout(self.src_box)
        src_layout.setContentsMargins(11, 8, 11, 8)
        self.src_label = QLabel()
        self.src_label.setObjectName("Source")
        self.src_label.setWordWrap(True)
        self.src_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        src_layout.addWidget(self.src_label)
        body.addWidget(self.src_box)

        # 译文
        self.dst_label = QLabel()
        self.dst_label.setObjectName("Target")
        self.dst_label.setWordWrap(True)
        self.dst_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.dst_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        body.addWidget(self.dst_label)

        # 底栏
        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.btn_copy = QPushButton("复制译文")
        self.btn_copy.setObjectName("Primary")
        self.btn_copy.setCursor(Qt.PointingHandCursor)
        self.btn_copy.clicked.connect(self._copy_target)
        self.btn_redo = QPushButton("重译")
        self.btn_redo.setCursor(Qt.PointingHandCursor)
        self.btn_redo.clicked.connect(self.retranslate_requested.emit)
        self.btn_toggle = QPushButton("隐藏原文")
        self.btn_toggle.setCursor(Qt.PointingHandCursor)
        self.btn_toggle.clicked.connect(self._toggle_source)
        bottom.addWidget(self.btn_copy)
        bottom.addWidget(self.btn_redo)
        bottom.addWidget(self.btn_toggle)
        bottom.addStretch(1)
        body.addLayout(bottom)

    def _apply_style(self) -> None:
        fs = int(CFG.get("popup.font_size", 16))
        self.setStyleSheet(
            f"""
            QFrame#card {{
                background: {theme.MILK};
                border: 1px solid {theme.BORDER};
                border-radius: 16px;
            }}
            QLabel#Title {{
                color: {theme.GREEN_DEEP};
                font-family: {theme.FONT_FAMILY};
                font-size: 12px;
                font-weight: 700;
                letter-spacing: 1px;
            }}
            QLabel#Meta {{
                color: {theme.TEXT_MUTED};
                font-family: {theme.FONT_FAMILY};
                font-size: 11px;
            }}
            QFrame#srcBox {{
                background: {theme.GREEN_PALE};
                border: 1px solid {theme.BORDER};
                border-radius: 10px;
            }}
            QLabel#Source {{
                color: {theme.TEXT_MUTED};
                font-family: {theme.FONT_FAMILY};
                font-size: {max(11, fs - 3)}px;
            }}
            QLabel#Target {{
                color: {theme.GREEN_DARK};
                font-family: {theme.FONT_FAMILY};
                font-size: {fs}px;
                line-height: 150%;
            }}
            QPushButton {{
                color: {theme.TEXT};
                font-family: {theme.FONT_FAMILY};
                font-size: 12px;
                background: transparent;
                border: 1px solid {theme.BORDER};
                border-radius: 8px;
                padding: 5px 12px;
            }}
            QPushButton:hover {{
                background: {theme.GREEN_PALE};
            }}
            QPushButton#Primary {{
                background: {theme.GREEN_DEEP};
                color: {theme.MILK};
                border: 1px solid {theme.GREEN_DEEP};
                font-weight: 600;
            }}
            QPushButton#Primary:hover {{
                background: {theme.GREEN_DARK};
            }}
            QPushButton#Close {{
                border: none;
                color: {theme.TEXT_MUTED};
                font-size: 14px;
                padding: 0px;
            }}
            QPushButton#Close:hover {{
                color: {theme.GREEN_DEEP};
                background: {theme.GREEN_PALE};
                border-radius: 12px;
            }}
            """
        )

    # ---------- 展示 ----------
    def show_loading(self, anchor: QRect) -> None:
        self._anchor = QRect(anchor)
        self._show_source = True
        self.src_box.setVisible(True)
        self.src_label.setText("正在识别…")
        self.dst_label.setText("稍等，本地模型正在跑")
        self.meta.setText("")
        self.btn_copy.setEnabled(False)
        self._resize_to_content()
        self._place(anchor)
        self.show()
        self.raise_()

    def show_message(self, text: str, anchor: QRect | None = None) -> None:
        if anchor is not None:
            self._anchor = QRect(anchor)
        self.src_box.setVisible(False)
        self.src_label.setText("")
        self.dst_label.setText(text)
        self.meta.setText("")
        self.btn_copy.setEnabled(False)
        self._resize_to_content()
        if anchor is not None:
            self._place(anchor)
        self.show()
        self.raise_()

    def show_result(self, result: PipelineResult, anchor: QRect) -> None:
        self._result = result
        self._anchor = QRect(anchor)

        if result.note and not result.target_text:
            self.show_message(result.note, anchor)
            return

        self.src_label.setText(result.source_text or "（无原文）")
        self.dst_label.setText(result.target_text or "（无译文）")
        bits = [f"{result.cost_ms} ms"]
        if result.line_count:
            bits.append(f"{result.line_count} 行")
        if result.from_cache:
            bits.append("缓存命中")
        if result.kind == "word":
            bits.append("单词")
        self.meta.setText(" · ".join(bits))
        self.btn_copy.setEnabled(bool(result.target_text))
        self.src_box.setVisible(self._show_source)
        self._resize_to_content()
        self._place(anchor)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)

    def update_anchor(self, anchor: QRect) -> None:
        self._anchor = QRect(anchor)
        self._place(anchor)

    def hide_and_close(self) -> None:
        self.hide()
        self.closed.emit()

    # ---------- 布局 ----------
    def _resize_to_content(self) -> None:
        max_w = int(CFG.get("popup.max_width", 520))
        screen = QGuiApplication.screenAt(self._anchor.center()) or QGuiApplication.primaryScreen()
        max_w = min(max_w, int(screen.availableGeometry().width() * 0.8)) if screen else max_w
        self.setFixedWidth(max_w + MARGIN * 2)
        self.card.setFixedWidth(max_w)
        self.adjustSize()
        max_h = int(screen.availableGeometry().height() * 0.7) if screen else 800
        if self.height() > max_h:
            self.setFixedHeight(max_h)

    def _place(self, anchor: QRect) -> None:
        screen = QGuiApplication.screenAt(anchor.center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        gap = 10
        w, h = self.width(), self.height()

        x = anchor.right() + gap
        if x + w > geo.right():
            x = anchor.left() - gap - w
        if x < geo.left():
            x = max(geo.left() + 4, min(anchor.left(), geo.right() - w - 4))

        y = anchor.top()
        if y + h > geo.bottom():
            y = geo.bottom() - h - 4
        if y < geo.top():
            y = geo.top() + 4

        self.move(QPoint(int(x), int(y)))

    # ---------- 交互 ----------
    def _copy_target(self) -> None:
        if self._result and self._result.target_text:
            QApplication.clipboard().setText(self._result.target_text)
            self.btn_copy.setText("已复制")
            from PySide6.QtCore import QTimer

            QTimer.singleShot(1200, lambda: self.btn_copy.setText("复制译文"))

    def _toggle_source(self) -> None:
        self._show_source = not self._show_source
        self.src_box.setVisible(self._show_source)
        self.btn_toggle.setText("隐藏原文" if self._show_source else "显示原文")
        self._resize_to_content()
        self._place(self._anchor)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.hide_and_close()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._drag_start = self.pos()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_origin is not None:
            delta = event.globalPosition().toPoint() - self._drag_origin
            self.move(self._drag_start + delta)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag_origin = None

    def paintEvent(self, event) -> None:  # noqa: N802
        # 外层透明，卡片自己画；这里只画一圈很淡的光晕让卡片浮起来
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(self.rect().adjusted(4, 4, -4, -4), 18, 18)
        painter.fillPath(path, QColor(0, 0, 0, 0))
        painter.end()
