# -*- coding: utf-8 -*-
"""生成多尺寸应用图标（16~256），供桌面快捷方式使用，保证小尺寸下依然清晰。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image

from doubao_orb import _orb_rgba

HERE = os.path.dirname(os.path.abspath(__file__))
SIZES = [(16, 16), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)]

base = _orb_rgba(256)                      # 1024x1024 超采样，抗锯齿更干净
master = base.resize((256, 256), Image.LANCZOS)

ico = os.path.join(HERE, "豆包截图挂件.ico")
master.save(ico, format="ICO", sizes=SIZES)

# 顺带存一张 PNG 预览，方便肉眼检查
master.save(os.path.join(HERE, "图标预览.png"))
print("ico:", ico, os.path.getsize(ico), "bytes")
