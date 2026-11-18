"""OCR 断行合并：把视觉上的多行拼回语义上的一句话。

不合并的后果：一句 "The quick brown fox / jumps over the lazy dog." 会被当成
两条独立句子喂给翻译模型，译文变成两截碎片，这是离线翻译最常见的体验崩塌点。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TextLine:
    text: str
    box: tuple[int, int, int, int]  # x, y, w, h（原图像素）
    conf: float = 1.0

    @property
    def bottom(self) -> int:
        return self.box[1] + self.box[3]

    @property
    def center_y(self) -> int:
        return self.box[1] + self.box[3] // 2


SENT_END = tuple(".!?:;。！？：；")
CJK = re.compile(r"[\u4e00-\u9fff]")


def _join(a: str, b: str) -> str:
    """拼接两行：中文之间不加空格，英文之间补空格，连字符行去掉断词。"""
    if not a:
        return b
    if not b:
        return a
    if a.endswith("-") and b[:1].islower():
        return a[:-1] + b
    if CJK.search(a[-1]) or CJK.search(b[0]):
        return a + b
    return a + " " + b


def group_rows(lines: list[TextLine], tolerance: float = 0.6) -> list[list[TextLine]]:
    """同一视觉行被切成多块时先粘回去（按 y 中心聚类）。"""
    if not lines:
        return []
    ordered = sorted(lines, key=lambda ln: (ln.center_y, ln.box[0]))
    rows: list[list[TextLine]] = []
    for ln in ordered:
        if rows:
            last = rows[-1]
            ref_h = max(1, max(x.box[3] for x in last))
            if abs(ln.center_y - last[0].center_y) <= ref_h * tolerance:
                last.append(ln)
                continue
        rows.append([ln])
    for row in rows:
        row.sort(key=lambda x: x.box[0])
    return rows


def merge_lines(lines: list[TextLine], gap_ratio: float = 1.45) -> list[str]:
    """按段落聚合，返回若干段文本。"""
    rows = group_rows(lines)
    if not rows:
        return []

    paragraphs: list[str] = []
    buf = ""
    prev_row_bottom = None
    prev_row_height = 1

    for row in rows:
        row_text = ""
        for ln in row:
            row_text = _join(row_text, ln.text.strip())
        row_text = row_text.strip()
        if not row_text:
            continue
        row_h = max(1, max(x.box[3] for x in row))
        row_top = min(x.box[1] for x in row)

        if buf and prev_row_bottom is not None:
            gap = row_top - prev_row_bottom
            same_para = gap <= max(prev_row_height, row_h) * gap_ratio
            # 上一行已经说完一句话，就不硬拼
            ends_sentence = buf.rstrip().endswith(SENT_END)
            if not same_para or (ends_sentence and gap > row_h * 0.8):
                paragraphs.append(buf)
                buf = row_text
            else:
                buf = _join(buf, row_text)
        else:
            buf = row_text if not buf else _join(buf, row_text)

        prev_row_bottom = max(x.bottom for x in row)
        prev_row_height = row_h

    if buf:
        paragraphs.append(buf)
    return [p for p in paragraphs if p.strip()]


def collect_text(lines: list[TextLine], gap_ratio: float = 1.45) -> str:
    """整块输出为一段（结果窗原文区用）。"""
    return "\n\n".join(merge_lines(lines, gap_ratio))
