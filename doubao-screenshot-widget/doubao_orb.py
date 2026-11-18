# -*- coding: utf-8 -*-
"""
豆包截图挂件 —— 圆形桌面悬浮窗，点一下就能截图问 AI。

流程：单击圆球 -> 屏幕变暗 -> 拖框选区 -> 自动上传给免费视觉模型 -> 圆球上方弹出答案气泡（可继续追问）。

依赖：仅 Python 标准库 + Pillow。
"""

import base64
import ctypes
import io
import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.error
import urllib.request

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageGrab, ImageTk

# ---------------------------------------------------------------- 常量

APP_TITLE = "豆包截图挂件"
API_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
MODELS = [
    ("glm-4.6v-flash", "GLM-4.6V-Flash（官方免费，推荐）"),
    ("glm-4v-flash", "GLM-4V-Flash（官方免费，老模型）"),
    ("glm-4.6v", "GLM-4.6V（收费，更强）"),
]
DEFAULT_PROMPT = (
    "我在电脑屏幕上框选截了一张图。请按下面要求回答：\n"
    "1. 先用一句话说清这是什么界面/这是什么东西；\n"
    "2. 如果我在问怎么操作，就给出具体的点击顺序或步骤；\n"
    "3. 用简体中文，分点、简短，不要客套话，不要重复我的问题。"
)
DEFAULT_MODEL = "glm-4.6v-flash"

TRANS = "#ff00ff"
TRANS_RGB = (255, 0, 255)

# ---------------------------------------------------------------- 窗口形状
# tkinter 的 -transparentcolor 在这台机器上不生效，圆球四角会残留洋红。
# 改用系统 SetWindowRgn 把窗口裁成真实形状：圆形窗口四角本来就不存在，
# 贴边收起时还能精确控制只露出半个圆。
_RGN_AND = 1   # GDI 常量：RGN_AND=1、RGN_OR=2、RGN_XOR=3、RGN_DIFF=4、RGN_COPY=5


def _hwnd_of(win):
    try:
        u = ctypes.windll.user32
        u.GetParent.restype = ctypes.c_void_p
        u.GetParent.argtypes = [ctypes.c_void_p]
        hwnd = int(win.winfo_id())
        parent = u.GetParent(ctypes.c_void_p(hwnd))
        return parent or hwnd
    except Exception:
        return 0


def send_win_h():
    """模拟按下 Win+H，唤起 Windows 自带听写（语音转文字）。"""
    try:
        u = ctypes.windll.user32
        VK_LWIN, VK_H, KEYUP = 0x5B, 0x48, 2
        u.keybd_event(VK_LWIN, 0, 0, 0)
        u.keybd_event(VK_H, 0, 0, 0)
        u.keybd_event(VK_H, 0, KEYUP, 0)
        u.keybd_event(VK_LWIN, 0, KEYUP, 0)
        return True
    except Exception:
        return False


def set_window_region(win, w, h, shape="ellipse", radius=0, part=None, inset=0):
    """把窗口裁成真实形状。shape: ellipse / round；part: None / left / right。

    inset 让裁剪边界比图片里的图形略向内收，用来吃掉抗锯齿残留的洋红像素。
    """
    try:
        u = ctypes.windll.user32
        g = ctypes.windll.gdi32
        g.CreateEllipticRgn.restype = ctypes.c_void_p
        g.CreateEllipticRgn.argtypes = [ctypes.c_int] * 4
        g.CreateRoundRectRgn.restype = ctypes.c_void_p
        g.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        g.CreateRectRgn.restype = ctypes.c_void_p
        g.CreateRectRgn.argtypes = [ctypes.c_int] * 4
        g.CombineRgn.restype = ctypes.c_int
        g.CombineRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p,
                                 ctypes.c_void_p, ctypes.c_int]
        g.DeleteObject.argtypes = [ctypes.c_void_p]
        u.SetWindowRgn.restype = ctypes.c_int
        u.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_bool]

        hwnd = _hwnd_of(win)
        if not hwnd:
            return
        w1, h1 = int(w) + 1, int(h) + 1
        ix = max(0, int(inset))
        if shape == "ellipse":
            base = g.CreateEllipticRgn(ix, ix, w1 - ix, h1 - ix)
        else:
            r = max(2, int(radius) * 2)
            base = g.CreateRoundRectRgn(ix, ix, w1 - ix, h1 - ix, r, r)
        if not base:
            return
        if part in ("left", "right"):
            if part == "left":
                clip = g.CreateRectRgn(0, 0, int(w) // 2, h1)
            else:
                clip = g.CreateRectRgn(int(w) // 2, 0, w1, h1)
            rgn = g.CreateRectRgn(0, 0, 0, 0)
            g.CombineRgn(rgn, base, clip, _RGN_AND)
            g.DeleteObject(clip)
            g.DeleteObject(base)
        else:
            rgn = base
        u.SetWindowRgn(ctypes.c_void_p(hwnd), rgn, True)
    except Exception:
        pass

if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

ORB_SIZE = 76          # 圆球逻辑尺寸
MAX_IMG_EDGE = 1400    # 上传前压缩的最长边
JPEG_QUALITY = 85


# ---------------------------------------------------------------- 系统相关

def enable_dpi_awareness():
    """让 tkinter 坐标、截图坐标、屏幕坐标统一为物理像素，避免高 DPI 下框选错位。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def virtual_screen():
    """返回整个虚拟桌面 (x, y, w, h)，支持多屏和负坐标。"""
    u = ctypes.windll.user32
    x = u.GetSystemMetrics(76)
    y = u.GetSystemMetrics(77)
    w = u.GetSystemMetrics(78)
    h = u.GetSystemMetrics(79)
    if w <= 0 or h <= 0:
        x, y = 0, 0
        w = u.GetSystemMetrics(0)
        h = u.GetSystemMetrics(1)
    return x, y, w, h


def grab_screen():
    x, y, w, h = virtual_screen()
    img = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
    return img.convert("RGB"), (x, y)


def pick_font(root, candidates, size, weight="normal"):
    fams = set(tkfont.families(root))
    for c in candidates:
        if c in fams:
            return (c, size, weight)
    return ("TkDefaultFont", size, weight)


# ---------------------------------------------------------------- 配置

def load_config():
    cfg = {"api_key": "", "model": DEFAULT_MODEL, "prompt": DEFAULT_PROMPT,
           "orb_pos": None, "orb_side": None}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k in cfg:
            if k in data:
                cfg[k] = data[k]
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------------------------------------------------------- 图像绘制

def lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def _rounded_card(w, h, radius, fill=(255, 255, 255), border=(214, 222, 238)):
    """4 倍超采样画圆角卡片，再缩回来，边缘平滑。"""
    s = 4
    img = Image.new("RGB", (w * s, h * s), TRANS_RGB)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [0, 0, w * s - 1, h * s - 1], radius=radius * s, fill=fill, outline=border, width=s
    )
    return img.resize((w, h), Image.LANCZOS)


def _cover_crop(img, w, h):
    """把图片等比放大后居中裁切成 w×h，用作卡片里的缩略图。"""
    ratio = max(w / float(img.width), h / float(img.height))
    nw, nh = max(w, int(img.width * ratio)), max(h, int(img.height * ratio))
    im = img.convert("RGB").resize((nw, nh), Image.LANCZOS)
    left, top = (nw - w) // 2, (nh - h) // 2
    return im.crop((left, top, left + w, top + h))


def _orb_rgba(size, scale=4):
    px = size * scale
    R = px // 2
    base = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    d = ImageDraw.Draw(base)
    center = (128, 112, 255)
    edge = (58, 76, 224)
    for r in range(R, 0, -1):
        t = r / R
        d.ellipse([R - r, R - r, R + r - 1, R + r - 1], fill=lerp(center, edge, t * 0.95))

    # 左上高光
    hi = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    hd = ImageDraw.Draw(hi)
    hd.ellipse([int(px * 0.16), int(px * 0.10), int(px * 0.66), int(px * 0.52)],
               fill=(255, 255, 255, 62))
    hi = hi.filter(ImageFilter.GaussianBlur(px // 14))
    base = Image.alpha_composite(base, hi)

    # 白色对话气泡符号
    sym = Image.new("RGBA", (px, px), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sym)
    l, r_ = int(px * 0.24), int(px * 0.76)
    t_, b_ = int(px * 0.26), int(px * 0.62)
    sd.rounded_rectangle([l, t_, r_, b_], radius=int(px * 0.10),
                         outline=(255, 255, 255, 255), width=max(2, int(px * 0.048)))
    # 气泡尾巴
    sd.polygon([(int(px * 0.36), b_ - 1), (int(px * 0.36), int(px * 0.74)),
                (int(px * 0.50), b_ - 1)], fill=(255, 255, 255, 255))
    # 三点
    cy = (t_ + b_) // 2
    for i, cx in enumerate([int(px * 0.37), int(px * 0.50), int(px * 0.63)]):
        rr = int(px * 0.030)
        sd.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(255, 255, 255, 255))
    base = Image.alpha_composite(base, sym)

    # 圆形裁切
    mask = Image.new("L", (px, px), 0)
    ImageDraw.Draw(mask).ellipse([1, 1, px - 2, px - 2], fill=255)
    base.putalpha(ImageChops.multiply(base.getchannel("A"), mask))
    return base


def orb_images(size, frames=12):
    """返回 idle 图 + 12 帧忙碌图（RGB，洋红底）。"""
    px_size = size * 4
    base = _orb_rgba(size)
    out = []

    def flatten(im):
        bg = Image.new("RGB", im.size, TRANS_RGB)
        bg.paste(im, (0, 0), im)
        return bg.resize((size, size), Image.LANCZOS)

    out.append(flatten(base))
    big = base.resize((px_size, px_size), Image.LANCZOS)
    for i in range(frames):
        f = big.copy()
        d = ImageDraw.Draw(f)
        ang = i * (360 / frames)
        rr = px_size // 2 - int(px_size * 0.045)
        d.arc([px_size // 2 - rr, px_size // 2 - rr, px_size // 2 + rr, px_size // 2 + rr],
              ang, ang + 78, fill=(255, 255, 255, 235), width=int(px_size * 0.040))
        out.append(flatten(f))
    return out


# ---------------------------------------------------------------- API

def clean_md(s):
    for a, b in [("**", ""), ("###", ""), ("##", ""), ("# ", ""), ("`", "")]:
        s = s.replace(a, b)
    return s.strip()


def encode_image(img):
    img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > MAX_IMG_EDGE:
        k = MAX_IMG_EDGE / max(w, h)
        img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def call_api(api_key, model, messages, timeout=120):
    payload = json.dumps({"model": model, "messages": messages, "temperature": 0.6,
                          "stream": False}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        API_URL, data=payload,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + api_key.strip()},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "ignore")
            msg = json.loads(body).get("error", {}).get("message") or body[:300]
        except Exception:
            msg = str(e)
        if e.code == 401:
            raise RuntimeError("API Key 无效或已过期，请在设置里重新填写。")
        if e.code == 429:
            raise RuntimeError("请求太频繁了，等几秒再试。")
        raise RuntimeError("接口返回错误(%s)：%s" % (e.code, msg))
    except urllib.error.URLError as e:
        raise RuntimeError("网络连不上：%s（检查网络或代理）" % e.reason)


# ---------------------------------------------------------------- 圆形悬浮窗

class FloatingOrb:
    def __init__(self, app):
        self.app = app
        self.size = ORB_SIZE
        self.frames = orb_images(self.size)
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TRANS)
        # 不用 -transparentcolor：分层窗口会让 SetWindowRgn 失效、四角露出洋红，
        # 形状统一交给 set_window_region 处理。
        self.label = tk.Label(self.win, bg=TRANS, bd=0, highlightthickness=0, cursor="hand2")
        self.label.pack()
        self.photos = [ImageTk.PhotoImage(f) for f in self.frames]
        self.label.configure(image=self.photos[0])

        self.screen_w = self.win.winfo_screenwidth()
        self.screen_h = self.win.winfo_screenheight()
        self.SLIVER = self.size // 2     # 收起时露在屏幕内的宽度，正好一半
        self.GAP = 6                     # 展开时离屏幕边缘的缝隙

        pos = app.cfg.get("orb_pos")
        if not (isinstance(pos, list) and len(pos) == 2):
            pos = [self.screen_w - self.size - 40, self.screen_h - self.size - 120]
        self.pos = [int(pos[0]), int(pos[1])]
        side = app.cfg.get("orb_side")
        self.side = side if side in ("left", "right") else self._nearest_side(self.pos[0])

        self._press = None
        self._drag_start = None
        self._moved = False
        self.busy = False
        self._anim = 0
        self._after = None
        self._anim_job = None
        self._collapse_job = None
        self.collapsed = True
        cx, cy = self._pos_collapsed()
        self.win.geometry("%dx%d+%d+%d" % (self.size, self.size, int(cx), int(cy)))
        self.win.update_idletasks()
        self._apply_shape(part=self._collapse_part())
        self.win.after(60, self._ensure_shape)

        for w in (self.win, self.label):
            w.bind("<ButtonPress-1>", self._on_press)
            w.bind("<B1-Motion>", self._on_drag)
            w.bind("<ButtonRelease-1>", self._on_release)
            w.bind("<Button-3>", self._on_menu)
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

        self.menu = tk.Menu(self.win, tearoff=0, font=app.font_ui)
        self.menu.add_command(label="截图提问  (Ctrl+Alt+Q)", command=self.app.start_capture)
        self.menu.add_command(label="重新看上次的截图", command=self.app.reopen_last)
        self.menu.add_separator()
        self.menu.add_command(label="设置  (API Key / 模型)", command=self.app.open_settings)
        self.menu.add_command(label="使用说明", command=self.app.show_help)
        self.menu.add_separator()
        self.menu.add_command(label="退出", command=self.app.quit)

    def _move(self, x=None, y=None):
        x = self.pos[0] if x is None else x
        y = self.pos[1] if y is None else y
        self.win.geometry("%dx%d+%d+%d" % (self.size, self.size, int(x), int(y)))

    # ---------- 贴边吸附 / 收起展开

    def _nearest_side(self, x):
        return "left" if x + self.size / 2 <= self.screen_w / 2 else "right"

    def _pos_collapsed(self):
        if self.side == "left":
            return 0, self.pos[1]
        return self.screen_w - self.SLIVER, self.pos[1]

    def _pos_expanded(self):
        if self.side == "left":
            return self.GAP, self.pos[1]
        return self.screen_w - self.size - self.GAP, self.pos[1]

    def _collapse_part(self):
        # 贴右边缘时露出圆的左半，贴左边缘时露出右半
        return "left" if self.side == "right" else "right"

    def _apply_shape(self, part=None):
        set_window_region(self.win, self.size, self.size, "ellipse", part=part, inset=1)

    def _ensure_shape(self):
        """窗口真正 map 出来之后再设一次形状（map 之前设的会被系统丢掉）。"""
        try:
            if not self.win.winfo_exists():
                return
            self._apply_shape(self._collapse_part() if self.collapsed else None)
        except Exception:
            pass

    def _clamp_y(self, y):
        return max(0, min(int(y), self.screen_h - self.size))

    def _animate_to(self, tx, ty):
        if self._anim_job:
            try:
                self.win.after_cancel(self._anim_job)
            except Exception:
                pass
            self._anim_job = None
        size = self.size

        def tick():
            cx, cy = self.win.winfo_x(), self.win.winfo_y()
            dx, dy = tx - cx, ty - cy
            if abs(dx) <= 8 and abs(dy) <= 8:
                self.win.geometry("%dx%d+%d+%d" % (size, size, int(tx), int(ty)))
                self._anim_job = None
                return
            sx = 0 if abs(dx) <= 8 else (10 if dx > 0 else -10)
            sy = 0 if abs(dy) <= 8 else (10 if dy > 0 else -10)
            self.win.geometry("%dx%d+%d+%d" % (size, size, cx + sx, cy + sy))
            self._anim_job = self.win.after(14, tick)

        tick()

    def cancel_collapse(self):
        if self._collapse_job:
            try:
                self.win.after_cancel(self._collapse_job)
            except Exception:
                pass
            self._collapse_job = None

    def schedule_collapse(self, delay=1400):
        self.cancel_collapse()
        if self.busy or self.app.busy or self.app.overlay:
            return
        self._collapse_job = self.win.after(int(delay), self.collapse)

    def expand(self, animated=True):
        self.cancel_collapse()
        if not self.collapsed:
            return
        self.collapsed = False
        x, y = self._pos_expanded()
        self._apply_shape(None)
        self.win.geometry("%dx%d+%d+%d" % (self.size, self.size, int(x), int(y)))
        if not self.busy:
            try:
                self.label.configure(image=self.photos[0])
            except Exception:
                pass

    def collapse(self):
        self._collapse_job = None
        if self.collapsed:
            return
        if self._press or self.busy or self.app.busy or self.app.overlay:
            self.schedule_collapse(900)
            return
        self.collapsed = True
        x, y = self._pos_collapsed()
        self._apply_shape(self._collapse_part())
        self.win.geometry("%dx%d+%d+%d" % (self.size, self.size, int(x), int(y)))
        if not self.busy:
            try:
                self.label.configure(image=self.photos[0])
            except Exception:
                pass

    def _on_enter(self, e):
        self.expand()

    def _on_leave(self, e):
        if self._press is not None:
            return
        self.schedule_collapse(1200)

    # ---------- 鼠标事件

    def _on_press(self, e):
        self.cancel_collapse()
        if self.collapsed:
            # 收起状态下按下，先瞬间展开成整圆，再开始记录拖动
            self.expand(animated=False)
        self._press = (e.x_root, e.y_root, time.time())
        self._drag_start = (self.win.winfo_x(), self.win.winfo_y(), e.x_root, e.y_root)
        self._moved = False

    def _on_drag(self, e):
        if not self._drag_start:
            return
        sx, sy, ex, ey = self._drag_start
        dx, dy = e.x_root - ex, e.y_root - ey
        if abs(dx) > 2 or abs(dy) > 2:
            self._moved = True
        self._move(sx + dx, self._clamp_y(sy + dy))

    def _on_release(self, e):
        if not self._press:
            return
        dt = time.time() - self._press[2]
        self._press = None
        if self._moved:
            # 拖到哪一侧，就吸附到哪一侧，纵向位置保留
            cx = self.win.winfo_x()
            self.side = self._nearest_side(cx)
            self.pos = [self._pos_expanded()[0], self._clamp_y(self.win.winfo_y())]
            self.collapsed = False
            self._move(self.pos[0], self.pos[1])
            self.app.cfg["orb_pos"] = self.pos
            self.app.cfg["orb_side"] = self.side
            save_config(self.app.cfg)
            self.schedule_collapse(1600)
            return
        if dt < 0.9:
            self.app.start_capture()
        else:
            self.schedule_collapse(900)

    def _on_menu(self, e):
        self.cancel_collapse()
        self.expand(animated=False)
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def hide(self):
        self.cancel_collapse()
        self.win.withdraw()

    def show(self):
        self.win.deiconify()
        self.win.attributes("-topmost", True)
        self.win.after(40, self._ensure_shape)
        self.schedule_collapse(1200)

    def set_busy(self, busy):
        self.busy = busy
        if busy:
            self.expand(animated=False)
            self._spin()
        else:
            if self._after:
                try:
                    self.win.after_cancel(self._after)
                except Exception:
                    pass
                self._after = None
            self.label.configure(image=self.photos[0])
            self.schedule_collapse(1500)

    def _spin(self):
        self._anim = (self._anim + 1) % len(self.photos)
        try:
            self.label.configure(image=self.photos[self._anim])
        except Exception:
            return
        self._after = self.win.after(90, self._spin)

    def geometry_for_bubble(self):
        return self.win.winfo_x(), self.win.winfo_y(), self.size


# ---------------------------------------------------------------- 截图遮罩层

class CaptureOverlay:
    def __init__(self, app, img, origin, on_done, on_cancel):
        self.app = app
        self.img = img
        self.origin = origin
        self.on_done = on_done
        self.on_cancel = on_cancel
        w, h = img.size

        self.dim = img.copy()
        self.dim = Image.eval(self.dim, lambda v: int(v * 0.92))
        overlay_layer = Image.new("RGB", (w, h), (12, 16, 32))
        self.dim = Image.blend(self.dim, overlay_layer, 0.55)

        self.top = tk.Toplevel(app.root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.geometry("%dx%d+%d+%d" % (w, h, origin[0], origin[1]))
        self.top.configure(bg="#000000", cursor="crosshair")

        self.photo = ImageTk.PhotoImage(self.dim)
        self.canvas = tk.Canvas(self.top, width=w, height=h, bd=0, highlightthickness=0,
                                cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")

        tip = "拖拽框选要问的区域    ·    Enter 截全屏    ·    Esc / 右键 取消"
        self.canvas.create_text(w // 2, 46, text=tip, fill="#FFFFFF",
                                font=(app.font_family, 13, "bold"))
        self.canvas.create_rectangle(w // 2 - 300, 26, w // 2 + 300, 66,
                                     outline="", fill="", width=0)

        self.start = None
        self.rect = None
        self.cur = None

        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Button-3>", lambda e: self._cancel())
        self.top.bind("<Escape>", lambda e: self._cancel())
        self.top.bind("<Return>", lambda e: self._full())
        self.top.focus_force()

    def _press(self, e):
        self.start = (e.x, e.y)
        if self.rect:
            self.canvas.delete(self.rect)
            self.canvas.delete("hud")
        self.rect = self.canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="#6E8BFF",
                                                 width=2, fill="")

    def _drag(self, e):
        if not self.start:
            return
        self.cur = (e.x, e.y)
        x1, y1 = self.start
        x2, y2 = self.cur
        self.canvas.coords(self.rect, x1, y1, x2, y2)
        self.canvas.delete("hud")
        wv, hv = abs(x2 - x1), abs(y2 - y1)
        tx, ty = min(x1, x2), min(y1, y2) - 22
        if ty < 12:
            ty = min(y1, y2) + hv + 14
        self.canvas.create_text(tx + 4, ty, text="%d × %d" % (wv, hv), anchor="w",
                                fill="#FFFFFF", font=(self.app.font_family, 10, "bold"), tags="hud")

    def _release(self, e):
        if not self.start or not self.cur:
            return
        x1, y1 = self.start
        x2, y2 = self.cur
        lx, ly = min(x1, x2), min(y1, y2)
        wv, hv = abs(x2 - x1), abs(y2 - y1)
        if wv < 10 or hv < 10:
            self.start = self.cur = None
            return
        self._finish((lx, ly, lx + wv, ly + hv))

    def _full(self):
        self._finish((0, 0, self.img.size[0], self.img.size[1]))

    def _finish(self, box):
        try:
            crop = self.img.crop(box)
        except Exception:
            crop = self.img
        self._close(False)
        self.on_done(crop)

    def _cancel(self):
        self._close(True)

    def _close(self, cancelled):
        try:
            self.top.destroy()
        except Exception:
            pass
        if cancelled:
            self.on_cancel()


# ---------------------------------------------------------------- 答案气泡

class Bubble:
    PAD = 14

    def __init__(self, app, anchor_geo):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=TRANS)
        # 不用 -transparentcolor：分层窗口会让 SetWindowRgn 失效、四角露出洋红，
        # 形状统一交给 set_window_region 处理。
        self.anchor = anchor_geo
        self.width = 420
        self.height = 240
        self.canvas = None
        self.card_png = None
        self.text = None
        self.status = None
        self.entry = None
        self.mic_btn = None
        self.close_btn = None
        self.thumb_photo = None
        self.thumb_h = 0
        self.body_top = 42
        self._status_text = ""
        self.btns = []
        self.save_btn = None
        self.send_btn = None
        self.job = None
        self._build(420, 240)

    # ---------- 布局

    def _build(self, w, h):
        self.win.geometry("%dx%d+%d+%d" % (w, h, 0, -1200))
        self.width, self.height = w, h
        self.win.update_idletasks()
        set_window_region(self.win, w, h, "round", radius=16)
        pad = self.PAD
        f = self.app.font_family
        self.card_png = ImageTk.PhotoImage(_rounded_card(w, h, 16))
        if self.canvas is None:
            self.canvas = tk.Canvas(self.win, width=w, height=h, bd=0,
                                    highlightthickness=0, bg=TRANS)
            self.canvas.place(x=0, y=0)
            self.bg_item = self.canvas.create_image(0, 0, image=self.card_png, anchor="nw")
        else:
            self.canvas.configure(width=w, height=h)
            self.canvas.itemconfigure(self.bg_item, image=self.card_png)
            self.canvas.delete("ui")
        self.canvas.create_text(pad + 2, pad + 2, text="AI 解读", anchor="nw",
                                fill="#5B6BE8", font=(f, 10, "bold"), tags="ui")

        # 截图缩略图：让你看得见到底截了什么，点它也能另存
        self.thumb_h = 0
        crop = getattr(self.app, "last_crop", None)
        if crop is not None:
            tw = w - pad * 2
            self.thumb_h = 52
            try:
                self.thumb_photo = ImageTk.PhotoImage(_cover_crop(crop, tw, self.thumb_h))
                self.canvas.create_image(pad, pad + 22, image=self.thumb_photo,
                                         anchor="nw", tags=("ui", "thumb"))
                self.canvas.create_rectangle(pad, pad + 22, pad + tw, pad + 22 + self.thumb_h,
                                             outline="#DCE3F0", width=1, tags=("ui", "thumb"))
                self.canvas.tag_bind("thumb", "<Button-1>", lambda e: self.save_image())
            except Exception:
                self.thumb_h = 0

        div_y = pad + 22 + self.thumb_h + (10 if self.thumb_h else 8)
        self.canvas.create_line(pad, div_y, w - pad, div_y, fill="#EDF0F5", tags="ui")
        self.body_top = div_y + 8
        self.canvas.create_line(pad, h - pad - 34, w - pad, h - pad - 34,
                                fill="#EDF0F5", tags="ui")
        self._place_children(w, h)
        for wgt in (self.text, self.status, self.entry, self.sb, self.mic_btn,
                    self.close_btn, self.save_btn, self.send_btn):
            try:
                wgt.lift()
            except Exception:
                pass

    def _place_children(self, w, h):
        pad = self.PAD
        f = self.app.font_family

        inner_w = w - pad * 2
        body_h = max(40, h - self.body_top - 50)
        if self.text is None:
            self.text = tk.Text(self.win, bg="white", bd=0, highlightthickness=0,
                                wrap="word", font=(f, 10), fg="#23262F",
                                padx=0, pady=0, spacing1=1, spacing3=4, cursor="arrow")
            self.sb = tk.Scrollbar(self.win, width=8)
        self.text.configure(state="normal")
        self.text.place(x=pad, y=self.body_top, width=inner_w, height=body_h)
        self.sb.place(x=w - pad - 9, y=self.body_top, height=body_h)
        self.sb.configure(command=self.text.yview)
        self.text.configure(yscrollcommand=self.sb.set)

        # 关闭按钮：用独立的控件，留足边距，不会被卡片圆角裁掉
        if self.close_btn is None:
            self.close_btn = tk.Label(self.win, text="×", bg="white", fg="#9AA3B2",
                                      font=(f, 13, "bold"), cursor="hand2")
            self.close_btn.bind("<Button-1>", lambda e: self.close())
            self.close_btn.bind("<Enter>",
                                lambda e: self.close_btn.configure(fg="#E0574C"))
            self.close_btn.bind("<Leave>",
                                lambda e: self.close_btn.configure(fg="#9AA3B2"))
        self.close_btn.place(x=w - pad - 30, y=pad - 6, width=24, height=24)

        # 状态文字挪到标题行，底部腾出位置放麦克风按钮
        by = h - pad - 26
        if self.status is None:
            self.status = tk.Label(self.win, text="", bg="white", fg="#8A93A5",
                                   font=(f, 9), anchor="e")
        self.status.place(x=pad + 60, y=pad - 2,
                          width=max(80, w - pad - 36 - (pad + 60)), height=22)

        # 麦克风：唤起系统听写，说出来的话直接变成输入框里的文字
        if self.mic_btn is None:
            self.mic_btn = tk.Label(self.win, text="麦", bg="#F4F6FA", fg="#5B6BE8",
                                    font=(f, 9, "bold"), cursor="hand2")
            self.mic_btn.bind("<Button-1>", lambda e: self.toggle_voice())
            self.mic_btn.bind("<Enter>",
                              lambda e: self.mic_btn.configure(bg="#E9EDF7"))
            self.mic_btn.bind("<Leave>",
                              lambda e: self.mic_btn.configure(bg="#F4F6FA"))
        self.mic_btn.place(x=pad, y=by, width=30, height=26)

        entry_right = w - pad - 116
        if self.entry is None:
            self.entry = tk.Entry(self.win, bg="#F4F6FA", bd=0, highlightthickness=0,
                                  font=(f, 10), fg="#23262F", insertbackground="#5B6BE8")
        self.entry.place(x=pad + 36, y=by,
                         width=max(50, entry_right - 6 - (pad + 36)), height=26)
        self.entry.configure(validate="none")
        self.entry.bind("<Return>", lambda e: self.ask_more())

        if not self.btns:
            save = tk.Label(self.win, text="存图", bg="#E9EDF7", fg="#4A5AD8",
                            font=(f, 9, "bold"), cursor="hand2")
            save.bind("<Button-1>", lambda e: self.save_image())
            save.bind("<Enter>", lambda e: save.configure(bg="#DCE3F7"))
            save.bind("<Leave>", lambda e: save.configure(bg="#E9EDF7"))
            send = tk.Label(self.win, text="追问", bg="#5B6BE8", fg="white",
                            font=(f, 9, "bold"), cursor="hand2")
            send.bind("<Button-1>", lambda e: self.ask_more())
            send.bind("<Enter>", lambda e: send.configure(bg="#4A5AD8"))
            send.bind("<Leave>", lambda e: send.configure(bg="#5B6BE8"))
            self.btns = [save, send]
            self.save_btn, self.send_btn = save, send
        save_btn, send_btn = self.btns[0], self.btns[1]
        send_btn.place_configure(x=w - pad - 64, y=by, width=56, height=26)
        save_btn.place_configure(x=w - pad - 64 - 6 - 48, y=by, width=48, height=26)
        for b in self.btns:
            try:
                b.lift()
            except Exception:
                pass
        try:
            self.mic_btn.lift()
            self.close_btn.lift()
        except Exception:
            pass

        self.text.bind("<Button-4>", lambda e: self.text.yview_scroll(-2, "units"))
        self.text.bind("<Button-5>", lambda e: self.text.yview_scroll(2, "units"))
        self.text.bind("<Key>", self._readonly_key)
        self._position()

    def _readonly_key(self, e):
        if e.keysym in ("Up", "Down", "Left", "Right", "Prior", "Next", "Home", "End"):
            return None
        if (e.state & 0x4) and e.keysym.lower() == "c":
            return None
        if (e.state & 0x4) and e.keysym.lower() == "a":
            self.text.tag_add("sel", "1.0", "end")
            return "break"
        return "break"

    def _position(self):
        ax, ay, asize = self.anchor
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = ax + asize // 2 - self.width // 2
        y = ay - self.height - 12
        if y < 8:
            y = ay + asize + 12
        x = max(8, min(x, sw - self.width - 8))
        y = max(8, min(y, sh - self.height - 44))
        self.win.geometry("%dx%d+%d+%d" % (self.width, self.height, int(x), int(y)))
        try:
            self.win.lift()
        except Exception:
            pass

    # ---------- 内容

    def set_text(self, body, status=""):
        if isinstance(self.text, tk.Text):
            self.text.configure(state="normal")
            self.text.delete("1.0", "end")
            self.text.insert("1.0", clean_md(body))
            self.text.configure(state="disabled")
            self.text.see("1.0")
        if self.status:
            self._status_text = status
            self.status.configure(text=status, fg="#8A93A5")
        try:
            self.win.update_idletasks()
        except Exception:
            pass
        self._autosize(body)
        try:
            self.win.after(60, self._toggle_sb)
        except Exception:
            pass

    def _toggle_sb(self):
        """内容装得下就把滚动条藏起来，右侧不留多余竖线。"""
        try:
            first, last = self.text.yview()
            if last >= 0.995 and first <= 0.005:
                self.sb.place_forget()
            else:
                self.sb.place(x=self.width - self.PAD - 9, y=self.PAD + 28,
                              height=self.height - 94)
        except Exception:
            pass

    def _autosize(self, body):
        """用 Tk 自己算出的折行数决定气泡高度，避免文字被切或留白太多。"""
        lines = 0
        try:
            got = self.text.count("1.0", "end-1c", "displaylines")
            if got:
                lines = int(got[0])
        except Exception:
            lines = 0
        if not lines:
            cpl = max(12, (self.width - self.PAD * 2) // 13)
            lines = sum(max(1, math.ceil(len(ln) / cpl)) for ln in str(body).split("\n"))
        h = min(480, max(self.body_top + 104, self.body_top + (lines + 1) * 26 + 62))
        if abs(h - self.height) > 8:
            self._build(self.width, h)

    # ---------- 语音输入

    def toggle_voice(self):
        """把焦点交给输入框，再唤起系统听写，说出来的话会直接变成文字。"""
        try:
            self.win.lift()
            self.win.focus_force()
            if self.entry:
                self.entry.focus_set()
                self.entry.icursor("end")
        except Exception:
            pass
        self.win.after(150, send_win_h)
        self._flash_status("已开听写，说完再点『麦』")

    # ---------- 保存截图

    def save_image(self):
        crop = getattr(self.app, "last_crop", None)
        if crop is None:
            return
        from tkinter import filedialog
        default_name = "截图_%s.png" % time.strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            parent=self.app.root, title="把截图另存为",
            defaultextension=".png", initialfile=default_name,
            filetypes=[("PNG 图片（无损）", "*.png"), ("JPEG 图片（体积小）", "*.jpg")])
        if not path:
            return
        try:
            if path.lower().endswith((".jpg", ".jpeg")):
                crop.convert("RGB").save(path, quality=92)
            else:
                crop.save(path)
            size_kb = max(1, os.path.getsize(path) // 1024)
            msg = "已保存 %s（%d KB）" % (os.path.basename(path), size_kb)
        except Exception as e:
            msg = "保存失败：" + str(e)
        self._flash_status(msg)

    def _flash_status(self, msg, keep=True):
        if not self.status:
            return
        try:
            self.status.configure(text=msg, fg="#5B6BE8")
        except Exception:
            return
        if not keep:
            self.win.after(2200, lambda: self.status.configure(
                text=self._status_text, fg="#8A93A5"))

    def show_loading(self, text="正在看图…"):
        self.set_text(text, "已截图")
        self.win.update_idletasks()
        self.win.deiconify()
        self._ensure_top()
        self._animate_dots(0)

    def _animate_dots(self, i):
        if self.status and self.status.cget("text").startswith("已截图"):
            self.status.configure(text="处理中" + "." * (i % 4))
            self.job = self.win.after(500, lambda: self._animate_dots(i + 1))

    def _stop_dots(self):
        if self.job:
            try:
                self.win.after_cancel(self.job)
            except Exception:
                pass
            self.job = None

    def finish(self, body, status="GLM 免费模型"):
        self._stop_dots()
        self.set_text(body, status)
        self.win.deiconify()
        self._ensure_top()

    def _ensure_top(self):
        try:
            self.win.attributes("-topmost", True)
            self.win.lift()
            self.win.focus_force()
        except Exception:
            pass

    def ask_more(self):
        q = self.entry.get().strip() if self.entry else ""
        if not q:
            return
        self.entry.delete(0, "end")
        self.app.follow_up(q, self)

    def close(self):
        self._stop_dots()
        self.app.bubble = None
        try:
            self.win.destroy()
        except Exception:
            pass

    def hide(self):
        """截图瞬间把自己藏起来，避免被截进画面。"""
        try:
            self.win.withdraw()
        except Exception:
            pass

    def show(self):
        try:
            self.win.deiconify()
            self.win.attributes("-topmost", True)
        except Exception:
            pass


# ---------------------------------------------------------------- 设置窗口

class Settings:
    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        self.win.title("豆包截图挂件 · 设置")
        self.win.configure(bg="#F7F9FC")
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        w, h = 560, 430
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.win.geometry("%dx%d+%d+%d" % (w, h, (sw - w) // 2, (sh - h) // 3))
        f = app.font_family

        tk.Label(self.win, text="设置", bg="#F7F9FC", fg="#23262F",
                 font=(f, 15, "bold")).place(x=28, y=20)
        tk.Label(self.win, text="接口用智谱开放平台的免费视觉模型，注册后免费额度足够个人日常截图问答。",
                 bg="#F7F9FC", fg="#8A93A5", font=(f, 9)).place(x=28, y=52)

        tk.Label(self.win, text="API Key", bg="#F7F9FC", fg="#23262F",
                 font=(f, 10, "bold")).place(x=28, y=84)
        self.key_var = tk.StringVar(value=app.cfg.get("api_key", ""))
        ent = tk.Entry(self.win, textvariable=self.key_var, font=(f, 10), bd=1, relief="solid",
                       bg="white", fg="#23262F", insertbackground="#5B6BE8")
        ent.place(x=28, y=108, width=404, height=32)
        tk.Label(self.win, text="获取：open.bigmodel.cn → 注册 → API Keys", bg="#F7F9FC",
                 fg="#5B6BE8", font=(f, 8), cursor="hand2").place(x=28, y=144)
        self.link = tk.Label(self.win, text="点此打开官网", bg="#F7F9FC", fg="#5B6BE8",
                             font=(f, 8, "underline"), cursor="hand2")
        self.link.place(x=28, y=160)
        self.link.bind("<Button-1>", lambda e: self._open_site())

        tk.Label(self.win, text="模型", bg="#F7F9FC", fg="#23262F",
                 font=(f, 10, "bold")).place(x=28, y=192)
        self.model_var = tk.StringVar()
        names = [m[1] for m in MODELS]
        cur = dict(MODELS).get(app.cfg.get("model"), names[0])
        self.model_box = tk.OptionMenu(self.win, self.model_var, *names,
                                       command=lambda *_: None)
        self.model_var.set(cur if cur in names else names[0])
        self.model_box.configure(bg="white", fg="#23262F", font=(f, 9), bd=1, relief="solid",
                                 highlightthickness=0, width=52, anchor="w")
        self.model_box.place(x=28, y=216, width=404, height=32)

        tk.Label(self.win, text="提问方式（可改：比如固定让它翻译英文、或只讲操作步骤）",
                 bg="#F7F9FC", fg="#23262F", font=(f, 10, "bold")).place(x=28, y=258)
        self.prompt = tk.Text(self.win, font=(f, 9), bd=1, relief="solid", bg="white",
                              fg="#23262F", wrap="word", padx=6, pady=6)
        self.prompt.place(x=28, y=282, width=504, height=76)
        self.prompt.insert("1.0", app.cfg.get("prompt", DEFAULT_PROMPT))

        self.tip = tk.Label(self.win, text="", bg="#F7F9FC", fg="#E0574C", font=(f, 9))
        self.tip.place(x=28, y=366, width=300)

        ok = tk.Label(self.win, text="保存", bg="#5B6BE8", fg="white", font=(f, 10, "bold"),
                      cursor="hand2")
        ok.place(x=404, y=362, width=64, height=30)
        ok.bind("<Button-1>", lambda e: self._save())
        test = tk.Label(self.win, text="测试", bg="#E9EDF7", fg="#4A5AD8", font=(f, 10, "bold"),
                        cursor="hand2")
        test.place(x=328, y=362, width=64, height=30)
        test.bind("<Button-1>", lambda e: self._test())

        self.win.protocol("WM_DELETE_WINDOW", self.win.destroy)

    def _open_site(self):
        import webbrowser
        webbrowser.open("https://open.bigmodel.cn/usercenter/apikeys")

    def _current_model_id(self):
        label = self.model_var.get()
        for mid, name in MODELS:
            if name == label:
                return mid
        return DEFAULT_MODEL

    def _collect(self):
        key = self.key_var.get().strip()
        if not key:
            self.tip.configure(text="请先填 API Key")
            return None
        return {
            "api_key": key,
            "model": self._current_model_id(),
            "prompt": self.prompt.get("1.0", "end").strip() or DEFAULT_PROMPT,
            "orb_pos": self.app.cfg.get("orb_pos"),
        }

    def _save(self, quiet=False):
        c = self._collect()
        if not c:
            return False
        self.app.cfg = c
        save_config(c)
        if not quiet:
            self.tip.configure(text="已保存", fg="#2F9E6B")
            self.win.after(900, self.win.destroy)
        return True

    def _test(self):
        c = self._collect()
        if not c:
            return
        self.tip.configure(text="测试中…", fg="#5B6BE8")

        def work():
            try:
                reply = call_api(c["api_key"], c["model"],
                                 [{"role": "user", "content": "只回复两个字：正常"}], timeout=40)
                msg = ("连接成功：" + reply.strip()[:20], "#2F9E6B")
            except Exception as e:
                msg = (str(e)[:120], "#E0574C")
            self.win.after(0, lambda: self.tip.configure(text=msg[0], fg=msg[1]))

        threading.Thread(target=work, daemon=True).start()


# ---------------------------------------------------------------- 主程序

class App:
    def __init__(self):
        enable_dpi_awareness()
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_TITLE)
        self.font_family = self._font_name()
        self.font_ui = (self.font_family, 9)

        self.bubble = None
        self.overlay = None
        self.capturing = False
        self.busy = False
        self.last_crop = None
        self.session = None
        self.q = queue.Queue()

        self.orb = FloatingOrb(self)
        self.root.after(120, self._poll)
        self._start_hotkey()

        if not self.cfg.get("api_key"):
            self.root.after(300, self._first_run)

    def _font_name(self):
        fams = set(tkfont.families(self.root))
        for c in ("Microsoft YaHei UI", "微软雅黑", "Microsoft YaHei", "SimHei"):
            if c in fams:
                return c
        return "TkDefaultFont"

    def _first_run(self):
        self.show_help(intro=True)
        self.open_settings()

    # ---------- 事件循环

    def _poll(self):
        try:
            while True:
                fn, args = self.q.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.root.after(90, self._poll)

    def post(self, fn, *args):
        self.q.put((fn, args))

    def _start_hotkey(self):
        try:
            u = ctypes.windll.user32
            if not u.RegisterHotKey(None, 1, 0x0001 | 0x0002, 0x51):  # Ctrl+Alt+Q
                return

            def loop():
                import ctypes.wintypes as wt
                msg = wt.MSG()
                while u.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                    if msg.message == 0x0312:
                        self.post(self.start_capture)

            threading.Thread(target=loop, daemon=True).start()
        except Exception:
            pass

    # ---------- 截图

    def start_capture(self):
        if self.busy or self.overlay or self.capturing:
            return
        self.capturing = True
        # 截图前把所有自己的窗口都收起来，否则圆球和答案卡片会被截进画面
        self.orb.cancel_collapse()
        self.orb.expand(animated=False)
        if self.bubble:
            self.bubble.hide()
        self.orb.hide()
        self.root.after(340, self._grab)

    def _grab(self):
        self.capturing = False
        try:
            img, origin = grab_screen()
        except Exception as e:
            self.orb.show()
            if self.bubble:
                self.bubble.show()
            self.error("截图失败：" + str(e))
            return
        if os.environ.get("DOUBAO_DEBUG_SHOT"):
            try:
                img.save(os.path.join(BASE_DIR, "debug_capture.png"))
            except Exception:
                pass
        self.overlay = CaptureOverlay(self, img, origin, self._on_crop, self._on_cancel)

    def _on_cancel(self):
        self.overlay = None
        self.capturing = False
        self.orb.show()
        if self.bubble:
            self.bubble.show()

    def _on_crop(self, crop):
        self.overlay = None
        self.capturing = False
        self.orb.show()
        self.last_crop = crop
        if crop.width < 4 or crop.height < 4:
            if self.bubble:
                self.bubble.show()
            return
        self.send_crop(crop, None)

    def send_crop(self, crop, question):
        self.orb.expand(animated=False)
        if not self.cfg.get("api_key"):
            self.open_settings()
            return
        self.busy = True
        self.orb.set_busy(True)
        anchor = self.orb.geometry_for_bubble()
        if self.bubble:
            self.bubble.close()
        self.bubble = Bubble(self, anchor)
        self.bubble.show_loading("正在看图…")

        b64 = encode_image(crop)
        prompt = self.cfg.get("prompt", DEFAULT_PROMPT)
        user_text = prompt if not question else (prompt + "\n\n我补充的问题：" + question)
        messages = [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
                {"type": "text", "text": user_text},
            ]}
        ]
        self.session = {"b64": b64, "messages": messages}
        self._run_api(messages)

    def _run_api(self, messages):
        key = self.cfg.get("api_key")
        model = self.cfg.get("model", DEFAULT_MODEL)

        def work():
            try:
                reply = call_api(key, model, messages)
                self.post(self._on_reply, reply)
            except Exception as e:
                self.post(self._on_fail, str(e))

        threading.Thread(target=work, daemon=True).start()

    def _on_reply(self, reply):
        self.busy = False
        self.orb.set_busy(False)
        if self.session:
            self.session["messages"].append({"role": "assistant", "content": reply})
        label = "GLM-4.6V · 免费" if "4.6v" in self.cfg.get("model", "") else "GLM · 免费"
        if self.bubble:
            self.bubble.finish(reply, label)

    def _on_fail(self, msg):
        self.busy = False
        self.orb.set_busy(False)
        if self.bubble:
            self.bubble.finish("出错了：\n" + msg, "失败")

    def follow_up(self, question, bubble):
        if not self.session:
            if self.last_crop:
                self.send_crop(self.last_crop, question)
            return
        self.orb.expand(animated=False)
        anchor = self.orb.geometry_for_bubble()
        if not bubble or bubble.win.winfo_exists() == 0:
            self.bubble = Bubble(self, anchor)
        else:
            self.bubble = bubble
        self.bubble.show_loading("追问中…")
        self.busy = True
        self.orb.set_busy(True)
        self.session["messages"].append({"role": "user", "content": question})
        self._run_api(self.session["messages"])

    def reopen_last(self):
        if not self.last_crop:
            self.error("还没有截过图。")
            return
        self.send_crop(self.last_crop, None)

    # ---------- 其它窗口

    def open_settings(self):
        Settings(self)

    def show_help(self, intro=False):
        w = tk.Toplevel(self.root)
        w.title("使用说明" + (" · 第一次使用" if intro else ""))
        w.configure(bg="#F7F9FC")
        w.attributes("-topmost", True)
        f = self.font_family
        text = (
            "怎么用\n"
            "1. 桌面上的圆球就是它，按住可以拖到任意位置，位置会自动记住。\n"
            "2. 单击圆球 → 屏幕变暗 → 用鼠标拖出一个框 → 松手，就自动发给 AI。\n"
            "3. 答案从圆球上方的小卡片弹出来；卡片底部可以直接打字继续追问。\n"
            "4. 快捷键 Ctrl+Alt+Q 也能直接开始框选；框选时按 Enter 截全屏，Esc 取消。\n"
            "5. 右键圆球：截图 / 重看上次截图 / 设置 / 退出。\n\n"
            "第一次要做的事\n"
            "点『设置』填一个 API Key（智谱开放平台注册即得），模型保持默认的\n"
            "GLM-4.6V-Flash 就是免费的。填完点『测试』能通就能用。\n\n"
            "为什么免费\n"
            "GLM-4.6V-Flash 是智谱官方标注输入输出全免费的视觉模型，个人日常截图\n"
            "问答额度够用。免费政策由智谱决定，若将来变化，可在设置里换模型。"
        )
        tk.Label(w, text=text, bg="#F7F9FC", fg="#23262F", font=(f, 10), justify="left",
                 anchor="nw").place(x=24, y=20)
        btn = tk.Label(w, text="知道了", bg="#5B6BE8", fg="white", font=(f, 10, "bold"),
                       cursor="hand2")
        btn.place(x=430, y=330, width=88, height=32)
        btn.bind("<Button-1>", lambda e: w.destroy())
        w.geometry("%dx%d+%d+%d" % (544, 380,
                                    (w.winfo_screenwidth() - 544) // 2,
                                    (w.winfo_screenheight() - 380) // 3))

    def error(self, msg):
        anchor = self.orb.geometry_for_bubble()
        if self.bubble:
            self.bubble.close()
        self.bubble = Bubble(self, anchor)
        self.bubble.finish(msg, "提示")

    def quit(self):
        save_config(self.cfg)
        try:
            self.root.destroy()
        except Exception:
            pass


# ---------------------------------------------------------------- 自检 / 打包辅助

def selftest():
    print("== 自检 ==")
    enable_dpi_awareness()
    t0 = time.time()
    frames = orb_images(ORB_SIZE)
    print("图标生成: %d 帧, %.2fs" % (len(frames), time.time() - t0))
    img, origin = grab_screen()
    print("抓屏成功: %dx%d, 原点=%s" % (img.width, img.height, origin))
    crop = img.crop((0, 0, min(300, img.width), min(200, img.height)))
    b64 = encode_image(crop)
    print("编码成功: base64 长度 %d" % len(b64))
    payload = {"model": DEFAULT_MODEL, "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64[:40]}},
        {"type": "text", "text": "test"}]}]}
    print("payload 结构: %s" % json.loads(json.dumps(payload))["messages"][0]["content"][0]["type"])
    ico = os.path.join(BASE_DIR, "icon.ico")
    orb_images(256)[0].save(ico, sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("图标已写出: %s" % ico)
    # GUI 冒烟测试
    app = App()
    app.root.after(700, app.quit)
    app.root.mainloop()
    print("== 自检通过 ==")


def preview():
    """生成两张预览图：贴边收起态、展开+气泡态。"""
    enable_dpi_awareness()
    app = App()
    app.orb.show()

    def cap_sliver():
        img, origin = grab_screen()
        y = app.orb.pos[1]
        if app.orb.side == "left":
            box = (0, y - 24, 140, y + ORB_SIZE + 24)
        else:
            box = (app.orb.screen_w - 140, y - 24, app.orb.screen_w, y + ORB_SIZE + 24)
        crop = img.crop((max(0, box[0] - origin[0]), max(0, box[1] - origin[1]),
                         min(img.width, box[2] - origin[0]),
                         min(img.height, box[3] - origin[1])))
        out = os.path.join(BASE_DIR, "贴边收起预览.png")
        crop.save(out)
        print("sliver saved:", out, crop.size)
        app.orb.expand(animated=False)
        app.root.after(400, shoot)

    def shoot():
        anchor = app.orb.geometry_for_bubble()
        # 造一张示例截图，让卡片里的缩略图有内容可显示
        try:
            scr, _ = grab_screen()
            app.last_crop = scr.crop((40, 40, 560, 340))
        except Exception:
            app.last_crop = None
        app.bubble = Bubble(app, anchor)
        app.bubble.finish(
            "这是 GitHub 的设置入口。\n1. 先点右上角头像，选 Settings；\n"
            "2. 左侧菜单拉到底，点 Developer settings；\n"
            "3. 再点 Personal access tokens → Tokens (classic)；\n"
            "4. 点 Generate new token，勾选 repo 权限后生成。",
            "GLM-4.6V · 免费")
        app.root.update()
        app.root.after(700, capture)

    def capture():
        img, origin = grab_screen()
        bw = app.bubble.win
        ox, oy, osz = app.orb.win.winfo_rootx(), app.orb.win.winfo_rooty(), ORB_SIZE
        bx, by, bwd, bht = bw.winfo_rootx(), bw.winfo_rooty(), bw.winfo_width(), bw.winfo_height()
        left = min(ox, bx) - 30 - origin[0]
        top = min(oy, by) - 30 - origin[1]
        right = max(ox + osz, bx + bwd) + 30 - origin[0]
        bottom = max(oy + osz, by + bht) + 30 - origin[1]
        crop = img.crop((max(0, left), max(0, top),
                         min(img.width, right), min(img.height, bottom)))
        out = os.path.join(BASE_DIR, "效果预览.png")
        crop.save(out)
        print("preview saved:", out, crop.size)
        app.quit()

    app.root.after(1200, cap_sliver)
    app.root.mainloop()


def capture_test():
    """真实走一遍截图流程，把实际抓到的画面存下来，检查有没有把自己的窗口截进去。"""
    enable_dpi_awareness()
    os.environ["DOUBAO_DEBUG_SHOT"] = "1"
    app = App()
    app.root.after(1500, app.start_capture)

    def cancel():
        if app.overlay:
            app.overlay._cancel()
        app.bubble = None
        app.root.after(700, app.quit)

    app.root.after(3200, cancel)
    app.root.mainloop()
    p = os.path.join(BASE_DIR, "debug_capture.png")
    print("debug capture:", p, os.path.exists(p))


def main():
    if "--preview" in sys.argv:
        preview()
        return
    if "--capture-test" in sys.argv:
        capture_test()
        return
    if "--selftest" in sys.argv:
        selftest()
        return
    App().root.mainloop()


if __name__ == "__main__":
    main()
