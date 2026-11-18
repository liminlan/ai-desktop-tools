"""配置管理：默认值 + JSON 读写 + 容错迁移。"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
from pathlib import Path


def app_root() -> Path:
    """程序根目录。打包后为 exe 同级目录（绿色版），开发时为项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


ROOT = app_root()
CONFIG_PATH = ROOT / "config.json"
MODELS_DIR = ROOT / "models"
CACHE_DB = ROOT / "cache.db"
LOG_PATH = ROOT / "app.log"

_SAFE_MODELS_DIR: Path | None = None


def _is_ascii_path(path: Path) -> bool:
    try:
        str(path).encode("ascii")
        return True
    except UnicodeEncodeError:
        return False


def safe_models_dir() -> Path:
    """CTranslate2 和 SentencePiece 的 C++ 层打不开含中文的路径。

    如果程序被放在中文目录下（比如桌面\离线翻译悬浮窗），模型会报
    NOT_FOUND，哪怕文件明明在那儿。这种情况把模型复制到纯英文目录再加载，
    用户不用为此改程序位置。
    """
    global _SAFE_MODELS_DIR
    if _SAFE_MODELS_DIR is not None:
        return _SAFE_MODELS_DIR
    if _is_ascii_path(MODELS_DIR) or not MODELS_DIR.exists():
        _SAFE_MODELS_DIR = MODELS_DIR
        return _SAFE_MODELS_DIR

    base = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData") / "OfflineTranslator" / "models"
    try:
        if not base.exists():
            base.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(MODELS_DIR, base)
        _SAFE_MODELS_DIR = base
    except Exception:
        _SAFE_MODELS_DIR = MODELS_DIR
    return _SAFE_MODELS_DIR

DEFAULTS = {
    "hotkey": {
        # 主推：按住热键划选后松开即译
        "capture": "Alt+T",
        # 兼容：把剪贴板/选中内容直接翻译
        "clipboard": "Ctrl+Alt+C",
    },
    "ball": {
        "shape": "ball",          # ball | bar
        "pos": [40, 320],
        "size": 56,
        "opacity": 0.94,
        "edge_snap": True,
    },
    "popup": {
        "font_size": 16,
        "max_width": 520,
        "theme": "light",
        "auto_copy": False,
        "close_on_esc": True,
    },
    "clipboard": {
        "auto_translate": False,   # 复制即翻（默认关，防误触）
        "min_chars": 2,
        "debounce_ms": 400,
    },
    "engine": {
        "device": "cpu",           # cpu | cuda
        "compute_type": "int8",    # int8 | float32 | auto
        "beam_size": 3,
        "max_chars": 1200,         # 超长文本截断保护
    },
    "ocr": {
        # auto: 优先 Windows 系统 OCR（8~50ms），不可用再退 RapidOCR
        "backend": "auto",         # auto | windows | rapidocr
    },
    "line_merge": {
        "enabled": True,           # OCR 断行合并成句（影响译文质量，别关）
        "line_gap_ratio": 1.45,    # 行距 <= 平均字高*该值 视为同一段
    },
    "startup": {
        "autostart": False,
    },
}


class Config:
    """轻量配置对象，属性式访问 + 自动落盘。"""

    def __init__(self) -> None:
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    # ---------- 读写 ----------
    def load(self) -> None:
        if not CONFIG_PATH.exists():
            self.save()
            return
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            # 配置损坏时不要崩溃，直接用默认值并备份坏文件
            try:
                CONFIG_PATH.replace(CONFIG_PATH.with_suffix(".bad.json"))
            except Exception:
                pass
            self.save()
            return
        self._merge(self._data, raw)
        self.save()

    @staticmethod
    def _merge(base: dict, incoming: dict) -> None:
        """只接受已知键，未知键丢弃；缺键用默认值补。"""
        for k, v in base.items():
            if k not in incoming:
                continue
            if isinstance(v, dict) and isinstance(incoming[k], dict):
                Config._merge(v, incoming[k])
            else:
                base[k] = incoming[k]

    def save(self) -> None:
        try:
            CONFIG_PATH.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            pass

    # ---------- 访问 ----------
    def get(self, path: str, default=None):
        node = self._data
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, path: str, value) -> None:
        parts = path.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self.save()


CFG = Config()
