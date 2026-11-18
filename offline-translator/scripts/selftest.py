"""端到端自测：不启动界面，直接验证 模型 -> 翻译 -> OCR -> 行合并 是否真的能跑。

用法（在项目根目录）：
    .venv\\Scripts\\python.exe offline_translator\\scripts\\selftest.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # offline_translator/
PROJ = ROOT.parent                                      # 项目根（含 .venv）
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(ROOT))

from offline_translator.core import model_manager  # noqa: E402
from offline_translator.services.translation import get_translator  # noqa: E402


def line(t=""):
    print(line.sep if not t else f"\n{t}")
line.sep = "-" * 62


def test_models() -> bool:
    print("== 1. 模型状态 ==")
    print("  包目录 :", model_manager.resolve_package_dir())
    print("  CT2 目录:", model_manager.resolve_model_dir())
    print("  分词文件:", model_manager.find_sentencepiece())
    ok = model_manager.nmt_ready()
    print("  就绪 :", ok)
    return ok


def test_translate() -> None:
    print("\n== 2. 翻译引擎 ==")
    tr = get_translator()
    t0 = time.perf_counter()
    ok = tr.load()
    load_ms = int((time.perf_counter() - t0) * 1000)
    print(f"  加载: {ok}  {load_ms}ms  错误: {tr.load_error}")
    if not ok:
        return
    print(f"  前缀探测结果: {tr._prefix!r}")
    samples = [
        "Hello, how are you today?",
        "Please click the button below to continue.",
        "The quick brown fox jumps over the lazy dog.",
        "离线翻译不需要联网，所有计算都在你自己的电脑上完成。",
    ]
    for s in samples:
        t0 = time.perf_counter()
        r = tr.translate(s)
        ms = int((time.perf_counter() - t0) * 1000)
        print(f"  [{ms:4d}ms] {s}\n          -> {r}")


def test_ocr() -> None:
    print("\n== 3. OCR + 行合并 ==")
    try:
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np
    except Exception as exc:  # noqa: BLE001
        print("  PIL 不可用:", exc)
        return

    text_lines = [
        "Machine translation systems have improved a lot",
        "over the past few years, and small offline models",
        "are now good enough for everyday reading.",
    ]
    font = None
    for name in ("arial.ttf", "segoeui.ttf", "calibri.ttf"):
        try:
            font = ImageFont.truetype(f"C:/Windows/Fonts/{name}", 22)
            break
        except Exception:
            continue
    if font is None:
        font = ImageFont.load_default()

    img = Image.new("RGB", (760, 140), "white")
    draw = ImageDraw.Draw(img)
    for i, t in enumerate(text_lines):
        draw.text((24, 18 + i * 34), t, fill="black", font=font)
    test_png = ROOT / "scripts" / "_ocr_sample.png"
    img.save(test_png)

    from offline_translator.services import ocr_engine
    from offline_translator.services.line_merge import merge_lines

    try:
        bgr = np.array(img)[:, :, ::-1].copy()
        t0 = time.perf_counter()
        lines = ocr_engine.recognize(np.ascontiguousarray(bgr))
        ocr_ms = int((time.perf_counter() - t0) * 1000)
        print(f"  OCR 耗时 {ocr_ms}ms，识别到 {len(lines)} 行：")
        for ln in lines:
            print(f"    box={ln.box} conf={ln.conf:.2f} {ln.text!r}")
        paragraphs = merge_lines(lines, 1.45)
        print(f"  合并成 {len(paragraphs)} 段：")
        for p in paragraphs:
            print("    ", p)
        tr = get_translator()
        if tr.ready and paragraphs:
            print("  译文：")
            for p in paragraphs:
                print("    ", tr.translate(p))
    except Exception as exc:  # noqa: BLE001
        print("  OCR 失败:", type(exc).__name__, exc)


def main() -> int:
    line()
    if not test_models():
        print("\n模型没就绪，先跑 scripts/download_models.py")
        return 1
    test_translate()
    test_ocr()
    line()
    print("自测结束")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
