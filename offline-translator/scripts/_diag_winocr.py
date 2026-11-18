"""测 Windows 自带 OCR（zh-Hans 引擎）对英文的识别速度与空格保留情况。"""
import asyncio
import io
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream


def make_img(w, h, lines, size=20, leading=1.9):
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size)
    for i, t in enumerate(lines):
        d.text((20, int(14 + i * size * leading)), t, fill="black", font=f)
    return img


async def to_bitmap(img: Image.Image):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(buf.getvalue())
    await writer.store_async()
    await writer.flush_async()
    writer.detach_stream()
    stream.seek(0)
    decoder = await BitmapDecoder.create_async(stream)
    return await decoder.get_software_bitmap_async(
        BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED
    )


async def main():
    eng = OcrEngine.try_create_from_language(Language("zh-Hans-CN"))
    if eng is None:
        eng = OcrEngine.try_create_from_user_profile_languages()
    print("engine:", eng, "lang:", eng.recognizer_language.language_tag if eng else None)

    cases = {
        "single 640x90": make_img(640, 90, ["Offline translation works without any internet."]),
        "para 900x220": make_img(900, 220, [
            "Machine translation systems have improved a lot",
            "over the past few years, and small offline models",
            "are now good enough for everyday reading.",
        ]),
        "web 1200x300": make_img(1200, 300, [
            "The report highlights three key findings from the survey.",
            "First, most users prefer reading English content directly.",
            "Second, translation quality matters more than speed.",
        ], 18),
        "mixed 800x120": make_img(800, 120, [
            "Hello 世界, this is a test 测试 line.",
        ], 20),
    }

    for name, img in cases.items():
        bmp = await to_bitmap(img)
        times = []
        result = None
        for _ in range(3):
            t0 = time.perf_counter()
            result = await eng.recognize_async(bmp)
            times.append(int((time.perf_counter() - t0) * 1000))
        print(f"\n--- {name} --- {times}ms 行数={len(result.lines)}")
        for ln in result.lines:
            rect = ln.words[0].bounding_rect if ln.words else None
            print(f"   {ln.text!r}  词数={len(ln.words)}")


asyncio.run(main())
