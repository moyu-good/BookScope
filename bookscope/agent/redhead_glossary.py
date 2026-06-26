"""公文名词解释(1.6 红头文件垂直·三炮)——把一份公文里普通人看不懂的术语挑出来、用人话释义。

**它解决什么**:红头文件满是政策黑话——「证照分离」「负面清单」「放管服」「一业一证」
「双随机一公开」。普通人读到这些词卡住:不知道是啥、跟自己有什么关系。这功能把一份公文里
**外行看不懂的术语**挑出来,每个用大白话讲清楚是什么意思,并锚回这个词在原文出现的那句。

**深度升级(WP-redhead-deep-reading-lenses「名词解释」那行,2026-06-26)**:不止给词典定义,
再加两层「读弦外」的功夫:

- **语境含义(context_meaning,证据层)**:这词在**这份文件里**特指什么——不是泛泛词典义。
  比如「平台」在一份公文里特指「网络交易平台经营者」,在另一份里特指「政务服务平台」;同一个
  词典词,落到具体文件里所指往往收窄。这层照样锚原文(跟着术语出现的那句原文走、不另起证据),
  讲解失败 / 核不过就退空,绝不编。
- **政策意图(policy_intent,评估层·研判)**:这术语 / 简称绑的政策方向或信号(「放管服」=简政
  放权改革方向、「包容审慎」=对新业态先松后管的姿态)。这是**推断**、直接撞 evidence-first,所以
  **绝不当词典事实**:前端标研判、视觉区别于定义。没有可靠政策意图的词就不给(可选字段、留空),
  绝不为了凑而硬编。

**跟另两个公文功能的分工**:
- 公文结构解读(doc_structure):把一份公文拆成头要素 + 逐条款的「结构」。
- 大白话翻译(redhead_plain):逐条款把整句官话改写成人话(「一条 → 一句白话」)。
- 名词解释(本模块):换个看法——不逐条翻整句,只把**散落在全文里的难词**挑出来逐个释义
  (「一个词 → 一条注解」)。同一个词在全文出现几次,只出一条;释义讲的是「这词什么意思」,
  不是「这句话什么意思」。独有维度 = 笺注(给难词夹注释义 + 本文件语境特指义 + 政策意图研判)。

三个功能共用同一份文脉(``get_or_build_doc_spine``):建一次,谁先点谁付精读的钱,后点的秒出。

**怎么做(套现成的机器,一行不改 doc_spine / cross_doc)**:

1. **拿文脉**:走 ``get_or_build_doc_spine`` 拿这份公文的文脉(头要素 + 条款,带证据)。同份
   公文命中缓存秒出,不重精读。文脉这里只当「这份公文读得通」的闸 + 共用缓存;难词识别是
   对全文重跑一遍 map(术语散落在任何条款里,不是一条一个词,所以不逐条款跑、改逐段跑)。
2. **分段并发识别难词**:对全文按字数分段(``run_segments``,同穷尽化 / 文脉条款维的道理),
   每段让 LLM 挑出「外行看不懂、需要解释的术语」+ 给人话释义 + 抠这词出现的原句当 evidence。
   段间按归一化的词面去重(同一个词跨段重复只留一条)。
3. **释义锚回原句,过核验**:每个词的 evidence(**这词出现的逐字原句**,不是释义)再过一次
   ``verify_citations``——核得到 ``verified=True`` 盖「鉴」印。核的是「这词真在原文出现过、
   那句找得到」,不是核释义本身(释义是讲解、不该也核不到原文)。识别失败 / 核不过的词,
   evidence 退空 + 标 ``verified=False``,绝不假装这词有原文撑。**语境含义**跟着同一句原文走
   (不另起证据,核不过原句时它也跟着失去原文撑、由前端按未核验呈现);**政策意图**是研判、
   不进核验(评估层),前端单独标研判。

铁律:**只 import ``doc_spine_cache`` 的缓存入口 + 现有 helper,一行不改 ``doc_spine`` /
``cross_doc`` / ``agent.py`` / ``schemas.py``**;端点该返的结构写在 ``glossary_from_spine``
的 docstring 里给主 Claude 接线。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.doc_spine_cache import get_or_build_doc_spine
from bookscope.agent._internal.exhaustive import (
    DEFAULT_CHAR_BUDGET,
    run_segments,
)
from bookscope.agent.citation_check import (
    build_evidence_map,
    normalize_text,
    verify_citations,
)
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

GLOSSARY_SCHEMA_VERSION = "v2"
"""名词解释记录结构版本——升级要让从文脉派生的这层重算(文脉缓存不受影响,只是释义层重跑)。

v2 = 每条在 ``explanation``(词典义)之外加 ``context_meaning``(本文件语境特指义,证据层、可选)
和 ``policy_intent``(政策意图研判,评估层、可选)。向后兼容:老字段不动,新字段缺就退空串。"""

DEFAULT_GLOSSARY_MAX_TOKENS = 1800
"""难词识别单段输出的 max_tokens。一段挑十来个词、每个一句释义 + 原句,v2 再多两段(语境含义 +
政策意图),输出比 v1 长些;从 1500 提到 1800 留足 reasoning 头还够用(deepseek-v4-flash 把
reasoning_content 算进 max_tokens,见 reference_reasoning_model_token_budget)。"""

_GLOSSARY_MAX_CHAPTERS = 8
"""难词识别分段的章节闸。比文脉条款维(3)宽:这里一段只挑词、不抽逐字段的密结构,输出条目轻,
8 章一段也塞得下 1500;比全局默认(12)略收,避免词条多的密集公文段冲 max_tokens。"""

# 分段识别难词的指令——喂这一段原文,让模型挑「外行看不懂、需要解释的术语」+ 给人话释义 +
# 本文件语境特指义 + 政策意图研判 + 抠这词出现的原句当 evidence。
# 死守:只挑真在这段出现的词、释义/语境义忠实不编、政策意图没把握就留空、原句逐字抄。
_INSTR_GLOSSARY = (
    "你是帮普通人读懂党政机关公文(红头文件)的助手。公文里常有外行看不懂的政策术语和"
    "专有名词——比如「证照分离」「负面清单」「放管服」「一业一证」「双随机一公开」"
    "「四个意识」「营商环境」这类词,普通人读到会卡住、不知道是什么意思。\n"
    "请从上面这段公文原文里,挑出**普通人看不懂、需要解释的术语 / 专有名词 / 政策简称**,"
    "每个给出:\n"
    "1. term:术语本身,**逐字抄原文里的写法**,别改写、别加书名号。\n"
    "2. explanation:用大白话讲清这个词**本身**是什么意思(泛义、词典义),死守三条——"
    "(a) 只讲这个词本身的含义,像在跟一个没听过这词的朋友解释;(b) 别编原文 / 常识里没有的东西;"
    "(c) 一两句话说完,短句、口语化、说人话。\n"
    "3. context_meaning:这个词**在这份文件里特指什么**——不是泛泛词典义,是它落到本文这具体"
    "语境里指的那个确定对象 / 确定范围。比如「平台」在一份文件里特指「网络交易平台经营者」、"
    "在另一份里特指「政务服务系统」。死守:**只能从上面原文的实际用法里读出来**——原文怎么用、"
    "它就特指什么,别拿文件外的常识硬套。如果原文用法跟词典义没差别、读不出更具体的所指,"
    "就把这条**留空字符串**,别硬凑。\n"
    "4. policy_intent:这个术语 / 简称背后绑的**政策方向或信号**(比如「放管服」=简政放权的改革"
    "方向、「包容审慎」=对新业态先放松再监管的姿态、「负面清单」=清单外都放开的市场化方向)。"
    "**这是你的研判推断、不是文件白纸黑字写的事实**,所以:(a) 只在你**确有把握**这个术语承载着"
    "公认的政策方向时才写,一句话点出方向 / 姿态即可;(b) 拿不准、或这词就是个中性名词没什么政策"
    "指向的,**一律留空字符串**——宁缺毋滥,绝不为了凑而编一个方向。\n"
    "5. evidence:这个词**在上面原文里出现的那一整句**,逐字抄下来(连标点),别改写、别截半句。\n"
    "只挑外行真看不懂的:常见词(「通知」「会议」「单位」)、谁都懂的词,别挑。挑不出就返空数组。\n"
    '只输出 JSON,形如 {"terms":[{"term":"","explanation":"","context_meaning":"",'
    '"policy_intent":"","evidence":""}]},别加任何解释、别加 markdown 围栏。'
)

_USER_MSG = "请按上面的要求,从这段公文里挑出难词并逐个释义。"


def _coerce_term(item: Any) -> dict[str, Any] | None:
    """把一条术语 dict 归一成该有的字段;term 为空 → 丢(没词面没法当词条)。

    term / explanation / context_meaning / policy_intent / evidence 都 coerce 成字符串、strip;
    term 空就丢——一条名词解释至少得有「哪个词」。其余字段缺退空串、抽不到不编:

    - ``context_meaning``(本文件语境特指义)、``policy_intent``(政策意图研判)是 v2 新增的
      **可选**字段,模型读不出 / 没把握时会按 prompt 留空——这里照单收空串,**不替它编**。
    """
    if not isinstance(item, dict):
        return None
    term = str(item.get("term", "")).strip()
    if not term:
        return None
    return {
        "term": term,
        "explanation": str(item.get("explanation", "")).strip(),
        "context_meaning": str(item.get("context_meaning", "")).strip(),
        "policy_intent": str(item.get("policy_intent", "")).strip(),
        "evidence": str(item.get("evidence", "")).strip(),
    }


def _make_glossary_parser():  # noqa: ANN202 — 返回闭包 parse_fn 喂 run_segments
    """造难词识别的 parse_fn:strip 围栏 → json.loads → 抠首个 obj → 截断抢救 → 归一段内去重。

    结构同 ``doc_spine._make_clause_parser``,只把数组键换成 ``"terms"``、归一走 ``_coerce_term``,
    段内按归一化词面去重(同段重复词只留一条;跨段去重在 reduce 阶段做)。
    """

    def _coerce_list(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for it in raw:
            t = _coerce_term(it)
            if t is None:
                continue
            key = normalize_text(t["term"])
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(t)
        return out

    def _parse(text: str) -> list[dict[str, Any]] | None:
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
            terms = _coerce_list(obj.get("terms"))
            if terms:
                return terms
        salvaged = _coerce_list(salvage_closed_objects(candidate, '"terms"') or [])
        if salvaged:
            logger.warning("redhead_glossary: 主解析失败,从截断抢救到 %d 个术语", len(salvaged))
            return salvaged
        return None

    return _parse


def _merge_terms(seg_outs: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """跨段把术语拍平 + 按归一化词面去重,保「先出现」顺序(段按章序排,先出现 = 靠前的段)。

    同一个词在全文出现多次(跨段),只留**第一次**出现的那条(它的 evidence = 最早那句)。
    词面归一后相同算同词(全角半角 / 空白差异不算两个词);不同词面全保留。
    """
    flat: list[dict[str, Any]] = []
    seen: set[str] = set()
    for seg in seg_outs:
        for t in seg:
            key = normalize_text(t.get("term", ""))
            if not key or key in seen:
                continue
            seen.add(key)
            flat.append(t)
    return flat


def glossary_from_spine(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    max_tokens: int = DEFAULT_GLOSSARY_MAX_TOKENS,
    max_workers: int | None = None,
    cache_enabled: bool = True,
    **spine_kwargs: Any,
) -> dict[str, Any]:
    """一份公文挑出难词逐个释义——拿文脉 → 分段并发识别难词 → 释义锚回原句过核验。

    复用现成的机器,一行不改 ``doc_spine`` / ``cross_doc``:

    - **文脉**走 ``get_or_build_doc_spine``(同份公文命中缓存秒出,跟公文结构解读 / 大白话翻译
      共用一份文脉)。文脉在这里当「这份公文读得通」的闸 + 共用缓存——文脉读不出东西(头要素
      全空 且 没条款)就当这份没正文可挑词,直接返空。
    - **识别**对全文按字数分段(``run_segments``,同穷尽化 / 文脉条款维),每段让 LLM 挑难词 +
      给人话释义 + 抠原句。段内 / 段间都按归一化词面去重(``_merge_terms``)。识别失败的段返
      空、不拖垮整体(``run_segments`` 自带截断拆小重抽兜底)。
    - **核验**每个词的 **原句 evidence**(不是释义)过 ``verify_citations``——核的是「这词真在
      原文出现、那句找得到」。核得到 ``verified=True`` 盖「鉴」印;核不过(含 evidence 为空)
      ``verified=False`` 标待核,evidence 退空(不留一句核不到的假原句撑场)。

    Args:
        chunks: 这份公文的 chunk 列表(每条含 ``chunk_id`` / ``chapter`` / ``text``)。
        llm_client: duck-typed LLM client(同 AgentLoop / 文脉)。
        model: 模型名。
        full_text: 这份公文的完整原文(含公布头)。透传给文脉构建当头要素抽取 + 兜底锚定;
            传了核验时也拿它当兜底登记(公布头在「第一章」前会被分块层当章前噪声丢,难词若
            出在公布头里,只拿 chunks 拼接核不到、靠它兜底)。
        max_tokens: 难词识别单段输出的 max_tokens。
        max_workers: 分段并发数(透传 ``run_segments`` → ``resolve_workers``)。
        cache_enabled: 是否走 L2 缓存(默认开;识别层 + 文脉层都吃)。
        **spine_kwargs: 透传给 ``get_or_build_doc_spine`` 的其余参数(char_budget 等);
            ``char_budget`` 同时用于难词识别分段(取 spine_kwargs 里的值,没传退默认)。

    Returns:
        ``{
            "schema_version": "v2",
            "terms": [{term(术语本身), explanation(词典义),
                       context_meaning(本文件语境特指义,证据层、可选、可空),
                       policy_intent(政策意图研判,评估层、可选、可空),
                       chapter(这词所在条款 / 章节序号), evidence(这词出现的原句),
                       verified, match_score}],
        }``。
        没挑出难词(或这份没正文)→ ``terms: []``。``terms`` 按全文先出现顺序排。

        两层深度字段的证据契约:``context_meaning`` 是从原文用法读出的语境特指义,跟着术语那句
        原文走——核不过(``verified=False``)时它跟着失去原文撑,由前端按未核验呈现(不盖鉴印);
        ``policy_intent`` 是**研判**(评估层),不进核验、不盖鉴印,前端单独标研判。两者模型读不出
        时都退空串(前端据此不渲染),绝不编。
    """
    spine = get_or_build_doc_spine(
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        full_text=full_text,
        cache_enabled=cache_enabled,
        **spine_kwargs,
    )
    # 文脉读不出东西(头要素全空 且 没条款)→ 这份没正文可挑词,直接返空,不白跑识别。
    head = spine.get("head") if isinstance(spine, dict) else None
    clauses = spine.get("clauses") if isinstance(spine, dict) else None
    head_has_value = isinstance(head, list) and any(
        isinstance(el, dict) and str(el.get("value", "")).strip() for el in head
    )
    if not (head_has_value or (isinstance(clauses, list) and clauses)):
        return {"schema_version": GLOSSARY_SCHEMA_VERSION, "terms": []}

    char_budget = int(spine_kwargs.get("char_budget", DEFAULT_CHAR_BUDGET))

    seg_outs = run_segments(
        chunks=chunks,
        instruction=_INSTR_GLOSSARY,
        user_msg=_USER_MSG,
        parse_fn=_make_glossary_parser(),
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_chapters=_GLOSSARY_MAX_CHAPTERS,
        max_workers=max_workers,
        cache_enabled=cache_enabled,
    )
    terms = _merge_terms(seg_outs)
    if not terms:
        return {"schema_version": GLOSSARY_SCHEMA_VERSION, "terms": []}

    # 核验:每个词的**原句 evidence**(不是释义)过 verify_citations。核的是「这词真在原文
    # 出现、那句找得到」——释义是讲解、不该也核不到原文,所以锚的是原句。同时拿命中 chunk 的
    # 真章节号当这词的 chapter(verify 附 chunk_id → 查回章号),供前端按章归拢。
    evidence_map = build_evidence_map(chunks)
    if full_text and full_text.strip():
        # 同文脉头要素维:公布头在「第一章」之前会被分块层当章前噪声丢掉,整份原文兜底锚定。
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": full_text}
    citations = [{"snippet": t["evidence"]} for t in terms]
    verify_citations(citations, evidence_map)

    out_terms: list[dict[str, Any]] = []
    for t, vc in zip(terms, citations, strict=True):
        verified = bool(vc.get("verified", False))
        # 命中的拿命中 chunk 的真章节号当 chapter;没命中退 None(前端按「无章归属」放)。
        chunk_id = vc.get("chunk_id")
        chapter = None
        if chunk_id is not None:
            entry = evidence_map.get(str(chunk_id))
            if entry is not None:
                chapter = entry.get("chapter")
        out_terms.append({
            "term": t["term"],
            "explanation": t["explanation"],
            # 语境特指义(证据层):跟术语那句原文同源,核不过时由 verified=False 标未核验,
            # 值仍带出(它是读出的所指、不是逐字引文,前端按未核验呈现、不盖鉴印)。
            "context_meaning": t["context_meaning"],
            # 政策意图(评估层·研判):不进核验、不盖鉴印,前端单独标研判;空就不渲染。
            "policy_intent": t["policy_intent"],
            "chapter": chapter,
            # 核不过(含 evidence 为空)就退空——不留一句核不到的假原句撑场。
            "evidence": t["evidence"] if verified else "",
            "verified": verified,
            "match_score": vc.get("match_score", 0.0),
        })

    return {"schema_version": GLOSSARY_SCHEMA_VERSION, "terms": out_terms}


__all__ = [
    "DEFAULT_GLOSSARY_MAX_TOKENS",
    "GLOSSARY_SCHEMA_VERSION",
    "glossary_from_spine",
]
