"""公文逐条精读(1.6 公文整合·centerpiece)——一份公文一次精读出「每条:大白话 + 结构标签 +
内联术语 + 对原文」的富视图,一个视图替原来的大白话 / 名词解释 / 公文结构条款三趟。

**它整合了什么**(设计稿 `WP-redhead-consolidation.md` 整合 1 + 整合 2):
原先用户读懂一条公文得在三个 tab 来回拼——结构 tab 看「这条是硬要求、谁负责、什么期限」、
大白话 tab 看「这条人话什么意思」、名词 tab 查「这条里那个术语啥意思」。三个 tab 啃的是同一批
原文条款,只是切面不同(典型的视图撞脸)。逐条精读把这三个切面合到一条卡上:

1. **大白话**(plain,墨色主体)——这条官话翻人话 + 命中措辞刻度时点弦外之音(nuance)。
   复用 ``redhead_plain._rewrite_one`` 的逐条改写 + ``detect_nuances``,口径不漂。
2. **结构标签**(朱砂小签)——硬/软 + 责任主体 + 时限 + 依据上位文件。**直接取 doc_spine 条款
   骨架,绝不重抽**(整合 1 收紧后的条款标签就是这条的骨架)。叙述体公文每要点也是一条(#34
   让公报/意见把每个原则/部署各抽一条),标签退成要点级。
3. **内联术语**(点开出释义)——这条命中的术语 + 释义。复用 ``glossary_from_spine`` 全文挑词,
   再按术语出现的原句**归属到对应的条款**——名词解释从「单独一张全文术语表」改成「锚在出现它
   的那条上」。术语本就该在它出现的地方解释,不该让用户拿着术语表跟原文两头对。
4. **对原文**(evidence,折叠)——doc_spine 条款已有的逐字原文。

**后端合成(作者拍板,不走前端三端点对齐)**:三者都从**同一份 doc_spine** 派生——大白话改写
吃条款的事项+原文、结构标签直接是条款骨架、术语挑出后按原句归条款。一次精读出齐,省一次跨端点
对齐的脏活,契合「证据脊一次建、多视图派生」的脊架构(``project_chapter_spine_turn``)。

**evidence-first 死守**(全站一个规矩):
- 每条大白话背后的**原文**(条款 evidence)过 ``verify_citations``,核得过盖鉴印、核不过老实标
  待核(白话退回原事项,不假装翻好了)。白话是改写不核白话本身,锚的是原 evidence。
- 内联术语的**原句**核不过 → 这术语不挂到任何条款(不留一条核不到的假术语)。
- nuance 只在条款原文里**确有** marker 时才出(``detect_nuances`` deterministic 串匹配,不靠
  LLM 脑补隐含义)。

**复用现成的机器,一行不改 ``doc_spine`` / ``redhead_plain`` / ``redhead_glossary``**:
只 import 它们的公共入口 + helper。``glossary_from_spine`` 内部会复用同一份文脉缓存
(``get_or_build_doc_spine`` 同份秒出),所以逐条精读 = 一次文脉精读 + 一遍逐条改写 + 一遍全文
挑词,文脉本身只精读一次。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from bookscope.agent._internal.doc_spine_cache import get_or_build_doc_spine
from bookscope.agent._internal.exhaustive import resolve_workers
from bookscope.agent.citation_check import (
    build_evidence_map,
    normalize_text,
    verify_citations,
)
from bookscope.agent.redhead_codebook import clause_is_pure_statement, detect_nuances
from bookscope.agent.redhead_glossary import (
    DEFAULT_GLOSSARY_MAX_TOKENS,
    glossary_from_spine,
)
from bookscope.agent.redhead_plain import DEFAULT_PLAIN_MAX_TOKENS, _rewrite_one

logger = logging.getLogger(__name__)

CLOSE_READING_SCHEMA_VERSION = "v1"
"""逐条精读记录结构版本——这是 1.6 整合首版,合成层从文脉派生。升级让这层重算(文脉缓存不受
影响,只是合成层重跑)。它本身不带 LLM 调用之外的缓存键,缓存吃在文脉 / 改写 / 挑词三层各自的
L2 上(同份公文重看命中)。"""


def _structure_label(clause: dict[str, Any]) -> dict[str, Any]:
    """从一条 doc_spine 条款骨架抠出结构标签(硬/软 + 责任主体 + 时限 + 依据)。

    **直接取 doc_spine 已抽的字段,绝不重抽**——这是整合 1 收紧后条款标签的复用点。叙述体公文
    每要点也是一条(``instruction_type`` 多为「方针部署」),actor/deadline 常空,留空照带。
    """
    return {
        "instruction_type": str(clause.get("instruction_type", "")).strip(),
        "actor": str(clause.get("actor", "")).strip(),
        "deadline": str(clause.get("deadline", "")).strip(),
        "basis_ref": str(clause.get("basis_ref", "")).strip(),
    }


def _attach_glossary_to_clauses(
    items: list[dict[str, Any]], terms: list[dict[str, Any]]
) -> None:
    """把已核的术语按「术语出现的原句」归属到对应条款的内联术语角标(原地改 items)。

    名词解释从「单独一张全文术语表」改成「锚在出现它的那条上」(整合 2)。归属规则,优先级:

    1. 术语的**原句 evidence** 是这条条款 evidence 的子串(归一化后比对)→ 归到这条。这是最准的:
       术语就出现在这条原文里。
    2. 退一步:术语核到的 ``chapter`` == 条款序号(``glossary_from_spine`` 已把命中 chunk 的真
       章节号当 chapter)→ 归到这条。

    **evidence-first 死守**:只挂**核过的**术语(``verified=True`` 且原句非空);核不过的术语
    (原句已被 ``glossary_from_spine`` 退空)一条都不挂——不留核不到原文的假术语。一个术语可能
    归到多条(它在多条里都出现,各挂一份);归不到任何条款的术语(原句不在任何条款 evidence 里、
    chapter 也对不上)就丢——逐条精读只内联「锚得到某条」的术语,通览全文术语另说(设计稿待拍板
    点 2:若实测需要全文术语总览,在逐条精读加折叠区,本批不做)。
    """
    # 只考虑核过、原句非空的术语(核不过的不挂)。
    verified_terms = [
        t for t in terms
        if t.get("verified") and str(t.get("evidence", "")).strip()
    ]
    if not verified_terms:
        return

    # 预归一化每条条款的 evidence,供子串比对。
    norm_clause_ev = [
        normalize_text(str(it.get("evidence", "")).strip()) for it in items
    ]

    for term in verified_terms:
        term_sentence = normalize_text(str(term.get("evidence", "")).strip())
        term_chapter = term.get("chapter")
        # 这术语内联呈现要带的字段:词 + 释义 + 语境义 + 政策意图研判(都已是 glossary 产物形态)。
        inline = {
            "term": term["term"],
            "explanation": str(term.get("explanation", "")).strip(),
            "context_meaning": str(term.get("context_meaning", "")).strip(),
            "policy_intent": str(term.get("policy_intent", "")).strip(),
        }
        matched_any = False
        for it, ev_norm in zip(items, norm_clause_ev, strict=True):
            # 规则 1:术语原句是这条 evidence 的子串(术语就出现在这条原文里)。
            hit = bool(term_sentence) and bool(ev_norm) and term_sentence in ev_norm
            # 规则 2:退一步按 chapter == 条款序号归(同一序号体系:都是 doc_spine 的 chapter)。
            if not hit and term_chapter is not None:
                hit = it.get("chapter") == term_chapter
            if hit:
                it.setdefault("glossary", []).append(dict(inline))
                matched_any = True
        if not matched_any:
            logger.debug(
                "close_reading: 术语「%s」归不到任何条款(原句不在条款 evidence、chapter 对不上),丢",
                term["term"],
            )


def close_reading_from_spine(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    plain_max_tokens: int = DEFAULT_PLAIN_MAX_TOKENS,
    glossary_max_tokens: int = DEFAULT_GLOSSARY_MAX_TOKENS,
    max_workers: int | None = None,
    cache_enabled: bool = True,
    **spine_kwargs: Any,
) -> dict[str, Any]:
    """一份公文逐条精读——从同一份文脉派生「每条:大白话 + 结构标签 + 内联术语 + 对原文」。

    合成三件套,全从同一份 ``doc_spine`` 派生(不走前端三端点对齐):

    1. **拿文脉**:走 ``get_or_build_doc_spine`` 拿这份公文的文脉(头要素 + 条款,带证据)。同份
       公文命中缓存秒出。文脉读不出条款(``clauses`` 空)→ 这份没分条/逐要点的正文可精读,直接
       返空(优雅退场)。
    2. **逐条大白话**:对每条条款并发改写(``redhead_plain._rewrite_one``,只喂这一条的事项 +
       原文)→ 白话锚回**原条款逐字原文**过 ``verify_citations`` → 命中 marker 挂 nuance。改写
       失败退回原事项、标 ``verified=False``。
    3. **结构标签**:直接取条款骨架(硬/软 + 责任主体 + 时限 + 依据),**不重抽**。
    4. **内联术语**:走 ``glossary_from_spine`` 全文挑词(复用同一份文脉缓存)→ 已核的术语按
       原句归属到对应条款的内联角标(``_attach_glossary_to_clauses``)。核不过的术语不挂。

    Args:
        chunks: 这份公文的 chunk 列表(每条含 ``chunk_id`` / ``chapter`` / ``text``)。
        llm_client: duck-typed LLM client(同 AgentLoop / 文脉)。
        model: 模型名。
        full_text: 这份公文的完整原文(含公布头)。透传文脉构建当头要素抽取 + 兜底锚;也透传
            glossary(术语原句若在公布头里靠它兜底)。
        plain_max_tokens: 逐条改写单条 max_tokens(默认 ``DEFAULT_PLAIN_MAX_TOKENS=1200``,
            一句白话够;reasoning 头也留足,见 reference_reasoning_model_token_budget)。
        glossary_max_tokens: 难词识别单段 max_tokens(默认 ``DEFAULT_GLOSSARY_MAX_TOKENS=8000``——
            **绝不调小**:glossary 踩过 1800→0 词的坑,reasoning 把预算吃光、content 返空)。
        max_workers: 逐条改写的并发数(透传 ``resolve_workers``);glossary 内部自己并发分段。
        cache_enabled: 是否走 L2 缓存(默认开;文脉 / 改写 / 挑词三层都吃)。
        **spine_kwargs: 透传给 ``get_or_build_doc_spine`` / ``glossary_from_spine`` 的其余参数
            (char_budget 等)。

    Returns:
        ``{
            "schema_version": "v1",
            "items": [{
                chapter,                # 条款序号(1 起,doc_spine 全局顺排)
                matter,                 # 这条管的事(官话事项,做卡片旁注)
                plain,                  # 大白话(改写失败退回 matter)
                structure: {instruction_type, actor, deadline, basis_ref},  # 结构标签(直接取骨架)
                glossary: [{term, explanation, context_meaning, policy_intent}],  # 内联术语(可空)
                evidence,               # 这条逐字原文(核不过退原值、verified 标 false)
                verified, match_score,
                nuance?: [{marker, meaning}],  # 命中措辞刻度才有(弦外之音)
            }],
        }``。
        没条款(这份没分条/逐要点正文)→ ``items: []``,前端优雅退场。``items`` 按条款序号排。
        ``scanned`` / ``book_session_id`` / ``trace`` 由端点层加,本模块不管。
    """
    spine = get_or_build_doc_spine(
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        full_text=full_text,
        cache_enabled=cache_enabled,
        **spine_kwargs,
    )
    clauses: list[dict[str, Any]] = (
        spine.get("clauses") if isinstance(spine, dict) else None
    ) or []
    if not clauses:
        # 没条款 = 这份没分条/逐要点的正文可精读(头要素全空 或 只有头要素没正文)→ 优雅退场。
        return {"schema_version": CLOSE_READING_SCHEMA_VERSION, "items": []}

    # ── 逐条大白话(并发改写,复用 redhead_plain._rewrite_one) ──────────────────
    workers = resolve_workers(max_workers)

    def _do(clause: dict[str, Any]) -> str:
        return _rewrite_one(
            clause,
            llm_client=llm_client,
            model=model,
            max_tokens=plain_max_tokens,
            cache_enabled=cache_enabled,
        )

    if workers <= 1 or len(clauses) <= 1:
        plains = [_do(c) for c in clauses]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            plains = list(ex.map(_do, clauses))

    items: list[dict[str, Any]] = []
    for clause, plain in zip(clauses, plains, strict=True):
        matter = str(clause.get("matter", "")).strip()
        evidence = str(clause.get("evidence", "")).strip()
        items.append({
            "chapter": clause.get("chapter"),
            "matter": matter,
            # 改写失败(空)→ 退回原事项,老实把官话摆出来,不假装翻好了。
            # 纯表态条款 plain 已是 PURE_STATEMENT_PLAIN 说明句(_rewrite_one 直接给,没调 LLM)。
            "plain": plain or matter,
            # 纯表态 / 实质:前端据此把纯表态的「大白话」当诚实说明渲染、不当复读的翻译
            # (WP-redhead-substance-vs-slogan §3.4)。
            "clause_kind": (
                "pure_statement" if clause_is_pure_statement(clause) else "substantive"
            ),
            "structure": _structure_label(clause),
            "glossary": [],  # 内联术语下面挂;归不到的不挂
            "evidence": evidence,
            "verified": False,
            "match_score": 0.0,
        })

    # ── 核验:每条白话背后的原文 evidence 过 verify_citations(核原文不核白话) ──
    evidence_map = build_evidence_map(chunks)
    if full_text and full_text.strip():
        # 公布头(成文日期/发文字号常在公布头)在「第一章」前会被分块层当章前噪声丢,整份原文兜底。
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": full_text}
    citations = [{"snippet": it["evidence"]} for it in items]
    verify_citations(citations, evidence_map)
    for it, vc in zip(items, citations, strict=True):
        it["verified"] = bool(vc.get("verified", False))
        it["match_score"] = vc.get("match_score", 0.0)
        # 弦外之意:命中措辞刻度就挂 nuance(原文确有 marker 才有,不靠 LLM 脑补)。
        nuances = detect_nuances(it["evidence"])
        if nuances:
            it["nuance"] = nuances

    # ── 内联术语:全文挑词(复用同一份文脉缓存)→ 已核术语按原句归属到对应条款 ──
    glossary = glossary_from_spine(
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        full_text=full_text,
        max_tokens=glossary_max_tokens,
        max_workers=max_workers,
        cache_enabled=cache_enabled,
        **spine_kwargs,
    )
    terms = (glossary.get("terms") if isinstance(glossary, dict) else None) or []
    _attach_glossary_to_clauses(items, terms)

    return {"schema_version": CLOSE_READING_SCHEMA_VERSION, "items": items}


__all__ = [
    "CLOSE_READING_SCHEMA_VERSION",
    "close_reading_from_spine",
]
