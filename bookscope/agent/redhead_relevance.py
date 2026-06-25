"""公文「跟我相关」(1.6 红头文件垂直·发明区一炮)——用户报上自己的身份,从一份公文里
圈出**跟他相关的条款** + 对他意味着什么。

**它解决什么**:一份红头文件几十条,普通人(个体工商户 / 某市市场监管局 / 某企业)真正
要操心的就那几条。这功能让用户报上身份,逐条判「这条跟你这种身份相不相关」,相关的话再说
清是**义务**(你得照办)/ **利好**(给你的好处)/ **条件**(满足了才适用 / 才能享),外加
一句「对你」的人话。不相关的条款一条不返——只把跟你有关的圈出来。

**它跟「公文结构解读 / 大白话翻译」的分工**:那俩把整份公文拆给所有人看(头要素 + 逐条款 /
官话翻人话);这个**带着你的身份**重看一遍,只留跟你这种身份相关的,并说清对你是义务还是利好。
独有维度 = 个性化(同一份公文,个体户看到的和市监局看到的是两份不同的清单)。同一份文脉
(``get_or_build_doc_spine``)建一次,三个功能共用、这个秒接。

**怎么做(套现成的机器,一行不改 doc_spine / cross_doc)**:

1. **拿文脉**:走 ``get_or_build_doc_spine`` 拿这份公文的文脉(条款带 instruction_type /
   actor / deadline / evidence)。同份公文命中缓存秒出,不重精读。
2. **逐条款带身份判相关**:对每条 clause 跑一次 LLM,把**用户身份 + 这一条的事项 / 指令类型 /
   责任主体 / 时限 / 原文**喂进去,要它判:这条跟这个身份相不相关?相关的话是义务 / 利好 /
   条件?给一句「对你」的人话。逐条并发(``ThreadPoolExecutor``,同穷尽化分段并发),每条走
   ``invoke_client_cached`` 缓存——同一份公文 + 同一身份第二次看秒出、不重付 token。
3. **相关的才锚原文过核验**:判为相关的条款,evidence(**原条款逐字原文**)再过一次
   ``verify_citations``——核得到 ``verified=True`` 盖「鉴」印。核的是「这条原文在文里找得到」,
   不是核 LLM 的相关判断(那是判断、本就没法核到原文)。判不相关 / 判断失败的条款不返。

铁律:**只 import ``doc_spine_cache`` 的缓存入口 + 现有 helper,一行不改 ``doc_spine`` /
``cross_doc`` / ``agent`` / ``schemas``**;不碰端点(端点该返的结构写在
``relevance_from_spine`` 的 docstring 里给主 Claude 接线)。evidence-first:锚原条款、核不过
标待核,绝不编原文没有的;LLM 说不相关就不返,不硬塞。
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from bookscope.agent._internal.doc_spine_cache import get_or_build_doc_spine
from bookscope.agent._internal.exhaustive import resolve_workers
from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

RELEVANCE_SCHEMA_VERSION = "v1"
"""「跟我相关」记录结构版本——升级要让从文脉派生的这层重算(文脉缓存不受影响,只是相关判断层重跑)。"""

DEFAULT_RELEVANCE_MAX_TOKENS = 1200
"""逐条款判相关单条的 max_tokens。一条判断 + 一句对你的话就一两句,1200 留足 reasoning 头
(deepseek-v4-flash 把 reasoning_content 算进 max_tokens,
见 reference_reasoning_model_token_budget)。"""

# 相关度两档(封闭集)。**不让模型打 0-10 分**——做成带原文撑的分类标签(同 instruction_type
# 的纪律,feedback_viz_algorithm_rigor):落不进就退「中」。
RELEVANCE_LEVELS: tuple[str, ...] = ("高", "中")
_DEFAULT_RELEVANCE = "中"

# 「对你意味着什么」三标签(封闭集)。同样是带原文撑的分类,不是分数。
BEARINGS: tuple[str, ...] = (
    "义务",  # 你这种身份得照办的(应当/必须/不得/限X日前)
    "利好",  # 给你这种身份的好处/便利/扶持(减免/补贴/简化/支持)
    "条件",  # 满足了才适用 / 才能享 / 才被管到的前提(符合X的/达到Y的)
)
_DEFAULT_BEARING = "条件"
"""bearing 落不进三类的兜底——退「条件」(最中性,不替用户断成义务也不许成利好)。"""

# 逐条带身份判相关的指令。把用户身份 + 这一条的字段喂进去,要 LLM 判相关 / bearing / 一句对你的话。
# 死守:不相关就老实说不相关、不硬塞;相关判断只依据这一条说的,别替用户脑补原文没有的义务/好处。
_INSTR_RELEVANCE = (
    "你是帮普通人(可能是个体工商户、某政府部门、某企业等)读懂党政机关公文(红头文件)的助手。"
    "用户告诉你他的**身份**,下面再给你公文里的**一条**条款(它的事项 / 指令类型 / 责任主体 / "
    "时限 / 原文)。\n"
    "请判断:**这一条跟这个身份的人相不相关**——也就是这条会不会落到他头上(要他办、给他好处、"
    "或设了他要满足的条件)。\n"
    "判断只依据这一条原文说的,别替用户脑补原文没写的义务或好处。死守:\n"
    "1. relevant:这条跟这个身份相不相关,只填 true / false。**拿不准、明显是管别的部门/别类"
    "主体的,就填 false**——宁可漏判不相关,绝不硬把无关的塞给他。\n"
    "2. relevant=false 时,后面几项随便填空,不会用到。\n"
    "3. relevant=true 时再填:\n"
    "   - level:相关度,只能填「高」或「中」。直接点名这类身份 / 明显主要冲他来的填「高」;"
    "沾边、间接相关的填「中」。\n"
    "   - bearing:对他意味着什么,只能填以下三个之一:\n"
    "       · 义务:他这种身份**得照办**的(应当/必须/不得/限X日前 这类硬要求落到他头上)。\n"
    "       · 利好:**给他**这种身份的好处 / 便利 / 扶持(减免/补贴/简化手续/优先/支持)。\n"
    "       · 条件:满足了**才适用 / 才能享 / 才被管到**的前提(「符合X的」「达到Y标准的」)。\n"
    "   - note:用人话写**一句**「对你」——直接称呼「你」,说清这条对他到底是什么意思、"
    "要他做什么或他能得到什么。只转述这条说的,别加原文没有的承诺/数字/处罚。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏),形如:\n"
    '{"relevant":true,"level":"高","bearing":"义务","note":""}'
)


def _coerce_level(value: Any) -> str:
    """相关度归一:必须落进两档封闭集,落不进退「中」。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in RELEVANCE_LEVELS else _DEFAULT_RELEVANCE


def _coerce_bearing(value: Any) -> str:
    """bearing 归一:必须落进三类封闭集,落不进退「条件」(最中性兜底)。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in BEARINGS else _DEFAULT_BEARING


def _parse_judgment(text: str) -> dict[str, Any] | None:
    """解析单条判断 ``{relevant, level, bearing, note}``——两层兜底(直接 loads → 抠首个 obj)。

    解析不出返 None(由上层当「这条没判出来、不返」处理)。relevant 不是 bool / 缺 → 当不相关。
    """
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
    if not isinstance(obj, dict):
        return None
    relevant = obj.get("relevant")
    if not isinstance(relevant, bool):
        # 有的模型回 "true"/"是" 字符串,宽松认一下;认不出当不相关。
        relevant = str(relevant).strip().lower() in ("true", "1", "是", "yes")
    return {
        "relevant": relevant,
        "level": _coerce_level(obj.get("level")),
        "bearing": _coerce_bearing(obj.get("bearing")),
        "note": str(obj.get("note", "")).strip(),
    }


def _judge_one(
    clause: dict[str, Any],
    *,
    role: str,
    llm_client: Any,
    model: str,
    max_tokens: int,
    cache_enabled: bool,
) -> dict[str, Any] | None:
    """带身份判一条条款相不相关——单条 LLM 调用,失败 / 解析不出返 None(由上层丢掉不返)。

    只把这一条的字段(事项 / 指令类型 / 责任主体 / 时限 / 原文)+ 用户身份喂进去(不喂全文),
    走 ``invoke_client_cached`` 缓存。用 ``build_longctx_system`` 拼(同站内其它功能,book-first
    前缀也让这层吃缓存:同一份公文 + 同一身份第二次判命中)——这里「书」位置放身份 + 这一条。
    """
    matter = str(clause.get("matter", "")).strip()
    evidence = str(clause.get("evidence", "")).strip()
    # 判相关至少得有「事项」或「原文」之一,否则没东西可判。
    if not (matter or evidence):
        return None
    payload = (
        f"用户身份:{role}\n\n"
        f"条款事项:{matter or '(未给)'}\n"
        f"指令类型:{clause.get('instruction_type') or '(未标)'}\n"
        f"责任主体:{clause.get('actor') or '(未标)'}\n"
        f"时限:{clause.get('deadline') or '(无)'}\n\n"
        f"原文:{evidence or '(未给逐字原文)'}"
    )
    system = build_longctx_system(payload, _INSTR_RELEVANCE)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=system,
            tools=[],
            messages=[{"role": "user", "content": "请按上面的要求判断并输出 JSON。"}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        return _parse_judgment(llm_client.extract_final_text(resp))
    except Exception as exc:  # noqa: BLE001 — 单条判断失败不拖垮整体,丢掉这条不返
        logger.warning(
            "redhead_relevance: 第 %s 条判断抛 %s: %s;丢掉不返",
            clause.get("chapter"),
            type(exc).__name__,
            exc,
        )
        return None


def relevance_from_spine(
    *,
    chunks: list[dict[str, Any]],
    role: str,
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    max_tokens: int = DEFAULT_RELEVANCE_MAX_TOKENS,
    max_workers: int | None = None,
    cache_enabled: bool = True,
    **spine_kwargs: Any,
) -> dict[str, Any]:
    """带用户身份,从一份公文里筛出跟他相关的条款 + 对他是义务 / 利好 / 条件。

    复用现成的机器,一行不改 ``doc_spine`` / ``cross_doc``:

    - **文脉**走 ``get_or_build_doc_spine``(同份公文命中缓存秒出,跟结构解读 / 大白话共用一份)。
    - **判相关**逐条款各跑一次 LLM(``_judge_one``,只喂身份 + 这一条的字段、不喂全文),
      ``ThreadPoolExecutor`` 并发,每条走 ``invoke_client_cached`` 缓存。判不相关 / 判断失败的
      条款**不返**(只圈出跟你有关的)。
    - **核验**判为相关的条款,这条的 **原文 evidence** 过一次 ``verify_citations``——核得到
      ``verified=True`` 盖「鉴」印;核不过(含原文为空)``verified=False`` 标待核。核的是「这条
      原文在文里找得到」,不是核 LLM 的相关判断。

    Args:
        chunks: 这份公文的 chunk 列表(每条含 ``chunk_id`` / ``chapter`` / ``text``)。
        role: 用户报的身份(自由文本,如「个体工商户」「某市市场监管局」「一家小餐饮企业」)。
            空身份 → 直接返空 items(没身份没法判相关)。
        llm_client: duck-typed LLM client(同 AgentLoop / 文脉)。
        model: 模型名。
        full_text: 这份公文的完整原文(含公布头),透传给文脉构建当头要素抽取 + 兜底锚定。
        max_tokens: 逐条判断单条的 max_tokens(一条判断 + 一句话够用)。
        max_workers: 逐条并发数(透传 ``resolve_workers``,同穷尽化分段并发)。
        cache_enabled: 是否走 L2 缓存(默认开;判断层 + 文脉层都吃)。
        **spine_kwargs: 透传给 ``get_or_build_doc_spine`` 的其余参数(char_budget 等)。

    Returns:
        ``{
            "schema_version": "v1",
            "role": 回显用户身份,
            "items": [{chapter(原条款序号), matter(原公文体事项), relevance("高"/"中"),
                       bearing("义务"/"利好"/"条件"), note(对你一句话),
                       evidence(原条款逐字原文), verified, match_score}],
        }``。
        **只含判为相关的条款**(不相关 / 判断失败的不返);按相关度(高在前)再按原条款序号排。
        身份空 / 没条款 / 没一条相关 → ``items: []``。
    """
    role = (role or "").strip()
    if not role:
        return {"schema_version": RELEVANCE_SCHEMA_VERSION, "role": "", "items": []}

    spine = get_or_build_doc_spine(
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        full_text=full_text,
        cache_enabled=cache_enabled,
        **spine_kwargs,
    )
    clauses: list[dict[str, Any]] = spine.get("clauses") or []
    if not clauses:
        return {"schema_version": RELEVANCE_SCHEMA_VERSION, "role": role, "items": []}

    workers = resolve_workers(max_workers)

    def _do(clause: dict[str, Any]) -> dict[str, Any] | None:
        return _judge_one(
            clause,
            role=role,
            llm_client=llm_client,
            model=model,
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )

    if workers <= 1 or len(clauses) <= 1:
        judgments = [_do(c) for c in clauses]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            judgments = list(ex.map(_do, clauses))

    # 只留判为相关的;判断失败(None)/ 判不相关都丢掉,不返。
    items: list[dict[str, Any]] = []
    for clause, judgment in zip(clauses, judgments, strict=True):
        if judgment is None or not judgment.get("relevant"):
            continue
        items.append({
            "chapter": clause.get("chapter"),
            "matter": str(clause.get("matter", "")).strip(),
            "relevance": judgment["level"],
            "bearing": judgment["bearing"],
            "note": judgment["note"],
            "evidence": str(clause.get("evidence", "")).strip(),
            "verified": False,
            "match_score": 0.0,
        })

    if not items:
        return {"schema_version": RELEVANCE_SCHEMA_VERSION, "role": role, "items": []}

    # 核验:每条相关条款的**原文 evidence** 过 verify_citations。核的是「这条原文在文里找得到」——
    # 锚的是原条款逐字原文(不是 LLM 的相关判断,那是判断、核不到原文)。
    evidence_map = build_evidence_map(chunks)
    if full_text and full_text.strip():
        # 同文脉头要素维:公布头在「第一章」之前会被分块层当章前噪声丢掉,整份原文兜底锚定。
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": full_text}
    citations = [{"snippet": it["evidence"]} for it in items]
    verify_citations(citations, evidence_map)
    for it, vc in zip(items, citations, strict=True):
        it["verified"] = bool(vc.get("verified", False))
        it["match_score"] = vc.get("match_score", 0.0)

    # 排序:相关度高的在前,同档按原条款序号(读起来跟原文顺序对得上)。
    _level_rank = {"高": 0, "中": 1}
    items.sort(
        key=lambda it: (
            _level_rank.get(it["relevance"], 2),
            it["chapter"] if isinstance(it.get("chapter"), int) else 1_000_000,
        )
    )

    return {"schema_version": RELEVANCE_SCHEMA_VERSION, "role": role, "items": items}


__all__ = [
    "BEARINGS",
    "DEFAULT_RELEVANCE_MAX_TOKENS",
    "RELEVANCE_LEVELS",
    "RELEVANCE_SCHEMA_VERSION",
    "relevance_from_spine",
]
