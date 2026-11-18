"""诊断：QApplication 存在时，Windows OCR 是否会卡住。"""
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

app = QApplication(sys.argv)

from offline_translator.services import ocr_engine

crop = Path(__file__).resolve().parent / "_preview_crop.png"
print("crop exists:", crop.exists())


def job():
    from PIL import Image
    import numpy as np

    img = Image.open(crop).convert("RGB")
    bgr = np.ascontiguousarray(np.array(img)[:, :, ::-1])
    print("backend:", ocr_engine.get_backend(), flush=True)
    t0 = time.perf_counter()
    lines = ocr_engine.recognize(bgr)
    print(f"main-thread OCR: {int((time.perf_counter()-t0)*1000)}ms lines={len(lines)}", flush=True)
    for ln in lines:
        print("   ", ln.box, ln.text, flush=True)


t = threading.Timer(8.0, lambda: (print("!! 8 秒没返回，判定为卡死", flush=True), __import__("os")._exit(3)))
t.daemon = True
t.start()
job()
t.cancel()
print("done", flush=True)
