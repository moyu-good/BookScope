"""章脉(ADR-010):整本一次精读出的、带证据的逐章结构,全书功能从它派生视图的单一事实源。

**为什么有这个模块**:关系图 / 叙事流 / 叙事曲线 / 时间线…… 十个全书功能本来各自把整本
map-reduce 一遍,同段原文 input 重发十遍,几百万字书跑不动(见 ADR-010)。改成:整本只精读
一次出章脉,各功能从章脉派生视图(纯计算或一次小调用)。

**分维抽取**(probe 定案,`scripts/probe_chapter_spine.py`:全维一趟短章网文 3/4 段截断,分维 0/4):
- 人物维:每章 在场人物 / 关系 / 人物处境
- 情节维:每章 事件 / 张力 / 情感 / 视角 / 主支线 / 伏笔候选
- 概念维(理论书):每章 主张

每维走 ``mapreduce_per_chapter``(D-7 章闸防输出截断 + 合并前逐段章号纠偏),再按**真章号**
跨维 union 成一条章脉记录。每条记录、每个字段都钉原文证据——没证据不进章脉(立身之本)。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from bookscope.agent._internal.exhaustive import (
    DEFAULT_MAX_CHAPTERS,
    mapreduce_per_chapter,
)
from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import salvage_closed_objects
from bookscope.agent.utils.json_parsing import strip_code_fence as _strip_code_fence

logger = logging.getLogger(__name__)

DEFAULT_SPINE_MAX_TOKENS = 16000
"""分维后单维输出比全维一趟小。probe(probe_spine_scale.py,三国 732k 字冷启动)实测:8000 配大段
(12 章 / 12 万字)有 12.9% 截断 → 触发续抽 / 补抽拖慢;抬到 16000 后 0 截断、单维大段一次抽完,
冷启动 649s→194s(快 3.3 倍)、完整度反升到 1.0。留够 flash 的 reasoning 头。"""

# ── 章脉专用段参数(超长文性能,probe_spine_scale 定案)──────────────────────────
# 段越大 = 往返越少 = 冷启动越快,但一段塞更多章、输出越容易撞 max_tokens 截断(截断触发续抽 /
# 补抽反而更慢)。原来靠"6 章封顶 + 8000 token"压截断,代价是段切得碎、往返多(三国 85 次调用)。
# probe(probe_spine_scale.py,三国 732k 字冷启动、4 组对照)测出安全 sweet spot:
#   段放大到 12 万字 / 12 章 + max_tokens 抬到 16000 → 截断率 12.9%→0、调用 85→42、
#   墙钟 649s→194s(快 3.3 倍)、完整度 .992→1.0。放大不掉质量、反而更完整(给够 token 一次抽完)。
# 所以 char/plot 两个重维用 12 章封顶 + 12 万字段预算(配 16000 token 不爆);concept 轻维沿用全局 12。
# **不动 exhaustive 的全局默认**(DEFAULT_CHAR_BUDGET=40000)——人物图 / 实体表等别的穷尽化功能照旧。
_SPINE_HEAVY_DIM_MAX_CHAPTERS = 12
"""char/plot 重维每段章闸;12 章配 16000 token 实测不爆(probe_spine_scale)。concept 轻维走全局 12。"""

_SPINE_CHAR_BUDGET = 120000
"""章脉每段字符预算(probe 定的超长文 sweet spot);段大 = 往返少 = 冷启动快,不改 exhaustive 全局 4 万。"""

_SPINE_CONTINUE_MAX_ROUNDS = 3
"""续抽最多补几轮——防止某段反复截断导致无限补抽,补满几轮还差就停(留 warning)。"""

SPINE_SCHEMA_VERSION = "v1"
"""章脉记录结构版本——升级要让缓存整本失效(接 ADR-008 L3,迁移计划第 5 步)。"""


# ── 三维抽取指令 ───────────────────────────────────────────────────────────
_INSTR_CHAR = (
    "你在给一本书做逐章人物精读。只针对下面这段原文,逐章抽,只抽本段出现的章,不臆测、不编造。\n"
    "每章给:\n"
    "1. present:这章在场（有戏份）的人物名数组。\n"
    "2. relations:这章里有互动的人物对数组,每条 {pair:[甲,乙], note:这章他俩之间发生了什么}。\n"
    "3. char_states:这章里主要人物的处境数组,每条 {name:人物, state:他这章处于什么境况}。\n"
    "4. evidence:这章里最能代表上面判定的一句原文逐字片段(原样摘录、不改写)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"chapters":[{"chapter":章号整数,"present":[],"relations":[],"char_states":[],"evidence":""}]}'
)

_INSTR_PLOT = (
    "你在给一本书做逐章情节精读。只针对下面这段原文,逐章抽,只抽本段出现的章,不臆测、不编造。\n"
    "每章给:\n"
    "1. events:这章的关键事件数组,每条一句话。\n"
    "2. tension:张力 0-10 整数,铺垫/过场低、高潮/冲突高。\n"
    "3. sentiment:情感方向 -5 到 5 整数,往上走(喜胜聚)正、往下沉(悲败散)负、平稳 0。\n"
    "4. pov:主导视角人物名;无单一视角(全景)填\"群像\"。\n"
    "5. mainline:推进主线 true,岔开支线/闲笔 false。\n"
    "6. foreshadow:这章的伏笔候选数组,每条 {type:\"埋\"或\"收\", hook:埋/收的是什么}。\n"
    "7. evidence:这章里最能代表上面判定的一句原文逐字片段(原样摘录、不改写)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"chapters":[{"chapter":章号整数,"events":[],"tension":0,"sentiment":0,"pov":"",'
    '"mainline":true,"foreshadow":[],"evidence":""}]}'
)

_INSTR_CONCEPT = (
    "你在给一本理论/论说类书做逐章精读。只针对下面这段原文,逐章抽,只抽本段出现的章,不臆测。\n"
    "每章给:\n"
    "1. claims:这章提出/论证的主张数组,每条一句话。\n"
    "2. evidence:这章里最能代表上面主张的一句原文逐字片段(原样摘录、不改写)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"chapters":[{"chapter":章号整数,"claims":[],"evidence":""}]}'
)

_USER_MSG = "请按上面的要求,只对这段原文逐章抽结构。"

# 每维:(指令, 该维除 chapter/evidence 外要保留的字段, 该字段缺省值)
_DIM_FIELDS: dict[str, dict[str, Any]] = {
    "char": {"present": list, "relations": list, "char_states": list},
    "plot": {"events": list, "tension": int, "sentiment": int, "pov": str,
             "mainline": bool, "foreshadow": list},
    "concept": {"claims": list},
}


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _coerce_dim(item: Any, dim: str) -> dict[str, Any] | None:
    """把一条章节 dict 归一成该维该有的字段;chapter 缺/非整数 → 丢(没章号摆不进章脉)。"""
    if not isinstance(item, dict):
        return None
    ch = item.get("chapter")
    if not isinstance(ch, int):
        return None
    out: dict[str, Any] = {"chapter": ch, "evidence": str(item.get("evidence", "")).strip()}
    for field, typ in _DIM_FIELDS[dim].items():
        v = item.get(field)
        if field == "tension":
            out[field] = _clamp_int(v, 0, 10, 0)
        elif field == "sentiment":
            out[field] = _clamp_int(v, -5, 5, 0)
        elif field == "pov":
            out[field] = (v.strip() if isinstance(v, str) else "") or "群像"
        elif field == "mainline":
            out[field] = v if isinstance(v, bool) else True
        elif typ is list:
            out[field] = v if isinstance(v, list) else []
    return out


def _make_parser(dim: str):  # noqa: ANN202 — 返回闭包 parse_fn 喂 mapreduce
    """造一个该维的 parse_fn:strip 围栏 → json.loads → 抠首个 obj → 抢救截断 → 归一。"""

    def _coerce_list(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for it in raw:
            c = _coerce_dim(it, dim)
            if c is None or c["chapter"] in seen:
                continue
            seen.add(c["chapter"])
            out.append(c)
        return out

    def _parse(text: str) -> list[dict[str, Any]] | None:
        raw = (text or "").strip()
        if not raw:
            return None
        candidate = _strip_code_fence(raw)
        obj: Any = None
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            sliced = _extract_first_json_object(candidate)
            if sliced is not None:
                try:
                    obj = json.loads(sliced)
                except json.JSONDecodeError:
                    obj = None
        if isinstance(obj, dict):
            chs = _coerce_list(obj.get("chapters"))
            if chs:
                return chs
        salvaged = _coerce_list(salvage_closed_objects(candidate, '"chapters"') or [])
        if salvaged:
            logger.warning("chapter_spine[%s]: 主解析失败,从截断抢救到 %d 章", dim, len(salvaged))
            return salvaged
        return None

    return _parse


def _segment_chapter_count(seg: list[dict[str, Any]]) -> int:
    """这段原文覆盖几个不同章(看 chunk 的真 chapter 字段)。续抽据此判"还差几章"。"""
    return len({c.get("chapter") for c in seg if isinstance(c.get("chapter"), int)})


def _make_continue_fn(
    dim: str,
    instruction: str,
    *,
    llm_client: Any,
    model: str,
    max_tokens: int,
    cache_enabled: bool,
):  # noqa: ANN202 — 返回闭包 continue_fn 喂 mapreduce
    """造该维的续抽回调(1.5.2 方案 C):某段截断只抢救回部分章时,把差掉的章补抽回来。

    判据用**数量**不用具体章号:段原文覆盖 N 个章(看 chunk 真 chapter),抢救回 M 条,差 N-M 章。
    不点名"第几章"是因为这一步章号还没纠偏(模型自报的小章号在多卷书里撞号、不可靠),改让模型
    "接着上次没抽完的往下抽"。最多补 ``_SPINE_CONTINUE_MAX_ROUNDS`` 轮防无限补,补满还差就停。
    续抽的章号同样在合并前由 ``_correct_by_evidence`` 纠偏,这里不管。
    """
    parse = _make_parser(dim)

    def _continue(
        seg: list[dict[str, Any]], partial: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        covered = _segment_chapter_count(seg)
        if covered == 0:  # 段不带章号(向后兼容路) → 没法判差几章,不续抽
            return []
        seg_text = "".join(str(c.get("text", "")) for c in seg)
        extra: list[dict[str, Any]] = []
        got = list(partial)
        for _round in range(_SPINE_CONTINUE_MAX_ROUNDS):
            missing = covered - len(got)
            if missing <= 0:
                break
            # 接着上次没抽完的往下抽:告诉模型已抽 len(got) 章、只补剩下的,别重复。
            cont_instr = (
                instruction
                + f"\n\n注意:你上次已经抽完了本段前 {len(got)} 个章,被长度截断了。"
                + f"现在请**只抽你还没抽的、本段剩下的约 {missing} 个章**,接着往下,"
                + "别重复前面抽过的章。"
            )
            system = build_longctx_system(seg_text, cont_instr)
            try:
                resp = invoke_client_cached(
                    llm_client,
                    model=model,
                    system=system,
                    tools=[],
                    messages=[{"role": "user", "content": _USER_MSG}],
                    max_tokens=max_tokens,
                    cache_enabled=cache_enabled,
                )
            except Exception as exc:  # noqa: BLE001 — 续抽调用失败就停,保已有的
                logger.warning(
                    "chapter_spine[%s]: 续抽调用抛 %s,停止续抽", dim, type(exc).__name__
                )
                break
            try:
                more = parse(llm_client.extract_final_text(resp)) or []
            except Exception:  # noqa: BLE001
                more = []
            if not more:  # 这轮没补到 → 再补也大概率空,停
                break
            extra.extend(more)
            got.extend(more)
        if extra:
            logger.warning(
                "chapter_spine[%s]: 段截断续抽补回 %d 条(本段共约 %d 章)",
                dim,
                len(extra),
                covered,
            )
        return extra

    return _continue


def _correct_by_evidence(records: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
    """合并前逐段把每条记录的章号纠偏成命中 chunk 的真章号(同 narrative,ADR-010 D-2)。

    多卷书正文标题每卷重数,模型照标题给撞号的小章号;若按它先 merge 会丢章。这里用记录的
    chapter 级 evidence 过 verify_citations,命中就用 chunk 的真章号覆盖,并附 verified/match_score。
    """
    evidence = build_evidence_map(chunks)
    citations = [{"snippet": r.get("evidence", ""), "chapter": r.get("chapter")} for r in records]
    verify_citations(citations, evidence)
    for rec, vc in zip(records, citations, strict=True):
        rec["verified"] = bool(vc.get("verified", False))
        rec["match_score"] = vc.get("match_score", 0.0)
        cid = vc.get("chunk_id")
        true_ch = evidence.get(cid, {}).get("chapter") if cid else None
        if isinstance(true_ch, int) and true_ch > 0:
            rec["chapter"] = true_ch


def _merge_dimensions(dim_lists: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """按**真章号**把各维的逐章记录 union 成一条章脉记录(各维字段不重叠,直接并)。

    chapter 级 evidence 保第一条非空;verified 取任一维命中即 True、match_score 取最大。
    """
    by_ch: dict[int, dict[str, Any]] = {}
    order: list[int] = []
    for dim_list in dim_lists:
        for rec in dim_list:
            ch = rec.get("chapter")
            if not isinstance(ch, int):
                continue
            if ch not in by_ch:
                by_ch[ch] = {"chapter": ch, "evidence": "", "verified": False, "match_score": 0.0}
                order.append(ch)
            tgt = by_ch[ch]
            for k, v in rec.items():
                if k == "chapter":
                    continue
                if k == "evidence":
                    if v and not tgt["evidence"]:
                        tgt["evidence"] = v
                elif k == "verified":
                    tgt["verified"] = tgt["verified"] or bool(v)
                elif k == "match_score":
                    tgt["match_score"] = max(tgt["match_score"], v or 0.0)
                else:
                    tgt[k] = v
    return [by_ch[ch] for ch in sorted(order)]


def build_chapter_spine(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    genre: str = "fiction",
    max_tokens: int = DEFAULT_SPINE_MAX_TOKENS,
    char_budget: int = _SPINE_CHAR_BUDGET,
    max_workers: int | None = None,
) -> list[dict[str, Any]]:
    """整本一次精读,出带证据的逐章章脉(ADR-010 单一事实源)。

    分维抽取:小说跑 人物维 + 情节维;``genre="theory"`` 加 概念维。每维 ``mapreduce_per_chapter``
    (章闸 + 合并前 ``_correct_by_evidence`` 纠偏),再按真章号跨维 union。空 → ``[]``。

    1.5.2 健壮性:char/plot 两个重维用更小的专用章闸(``_SPINE_HEAVY_DIM_MAX_CHAPTERS``)让单段
    输出不爆 ``max_tokens``(方案 B);某段仍被截断时靠 ``continue_fn`` 把差掉的章续抽补完、不悄悄
    丢(方案 C)。concept 轻维沿用全局章闸、不续抽。**不动 exhaustive 全局默认**——别的穷尽化功能照旧。

    Returns: ``[{chapter, present, relations, char_states, events, tension, sentiment, pov,
    mainline, foreshadow, [claims], evidence, verified, match_score}]``,按章号升序。
    """
    dims = [("char", _INSTR_CHAR), ("plot", _INSTR_PLOT)]
    if genre == "theory":
        dims.append(("concept", _INSTR_CONCEPT))

    # 抽一个维度(char/plot 重维收窄章闸 + 开续抽;concept 轻维走全局默认、不续抽)。
    def _run_dim(dim: str, instruction: str) -> list[dict[str, Any]]:
        heavy = dim != "concept"
        dim_max_chapters = _SPINE_HEAVY_DIM_MAX_CHAPTERS if heavy else DEFAULT_MAX_CHAPTERS
        continue_fn = (
            _make_continue_fn(
                dim,
                instruction,
                llm_client=llm_client,
                model=model,
                max_tokens=max_tokens,
                cache_enabled=True,
            )
            if heavy
            else None
        )
        return mapreduce_per_chapter(
            chunks=chunks,
            instruction=instruction,
            user_msg=_USER_MSG,
            parse_fn=_make_parser(dim),
            llm_client=llm_client,
            model=model,
            max_tokens=max_tokens,
            char_budget=char_budget,
            max_chapters=dim_max_chapters,
            max_workers=max_workers,
            correct_fn=_correct_by_evidence,
            continue_fn=continue_fn,
            sweep_missing_chapters=True,  # 1.5.2 兜底:缺章单章重抽,堵住所有截断丢章
        )

    # 各维互不依赖、输入相同 → 并行跑,别再"一维扫完全本才轮下一维"(冷启动墙钟约减半:
    # 原来 char 40 段跑完才开 plot 40 段,现在两维一起进池)。维内仍各自 map-reduce 并发;
    # 并发底座已线程安全(维内本就多线程跑同一 client、_UsageRecorder 加锁、SQLite 每调用新 conn)。
    # pool.map 按 dims 顺序收集结果,不影响 _merge_dimensions 的跨维 union。
    with ThreadPoolExecutor(max_workers=len(dims)) as pool:
        dim_lists = list(pool.map(lambda d: _run_dim(d[0], d[1]), dims))

    return _merge_dimensions(dim_lists)


__all__ = [
    "DEFAULT_SPINE_MAX_TOKENS",
    "SPINE_SCHEMA_VERSION",
    "build_chapter_spine",
]
