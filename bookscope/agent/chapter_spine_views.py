"""从章脉(ADR-010)派生各功能视图——纯计算,0 次 LLM。

章脉是整本一次精读出的带证据逐章结构(``chapter_spine.build_chapter_spine``)。本模块把它
投影/聚合成各功能要的形态,不再各自重跑全书。

**本文件目前只放"章级标量"视图**(叙事曲线 / 节奏)——它们要的 tension/sentiment/pov 章脉
直接有,满精度投影、没有开放问题。关系图 / 叙事流 / 时间线要"每条边/事件带逐字证据",而章脉
当前只到章级证据(给每条关系/事件加证据会让 spine 抽取输出暴涨、章闸要砍半),证据粒度怎么定
是 ADR-010 的开放问题(牵动立身之本),定了再在这里加。
"""

from __future__ import annotations

from typing import Any


def narrative_curve_from_spine(spine: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """叙事曲线视图:章脉逐章已有 tension/sentiment/pov/mainline/evidence/verified,直接投影。

    与 ``generate_narrative_curve_exhaustive`` 的产出同形,可 drop-in;但不再单独跑全书,
    从共享章脉来(0 次 LLM)。
    """
    out: list[dict[str, Any]] = []
    for rec in spine:
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        out.append({
            "chapter": ch,
            "tension": rec.get("tension", 0),
            "sentiment": rec.get("sentiment", 0),
            "pov": rec.get("pov", "群像"),
            "mainline": rec.get("mainline", True),
            "evidence": rec.get("evidence", ""),
            "verified": rec.get("verified", False),
            "match_score": rec.get("match_score", 0.0),
        })
    out.sort(key=lambda c: c["chapter"])
    return out


def _rescale_tension_10_to_5(t: Any) -> int:
    """章脉张力是 0-10,节奏视图历来用 1-5——线性压一下,钳到 1-5。"""
    try:
        n = int(round(float(t) / 2))
    except (TypeError, ValueError):
        n = 1
    return max(1, min(5, n))


def pacing_from_spine(spine: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """节奏曲线视图:章脉张力(0-10)压到 1-5,note 取本章第一个事件、没有就用 evidence。

    与 ``generate_pacing_curve`` 的产出同形(``{chapter, tension(1-5), note}``)。节奏和叙事
    曲线本就高度重叠,共享章脉后两者同源、不再各跑一遍。
    """
    out: list[dict[str, Any]] = []
    for rec in spine:
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        events = rec.get("events")
        note = ""
        if isinstance(events, list) and events:
            first = events[0]
            note = str(first.get("event", first) if isinstance(first, dict) else first).strip()
        if not note:
            note = str(rec.get("evidence", "")).strip()
        out.append({
            "chapter": ch,
            "tension": _rescale_tension_10_to_5(rec.get("tension", 0)),
            "note": note,
        })
    out.sort(key=lambda c: c["chapter"])
    return out


__all__ = [
    "narrative_curve_from_spine",
    "pacing_from_spine",
]
