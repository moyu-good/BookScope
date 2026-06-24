"""时间线 = 章脉派生(一次全局推理还原故事时序)。ADR-010 出路 B 的一个视图。

**为什么有这个模块**:时间线的命根子是**把倒叙/插叙还原成真实故事时序**(卡片写着"多线、
倒叙也理清真实的时间先后")。老实现 ``generate_timeline_exhaustive`` 是 map-reduce 逐段抽
事件、merge 后 ``sort(key=chapter)`` 按**叙述章号**排——那是阅读顺序,不是故事顺序。每段只看
得见自己那几章,跨段哪件事在故事时间上更早根本判不了。一本"开篇先写结局再倒叙"的书,老实现会
把结局排在最前面,名不副实。

``chapter_spine_views.timeline_from_spine`` 那版也只是把章脉 events 按章升序摊平,同样是叙述序,
不是这里要的故事序。

做法:从章脉收**全书事件流**(逐章 ``events``,带叙述章号),**一次 LLM 调用**让模型通看全书
紧凑事件清单、给每个事件判它在**故事时间**里的先后(不是叙述章号)。一次看全书既不像 map-reduce
跨段瞎、也不像整本喂全文大书截断——判跨章/跨线时序就该这么做。

**只让 LLM 判时序、不让它重写事件**:事件文字、叙述章号、原文证据全从章脉锚定(章脉每条都过过
verify_citations)。LLM 只回 ``{id, time, story_order}``——id 锚回章脉真事件(防编造),time 是
故事时间描述(如"建安五年"),story_order 是故事时序序号。LLM 没判到的事件按叙述序兜底排在末尾,
不丢。

**便宜 + 稳**:只发事件摘要(不发原文),走 L2 缓存按清单命中,同书零成本。判不出 / 解析不出 →
返 None,端点照走旧路径(不 break)。
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

DEFAULT_ORDER_MAX_TOKENS = 24000
"""时序判定输出 ∝ 事件条数 + reasoning 头,给足防截断。

deepseek-v4-flash 是 reasoning 模型,reasoning_content 算进 max_tokens(见
[[reference_reasoning_model_token_budget]])。给小了 reasoning 吃光预算、content 全空
(finish=length)。三国上百号事件需要大输出;给 24000 覆盖三国 + 余量,更大的书超了靠
``_parse_order`` 截断抢救兜底。"""

_MAX_EVENTS_PER_CH = 6
"""每章事件流取前几条进清单。比伏笔的 4 多一点——时间线本就是把事件铺开,够覆盖又不撑爆 input。"""

_ORDER_INSTR = (
    "下面 events 是一本书逐章的主要事件,带 id 和它在书里**被叙述**的章号(ch)。\n"
    "书可能有倒叙 / 插叙 / 多线并行,**叙述顺序不等于故事真实发生的时间顺序**。\n"
    "请通看全书,判断每个事件在**故事时间线**上的真实先后,重新排出故事时序。\n"
    "- story_order 从 1 起、按故事真实发生的时间先后递增(不是按章号、不是按叙述顺序)。\n"
    "- 倒叙/插叙交代的往事,story_order 要排到它真实发生的那个时间点,即使它在很后面的章才被讲。\n"
    "- time:这件事在故事里发生的时间描述(书里写明的纪年/时段,如\"建安五年\";没写就留空字符串)。\n"
    "- 只给出 events 里真有的 id,别编 id、别新增事件、别改事件内容。每个 id 给一次。\n"
    "严格输出 JSON(别的话别说、别加 markdown 代码围栏):\n"
    '{"order":[{"id":事件id整数,"time":"故事时间或空字符串","story_order":故事时序整数}]}'
)


def _collect_events(
    spine: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]]]:
    """从章脉收全书事件流,给每个事件编叙述序 id。

    返回 (发给 LLM 的紧凑清单, id→事件锚)。事件锚带 event 文字 / chapter / evidence,
    全从章脉来——LLM 只回 id + 时序,锚靠这张表还原,不信 LLM 重写的内容。
    """
    payload: list[dict[str, Any]] = []
    anchor: dict[int, dict[str, Any]] = {}
    eid = 0

    def _ch_key(r: dict[str, Any]) -> int:
        c = r.get("chapter")
        return c if isinstance(c, int) else 0

    for rec in sorted(spine, key=_ch_key):
        if not isinstance(rec, dict):
            continue
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        evidence = str(rec.get("evidence", "")).strip()
        events = rec.get("events")
        if not isinstance(events, list):
            continue
        for ev in events[:_MAX_EVENTS_PER_CH]:
            text = str(ev.get("event", ev) if isinstance(ev, dict) else ev).strip()
            if not text:
                continue
            payload.append({"id": eid, "ch": ch, "事": text})
            anchor[eid] = {"event": text, "chapter": ch, "evidence": evidence}
            eid += 1
    return payload, anchor


def _parse_order(text: str) -> list[dict[str, Any]]:
    """把 LLM 的 ``{"order":[...]}`` 解析成 list;三层兜底(直解析 / 切首个对象 / 截断抢救)。"""
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
    if isinstance(obj, dict) and isinstance(obj.get("order"), list):
        return obj["order"]
    salvaged = salvage_closed_objects(candidate, '"order"')
    if salvaged:
        logger.warning("chapter_spine_timeline: 主解析失败,从截断抢救到 %d 条时序", len(salvaged))
        return salvaged
    return []


def timeline_from_spine(
    *,
    spine: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_ORDER_MAX_TOKENS,
    cache_enabled: bool = True,
) -> list[dict[str, Any]] | None:
    """章脉全书事件流一次全局推理判故事时序 → 按故事时序排的事件 list。任意环节空/抛 → None。

    事件形态对齐旧 ``generate_timeline``:``{order, time, event, chapter, evidence}``。
    - order:故事时序序号(从 1 重编),不是叙述章号。
    - time:故事时间描述(LLM 据全书判,书里没写就空)。
    - event / chapter / evidence:全从章脉锚定(event 文字、叙述所在章、该章已核验证据)。

    LLM 只回 ``{id, time, story_order}``,id 必须是章脉真事件的 id(否则丢,防编造)。LLM 没判到
    的章脉事件按叙述序兜底排在末尾,不丢。
    """
    payload, anchor = _collect_events(spine)
    if not payload:
        return None

    user_content = json.dumps({"events": payload}, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_ORDER_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 判定失败降级返 None,不 break 端点
        logger.warning(
            "chapter_spine_timeline: 时序调用抛 %s: %s;返 None", type(exc).__name__, exc
        )
        return None

    # LLM 判到的:锚回章脉真事件,记下 story_order 和 time
    judged: dict[int, dict[str, Any]] = {}
    for o in _parse_order(text):
        if not isinstance(o, dict):
            continue
        eid = o.get("id")
        so = o.get("story_order")
        if not isinstance(eid, int) or eid not in anchor or not isinstance(so, int):
            continue  # 锚到真事件,id 编了就丢
        if eid in judged:
            continue  # 同 id 给多次,取第一次
        judged[eid] = {
            "story_order": so,
            "time": str(o.get("time", "")).strip(),
        }
    if not judged:
        return None

    # LLM 没判到的事件:按叙述序(id 升序)兜底排在末尾,不丢
    sentinel = max(j["story_order"] for j in judged.values()) + 1
    rows: list[dict[str, Any]] = []
    for eid, a in anchor.items():
        j = judged.get(eid)
        # 排序键:(故事时序, 叙述序 id)——LLM 判到的按它的故事序;没判到的统一沉到 sentinel 段、
        # 段内按叙述序;同 story_order 的也用叙述序稳定排
        story_order = j["story_order"] if j else sentinel
        rows.append({
            "_story_order": story_order,
            "_eid": eid,
            "time": j["time"] if j else "",
            "event": a["event"],
            "chapter": a["chapter"],
            "evidence": a["evidence"],
        })

    rows.sort(key=lambda r: (r["_story_order"], r["_eid"]))
    out: list[dict[str, Any]] = []
    for i, r in enumerate(rows, 1):
        out.append({
            "order": i,
            "time": r["time"],
            "event": r["event"],
            "chapter": r["chapter"],
            "evidence": r["evidence"],
        })
    return out or None


__all__ = ["DEFAULT_ORDER_MAX_TOKENS", "timeline_from_spine"]
