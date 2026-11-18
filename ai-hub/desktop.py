# -*- coding: utf-8 -*-
"""
AI 聚合助手 · 桌面版
- 独立窗口（Edge WebView2 内核），不占浏览器标签
- 关窗口 = 收进系统托盘，不退出
- 全局热键 Ctrl+Alt+Space：随时把它叫到最前面
- 服务仍是 server.py 那一套，只监听 127.0.0.1，不外网暴露

用法：
    python desktop.py               正常启动
    python desktop.py --smoke 8     启动 8 秒后自动退出（自检用）
"""
import ctypes
import os
import socket
import sys
import threading
import time
import webbrowser
from http.server import ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import server as sv           # 复用本地服务（转发 / 导出 / 工具 / 语音）

APP_NAME = 'AI 聚合助手'
ICON_PATH = os.path.join(ROOT, 'assets', 'app-icon.png')
HOTKEY_DESC = 'Ctrl+Alt+Space'

_state = {'httpd': None, 'port': 0, 'window': None, 'icon': None, 'quitting': False, 'hide_on_close': True}


# ---------------------------------------------------------------- 服务
def start_service():
    port = sv.pick_port()
    if not port:
        raise RuntimeError('端口 8760-8799 都被占用，先关掉占用它们的程序')
    httpd = ThreadingHTTPServer(('127.0.0.1', port), sv.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    _state['httpd'] = httpd
    _state['port'] = port
    return port


def stop_service():
    h = _state['httpd']
    if h:
        try:
            h.shutdown()
            h.server_close()
        except Exception:
            pass
        _state['httpd'] = None


def base_url():
    return 'http://127.0.0.1:%d/' % _state['port']


# ---------------------------------------------------------------- 窗口动作
def show_window():
    w = _state['window']
    if not w:
        return
    try:
        w.show()
    except Exception:
        pass
    try:
        w.restore()
    except Exception:
        pass
    try:                     # 稍微顶一下，确保真的来到最前
        w.on_top = True
        time.sleep(0.12)
        w.on_top = False
    except Exception:
        pass


def hide_window():
    w = _state['window']
    if not w:
        return
    try:
        w.hide()
    except Exception:
        pass


def reload_page():
    w = _state['window']
    if not w:
        return
    try:
        w.evaluate_js('location.reload()')
    except Exception:
        pass


def open_in_browser():
    webbrowser.open(base_url())


def quit_app():
    _state['quitting'] = True
    icon = _state['icon']
    if icon:
        try:
            icon.stop()
        except Exception:
            pass
    w = _state['window']
    if w:
        try:
            w.destroy()
        except Exception:
            pass
    stop_service()
    os._exit(0)


# ---------------------------------------------------------------- 全局热键
class _MSG(ctypes.Structure):
    _fields_ = [('hwnd', ctypes.c_void_p), ('message', ctypes.c_uint), ('wParam', ctypes.c_void_p),
                ('lParam', ctypes.c_void_p), ('time', ctypes.c_uint), ('pt_x', ctypes.c_long),
                ('pt_y', ctypes.c_long)]


def register_hotkey():
    """Win32 RegisterHotKey：只注册热键、不装键盘钩子，避免被杀毒误报。
       注册和消息循环必须在同一个线程里，所以整段放进子线程。"""
    MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
    VK_SPACE = 0x20
    WM_HOTKEY = 0x0312

    def loop():
        try:
            user32 = ctypes.windll.user32
        except Exception:
            return
        if not user32.RegisterHotKey(None, 101, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, VK_SPACE):
            return          # 被别的程序占了，安静地跳过
        try:
            msg = _MSG()
            while not _state['quitting']:
                r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0:      # WM_QUIT
                    break
                if msg.message == WM_HOTKEY:
                    show_window()
        finally:
            try:
                user32.UnregisterHotKey(None, 101)
            except Exception:
                pass

    threading.Thread(target=loop, daemon=True).start()
    return True


# ---------------------------------------------------------------- 托盘
def build_tray():
    import pystray
    from pystray import Menu, MenuItem
    try:
        from PIL import Image
        img = Image.open(ICON_PATH).convert('RGBA').resize((64, 64))
    except Exception:
        img = None
    if img is None:
        return None

    menu = Menu(
        MenuItem('显示窗口', lambda *_: show_window(), default=True),
        MenuItem('重新载入页面', lambda *_: reload_page()),
        MenuItem('在浏览器打开', lambda *_: open_in_browser()),
        MenuItem('复制访问地址', lambda *_: _copy_addr()),
        MenuItem('重启本地服务', lambda *_: _restart_service()),
        pystray.Menu.SEPARATOR,
        MenuItem('退出', lambda *_: quit_app()),
    )
    icon = pystray.Icon('aihub', img, APP_NAME, menu)
    _state['icon'] = icon
    icon.run()
    return icon


def _copy_addr():
    try:
        import tkinter
        r = tkinter.Tk()
        r.withdraw()
        r.clipboard_clear()
        r.clipboard_append(base_url())
        r.update()
        r.destroy()
    except Exception:
        pass


def _restart_service():
    stop_service()
    try:
        start_service()
    except Exception:
        pass
    reload_page()


# ---------------------------------------------------------------- 入口
def main():
    smoke = 0
    for i, a in enumerate(sys.argv):
        if a == '--smoke' and i + 1 < len(sys.argv):
            smoke = int(float(sys.argv[i + 1]))

    import webview

    port = start_service()
    window = webview.create_window(
        APP_NAME,
        base_url(),
        width=1300,
        height=860,
        min_size=(980, 640),
        background_color='#0D1017',
    )
    _state['window'] = window

    def on_closing():
        if _state['quitting'] or not _state['hide_on_close']:
            return True
        hide_window()
        return False        # 取消关闭，收进托盘

    window.events.closing += on_closing

    def after_start():
        threading.Thread(target=register_hotkey, daemon=True).start()
        threading.Thread(target=build_tray, daemon=True).start()
        if smoke:
            def bye():
                time.sleep(smoke)
                print('SMOKE_OK port=%d' % _state['port'], flush=True)
                quit_app()
            threading.Thread(target=bye, daemon=True).start()

    webview.start(after_start, private_mode=False, storage_path=os.path.join(ROOT, '.webview'))


if __name__ == '__main__':
    main()
