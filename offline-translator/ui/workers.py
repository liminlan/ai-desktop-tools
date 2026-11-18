"""后台任务：OCR 和翻译都不能跑在 UI 线程，否则悬浮球会卡住。

不用 QRunnable + QThreadPool：QRunnable 开 autoDelete 后，任务结束时对象会被
C++ 侧回收，而信号是异步投递的，跨线程 emit 有可能落在对象已销毁之后（表现为
结果窗一直停在"正在识别"、回调根本没跑）；池化线程在某些情况下还会让任务排队
不执行。这里改成一次任务一个普通线程 + 独立的信号桥，跑完由主线程回收。
"""
from __future__ import annotations

import threading
import traceback
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str, str)  # (简短错误, 详细 traceback)


# 任务存活期间必须持有信号对象，否则跨线程 emit 之前就被 GC
_alive: set[_Signals] = set()


def run_async(
    fn: Callable[..., Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[str, str], None] | None = None,
    *args,
    **kwargs,
) -> None:
    signals = _Signals()
    if on_done:
        signals.done.connect(on_done)
    if on_error:
        signals.failed.connect(on_error)
    # 回调跑完（在主线程）再把桥回收，避免信号还没投递就被释放
    signals.done.connect(lambda *_: _alive.discard(signals))
    signals.failed.connect(lambda *_: _alive.discard(signals))
    _alive.add(signals)

    def worker() -> None:
        try:
            result = fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            signals.failed.emit(f"{type(exc).__name__}: {exc}", traceback.format_exc())
        else:
            signals.done.emit(result)

    threading.Thread(target=worker, name="translate-task", daemon=True).start()
