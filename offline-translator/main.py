"""程序入口：单实例 + 组装各模块 + 全局热键 + 剪贴板监听。

运行方式（开发态）：
    .venv\\Scripts\\pythonw.exe offline_translator\\main.py
"""
from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

# 允许以 `python offline_translator/main.py` 直接运行
_HERE = Path(__file__).resolve().parent
if str(_HERE.parent) not in sys.path:
    sys.path.insert(0, str(_HERE.parent))

from PySide6.QtCore import QObject, QRect, QSize, QTimer, Qt, Signal  # noqa: E402
from PySide6.QtGui import QCursor, QGuiApplication  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog  # noqa: E402

from offline_translator.core import model_manager  # noqa: E402
from offline_translator.core.config import CFG, LOG_PATH  # noqa: E402
from offline_translator.core.hotkey import HotkeyManager  # noqa: E402
from offline_translator.services.cache import Cache  # noqa: E402
from offline_translator.services.pipeline import PipelineResult, TranslateService  # noqa: E402
from offline_translator.ui.capture_overlay import CaptureOverlay, qimage_to_bgr  # noqa: E402
from offline_translator.ui.floating import FloatingWidget  # noqa: E402
from offline_translator.ui.result_popup import ResultPopup  # noqa: E402
from offline_translator.ui.settings_dialog import SettingsDialog  # noqa: E402
from offline_translator.ui.tray import Tray  # noqa: E402
from offline_translator.ui.workers import run_async  # noqa: E402

SERVER_KEY = "OfflineTranslator_SingleInstance_v1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("app")


class _Bridge(QObject):
    """热键线程 -> 主线程的安全通道（Qt 会自动走 queued connection）。"""

    capture = Signal()
    clipboard = Signal()


class App(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__()
        self.app = app
        self.cache = Cache()
        self.service = TranslateService(self.cache)

        self.ball = FloatingWidget()
        self.overlay = CaptureOverlay()
        self.popup = ResultPopup()
        self.tray = Tray()
        self.settings: SettingsDialog | None = None

        self._bridge = _Bridge()
        self._hotkeys = HotkeyManager()
        self._clip_timer = QTimer(self)
        self._clip_timer.setSingleShot(True)
        self._last_clip_text = ""
        self._last_anchor = QRect()

        self._wire()

    # ---------- 信号串联 ----------
    def _wire(self) -> None:
        self.ball.capture_requested.connect(self.start_capture)
        self.ball.clipboard_requested.connect(self.start_clipboard)
        self.ball.settings_requested.connect(self.open_settings)
        self.ball.shape_toggle_requested.connect(self.toggle_shape)
        self.ball.quit_requested.connect(self.quit)

        self.tray.capture_requested.connect(self.start_capture)
        self.tray.clipboard_requested.connect(self.start_clipboard)
        self.tray.shape_toggle_requested.connect(self.toggle_shape)
        self.tray.settings_requested.connect(self.open_settings)
        self.tray.quit_requested.connect(self.quit)

        self.overlay.selected.connect(self.on_selected)
        self.overlay.cancelled.connect(self.on_capture_cancelled)

        self.popup.retranslate_requested.connect(self.retranslate)
        self.popup.closed.connect(lambda: None)

        self._bridge.capture.connect(self.start_capture, Qt.QueuedConnection)
        self._bridge.clipboard.connect(self.start_clipboard, Qt.QueuedConnection)

        self._clip_timer.timeout.connect(self._on_clip_debounce)
        QGuiApplication.clipboard().dataChanged.connect(self._on_clip_changed)

    # ---------- 启动 ----------
    def start(self) -> None:
        self.tray.show()
        self.ball.show()
        self.ball.setWindowOpacity(float(CFG.get("ball.opacity", 0.94)))

        failed = self._hotkeys.register([
            (str(CFG.get("hotkey.capture", "Alt+T")), "capture"),
            (str(CFG.get("hotkey.clipboard", "Ctrl+Alt+C")), "clipboard"),
        ])
        # 必须注册之后再绑回调：register() 会把回调表清空
        self._hotkeys.bind_callback("capture", self._bridge.capture.emit)
        self._hotkeys.bind_callback("clipboard", self._bridge.clipboard.emit)
        for item in failed:
            log.warning("热键注册失败: %s", item)
        if failed and self.tray.isSystemTrayAvailable():
            self.tray.showMessage(
                "热键被占用",
                "以下热键没注册成功，去设置里换一个：\n" + "\n".join(failed),
                TrayIconInfo(),
                6000,
            )

        # 后台预热模型，别让第一次取词等两三秒
        def _warm():
            msg = self.service.warm_up()
            log.info("预热结果：%s", msg)
            return msg

        def _on_warm(msg: str):
            if "失败" in msg:
                self.ball.setToolTip("模型异常：" + msg)

        run_async(_warm, _on_warm, lambda s, d: log.error("预热异常: %s", s))

    # ---------- 取词 ----------
    def start_capture(self) -> None:
        if self.overlay.isVisible():
            return
        self.popup.hide()
        # 先把悬浮球藏起来再抓屏，否则它会被截进画面
        self.ball.hide()
        QTimer.singleShot(120, self._begin_capture)

    def _begin_capture(self) -> None:
        self.overlay.start()

    def on_capture_cancelled(self) -> None:
        self.ball.show()

    def on_selected(self, image, anchor: QRect) -> None:
        self.ball.show()
        self.ball.set_busy(True)
        self._last_anchor = QRect(anchor)
        self.popup.show_loading(anchor)

        bgr = qimage_to_bgr(image)

        def _done(result: PipelineResult) -> None:
            log.info("取词完成：%d 行，%dms，缓存=%s", result.line_count, result.cost_ms, result.from_cache)
            self.ball.set_busy(False)
            self.popup.show_result(result, self._last_anchor)

        def _fail(brief: str, detail: str) -> None:
            self.ball.set_busy(False)
            log.error("取词失败: %s\n%s", brief, detail)
            self.popup.show_message(f"出错了：{brief}", self._last_anchor)

        run_async(self.service.translate_image, _done, _fail, bgr)

    # ---------- 剪贴板 ----------
    def start_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if not text:
            self._popup_at_cursor("剪贴板里没有文字")
            return
        self._translate_clipboard(text)

    def _translate_clipboard(self, text: str) -> None:
        anchor = QRect(QCursor.pos(), QSize(1, 1))
        self._last_anchor = anchor
        self.popup.show_loading(anchor)

        def _done(result: PipelineResult) -> None:
            self.popup.show_result(result, self._last_anchor)

        def _fail(brief: str, detail: str) -> None:
            log.error("剪贴板翻译失败: %s\n%s", brief, detail)
            self.popup.show_message(f"出错了：{brief}", self._last_anchor)

        run_async(self.service.translate_text, _done, _fail, text)

    def _on_clip_changed(self) -> None:
        if not CFG.get("clipboard.auto_translate", False):
            return
        self._clip_timer.start(int(CFG.get("clipboard.debounce_ms", 400)))

    def _on_clip_debounce(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if not text or text == self._last_clip_text:
            return
        min_chars = int(CFG.get("clipboard.min_chars", 2))
        if len(text) < min_chars or len(text) > 4000:
            return
        self._last_clip_text = text
        self._translate_clipboard(text)

    def _popup_at_cursor(self, message: str) -> None:
        anchor = QRect(QCursor.pos(), QSize(1, 1))
        self._last_anchor = anchor
        self.popup.show_message(message, anchor)

    # ---------- 其它 ----------
    def retranslate(self) -> None:
        if not self.popup.isVisible():
            return
        text = self.popup.src_label.text().strip()
        if text:
            self._translate_clipboard(text)

    def toggle_shape(self) -> None:
        new = "bar" if self.ball.shape_name == "ball" else "ball"
        self.ball.set_shape(new)
        self.ball.show()

    def open_settings(self) -> None:
        if self.settings is not None and self.settings.isVisible():
            self.settings.raise_()
            return
        self.settings = SettingsDialog(self.cache)
        self.settings.settings_applied.connect(self._apply_settings)
        self.settings.exec()

    def _apply_settings(self) -> None:
        self.ball.set_shape(str(CFG.get("ball.shape", "ball")))
        self.ball.setWindowOpacity(float(CFG.get("ball.opacity", 0.94)))
        self.ball.show()

    def quit(self) -> None:
        try:
            self._hotkeys.stop()
            self.cache.close()
        finally:
            self.tray.hide()
            self.app.quit()


def TrayIconInfo():
    from PySide6.QtWidgets import QSystemTrayIcon

    return QSystemTrayIcon.Information


def _maybe_offer_model_download() -> None:
    """模型缺失时引导下载（只此一次联网）。"""
    if model_manager.nmt_ready():
        return
    answer = QMessageBox.question(
        None,
        "还缺翻译模型",
        "第一次用需要下载 en→zh 翻译模型（约 70MB，只这一次联网，之后永久离线）。\n现在下载吗？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )
    if answer != QMessageBox.Yes:
        return

    progress = QProgressDialog("正在下载翻译模型…", "取消", 0, 100)
    progress.setWindowTitle("下载模型")
    progress.setWindowModality(Qt.ApplicationModal)
    progress.setMinimumDuration(0)
    progress.show()

    def _job():
        return model_manager.download_nmt(progress=lambda r: progress.setValue(int(r * 100)))

    def _ok(msg: str) -> None:
        progress.close()
        QMessageBox.information(None, "模型就绪", f"{msg}\n\n现在可以正常用了。")

    def _fail(brief: str, detail: str) -> None:
        progress.close()
        log.error("模型下载失败: %s\n%s", brief, detail)
        QMessageBox.warning(
            None,
            "下载失败",
            f"{brief}\n\n可以手动把 .argosmodel 解压到 models/nmt/en_zh/ 下，"
            "或用命令行跑：python offline_translator/scripts/download_models.py",
        )

    run_async(_job, _ok, _fail)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("离线翻译悬浮窗")
    app.setQuitOnLastWindowClosed(False)

    # 单实例：已经开着一份就不再起第二个
    probe = QLocalSocket()
    probe.connectToServer(SERVER_KEY)
    if probe.waitForConnected(300):
        probe.disconnectFromServer()
        QMessageBox.information(None, "已在运行", "桌面右下角托盘里已经有了，别重复开。")
        return 0

    server = QLocalServer()
    QLocalServer.removeServer(SERVER_KEY)
    server.listen(SERVER_KEY)

    def _excepthook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("未捕获异常:\n%s", text)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook

    _maybe_offer_model_download()

    controller = App(app)
    controller.start()
    log.info("启动完成，热键框选=%s", CFG.get("hotkey.capture"))
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
