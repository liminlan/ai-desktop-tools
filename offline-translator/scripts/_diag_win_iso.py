"""对照实验：找出 WinRT OCR 在哪种环境下会卡。"""
import asyncio
import ctypes
import sys
import threading
import time

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapDecoder, BitmapPixelFormat
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

from pathlib import Path

PNG = (Path(__file__).resolve().parent / "_preview_crop.png").read_bytes()


def make_engine():
    return OcrEngine.try_create_from_language(Language("zh-Hans-CN")) or OcrEngine.try_create_from_user_profile_languages()


async def ocr(png):
    stream = InMemoryRandomAccessStream()
    w = DataWriter(stream)
    w.write_bytes(png)
    await w.store_async()
    await w.flush_async()
    w.detach_stream()
    stream.seek(0)
    dec = await BitmapDecoder.create_async(stream)
    bmp = await dec.get_software_bitmap_async(BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED)
    eng = make_engine()
    return await eng.recognize_async(bmp)


def run_in_thread(apartment: str):
    out = {}

    def worker():
        if apartment == "mta":
            ctypes.windll.ole32.CoInitializeEx(None, 0x0)
        elif apartment == "sta":
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            t0 = time.perf_counter()
            res = loop.run_until_complete(ocr(PNG))
            out["ms"] = int((time.perf_counter() - t0) * 1000)
            out["lines"] = len(res.lines)
            out["text"] = res.lines[0].text if res.lines else ""
        except Exception as exc:
            out["error"] = repr(exc)

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    t.join(10)
    return out if out else {"hang": True}


def scenario(name, use_qt):
    app = None
    if use_qt:
        from PySide6.QtWidgets import QApplication
        app = QApplication(sys.argv)
    print(f"--- {name} ---")
    if use_qt:
        for ap in ("mta", "sta"):
            print(f"   子线程{ap}:", run_in_thread(ap))
        print("   (主线程调用跳过，已知会卡)")
    else:
        out = {}
        try:
            t0 = time.perf_counter()
            res = asyncio.run(ocr(PNG))
            out["ms"] = int((time.perf_counter() - t0) * 1000)
            out["lines"] = len(res.lines)
            out["text"] = res.lines[0].text if res.lines else ""
        except Exception as exc:
            out["error"] = repr(exc)
        print("   主线程:", out)
    del app


if __name__ == "__main__":
    scenario("无 Qt", use_qt=False)
    scenario("有 Qt", use_qt=True)
