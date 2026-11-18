"""设置窗口：热键、形态、字号、设备、缓存。浅色米黄/绿风格。"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..core import autostart, model_manager
from ..core.config import CFG
from ..core.hotkey import parse_hotkey
from . import theme


class SettingsDialog(QDialog):
    settings_applied = Signal()

    def __init__(self, cache=None, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("离线翻译 · 设置")
        self.setModal(True)
        self.setMinimumWidth(430)
        self.setStyleSheet(theme.SETTINGS_QSS)
        self._cache = cache
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 16)
        root.setSpacing(12)

        title = QLabel("离线翻译悬浮窗")
        title.setStyleSheet(
            f"color:{theme.GREEN_DEEP}; font-size:17px; font-weight:700;"
            f" font-family:{theme.FONT_FAMILY};"
        )
        root.addWidget(title)
        sub = QLabel("全部在本机运行，不联网、不调用任何在线接口")
        sub.setObjectName("Hint")
        root.addWidget(sub)

        # 热键
        g_hot = QGroupBox("操作方式")
        f_hot = QFormLayout(g_hot)
        f_hot.setLabelAlignment(Qt.AlignLeft)
        f_hot.setSpacing(9)

        self.k_capture = QKeySequenceEdit()
        self.k_capture.setKeySequence(QKeySequence(str(CFG.get("hotkey.capture", "Alt+T")))
                                      )
        f_hot.addRow("框选翻译热键", self.k_capture)

        self.k_clip = QKeySequenceEdit()
        self.k_clip.setKeySequence(QKeySequence(str(CFG.get("hotkey.clipboard", "Ctrl+Alt+C")))
                                   )
        f_hot.addRow("翻译剪贴板热键", self.k_clip)

        self.c_shape = QComboBox()
        self.c_shape.addItems(["悬浮球（圆形，占地小）", "悬浮条（横条）"])
        self.c_shape.setCurrentIndex(0 if str(CFG.get("ball.shape", "ball")) == "ball" else 1)
        f_hot.addRow("悬浮形态", self.c_shape)

        self.chk_clip_auto = QCheckBox("复制英文后自动翻译（默认关闭，防误触）")
        self.chk_clip_auto.setChecked(bool(CFG.get("clipboard.auto_translate", False)))
        f_hot.addRow("", self.chk_clip_auto)

        self.chk_autostart = QCheckBox("开机自动启动")
        self.chk_autostart.setChecked(bool(CFG.get("startup.autostart", False)))
        f_hot.addRow("", self.chk_autostart)
        root.addWidget(g_hot)

        # 显示
        g_view = QGroupBox("外观")
        f_view = QFormLayout(g_view)
        f_view.setSpacing(9)
        self.spin_font = QSpinBox()
        self.spin_font.setRange(12, 28)
        self.spin_font.setSuffix(" px")
        self.spin_font.setValue(int(CFG.get("popup.font_size", 16)))
        f_view.addRow("译文字号", self.spin_font)

        self.spin_width = QSpinBox()
        self.spin_width.setRange(320, 900)
        self.spin_width.setSingleStep(20)
        self.spin_width.setSuffix(" px")
        self.spin_width.setValue(int(CFG.get("popup.max_width", 520)))
        f_view.addRow("结果窗宽度", self.spin_width)
        root.addWidget(g_view)

        # 引擎
        g_eng = QGroupBox("引擎")
        f_eng = QFormLayout(g_eng)
        f_eng.setSpacing(9)
        self.c_device = QComboBox()
        self.c_device.addItems(["cpu（稳定，够快）", "cuda（有 N 卡可试）"])
        self.c_device.setCurrentIndex(
            0 if str(CFG.get("engine.device", "cpu")) == "cpu" else 1
        )
        f_eng.addRow("计算设备", self.c_device)

        self.lbl_model = QLabel(model_manager.nmt_status())
        self.lbl_model.setObjectName("Hint")
        self.lbl_model.setWordWrap(True)
        f_eng.addRow("模型状态", self.lbl_model)

        ocr_label = "加载中…"
        try:
            from ..services import ocr_engine

            ocr_label = ocr_engine.backend_label()
        except Exception as exc:  # noqa: BLE001
            ocr_label = f"不可用（{exc}）"
        lbl_ocr = QLabel(ocr_label)
        lbl_ocr.setObjectName("Hint")
        f_eng.addRow("取词引擎", lbl_ocr)

        self.btn_clear = QPushButton("清除翻译缓存")
        self.btn_clear.clicked.connect(self._clear_cache)
        f_eng.addRow("", self.btn_clear)
        root.addWidget(g_eng)

        tip = QLabel("提示：改了热键要重启程序才生效；其余设置保存后立即生效。")
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        root.addWidget(tip)

        # 底部
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save = QPushButton("保存")
        self.btn_save.setObjectName("Primary")
        self.btn_save.clicked.connect(self._save)
        bottom.addWidget(self.btn_cancel)
        bottom.addWidget(self.btn_save)
        root.addLayout(bottom)

    # ---------- 动作 ----------
    def _clear_cache(self) -> None:
        if self._cache is None:
            return
        try:
            n = self._cache.clear()
            QMessageBox.information(self, "已清除", f"删掉了 {n} 条缓存记录。")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "出错了", str(exc))

    def _save(self) -> None:
        capture = self.k_capture.keySequence().toString()
        clip = self.k_clip.keySequence().toString()

        if not parse_hotkey(capture):
            QMessageBox.warning(self, "热键无效", "框选翻译热键至少需要一个修饰键 + 一个按键，例如 Alt+T。")
            return
        if not parse_hotkey(clip):
            QMessageBox.warning(self, "热键无效", "翻译剪贴板热键格式不对，例如 Ctrl+Alt+C。")
            return

        CFG.set("hotkey.capture", capture)
        CFG.set("hotkey.clipboard", clip)
        CFG.set("ball.shape", "ball" if self.c_shape.currentIndex() == 0 else "bar")
        CFG.set("clipboard.auto_translate", self.chk_clip_auto.isChecked())
        CFG.set("startup.autostart", self.chk_autostart.isChecked())
        CFG.set("popup.font_size", self.spin_font.value())
        CFG.set("popup.max_width", self.spin_width.value())
        CFG.set("engine.device", "cpu" if self.c_device.currentIndex() == 0 else "cuda")

        if self.chk_autostart.isChecked():
            if not autostart.set_enabled(True):
                QMessageBox.warning(self, "设置失败", "写开机启动项失败，可能被安全软件拦了。")
                CFG.set("startup.autostart", False)
        else:
            autostart.set_enabled(False)

        self.settings_applied.emit()
        self.accept()
