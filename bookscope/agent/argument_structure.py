"""论点结构梳理：拆解一本书的论证骨架——主要主张 + 原文证据 + 所在章节。

学习者发明区——读理论书/论文，抓核心主张、看作者靠什么撑。长上下文整本进 context、
按论证推进列出主要论点，每条带一句原文逐字证据。

复用 [[project_wholebook_feature_pattern]]：长上下文 + 结构化 JSON + 三守卫（够 token /
关缓存 / 重试 + 截断抢救）。每条 evidence 过 verify_citations 标 verified + 真章号纠偏。
probe GO：zhinei 引用真实性 100%、命根子（支撑书反对的主张）假阳性 0%。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bookscope.agent._internal.exhaustive import merge_by_key, run_segments
from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent._internal.loop_shared import read_openai_finish_reason
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.scholar_stance import _norm as _sc_norm
from bookscope.agent.scholar_stance import _quote_grounded
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    salvage_closed_objects,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_ARGUMENT_MAX_TOKENS = 8000
_MAX_ATTEMPTS = 2
_MAX_CLAIMS = 30

# 论点结构是理论书/论说文功能（抓论证主张）。叙事书（小说）没有"论证骨架"可梳理，
# 在上面硬抽会编出怪东西，所以非论说类题材直接优雅退场、不跑 LLM。
# genre 取值沿用 chapter_spine 的约定："theory" = 论说/理论，"fiction" = 叙事/小说。
_ARGUMENT_GENRES = frozenset({"theory"})
GENRE_SKIP_REASON = "这本是叙事/小说，没有论点结构可梳理。"


def is_argument_genre(genre: str | None) -> bool:
    """这个题材有没有"论点结构"可梳理。``None`` 视作论说类（向后兼容旧调用）。"""
    if genre is None:
        return True
    return genre in _ARGUMENT_GENRES

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的论点梳理助手。请梳理这段原文里作者的**主干论点**——他主张什么、靠什么撑。"
    "死守两条(#47):\n"
    "1. **claim 用你自己的话把这条论点综括出来**(一句、点明主张),别照抄或原样复述原文那句"
    "——照抄不是梳理、是复读。综括**不等于编造**:只能说这段原文**确实在主张**的意思,信息量不超过"
    "原文,绝不添原文没有的论点/结论。\n"
    "2. **evidence 是原文里逐字出现的句子**(要拿去跟原文比对核验,改一个字都核不上),跟 claim 分开:"
    "claim 是你综括的话、evidence 是原文原话,两者不该一模一样。\n"
    "只抽**本段的主干论点**,通常就几条(约 3-6 条),别把每一句都拎出来当论点;这段若只是叙事 / "
    "铺陈 / 过渡、没有论证主张,就返空 claims(宁缺毋滥,别硬凑)。\n"
    "严格输出 JSON(不要别的话、不要 markdown 代码围栏):\n"
    '{"claims": [{"order": 序号整数, "claim": "你综括的主张一句", '
    '"chapter": 章号整数, "evidence": "原文逐字片段"}]}\n'
    "order 从 1 起递增。"
)


def _resp_field(resp: Any, field: str) -> Any:
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def _coerce(raw: Any) -> list[dict[str, Any]] | None:
    if not isinstance(raw, dict):
        return None
    items = raw.get("claims")
    if not isinstance(items, list):
        return None
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim", "")).strip()
        if not claim:
            continue
        order = item.get("order")
        chapter = item.get("chapter")
        out.append({
            "order": order if isinstance(order, int) else len(out) + 1,
            "claim": claim,
            "chapter": chapter if isinstance(chapter, int) else 0,
            "evidence": str(item.get("evidence", "")).strip(),
        })
        if len(out) >= _MAX_CLAIMS:
            break
    out.sort(key=lambda c: c["order"])
    return out or None


def _salvage_truncated(text: str) -> list[dict[str, Any]] | None:
    """从截断 JSON 抠出 ``claims`` 数组里已闭合的完整对象（同 timeline 抢救）。"""
    raw_items = salvage_closed_objects(text, '"claims"') or []
    return _coerce({"claims": raw_items}) if raw_items else None


def _parse_claims(text: str) -> list[dict[str, Any]] | None:
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
    result = _coerce(obj)
    if result is not None:
        return result
    salvaged = _salvage_truncated(candidate)
    if salvaged:
        logger.warning(
            "argument_structure: 主解析失败，从截断输出抢救到 %d 条", len(salvaged)
        )
    return salvaged


def _verify_claims(claims: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
    """每条 claim 的 evidence 当一条 citation 过 verify_citations（原地附加）。

    命中 → ``verified=True`` + 用命中 chunk 的真章号纠偏（不信模型自报章号）；没命中 →
    ``verified=False``，章号留模型自报的（FE 只在 verified 上盖钤印）。
    """
    evidence_map = build_evidence_map(chunks)
    for cl in claims:
        # 带上 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
        # chapter 为 0 = 模型没报，不传，退回确定性首个。
        self_ch = cl.get("chapter")
        cit: dict[str, Any] = {"snippet": cl["evidence"]}
        if isinstance(self_ch, int) and self_ch > 0:
            cit["chapter"] = self_ch
        cits = [cit]
        verify_citations(cits, evidence_map)
        vc = cits[0]
        cl["verified"] = bool(vc.get("verified", False))
        cid = vc.get("chunk_id")
        true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
        if isinstance(true_ch, int) and true_ch > 0:
            cl["chapter"] = true_ch


def generate_argument_structure(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_ARGUMENT_MAX_TOKENS,
    session_id: str | None = None,
    genre: str | None = None,
) -> list[dict[str, Any]] | None:
    """梳理书的论点结构；失败返 ``None``。

    每条 evidence 过 verify_citations 标 verified + 真章号纠偏。保留全部论点（含 evidence
    未命中的，标 verified=False 供用户判断 + 前端只在 verified 上盖钤印）。

    题材门控：``genre`` 非论说类（小说/叙事）时直接返空列表 ``[]``（优雅退场，不跑 LLM）——
    叙事书没有论证骨架可梳理，硬抽只会编。``genre=None`` 视作论说类（向后兼容，端点没传时照旧跑）。

    Returns:
        ``[{order, claim, chapter, evidence, verified}, ...]`` 按 order 排；失败 ``None``；
        题材不对 → ``[]``（区别于失败的 ``None``）。
    """
    _ = session_id
    if not is_argument_genre(genre):
        return []
    system = build_longctx_system(full_text, _SYSTEM_INSTRUCTION)
    messages = [{"role": "user", "content": "请梳理这本书的主要论点结构。"}]
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=messages,
                max_tokens=max_tokens,
                cache_enabled=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "argument_structure LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        claims = _parse_claims(llm_client.extract_final_text(response))
        if claims is None:
            logger.warning(
                "argument_structure parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
            )
            continue
        _verify_claims(claims, chunks)
        return claims
    return None


_CLAIM_NORM_RE = re.compile(r"[。;；,，、\s\"「」“”'']+")


def _norm_claim(s: str) -> str:
    """归一 claim 文本(去标点/空白/引号)做近似比对。跟 FE claimEchoesEvidence 一套判据。"""
    return _CLAIM_NORM_RE.sub("", (s or "").strip())


def _dedup_near_claims(claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """去**近似**重复的 claim(#47 ②)——``merge_by_key`` 只去完全相同文本,跨段抽到的同一论点
    表述略异(标点差、一方是另一方截断)就漏网、堆成一大列。这里补一道纯字符近似:归一后相等,
    或都够长(≥8 字)且一方是另一方子串,就当同一条,留先出现的(段序靠前 = 文中靠前)。

    纯字符(不引 embedding,同 [[project_retrieval_direction]] 本地 embedding 已否决 + 延迟考量)。
    claim 综括后表述差异大时字面重叠低、近似重复可能漏网——这是字符近似的固有局限,靠 exp probe
    看漏网率、必要时再加弱判据(见 WP-argument-structure-refine 开放点 2)。
    """
    kept: list[dict[str, Any]] = []
    kept_norms: list[str] = []
    for c in claims:
        n = _norm_claim(str(c.get("claim", "")))
        if not n:
            continue
        if any(
            n == kn or (min(len(n), len(kn)) >= 8 and (n in kn or kn in n))
            for kn in kept_norms
        ):
            continue
        kept.append(c)
        kept_norms.append(n)
    return kept


def generate_argument_structure_exhaustive(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_ARGUMENT_MAX_TOKENS,
    char_budget: int = 40000,
    max_workers: int | None = None,
    genre: str | None = None,
) -> list[dict[str, Any]] | None:
    """穷尽化:分段→每段抽本段论点→按 claim 去重拼,覆盖全书(1.4)。

    单次调用带硬帽（prompt 写"最多约 20 条"），长书论点列不全。改 map-reduce:每段只抽本段
    论点，跨段按 claim 去重拼起来。论点不像章节那样 disjoint——同一论点可能在相邻段都被抽到，
    所以按 claim 文本去重。合并后按章号重排再重编 order，最后一次性 ``_verify_claims``。

    题材门控：``genre`` 非论说类（小说/叙事）时返空列表 ``[]``（优雅退场，不跑分段 LLM）。
    ``genre=None`` 视作论说类（向后兼容，端点没传时照旧跑）。

    Returns: 同 ``generate_argument_structure``,但覆盖全书；空 → ``None``；题材不对 → ``[]``。
    """
    if not is_argument_genre(genre):
        return []
    outs = run_segments(
        chunks=chunks,
        instruction=_SYSTEM_INSTRUCTION,
        user_msg="请梳理下面这段原文里出现的主要论点（只列本段的）。",
        parse_fn=_parse_claims,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_workers=max_workers,
    )
    merged = merge_by_key(outs, key_fn=lambda c: c.get("claim"))
    if not merged:
        return None
    # #47 ②:merge_by_key 只去完全相同文本;再去一道近似重复(跨段同一论点表述略异),
    # 收编碎论点。claim 综括后按主干合并 + 这道去重 = 论点自然精简(不砍死 top-N)。
    merged = _dedup_near_claims(merged)
    merged.sort(key=lambda c: c["chapter"])  # 段内 order 跨段会重复，按章号重排
    for i, c in enumerate(merged, 1):
        c["order"] = i  # 重排后重新编号 1..N
    _verify_claims(merged, chunks)
    return merged


# ─────────────────────────────────────────────────────────────────────────
# 论证骨架树:把平铺 claim 升成 中心论点(thesis) + 论点(逻辑角色 + supports 关系),锚原文。
# exp034 GO(制内市场真语料:骨架能锚原文、有真层级;角色分化弱,靠 prompt 铁律 5 逼分化)。
# ─────────────────────────────────────────────────────────────────────────

DEFAULT_ARGUMENT_TREE_MAX_TOKENS = 12000
"""树输出带每条论点的原文引文,比平铺 claim 长;flash 把 reasoning 算进 max_tokens,4000/8000
易撞 finish_reason=length 空返,给 12000 打底、length 再加倍重试(同 scholar_stance / exp034)。"""

_TREE_LENGTH_BUMP_CAP = 24000
_TREE_MAX_ATTEMPTS = 3
_TREE_MIN_CLAIMS = 2
_ARGUMENT_ROLES = frozenset({"中心", "前提", "支撑", "递进", "反驳", "论据", "结论"})

_TREE_INSTRUCTION = (
    "你是严谨的学术论证分析助手。\n"
    "任务:拆出这本书的**论证骨架**——中心论点 + 主要论点各自的逻辑角色和支撑关系。\n"
    "铁律(违反即失败):\n"
    "1. 只据本书原文判,不臆测、不用书外知识。每条论点必须能在原文找到刻画它的**原句**。\n"
    "2. 先定全书**中心论点**(thesis):作者最核心那句主张,用本书的话概括。\n"
    "3. 抽主要论点,每个给:role(逻辑角色,只从 中心 / 前提 / 支撑 / 递进 / 反驳 / 论据 / 结论 里选)、"
    'supports(它直接**撑**或**反**哪一个,填另一条论点的 id,或填 "thesis" 表示直接撑中心论点)、'
    "quote(本书原文里刻画它的原句,逐字照抄)、brief(一句)。\n"
    "4. 只连原文里**真有论证关系**的:别硬造层级,也别把所有论点一律挂到 thesis 凑平;"
    "论点之间有递进 / 支撑 / 反驳的,supports 指向那条论点的 id。\n"
    "5. 角色尽量分化:别所有论点都填「支撑」——是前提 / 递进 / 反驳 / 论据 / 结论 的就如实标。"
)
_TREE_USER = (
    "严格只输出 JSON(不要别的话、不要 markdown 围栏):\n"
    '{"thesis":{"claim":"中心论点,用本书话概括","quote":"原文原句","from_book":"依据"},'
    '"claims":[{"id":"c1","claim":"","role":"支撑","supports":"thesis",'
    '"quote":"本书原文原句","brief":"一句"}]}\n'
    "id 用 c1 / c2 / … 好让 supports 互相指。尽量抽全主要论点,理清谁撑谁、谁反谁。"
)


def _parse_tree(text: str) -> dict[str, Any] | None:
    """解析论证树 JSON:要有 thesis(对象)+ claims(数组),否则 None。"""
    candidate = _strip_code_fence((text or "").strip())
    if not candidate:
        return None
    sliced = _extract_first_json_object(candidate)
    if sliced is None:
        return None
    try:
        obj = json.loads(sliced)
    except json.JSONDecodeError:
        return None
    if (
        isinstance(obj, dict)
        and isinstance(obj.get("thesis"), dict)
        and isinstance(obj.get("claims"), list)
    ):
        return obj
    return None


def generate_argument_tree(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_ARGUMENT_TREE_MAX_TOKENS,
    session_id: str | None = None,
    genre: str | None = None,
) -> dict[str, Any]:
    """拆书的论证骨架树:中心论点 + 论点(逻辑角色 + supports 关系),每条锚原文。exp034 GO。

    一次长上下文(book-first、缓存开):模型据原文定 thesis + 抽论点、连 supports。引文先过
    ``verify_citations`` 拿 verified + 真章号,再用 ``_quote_grounded`` 片段兜底,捞回被整条 /
    chunk 比对漏报的"……"拼接引文(exp022 / 033 / 034 教训)。题材非论说 / 抽不出 thesis /
    有效论点 < 2 → graceful 空(判不出不硬造,同平铺版题材门控)。

    Returns:
        ``{"scanned": bool, "thesis": {claim, quote, quote_verified, chapter, from_book}|None,
        "claims": [{id, claim, role, supports, quote, quote_verified, chapter, brief}]}``。
    """
    _ = session_id
    graceful: dict[str, Any] = {"scanned": False, "thesis": None, "claims": []}
    if not is_argument_genre(genre):
        return graceful

    system = build_longctx_system(full_text, _TREE_INSTRUCTION)
    messages = [{"role": "user", "content": _TREE_USER}]
    eff_max_tokens = max_tokens
    length_bumped = False
    obj: dict[str, Any] | None = None
    for attempt in range(1, _TREE_MAX_ATTEMPTS + 1):
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=messages,
                max_tokens=eff_max_tokens,
                cache_enabled=True,
            )
        except Exception as exc:  # noqa: BLE001 — 包死,重试 / 返 graceful
            logger.warning(
                "argument_tree LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        parsed = _parse_tree(llm_client.extract_final_text(response))
        if parsed is not None:
            obj = parsed
            break
        fr = read_openai_finish_reason(response)
        if fr == "length" and not length_bumped:
            eff_max_tokens = min(eff_max_tokens * 2, _TREE_LENGTH_BUMP_CAP)
            length_bumped = True
            logger.info(
                "argument_tree 撞 finish_reason=length,max_tokens→%d 重试一次", eff_max_tokens
            )
            continue
        logger.warning(
            "argument_tree 解析不出 JSON(attempt %d/%d, finish_reason=%s)",
            attempt, _TREE_MAX_ATTEMPTS, fr,
        )
        break

    if obj is None:
        return graceful
    thesis_raw = obj.get("thesis")
    if not isinstance(thesis_raw, dict):
        return graceful
    thesis_claim = str(thesis_raw.get("claim", "")).strip()
    if not thesis_claim:
        return graceful

    raw_claims = obj.get("claims")
    if not isinstance(raw_claims, list):
        return graceful
    claims: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for i, c in enumerate(raw_claims, 1):
        if not isinstance(c, dict):
            continue
        claim = str(c.get("claim", "")).strip()
        if not claim:
            continue
        cid = str(c.get("id", "")).strip() or f"c{i}"
        if cid in seen_ids:
            continue
        seen_ids.add(cid)
        role = str(c.get("role", "")).strip()
        claims.append({
            "id": cid,
            "claim": claim,
            "role": role if role in _ARGUMENT_ROLES else "支撑",
            "supports": str(c.get("supports", "") or "").strip(),
            "quote": str(c.get("quote", "") or "").strip(),
            "brief": str(c.get("brief", "") or "").strip(),
        })
    if len(claims) < _TREE_MIN_CLAIMS:
        return graceful
    # supports 指向不存在的 id → 落 "thesis"(不悬空,同 exp034 尺子③关系不悬空)
    valid_targets = seen_ids | {"thesis"}
    for c in claims:
        if c["supports"] not in valid_targets:
            c["supports"] = "thesis"

    # 引文核验 + 章号:thesis + 各 claim 一批过 verify_citations(拿 verified + 真章号),
    # 再用 _quote_grounded 片段兜底捞回"……"拼接引文的漏报(exp022 / 033 / 034)。
    full_norm = _sc_norm(full_text)
    evidence_map = build_evidence_map(chunks)
    quotes = [str(thesis_raw.get("quote", "") or "").strip()] + [c["quote"] for c in claims]
    cits: list[dict[str, Any]] = [{"snippet": q} for q in quotes]
    verify_citations(cits, evidence_map)

    def _chapter_of(vc: dict[str, Any]) -> int:
        cid = vc.get("chunk_id")
        ch = evidence_map.get(cid, {}).get("chapter") if cid else None
        return ch if isinstance(ch, int) and ch > 0 else 0

    t_quote = quotes[0]
    thesis = {
        "claim": thesis_claim,
        "quote": t_quote,
        "quote_verified": bool(cits[0].get("verified"))
        or (bool(t_quote) and _quote_grounded(t_quote, full_norm)),
        "chapter": _chapter_of(cits[0]),
        "from_book": str(thesis_raw.get("from_book", "") or "").strip(),
    }
    for c, vc in zip(claims, cits[1:], strict=True):
        q = c["quote"]
        c["quote_verified"] = bool(vc.get("verified")) or (
            bool(q) and _quote_grounded(q, full_norm)
        )
        c["chapter"] = _chapter_of(vc)

    return {"scanned": True, "thesis": thesis, "claims": claims}


__all__ = [
    "DEFAULT_ARGUMENT_MAX_TOKENS",
    "DEFAULT_ARGUMENT_TREE_MAX_TOKENS",
    "GENRE_SKIP_REASON",
    "generate_argument_structure",
    "generate_argument_structure_exhaustive",
    "generate_argument_tree",
    "is_argument_genre",
]
