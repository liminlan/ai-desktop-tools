import time, numpy as np, cv2
from PIL import Image, ImageDraw, ImageFont
from rapidocr_onnxruntime import RapidOCR

def make_img(w, h, lines, size=20):
    img = Image.new("RGB",(w,h),"white"); d=ImageDraw.Draw(img)
    f = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", size)
    for i,t in enumerate(lines):
        d.text((18, 12+i*(size+12)), t, fill="black", font=f)
    return np.ascontiguousarray(np.array(img)[:,:,::-1])

# 两个典型场景：小条选区 640x80（单行），网页段落 900x200（3行）
cases = {
 "single 640x80": make_img(640,80,["Offline translation works without any internet."],20),
 "para 900x200": make_img(900,200,["Machine translation systems have improved a lot over the past few years,","and small offline models are now good enough for everyday reading.","This means you can read English pages without a network."],16),
}

configs = {
 "A: min 736 (默认)": dict(limit_side_len=736, limit_type="min"),
 "B: max 960":        dict(limit_side_len=960, limit_type="max"),
 "C: max 1280":       dict(limit_side_len=1280, limit_type="max"),
 "D: max 1280 +关角度分类": dict(limit_side_len=1280, limit_type="max", use_angle_cls=False),
}

for name, cfg in configs.items():
    try:
        eng = RapidOCR(**cfg)
    except Exception as e:
        print(f"{name}: 构造失败 {e}"); continue
    print(f"--- {name} ---")
    for cname, img in cases.items():
        t0=time.perf_counter(); out = eng(img); ms=int((time.perf_counter()-t0)*1000)
        res = out[0] if isinstance(out,tuple) else out
        n = len(res) if res else 0
        txt = " | ".join(r[1] for r in (res or []))[:80]
        print(f"   {cname}: {ms}ms 行数={n}")
        print(f"       {txt}")
