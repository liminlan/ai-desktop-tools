"""第二层自测：验证 pipeline 门面（语言拦截 / 缓存命中 / 预热后耗时）。"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJ = ROOT.parent
sys.path.insert(0, str(PROJ))
sys.path.insert(0, str(ROOT))

from offline_translator.services.cache import Cache  # noqa: E402
from offline_translator.services.pipeline import TranslateService  # noqa: E402


def main() -> int:
    svc = TranslateService(Cache(ROOT / "cache_test.db"))
    print("== 预热 ==")
    t0 = time.perf_counter()
    print("  ", svc.warm_up(), f"{(time.perf_counter()-t0)*1000:.0f}ms")

    print("\n== 语言拦截 ==")
    cases = [
        "这是一段中文，不应该被翻译",
        "Hello world",
        "离线翻译软件",
        "abcdef",
        "Good morning, have a nice day!",
    ]
    for c in cases:
        r = svc.translate_text(c)
        print(f"  {c!r}\n    -> 译文={r.target_text!r} 提示={r.note!r} {r.cost_ms}ms")

    print("\n== 缓存命中 ==")
    s = "This sentence should be served from cache the second time."
    r1 = svc.translate_text(s)
    r2 = svc.translate_text(s)
    print(f"  第一次 {r1.cost_ms}ms 缓存={r1.from_cache}  -> {r1.target_text}")
    print(f"  第二次 {r2.cost_ms}ms 缓存={r2.from_cache}  -> {r2.target_text}")

    print("\n== OCR 预热后耗时 ==")
    try:
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np
        from offline_translator.services import ocr_engine

        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 20)
        img = Image.new("RGB", (640, 80), "white")
        draw = ImageDraw.Draw(img)
        draw.text((20, 26), "Offline translation works without any internet.", fill="black", font=font)
        bgr = np.ascontiguousarray(np.array(img)[:, :, ::-1])
        for i in range(3):
            t0 = time.perf_counter()
            lines = ocr_engine.recognize(bgr)
            print(f"  第{i+1}次 OCR: {int((time.perf_counter()-t0)*1000)}ms 行数={len(lines)}")
        r = svc.translate_image(bgr)
        print(f"  整链路: {r.cost_ms}ms  -> {r.target_text}")
    except Exception as exc:  # noqa: BLE001
        print("  OCR 测试失败:", type(exc).__name__, exc)

    print("\n== 历史 ==")
    for row in svc.cache.history(5):
        print("  ", row)
    svc.cache.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
