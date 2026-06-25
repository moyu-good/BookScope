"""关系演变 = 章脉派生的「关系编年」(逐对一次全局推理)。ADR-010 出路 B 的又一个视图。

**1.5.1 重做(2026-06-25,作者认的方向)**:旧版把一对关系压成"一个 frozen relation 类型 +
每章一个 strength 0-10 标量",作者反复"不对"——根因是**抽象**:把关系压成一根不可信的线,
跟关系图(星图)撞脸、没存在价值。新方向**不抽象**,做成一对人的**关系编年**:

1. **整体判断(verdict)**:站在全书高度先给这对关系下个评点式总论——本质一句话、总体走向、
   不对称(两人对彼此看法是否不同,对称就不拆)、最尖锐的一笔。不是逐幕拼的,是看完全程的综合。
2. **逐幕编年(beats)**:这对人**每一个有戏的章**都成一幕(穷尽、不挑三五个、不设小数帽——
   修作者点的"数据不够多"),每幕 = 场景一句话 + 关系表述(此刻敌友/状态)+ 为何变怎么变(因果)+
   敌友色温(辅) + 原文 evidence(核验)。

**为什么逐对发一次全局推理**:一对的逐章 note 序列就是这对人的完整传记,逐对发让模型聚焦一对、
看完全程才推得出连贯的"为何变"(逐段 map-reduce 看不见别段,推不出贯穿全书的因果)。逐对走 L2
缓存,同书重开零成本。

**便宜 + 稳**:只发每对的逐章 note(不发原文),走 ``invoke_client_cached`` 按清单缓存。某对
推理失败 / 解析不出 → 跳过这对(不 break 整体);全失败 / 没有成戏的人物对(论文工具书等)→ 返
None,端点返空态(关系演变骨子里是人物关系,非叙事书优雅退场,概念间关系归概念图)。每幕 evidence
取相关章章脉那条已核验的章级 evidence,再走 ``verify_citations`` 附 verified/match_score
(evidence-first:核不过的标灰、不当确定结论画)。人名先过 ``build_spine_name_map`` 别名合并。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.chapter_spine_canon import build_spine_name_map
from bookscope.agent.chapter_spine_evidence import (
    chapter_text_map as _chapter_text_map,
)
from bookscope.agent.chapter_spine_evidence import split_sentences
from bookscope.agent.chapter_spine_views import _canon, _norm_pair
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_CHRONICLE_MAX_TOKENS = 16000
"""单对的「总判 + 逐幕编年」比旧的一根强度线大不少——verdict 几句 + 穷尽逐幕(场景/表述/因果)。

deepseek-v4-flash 把 reasoning_content 算进 max_tokens(见
[[reference_reasoning_model_token_budget]])。这里每次判一对人、输出一段总判 + 十几到几十幕编年,
16000 给 reasoning 头 + 编年余量;真撑爆靠 ``_parse_chronicle`` 截断抢救兜底。"""

MAX_PAIRS = 30
"""一本书逐对全局推理最多跑戏份最重的前多少对(按出场章数排)。

每对一次 LLM 调用,成本随对数线性涨。取戏份最重的前 30 对盖住三国这类大书里真正有演变的对;
前端概览默认显 top14、点「看全部」看到全部 30。长尾只 1 章露面的对没演变可言,
``MIN_CHAPTERS_PER_PAIR`` 已滤掉。这是成本 vs 丰富度的权衡点。"""

MIN_CHAPTERS_PER_PAIR = 2
"""一对人至少在几章里有互动 note 才值得铺编年。只在 1 章露过面的对没"演变"可言,跳过。"""

_CHRONICLE_INSTR = (
    "下面是一本书里**同一对人物**(称甲、乙)从头到尾、按章节顺序发生的事(notes 数组,每条带"
    "章号)。请通读这对人的**完整轨迹**,像评点家一样给这对关系做一份「总判 + 编年」。"
    "严格只依据 notes,不臆测、不编造。\n\n"
    "输出两部分:\n\n"
    "一、verdict —— 对这对关系的**整体判断**(站在全书高度先定性,不是逐幕拼出来的):\n"
    "  - essence:一句话点透这对关系的本质(如\"互为镜像的枭雄,注定两立的政敌\")。\n"
    "  - arc:总体走向一句话(从哪到哪,如\"从依附→决裂→分庭抗礼的死敌\")。\n"
    "  - asymmetric:两人对彼此的看法是否**明显不同**(true/false)。真不同才 true。\n"
    "  - view_a_on_b / view_b_on_a:**仅当 asymmetric=true** 时填——甲怎么看乙、乙怎么看甲"
    "(各一句);对称的关系两个都留空,绝不硬编不对称。\n"
    "  - sharp_point:最尖锐的一笔(这对关系里最关键/最反常的那一点)。\n"
    "  - pivot_chapter:sharp_point 最对应的那一章章号(整数,挂回下面某一幕)。\n\n"
    "二、beats —— 逐幕**关系编年**。notes 里这对人**每个有戏的章都给一幕**——要密,别只挑三五个、"
    "别漏掉中间的转折章。每幕:\n"
    "  {chapter:章号整数, scene:这章他俩之间具体发生了什么(一句), "
    "state:此刻是什么关系(敌友 + 状态,如\"同盟·又用又防\"\"死敌·分庭抗礼\"), "
    "valence:此刻敌友倾向(-5到5整数,友为正、敌为负、中立0), "
    "change:到这一幕关系**为何变、怎么变**(一句因果;第一幕可留空)}。\n\n"
    "**只依据 notes。编年要密——这对人出现的每个有戏的章都该成一幕。对称的关系 asymmetric 填 "
    "false、两个 view 留空。关系明明越来越敌对的别判成越来越友好——方向以 notes 为准。**\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"verdict":{"essence":"","arc":"","asymmetric":false,"view_a_on_b":"","view_b_on_a":"",'
    '"sharp_point":"","pivot_chapter":章号整数},'
    '"beats":[{"chapter":章号整数,"scene":"","state":"","valence":0,"change":""}]}'
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
    一对人同章多条 note 合成一条(用换行拼),保证一对一章一条。
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


def _coerce_beats(raw: Any, chapters_with_note: set[int]) -> list[dict[str, Any]]:
    """逐幕编年归一成 ``[{chapter, scene, state, valence, change}]``。

    章号锚到这对人真有 note 的章(防 LLM 编章号),不命中则退到最近一条 note 的章;同章去重(留首条)、
    按章号升序。
    """
    if not isinstance(raw, list):
        return []
    sorted_note_chs = sorted(chapters_with_note)
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for b in raw:
        if not isinstance(b, dict):
            continue
        ch = b.get("chapter")
        if not isinstance(ch, int):
            continue
        if ch not in chapters_with_note and sorted_note_chs:
            ch = min(sorted_note_chs, key=lambda c: abs(c - ch))  # type: ignore[arg-type]
        if ch in seen:
            continue
        seen.add(ch)
        out.append({
            "chapter": ch,
            "scene": str(b.get("scene", "")).strip(),
            "state": str(b.get("state", "")).strip(),
            "valence": _clamp_int(b.get("valence"), -5, 5, 0),
            "change": str(b.get("change", "")).strip(),
        })
    out.sort(key=lambda x: x["chapter"])
    return out


def _coerce_verdict(raw: Any) -> dict[str, Any]:
    """整体判断归一:``essence/arc/asymmetric/view_a_on_b/view_b_on_a/sharp_point/pivot_chapter``。

    asymmetric=False 时强制清空两个 view(防模型嘴上说对称、还是硬填了两边)。
    """
    d = raw if isinstance(raw, dict) else {}
    asymmetric = bool(d.get("asymmetric", False))
    pivot = d.get("pivot_chapter")
    return {
        "essence": str(d.get("essence", "")).strip(),
        "arc": str(d.get("arc", "")).strip(),
        "asymmetric": asymmetric,
        "view_a_on_b": str(d.get("view_a_on_b", "")).strip() if asymmetric else "",
        "view_b_on_a": str(d.get("view_b_on_a", "")).strip() if asymmetric else "",
        "sharp_point": str(d.get("sharp_point", "")).strip(),
        "pivot_chapter": pivot if isinstance(pivot, int) else None,
    }


def _parse_chronicle(text: str) -> dict[str, Any] | None:
    """解析单对的 ``{verdict, beats}``;三层兜底(直解析 / 切首个对象 / 抢救)。"""
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
    if isinstance(obj, dict) and ("beats" in obj or "verdict" in obj):
        return obj
    # 截断抢救:从半截 JSON 里把 beats 数组里已闭合的幕抠出来(verdict 抠不出就给空)。
    salvaged_beats = salvage_closed_objects(candidate, '"beats"')
    if salvaged_beats:
        logger.warning("chapter_spine_relationship: 单对主解析失败,从截断抢救 beats")
        return {"verdict": {}, "beats": salvaged_beats}
    return None


def _build_one_chronicle(
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
    """对一对人发一次全局推理 → 归一成 ``{a, b, verdict, beats}``;失败 / 无幕返 None。

    beat 章号锚到这对人真有 note 的章。每幕 evidence 在调用方从章脉补 + 核验。
    """
    user_content = json.dumps({"a": a, "b": b, "notes": notes}, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_CHRONICLE_INSTR,
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

    parsed = _parse_chronicle(text)
    if parsed is None:
        return None

    beats = _coerce_beats(parsed.get("beats"), chapters_with_note)
    if not beats:
        return None
    verdict = _coerce_verdict(parsed.get("verdict"))
    # pivot_chapter 夹回真有幕的章:不命中退到最近一幕(让总判挂得到底下某一幕)。
    beat_chs = {bt["chapter"] for bt in beats}
    pivot = verdict["pivot_chapter"]
    if pivot is not None and pivot not in beat_chs:
        verdict["pivot_chapter"] = min(sorted(beat_chs), key=lambda c: abs(c - pivot))
    return {"a": a, "b": b, "verdict": verdict, "beats": beats}


def _appellations(canonical: str, name_map: dict[str, str] | None) -> list[str]:
    """一个 canonical 名字的全部叫法:canonical 本身 + 所有映射到它的别名(玄德/先主→刘备)。

    原文里用的是当下称呼(玄德/操),按 canonical("刘备")字面搜会漏;反查 name_map 拿齐别名再搜。
    """
    names = {canonical} if canonical else set()
    for alias, canon in (name_map or {}).items():
        if canon == canonical and alias:
            names.add(alias)
    return [n for n in names if n]


def _event_bigrams(text: str) -> set[str]:
    """事件描述拆 2-gram 当检索词(中文没空格切词,用 bigram 衡量某句像不像在讲这件事)。"""
    e = re.sub(r"\s+", "", text or "")
    return {e[i : i + 2] for i in range(len(e) - 1)}


def _pair_evidence(
    chapter_text: str, a_names: list[str], b_names: list[str], event_text: str
) -> str:
    """从一章原文里捞最支撑"这对人 + 这件事"的那句;都不沾的句子不要、返空。

    打分 ``(这对人命中数, 与 scene/change 的 bigram 重叠数, -句长)``:先认人(两人都中 > 一人中),
    同档再认事(跟这一幕描述字面越像越优先),同档短句更聚焦。比纯人名命中精准——光认人会抓到
    "曹操还兵许都"这类只蹭一个名字、跟这件事无关的句;加事件相似度才落到真讲这件事的那句。
    """
    if not chapter_text:
        return ""
    bigrams = _event_bigrams(event_text)
    best: tuple[tuple[int, int, int], str] | None = None
    for s in split_sentences(chapter_text):
        a_hit = any(n in s for n in a_names)
        b_hit = any(n in s for n in b_names)
        pair_hits = int(a_hit) + int(b_hit)
        overlap = sum(1 for bg in bigrams if bg in s)
        if pair_hits == 0:
            continue  # 连这对人一个都没沾,不可能是这对关系的证据
        if pair_hits < 2 and overlap == 0:
            continue  # 只蹭一个名字、又不讲这件事(零字面重叠)→ 不当证据,宁可空着标灰
        score = (pair_hits, overlap, -len(s))
        if best is None or score > best[0]:
            best = (score, s)
    return best[1] if best else ""


def _attach_and_verify_evidence(
    relations: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    name_map: dict[str, str] | None,
) -> None:
    """每幕按"这对人 + 这一章"去原文里捞相关那句当 evidence,过 verify_citations 附 verified。

    **不再用章级代表句**(那只代表这章最显眼的事、未必关乎这对人,会出现"场景说刘备投曹操、原文
    却是辕门射戟"的错锚)。改成 ``_pair_evidence``:在该章原文里找真提到这对人(含别名)的那句。
    命中 → verified=True;该章原文里压根没这对人(罕见)→ 空串、verified=False(FE 标灰,不硬塞
    无关原文)。evidence-first:没真原文支撑的幕不当确定结论画。
    """
    evidence_map = build_evidence_map(chunks)
    chapter_text = _chapter_text_map(chunks)
    for rel in relations:
        a_names = _appellations(rel["a"], name_map)
        b_names = _appellations(rel["b"], name_map)
        beats = rel["beats"]
        for bt in beats:
            event_text = f"{bt.get('scene', '')} {bt.get('change', '')}"
            bt["evidence"] = _pair_evidence(
                chapter_text.get(bt["chapter"], ""), a_names, b_names, event_text
            )
        citations = [{"snippet": bt["evidence"], "chapter": bt["chapter"]} for bt in beats]
        verify_citations(citations, evidence_map)
        for bt, vc in zip(beats, citations, strict=True):
            bt["verified"] = bool(vc.get("verified", False))
            bt["match_score"] = vc.get("match_score", 0.0)
            cid = vc.get("chunk_id")
            true_chapter = evidence_map.get(cid, {}).get("chapter") if cid else None
            if isinstance(true_chapter, int) and true_chapter > 0:
                bt["chapter"] = true_chapter  # 命中 chunk 的真章号纠偏
        beats.sort(key=lambda x: x["chapter"])  # 纠偏后可能乱序,再排一次


def relationship_timeline_from_spine(
    *,
    spine: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    name_map: dict[str, str] | None = None,
    max_pairs: int = MAX_PAIRS,
    max_tokens: int = DEFAULT_CHRONICLE_MAX_TOKENS,
    cache_enabled: bool = True,
) -> dict[str, Any] | None:
    """章脉派生关系编年:逐对收逐章 note → 逐对一次全局推理 → 总判 + 逐幕编年 + 每幕核验。

    每对人**一次性**把全程逐章 note 喂进去,看完全程才下总判、推因果——修了 map-reduce 逐段
    看不见别段、推不出贯穿全书因果的范式错,也修了旧版"压成一根不可信亲疏线"的抽象错。

    Args:
        spine: 章脉(``get_or_build_spine`` 的产出),每章 ``relations`` 为 ``[{pair, note}]``。
        chunks: 全书 chunk(含 ``chunk_id`` / ``chapter`` / ``text``),给每幕 evidence 核验。
        llm_client: duck-typed LLM client(同 AgentLoop)。
        model: 模型名。
        name_map: 别名→canonical 表;不传则内部用 ``build_spine_name_map`` 自建(合并 玄德/刘备)。
        max_pairs: 最多跑戏份最重的前几对(默认 30)。
        max_tokens: 单对 LLM 调用 max_tokens(总判 + 编年比旧的一根线大,默认 16000)。
        cache_enabled: 单对调用是否走 L2 缓存(默认开,同书重开零成本)。

    Returns:
        ``{"relations": [{"a", "b", "verdict": {essence, arc, asymmetric, view_a_on_b,
        view_b_on_a, sharp_point, pivot_chapter}, "beats": [{chapter, scene, state, valence,
        change, evidence, verified, match_score}]}]}``;
        全部失败 / 没有成戏的人物对(非叙事书) → ``None``(端点返空态)。
    """
    if name_map is None:
        name_map = build_spine_name_map(spine=spine, llm_client=llm_client, model=model)

    pair_notes, _ = _collect_pair_notes(spine, name_map)
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
        rel = _build_one_chronicle(
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

    _attach_and_verify_evidence(relations, chunks, name_map)
    return {"relations": relations}


def relationship_pairs_index(
    spine: list[dict[str, Any]],
    name_map: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """便宜的全员对清单(不调 LLM):每对 ``{a, b, chapters, first, last, count}``,按互动章数降序。

    给前端总览 / 选择器——关系图是全员索引,这清单覆盖全书所有有互动的对(canonical 化、无向),
    点一对再调 ``relationship_chronicle_for_pair`` 取编年。**不设 MIN_CHAPTERS 帽**:1 章的对也列
    (点进去 chronicle 会说"没演变可铺"),保证"关系图里的人都能在这找到"。name_map 应由调用方
    (端点)从关系图那张共享传入,两边对齐"谁是谁"。
    """
    pair_notes, _ = _collect_pair_notes(spine, name_map)
    out: list[dict[str, Any]] = []
    for (a, b), seq in pair_notes.items():
        chs = [p["chapter"] for p in seq]
        out.append({
            "a": a, "b": b, "chapters": chs,
            "first": min(chs), "last": max(chs), "count": len(chs),
        })
    out.sort(key=lambda x: (-x["count"], x["a"], x["b"]))
    return out


def relationship_chronicle_for_pair(
    *,
    a: str,
    b: str,
    spine: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    name_map: dict[str, str] | None = None,
    max_tokens: int = DEFAULT_CHRONICLE_MAX_TOKENS,
    cache_enabled: bool = True,
) -> dict[str, Any] | None:
    """按需算**指定一对**的关系编年(关系图点开下钻用)——复用全局推理 + 逐幕证据核验。

    a/b 先按 name_map canonical 化(关系图给的就是 canonical、这步幂等),无向归一后查这对的逐章
    note;互动 < ``MIN_CHAPTERS_PER_PAIR`` 或推不出幕 → None(端点返空,前端显"这对没演变可铺")。
    走 L2 缓存按这对 note 命中——在关系图里点来点去,点过的对零成本。name_map 应由端点从关系图
    共享传入,确保"关系图里点的刘备"和"这里查的刘备"是同一个 canonical。
    """
    if name_map is None:
        name_map = build_spine_name_map(spine=spine, llm_client=llm_client, model=model)
    pair_notes, _ = _collect_pair_notes(spine, name_map)
    key = _norm_pair(_canon(a, name_map), _canon(b, name_map))
    seq = pair_notes.get(key)
    if not seq or len(seq) < MIN_CHAPTERS_PER_PAIR:
        return None
    rel = _build_one_chronicle(
        a=key[0],
        b=key[1],
        notes=seq,
        chapters_with_note={p["chapter"] for p in seq},
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        cache_enabled=cache_enabled,
    )
    if rel is None:
        return None
    _attach_and_verify_evidence([rel], chunks, name_map)
    return rel


__all__ = [
    "DEFAULT_CHRONICLE_MAX_TOKENS",
    "MAX_PAIRS",
    "MIN_CHAPTERS_PER_PAIR",
    "relationship_chronicle_for_pair",
    "relationship_pairs_index",
    "relationship_timeline_from_spine",
]
