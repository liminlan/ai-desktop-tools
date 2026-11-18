"""首次运行用的模型下载脚本：抓 Argos en→zh 语言包并解压到 models/nmt/en_zh。

用法：
    python scripts/download_models.py

只联网这一次，下完之后程序永久离线可用。
"""
from __future__ import annotations

import json
import sys
import urllib.request
import zipfile
from pathlib import Path

INDEXES = [
    "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json",
    "https://argos-net.com/v1/index.json",
]
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
NMT_DIR = MODELS_DIR / "nmt" / "en_zh"


def _iter_items(index):
    """索引文件的结构在不同版本里变过：可能是 dict，也可能是 list[dict]。"""
    if isinstance(index, dict):
        values = list(index.values())
    elif isinstance(index, list):
        values = index
    else:
        return
    for value in values:
        if isinstance(value, list):
            for sub in value:
                if isinstance(sub, dict):
                    yield sub
        elif isinstance(value, dict):
            yield value


def find_link(index) -> str | None:
    for item in _iter_items(index):
        if item.get("from_code") == "en" and item.get("to_code") == "zh":
            links = item.get("links") or []
            if links:
                # 优先选版本号最大的
                return sorted(links)[-1]
    return None


def fetch_index() -> dict:
    last_err = None
    for url in INDEXES:
        try:
            with urllib.request.urlopen(url, timeout=25) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    raise RuntimeError(f"所有索引地址都拿不到：{last_err}")


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=90) as resp, open(dest, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1024 * 128)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                pct = done / total * 100
                sys.stdout.write(f"\r下载中 {pct:5.1f}%  {done/1e6:6.1f}MB / {total/1e6:.1f}MB")
                sys.stdout.flush()
    sys.stdout.write("\n")


def main() -> int:
    print("== 获取 Argos 模型索引 ==")
    index = fetch_index()
    link = find_link(index)
    if not link:
        print("!! 索引里没有 en->zh 语言包")
        return 1
    print(f"语言包地址：{link}")

    NMT_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MODELS_DIR / "_en_zh.argosmodel"
    download(link, tmp)

    print("== 解压 ==")
    with zipfile.ZipFile(tmp) as zf:
        names = zf.namelist()
        zf.extractall(NMT_DIR)
    tmp.unlink(missing_ok=True)

    print("解压后的顶层内容：")
    for name in names[:20]:
        print("  ", name)

    sp_files = list(NMT_DIR.glob("*.model")) + list(NMT_DIR.glob("*.spm"))
    model_dirs = [p for p in NMT_DIR.iterdir() if p.is_dir()]
    print(f"分词文件：{[p.name for p in sp_files]}")
    print(f"模型目录：{[p.name for p in model_dirs]}")
    ok = bool(sp_files) and bool(model_dirs)
    print("== 就绪 ==" if ok else "== 结构不符合预期，请检查 ==")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
