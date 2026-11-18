"""不接管鼠标的 GUI 验证：真实抓屏裁剪 + OCR + 翻译 + 把界面渲染成图片。

用法：.venv\\Scripts\\python.exe offline_translator\\scripts\\ui_preview.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJ = ROOT.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QRect, QSize  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from offline_translator.core.config import CFG  # noqa: E402
from offline_translator.services.cache import Cache  # noqa: E402
from offline_translator.services.pipeline import TranslateService, PipelineResult  # noqa: E402
from offline_translator.ui.capture_overlay import CaptureOverlay, qimage_to_bgr  # noqa: E402
from offline_translator.ui.floating import FloatingWidget  # noqa: E402
from offline_translator.ui.result_popup import ResultPopup  # noqa: E402

OUT = ROOT / "scripts"
svc = TranslateService(Cache(ROOT / "cache_test.db"))

print("== 1. 真实抓屏 + 裁剪 ==")
ov = CaptureOverlay()
ov._grab_screens()
ov.setGeometry(ov._virtual)
print("   虚拟桌面:", ov._virtual, " 屏数:", len(ov._shots))
crop_rect = QRect(40, 40, 1100, 380)
crop = ov._crop(crop_rect)
crop_path = OUT / "_preview_crop.png"
crop.save(str(crop_path))
print(f"   裁剪尺寸: {crop.width()}x{crop.height()} -> {crop_path.name}")

bgr = qimage_to_bgr(crop)
result = svc.translate_image(bgr)
print("   OCR 原文:")
for ln in result.source_text.split("\n\n"):
    print("     ", ln.replace("\n", " / "))
print("   译文:")
for ln in result.target_text.split("\n\n"):
    print("     ", ln)
print(f"   提示={result.note!r} 行数={result.line_count} 耗时={result.cost_ms}ms")

print("\n== 2. 渲染结果窗 ==")
popup = ResultPopup()
popup.show_loading(QRect(400, 300, 200, 60))
app.processEvents()
popup.show_result(result, QRect(400, 300, 200, 60))
app.processEvents()
popup_png = OUT / "_preview_popup.png"
popup.grab().save(str(popup_png))
print("   ->", popup_png.name, popup.size())

print("\n== 3. 渲染悬浮球 / 悬浮条 ==")
ball = FloatingWidget()
ball.set_shape("ball")
ball.show()
app.processEvents()
ball.grab().save(str(OUT / "_preview_ball.png"))
print("   悬浮球尺寸:", ball.size())

ball.set_shape("bar")
ball.show()
app.processEvents()
ball.grab().save(str(OUT / "_preview_bar.png"))
print("   悬浮条尺寸:", ball.size())

ball.set_shape("ball")  # 恢复默认，别把用户配置留在 bar
ball.hide()
popup.hide()
print("   完成")

svc.cache.close()
