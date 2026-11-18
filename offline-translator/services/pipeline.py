"""处理流水线：图/文 -> OCR -> 行合并 -> 缓存查询 -> 翻译 -> 结果。

UI 层只跟这个门面打交道，不直接碰模型。
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

import numpy as np

from ..core.config import CFG
from . import ocr_engine
from .cache import Cache
from .line_merge import TextLine, collect_text
from .textfix import fix_english, keep_english_line
from .translation import BACKEND_NAME, get_translator

log = logging.getLogger(__name__)

ASCII_LETTER = re.compile(r"[A-Za-z]")
HAS_ENOUGH_ENGLISH = re.compile(r"[A-Za-z]{2,}")
CJK_CHAR = re.compile(r"[\u4e00-\u9fff]")
# 极简英文拼写检查：用来识别"模型把非英文文本硬翻成噪声"的情况


def _looks_chinese(text: str, threshold: float = 0.6) -> bool:
    """中文字符占比超过阈值，就认为这段是中文。"""
    body = re.sub(r"\s", "", text)
    if not body:
        return False
    cjk = len(CJK_CHAR.findall(body))
    letters = len(ASCII_LETTER.findall(body))
    return cjk >= 3 and cjk / max(1, cjk + letters) >= threshold


@dataclass
class PipelineResult:
    source_text: str
    target_text: str
    kind: str = "sentence"
    from_cache: bool = False
    cost_ms: int = 0
    line_count: int = 0
    note: str = ""


class TranslateService:
    def __init__(self, cache: Cache) -> None:
        self.cache = cache

    # ---------- 对外 ----------
    def translate_image(self, bgr: np.ndarray) -> PipelineResult:
        t0 = time.perf_counter()
        log.info("取词开始：%dx%d 像素", bgr.shape[1], bgr.shape[0])
        lines = ocr_engine.recognize(bgr)
        log.info("OCR 完成：%d 行，%dms", len(lines), _ms(t0))
        if not lines:
            return PipelineResult("", "", note="没识别到文字，换个区域再试一次", cost_ms=_ms(t0))

        # 丢掉窗口标题栏、中文菜单这类噪声行，只留英文为主的文字
        english_lines = [ln for ln in lines if keep_english_line(ln.text)]
        if not english_lines:
            return PipelineResult(
                "", "", note="这块区域里没有英文", line_count=len(lines), cost_ms=_ms(t0)
            )

        gap = float(CFG.get("line_merge.line_gap_ratio", 1.45))
        raw_source = collect_text(english_lines, gap)
        # 修掉 OCR 切错的单词空格和大小写抖动
        source = "\n\n".join(fix_english(p) for p in raw_source.split("\n\n") if p.strip())

        if not HAS_ENOUGH_ENGLISH.search(source):
            return PipelineResult(
                source, "", note="这块区域里没有成段的英文",
                line_count=len(lines), cost_ms=_ms(t0),
            )
        res = self._translate_source(source, t0)
        res.line_count = len(english_lines)
        return res

    def translate_text(self, text: str) -> PipelineResult:
        t0 = time.perf_counter()
        text = text.strip()
        if not text:
            return PipelineResult("", "", note="没有可翻译的内容")
        if _looks_chinese(text):
            return PipelineResult(
                text, "", note="这段是中文。当前模型只做英译中，中文不需要翻译", cost_ms=_ms(t0)
            )
        if not HAS_ENOUGH_ENGLISH.search(text):
            return PipelineResult(text, "", note="没检测到成段的英文", cost_ms=_ms(t0))
        return self._translate_source(text, t0)

    def warm_up(self) -> str:
        """启动时后台预热：加载翻译模型 + OCR 引擎，避免第一次取词卡两秒。"""
        notes = []
        tr = get_translator()
        if tr.load():
            notes.append("翻译模型已加载")
        else:
            notes.append(f"翻译模型加载失败：{tr.load_error}")
        try:
            notes.append(f"OCR 引擎已加载（{ocr_engine.backend_label()}）")
        except Exception as exc:  # noqa: BLE001
            notes.append(f"OCR 引擎加载失败：{exc}")
        return "；".join(notes)

    # ---------- 内部 ----------
    def _translate_source(self, source: str, t0: float) -> PipelineResult:
        paragraphs = [p for p in source.split("\n\n") if p.strip()]
        if not paragraphs:
            return PipelineResult(source, "", note="没有可翻译的内容", cost_ms=_ms(t0))

        translator = get_translator()
        if not translator.ready and not translator.load():
            return PipelineResult(
                source, "", note=f"翻译模型加载失败：{translator.load_error}", cost_ms=_ms(t0)
            )

        hits: dict[int, str] = {}
        misses: list[tuple[int, str]] = []
        for idx, para in enumerate(paragraphs):
            cached = self.cache.get(para, "en", "zh", BACKEND_NAME)
            if cached:
                hits[idx] = cached
            else:
                misses.append((idx, para))

        if misses:
            translated = translator.translate_batch([p for _, p in misses])
            for (idx, para), target in zip(misses, translated):
                hits[idx] = target
                self.cache.put(para, "en", "zh", BACKEND_NAME, target)

        target_text = "\n\n".join(hits.get(i, "") for i in range(len(paragraphs)))
        kind = "word" if len(paragraphs) == 1 and _is_word(paragraphs[0]) else "sentence"
        return PipelineResult(
            source_text=source,
            target_text=target_text,
            kind=kind,
            from_cache=not misses,
            cost_ms=_ms(t0),
            line_count=0,
        )


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _is_word(text: str) -> bool:
    return len(text.split()) <= 2 and len(text) < 24


def lines_to_text(lines: list[TextLine]) -> str:
    return collect_text(lines, float(CFG.get("line_merge.line_gap_ratio", 1.45)))
