"""公文「关键时间轴」(1.6 红头文件垂直·三炮)——把一份公文里散落的时间节点拉成一条时序。

**它解决什么**:一份公文里时间散落各处——申报截止在第三条、过渡期在第十条、生效日在落款、
阶段目标埋在附则。读者要自己从头翻到尾把这些时间点拼出来,才知道「我什么时候之前得交、哪天
开始管我、过渡期到哪天、哪天彻底废止」。这功能把这些带时间的要求**抽出来排成一条时序**,
一眼看清这份公文给你定了哪些时间节点、各要在哪个点前做什么。

**跟公文结构解读 / 大白话翻译的分工**:那两个把一份公文拆成头要素 + 逐条款 / 逐条翻成人话;
这个拿同一份文脉的条款,**只挑带时间的**,一次全局推理排成时序。同一份文脉
(``get_or_build_doc_spine``)建一次,三个功能共用、第二个起秒出。

**意象**:不是套书的山水叙事曲线、不是通用甘特图——是「公文里的时间节点排成官府办事的时间线」,
编年时序(申报截止 → 实施日 → 过渡期 → 生效 → 废止 → 阶段目标),每个节点钉一句原文。

**怎么做(套现成的机器,一行不改 doc_spine / cross_doc / agent.py)**:

1. **拿文脉**:走 ``get_or_build_doc_spine`` 拿这份公文的文脉(头要素 + 逐条款,带证据)。同份
   公文命中缓存秒出,不重精读。
2. **一次全局推理抽时间节点**:把逐条款收成紧凑清单(每条的序号 / 事项 / 时限 / 原文),**一次**
   LLM 调用让模型把带时间的要求挑出来,每个节点给「when(日期或『印发起30日内』这类相对期)/
   what(到这个点要发生啥)/ chapter(来源条款序号)/ evidence(撑这个时间的原文逐字片段)」。
   这正是 ``concept_evolution_from_spine`` 那台「从脊收紧凑清单 → 一次全局推理 → 锚回真实单元」
   的同一台机器,单元是「条款」、推理的是「时间」。
3. **锚回原条款,过核验,绝不编日期**:每个节点的 evidence(**原条款里撑这个时间的那句原文**)
   过 ``verify_citations``——核得到 ``verified=True`` 盖「鉴」印,核不过(含 evidence 空)标
   ``verified=False`` 待核。时间是从原文里抽的、不是模型脑补的;一个节点连撑它的原文都核不到,
   就标待核不当真,**绝不假装这个日期有原文撑**。

铁律:**只 import ``doc_spine_cache`` 的缓存入口 + 现有 helper,一行不改 ``doc_spine`` /
``cross_doc`` / ``agent.py`` / ``schemas.py``**;端点该返的结构写在
``timeline_from_spine`` 的 docstring 里给主 Claude 接线。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.doc_spine_cache import get_or_build_doc_spine
from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.redhead_codebook import codebook_block
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

TIMELINE_SCHEMA_VERSION = "v1"
"""时间轴记录结构版本——升级要让从文脉派生的这层重算(文脉缓存不受影响,只这层重跑)。"""

DEFAULT_TIMELINE_MAX_TOKENS = 1500
"""一次全局推理抽时间节点的 max_tokens。一份公文的时间节点通常十几个以内,每个就几句,
1500 留足 reasoning 头(deepseek-v4-flash 把 reasoning_content 算进 max_tokens,见
reference_reasoning_model_token_budget)。节点多被截断时靠 salvage_closed_objects 抢救。

加约束力层(1.6.1)后每个节点多 deadline_type / deadline_reason 两个短字段——量很小,1500
仍够;真被截断 ``salvage_closed_objects`` 照样兜底。"""

# 时间点性质(deadline_type)两档(封闭集,1.6.1 加的判断层)——这个时间点是真咬人的死线
# (逾期有罚则/考核),还是没硬后果的软目标 / 倡导性时点。判据走 codebook 的开环/闭环:
# 绑硬约束词 + 逾期有罚则/考核兜底 = 真deadline;阶段性「力争X前达到」「逐步」这类 = 软目标。
DEADLINE_TYPES: tuple[str, ...] = (
    "真deadline",  # 逾期有罚则/考核/失权的死线(限X前办结,逾期不予受理 / 通报问责)
    "软目标",      # 倡导性 / 力争性 / 阶段性时点,逾期无硬后果(力争X前达到、逐步推进)
)
_DEFAULT_DEADLINE_TYPE = "软目标"
"""时间点性质落不进两档的兜底——退「软目标」(最保守,不替一个时点拔高成真死线吓唬用户)。"""

# 一次全局推理的指令——不喂全文,只喂逐条款的紧凑清单(序号 / 事项 / 时限 / 原文),要模型
# 把**带时间的要求**挑出来排成时序。死守:只抽原文真有时间的、绝不编日期、锚回真实条款。
_INSTR_TIMELINE = (
    "你在给一份党政机关公文(红头文件)抽**关键时间轴**。下面 === 任务要求 === 之后给你这份"
    "公文的逐条款清单(每条:序号 + 事项 + 时限 + 原文)。\n"
    "请把这份公文里**带时间的要求**挑出来,排成一条时序。带时间的要求包括但不限于:申报 / "
    "申请截止日、实施日 / 施行日、过渡期(到某日为止的缓冲)、生效日、废止 / 失效日、阶段目标"
    "(到某年某季度前要达到的指标)、定期动作(每年 / 每季度某时点)。\n"
    "死守三条:\n"
    "1. **只抽原文真有时间的**。原文写了具体日期(「2024年5月8日」)、相对期(「自印发之日起"
    "30日内」「过渡期至2025年底」)、或明确的时间节点(「第十四个五年规划期末」)才抽;原文没"
    "写时间的条款别抽进来。\n"
    "2. **绝不编日期**。原文说「自印发之日起30日内」就照抄这个相对期当 when,别擅自换算成某个"
    "具体日期;原文没给具体年月就别填一个。模糊就如实保留模糊(「过渡期内」)。\n"
    "3. **锚回真实条款**。每个时间节点必须指到它来自第几条(chapter 填那条的序号),并摘一句"
    "**撑这个时间的原文逐字片段**(原样照抄、不改写)放进 evidence。\n"
    "每个时间节点给:\n"
    "- when:时间本身——具体日期或「自印发之日起30日内」这类相对期,照原文写法。\n"
    "- what:到这个时间点要发生 / 完成什么事,一句话(如「市场主体须完成存量登记」)。\n"
    "- chapter:这个时间节点来自第几条条款(整数序号)。\n"
    "- evidence:撑这个时间的那句原文逐字片段(原样摘录)。\n"
    "- deadline_type:这个时间点是**真咬人的死线**还是**软目标**——**只能填「真deadline」或"
    "「软目标」**。用下面的措辞刻度判:这条绑了硬约束词(应当/必须/限X前办结)、逾期有罚则 / "
    "考核 / 失权(如「逾期不予受理」「未按期完成予以问责」)兜底的 → 「真deadline」;只是"
    "阶段性 / 力争性 / 倡导性的时点(「力争2025年底前达到」「逐步」「条件成熟时」)、逾期没硬后果"
    "的 → 「软目标」。判不准退「软目标」。\n"
    "- deadline_reason:凭原文里**哪个词**判成这档(点出绑的约束词 / 有无逾期罚则,锚原文,"
    "别空说);判不出留空。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏),按时间先后排(说不准先后就按条款序号排):\n"
    '{"nodes":[{"when":"","what":"","chapter":条款序号整数,"evidence":"",'
    '"deadline_type":"软目标","deadline_reason":""}]}'
    "\n\n" + codebook_block()
)

_USER_MSG = "请按上面的要求抽关键时间轴。"


def _compact_clauses(clauses: list[dict[str, Any]]) -> str:
    """把逐条款收成喂给全局推理的紧凑清单——每条:序号 / 事项 / 时限 / 原文。

    只发紧凑清单不发全文(同 concept_evolution「从脊收紧凑清单」),省 token。时限(deadline)
    单列出来当抓手:文脉条款维已经抽了 deadline 字段,这里把它显式摆出来,提示模型哪几条本来
    就带时间(但不限于此——原文 evidence 里也可能藏时间)。
    """
    lines: list[str] = []
    for c in clauses:
        ch = c.get("chapter")
        matter = str(c.get("matter", "")).strip()
        deadline = str(c.get("deadline", "")).strip()
        evidence = str(c.get("evidence", "")).strip()
        # 文脉条款维(1.6.1)已抽了不办的代价(penalty)——把它显式摆出来,是判这个时间点
        # 是真死线还是软目标最直接的 marker:有罚则=真咬人,没罚则多半是软目标。
        penalty = str(c.get("penalty", "")).strip()
        parts = [f"第{ch}条"]
        if matter:
            parts.append(f"事项:{matter}")
        if deadline:
            parts.append(f"时限:{deadline}")
        if penalty:
            parts.append(f"不办的代价:{penalty}")
        if evidence:
            parts.append(f"原文:{evidence}")
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def _coerce_deadline_type(value: Any) -> str:
    """时间点性质归一:必须落进两档封闭集,落不进退「软目标」(最保守,不替时点拔高成真死线)。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in DEADLINE_TYPES else _DEFAULT_DEADLINE_TYPE


def _coerce_node(item: Any) -> dict[str, Any] | None:
    """把一个时间节点 dict 归一成该有的字段;when 与 evidence 都空 → 丢(没时间也没原文摆不进)。

    chapter 缺 / 非整数 → 置 None(节点仍保留,只是锚不回具体条款);when / what / evidence
    coerce 成字符串。绝不在这里补日期——抽不到就是空,真伪靠 verify 那道闸。
    ``deadline_type`` / ``deadline_reason`` 是 1.6.1 约束力层(向后兼容):缺时 deadline_type
    退「软目标」(最保守)、reason 退空串,绝不替一个时点拔高成真死线吓唬用户。
    """
    if not isinstance(item, dict):
        return None
    when = str(item.get("when", "")).strip()
    evidence = str(item.get("evidence", "")).strip()
    # when 和 evidence 都空——既没时间也没原文撑,这节点没意义,丢。
    if not when and not evidence:
        return None
    ch = item.get("chapter")
    chapter = ch if isinstance(ch, int) else None
    return {
        "when": when,
        "what": str(item.get("what", "")).strip(),
        "chapter": chapter,
        "evidence": evidence,
        "deadline_type": _coerce_deadline_type(item.get("deadline_type")),
        "deadline_reason": str(item.get("deadline_reason", "")).strip(),
    }


def _parse_nodes(text: str) -> list[dict[str, Any]] | None:
    """解析一次全局推理回的 ``{nodes:[{when,what,chapter,evidence}]}`` → 归一后的节点列表。

    三层兜底同 doc_spine 条款维:strip 围栏 → json.loads → 抠首个 obj → 截断抢救。解析不出 / 抽空
    返 None(由上层退成空时间轴,不编)。
    """

    def _coerce_list(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        for it in raw:
            node = _coerce_node(it)
            if node is not None:
                out.append(node)
        return out

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
    if isinstance(obj, dict):
        nodes = _coerce_list(obj.get("nodes"))
        if nodes:
            return nodes
    salvaged = _coerce_list(salvage_closed_objects(candidate, '"nodes"') or [])
    if salvaged:
        logger.warning("redhead_timeline: 主解析失败,从截断抢救到 %d 个时间节点", len(salvaged))
        return salvaged
    return None


def timeline_from_spine(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    max_tokens: int = DEFAULT_TIMELINE_MAX_TOKENS,
    max_workers: int | None = None,
    cache_enabled: bool = True,
    **spine_kwargs: Any,
) -> dict[str, Any]:
    """一份公文里散落的时间节点拉成一条时序——拿文脉 → 一次全局推理抽时间 → 锚回原条款过核验。

    复用现成的机器,一行不改 ``doc_spine`` / ``cross_doc`` / ``agent.py``:

    - **文脉**走 ``get_or_build_doc_spine``(同份公文命中缓存秒出,跟公文结构解读 / 大白话翻译
      共用一份文脉)。
    - **抽时间**把逐条款收成紧凑清单(``_compact_clauses``,只发序号 / 事项 / 时限 / 原文、不发全文),
      **一次** LLM 调用(``concept_evolution`` 那台「收紧凑清单 → 一次全局推理 → 锚回真实单元」的
      同机器)把带时间的要求挑出来。
    - **核验**每个节点的 evidence(**撑这个时间的原文逐字片段**)过 ``verify_citations``——核得到
      ``verified=True`` 盖「鉴」印,核不过(含 evidence 空)``verified=False`` 标待核。**时间是从原文
      抽的、不是模型脑补的;一个节点连撑它的原文都核不到,就标待核不当真,绝不假装这个日期有原文撑**。

    Args:
        chunks: 这份公文的 chunk 列表(每条含 ``chunk_id`` / ``chapter`` / ``text``)。
        llm_client: duck-typed LLM client(同 AgentLoop / 文脉)。
        model: 模型名。
        full_text: 这份公文的完整原文(含公布头),透传给文脉构建当头要素抽取 + 兜底锚定。
        max_tokens: 一次全局推理抽时间节点的 max_tokens。
        max_workers: 透传给文脉构建的逐段并发数(本层只一次调用,这参数只影响建文脉那步)。
        cache_enabled: 是否走 L2 缓存(默认开;时间轴这层 + 文脉层都吃)。
        **spine_kwargs: 透传给 ``get_or_build_doc_spine`` 的其余参数(char_budget 等)。

    Returns:
        ``{
            "schema_version": "v1",
            "nodes": [{when(日期或「印发起30日内」这类相对期),
                       what(到这个点要发生啥),
                       chapter(来源条款序号,可能 None),
                       evidence(撑这个时间的原文逐字片段),
                       deadline_type(真deadline/软目标),  # 1.6.1 约束力层
                       deadline_reason,                    # 凭哪个词判的(锚原文)
                       verified, match_score}],
        }``。
        条款空(这份没拆出可逐条的正文)/ 没抽到任何带时间的要求 → ``nodes: []``。
        ``nodes`` 按时间先后排(模型排好的顺序,排不准退按条款序号)。

        **1.6.1 约束力层**(向后兼容,纯增字段):每个节点多带 ``deadline_type``(真 deadline vs
        软目标——前端据此标出哪些时点逾期真咬人)、``deadline_reason``。
    """
    spine = get_or_build_doc_spine(
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        full_text=full_text,
        max_workers=max_workers,
        cache_enabled=cache_enabled,
        **spine_kwargs,
    )
    clauses: list[dict[str, Any]] = spine.get("clauses") or []
    if not clauses:
        return {"schema_version": TIMELINE_SCHEMA_VERSION, "nodes": []}

    # 一次全局推理:把逐条款的紧凑清单当「书」喂进 book-first system(公文也吃前缀缓存——同份
    # 公文的紧凑清单 byte 一致,重看命中),时间轴指令落在清单之后。
    compact = _compact_clauses(clauses)
    system = build_longctx_system(compact, _INSTR_TIMELINE)
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
        nodes = _parse_nodes(llm_client.extract_final_text(resp))
    except Exception as exc:  # noqa: BLE001 — 抽取失败不拖垮整体,退空时间轴(不编)
        logger.warning(
            "redhead_timeline: 时间轴抽取抛 %s: %s;退空时间轴", type(exc).__name__, exc
        )
        nodes = None

    nodes = nodes or []
    if not nodes:
        return {"schema_version": TIMELINE_SCHEMA_VERSION, "nodes": []}

    records: list[dict[str, Any]] = []
    for node in nodes:
        records.append({
            "when": node["when"],
            "what": node["what"],
            "chapter": node["chapter"],
            "evidence": node["evidence"],
            # 1.6.1 约束力层:真deadline vs 软目标(_coerce_node 已落封闭集 / 兜底)。
            "deadline_type": node["deadline_type"],
            "deadline_reason": node["deadline_reason"],
            "verified": False,
            "match_score": 0.0,
        })

    # 核验:每个节点的 evidence(撑这个时间的原文)过 verify_citations。核的是「撑这个日期的那句
    # 原文在文中找得到」——日期是从原文抽的,撑它的原文核不到这节点就标待核,不假装有原文撑。
    evidence_map = build_evidence_map(chunks)
    if full_text and full_text.strip():
        # 同文脉头要素维:公布头(成文日期等)在「第一章」之前会被分块层当章前噪声丢掉,
        # 整份原文兜底锚定——成文日期 / 公布日期常是关键时间节点,光拿 chunks 当证据表核不过。
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": full_text}
    citations = [{"snippet": r["evidence"], "chapter": r["chapter"]} for r in records]
    verify_citations(citations, evidence_map)
    for rec, vc in zip(records, citations, strict=True):
        rec["verified"] = bool(vc.get("verified", False))
        rec["match_score"] = vc.get("match_score", 0.0)

    return {"schema_version": TIMELINE_SCHEMA_VERSION, "nodes": records}


__all__ = [
    "DEADLINE_TYPES",
    "DEFAULT_TIMELINE_MAX_TOKENS",
    "TIMELINE_SCHEMA_VERSION",
    "timeline_from_spine",
]
