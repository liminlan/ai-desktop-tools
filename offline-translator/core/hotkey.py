"""全局热键（Windows RegisterHotKey）。

用独立线程跑消息循环接收 WM_HOTKEY，比挂在 Qt nativeEventFilter 上更稳，
也不依赖第三方 keyboard 库（那个需要键盘钩子，容易被杀软拦）。
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP_CLEAR = 0x8000 + 17

MODIFIER_NAMES = {
    "ALT": MOD_ALT,
    "CTRL": MOD_CONTROL,
    "CONTROL": MOD_CONTROL,
    "SHIFT": MOD_SHIFT,
    "WIN": MOD_WIN,
}

_VK_MAP = {
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): ord(str(d)) for d in range(0, 10)},
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75,
    "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "ESC": 0x1B,
    "`": 0xC0, ";": 0xBA, "'": 0xDE, ",": 0xBC, ".": 0xBE, "/": 0xBF,
    "[": 0xDB, "]": 0xDD, "\\": 0xDC, "-": 0xBD, "=": 0xBB,
}


def parse_hotkey(spec: str) -> tuple[int, int] | None:
    """'Alt+T' -> (mods, vk)。解析失败返回 None。"""
    if not spec:
        return None
    parts = [p.strip().upper() for p in spec.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return None
    mods = 0
    vk = None
    for part in parts:
        if part in MODIFIER_NAMES:
            mods |= MODIFIER_NAMES[part]
        elif part in _VK_MAP:
            vk = _VK_MAP[part]
        elif len(part) == 1 and part.isalnum():
            vk = ord(part.upper())
        else:
            return None
    if vk is None:
        return None
    return (mods | MOD_NOREPEAT, vk)


def hotkey_to_text(spec: str) -> str:
    return spec.replace("Ctrl", "Ctrl").replace("+", " + ")


class HotkeyManager:
    """注册若干全局热键，触发时在后台线程回调（回调里不要直接碰 UI）。"""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._callbacks: dict[int, Callable[[], None]] = {}
        self._bindings: list[tuple[str, str]] = []
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self.failed: list[str] = []

    # ---------- 对外 ----------
    def register(self, bindings: list[tuple[str, str]]) -> list[str]:
        """bindings: [(热键字符串, 回调名)]；回调名后续用 bind_callback 关联。

        返回注册失败的描述列表（比如热键被别的软件占用）。
        """
        self.stop()
        self._bindings = list(bindings)
        self.failed = []
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="hotkey-loop", daemon=True)
        self._thread.start()
        self._ready.wait(2.0)
        return self.failed

    def bind_callback(self, name: str, cb: Callable[[], None]) -> None:
        self._callbacks[name] = cb

    def stop(self) -> None:
        tid = self._thread_id
        if tid:
            try:
                user32.PostThreadMessageW(tid, WM_APP_CLEAR, 0, 0)
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(1.0)
        self._thread = None
        self._thread_id = None

    # ---------- 线程体 ----------
    def _run(self) -> None:
        self._thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        # 先创建消息队列（GetMessage 会隐式创建，这里显式喂一次）
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)

        registered: list[int] = []
        for idx, (spec, name) in enumerate(self._bindings):
            parsed = parse_hotkey(spec)
            if not parsed:
                self.failed.append(f"{spec}（无法解析）")
                continue
            mods, vk = parsed
            hid = 0xB000 + idx
            ok = user32.RegisterHotKey(None, hid, mods, vk)
            if not ok:
                self.failed.append(f"{spec}（已被其它程序占用）")
            else:
                registered.append(hid)

        self._ready.set()

        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret == 0 or ret == -1:
                break
            if msg.message == WM_HOTKEY:
                hid = int(msg.wParam)
                idx = hid - 0xB000
                if 0 <= idx < len(self._bindings):
                    name = self._bindings[idx][1]
                    cb = self._callbacks.get(name)
                    if cb:
                        try:
                            cb()
                        except Exception:
                            pass
            elif msg.message == WM_APP_CLEAR:
                break

        for hid in registered:
            try:
                user32.UnregisterHotKey(None, hid)
            except Exception:
                pass
