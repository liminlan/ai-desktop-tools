"""OCR 英文结果的文本修复。

Windows OCR 对英文有三类典型损伤，不修会直接影响翻译：
1. 粘连：'a lot over' 被认成 'lOtover'、'past few' 认成 'pastfew'
2. 被切开：'improved' 认成 'imp roved'、'years' 认成 'yea rs'、'are' 认成 'a re'
3. 大小写抖动：句子中间冒出 'lOt'

修复靠 wordninja（纯离线英文词频词典，约 1MB）判断"这个词到底存不存在"：
- 两个片段拼起来是个真词 -> 合并
- 一个长词在词典里查不到 -> 按词典切开

这样 'a lot'、'in fact' 这类正常双词不会被误合并（'alot'、'infact' 不在词典）。
"""
from __future__ import annotations

import re

import wordninja

WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
CJK_RE = re.compile(r"[\u3400-\u9fff\u3000-\u303f\uff01-\uff60]")


# 这些短词是真实存在的独立词，不能跟前一个词粘起来（否则 "in fact" 会被错并成 "infact"）
COMMON_SHORT = set("""
a an the of in to is it on at by or as be we he my up do if no so am us me
i and but for with you are not had has was were they that this from have will
been your what when which their there would could should about into than then
them these those such also just more most some only over very well make made
like time year years first last new old way day days may can one two three
four five six ten all any each few own same too out off now get got let see
say go going come came know take took give gave find find found tell told
use used work works part parts even back still here why how who whom whose
every other under above after before while where both much many once again
away else ever home less next open past per put run set show side since
""".split())


def _is_alpha(tok: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z']+", tok))


def in_lexicon(word: str) -> bool:
    """这个词是否能被词典完整解释（不被切碎）。"""
    low = word.lower()
    return wordninja.split(low) == [low]


def fix_glued_words(text: str) -> str:
    # 先把标点独立成 token，否则 "yea rs," 里的逗号会让 "rs" 判不出是字母
    text = re.sub(r"([,.;:!?])", r" \1 ", text)
    tokens = text.split()
    out: list[str] = []
    i = 0
    while i < len(tokens):
        cur = tokens[i]

        # 1) 相邻两段拼起来是真词 -> 粘回去（imp+roved、yea+rs、a+re、netwo+rk）
        if i + 1 < len(tokens) and _is_alpha(cur) and _is_alpha(tokens[i + 1]):
            nxt = tokens[i + 1]
            cand = cur + nxt
            standalone = len(cur) > 1 and cur.lower() in COMMON_SHORT
            if len(cand) >= 3 and in_lexicon(cand) and len(cur) <= 5 and not standalone:
                out.append(cand)
                i += 2
                continue

        # 2) 长且词典查不到的小写词 -> 按词典切开（lOtover、pastfew、goodenough）
        if _is_alpha(cur) and len(cur) >= 7 and cur[0].islower() and not in_lexicon(cur):
            parts = wordninja.split(cur.lower())
            if 1 < len(parts) <= 3 and all(len(p) >= 2 for p in parts):
                out.extend(parts)
                i += 1
                continue

        out.append(cur)
        i += 1
    return re.sub(r"\s+([,.;:!?])", r"\1", " ".join(out))


def fix_case_glitch(text: str) -> str:
    """短词内部出现大写（lOt、wOrd）就转小写；全大写缩写和长专有名词不动。"""

    def repl(match: re.Match) -> str:
        word = match.group(0)
        if len(word) <= 4 and not word.isupper() and any(c.isupper() for c in word[1:]):
            return word.lower()
        return word

    return WORD_RE.sub(repl, text)


def tidy_punctuation(text: str) -> str:
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def fix_english(text: str) -> str:
    if not text:
        return text
    return tidy_punctuation(fix_case_glitch(fix_glued_words(text)))


def english_ratio(text: str) -> float:
    body = re.sub(r"\s", "", text)
    if not body:
        return 0.0
    return len(re.findall(r"[A-Za-z]", body)) / len(body)


def keep_english_line(text: str, threshold: float = 0.55, min_letters: int = 2) -> bool:
    """过滤窗口标题栏、中文菜单这类噪声行。"""
    if len(re.findall(r"[A-Za-z]", text)) < min_letters:
        return False
    body = re.sub(r"\s", "", text)
    cjk = len(CJK_RE.findall(body))
    # 明显中英混排的行（标题栏、菜单栏）直接丢掉，翻译价值低还会污染上下文
    if cjk >= 2 and cjk / max(1, len(body)) >= 0.2:
        return False
    return english_ratio(text) >= threshold
