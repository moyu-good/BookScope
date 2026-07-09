"""从章脉(ADR-010)派生各功能视图——纯计算,0 次 LLM。

章脉是整本一次精读出的带证据逐章结构(``chapter_spine.build_chapter_spine``)。本模块把它
投影/聚合成各功能要的形态,不再各自重跑全书。

两类视图:
- **章级标量**(叙事曲线 / 节奏):tension/sentiment/pov 章脉直接有,满精度投影。
- **章级锚**(关系图 / 叙事流 / 时间线,ADR-010 D-2 出路 B,作者 2026-06-23 拍 B):边/对/事件
  不带 upfront 逐字证据(那要把 spine 抽取输出翻倍),改成钉到章号;前端点开某条时调按需取证
  端点现取那一句精确原文(贴 NORTH_STAR"查询时证据现场取")。按需取证端点 + 缓存接线是后续步。
"""

from __future__ import annotations

from typing import Any

from bookscope.agent.chapter_spine_evidence import (
    chapter_text_map as _chapter_text_map,
)
from bookscope.agent.chapter_spine_evidence import evidence_for_event


def _tension_query(rec: dict[str, Any]) -> str:
    """拼"这章为什么紧"的检索词:本章首个事件 + 各人物处境,拿去原文里捞真讲这件事的那句。

    张力高/低是情节判定,本章 events 首条最能代表"这章发生了什么"、char_states 补"谁处境如何",
    合起来当 query 比章代表句精准——章代表句只是"这章最显眼那件事",未必关乎这章的张力来源。
    """
    parts: list[str] = []
    events = rec.get("events")
    if isinstance(events, list) and events:
        first = events[0]
        text = str(first.get("event", first) if isinstance(first, dict) else first).strip()
        if text:
            parts.append(text)
    states = rec.get("char_states")
    if isinstance(states, list):
        for st in states:
            if isinstance(st, dict):
                s = str(st.get("state", "")).strip()
                if s:
                    parts.append(s)
    return " ".join(parts)


def _event_text(ev: Any) -> str:
    """章脉 events 一条:可能是字符串、也可能是 {event: ...},归一成一句话文本。"""
    return str(ev.get("event", ev) if isinstance(ev, dict) else ev).strip()


def _chapter_events(rec: dict[str, Any], chapter_text: str | None) -> list[dict[str, Any]]:
    """把一章的 events 摊成 ``[{text, evidence, verified}]``,每条事件回该章原文现捞一句。

    事件文本是模型概括的一句话,当不了精确子串;有原文(``chapter_text`` 非 None)时走
    ``evidence_for_event``(2-gram 命中)在该章里捞最像在讲这件事的那句,捞到 → verified=True、
    捞不到 → 空串 + verified=False(FE 标"待核",不硬塞无关原文)。``chapter_text=None`` 时不取证
    (evidence 空、verified=False)。
    """
    out: list[dict[str, Any]] = []
    for ev in rec.get("events") or []:
        text = _event_text(ev)
        if not text:
            continue
        evidence = evidence_for_event(chapter_text, text) if chapter_text else ""
        out.append({"text": text, "evidence": evidence, "verified": bool(evidence)})
    return out


def _chapter_turnings(rec: dict[str, Any], chapter_text: str | None) -> list[dict[str, Any]]:
    """把一章的 foreshadow 收束(payoff)当"转折"摊成 ``[{hook, kind, evidence, verified}]``。

    章脉没有逐章 ``turning_points`` 字段(plot 维只有 events/tension/.../foreshadow);最贴近
    "这章发生了转折"的可数、可锚信号是伏笔 **收束**——一条伏笔在这章被收掉,就是一个结构上的转折
    点。埋(setup)不算转折(只是埋线),只收(payoff)算。每条回该章原文现捞证据(同 events)。
    """
    out: list[dict[str, Any]] = []
    for fs in rec.get("foreshadow") or []:
        if not isinstance(fs, dict):
            continue
        if str(fs.get("type", "")).strip() != "收":
            continue
        hook = str(fs.get("hook", "")).strip()
        if not hook:
            continue
        evidence = evidence_for_event(chapter_text, hook) if chapter_text else ""
        out.append({"hook": hook, "kind": "收", "evidence": evidence, "verified": bool(evidence)})
    return out


def narrative_curve_from_spine(
    spine: list[dict[str, Any]],
    chunks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """叙事曲线视图:纵轴 = 这章能数出来的事(事件数 + 转折数),不是模型眼估的张力标量。

    1.5.x 重做(作者拍板):旧版纵轴画的是 tension(0-10,模型一句话糊的标量,probe 实测绝对分跨次
    抖 ±1、不可信),跟节奏曲线画的是同一个东西、重复。新版纵轴换成"能锚到原文、能数的事":

    - ``event_count`` = 这章 ``events`` 条数(章脉情节维逐章抽的关键事件)。
    - ``turning_count`` = 这章伏笔 **收束** 条数(章脉没有逐章 turning_points 字段,伏笔收掉=结构
      转折,是最贴近"转折"的可数信号;埋线不算)。
    - ``height`` = event_count + turning_count(前端画的高度),全是数出来的、每条能回原文核验。
    - ``is_turning`` = turning_count > 0 → 前端朱砂点标"这章有转折"。
    - ``events`` / ``turning_points``:逐条 ``{..., evidence, verified}``,点开看原文(复用按需取证)。

    tension/sentiment/pov/mainline 仍带回,但只进选中章明细标"模型判读",**绝不再当纵轴**。

    传 ``chunks``(全书原文)时每条事件/转折回该章原文现捞证据;``chunks=None`` 时不取证(evidence
    空、verified=False),向后兼容、不报错。
    """
    chapter_text = _chapter_text_map(chunks) if chunks is not None else None
    out: list[dict[str, Any]] = []
    for rec in spine:
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        ct = chapter_text.get(ch, "") if chapter_text is not None else None
        events = _chapter_events(rec, ct)
        turnings = _chapter_turnings(rec, ct)
        out.append({
            "chapter": ch,
            "event_count": len(events),
            "turning_count": len(turnings),
            "height": len(events) + len(turnings),
            "is_turning": bool(turnings),
            "events": events,
            "turning_points": turnings,
            # 以下三维只进选中章明细(标"模型判读"),不当纵轴:
            "tension": rec.get("tension", 0),
            "sentiment": rec.get("sentiment", 0),
            "pov": rec.get("pov", "群像"),
            "mainline": rec.get("mainline", True),
            # 章代表句兜底(events 全空的"平铺过渡"章,明细里仍有一句可看):
            "evidence": str(rec.get("evidence", "")).strip(),
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


def pacing_from_spine(
    spine: list[dict[str, Any]],
    chunks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """节奏曲线视图:章脉张力(0-10)压到 1-5,note 取本章第一个事件、没有就现捞。

    与 ``generate_pacing_curve`` 的产出同形(``{chapter, tension(1-5), note}``)。节奏和叙事
    曲线本就高度重叠,共享章脉后两者同源、不再各跑一遍。

    note 优先用本章首个事件(那本就是"这章发生了什么"、不是章代表句)。没有事件时:传
    ``chunks`` 则按"这章为什么紧/缓"在该章原文里现捞(同叙事曲线,走 ``evidence_for_event``),
    捞不到留空;``chunks=None``(默认)退回章代表句 ``rec.get("evidence")``、保持老行为。
    """
    chapter_text = _chapter_text_map(chunks) if chunks is not None else None
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
            if chapter_text is not None:
                note = evidence_for_event(chapter_text.get(ch, ""), _tension_query(rec))
            else:
                note = str(rec.get("evidence", "")).strip()
        out.append({
            "chapter": ch,
            "tension": _rescale_tension_10_to_5(rec.get("tension", 0)),
            "note": note,
        })
    out.sort(key=lambda c: c["chapter"])
    return out


# ── 章级锚视图(ADR-010 D-2 出路 B:章脉只记"这条在第几章",证据点开现取)─────────
#
# 关系图 / 叙事流 / 时间线的边/对/事件不带 upfront 逐字证据(那要把 spine 抽取输出翻倍),
# 改成钉到章号;前端点开某条边/事件时,调按需取证端点现取那一句精确原文(贴 NORTH_STAR
# "查询时证据现场取")。所以下面的派生不产 evidence 字段,只产章级锚 + 描述。


def _norm_pair(a: str, b: str) -> tuple[str, str]:
    """无向对归一成 (小, 大),让 甲-乙 和 乙-甲 合到一条边。"""
    return (a, b) if a <= b else (b, a)


def _canon(name: str, name_map: dict[str, str] | None) -> str:
    """别名合并:玄德/先主 → 刘备(用 KG 的 别名→canonical 表)。没表或没命中就原样。

    章脉的 relations/present 是逐章抽的,模型每章可能给不同称呼(玄德/刘备/先主),不合并就
    碎成好几个节点(三国实测 702 节点,其中大量别名碎裂)。老的专门抽边路径喂 KG canonical 表
    合并过,迁章脉时丢了这步——这里补回来(ADR-010 整合发现的隐患)。
    """
    n = name.strip()
    return name_map.get(n, n) if name_map else n


def relationship_graph_from_spine(
    spine: list[dict[str, Any]],
    name_map: dict[str, str] | None = None,
    top_n: int | None = None,
) -> dict[str, Any]:
    """关系图视图:把章脉逐章 relations 聚合成 nodes + edges(章级锚,证据点开现取)。

    edge = 一对人物跨章的并集:``{source, target, chapters:[出现的章], notes:[每章一句], weight}``,
    章脉 v2 起再带 ``rel_type``(主导关系类型·跨章众数)+ ``valence``(综合敌友·跨章均值 -5..5);
    旧缓存(v1)没这俩,边就不带,前端退回现有(共现粗细 + 兜底色)。
    weight = 出现章数(画粗细)。节点 = 所有露面人物。不带 upfront evidence(出路 B)。
    ``name_map``(别名→canonical,来自 KG)合并 玄德/刘备/先主 这类碎裂别名。

    **默认展示整本书的完整关系网**:只去掉"没抽到任何关系的孤立点"(关系图本就该画有关系的人;
    present 里露过面但没进任何 relation 的人留在章脉、不画进图)。一百多回的书有几百号人有关系,
    就画几百个——不设人数帽(密不密是前端显示/缩放的事,不在这里丢数据)。

    ``top_n`` 可选,**默认 None=不砍**;只在调用方明确要"只看主干"时按连接度取前 top_n。曾经默认
    砍到 40 是错的(一百多回的书哪可能只有 40 个人),已去掉。
    """
    nodes: dict[str, int] = {}          # name -> 出现次数(节点大小)
    edges: dict[tuple[str, str], dict[str, Any]] = {}
    for rec in spine:
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        for name in rec.get("present", []) or []:
            if isinstance(name, str) and name.strip():
                cn = _canon(name, name_map)
                nodes[cn] = nodes.get(cn, 0) + 1
        for rel in rec.get("relations", []) or []:
            if not isinstance(rel, dict):
                continue
            pair = rel.get("pair")
            if not (isinstance(pair, list) and len(pair) == 2):
                continue
            a, b = _canon(str(pair[0]), name_map), _canon(str(pair[1]), name_map)
            if not a or not b or a == b:
                continue
            key = _norm_pair(a, b)
            e = edges.setdefault(key, {"source": key[0], "target": key[1],
                                       "chapters": [], "notes": [], "weight": 0,
                                       "types": [], "valences": []})
            if ch not in e["chapters"]:
                e["chapters"].append(ch)
                e["weight"] += 1
            note = str(rel.get("note", "")).strip()
            if note:
                e["notes"].append(note)
            # v2(WP-relationship-depth,probe exp025 GO):关系带 type/valence 就收集,
            # 聚合成边的主导类型 + 综合敌友;旧缓存(v1)没这俩 → 空 → 边不带、前端退现有。
            rtype = str(rel.get("type", "")).strip()
            if rtype and rtype != "其他":
                e["types"].append(rtype)
            val = rel.get("valence")
            if isinstance(val, (int, float)) and not isinstance(val, bool):
                e["valences"].append(float(val))
    for e in edges.values():
        e["chapters"].sort()
        types = e.pop("types")
        vals = e.pop("valences")
        if types:
            e["rel_type"] = max(set(types), key=types.count)  # 主导关系类型(跨章众数)
        if vals:
            e["valence"] = round(sum(vals) / len(vals))  # 综合敌友(跨章均值,-5..5)

    # 只画有关系的人(关系图本义):去掉没进任何边的孤立点。不设人数帽,几百号人有关系就画几百个。
    connected = {e["source"] for e in edges.values()} | {e["target"] for e in edges.values()}
    nodes = {n: c for n, c in nodes.items() if n in connected}

    if top_n is not None and len(nodes) > top_n:
        # 调用方明确要主干时才砍:按连接度(节点上所有边的 weight 之和)取前 top_n,同分用 mentions 兜底
        degree: dict[str, int] = {}
        for e in edges.values():
            degree[e["source"]] = degree.get(e["source"], 0) + e["weight"]
            degree[e["target"]] = degree.get(e["target"], 0) + e["weight"]
        kept = set(
            sorted(nodes, key=lambda n: (degree.get(n, 0), nodes[n]), reverse=True)[:top_n]
        )
        nodes = {n: c for n, c in nodes.items() if n in kept}
        edges = {k: e for k, e in edges.items() if e["source"] in kept and e["target"] in kept}

    return {
        "nodes": [{"name": n, "mentions": c} for n, c in sorted(nodes.items())],
        "edges": sorted(edges.values(), key=lambda e: (-e["weight"], e["source"])),
    }


def narrative_flow_from_spine(
    spine: list[dict[str, Any]], name_map: dict[str, str] | None = None
) -> list[dict[str, Any]]:
    """叙事流视图:逐章 ``{chapter, present:[人名], pairs:[{a,b}]}``(章级锚,证据点开现取)。

    ``name_map``(别名→canonical,来自 KG)合并 玄德/刘备 这类碎裂别名(同关系图)。
    """
    out: list[dict[str, Any]] = []
    for rec in spine:
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        present_seen: dict[str, None] = {}
        for n in rec.get("present") or []:
            cn = _canon(str(n), name_map)
            if cn:
                present_seen.setdefault(cn, None)
        present = list(present_seen)
        pairs: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for rel in rec.get("relations", []) or []:
            if not isinstance(rel, dict):
                continue
            pair = rel.get("pair")
            if not (isinstance(pair, list) and len(pair) == 2):
                continue
            a, b = _canon(str(pair[0]), name_map), _canon(str(pair[1]), name_map)
            if not a or not b or a == b:
                continue
            key = _norm_pair(a, b)
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"a": a, "b": b})
        out.append({"chapter": ch, "present": present, "pairs": pairs})
    out.sort(key=lambda c: c["chapter"])
    return out


def timeline_from_spine(spine: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """时间线视图:把章脉逐章 events 摊平成按章升序的事件列表(章级锚,证据点开现取)。

    ``[{order, chapter, event}]``——time / evidence 不在这里产(时间靠章序,证据点开现取)。
    """
    out: list[dict[str, Any]] = []
    for rec in sorted(spine, key=lambda r: r.get("chapter", 0)):
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        for ev in rec.get("events", []) or []:
            text = str(ev.get("event", ev) if isinstance(ev, dict) else ev).strip()
            if text:
                out.append({"order": len(out) + 1, "chapter": ch, "event": text})
    return out


__all__ = [
    "narrative_curve_from_spine",
    "pacing_from_spine",
    "relationship_graph_from_spine",
    "narrative_flow_from_spine",
    "timeline_from_spine",
]
