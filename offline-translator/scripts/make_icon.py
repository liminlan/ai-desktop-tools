"""生成桌面快捷方式用的图标：米黄圆底 + 深绿描边 + "译" 字，和悬浮球同一套配色。"""
from __future__ import annotations

import os
import sys

from PIL import Image, ImageDraw, ImageFont

MILK = (251, 247, 234, 255)
GREEN_DEEP = (47, 93, 80, 255)
TEXT = (36, 56, 47, 255)
DOT = (110, 154, 120, 255)

OUT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def render(size: int) -> Image.Image:
    scale = 4  # 先画 4 倍再缩小，边缘干净
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = int(s * 0.06)
    ring = max(2, int(s * 0.018))
    d.ellipse([pad, pad, s - pad, s - pad], fill=MILK, outline=GREEN_DEEP, width=ring)

    # 顶部小绿点，呼应悬浮球
    r = int(s * 0.055)
    cx = s // 2
    cy = int(s * 0.205)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=DOT)

    # "译" 字
    font_size = int(s * 0.5)
    font = None
    for cand in (r"C:\Windows\Fonts\msyhbd.ttc", r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(cand):
            try:
                font = ImageFont.truetype(cand, font_size)
                break
            except OSError:
                continue
    if font is None:
        font = ImageFont.load_default()

    text = "译"
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    d.text((cx - tw / 2 - box[0], int(s * 0.5) - th / 2 - box[1]), text, font=font, fill=TEXT)

    return img.resize((size, size), Image.LANCZOS)


def main() -> int:
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    big = render(256)
    out = os.path.join(OUT_DIR, "app_icon.ico")
    big.save(out, format="ICO", sizes=sizes)
    print("icon:", out, os.path.getsize(out), "bytes")
    png = os.path.join(OUT_DIR, "app_icon.png")
    big.save(png, format="PNG")
    print("png:", png)
    return 0


if __name__ == "__main__":
    sys.exit(main())
