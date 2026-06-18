"""伏笔→回收弧线：整本进 context、抽"每条伏笔的埋点章 + 回收点章 + 描述"结构化 JSON。

设计：WP-foreshadow-payoff-arcs。

伏笔**能不能抽**已 GO（exp-008，找对 100% / 假阳性 0% / 引用 96% 真实）——这里**不重做
伏笔判定**，只把"第几章埋、第几章收"画成跨章弧线。本模块把它做成整本抽取的生产实现，
给前端画 arc diagram（横轴章节、每条伏笔从埋点拱到回收点）。

结构同 :func:`bookscope.agent.narrative_curve.generate_narrative_curve`，差别两处：

1. **出伏笔配对**——``{"arcs": [{"description": 一句话, "setup_chapter": M,
   "payoff_chapter": N 或 null, "setup_evidence": 埋点原文, "payoff_evidence":
   回收原文}]}``，而不是逐章曲线。
2. **两端各挂原文证据**——埋点 evidence + 回收点 evidence 各当一条 citation 过
   :func:`verify_citations`。埋点核不过 → 整条弧丢（连埋点都站不住，不算伏笔）；
   回收点核不过 / 模型给的 payoff_chapter 为 null → 这条是**断弧**（埋了没回收），
   ``status="dangling"`` 明确标出——这正是作家审稿最想抓的"挖的坑填了没"。

整本书结构化功能模式三可靠性守卫照搬：够 max_tokens 防 reasoning 吃 token 截断、
``cache_enabled=False`` 防坏响应被 poison、解析失败重试一次 + 截断抢救。契约同
``generate_narrative_curve``：成功返 list[弧 dict]，**任意环节失败返 None**。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent.citation_check import verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_ARCS_MAX_TOKENS = 8000
"""每条弧两端原文 + 描述比单点判断长——给 8000 留 reasoning 头，防截断/空（同节奏曲线/叙事流）。"""

_MAX_ATTEMPTS = 2

_SYSTEM_INSTRUCTION = (
    "你是严谨的长文本分析助手。下面 === 全书原文 === 之后是一整本书的完整原文。"
    "请梳理这本书里的**伏笔与回收**——前文埋下一个悬念/线索/承诺（埋点 setup），"
    "后文把它兑现/呼应/解开（回收点 payoff）。\n"
    "对每条伏笔判断：它在后文有没有被回收？\n"
    "- **有回收**：给出回收点在第几章 + 回收那段原文。\n"
    "- **埋了没回收**（坑没填）：payoff_chapter 填 null、payoff_evidence 留空字符串。"
    "宁可如实标「没回收」，也不要为了凑一个回收点而硬扯一段不相干的原文——"
    "错报一条回收比漏报一条断弧更糟。\n"
    "只依据原文，不臆测、不编造书里不存在的伏笔或回收。每条伏笔的埋点和回收点都要"
    "给一段原文逐字片段当证据（断弧只给埋点证据）。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"arcs": [{"description": "这条伏笔讲的是什么，一句话", '
    '"setup_chapter": 埋点章号整数, "payoff_chapter": 回收点章号整数或null, '
    '"setup_evidence": "埋设这处伏笔的原文逐字片段，原样摘录不改写", '
    '"payoff_evidence": "呼应回收的原文逐字片段（断弧留空字符串）"}]}\n'
    "setup_chapter 必须是整数；payoff_chapter 是整数（已回收）或 null（断弧）。"
    "按 setup_chapter 从小到大排列，覆盖主要伏笔（最多约 30 条）；"
    "宁可少而准，不必穷尽次要伏笔。"
)

_BOOK_DELIMITER = "\n\n=== 全书原文 ===\n"


def _coerce_arc(item: Any) -> dict[str, Any] | None:
    """把一条弧 dict 归一成统一形态。

    setup_chapter 缺/非整数 → 丢（埋点没章号没法摆横轴）；payoff_chapter 是整数则
    保留、否则一律归一成 None（断弧）；description / 两段 evidence 归一成字符串。
    """
    if not isinstance(item, dict):
        return None
    setup_ch = item.get("setup_chapter")
    if not isinstance(setup_ch, int):
        return None

    raw_payoff = item.get("payoff_chapter")
    payoff_ch = raw_payoff if isinstance(raw_payoff, int) else None

    return {
        "description": str(item.get("description", "")).strip(),
        "setup_chapter": setup_ch,
        "payoff_chapter": payoff_ch,
        "setup_evidence": str(item.get("setup_evidence", "")).strip(),
        "payoff_evidence": str(item.get("payoff_evidence", "")).strip(),
    }


def _coerce_arcs(raw: Any) -> list[dict[str, Any]]:
    """保留 setup_chapter 齐全的弧；按 setup_chapter 升序（同章号不去重——一章可埋多条伏笔）。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        arc = _coerce_arc(item)
        if arc is None:
            continue
        out.append(arc)
    out.sort(key=lambda a: a["setup_chapter"])
    return out


def _salvage_truncated_arcs(text: str) -> list[dict[str, Any]] | None:
    """从截断的 JSON 里抢救已吐完的完整弧对象。

    flash 把 reasoning_content 算进 max_tokens，弧列表一大就可能被截断成半截 JSON，
    整段 ``json.loads`` 必败。与其整张图丢掉返 None，不如把 ``"arcs"`` 数组里已经
    闭合的 ``{...}`` 逐个抠出来——用户至少看到大部分弧（同节奏曲线/叙事流截断抢救思路）。
    """
    idx = text.find('"arcs"')
    if idx == -1:
        return None
    start = text.find("[", idx)
    if start == -1:
        return None
    raw_arcs: list[Any] = []
    i = start + 1
    n = len(text)
    while i < n:
        while i < n and text[i] not in "{]":  # 跳到下一个对象起点；遇 ] 收工
            i += 1
        if i >= n or text[i] == "]":
            break
        depth = 0
        in_str = False
        esc = False
        closed = False
        j = i
        while j < n:  # 括号匹配抠一个完整 {...}，跳过字符串内的括号
            ch = text[j]
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        closed = True
                        break
            j += 1
        if not closed:
            break  # 最后一个对象被截断 → 停
        try:
            raw_arcs.append(json.loads(text[i:j]))
        except json.JSONDecodeError:
            pass
        i = j
    arcs = _coerce_arcs(raw_arcs)
    return arcs or None


def _parse_arcs(text: str) -> list[dict[str, Any]] | None:
    """解析模型输出的伏笔弧 JSON。正常失败 → 抢救截断的弧 → 仍不行返 None。"""
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
        arcs = _coerce_arcs(obj.get("arcs"))
        if arcs:
            return arcs
    salvaged = _salvage_truncated_arcs(candidate)
    if salvaged is not None:
        logger.warning(
            "foreshadow_arcs: 主解析失败，从截断输出抢救到 %d 条弧", len(salvaged)
        )
        return salvaged
    logger.warning("foreshadow_arcs parse failed; raw head=%r", candidate[:200])
    return None


def _verify_endpoints(
    arcs: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """两端原文核验 + 定 status；返回保留下来的弧（埋点核不过的整条丢）。

    每条弧的 setup_evidence / payoff_evidence 各当一条 citation 过 verify_citations。

    - 埋点核不过（verified=False）→ 整条弧丢（连埋点都站不住，不算伏笔，
      evidence-first：挂不上原文的伏笔不画）。
    - 命中某 chunk → 用命中 chunk 的真章号纠偏埋点/回收点章号（不信模型自报，同
      character_flow / narrative_curve）。
    - 回收点：模型给了 payoff_chapter 且 payoff_evidence 核验过 → ``status="resolved"``
      （已回收实弧）；payoff_chapter 为 null 或回收 evidence 核不过 → ``status="dangling"``
      （断弧，埋了没回收），回收端字段清空——绝不强行画一条挂不上原文的实弧。
    """
    evidence = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }

    def _verify_one(snippet: str, self_chapter: object = None) -> dict[str, Any]:
        # 带上 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
        # 自报章号缺/非正整数时不传，退回确定性首个。
        cit: dict[str, Any] = {"snippet": snippet}
        if isinstance(self_chapter, int) and self_chapter > 0:
            cit["chapter"] = self_chapter
        cite = [cit]
        verify_citations(cite, evidence)
        vc = cite[0]
        verified = bool(vc.get("verified", False))
        cid = vc.get("chunk_id")
        true_ch = evidence.get(cid, {}).get("chapter") if cid else None
        return {
            "verified": verified,
            "match_score": vc.get("match_score", 0.0),
            "true_chapter": true_ch if isinstance(true_ch, int) and true_ch > 0 else None,
        }

    kept: list[dict[str, Any]] = []
    for arc in arcs:
        setup_vc = _verify_one(arc["setup_evidence"], arc.get("setup_chapter"))
        if not setup_vc["verified"]:
            continue  # 埋点都核不过 → 整条丢

        arc["setup_verified"] = True
        arc["setup_match_score"] = setup_vc["match_score"]
        if setup_vc["true_chapter"] is not None:
            arc["setup_chapter"] = setup_vc["true_chapter"]  # 命中 chunk 真章号纠偏

        payoff_ch = arc.get("payoff_chapter")
        payoff_text = arc["payoff_evidence"]
        if payoff_ch is not None and payoff_text:
            payoff_vc = _verify_one(payoff_text, payoff_ch)
            if payoff_vc["verified"]:
                # 已回收实弧
                arc["status"] = "resolved"
                arc["payoff_verified"] = True
                arc["payoff_match_score"] = payoff_vc["match_score"]
                if payoff_vc["true_chapter"] is not None:
                    arc["payoff_chapter"] = payoff_vc["true_chapter"]
                kept.append(arc)
                continue

        # 断弧：要么模型自己说没回收（payoff null），要么回收 evidence 核不过——
        # 都按"埋了没回收"处理，绝不强行画实弧（evidence-first 的纯净产物）
        arc["status"] = "dangling"
        arc["payoff_chapter"] = None
        arc["payoff_evidence"] = ""
        arc["payoff_verified"] = False
        arc["payoff_match_score"] = 0.0
        kept.append(arc)

    return kept


def generate_foreshadow_arcs(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_ARCS_MAX_TOKENS,
    session_id: str | None = None,
) -> list[dict[str, Any]] | None:
    """整本进 context 抽伏笔弧 + 两端原文核验；失败返 ``None``。

    Args:
        full_text: 整本书 cleaned 原文。
        chunks: 全书 chunk dict（含 ``chunk_id`` / ``chapter`` / ``text``），给两端
            evidence 做证据登记表 + 提供章号 ground truth。
        llm_client: duck-typed LLM client（同 AgentLoop / narrative_curve）。
        model: 模型名。
        max_tokens: 单次 LLM 调用 max_tokens（默认 8000，弧列表两端原文长）。
        session_id: 仅签名兼容——本任务关缓存（防坏响应被 poison）。

    Returns:
        ``[{"description": str, "setup_chapter": int, "payoff_chapter": int|None,
        "setup_evidence": str, "payoff_evidence": str, "status": "resolved"|"dangling",
        "setup_verified": bool, "payoff_verified": bool, "setup_match_score": float,
        "payoff_match_score": float}, ...]`` 按 setup_chapter 排序；任意失败 ``None``。

        埋点核不过的弧已被滤掉；``status="dangling"`` = 断弧（埋了没回收）。
    """
    _ = session_id  # 关缓存：本任务出结构化 JSON，坏响应不该被缓存 poison
    system = _SYSTEM_INSTRUCTION + _BOOK_DELIMITER + full_text
    messages = [{"role": "user", "content": "请抽这本书的伏笔与回收弧线。"}]
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
        except Exception as exc:  # noqa: BLE001 — 包死，重试 / 返 None
            logger.warning(
                "foreshadow_arcs LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        arcs = _parse_arcs(llm_client.extract_final_text(response))
        if arcs is not None:
            return _verify_endpoints(arcs, chunks)
        logger.warning(
            "foreshadow_arcs parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
        )
    return None


__all__ = ["DEFAULT_ARCS_MAX_TOKENS", "generate_foreshadow_arcs"]
