"""OCR 引擎：双后端，纯离线。

1) windows  —— Windows 10/11 自带的 Media.Ocr。实测英文识别 8~50ms，空格保留完整，
               零模型体积，是框选取词的最优解。
2) rapidocr —— PP-OCR 的 ONNX 版，作为兜底（系统没有 OCR 语言包或需要更强中文时用）。

选择逻辑：auto 时优先 windows，不可用再退 rapidocr。
"""
from __future__ import annotations

import io
import logging
import threading

import numpy as np

from ..core.config import CFG
from .line_merge import TextLine

log = logging.getLogger(__name__)

_ENGINE = None
_ENGINE_KIND = "none"
# 用 RLock：get_backend() 持锁期间会调用 _win_call()，_win_call 内部还要再拿一次锁
_LOCK = threading.RLock()

# Windows OCR 必须跑在独立的 MTA 线程里：
# Qt 主线程是 STA 且事件循环里没有等待 WinRT 的异步，直接在主线程 await 会永久卡死。
_WIN_QUEUE: "queue.Queue" = None  # type: ignore[assignment]
_WIN_THREAD = None


class OcrError(RuntimeError):
    pass


# ============================ Windows OCR ============================
def _windows_available() -> bool:
    try:
        from winrt.windows.media.ocr import OcrEngine  # noqa: F401

        return True
    except Exception:
        return False


def _make_windows_engine():
    from winrt.windows.media.ocr import OcrEngine

    # 优先找英文识别器；中文系统一般只有 zh-Hans，它对拉丁字母同样有效
    try:
        langs = [lang.language_tag for lang in OcrEngine.available_recognizer_languages]
    except Exception:
        langs = []
    for tag in ("en-US", "en-GB", "zh-Hans-CN", "zh-Hans"):
        if tag in langs:
            from winrt.windows.globalization import Language

            engine = OcrEngine.try_create_from_language(Language(tag))
            if engine is not None:
                return engine
    engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise OcrError("系统没有可用的 OCR 语言包")
    return engine


async def _win_recognize_async(png_bytes: bytes):
    from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapDecoder, BitmapPixelFormat
    from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async(
        BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED
    )
    return await _ENGINE.recognize_async(bitmap)


def _windows_lines(bgr: np.ndarray) -> list[TextLine]:
    import io

    from PIL import Image

    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    buf = io.BytesIO()
    Image.fromarray(rgb).save(buf, format="PNG")

    result = _win_call(buf.getvalue())
    lines: list[TextLine] = []
    for ln in result.lines:
        text = (ln.text or "").strip()
        if not text:
            continue
        words = list(ln.words or [])
        if words:
            x0 = min(int(w.bounding_rect.x) for w in words)
            y0 = min(int(w.bounding_rect.y) for w in words)
            x1 = max(int(w.bounding_rect.x + w.bounding_rect.width) for w in words)
            y1 = max(int(w.bounding_rect.y + w.bounding_rect.height) for w in words)
            box = (x0, y0, max(1, x1 - x0), max(1, y1 - y0))
        else:
            box = (0, 0, bgr.shape[1], max(1, bgr.shape[0] // max(1, len(result.lines))))
        lines.append(TextLine(text=text, box=box, conf=1.0))
    return lines


def _win_worker() -> None:
    """常驻工作线程：MTA + 自己的事件循环，串行处理 OCR 请求。"""
    import asyncio
    import ctypes

    global _ENGINE
    try:
        # COINIT_MULTITHREADED = 0x0；多线程套间不需要消息泵，WinRT 异步可以正常完成
        ctypes.windll.ole32.CoInitializeEx(None, 0x0)
    except Exception:
        pass

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    while True:
        item = _WIN_QUEUE.get()
        if item is None:
            break
        png_bytes, slot = item
        try:
            if _ENGINE is None:
                _ENGINE = _make_windows_engine()
            slot["result"] = loop.run_until_complete(_win_recognize_async(png_bytes))
        except Exception as exc:  # noqa: BLE001
            slot["error"] = exc
        finally:
            slot["event"].set()


def _win_call(png_bytes: bytes, timeout: float = 12.0):
    import queue

    global _WIN_QUEUE, _WIN_THREAD, _ENGINE
    with _LOCK:
        if _WIN_QUEUE is None:
            _WIN_QUEUE = queue.Queue()
        if _WIN_THREAD is None or not _WIN_THREAD.is_alive():
            log.info("启动 Windows OCR 工作线程")
            _ENGINE = None
            _WIN_THREAD = threading.Thread(target=_win_worker, name="win-ocr", daemon=True)
            _WIN_THREAD.start()

    slot = {"event": threading.Event(), "result": None, "error": None}
    log.info("OCR 请求入队，%d 字节", len(png_bytes))
    _WIN_QUEUE.put((png_bytes, slot))
    if not slot["event"].wait(timeout):
        log.error("Windows OCR 超时（%.0f 秒未返回）", timeout)
        raise OcrError(f"Windows OCR 超时（{timeout:.0f} 秒未返回）")
    if slot["error"] is not None:
        log.error("Windows OCR 报错: %r", slot["error"])
        raise slot["error"]
    log.info("OCR 返回 %d 行", len(getattr(slot["result"], "lines", []) or []))
    return slot["result"]


# ============================ RapidOCR ============================
def _create_rapidocr():
    errors: list[str] = []
    try:
        from rapidocr import RapidOCR  # 3.x 新版

        return ("rapidocr", RapidOCR())
    except Exception as exc:  # noqa: BLE001
        errors.append(f"rapidocr: {exc}")
    try:
        from rapidocr_onnxruntime import RapidOCR  # 旧版

        return ("rapidocr_onnxruntime", RapidOCR())
    except Exception as exc:  # noqa: BLE001
        errors.append(f"rapidocr_onnxruntime: {exc}")
    raise OcrError("OCR 引擎加载失败：" + " | ".join(errors))


def _rapidocr_lines(raw, flavor: str) -> list[TextLine]:
    out: list[TextLine] = []
    if flavor == "rapidocr_onnxruntime":
        if not raw:
            return []
        res = raw[0] if isinstance(raw, tuple) else raw
        if not res:
            return []
        for item in res:
            try:
                box, text, score = item[0], item[1], item[2]
            except Exception:
                continue
            line = _to_line(box, text, score)
            if line:
                out.append(line)
        return out

    boxes = getattr(raw, "boxes", None)
    txts = getattr(raw, "txts", None)
    scores = getattr(raw, "scores", None)
    if boxes is not None and txts is not None:
        for i, box in enumerate(boxes):
            text = txts[i] if i < len(txts) else ""
            score = float(scores[i]) if (scores is not None and i < len(scores)) else 1.0
            line = _to_line(box, text, score)
            if line:
                out.append(line)
        return out
    if isinstance(raw, (list, tuple)):
        return _rapidocr_lines((raw, None), "rapidocr_onnxruntime")
    return []


def _to_line(box, text: str, score) -> TextLine | None:
    text = (text or "").strip()
    if not text:
        return None
    try:
        pts = np.array(box, dtype=float).reshape(-1, 2)
        x0, y0 = int(pts[:, 0].min()), int(pts[:, 1].min())
        x1, y1 = int(pts[:, 0].max()), int(pts[:, 1].max())
    except Exception:
        return None
    try:
        conf = float(score)
    except Exception:
        conf = 1.0
    return TextLine(text=text, box=(x0, y0, max(1, x1 - x0), max(1, y1 - y0)), conf=conf)


# ============================ 门面 ============================
def get_backend() -> str:
    """返回当前实际使用的后端：windows / rapidocr / none。"""
    global _ENGINE_KIND
    with _LOCK:
        if _ENGINE_KIND != "none":
            return _ENGINE_KIND

        want = str(CFG.get("ocr.backend", "auto"))
        if want in ("auto", "windows") and _windows_available():
            # 真正验证一次：能建出引擎才算可用
            try:
                _win_call(_probe_png())
                _ENGINE_KIND = "windows"
                return _ENGINE_KIND
            except Exception:
                if want == "windows":
                    raise

        # 兜底 RapidOCR
        flavor, engine = _create_rapidocr()
        globals()["_RAPID_ENGINE"] = (flavor, engine)
        _ENGINE_KIND = "rapidocr_onnxruntime"
        return _ENGINE_KIND


def _probe_png() -> bytes:
    """造一张带英文字的小图，用来验证 OCR 后端真的能出结果。"""
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (200, 40), "white")
    ImageDraw.Draw(img).text((8, 10), "Hello world", fill="black")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def recognize(bgr: np.ndarray) -> list[TextLine]:
    """bgr: OpenCV 风格的 BGR ndarray。返回按阅读顺序的文本行。"""
    if bgr is None or getattr(bgr, "size", 0) == 0:
        return []
    kind = get_backend()
    if kind == "windows":
        return _windows_lines(bgr)

    flavor, engine = globals().get("_RAPID_ENGINE", ("rapidocr_onnxruntime", None))
    if engine is None:
        return []
    raw = engine(bgr)
    lines = _rapidocr_lines(raw, flavor)
    return [ln for ln in lines if ln.conf >= 0.45]


def is_available() -> bool:
    try:
        get_backend()
        return True
    except Exception:
        return False


def backend_label() -> str:
    kind = get_backend() if is_available() else "none"
    return {
        "windows": "Windows 系统 OCR",
        "rapidocr_onnxruntime": "RapidOCR (ONNX)",
        "none": "不可用",
    }.get(kind, kind)
