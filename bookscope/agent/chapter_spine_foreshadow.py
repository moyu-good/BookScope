"""伏笔回收 = 章脉派生(轻 LLM)。ADR-010 出路 B 的一个视图。

**为什么有这个模块**:伏笔天生**跨章**——前文埋(setup)、后文收(payoff)。老实现
``generate_foreshadow_arcs_exhaustive`` 是 map-reduce 逐段跑的,每段只看得见自己那几章,
跨段的真伏笔根本配不上 → 模型只能把回收点也写成埋点同章(2026-06-24 实测三国:114 条里
58 条跨度=0、98 条跨度≤3,真正长跨度只有 4 条),命根子"早埋晚收"全废。

做法:从章脉收**全书埋点清单**(逐章 ``foreshadow`` 里的「埋」)+ **全书事件流**(逐章
``events``),**一次 LLM 调用**让模型对每个埋点在后文事件里找回收章。一次看全书紧凑清单
既不像 map-reduce 跨段瞎、也不像整本喂全文大书截断——跨章配对就该这么做。

**为什么靠事件流不靠「收」标**:回收点那一章常常没把自己标成「收」(它不知道在还前文的债),
但回收一定出现在那章的**事件**里。三国实测:只匹配稀疏的「收」标 → 配出 15 条、全短跨度;
拿事件流当回收线索 → 配出 67 条、跨度到 52 章(真长程伏笔浮出来)。

**便宜 + 稳**:只发埋点 + 事件摘要(不发原文),走 L2 缓存按清单命中,同书零成本。配对失败 /
解析不出 → 返 None,端点照走(不 break)。arc 锚到章脉里**真有埋点的章**(防 LLM 编章号),
回收章须是真实章且晚于埋点;两端原文取章脉那一章已核验过的 evidence(章级锚)。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_MATCH_MAX_TOKENS = 24000
"""配对输出 ∝ 埋点条数 + reasoning 头,给足防截断。

deepseek-v4-flash 是 reasoning 模型,reasoning_content 算进 max_tokens(见
[[reference_reasoning_model_token_budget]])。三国实测:90 章埋/收清单,reasoning ~10000 +
content ~8000 = 18293 tokens 才吐完 94 条弧;给 12000 会被截在 reasoning 中途、content 全空
(finish=length)。给 24000 覆盖三国 + 余量;更大的书超了靠 ``_parse_arcs`` 截断抢救兜底。"""

_MAX_EVENTS_PER_CH = 4  # 每章事件流取前几条当回收线索,够定位又不撑爆 input

_MATCH_INSTR = (
    "下面 setups 是这本书逐章埋下的伏笔(埋点);timeline 是每章发生的主要事件。\n"
    "请对每个埋点,在 timeline 的**后文事件**里找到它兑现/呼应/解开的那一章——这就是回收点。\n"
    "- 回收章必须**晚于**埋点章(payoff_chapter > setup_chapter)。\n"
    "- 后文事件里找不到明确回收的,payoff_chapter 填 null(断弧——挖了坑没填,正是审稿要抓的)。\n"
    "- 只在后文事件**确实兑现**这个埋点时才配;拿不准就当断弧。错配一条比漏配一条更糟。\n"
    "- 只依据给出的事件,别编书里没有的回收。\n"
    "description 用一句话说清这条伏笔:埋的是什么、(若回收)在哪兑现。\n"
    "严格输出 JSON(别的话别说、别加 markdown 代码围栏):\n"
    '{"arcs":[{"description":"一句话","setup_chapter":埋点章号整数,'
    '"payoff_chapter":回收点章号整数或null}]}'
)


def _collect_inventory(
    spine: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], set[int], set[int], dict[int, str]]:
    """从章脉收 埋点清单 + 逐章事件流(回收线索)+ 章级证据。

    伏笔回收点常常**没被标成「收」**(那一章自己不知道在还前文的债),但它一定出现在那章的
    **事件**里。所以拿全书事件流当回收线索,比只匹配稀疏的「收」标命中率高得多(三国实测:
    收标匹配只配出 15 条、全短跨度;事件流匹配配出 67 条、跨度到 52)。

    返回 (setups, timeline, 有埋点的章集, 全部章集, 章号→证据)。
    """
    setups: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    setup_chs: set[int] = set()
    all_chs: set[int] = set()
    evidence: dict[int, str] = {}
    for rec in spine:
        if not isinstance(rec, dict):
            continue
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        all_chs.add(ch)
        evidence[ch] = str(rec.get("evidence", "")).strip()
        events = rec.get("events")
        evs = (
            [
                str(e.get("event", e) if isinstance(e, dict) else e).strip()
                for e in events[:_MAX_EVENTS_PER_CH]
            ]
            if isinstance(events, list)
            else []
        )
        timeline.append({"章": ch, "事": [e for e in evs if e]})
        fs = rec.get("foreshadow")
        if isinstance(fs, list):
            for f in fs:
                if isinstance(f, dict) and f.get("type") == "埋":
                    hook = str(f.get("hook", "")).strip()
                    if hook:
                        setups.append({"埋点章": ch, "埋的是": hook})
                        setup_chs.add(ch)
    return setups, timeline, setup_chs, all_chs, evidence


def _parse_arcs(text: str) -> list[dict[str, Any]]:
    """把 LLM 的 ``{"arcs":[...]}`` 解析成 list;三层兜底(直解析 / 切首个对象 / 截断抢救)。"""
    raw = (text or "").strip()
    if not raw:
        return []
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
    if isinstance(obj, dict) and isinstance(obj.get("arcs"), list):
        return obj["arcs"]
    salvaged = salvage_closed_objects(candidate, '"arcs"')
    if salvaged:
        logger.warning("chapter_spine_foreshadow: 主解析失败,从截断抢救到 %d 条弧", len(salvaged))
        return salvaged
    return []


def foreshadow_from_spine(
    *,
    spine: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_MATCH_MAX_TOKENS,
    cache_enabled: bool = True,
) -> list[dict[str, Any]] | None:
    """章脉里全书"埋/收"一次 LLM 跨章配对 → 伏笔弧 list。任意环节空/抛 → None。

    弧形态同 ``generate_foreshadow_arcs_exhaustive``:
    ``{description, setup_chapter, payoff_chapter|None, setup_evidence, payoff_evidence, status}``。
    setup_chapter 必须是章脉里**真有埋点**的章(否则丢,防 LLM 编);payoff 须晚于 setup
    且是真有回收点的章,否则归断弧。两端 evidence 取章脉那章已核验的证据。
    """
    setups, timeline, setup_chs, all_chs, evidence = _collect_inventory(spine)
    if not setup_chs:
        return None

    user_content = json.dumps({"setups": setups, "timeline": timeline}, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_MATCH_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 配对失败降级返 None,不 break 端点
        logger.warning(
            "chapter_spine_foreshadow: 配对调用抛 %s: %s;返 None", type(exc).__name__, exc
        )
        return None

    out: list[dict[str, Any]] = []
    for a in _parse_arcs(text):
        if not isinstance(a, dict):
            continue
        s = a.get("setup_chapter")
        if not isinstance(s, int) or s not in setup_chs:
            continue  # 锚到真有埋点的章
        p = a.get("payoff_chapter")
        resolved = isinstance(p, int) and p > s and p in all_chs
        out.append(
            {
                "description": str(a.get("description", "")).strip(),
                "setup_chapter": s,
                "payoff_chapter": p if resolved else None,
                "setup_evidence": evidence.get(s, ""),
                "payoff_evidence": evidence.get(p, "") if resolved else "",
                "status": "resolved" if resolved else "dangling",
            }
        )
    out.sort(key=lambda x: x["setup_chapter"])
    return out or None


__all__ = ["DEFAULT_MATCH_MAX_TOKENS", "foreshadow_from_spine"]
