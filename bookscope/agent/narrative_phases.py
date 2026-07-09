"""情节脉络·阶段抽取(章脉派生)。WP-narrative-phases,probe exp027 GO。

从章脉逐章 events 派生一份**阶段划分**:先判书型(叙事型 / 论述型),叙事型才把全书切成
3-6 个大阶段(名 + 起止章 + 一句概括 + 代表事件原文),论述型返空阶段(它没时间阶段,别硬切)。
给"情节脉络"这个镜头一条脉:史书 / 叙事看阶段推进,论述书就老实不显阶段。

probe(exp027):三国判叙事型 + 5 个合理阶段全锚原文;条例判论述型不硬切(判别过);裸调偶发
解析失败 → 这里补上整本书结构化功能三守卫(够 max_tokens / 关缓存防 poison / 重试 + 截断抢救)。

契约:成功返 ``{"book_type": "叙事型"|"论述型", "phases": [...]}``;任意失败返 ``None``。
每个 phase 的 evidence 过 ``verify_citations`` 挂 verified(核不过标灰、不当确定结论画)。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_PHASES_MAX_TOKENS = 3000
"""判书型 + 3-6 阶段(每阶段一句概括 + 一条原文)不长;3000 给 reasoning 头够用。"""

_MAX_ATTEMPTS = 2
_MAX_PHASES = 8  # 防切太碎;正常 3-6

_SYSTEM_INSTRUCTION = (
    "下面是一本书的逐章梗概(每章的关键事件)。先判这本书属哪种:\n"
    "- **叙事型**:有时间线 / 事件推进 / 情节(小说、历史叙事、传记)。\n"
    "- **论述型**:讲道理 / 摆论点、没有时间推进(理论、论文、政策条款、工具书)。\n"
    "只有**叙事型**才把全书分成大阶段——分 3-6 个,每阶段:\n"
    "  {name:阶段名(如\"群雄割据\"), start_ch:起始章整数, end_ch:结束章整数, "
    "gist:这阶段一句话概括, evidence:这阶段代表性事件的原文逐字片段(从梗概里摘,原样不改写)}。\n"
    "**论述型直接让 phases 为空数组 []、别硬切阶段**(它没有时间阶段)。只依据梗概,不臆测、不编造。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"book_type":"叙事型|论述型","phases":[{"name":"","start_ch":章号整数,"end_ch":章号整数,'
    '"gist":"","evidence":"原文逐字片段"}]}'
)


def _clamp_int(value: Any, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def _build_digest(spine: list[dict[str, Any]], max_events_per_ch: int = 4) -> str:
    """把章脉逐章 events 摊成一份紧凑梗概喂给模型:``第N章: 事件1;事件2…``。

    只发梗概(不发全文)——阶段划分看的是事件流,不需要原文全量;便宜、稳。
    """
    lines: list[str] = []
    for rec in sorted(spine, key=lambda r: r.get("chapter", 0)):
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        evs = []
        for ev in (rec.get("events") or [])[:max_events_per_ch]:
            t = str(ev.get("event", ev) if isinstance(ev, dict) else ev).strip()
            if t:
                evs.append(t)
        if evs:
            lines.append(f"第{ch}章: " + "；".join(evs))
    return "\n".join(lines)


def _coerce(obj: Any) -> dict[str, Any] | None:
    """归一成 ``{book_type, phases}``;论述型 phases 强制空(它没时间阶段)。"""
    if not isinstance(obj, dict):
        return None
    bt = str(obj.get("book_type", "")).strip()
    if bt not in ("叙事型", "论述型"):
        # 判不出书型不硬猜:有 phases 当叙事型、没有当论述型(保守)
        bt = "叙事型" if obj.get("phases") else "论述型"
    if bt == "论述型":
        return {"book_type": "论述型", "phases": []}
    phases: list[dict[str, Any]] = []
    for p in obj.get("phases") or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name", "")).strip()
        if not name:
            continue
        phases.append({
            "name": name,
            "start_ch": _clamp_int(p.get("start_ch")),
            "end_ch": _clamp_int(p.get("end_ch")),
            "gist": str(p.get("gist", "")).strip(),
            "evidence": str(p.get("evidence", "")).strip(),
        })
        if len(phases) >= _MAX_PHASES:
            break
    phases.sort(key=lambda x: x["start_ch"])
    return {"book_type": "叙事型", "phases": phases}


def _parse(text: str) -> dict[str, Any] | None:
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
    if isinstance(obj, dict) and ("book_type" in obj or "phases" in obj):
        return _coerce(obj)
    logger.warning("narrative_phases parse failed; head=%r", candidate[:200])
    return None


def _verify_phases(phases: list[dict[str, Any]], chunks: list[dict[str, Any]]) -> None:
    """每阶段代表事件 evidence 过 verify_citations 挂 verified + 命中章号纠偏(同 character_arc)。"""
    evidence = build_evidence_map(chunks)
    citations = [{"snippet": p["evidence"], "chapter": p.get("start_ch")} for p in phases]
    verify_citations(citations, evidence)
    for p, vc in zip(phases, citations, strict=True):
        p["verified"] = bool(vc.get("verified", False))
        p["match_score"] = vc.get("match_score", 0.0)


def generate_narrative_phases(
    *,
    spine: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_PHASES_MAX_TOKENS,
) -> dict[str, Any] | None:
    """章脉派生阶段划分:判书型 + 叙事型切 3-6 阶段 + 每阶段锚原文核验;任意失败返 ``None``。

    Returns:
        ``{"book_type": "叙事型"|"论述型", "phases": [{name, start_ch, end_ch, gist,
        evidence, verified, match_score}]}``;论述型 phases 为空。失败 ``None``。
    """
    digest = _build_digest(spine)
    if not digest.strip():
        return None  # 章脉没 events(概念书 / 抽空)→ 没梗概可切,交端点返空态
    messages = [{"role": "user", "content": digest + "\n\n请按上面要求判书型、必要时分阶段。"}]
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = _invoke_client(
                llm_client,
                model=model,
                system=_SYSTEM_INSTRUCTION,
                tools=[],
                messages=messages,
                max_tokens=max_tokens,
                cache_enabled=False,  # 结构化 JSON,坏响应不进缓存 poison
            )
        except Exception as exc:  # noqa: BLE001 — 包死,重试 / 返 None
            logger.warning(
                "narrative_phases LLM raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        parsed = _parse(llm_client.extract_final_text(resp))
        if parsed is not None:
            if parsed["phases"]:
                _verify_phases(parsed["phases"], chunks)
            return parsed
        logger.warning("narrative_phases parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS)
    return None


__all__ = ["DEFAULT_PHASES_MAX_TOKENS", "generate_narrative_phases"]
