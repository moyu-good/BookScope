"""agent 模式编排器（WP-agent-mode §3 / §6 / §10）。

用户说一个目标，编排器三步把已有的整本书分析串起来回答它——**不跑任何新分析**：

1. **① 规划**：一次 LLM 调用，给目标 + 功能菜单，让模型挑该跑哪几个功能（只许挑菜单
   里的，未知功能丢弃；要参数的功能模型没给参数就跳过那条）。
2. **② 跑**：按计划调对应的已建 ``generate_*``（复用、不造新分析），收每个的**已核验**
   发现（verified 的）。单个功能失败记日志、跳过、不拖垮整次。
3. **③ 综合**：一次 LLM 调用，给目标 + 收齐的已核验发现（每条自带原文 snippet + 章号，
   都已过各源的 verify），写一段回答目标的综合。**每条结论引用某条发现**，不许引入无
   证据的新主张。

evidence-first 红线（同 annotations.py / WP §6）：综合只能用收齐的已核验发现，每条发现
自带的 snippet 都已被对应 ``generate_*`` 的 ``verify_citations`` 核过，所以综合输出的
citations 直接复用这些发现的 snippet + 真章号，不再让 LLM 自己编引用。没有发现就直说
没查到证据，不硬凑。

复用范式照搬 :mod:`bookscope.agent.annotations`：按选中调已有 generate_* 当数据源、
收已核验发现、不造新分析。LLM 调用走 :func:`invoke_client_cached`（规划/综合都关缓存
防 poison，同各 generate_* 的做法）。

三可靠性守卫（WP §10）：规划/综合两次 LLM 调用各自够 token + 解析失败重试一次；
子功能各自继承自身的 token / 缓存 / 重试守卫。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent.argument_structure import generate_argument_structure
from bookscope.agent.character_arc import generate_character_arc
from bookscope.agent.character_flow import generate_character_flow
from bookscope.agent.character_graph import extract_character_graph
from bookscope.agent.character_voice import generate_character_voice
from bookscope.agent.concept_evolution import generate_concept_evolution
from bookscope.agent.consistency_scan import generate_consistency_scan
from bookscope.agent.entity_recall import generate_entity_recall
from bookscope.agent.foreshadow_arcs import generate_foreshadow_arcs
from bookscope.agent.motif_tracking import generate_motif_tracking
from bookscope.agent.narrative_curve import generate_narrative_curve
from bookscope.agent.relationship_timeline import generate_relationship_timeline
from bookscope.agent.study_cards import generate_study_cards
from bookscope.agent.style_issues import generate_style_issues
from bookscope.agent.subplot_weave import generate_subplot_weave
from bookscope.agent.timeline import generate_timeline
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    parse_final_answer as _parse_final_answer,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)
from bookscope.agent.writing_technique import generate_writing_technique

logger = logging.getLogger(__name__)

# generate_* 名 → 函数对象的白名单映射。run 闭包在调用时按名查这张表（不是直接绑
# 函数对象），让测试 monkeypatch 这张表里的项能生效（同 annotations.py 的可测范式），
# 同时把哪些源可被编排显式收敛在一处。
_GENERATORS: dict[str, Callable[..., Any]] = {
    "extract_character_graph": extract_character_graph,
    "generate_character_flow": generate_character_flow,
    "generate_timeline": generate_timeline,
    "generate_consistency_scan": generate_consistency_scan,
    "generate_entity_recall": generate_entity_recall,
    "generate_concept_evolution": generate_concept_evolution,
    "generate_motif_tracking": generate_motif_tracking,
    "generate_argument_structure": generate_argument_structure,
    "generate_writing_technique": generate_writing_technique,
    "generate_study_cards": generate_study_cards,
    "generate_style_issues": generate_style_issues,
    "generate_narrative_curve": generate_narrative_curve,
    "generate_relationship_timeline": generate_relationship_timeline,
    "generate_character_arc": generate_character_arc,
    "generate_character_voice": generate_character_voice,
    "generate_subplot_weave": generate_subplot_weave,
    "generate_foreshadow_arcs": generate_foreshadow_arcs,
}

# 规划 / 综合两次 LLM 调用各自的 max_tokens + 重试次数（三可靠性守卫之一）。
PLAN_MAX_TOKENS = 1500
SYNTHESIS_MAX_TOKENS = 4000
_PLAN_MAX_ATTEMPTS = 2
_SYNTHESIS_MAX_ATTEMPTS = 2

# 单个功能收发现的封顶——一个功能产出太多发现会把综合 prompt 撑爆，截断保护。
_MAX_FINDINGS_PER_FEATURE = 12


# ---------------------------------------------------------------------------
# 把各 generate_* 千差万别的返回拍平成统一「已核验发现」：
#   {summary: 一句话结论, snippet: 原文片段, chapter: 真章号}
# 只收 verified 的（evidence-first）。每个 collect 函数对应一个数据源的返回形态。
# ---------------------------------------------------------------------------


def _verified(item: dict[str, Any]) -> bool:
    return bool(item.get("verified"))


def _finding(summary: str, snippet: str, chapter: Any) -> dict[str, Any] | None:
    """组一条发现；summary / snippet 任一为空就丢（无证据不进）。"""
    summary = str(summary or "").strip()
    snippet = str(snippet or "").strip()
    if not summary or not snippet:
        return None
    return {
        "summary": summary,
        "snippet": snippet,
        "chapter": chapter if isinstance(chapter, int) and chapter > 0 else 0,
    }


def _collect_flat(
    rows: Any,
    *,
    summary_key: str,
    snippet_key: str = "snippet",
) -> list[dict[str, Any]]:
    """收一个返回 list[dict] 的源：每条已核验的映射成一条发现。"""
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict) or not _verified(r):
            continue
        f = _finding(r.get(summary_key, ""), r.get(snippet_key, ""), r.get("chapter"))
        if f:
            out.append(f)
    return out


def _collect_foreshadow(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for arc in rows:
        if not isinstance(arc, dict) or not arc.get("setup_verified"):
            continue
        resolved = arc.get("status") == "resolved" and arc.get("payoff_verified")
        label = "伏笔已回收" if resolved else "伏笔埋下（未见回收）"
        f = _finding(
            f"{label}：{arc.get('description', '')}",
            arc.get("setup_evidence", ""),
            arc.get("setup_chapter"),
        )
        if f:
            out.append(f)
    return out


def _collect_consistency(rows: Any) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for c in rows:
        if not isinstance(c, dict):
            continue
        a = c.get("a") or {}
        b = c.get("b") or {}
        # 两侧都得 verified（同 annotations 的命根子）
        if not _verified(a) or not _verified(b):
            continue
        f = _finding(
            f"设定矛盾：{c.get('conflict', '') or c.get('topic', '')}",
            a.get("snippet", ""),
            a.get("chapter"),
        )
        if f:
            out.append(f)
    return out


def _collect_graph(result: Any) -> list[dict[str, Any]]:
    """character_graph 返回带 .edges 的对象；每条已核验的边一条发现。"""
    edges = getattr(result, "edges", None)
    if not isinstance(edges, list):
        return []
    out: list[dict[str, Any]] = []
    for e in edges:
        if not isinstance(e, dict) or not _verified(e):
            continue
        f = _finding(
            f"{e.get('source', '')} 与 {e.get('target', '')}：{e.get('relation', '')}",
            e.get("evidence", ""),
            e.get("chapter"),
        )
        if f:
            out.append(f)
    return out


def _collect_nested_points(
    rows: Any,
    *,
    outer_label_key: str,
    points_key: str,
    point_summary: Callable[[dict[str, Any]], str],
) -> list[dict[str, Any]]:
    """收 ``[{label, points:[{evidence, verified, chapter}]}]`` 形态（弧线 / 关系演变）。"""
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get(outer_label_key, "")).strip()
        points = row.get(points_key)
        if not isinstance(points, list):
            continue
        for p in points:
            if not isinstance(p, dict) or not _verified(p):
                continue
            f = _finding(
                f"{label}：{point_summary(p)}" if label else point_summary(p),
                p.get("evidence", ""),
                p.get("chapter"),
            )
            if f:
                out.append(f)
    return out


def _collect_narrative_curve(rows: Any) -> list[dict[str, Any]]:
    """逐章多维：每章一条 {chapter, tension, sentiment, pov, evidence, verified}。"""
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for ch in rows:
        if not isinstance(ch, dict) or not _verified(ch):
            continue
        f = _finding(
            f"第{ch.get('chapter', 0)}章 张力{ch.get('tension', '?')}"
            f" 情感{ch.get('sentiment', '?')} 视角{ch.get('pov', '')}",
            ch.get("evidence", ""),
            ch.get("chapter"),
        )
        if f:
            out.append(f)
    return out


def _collect_voice(result: Any) -> list[dict[str, Any]]:
    """character_voice 返回 dict：features（保留全部含未核验）+ drift_items（已 verify-filter）。

    这里两类都过 ``_verified`` / ``_finding`` 收，只留挂得上原文的。
    """
    if not isinstance(result, dict):
        return []
    out: list[dict[str, Any]] = []
    for feat in result.get("features", []) or []:
        if not isinstance(feat, dict) or not _verified(feat):
            continue
        f = _finding(
            f"语言特征：{feat.get('trait', '')}",
            feat.get("evidence", ""),
            feat.get("chapter"),
        )
        if f:
            out.append(f)
    for d in result.get("drift_items", []) or []:
        if not isinstance(d, dict):
            continue
        f = _finding(
            f"声口可能跑偏：{d.get('reason', '')}",
            d.get("quote", ""),
            d.get("chapter"),
        )
        if f:
            out.append(f)
    return out


def _collect_subplot(result: Any) -> list[dict[str, Any]]:
    """subplot_weave 返回 dict：intersections 已双端 verify-filter，取它做发现。"""
    if not isinstance(result, dict):
        return []
    out: list[dict[str, Any]] = []
    for it in result.get("intersections", []) or []:
        if not isinstance(it, dict):
            continue
        names = it.get("subplots") or []
        label = " × ".join(str(n) for n in names) if isinstance(names, list) else ""
        f = _finding(
            f"支线交汇：{label}",
            it.get("a_evidence", ""),
            it.get("chapter"),
        )
        if f:
            out.append(f)
    return out


# ---------------------------------------------------------------------------
# 功能菜单：可编排的分析功能。每项：
#   desc   一句话「能干啥」（喂规划 LLM）
#   params 需要的额外参数名（entity / motif / concept / character）；没有则空 tuple
#   run    (full_text, chunks, llm_client, model, session_id, params) -> 已核验发现 list
# 问书本身、suggest-questions 不进菜单（WP §10）。pacing-curve 无原文证据、不进
# （evidence-first：没 verified 字段的不当综合证据）。
# ---------------------------------------------------------------------------


def _runner(
    gen_name: str,
    collect: Callable[[Any], list[dict[str, Any]]],
    *,
    extra_arg: str | None = None,
) -> Callable[..., list[dict[str, Any]]]:
    """把一个 generate_* + 它的 collect 包成统一 run 签名。

    ``gen_name`` 是 generate_* 在 ``_GENERATORS`` 里的键（不是函数对象）——运行时按名
    查表取，这样测试 monkeypatch ``_GENERATORS[name]`` 能生效（同 annotations.py 的
    可测范式）。``extra_arg`` 指定该功能要从 params 里取哪个参数（如 entity）喂给
    generate_*；None 表示该功能不要额外参数。
    """

    def _run(
        *,
        full_text: str,
        chunks: list[dict[str, Any]],
        llm_client: Any,
        model: str,
        session_id: str | None,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        gen = _GENERATORS[gen_name]
        kw: dict[str, Any] = {
            "full_text": full_text,
            "chunks": chunks,
            "llm_client": llm_client,
            "model": model,
            "session_id": session_id,
        }
        if extra_arg is not None:
            kw[extra_arg] = params[extra_arg]
        return collect(gen(**kw))

    return _run


def _runner_graph() -> Callable[..., list[dict[str, Any]]]:
    """character_graph 签名特殊（用 extract_character_graph + unit），单独包。"""

    def _run(
        *,
        full_text: str,
        chunks: list[dict[str, Any]],
        llm_client: Any,
        model: str,
        session_id: str | None,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        result = _GENERATORS["extract_character_graph"](
            full_text=full_text,
            chunks=chunks,
            llm_client=llm_client,
            model=model,
            unit="person",
            session_id=session_id,
        )
        return _collect_graph(result)

    return _run


FEATURE_MENU: dict[str, dict[str, Any]] = {
    "character_graph": {
        "desc": "抽全书人物关系图（谁和谁什么关系，带原文出处）",
        "params": (),
        "run": _runner_graph(),
    },
    "character_flow": {
        "desc": "逐章谁和谁同场登场互动（叙事流）",
        "params": (),
        "run": _runner(
            "generate_character_flow",
            lambda chapters: _collect_nested_points(
                chapters,
                outer_label_key="chapter",
                points_key="pairs",
                point_summary=lambda p: f"{p.get('a', '')} 与 {p.get('b', '')} 同场",
            ),
        ),
    },
    "timeline": {
        "desc": "按时间先后梳理全书主要事件（含倒叙还原真实顺序）",
        "params": (),
        "run": _runner(
            "generate_timeline",
            lambda rows: _collect_flat(rows, summary_key="event", snippet_key="evidence"),
        ),
    },
    "consistency": {
        "desc": "扫全书设定/人物前后矛盾（每条两处原文都核验过）",
        "params": (),
        "run": _runner("generate_consistency_scan", _collect_consistency),
    },
    "entity_recall": {
        "desc": "回溯某个实体（人/物/地点/概念）在全书的出现轨迹",
        "params": ("entity",),
        "run": _runner(
            "generate_entity_recall",
            lambda rows: _collect_flat(rows, summary_key="what"),
            extra_arg="entity",
        ),
    },
    "concept_evolution": {
        "desc": "回溯某个概念在全书的演进阶段（理论书学习）",
        "params": ("concept",),
        "run": _runner(
            "generate_concept_evolution",
            lambda rows: _collect_flat(rows, summary_key="development"),
            extra_arg="concept",
        ),
    },
    "motif": {
        "desc": "追踪某个主题/母题在全书的复现",
        "params": ("motif",),
        "run": _runner(
            "generate_motif_tracking",
            lambda rows: _collect_flat(rows, summary_key="manifestation"),
            extra_arg="motif",
        ),
    },
    "argument_structure": {
        "desc": "梳理一本书的论点结构（主张 + 原文证据，理论书/论文）",
        "params": (),
        "run": _runner(
            "generate_argument_structure",
            lambda rows: _collect_flat(rows, summary_key="claim", snippet_key="evidence"),
        ),
    },
    "writing_technique": {
        "desc": "分析一本书的写作手法（学手艺，带原文例子）",
        "params": (),
        "run": _runner(
            "generate_writing_technique",
            lambda rows: _collect_flat(rows, summary_key="technique", snippet_key="snippet"),
        ),
    },
    "study_cards": {
        "desc": "据一本书出知识点卡片（含自测题，理论书/工具书）",
        "params": (),
        "run": _runner(
            "generate_study_cards",
            lambda rows: _collect_flat(rows, summary_key="point", snippet_key="snippet"),
        ),
    },
    "style_issues": {
        "desc": "扫一本书的文体级毛病（用词重复/视角越界/支线失踪，作家自审）",
        "params": (),
        "run": _runner(
            "generate_style_issues",
            lambda rows: _collect_flat(rows, summary_key="what", snippet_key="snippet"),
        ),
    },
    "narrative_curve": {
        "desc": "逐章抽多维叙事曲线（张力 + 情感方向 + 主导视角）",
        "params": (),
        "run": _runner("generate_narrative_curve", _collect_narrative_curve),
    },
    "relationship_timeline": {
        "desc": "逐对主要关系抽随时间的演变 + 关键转折",
        "params": (),
        "run": _runner(
            "generate_relationship_timeline",
            lambda rows: _collect_nested_points(
                rows,
                outer_label_key="relation",
                points_key="turning_points",
                point_summary=lambda p: p.get("change", ""),
            ),
        ),
    },
    "character_arc": {
        "desc": "给主要角色逐章抽戏份/处境弧线（谁何时主导、过得顺不顺）",
        "params": (),
        "run": _runner(
            "generate_character_arc",
            lambda rows: _collect_nested_points(
                rows,
                outer_label_key="name",
                points_key="points",
                point_summary=lambda p: (
                    f"第{p.get('chapter', 0)}章 戏份{p.get('presence', '?')}"
                    f" 处境{p.get('fortune', '?')}"
                ),
            ),
        ),
    },
    "character_voice": {
        "desc": "给一个角色刻画声口 + 标「这句不像他说的」",
        "params": ("character",),
        "run": _runner("generate_character_voice", _collect_voice, extra_arg="character"),
    },
    "subplot_weave": {
        "desc": "抽情节支线 + 两条支线同章交汇（编织结构）",
        "params": (),
        "run": _runner("generate_subplot_weave", _collect_subplot),
    },
    "foreshadow": {
        "desc": "抽伏笔→回收弧线（埋了什么、有没有回收）",
        "params": (),
        "run": _runner("generate_foreshadow_arcs", _collect_foreshadow),
    },
}


# ---------------------------------------------------------------------------
# 事件回调（复用问书 SSE 基建的形态：keyword-only、异常包死、None 即跳过）。
# 端点把这些 dict emit 成 SSE 帧；编排器本身不依赖 SSE，回调可为 None。
# ---------------------------------------------------------------------------

OrchestrateCallback = Callable[[dict[str, Any]], None]


def _make_safe_emit(on_event: OrchestrateCallback | None) -> Callable[[dict[str, Any]], None]:
    def _emit(event: dict[str, Any]) -> None:
        if on_event is None:
            return
        try:
            on_event(event)
        except Exception:  # noqa: BLE001 — 回调异常绝不拖垮编排主流程
            logger.exception("orchestrate on_event callback raised; suppressed")

    return _emit


# ---------------------------------------------------------------------------
# ① 规划
# ---------------------------------------------------------------------------

_PLAN_SYSTEM = (
    "你是 BookScope 的分析编排器。用户给你一个分析目标，你要从下面的「功能菜单」里挑出"
    "为达成这个目标该跑哪几个分析功能、按什么顺序跑、为什么。\n"
    "严格只输出 JSON（不要别的话、不要 markdown 围栏）：\n"
    '{"plan": [{"feature": "菜单里的功能名", "params": {"参数名": "值"}, "why": "为什么挑它"}]}\n'
    "硬规则：\n"
    "1. feature 只能是菜单里列出的名字，不许编。\n"
    "2. 需要参数的功能（菜单标了 params）必须在 params 里给齐，给不出就别挑它。\n"
    "3. 挑最相关的 2-5 个，别把整张菜单都列上——目标不需要的不挑。\n"
    "4. params 里只放该功能要的参数；不需要参数的功能 params 给空对象 {}。"
)


def _format_menu_for_prompt() -> str:
    """把菜单编成喂给规划 LLM 的人话清单（功能名 + 能干啥 + 要哪些参数）。"""
    lines: list[str] = []
    for name, spec in FEATURE_MENU.items():
        params = spec["params"]
        param_note = (
            f"（需要参数：{', '.join(params)}）" if params else "（不需要参数）"
        )
        lines.append(f"- {name}：{spec['desc']} {param_note}")
    return "\n".join(lines)


def _parse_plan(text: str) -> list[dict[str, Any]] | None:
    """从规划 LLM 输出里抠出 plan 数组；解析失败返 None（调用方重试）。"""
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
    if not isinstance(obj, dict):
        return None
    plan = obj.get("plan")
    if not isinstance(plan, list):
        return None
    return plan


def _validate_plan(raw_plan: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """校验 LLM 给的计划：只留菜单里的功能；要参数的没给齐就丢那条（WP §10）。

    返回清洗后的 ``[{feature, params, why}]``，feature 都在 ``FEATURE_MENU`` 里、
    params 含该功能要的所有参数。重复功能按首次出现保留。
    """
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for step in raw_plan:
        if not isinstance(step, dict):
            continue
        feature = step.get("feature")
        if not isinstance(feature, str) or feature not in FEATURE_MENU:
            logger.info("orchestrate: 丢弃菜单外功能 %r", feature)
            continue
        if feature in seen:
            continue
        spec = FEATURE_MENU[feature]
        params_in = step.get("params")
        params: dict[str, Any] = params_in if isinstance(params_in, dict) else {}
        # 要参数的功能：每个要的参数都得有非空值，否则跳过这条
        missing = [
            p for p in spec["params"]
            if not str(params.get(p, "")).strip()
        ]
        if missing:
            logger.info(
                "orchestrate: 功能 %r 缺参数 %s，跳过", feature, missing
            )
            continue
        clean_params = {p: str(params[p]).strip() for p in spec["params"]}
        seen.add(feature)
        out.append({
            "feature": feature,
            "params": clean_params,
            "why": str(step.get("why", "")).strip(),
        })
    return out


def _plan(
    goal: str,
    *,
    llm_client: Any,
    model: str,
    session_id: str | None,
) -> list[dict[str, Any]]:
    """① 规划：一次 LLM 调用挑功能，校验后返清洗过的计划。失败返空计划。"""
    system = _PLAN_SYSTEM + "\n\n=== 功能菜单 ===\n" + _format_menu_for_prompt()
    user = f"分析目标：{goal}"
    for attempt in range(1, _PLAN_MAX_ATTEMPTS + 1):
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=[{"role": "user", "content": user}],
                max_tokens=PLAN_MAX_TOKENS,
                cache_enabled=False,  # 规划随目标变，关缓存防 poison（同各 generate_*）
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "orchestrate plan LLM 调用失败 %s: %s（attempt %d）",
                type(exc).__name__, exc, attempt,
            )
            continue
        raw_plan = _parse_plan(llm_client.extract_final_text(response))
        if raw_plan is None:
            logger.warning(
                "orchestrate plan 解析失败（attempt %d/%d）", attempt, _PLAN_MAX_ATTEMPTS
            )
            continue
        return _validate_plan(raw_plan)
    return []


# ---------------------------------------------------------------------------
# ② 跑
# ---------------------------------------------------------------------------


def _run_step(
    step: dict[str, Any],
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    session_id: str | None,
) -> list[dict[str, Any]]:
    """跑一个计划步（调对应 generate_*、收已核验发现）。失败抛给调用方按步跳过。"""
    spec = FEATURE_MENU[step["feature"]]
    findings = spec["run"](
        full_text=full_text,
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        session_id=session_id,
        params=step["params"],
    )
    return findings[:_MAX_FINDINGS_PER_FEATURE]


# ---------------------------------------------------------------------------
# ③ 综合
# ---------------------------------------------------------------------------

_SYNTHESIS_SYSTEM = (
    "你是 BookScope 的综合分析助手。下面给你一个分析目标，和一组「已核验发现」——每条发现"
    "都自带一句原文片段（snippet）和它所在的章号，这些原文都已被核验过确实出自本书。\n"
    "请只根据这些发现，写一段回答目标的综合分析。\n"
    "硬规则（evidence-first，命根子）：\n"
    "1. 每个结论都必须靠某条发现支撑，不许引入发现里没有的新主张、不许用书外知识。\n"
    "2. citations 里每条直接引用某条发现的原文片段，原样摘录、不要改写 snippet。\n"
    "3. 发现不足以支撑目标时，老实说证据不够，别硬凑。\n"
    "严格输出 JSON（不要别的话、不要 markdown 围栏）：\n"
    '{"answer": "你的综合分析", "citations": [{"chapter": 章号整数, "snippet": "原文片段"}]}'
)


def _format_findings_for_prompt(findings: list[dict[str, Any]]) -> str:
    """把收齐的发现编号列给综合 LLM（带章号 + 一句话结论 + 原文片段）。"""
    lines: list[str] = []
    for i, f in enumerate(findings, start=1):
        lines.append(
            f"[发现{i}] 第{f['chapter']}章 · {f['summary']}\n"
            f"  原文：{f['snippet']}"
        )
    return "\n".join(lines)


def _synthesize(
    goal: str,
    findings: list[dict[str, Any]],
    *,
    llm_client: Any,
    model: str,
    session_id: str | None,
) -> dict[str, Any]:
    """③ 综合：一次 LLM 调用据已核验发现写综合，citations 复用发现的原文。

    返回 ``{"text": 综合文, "citations": [...]}``。综合 LLM 自己输出的 citations 只取
    它引用的章号 + snippet，但为守 evidence-first，最终 citations 用「与某条发现 snippet
    对得上」的那些发现原文（带真章号），对不上的 LLM 自造引用一律丢——综合不该引入无
    证据的新引用。发现为空 / 综合失败时返回兜底「没查到证据」。
    """
    if not findings:
        return {
            "text": "没有从这本书里查到能支撑这个目标的原文证据。",
            "citations": [],
        }

    system = (
        _SYNTHESIS_SYSTEM
        + f"\n\n=== 分析目标 ===\n{goal}\n\n=== 已核验发现 ===\n"
        + _format_findings_for_prompt(findings)
    )
    for attempt in range(1, _SYNTHESIS_MAX_ATTEMPTS + 1):
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=[{"role": "user", "content": "请据这些发现综合回答目标。"}],
                max_tokens=SYNTHESIS_MAX_TOKENS,
                cache_enabled=False,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "orchestrate synthesis LLM 调用失败 %s: %s（attempt %d）",
                type(exc).__name__, exc, attempt,
            )
            continue
        try:
            answer, citations = _parse_final_answer(
                llm_client.extract_final_text(response), lenient=True
            )
        except Exception as exc:  # noqa: BLE001 — 解析失败：重试再兜底
            logger.warning(
                "orchestrate synthesis 解析失败（attempt %d/%d）：%s",
                attempt, _SYNTHESIS_MAX_ATTEMPTS, exc,
            )
            continue
        return {
            "text": answer,
            "citations": _ground_citations(citations, findings),
        }
    # 两次都失败：不丢发现，退化成「列出已查到的证据」兜底
    return {
        "text": (
            "综合分析这一步没跑成，但已经从书里查到下面这些有原文支撑的发现，"
            "供你自己判断。"
        ),
        "citations": [
            {"chapter": f["chapter"], "snippet": f["snippet"]} for f in findings
        ],
    }


def _ground_citations(
    llm_citations: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """把综合 LLM 给的 citations 钉回已核验发现（evidence-first 守门）。

    只保留「snippet 能和某条发现对上」的引用——发现的 snippet 已过各源 verify，是可信
    原文。LLM 自造、对不上任何发现的引用一律丢（不许引入无证据的新引用）。匹配宽松：
    子串双向命中即算（LLM 可能截一段发现原文）。命中后用发现的真章号，不信 LLM 自报。
    """
    grounded: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for cit in llm_citations:
        snippet = str(cit.get("snippet", "")).strip()
        if not snippet:
            continue
        match = _match_finding(snippet, findings)
        if match is None:
            logger.info("orchestrate: 丢弃对不上发现的综合引用 %r", snippet[:40])
            continue
        key = (match["chapter"], match["snippet"])
        if key in seen:
            continue
        seen.add(key)
        # match 来自"只收 verified"的发现、snippet 已过各源 verify → 标 verified,
        # 让前端能盖「鉴」、综合的 evidence-first 在数据上诚实(不靠前端 undefined 兜底)。
        grounded.append({
            "chapter": match["chapter"], "snippet": match["snippet"], "verified": True,
        })
    return grounded


def _match_finding(
    snippet: str, findings: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """找 snippet 对得上的发现：互为子串即命中（LLM 可能截一段）。"""
    for f in findings:
        fs = f["snippet"]
        if snippet in fs or fs in snippet:
            return f
    return None


# ---------------------------------------------------------------------------
# 编排主流程
# ---------------------------------------------------------------------------


def orchestrate(
    *,
    goal: str,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    session_id: str | None = None,
    on_event: OrchestrateCallback | None = None,
) -> dict[str, Any]:
    """目标驱动的编排：规划 → 跑已有分析 → 综合（evidence-first）。

    Args:
        goal: 用户的自然语言分析目标。
        full_text: 整本书 cleaned 原文（喂各 generate_*）。
        chunks: 全书 chunk（给各源核验 + 章号 ground truth）。
        llm_client: duck-typed LLM client（可被 _UsageRecorder 包一层记账）。
        model: 模型名。
        session_id: 透传给各 generate_*（它们各自关缓存防 poison）。
        on_event: 可选 SSE 回调。依次 emit::

            {"type": "plan", "plan": [{feature, why, params}]}
            {"type": "step", "feature": ..., "summary": 一句话, "found": n,
             "drill": {"feature": ..., "params": {...}}}   # 每跑完一个功能
            {"type": "synthesis", "text": ..., "citations": [...]}
            {"type": "error", "message": ...}              # 整体失败

    Returns:
        ``{goal, plan, steps, synthesis, scanned}``：

        - ``plan``：清洗后的计划 ``[{feature, params, why}]``。
        - ``steps``：每个跑成功的功能 ``[{feature, summary, found, drill}]``，
          ``drill`` = ``{feature, params}`` 让前端能点进该功能完整视图。
        - ``synthesis``：``{text, citations}``，citations 每条挂得到原文（已钉回发现）。
        - ``scanned``：实际跑成功（没抛错）的功能名列表。
    """
    emit = _make_safe_emit(on_event)

    plan = _plan(goal, llm_client=llm_client, model=model, session_id=session_id)
    emit({"type": "plan", "plan": plan})

    all_findings: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    scanned: list[str] = []

    for step in plan:
        feature = step["feature"]
        try:
            findings = _run_step(
                step,
                full_text=full_text,
                chunks=chunks,
                llm_client=llm_client,
                model=model,
                session_id=session_id,
            )
        except Exception as exc:  # noqa: BLE001 — 单功能失败不拖垮整次编排
            logger.warning(
                "orchestrate 功能 %s 失败 %s: %s，跳过",
                feature, type(exc).__name__, exc,
            )
            continue
        scanned.append(feature)
        all_findings.extend(findings)
        summary = (
            f"查到 {len(findings)} 条带原文的发现"
            if findings
            else "没查到带原文支撑的发现"
        )
        step_record = {
            "feature": feature,
            "summary": summary,
            "found": len(findings),
            "drill": {"feature": feature, "params": step["params"]},
        }
        steps.append(step_record)
        emit({"type": "step", **step_record})

    synthesis = _synthesize(
        goal, all_findings, llm_client=llm_client, model=model, session_id=session_id
    )
    emit({
        "type": "synthesis",
        "text": synthesis["text"],
        "citations": synthesis["citations"],
    })

    return {
        "goal": goal,
        "plan": plan,
        "steps": steps,
        "synthesis": synthesis,
        "scanned": scanned,
    }


__all__ = [
    "FEATURE_MENU",
    "PLAN_MAX_TOKENS",
    "SYNTHESIS_MAX_TOKENS",
    "OrchestrateCallback",
    "orchestrate",
]
