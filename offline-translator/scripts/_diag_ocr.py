import time, numpy as np
from PIL import Image, ImageDraw, ImageFont
import cv2
print("cv2:", cv2.__version__)
font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 20)
img = Image.new("RGB",(640,80),"white"); d=ImageDraw.Draw(img)
d.text((20,26),"Offline translation works without any internet.",fill="black",font=font)
bgr = np.ascontiguousarray(np.array(img)[:,:,::-1])
from rapidocr_onnxruntime import RapidOCR
import inspect
print("init sig:", inspect.signature(RapidOCR.__init__))
t0=time.perf_counter(); eng = RapidOCR(); print("load", int((time.perf_counter()-t0)*1000),"ms")
for i in range(3):
    t0=time.perf_counter(); out = eng(bgr); ms=int((time.perf_counter()-t0)*1000)
    print(f"run{i+1}: {ms}ms  elapse={out[1] if isinstance(out,tuple) else 'n/a'}")
print("default config:")
try:
    from rapidocr_onnxruntime import config as cfgs
    print(cfgs.DEFAULT_CFG if hasattr(cfgs,'DEFAULT_CFG') else dir(cfgs)[:20])
except Exception as e:
    print("cfg err", e)
