import time
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from rapidocr_onnxruntime import RapidOCR


def make_img(w, h, lines, size=20, leading=1.9):
    img = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size)
    for i, t in enumerate(lines):
        d.text((20, int(14 + i * size * leading)), t, fill="black", font=f)
    return np.ascontiguousarray(np.array(img)[:, :, ::-1])


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
}

cfgs = {
    "default(min736,global忽略)": dict(),
    "det_max960": dict(det_limit_side_len=960, det_limit_type="max"),
    "det_max1280": dict(det_limit_side_len=1280, det_limit_type="max"),
    "det_max1280+nocls": dict(det_limit_side_len=1280, det_limit_type="max", use_angle_cls=False),
}

for name, cfg in cfgs.items():
    eng = RapidOCR(**cfg)
    print(f"--- {name} ---")
    for cname, img in cases.items():
        times = []
        out = None
        for _ in range(2):
            t0 = time.perf_counter()
            out = eng(img)
            times.append(int((time.perf_counter() - t0) * 1000))
        res = out[0] if isinstance(out, tuple) else out
        print(f"   {cname}: {times}ms 行数={len(res or [])}")
        for r in (res or []):
            print(f"       {r[1]!r}")
