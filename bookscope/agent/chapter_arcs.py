"""卷/幕层(WP-hierarchical-spine):把逐章章脉聚成 ~8-15 个连续卷,给全局功能省 token。

**为什么有这个模块**:章脉(ADR-010)是所有整本书功能的公共前置。长书的全局功能(关系图 /
时间线 / 母题 / 节奏)现在把几百条逐章记录直接塞进上下文 → token 大、且几百个点看不出全书
骨架(研究笔记 012「分层归并拼接不连贯」的公认坑)。加一层卷节点:把连续章按大转折聚成
~几十个叙事单元,全局功能改吃卷 → token 降一个量级、更连贯;要细节再下钻到章 / 原文。

**方法论锚 RAPTOR(2401.18059)**,两处叙事化偏离:
1. 不用 embedding 聚类——小说的卷是**连续**章构成的子故事。让 LLM 在**紧凑章脉**上
   (读 events/转折,**绝不喂原文**)按大转折切连续卷 → 便宜、不重读原文。
2. 每个卷节点的证据 = 指回成员章(章记录本身已锚原文)——evidence-first 不新增幻觉面。

**这一层纯 additive**:不碰 ``build_chapter_spine``、不碰任何现有端点。probe(exp021,三国 120
章切 15 卷、边界准、全局 input 省 6.4 倍、质量 ≥ 章层)GO 才实现。

**三个守卫(probe 定的)**:结构校验不合规 → 退固定窗口兜底;evidence_chapters 裁到本卷跨度内;
短书(章数 < ``_ARC_MIN_CHAPTERS``)不建卷层、返 None(调用方用章层)。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import strip_code_fence as _strip_code_fence

logger = logging.getLogger(__name__)

ARC_SCHEMA_VERSION = "v1"
"""卷层记录结构版本——升级要让卷层缓存失效(接 ADR-008 L3,同 SPINE_SCHEMA_VERSION 思路)。"""

_ARC_MIN_CHAPTERS = 40
"""短书跳过阈值:章数 < 40 → 不建卷层、返 None(章少的书卷层没意义,省得多一步)。WP 第一节。"""

_ARC_MAX_TOKENS = 8000
"""卷切分输出(~8-15 个卷 × 几字段)一次装得下;比逐章抽取的 16000 小(卷层输出短)。"""

_ARC_TARGET_MIN = 8
_ARC_TARGET_MAX = 15
"""卷数目标区间(probe 定的 8-15,别太碎也别太粗)。只作 prompt 引导,不作硬校验门槛。"""

_FIXED_WINDOW_SIZE = 10
"""固定窗口兜底:LLM 切分不合规时,每 ~10 章机械切一卷(WP 守卫 a)。"""


# ── 卷切分指令(input = 紧凑章脉,绝不喂原文;沿用 probe 定案的 prompt 形态)──────────
_VOLUME_SPLIT_INSTR = (
    "下面是一本书的**逐章骨架**(每行一章:在场人物 / 关键事件 / 张力 / 主支线 / 伏笔)。"
    "这不是原文,是已经精读过的章脉摘要。\n"
    "请你**按大的叙事转折**把连续的章切成若干个「卷」(叙事单元),每个卷是一段连续剧情。"
    f"目标切成 {_ARC_TARGET_MIN} 到 {_ARC_TARGET_MAX} 个卷,别太碎也别太粗。"
    "切分点要踩在真正的大转折上(势力更替 / 关键人物登场退场 / 战役成败 / 阶段目标达成)。\n"
    "每个卷给:\n"
    "1. chapter_span:这个卷覆盖的章号跨度 [起始章, 结束章](整数,连续、不重叠、不留空)。\n"
    "2. title:这个卷的卷名/主题(一句短语,概括这段讲什么)。\n"
    "3. theme:这个卷在全书里的作用/主题(一句话)。\n"
    "4. key_events:这个卷的关键事件数组(从成员章聚合,3-6 条,每条一句)。\n"
    "5. central_characters:这个卷的核心人物数组(这段戏份最重的几个)。\n"
    "6. evidence_chapters:这个卷的判断依据 = 指回哪几章的章号数组(成员章里最能定性这卷的几章)。\n"
    "只据上面的逐章骨架判断,不臆测骨架里没有的内容。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"volumes":[{"chapter_span":[起,止],"title":"","theme":"","key_events":[],'
    '"central_characters":[],"evidence_chapters":[]}]}'
)

_USER_MSG = "请按上面的要求把这些章切成卷。"


# ── 紧凑章脉视图:只留全局推理要的骨架字段,绝不带 evidence 原文逐字长片段 ──────────
def _compact_chapter_line(rec: dict[str, Any]) -> str:
    """把一条章脉记录压成一行紧凑文本(喂卷切分)。

    只取骨架:章号 / 在场人物 / 事件 / 张力 / 主支线 / 伏笔埋收。**不含 evidence 原文**——
    evidence 是逐字原文片段,喂进去会稀释 token、也偏离「卷层不重读原文」的精神。
    """
    ch = rec.get("chapter")
    present = rec.get("present") or []
    events = rec.get("events") or []
    tension = rec.get("tension")
    mainline = rec.get("mainline")
    fore = rec.get("foreshadow") or []
    parts = [f"第{ch}章"]
    if present:
        parts.append("在场:" + "、".join(str(p) for p in present[:8]))
    if events:
        parts.append("事件:" + ";".join(str(e) for e in events[:4]))
    if isinstance(tension, int):
        parts.append(f"张力{tension}")
    if mainline is False:
        parts.append("支线")
    if fore:
        hooks = []
        for f in fore[:3]:
            if isinstance(f, dict):
                hooks.append(f"{f.get('type', '')}:{f.get('hook', '')}")
        if hooks:
            parts.append("伏笔[" + "|".join(hooks) + "]")
    return " / ".join(parts)


def _compact_spine_text(spine: list[dict[str, Any]]) -> str:
    """整条章脉压成逐章紧凑文本块(卷切分的 input)。"""
    return "\n".join(_compact_chapter_line(r) for r in spine)


# ── 解析 LLM 卷切分输出 ──────────────────────────────────────────────────────
def _parse_volumes(text: str) -> list[dict[str, Any]] | None:
    """从模型输出里抠 ``{"volumes":[...]}`` 的卷数组;抠不到返 None。

    复用 json_parsing 的 strip 围栏 + 括号平衡剥首个 obj,不另造解析器。
    """
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
    volumes = obj.get("volumes")
    return volumes if isinstance(volumes, list) else None


def _sorted_chapters(spine: list[dict[str, Any]]) -> list[int]:
    """章脉里的真章号,去重升序(卷层的覆盖基准)。"""
    return sorted({r["chapter"] for r in spine if isinstance(r.get("chapter"), int)})


# ── 守卫 a:结构校验(连续 / 不重叠 / 覆盖全部章号)────────────────────────────────
def _validate_spans(volumes: list[dict[str, Any]], chapters: list[int]) -> bool:
    """校验卷跨度:连续、不重叠、恰好覆盖章脉里的全部章号。

    合规条件(全部满足才 True):
    - 每个卷有合法 [起, 止] 整数跨度、起 ≤ 止;
    - 卷按起始章排序后首尾相接(第 i 卷的止 + 1 == 第 i+1 卷的起)——无 gap、无 overlap;
    - 第一卷起 == 最小章号,末卷止 == 最大章号(覆盖全书);
    - 章脉不连号(有洞)时,卷跨度并起来的章集合恰好等于章脉章集合。

    任一不满足 → False,调用方退固定窗口兜底(别硬用坏切分)。
    """
    if not volumes or not chapters:
        return False
    spans: list[tuple[int, int]] = []
    for v in volumes:
        s = v.get("chapter_span")
        if not (isinstance(s, list) and len(s) == 2):
            return False
        lo, hi = s[0], s[1]
        if not (isinstance(lo, int) and isinstance(hi, int)) or lo > hi:
            return False
        spans.append((lo, hi))
    spans.sort()
    # 首尾相接:相邻卷严格 prev_hi + 1 == cur_lo(无 gap、无 overlap)
    for i in range(1, len(spans)):
        if spans[i][0] != spans[i - 1][1] + 1:
            return False
    chap_set = set(chapters)
    # 覆盖全书:首卷起=最小章、末卷止=最大章,且跨度并集恰好等于章脉章集(容洞不多算)
    if spans[0][0] != min(chap_set) or spans[-1][1] != max(chap_set):
        return False
    covered = {c for lo, hi in spans for c in range(lo, hi + 1)}
    return covered == chap_set


# ── 守卫 b:evidence_chapters 裁剪到本卷跨度内 ────────────────────────────────
def _clip_evidence_chapters(vol: dict[str, Any]) -> list[int]:
    """把卷的 evidence_chapters 裁到本卷 chapter_span 内(模型偶尔点到邻卷)。

    只保留 [起, 止] 区间内的整数章号,去重升序。span 非法 / evidence 空 → 返 []。
    """
    span = vol.get("chapter_span")
    if not (isinstance(span, list) and len(span) == 2):
        return []
    lo, hi = span[0], span[1]
    if not (isinstance(lo, int) and isinstance(hi, int)):
        return []
    raw = vol.get("evidence_chapters") or []
    if not isinstance(raw, list):
        return []
    kept = {c for c in raw if isinstance(c, int) and lo <= c <= hi}
    return sorted(kept)


def _normalize_volume(vol: dict[str, Any]) -> dict[str, Any]:
    """把一个卷 dict 归一成卷层该有的字段(缺的给缺省,evidence 裁到本卷跨度内)。"""
    span = vol.get("chapter_span")
    span_out = (
        [span[0], span[1]]
        if isinstance(span, list) and len(span) == 2
        and isinstance(span[0], int) and isinstance(span[1], int)
        else []
    )
    return {
        "chapter_span": span_out,
        "title": str(vol.get("title", "")).strip(),
        "theme": str(vol.get("theme", "")).strip(),
        "key_events": vol.get("key_events") if isinstance(vol.get("key_events"), list) else [],
        "central_characters": (
            vol.get("central_characters")
            if isinstance(vol.get("central_characters"), list)
            else []
        ),
        "evidence_chapters": _clip_evidence_chapters(vol),
    }


# ── 固定窗口兜底(守卫 a 不合规时机械切)────────────────────────────────────────
def _fixed_window_arcs(chapters: list[int]) -> list[dict[str, Any]]:
    """LLM 切分不合规时的兜底:每 ~``_FIXED_WINDOW_SIZE`` 章机械切一卷。

    卷标「近似分卷」——title/theme 空、key_events/central_characters 空(没重读、不硬编);
    chapter_span 用真章号的窗口边界(连续、不重叠、覆盖全部章);evidence_chapters = 本窗口全部章。
    覆盖全书骨架就行,别硬凑内容(evidence-first:核不过的不编)。
    """
    if not chapters:
        return []
    arcs: list[dict[str, Any]] = []
    for i in range(0, len(chapters), _FIXED_WINDOW_SIZE):
        window = chapters[i : i + _FIXED_WINDOW_SIZE]
        arcs.append(
            {
                "chapter_span": [window[0], window[-1]],
                "title": "",
                "theme": "",
                "key_events": [],
                "central_characters": [],
                "evidence_chapters": list(window),
                "approximate": True,  # 标「近似分卷」:兜底切的,非 LLM 按转折切
            }
        )
    return arcs


# ── 主构建函数 ────────────────────────────────────────────────────────────────
def build_arc_layer(
    *,
    spine: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    min_chapters: int = _ARC_MIN_CHAPTERS,
    max_tokens: int = _ARC_MAX_TOKENS,
) -> list[dict[str, Any]] | None:
    """把逐章章脉聚成卷层(WP-hierarchical-spine)。**纯 additive,不碰章脉构建。**

    流程:
    1. **守卫 c(短书跳过)**:章脉真章数 < ``min_chapters`` → 返 ``None``(调用方用章层)。
    2. 把紧凑章脉(骨架,绝不喂原文)喂一次 LLM 切成 ~8-15 个连续卷。
    3. **守卫 a(结构校验)**:卷跨度不连续/重叠/漏章 → 退**固定窗口兜底**(每 ~10 章一卷)。
    4. **守卫 b(evidence 裁剪)**:每卷 evidence_chapters 裁到本卷跨度内。

    LLM 失败(抛异常 / 返空 / 解析不出)→ graceful 退固定窗口,不崩。

    Returns:
        卷层 ``[{chapter_span:[X,Y], title, theme, key_events, central_characters,
        evidence_chapters}]``(兜底切的额外带 ``approximate: True``);短书返 ``None``。
    """
    chapters = _sorted_chapters(spine)
    # 守卫 c:短书不建卷层
    if len(chapters) < min_chapters:
        logger.info("chapter_arcs: 章数 %d < %d,短书跳过卷层", len(chapters), min_chapters)
        return None

    compact = _compact_spine_text(spine)
    system = _VOLUME_SPLIT_INSTR + "\n\n=== 逐章骨架 ===\n" + compact

    volumes: list[dict[str, Any]] | None = None
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=system,
            tools=[],
            messages=[{"role": "user", "content": _USER_MSG}],
            max_tokens=max_tokens,
            cache_enabled=True,
        )
        volumes = _parse_volumes(llm_client.extract_final_text(resp))
    except Exception as exc:  # noqa: BLE001 — LLM/解析任何意外都退兜底,绝不崩
        logger.warning(
            "chapter_arcs: 卷切分调用抛 %s,退固定窗口兜底", type(exc).__name__
        )
        volumes = None

    # 守卫 a:结构不合规(含 LLM 失败/空)→ 退固定窗口兜底
    if not volumes or not _validate_spans(volumes, chapters):
        if volumes:
            logger.warning("chapter_arcs: 卷切分结构不合规(gap/overlap/漏章),退固定窗口兜底")
        return _fixed_window_arcs(chapters)

    # 守卫 b:归一 + evidence 裁到本卷跨度内
    return [_normalize_volume(v) for v in volumes]


__all__ = [
    "ARC_SCHEMA_VERSION",
    "build_arc_layer",
]
