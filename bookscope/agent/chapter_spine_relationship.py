"""关系演变 = 章脉派生(逐对一次全局推理)。ADR-010 出路 B 的又一个视图。

**为什么有这个模块**:关系演变的命根子是"截至此章这对人多紧"——**这是累积量**:判第 N 章
刘备和曹操多紧,得知道前面 1..N 章他俩之间一路发生过什么(煮酒论英雄、反目、各自割据)。
老实现 ``generate_relationship_timeline_exhaustive`` 是 map-reduce 逐段跑的,每段只看得见自己
那几章——第三段打"截至第 N 章多紧"时根本不知道第一段他俩有过什么,各段各自打分再按章拼,
≠ 全程累积判断。强度曲线和转折点因此都不可信(这是范式错,不只大书才犯)。

做法:章脉每章 ``relations`` 里有这对人**这一章**什么关系/发生了什么(``{pair, note}``)。
本模块按无向人物对收齐每对的**逐章 note 序列**(按章序),然后**逐对一次 LLM 全局推理**——
把这对人从头到尾每章发生了什么一次性喂进去,让模型看完全程才打"逐章累积强度曲线 + 转折点"。
一对人发一次、看的是这对人的完整轨迹,不像 map-reduce 跨段瞎。

**为什么逐对发而不是一次发全部关系**:一对的逐章 note 序列就是这对人的完整传记,逐对发让
模型聚焦一对、判得准;一次塞几十对会互相干扰、且 reasoning 模型 max_tokens 容易爆。逐对走
L2 缓存按这对的 note 清单命中,同书重开零成本。

**便宜 + 稳**:只发每对的逐章 note(不发原文),走 ``invoke_client_cached`` 按清单缓存。某对
推理失败 / 解析不出 → 跳过这对(不 break 整体);全失败 → 返 None,端点照走。转折 evidence
取相关章章脉那条已核验的章级 evidence,再走 ``verify_citations`` 附 verified/match_score
(同 ``relationship_timeline``,evidence-first:核不过的转折标灰、不当确定结论画)。
人名先过 ``build_spine_name_map`` 别名合并,免得同一人(玄德/刘备/先主)碎成好几对。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.chapter_spine_canon import build_spine_name_map
from bookscope.agent.chapter_spine_views import _canon, _norm_pair
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_CURVE_MAX_TOKENS = 8000
"""单对的逐章强度曲线 + 转折比一张全局图小——一对人一次发,8000 留 reasoning 头够用。

deepseek-v4-flash 把 reasoning_content 算进 max_tokens(见
[[reference_reasoning_model_token_budget]])。这里每次只判一对人、输入是这对人的逐章 note
清单(几十条),输出一条强度曲线 + 几个转折,8000 覆盖三国最戏份重的对 + 余量;真撑爆靠
``_parse_curve`` 截断抢救兜底。"""

MAX_PAIRS = 30
"""一本书逐对全局推理最多跑前多少对(按出场章数排)。

每对一次 LLM 调用,成本随对数线性涨;但只跑 14 对就太少(旧版 132 对、前端还有「看全部」按钮)。
取戏份最重的前 30 对——盖住三国这类大书里真正有演变的对(≥2 章互动的有意义对约 30-50),前端
小多图默认显 top14、点「看全部」看到全部 30。长尾只 1 章露面的对没演变可言,``MIN_CHAPTERS_PER_PAIR``
已滤掉。要更省可调低、要更全可调高——这是成本 vs 丰富度的权衡点。"""

MIN_CHAPTERS_PER_PAIR = 2
"""一对人至少在几章里有互动 note 才值得画曲线。只在 1 章露过面的对没"演变"可言,跳过。"""

_CURVE_INSTR = (
    "下面是一本书里**同一对人物**从头到尾、按章节顺序发生的事(notes 数组,每条带章号)。\n"
    "请通读这对人的**完整轨迹**,判断他们关系随章节怎么一章章变,给出:\n"
    "1. relation:这两人是什么关系(君臣/政敌/父子/同盟/师徒等)。全程性质有变就填最有代表性的那种。\n"
    "2. points:逐章强度曲线,列若干 {chapter, strength}。strength 是**截至这一章**两人关系有多紧"
    "(0-10 整数,越大越紧)——这是累积判断:要结合这章之前他俩一路发生过的事来定,不是只看这一章。\n"
    "   只在关系**确实有变化**的章给点;没什么变化的平段不必逐章给点(曲线在那段就是平的)。\n"
    "3. turning_points:关系**真正发生明显变化**的章——初识、结盟、升温、决裂、和解、顶峰等。"
    "每个给 {chapter, change(一句话说这章他俩之间发生了什么导致关系变)}。\n"
    "**只依据给出的 notes,不臆测、不编造。全程平稳没大变化的,turning_points 留空,绝不为凑数编"
    "不存在的拐点;关系明明越来越近的别判成越走越远——方向以 notes 为准。**\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"relation":"关系性质","points":[{"chapter":章号整数,"strength":0-10整数}],'
    '"turning_points":[{"chapter":章号整数,"change":"这章发生了什么"}]}'
)


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    """把模型给的数值钳到 [lo, hi] 整数;非数 / 缺失退 default。"""
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _collect_pair_notes(
    spine: list[dict[str, Any]], name_map: dict[str, str] | None
) -> tuple[dict[tuple[str, str], list[dict[str, Any]]], dict[int, str]]:
    """从章脉收每对(canonical 化后无向)关系的**逐章 note 序列** + 章级证据表。

    返回 (pair → [{chapter, note}](按章升序), 章号 → 章级 evidence)。
    一对人同章多条 note 合成一条(用换行拼),保证一对一章一个点。
    """
    pair_notes: dict[tuple[str, str], dict[int, list[str]]] = {}
    evidence: dict[int, str] = {}
    for rec in spine:
        if not isinstance(rec, dict):
            continue
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        ev = str(rec.get("evidence", "")).strip()
        if ev and ch not in evidence:
            evidence[ch] = ev
        for rel in rec.get("relations") or []:
            if not isinstance(rel, dict):
                continue
            pair = rel.get("pair")
            if not (isinstance(pair, list) and len(pair) == 2):
                continue
            a, b = _canon(str(pair[0]), name_map), _canon(str(pair[1]), name_map)
            if not a or not b or a == b:
                continue
            note = str(rel.get("note", "")).strip()
            if not note:
                continue
            key = _norm_pair(a, b)
            pair_notes.setdefault(key, {}).setdefault(ch, []).append(note)

    collected: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for key, by_ch in pair_notes.items():
        seq = [
            {"chapter": ch, "note": "；".join(notes)}
            for ch, notes in sorted(by_ch.items())
        ]
        collected[key] = seq
    return collected, evidence


def _coerce_points(raw: Any) -> list[dict[str, Any]]:
    """逐章强度点归一成 ``[{chapter:int, strength:0-10}]``;去重同章号、按章号升序。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for p in raw:
        if not isinstance(p, dict):
            continue
        ch = p.get("chapter")
        if not isinstance(ch, int) or ch in seen:
            continue
        seen.add(ch)
        out.append({"chapter": ch, "strength": _clamp_int(p.get("strength"), 0, 10, 0)})
    out.sort(key=lambda x: x["chapter"])
    return out


def _coerce_turning_points(raw: Any, fallback_chapter: int) -> list[dict[str, Any]]:
    """转折点归一成 ``[{chapter:int, change:str}]``(evidence 后面从章脉补);按章号升序。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for tp in raw:
        if not isinstance(tp, dict):
            continue
        ch = tp.get("chapter")
        chapter = ch if isinstance(ch, int) else fallback_chapter
        out.append({"chapter": chapter, "change": str(tp.get("change", "")).strip()})
    out.sort(key=lambda x: x["chapter"])
    return out


def _parse_curve(text: str) -> dict[str, Any] | None:
    """解析单对的 ``{relation, points, turning_points}``;三层兜底(直解析 / 切首个对象 / 抢救)。"""
    raw = (text or "").strip()
    if not raw:
        return None
    candidate = strip_code_fence(raw)
    obj: Any = None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        sliced = extract_first_json_object(candidate)
        if sliced is not None:
            try:
                obj = json.loads(sliced)
            except json.JSONDecodeError:
                obj = None
    if isinstance(obj, dict) and ("points" in obj or "turning_points" in obj):
        return obj
    # 截断抢救:从半截 JSON 里把 points 数组里已闭合的点抠出来,转折同理。
    salvaged_points = salvage_closed_objects(candidate, '"points"')
    salvaged_tps = salvage_closed_objects(candidate, '"turning_points"')
    if salvaged_points or salvaged_tps:
        logger.warning("chapter_spine_relationship: 单对主解析失败,从截断抢救")
        return {"points": salvaged_points or [], "turning_points": salvaged_tps or []}
    return None


def _build_one_relation(
    *,
    a: str,
    b: str,
    notes: list[dict[str, Any]],
    chapters_with_note: set[int],
    llm_client: Any,
    model: str,
    max_tokens: int,
    cache_enabled: bool,
) -> dict[str, Any] | None:
    """对一对人发一次全局推理 → 归一成 ``{a, b, relation, points, turning_points}``;失败返 None。

    points 章号锚到这对人真有 note 的章(防 LLM 编章号);转折章号同样夹回真有 note 的章,
    超界的退到最近一条 note 的章。转折 evidence 在调用方从章脉补 + 核验。
    """
    user_content = json.dumps({"notes": notes}, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_CURVE_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 单对失败跳过,不 break 整体
        logger.warning(
            "chapter_spine_relationship: %s—%s 推理抛 %s: %s;跳过这对",
            a, b, type(exc).__name__, exc,
        )
        return None

    parsed = _parse_curve(text)
    if parsed is None:
        return None

    points = [p for p in _coerce_points(parsed.get("points")) if p["chapter"] in chapters_with_note]
    first_ch = points[0]["chapter"] if points else (notes[0]["chapter"] if notes else 0)
    tps = _coerce_turning_points(parsed.get("turning_points"), first_ch)
    # 转折章号锚到真有 note 的章:命中直接用,没命中退到最近一条 note 的章(仍知道大概在哪)。
    sorted_note_chs = sorted(chapters_with_note)
    for tp in tps:
        if tp["chapter"] not in chapters_with_note and sorted_note_chs:
            tp["chapter"] = min(sorted_note_chs, key=lambda c: abs(c - tp["chapter"]))
    if not points and not tps:
        return None
    return {
        "a": a,
        "b": b,
        "relation": str(parsed.get("relation", "")).strip(),
        "points": points,
        "turning_points": tps,
    }


def _attach_and_verify_evidence(
    relations: list[dict[str, Any]],
    chapter_evidence: dict[int, str],
    chunks: list[dict[str, Any]],
) -> None:
    """每个转折从章脉补该章 evidence 当 citation,过 verify_citations 附 verified/match_score。

    章脉的章级 evidence 本就是从原文摘的已核验那一句,拿它当转折 evidence(章级锚):命中 →
    verified=True + 用命中 chunk 的真章号纠偏;没命中 → verified=False + 退回原章号(FE 标灰)。
    同 ``relationship_timeline._verify_turning_points``,evidence-first。
    """
    evidence_map = build_evidence_map(chunks)
    for rel in relations:
        tps = rel["turning_points"]
        for tp in tps:
            tp["evidence"] = chapter_evidence.get(tp["chapter"], "")
        tp_citations = [{"snippet": tp["evidence"], "chapter": tp["chapter"]} for tp in tps]
        verify_citations(tp_citations, evidence_map)
        for tp, vc in zip(tps, tp_citations, strict=True):
            tp["verified"] = bool(vc.get("verified", False))
            tp["match_score"] = vc.get("match_score", 0.0)
            cid = vc.get("chunk_id")
            true_chapter = evidence_map.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_chapter, int) and true_chapter > 0:
                tp["chapter"] = true_chapter  # 命中 chunk 的真章号纠偏
        tps.sort(key=lambda t: t["chapter"])  # 纠偏后可能乱序,再排一次


def relationship_timeline_from_spine(
    *,
    spine: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    name_map: dict[str, str] | None = None,
    max_pairs: int = MAX_PAIRS,
    max_tokens: int = DEFAULT_CURVE_MAX_TOKENS,
    cache_enabled: bool = True,
) -> dict[str, Any] | None:
    """章脉派生关系演变:逐对收逐章 note → 逐对一次全局推理 → 强度曲线 + 转折 + 核验。

    每对人**一次性**把全程逐章 note 喂进去判累积强度——修了 map-reduce 逐段看不见别段、
    累积量打错的范式错。

    Args:
        spine: 章脉(``get_or_build_spine`` 的产出),每章 ``relations`` 为 ``[{pair, note}]``。
        chunks: 全书 chunk(含 ``chunk_id`` / ``chapter`` / ``text``),给转折 evidence 核验。
        llm_client: duck-typed LLM client(同 AgentLoop)。
        model: 模型名。
        name_map: 别名→canonical 表;不传则内部用 ``build_spine_name_map`` 自建(合并 玄德/刘备)。
        max_pairs: 最多跑戏份最重的前几对(默认 14,盖住前端默认显示量)。
        max_tokens: 单对 LLM 调用 max_tokens。
        cache_enabled: 单对调用是否走 L2 缓存(默认开,同书重开零成本)。

    Returns:
        ``{"relations": [{"a", "b", "relation", "points": [{chapter, strength}],
        "turning_points": [{chapter, change, evidence, verified, match_score}]}]}``;
        全部失败或没有可画的对 → ``None``(契约同 ``generate_relationship_timeline``)。
    """
    if name_map is None:
        name_map = build_spine_name_map(spine=spine, llm_client=llm_client, model=model)

    pair_notes, chapter_evidence = _collect_pair_notes(spine, name_map)
    if not pair_notes:
        return None

    # 戏份最重的前 max_pairs 对:按"有互动的章数"排(同分按对名,确定性→缓存 key 稳)。
    eligible = [
        (key, seq) for key, seq in pair_notes.items() if len(seq) >= MIN_CHAPTERS_PER_PAIR
    ]
    eligible.sort(key=lambda kv: (-len(kv[1]), kv[0]))
    eligible = eligible[:max_pairs]
    if not eligible:
        return None

    relations: list[dict[str, Any]] = []
    for (a, b), seq in eligible:
        chapters_with_note = {p["chapter"] for p in seq}
        rel = _build_one_relation(
            a=a,
            b=b,
            notes=seq,
            chapters_with_note=chapters_with_note,
            llm_client=llm_client,
            model=model,
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        if rel is not None:
            relations.append(rel)

    if not relations:
        return None

    _attach_and_verify_evidence(relations, chapter_evidence, chunks)
    return {"relations": relations}


__all__ = [
    "DEFAULT_CURVE_MAX_TOKENS",
    "MAX_PAIRS",
    "MIN_CHAPTERS_PER_PAIR",
    "relationship_timeline_from_spine",
]
