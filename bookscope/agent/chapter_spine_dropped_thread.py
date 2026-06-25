"""支线失踪 = 章脉派生(算术筛候选 + 一次轻 LLM 复核)。ADR-010 出路 B 的一个视图。

**为什么有这个模块**:文体体检(``style_issues.generate_style_issues``)原来把"支线失踪
(dropped_thread)"和用词重复 / 视角越界一起塞在**局部**检测里——整本喂进一次 LLM、让它顺手
报。前两类是段内能判的局部毛病,可"支线失踪"天生**跨章**:一条线起了头、推进了几章,然后
后文再没下文。大书走分段 / 截断时,没有哪一段同时看见"这条线起了头"和"全书结束它还没回来",
这毛病系统性漏报。这是把关系型 / 时序型判断错塞进了聚合型流程——定义级的错。

做法分两步,复用已有的全书支线编织(``subplot_weave_from_spine``,它一次全局推理出每条支线 +
每条的 ``active_chapters``):

1. **算术筛候选**:一条支线起头有分量(活跃章数 ≥ ``min_active_chapters``,排掉打个酱油提一句
   的零散线),且最后一次活跃章远早于全书末章(末活跃章后还剩 ≥ ``min_silent_tail`` 章的沉默
   尾巴),就是"可疑失踪"。贯穿全书的主线活到末章,这步就排掉。

2. **一次轻 LLM 复核**(命根子=不 cry wolf):光看 active_chapters 区分不了两种"后文没下文"——
   一种是作者忘了收尾(真失踪),一种是这条线本就该在那儿终结(角色死了 / 目标达成 / 合流进
   主线,正常完结)。三国实测:"董卓祸乱"在董卓被杀那章正常终结、"吕布反复"在吕布被缢死那章
   正常终结——算术上和"忘了收尾"长得一模一样,直接报就是乱报。所以拿每条候选末活跃章前后的
   **事件流**问一次模型:这条线在这儿是**收束了**还是**悬着没下文**?只留悬着的。收束的滤掉。

**为什么第一步纯算术、只第二步发一次 LLM**:跨章的支线信息编织已经提炼好了(同
``chapter_spine_views`` 那批从章脉再投影的视图);失踪与否的算术初筛(active_chapters 对全书末章)
确定性算得出,不必发调用。只有"收束 vs 悬着"这一步是语义判断、躲不开 LLM——但只问已筛出的
少数候选、只发事件摘要(不发原文),便宜。一次调用,异常降级。

**输出形态对齐 style_issues 的 dropped_thread 条目**:``{type:"dropped_thread", what, chapter,
snippet, verified}``,FE 照旧读。``chapter`` = 这条线最后活跃(就此消失)的那一章;``snippet``
是这条线在末活跃章里的证据——传了 ``chunks`` 就**按失踪线名在末活跃章原文里现捞**那句真讲这条
线的话(证"这章这条线还在动"),没传则退回那一章的章代表句(向后兼容);``what`` 一句话说清
"哪条线、起于哪章、在哪章后消失"。另带更全的字段(线名 / 起于 / 末活跃 / 沉默尾巴长度),
FE 要画"失踪支线"专列时用。

任意环节空 / 抽不出 / 调用降级 → 返 ``[]``(没判出失踪,合法,不是失败)。复核调用抛异常时
**不**退回"全报"(那会 cry wolf),而是返 ``[]``——审稿工具宁可这次漏报,不可乱报。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.chapter_spine_evidence import (
    chapter_text_map as _chapter_text_map,
)
from bookscope.agent.chapter_spine_subplot import (
    DEFAULT_WEAVE_MAX_TOKENS,
    _thread_evidence,
    subplot_weave_from_spine,
)
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

# 起头有分量:活跃到这么多章才算"成了一条线"——只露一两章的零散提及不当支线失踪报(防 cry wolf)。
DEFAULT_MIN_ACTIVE_CHAPTERS = 2
# 沉默尾巴:末活跃章之后还剩这么多章没再出现,才算"后文消失没收尾"——离末章只差一两章不算失踪。
DEFAULT_MIN_SILENT_TAIL = 5
# 复核时给模型看末活跃章前后多少章的事件流当上下文(判这条线在这儿是收束还是悬着)。
_REVIEW_CONTEXT_WINDOW = 2

DEFAULT_REVIEW_MAX_TOKENS = 8000
"""复核输出只是逐候选一句判定 + 一个布尔,比支线编织小得多;留 reasoning 头给足防截断。"""

_REVIEW_INSTR = (
    "下面 candidates 是从一本书里初筛出的「疑似失踪支线」——每条线起头活跃了几章,之后到全书\n"
    "结束再没出现。但「之后没出现」有两种,要你分清:\n"
    "  A. **正常收束**:这条线本就该在最后那章了结——关键人物死了 / 目标达成或彻底失败 /\n"
    "     这条线合流进了别的线。不是毛病,作者收干净了。\n"
    "  B. **真失踪**:这条线起了头、立了悬念或目标,后文却再没交代,像是作者忘了收尾。这才是\n"
    "     审稿要抓的支线失踪。\n"
    "每条 candidate 给了:线名、它最后活跃的那一章、那一章前后的事件流(last_active_events)。\n"
    "请只依据这些事件判断每条是 A 还是 B。**判不准、或事件看着这条线是了结了的,一律当 A\n"
    "(正常收束)**——审稿宁可漏报,绝不把作者收好的线误报成失踪。\n"
    "严格输出 JSON(别的话别说、别加 markdown 代码围栏):\n"
    '{"verdicts":[{"thread":"线名(和输入一致)","dropped":true 表示真失踪/B、false 表示正常收束/A,'
    '"why":"一句话理由"}]}'
)


def _book_last_chapter(spine: list[dict[str, Any]]) -> int | None:
    """全书末章号(章脉里最大的真章号)。没有真章返 None。"""
    chs = [
        rec["chapter"]
        for rec in spine
        if isinstance(rec, dict) and isinstance(rec.get("chapter"), int)
    ]
    return max(chs) if chs else None


def _spine_by_chapter(spine: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    """章号 → 那一章的章脉记录(取证据 / 事件用)。"""
    out: dict[int, dict[str, Any]] = {}
    for rec in spine:
        if isinstance(rec, dict) and isinstance(rec.get("chapter"), int):
            out[rec["chapter"]] = rec
    return out


def _events_around(
    by_ch: dict[int, dict[str, Any]], center: int, window: int
) -> list[str]:
    """取 center 章前后 window 章范围内的事件流(给复核当判收束/悬着的线索)。"""
    evs: list[str] = []
    for ch in range(center - window, center + window + 1):
        rec = by_ch.get(ch)
        if not rec:
            continue
        for e in rec.get("events", []) or []:
            text = str(e.get("event", e) if isinstance(e, dict) else e).strip()
            if text:
                evs.append(f"第{ch}章:{text}")
    return evs


def _chapter_events_text(by_ch: dict[int, dict[str, Any]], ch: int) -> str:
    """取某一章的事件文本拼接(给"按失踪线名现捞末活跃章证据"拼 query 用)。

    线名抽象,光拿它去原文按字面捞命中弱;加这章的事件文本一起当检索词,更容易落到真讲这条线
    的那句(同 ``chapter_spine_subplot._collect_timeline`` 的 events_text 思路)。
    """
    rec = by_ch.get(ch)
    if not rec:
        return ""
    evs: list[str] = []
    for e in rec.get("events", []) or []:
        text = str(e.get("event", e) if isinstance(e, dict) else e).strip()
        if text:
            evs.append(text)
    return " ".join(evs)


def _parse_verdicts(text: str) -> dict[str, bool]:
    """把复核 LLM 的 ``{"verdicts":[...]}`` 解析成 线名→是否真失踪;三层兜底。

    解析不出任何裁决 → 返空 dict(调用方据此返 [],宁漏报不乱报)。
    """
    raw = (text or "").strip()
    if not raw:
        return {}
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
    items: Any = None
    if isinstance(obj, dict) and isinstance(obj.get("verdicts"), list):
        items = obj["verdicts"]
    else:
        salvaged = salvage_closed_objects(candidate, '"verdicts"')
        if salvaged:
            logger.warning(
                "chapter_spine_dropped_thread: 复核主解析失败,从截断抢救到 %d 条裁决",
                len(salvaged),
            )
            items = salvaged
    if not isinstance(items, list):
        return {}
    out: dict[str, bool] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("thread", "")).strip()
        if name:
            out[name] = bool(it.get("dropped"))
    return out


def dropped_threads_from_spine(
    *,
    spine: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    chunks: list[dict[str, Any]] | None = None,
    max_tokens: int = DEFAULT_WEAVE_MAX_TOKENS,
    review_max_tokens: int = DEFAULT_REVIEW_MAX_TOKENS,
    cache_enabled: bool = True,
    min_active_chapters: int = DEFAULT_MIN_ACTIVE_CHAPTERS,
    min_silent_tail: int = DEFAULT_MIN_SILENT_TAIL,
) -> list[dict[str, Any]]:
    """从全书支线编织判"起了头、后文消失没收尾"的失踪支线。算术筛候选 + 一次轻 LLM 复核。

    第一步复用 ``subplot_weave_from_spine`` 出的每条支线 ``active_chapters`` 算术初筛:起头有分量
    (活跃 ≥ ``min_active_chapters`` 章)、却在书没结束时就断了(末活跃章后留 ≥ ``min_silent_tail``
    章沉默尾巴)。第二步一次 LLM 复核,把"正常收束"(角色死 / 目标达成 / 合流入主线)的滤掉,
    只留"真悬着没下文"的——审稿命根子是不 cry wolf。

    Returns:
        list,每条对齐 style_issues 的 dropped_thread 条目并多带几个支线维度字段::

            {
                "type": "dropped_thread",
                "what": "「<线名>」起于第X章、推进到第Y章后再没下文（全书共Z章）",
                "chapter": 末活跃章 Y,         # 这条线就此消失的那一章
                "snippet": <第Y章里按失踪线名现捞的那句>,  # 证"这章这条线还在动"
                "verified": <snippet 是否非空>,
                "thread": <线名>,
                "started_chapter": X,
                "last_active_chapter": Y,
                "silent_tail": 末章 - Y,        # 后文沉默了多少章
                "active_chapters": [...],       # 这条线全部活跃章
            }

        没判出失踪(没失踪的线 / 候选全被复核判为正常收束 / 支线编织抽不出 / 书太短 / 复核降级)
        → ``[]``(合法,不是失败)。
    """
    last_ch = _book_last_chapter(spine)
    if last_ch is None:
        return []

    weave = subplot_weave_from_spine(
        spine=spine,
        llm_client=llm_client,
        model=model,
        chunks=chunks,
        max_tokens=max_tokens,
        cache_enabled=cache_enabled,
    )
    if not weave or not weave.get("subplots"):
        return []  # 支线编织降级 / 没支线:没判出失踪,合法

    by_ch = _spine_by_chapter(spine)
    # 传了 chunks 才现捞:按失踪线名在末活跃章原文里找真讲这条线的那句(证"这章它还在动")。
    chapter_text = _chapter_text_map(chunks) if chunks else {}

    # ── 第一步:算术筛"可疑失踪"候选 ────────────────────────────────────────
    candidates: list[dict[str, Any]] = []
    for sp in weave["subplots"]:
        active = sp.get("active_chapters") or []
        if len(active) < min_active_chapters:
            continue  # 只露一两章的零散提及,不当支线、更不当"失踪"
        started, last_active = active[0], active[-1]
        silent_tail = last_ch - last_active
        if silent_tail < min_silent_tail:
            continue  # 活到接近末章的(含主线):没消失,跳过
        if chunks:
            # 末活跃章原文里按"这条失踪线名"现捞,不挂章代表句(那是这章最显眼的别的事)。
            snippet = _thread_evidence(
                chapter_text.get(last_active, ""),
                sp["name"],
                _chapter_events_text(by_ch, last_active),
            )
        else:
            snippet = str(by_ch.get(last_active, {}).get("evidence", "")).strip()
        candidates.append({
            "thread": sp["name"],
            "started_chapter": started,
            "last_active_chapter": last_active,
            "silent_tail": silent_tail,
            "active_chapters": active,
            "snippet": snippet,
        })
    if not candidates:
        return []

    # ── 第二步:一次轻 LLM 复核,滤掉"正常收束"的,只留"真悬着" ───────────────
    review_payload = [
        {
            "thread": c["thread"],
            "last_active_chapter": c["last_active_chapter"],
            "last_active_events": _events_around(
                by_ch, c["last_active_chapter"], _REVIEW_CONTEXT_WINDOW
            ),
        }
        for c in candidates
    ]
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_REVIEW_INSTR,
            tools=[],
            messages=[{
                "role": "user",
                "content": json.dumps({"candidates": review_payload}, ensure_ascii=False),
            }],
            max_tokens=review_max_tokens,
            cache_enabled=cache_enabled,
        )
        verdicts = _parse_verdicts(llm_client.extract_final_text(resp))
    except Exception as exc:  # noqa: BLE001 — 复核失败宁可这次漏报,绝不退回"全报"乱报
        logger.warning(
            "chapter_spine_dropped_thread: 复核调用抛 %s: %s;返 []（宁漏报不乱报）",
            type(exc).__name__, exc,
        )
        return []

    out: list[dict[str, Any]] = []
    for c in candidates:
        if not verdicts.get(c["thread"]):  # 复核判为正常收束 / 没裁决到 → 滤掉
            continue
        out.append({
            "type": "dropped_thread",
            "what": (
                f"「{c['thread']}」起于第{c['started_chapter']}章、"
                f"推进到第{c['last_active_chapter']}章后再没下文"
                f"（全书共{last_ch}章）"
            ),
            "chapter": c["last_active_chapter"],
            "snippet": c["snippet"],
            "verified": bool(c["snippet"]),
            "thread": c["thread"],
            "started_chapter": c["started_chapter"],
            "last_active_chapter": c["last_active_chapter"],
            "silent_tail": c["silent_tail"],
            "active_chapters": c["active_chapters"],
        })
    # 沉默尾巴越长的越像"彻底断了",排前面
    out.sort(key=lambda d: -d["silent_tail"])
    return out


__all__ = [
    "DEFAULT_MIN_ACTIVE_CHAPTERS",
    "DEFAULT_MIN_SILENT_TAIL",
    "DEFAULT_REVIEW_MAX_TOKENS",
    "dropped_threads_from_spine",
]
