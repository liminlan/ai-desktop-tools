"""离线翻译引擎：CTranslate2 + SentencePiece，直接吃 Argos 语言包。

不用 argostranslate 这个库的原因：它硬依赖 stanza -> torch，光依赖就 2GB+，
而我们要的只是它语言包里的 CT2 模型和分词模型。自己加载一下，省掉一大坨。
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..core import model_manager
from ..core.config import CFG

BACKEND_NAME = "argos-ct2-en-zh"

# 模型若需要目标语言前缀（部分多语种 OPUS 模型需要），这里留一组候选用于自动探测
TARGET_PREFIX_CANDIDATES = ["", ">>cmn_Hans<< ", ">>zho<< ", ">>zh<< "]
_PROBE_SENTENCE = "How are you today? I am fine, thank you."

# sentencepiece 的词边界符号，decode 后偶尔会残留，必须清掉
SP_SPACE = "\u2581"
CJK_CHARS = r"\u4e00-\u9fff\u3400-\u4dbf"
CJK_PUNCT = r"\u3000-\u303f\uff01-\uff60"
_CJK_LEFT = re.compile(rf"(?<=[{CJK_CHARS}{CJK_PUNCT}])\s+")
_CJK_RIGHT = re.compile(rf"\s+(?=[{CJK_CHARS}{CJK_PUNCT}])")
_MULTI_SPACE = re.compile(r"[ \t]+")
_ASCII_PUNCT = {",": "，", ".": "。", "?": "？", "!": "！", ":": "：", ";": "；"}


def clean_decoded(text: str) -> str:
    """把模型输出整理成正常中文：
    1) 去掉残留的 ▁；2) 中文与中文之间不留空格；3) 中文句子里的半角标点转全角。
    """
    if not text:
        return ""
    text = text.replace(SP_SPACE, " ")
    text = _CJK_LEFT.sub("", text)
    text = _CJK_RIGHT.sub("", text)
    text = _MULTI_SPACE.sub(" ", text).strip()

    # 若这一段以中文为主，则把半角标点换成全角，避免出现 "你好,今天." 这种割裂感
    cjk_count = len(re.findall(rf"[{CJK_CHARS}]", text))
    if cjk_count >= max(3, len(text) // 3):
        for half, full in _ASCII_PUNCT.items():
            text = text.replace(f" {half}", full).replace(half, full)
    return text.strip()


@dataclass
class TranslationResult:
    source: str
    target: str
    kind: str
    from_cache: bool
    cost_ms: int


class Translator:
    """线程安全：内部加锁串行推理（CT2 本身多线程，但避免并发抢同一实例）。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sp = None
        self._ct2 = None
        self._prefix = ""
        self._ready = False
        self._load_error: str | None = None

    # ---------- 生命周期 ----------
    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def load_error(self) -> str | None:
        return self._load_error

    def load(self) -> bool:
        if self._ready:
            return True
        with self._lock:
            if self._ready:
                return True
            try:
                import ctranslate2
                import sentencepiece as spm

                sp_path = model_manager.find_sentencepiece()
                if sp_path is None:
                    self._load_error = "模型目录缺分词文件（sentencepiece.model）"
                    return False

                model_dir = model_manager.resolve_model_dir()
                if model_dir is None:
                    self._load_error = "模型目录缺 CT2 模型（model/model.bin）"
                    return False

                self._sp = spm.SentencePieceProcessor(model_file=str(sp_path))
                device = str(CFG.get("engine.device", "cpu"))
                compute = str(CFG.get("engine.compute_type", "int8"))
                try:
                    self._ct2 = ctranslate2.Translator(
                        str(model_dir), device=device, compute_type=compute,
                        inter_threads=1, intra_threads=0,
                    )
                except Exception:
                    # cuda 不可用时静默回落 CPU，别让用户看到程序直接挂掉
                    self._ct2 = ctranslate2.Translator(
                        str(model_dir), device="cpu", compute_type="int8",
                    )
                    CFG.set("engine.device", "cpu")

                self._prefix = self._detect_prefix()
                self._ready = True
                return True
            except Exception as exc:  # noqa: BLE001
                self._load_error = f"{type(exc).__name__}: {exc}"
                return False

    # ---------- 推理 ----------
    def _raw(self, text: str) -> str:
        toks = self._sp.encode(text, out_type=str)
        out = self._ct2.translate_batch(
            [toks],
            beam_size=int(CFG.get("engine.beam_size", 3)),
            max_decoding_length=512,
        )
        return clean_decoded(self._sp.decode(out[0].hypotheses[0]))

    def _detect_prefix(self) -> str:
        """探测模型是否需要目标语言前缀：不加前缀若把原文照抄回来，就换前缀重试。"""
        base = _PROBE_SENTENCE.lower()
        for cand in TARGET_PREFIX_CANDIDATES:
            try:
                out = self._raw(cand + _PROBE_SENTENCE)
            except Exception:
                continue
            out_norm = out.strip().lower()
            if not out_norm:
                continue
            # 输出里有中文 -> 这个前缀可用
            if re.search(r"[\u4e00-\u9fff]", out):
                return cand
            # 输出仍是近似原文 -> 换下一个前缀
            if out_norm == base or out_norm == _PROBE_SENTENCE.lower():
                continue
        return ""

    def translate(self, text: str) -> str:
        if not text.strip():
            return ""
        if not self._ready and not self.load():
            raise RuntimeError(self._load_error or "翻译模型未加载")
        max_chars = int(CFG.get("engine.max_chars", 1200))
        clipped = text[:max_chars]
        with self._lock:
            return self._raw(self._prefix + clipped).strip()

    def translate_batch(self, texts: list[str]) -> list[str]:
        if not texts:
            return []
        if not self._ready and not self.load():
            raise RuntimeError(self._load_error or "翻译模型未加载")
        with self._lock:
            toks = [self._sp.encode(self._prefix + t, out_type=str) for t in texts]
            out = self._ct2.translate_batch(
                toks, beam_size=int(CFG.get("engine.beam_size", 3)), max_decoding_length=512
            )
            return [clean_decoded(self._sp.decode(o.hypotheses[0])) for o in out]

    def close(self) -> None:
        with self._lock:
            self._ct2 = None
            self._sp = None
            self._ready = False


_TRANSLATOR: Translator | None = None


def get_translator() -> Translator:
    global _TRANSLATOR
    if _TRANSLATOR is None:
        _TRANSLATOR = Translator()
    return _TRANSLATOR
