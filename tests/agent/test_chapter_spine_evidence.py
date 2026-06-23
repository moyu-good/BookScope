"""章脉按需取证(ADR-010 出路 B)单测 —— 纯检索,不调 LLM。"""

from __future__ import annotations

from bookscope.agent.chapter_spine_evidence import (
    evidence_for_event,
    evidence_for_pair,
    find_supporting_sentences,
    split_sentences,
)

_CH = "桃园之中，备下乌牛白马。刘备、关羽、张飞焚香再拜结义。次日，曹操引兵来犯。张飞大怒。"


def test_split_sentences_keeps_punctuation() -> None:
    sents = split_sentences(_CH)
    assert "刘备、关羽、张飞焚香再拜结义。" in sents
    assert all(s.strip() for s in sents)


def test_find_supporting_prefers_more_hits() -> None:
    # 刘备+关羽 都命中的句排在只命中一个的前面
    out = find_supporting_sentences(_CH, ["刘备", "关羽"], top_k=1)
    assert out and "刘备" in out[0] and "关羽" in out[0]


def test_find_supporting_empty_terms_returns_empty() -> None:
    assert find_supporting_sentences(_CH, []) == []
    assert find_supporting_sentences(_CH, ["   "]) == []


def test_find_supporting_no_hit_returns_empty() -> None:
    assert find_supporting_sentences(_CH, ["诸葛亮"]) == []   # 本章没这人 → 不输出


def test_evidence_for_pair_both_names() -> None:
    ev = evidence_for_pair(_CH, "刘备", "关羽")
    assert "刘备" in ev and "关羽" in ev


def test_evidence_for_pair_no_hit_empty() -> None:
    assert evidence_for_pair(_CH, "孙权", "周瑜") == ""    # 都不在本章 → 空


def test_evidence_for_event_matches_keywords() -> None:
    # 章脉的事件是模型给的较完整描述(非极端缩写),bigram 跟原文重叠多的句胜出
    ev = evidence_for_event(_CH, "刘备关羽张飞桃园结义")
    assert "结义" in ev
