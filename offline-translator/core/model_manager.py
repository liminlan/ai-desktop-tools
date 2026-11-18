"""模型管理：检测本地模型是否就绪、路径解析、首次下载引导。

模型目录布局（兼容 Argos 语言包解压后带版本号子目录的情况）：
    models/
      nmt/en_zh/
        translate-en_zh-1_9/          <- 实际包目录（也可能是 en_zh 本身平铺）
          metadata.json
          sentencepiece.model
          model/model.bin
          stanza/
      ocr/                            <- 可选，外置 OCR 模型
"""
from __future__ import annotations

import json
import urllib.request
import zipfile
from pathlib import Path

from .config import MODELS_DIR, safe_models_dir

# 模型实际加载目录：程序在中文路径下时会被自动换到纯英文目录
_MODELS = safe_models_dir()
NMT_DIR = _MODELS / "nmt" / "en_zh"
OCR_DIR = _MODELS / "ocr"

ARGOS_INDEXES = [
    "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json",
    "https://argos-net.com/v1/index.json",
]

SP_NAMES = ("sentencepiece.model", "bpe.model", "source.spm")
MODEL_DIR_NAMES = ("model", "ct2-model")


def resolve_package_dir() -> Path | None:
    """找到真正包含分词模型的目录（可能在带版本号的子目录里）。"""
    if not NMT_DIR.exists():
        return None
    candidates = [NMT_DIR] + sorted(
        [p for p in NMT_DIR.iterdir() if p.is_dir() and not p.name.startswith("_")],
        key=lambda p: p.name, reverse=True,
    )
    for cand in candidates:
        if any((cand / n).exists() for n in SP_NAMES):
            return cand
    return None


def resolve_model_dir() -> Path | None:
    pkg = resolve_package_dir()
    if pkg is None:
        return None
    for name in MODEL_DIR_NAMES:
        d = pkg / name
        if d.is_dir() and (d / "model.bin").exists():
            return d
    return None


def nmt_ready() -> bool:
    return resolve_package_dir() is not None and resolve_model_dir() is not None


def find_sentencepiece() -> Path | None:
    pkg = resolve_package_dir()
    if pkg is None:
        return None
    for name in SP_NAMES:
        cand = pkg / name
        if cand.exists():
            return cand
    return None


def ocr_model_dir() -> Path | None:
    if (OCR_DIR / "det.onnx").exists() and (OCR_DIR / "rec.onnx").exists():
        return OCR_DIR
    return None


def nmt_status() -> str:
    if nmt_ready():
        return "翻译模型已就绪"
    return "翻译模型缺失（models/nmt/en_zh 下未找到分词模型或 model.bin）"


def _find_en_zh_link(index) -> str | None:
    if isinstance(index, dict):
        values = list(index.values())
    elif isinstance(index, list):
        values = index
    else:
        return None
    flat = []
    for v in values:
        if isinstance(v, list):
            flat.extend([x for x in v if isinstance(x, dict)])
        elif isinstance(v, dict):
            flat.append(v)
    for item in flat:
        if item.get("from_code") == "en" and item.get("to_code") == "zh":
            links = item.get("links") or []
            if links:
                return sorted(links)[-1]
    return None


def download_nmt(progress=None) -> str:
    """下载 en→zh Argos 语言包（约 70MB）并解压。仅首次联网。"""
    NMT_DIR.mkdir(parents=True, exist_ok=True)
    index = None
    last_err = None
    for url in ARGOS_INDEXES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=25) as resp:
                index = json.loads(resp.read().decode("utf-8"))
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if index is None:
        raise RuntimeError(f"无法获取模型索引：{last_err}")

    link = _find_en_zh_link(index)
    if not link:
        raise RuntimeError("索引里没有 en→zh 语言包")

    tmp = _MODELS / "_en_zh.argosmodel"
    req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1024 * 128)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total)
    with zipfile.ZipFile(tmp) as zf:
        zf.extractall(NMT_DIR)
    try:
        tmp.unlink()
    except Exception:
        pass
    return f"模型已安装：{resolve_package_dir()}"
