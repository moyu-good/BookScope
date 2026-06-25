"""章脉按需取证(ADR-010 出路 B 的"点开现取"核心)——纯检索,0 次 LLM。

章级锚视图(关系图/叙事流/时间线)的边/对/事件只钉到章号、不带 upfront 逐字证据。用户点开某条
时,从那一章原文里现找出支撑它的那一句原文。这里是检索原语:按词命中给章内句子打分、取最佳。
关系对传两个人名(优先两个都命中的句子),事件传事件描述的关键词。纯字符串匹配,不调 LLM、不要
GPU,贴 NORTH_STAR"查询时证据现场取 + 没原文不输出"。
"""

from __future__ import annotations

import re
from typing import Any

# 断句:中文句末标点 + 换行;保留标点跟句子一起,免得证据片段缺尾。
_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")


def chapter_text_map(chunks: list[dict[str, Any]]) -> dict[int, str]:
    """章号 → 该章全部 chunk 原文拼接。各章级锚视图(关系/伏笔/矛盾/概念/支线/节奏…)按需
    取证的共用入口:拿到这张表后,再用 ``evidence_for_pair`` / ``evidence_for_event`` 在对应章
    原文里现捞那一句。

    遍历 chunks,只收 ``chapter`` 是 int 且 ``text`` 非空的,同章多块按出现顺序换行拼接。
    """
    by_ch: dict[int, list[str]] = {}
    for c in chunks:
        ch = c.get("chapter")
        txt = str(c.get("text", ""))
        if isinstance(ch, int) and txt:
            by_ch.setdefault(ch, []).append(txt)
    return {ch: "\n".join(parts) for ch, parts in by_ch.items()}


def split_sentences(text: str) -> list[str]:
    """把一章原文切成句子(按中文句末标点/换行),去空白空句。"""
    if not text:
        return []
    return [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]


def _score(sentence: str, terms: list[str]) -> tuple[int, int]:
    """一句对一组词的得分:(命中几个不同词, -句长)。命中多优先,同命中数短句优先(更聚焦)。"""
    hit = sum(1 for t in terms if t and t in sentence)
    return (hit, -len(sentence))


def find_supporting_sentences(
    chapter_text: str,
    terms: list[str],
    top_k: int = 1,
) -> list[str]:
    """从一章原文里找最支撑这些词的句子,按命中数(同数短句优先)取前 top_k。

    一个词都没命中的句子不返(没原文支撑不输出)。terms 全空 → 返 []。
    关系对调用方传 ``[甲, 乙]``(优先两个都命中的句);事件传事件描述里的关键词。
    """
    terms = [t.strip() for t in terms if isinstance(t, str) and t.strip()]
    if not terms:
        return []
    scored = [
        (s, _score(s, terms)) for s in split_sentences(chapter_text)
    ]
    hits = [(s, sc) for s, sc in scored if sc[0] > 0]   # 至少命中一个词
    hits.sort(key=lambda x: x[1], reverse=True)
    return [s for s, _ in hits[:max(1, top_k)]]


def evidence_for_pair(chapter_text: str, a: str, b: str) -> str:
    """关系边按需取证:优先两个人名都出现的句子,没有则任一出现的;都没有返空串。"""
    both = find_supporting_sentences(chapter_text, [a, b], top_k=1)
    if both and a in both[0] and b in both[0]:
        return both[0]
    # 退而求其次:任一人名命中的最佳句(find_supporting_sentences 已按命中数排)
    return both[0] if both else ""


def evidence_for_event(chapter_text: str, event: str) -> str:
    """事件按需取证:事件描述拆成 2-gram 当 query 词,取与它字面重叠最多的一句。

    模型概括过的事件描述当不了精确子串(中文也没空格切词),用 2-gram 命中数衡量"哪句最像在
    讲这件事"——共享 bigram 越多越贴。一个 bigram 都不命中 → 返空(没原文支撑不输出)。
    """
    e = re.sub(r"\s+", "", event)
    bigrams = list({e[i : i + 2] for i in range(len(e) - 1)})
    hits = find_supporting_sentences(chapter_text, bigrams, top_k=1)
    return hits[0] if hits else ""


__all__ = [
    "chapter_text_map",
    "split_sentences",
    "find_supporting_sentences",
    "evidence_for_pair",
    "evidence_for_event",
]
