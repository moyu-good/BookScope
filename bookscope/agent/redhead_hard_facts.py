"""公文硬信息提取表(1.6 红头文件垂直·三炮)——把一份公文里散落各处的硬信息聚成一张速查表。

**它解决什么**:一份红头文件里真正"要照着办"的硬信息——什么时候前办完、要达多少比例、管哪些
单位、哪天生效哪天废止、谁来负责——往往散落在好几条款、好几页里,读完一遍记不住、回头翻又难找。
这功能把这些硬信息从全份里捞出来聚成一张速查表,按五类(时限 / 数字指标 / 适用范围 / 生效废止 /
责任主体)分组,每条钉一句原文。

**它跟公文结构解读(doc_structure)的分工**:结构解读是把公文**逐条款**拆开看(这条管啥、是
硬要求还是软倡导);硬信息提取是**横切**——不管它在哪条,只要是"时限 / 数字 / 范围 / 起止日 /
责任主体"这五类硬信息,就捞出来汇到一处。结构解读回答"这份公文每条在说什么",硬信息表回答
"我要照着办,得记住哪几个数 / 哪几个日子 / 归谁管"。同一份文脉(``get_or_build_doc_spine``)
建一次,两个功能共用、第二个秒出。

**为什么一次扫全份、不逐条款抽**(跟 redhead_plain 的逐条改写不同):硬信息不绑定单条条款——
一个"生效日期"可能在附则、一个"适用范围"可能在总则、几个"数字指标"散在正文各处。逐条各抽一次
既漏(跨条款的综合范围抽不全)又重(同一个日期被相邻条款各报一遍)。所以这里走**头要素维那套
一次抽取**:整份原文进上下文,一次性把五类硬信息全捞出来汇成一张表(同 ``_build_head_elements``
的模式)。

**怎么做(套现成的机器,一行不改 doc_spine / cross_doc)**:

1. **拿文脉**:走 ``get_or_build_doc_spine`` 拿这份公文的文脉(同份命中缓存秒出,不重精读)。
   文脉本身这里**不直接抽字段**——它的价值是触发/复用那份缓存的整份精读上下文;硬信息要的是
   横切五类,得对全份原文再跑一次专门的抽取。
2. **一次扫全份抽硬信息**:整份原文(``build_longctx_system`` book-first 拼,公文也吃前缀缓存)
   进上下文,跑一次 LLM,要它把五类硬信息(时限 / 数字指标 / 适用范围 / 生效废止 / 责任主体)
   全捞出来,每条给 ``{kind, value, context, evidence}``。死守:value 必须是原文里**真有**的
   数 / 日期 / 范围 / 主体,``evidence`` 给撑它的逐字原文;**抽不到就别抽,绝不编一个数 / 日期**。
3. **kind 走封闭集、value 锚原文过核验**:``kind`` 必须落进五类封闭集,落不进的那条丢(不让模型
   自造一类硬信息)。每条的 ``evidence`` 再过一次 ``verify_citations``——核得到 ``verified=True``
   盖"鉴"印;核不过(含 evidence 空)``verified=False`` 标待核,绝不假装核过了。

铁律:**只 import ``doc_spine_cache`` 的缓存入口 + 现有 helper,一行不改 ``doc_spine`` /
``cross_doc`` / ``agent.py`` / ``schemas.py``**;端点该返的结构写在 ``hard_facts_from_spine``
的 docstring 里给主 Claude 接线。
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

HARD_FACTS_SCHEMA_VERSION = "v1"
"""硬信息表结构版本——升级要让从文脉派生的这层重算(文脉缓存不受影响,只是这层重跑)。"""

DEFAULT_HARD_FACTS_MAX_TOKENS = 8000
"""一次扫全份抽硬信息的 max_tokens。

**1500 是返 0 的根因**:这功能把整份公文原文进上下文(``build_longctx_system`` 全文),
跟时间轴(只喂逐条款紧凑清单、输入轻)不是一码事——全文进上下文后,deepseek-v4-flash 会
先吐一大段 ``reasoning_content``,而它把 reasoning 也算进 max_tokens(见
reference_reasoning_model_token_budget)。1500 这点预算全被 reasoning 吃光,
``finish_reason=length`` 而 ``content`` 是空的,解析自然抽到 0 条(国办意见实测:
1500→content 空、facts 0;8000→正常抽到「2020年底前」等)。

所以对齐**同样把整份原文进上下文**的兄弟那档:``doc_spine._build_head_elements`` 走
``DEFAULT_DOC_SPINE_MAX_TOKENS = 8000``。8000 装得下一张几十条的硬信息表,还给
reasoning 留足头;真被截断有 ``salvage_closed_objects`` 抢救兜底。"""

# 五类硬信息(封闭集)。落不进这五类的条目丢——不让模型自造一类硬信息(同文种 / 指令类型封闭集
# 的纪律)。顺序就是速查表里分组的展示顺序。
HARD_FACT_KINDS: tuple[str, ...] = (
    "时限",      # X日内办结 / 限X月底前完成 / 自X日起执行多少天 —— 要赶的时间点
    "数字指标",  # 达XX% / 不低于XX元 / 控制在XX以内 —— 要达到的量化目标
    "适用范围",  # 适用于哪些单位 / 哪类对象 / 哪个区域 —— 管谁、管到哪
    "生效废止",  # 自X年X月X日起施行 / X文件同时废止 —— 这份文件的时效起止
    "责任主体",  # 由X部门负责 / X单位牵头落实 —— 谁来办、谁牵头
)

# 约束力(binding)两档(封闭集,1.6.1 加的判断层)——一个数是有罚则兜底的硬门槛,还是
# 「力争/参考」的软目标。判据走 codebook 的约束力阶梯 + 开环/闭环:绑硬约束词(应当/不得/
# 限X前)且有考核罚则的数 = 硬指标;带「力争/原则上/参考/不低于…(纯倡导)」的 = 参考值。
BINDINGS: tuple[str, ...] = (
    "硬指标",  # 有罚则/考核兜底、必须达到的硬门槛(应当达XX% / 限X前办结,逾期问责)
    "参考值",  # 倡导性、力争性、参考性的软目标(力争达XX% / 原则上不超 / 参考标准)
)
_DEFAULT_BINDING = "参考值"
"""约束力落不进两档的兜底——退「参考值」(最保守,不替一个数拔高成硬指标误导用户)。"""

# 一次扫全份抽硬信息的指令。死守:只抽原文真有的、kind 落五类、value 锚 evidence、绝不编数字/日期。
_INSTR_HARD_FACTS = (
    "你在给一份党政机关公文(红头文件)做**硬信息提取**——把读者真正要照着办、必须记住的"
    "硬信息从全文里捞出来,汇成一张速查表。只看**硬信息**(具体的数 / 日期 / 范围 / 主体),"
    "不要泛泛的态度倡导、不要原则性表述。\n"
    "硬信息分这**五类**,每条只能归其中一类(``kind`` 字段只能填这五个之一):\n"
    "- 时限:得在什么时候前办完 / 执行多久,如「应当于30日内办结」「限2024年6月底前完成」。\n"
    "- 数字指标:要达到的量化目标,如「不低于85%」「补贴每户2000元」「控制在3%以内」。\n"
    "- 适用范围:这份文件管谁 / 管到哪,如「适用于本市各区县人民政府」「面向规模以上工业企业」。\n"
    "- 生效废止:这份文件本身的时效起止,如「自2024年1月1日起施行」「X号文件同时废止」。\n"
    "- 责任主体:具体哪个部门 / 单位牵头办 / 负责落实,如「由市发改委牵头」「各乡镇政府负责」。\n"
    "每条硬信息给:\n"
    '1. ``kind``:上面五类之一(填不进这五类的硬信息别抽)。\n'
    '2. ``value``:这条硬信息本身,短、准——把那个数 / 日期 / 范围 / 主体说清,如「30日内」'
    '「不低于85%」「本市各区县人民政府」「2024年1月1日起施行」「市发改委牵头」。\n'
    '3. ``context``:这条出自哪条 / 管的什么事,一句话点明它的语境(如「项目审批时限」'
    '「企业研发投入占比目标」),让读者知道这个数 / 日期是管啥的。\n'
    '4. ``evidence``:原文里**撑这条的逐字片段**(原样摘录、不改写)。\n'
    '5. ``binding``:这个数的**约束力**——**只能填「硬指标」或「参考值」**。看它绑的措辞'
    "(用下面的约束力阶梯判):有「应当/必须/不得/限X前」这类硬约束词、且有考核/罚则/问责兜底、"
    "逾期或未达有代价的 → 「硬指标」(必须达到的硬门槛);带「力争/原则上/参考/倡导」这类软措辞、"
    "或纯方向性目标、没罚则没人盯的 → 「参考值」(软目标,达不到也没硬后果)。判不准退「参考值」。\n"
    '6. ``binding_reason``:凭原文里**哪个词**判成这档(点出绑的约束词 / 有无罚则考核,锚原文,'
    "别空说);判不出留空。\n"
    "死守三条:\n"
    "①只抽原文**真有**的硬信息;原文没写的数 / 日期 / 范围 / 主体,一个都别编、别猜、别推算。\n"
    "②``value`` 必须能在 ``evidence`` 里找到出处;``evidence`` 找不到的那条别抽。\n"
    "③同一条硬信息只汇一次,别因为它在多处出现就重复列。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏),形如:\n"
    '{"facts":[{"kind":"时限","value":"","context":"","evidence":"",'
    '"binding":"参考值","binding_reason":""}]}'
    "\n\n" + codebook_block()
)

_USER_MSG = "请按上面的要求把这份公文的硬信息提取成速查表。"


def _coerce_kind(value: Any) -> str:
    """硬信息类别归一:必须落进五类封闭集,落不进退空串(由上层丢这条,不自造类)。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in HARD_FACT_KINDS else ""


def _coerce_binding(value: Any) -> str:
    """约束力归一:必须落进两档封闭集,落不进退「参考值」(最保守,不替一个数拔高成硬指标)。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in BINDINGS else _DEFAULT_BINDING


def _coerce_fact(item: Any) -> dict[str, Any] | None:
    """把一条硬信息 dict 归一;kind 落不进五类 或 value 空 → 丢(没类别 / 没值的不进表)。

    value 是这条硬信息本身,空了这条没意义(读者拿不到那个数 / 日期);kind 落不进五类说明
    模型自造了一类,丢。evidence / context 缺退空串(evidence 空会在核验那步标待核)。
    ``binding`` / ``binding_reason`` 是 1.6.1 约束力层(向后兼容):缺时 binding 退「参考值」
    (最保守)、reason 退空串,绝不替一个数拔高成硬指标。
    """
    if not isinstance(item, dict):
        return None
    kind = _coerce_kind(item.get("kind"))
    value = item.get("value")
    value = value.strip() if isinstance(value, str) else ""
    if not kind or not value:
        return None
    return {
        "kind": kind,
        "value": value,
        "context": str(item.get("context", "")).strip(),
        "evidence": str(item.get("evidence", "")).strip(),
        "binding": _coerce_binding(item.get("binding")),
        "binding_reason": str(item.get("binding_reason", "")).strip(),
    }


def _parse_facts(text: str) -> list[dict[str, Any]]:
    """解析 ``{facts:[{kind,value,context,evidence}]}`` → 归一后的硬信息列表。

    三层兜底同文脉:strip 围栏 → json.loads → 抠首个 obj → 截断抢救。归一走 ``_coerce_fact``
    (丢 kind 落不进五类 / value 空的),按 (kind, value) 去重(同一条硬信息只汇一次)。
    解析不出 / 全被归一丢掉 → 返空列表。
    """
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

    facts_raw: Any = None
    if isinstance(obj, dict):
        facts_raw = obj.get("facts")
    if not isinstance(facts_raw, list):
        salvaged = salvage_closed_objects(candidate, '"facts"')
        if salvaged:
            logger.warning("redhead_hard_facts: 主解析失败,从截断抢救硬信息")
            facts_raw = salvaged
        else:
            return []

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for it in facts_raw:
        fact = _coerce_fact(it)
        if fact is None:
            continue
        dedup_key = (fact["kind"], fact["value"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        out.append(fact)
    return out


def hard_facts_from_spine(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    max_tokens: int = DEFAULT_HARD_FACTS_MAX_TOKENS,
    max_workers: int | None = None,  # noqa: ARG001 — 一次扫全份不分段,留参对齐兄弟模块签名
    cache_enabled: bool = True,
    **spine_kwargs: Any,
) -> dict[str, Any]:
    """一份公文的硬信息聚成速查表——触发/复用文脉缓存 → 一次扫全份抽五类硬信息 → 锚原文过核验。

    复用现成的机器,一行不改 ``doc_spine`` / ``cross_doc``:

    - **文脉**走 ``get_or_build_doc_spine``(同份公文命中缓存秒出,跟公文结构解读 / 大白话翻译
      共用一份文脉的整份精读)。文脉本身这里不拆字段——它的价值是触发/复用那份缓存,硬信息要的
      是横切五类,得对全份原文再跑一次专门抽取。
    - **抽取**一次扫全份(整份原文进 ``build_longctx_system`` book-first 上下文、吃前缀缓存),
      跑一次 LLM 把五类硬信息全捞出来(同头要素维一次抽取的模式,不逐条款分段——硬信息不绑单条)。
      走 ``invoke_client_cached`` 缓存,同份第二次看秒出、不重付 token。
    - **核验**每条硬信息的 ``evidence`` 过 ``verify_citations``——核的是"撑这条的那句原文在文中
      找得到"。核得到 ``verified=True`` 盖"鉴"印;核不过(含 evidence 空)``verified=False``
      标待核。绝不编数字 / 日期:value 必须有原文撑,核不过的老实标待核让用户回原件。

    ``max_workers`` 这里用不上(一次扫全份不分段),留参只为对齐 ``plain_language_from_spine`` /
    ``build_doc_spine`` 的签名,端点接线时可统一透传。

    Args:
        chunks: 这份公文的 chunk 列表(每条含 ``chunk_id`` / ``chapter`` / ``text``)。
        llm_client: duck-typed LLM client(同 AgentLoop / 文脉)。
        model: 模型名。
        full_text: 这份公文的**完整原文**(含公布头)。传了抽取就用它进上下文 + 当核验兜底锚
            (公布头在"第一章"前会被分块层丢掉,光拿 chunks 拼全文里的生效日期等可能核不过);
            没传退回 ``chunks`` 拼接(向后兼容)。
        max_tokens: 一次扫全份抽硬信息的 max_tokens。整份原文进上下文后 reasoning 也吃这个
            预算(deepseek-v4-flash),太小会被 reasoning 吃光导致 content 空、抽 0 条——
            默认 8000 对齐 ``doc_spine`` 同样全文进上下文那档。
        max_workers: 占位,不生效(一次扫全份不分段)。
        cache_enabled: 是否走 L2 缓存(默认开;抽取层 + 文脉层都吃)。
        **spine_kwargs: 透传给 ``get_or_build_doc_spine`` 的其余参数(char_budget 等)。

    Returns:
        ``{
            "schema_version": "v1",
            "facts": [{kind(五类之一), value, context, evidence, verified, match_score,
                       binding(硬指标/参考值),  # 1.6.1 约束力层
                       binding_reason}],         # 凭哪个词判的(锚原文)
        }``。
        ``facts`` 按 ``HARD_FACT_KINDS`` 的类别顺序(时限→数字指标→适用范围→生效废止→责任主体)
        排,同类内保抽取顺序——前端按 kind 分组成速查要目时直接顺着排。没抽到任何硬信息 →
        ``facts: []``(前端优雅退场,不画空表)。

        **1.6.1 约束力层**(向后兼容,纯增字段):每条多带 ``binding``(硬指标 vs 参考值——
        前端据此把有罚则兜底的硬门槛和「力争/参考」软目标分开标)、``binding_reason``。
    """
    # 触发/复用文脉缓存:同份公文这步命中缓存秒出,跟结构解读 / 大白话共用整份精读。
    # 文脉本身不在这拆字段(硬信息要横切五类,得对全份再跑专门抽取),但走这个入口能复用那份
    # 已精读过的上下文缓存、不重精读。
    get_or_build_doc_spine(
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        full_text=full_text,
        cache_enabled=cache_enabled,
        **spine_kwargs,
    )

    # 一次扫全份抽硬信息:整份原文进上下文(优先完整原文,含公布头;没传退 chunk 拼接)。
    source_text = (
        full_text
        if (full_text and full_text.strip())
        else "".join(str(c.get("text", "")) for c in chunks)
    )
    if not source_text.strip():
        return {"schema_version": HARD_FACTS_SCHEMA_VERSION, "facts": []}

    system = build_longctx_system(source_text, _INSTR_HARD_FACTS)
    facts: list[dict[str, Any]] = []
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
        facts = _parse_facts(llm_client.extract_final_text(resp))
    except Exception as exc:  # noqa: BLE001 — 抽取失败不抛,返空表(前端优雅退场)
        logger.warning(
            "redhead_hard_facts: 抽取抛 %s: %s;返空表", type(exc).__name__, exc
        )
        facts = []

    if not facts:
        return {"schema_version": HARD_FACTS_SCHEMA_VERSION, "facts": []}

    # 核验:每条硬信息的 evidence 过 verify_citations。核的是"撑这条的那句原文在文中找得到"。
    # 证据表除 chunks 外补一条整份原文兜底——公布头(生效日期 / 成文日期常在公布头)在"第一章"
    # 之前会被分块层当章前噪声丢掉、不进任何 chunk,光拿 chunks 当证据表这类硬信息永远核不过。
    evidence_map = build_evidence_map(chunks)
    if source_text.strip():
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": source_text}
    citations = [{"snippet": f["evidence"]} for f in facts]
    verify_citations(citations, evidence_map)
    for f, vc in zip(facts, citations, strict=True):
        f["verified"] = bool(vc.get("verified", False))
        f["match_score"] = vc.get("match_score", 0.0)

    # 按五类顺序稳定排序(同类内保抽取顺序)——前端按 kind 分组直接顺着排。
    kind_order = {k: i for i, k in enumerate(HARD_FACT_KINDS)}
    facts.sort(key=lambda f: kind_order.get(f["kind"], len(HARD_FACT_KINDS)))

    return {"schema_version": HARD_FACTS_SCHEMA_VERSION, "facts": facts}


__all__ = [
    "BINDINGS",
    "DEFAULT_HARD_FACTS_MAX_TOKENS",
    "HARD_FACTS_SCHEMA_VERSION",
    "HARD_FACT_KINDS",
    "hard_facts_from_spine",
]
