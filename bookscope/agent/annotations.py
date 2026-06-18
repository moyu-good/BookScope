"""精读注释层编排器（WP-annotated-reading）。

把已有的整本书结构化分析，按"原文位置"重新摆成行间注释——**不跑任何新 LLM 抽取**。
按用户选中的 layers 调已建的 generate_* 当数据源，收它们**已核验**的结论，每条映射成
一条注释贴回章内：

- ``foreshadow`` → :func:`generate_foreshadow_arcs`：每条伏笔弧映射成埋点处的一条注释；
  已回收的实弧带 target_chapter/target_snippet 指向回收处（跨章）。
- ``motif`` → :func:`generate_motif_tracking`：母题的每处复现一条注释。
- ``contradiction`` → :func:`generate_consistency_scan`：每条矛盾映射成 a 侧的一条注释，
  target_* 指向 b 侧（跨章对照）。
- ``entity`` → :func:`generate_entity_recall`：实体的每处出现一条注释。

evidence-first 红线（WP §4 / §42）：**verified=false 的一律不进**——阅读视图里直接不出现，
不是标灰。各数据源里：foreshadow 埋点必 verified（核不过整条已被滤），payoff 只有 resolved
才挂；motif / consistency 已 verify-filter；entity 保留全部含未核验，这里**显式只收 verified**。

章号一律用各数据源 verify 后纠偏过的真章号，注释不自报位置（WP §44）。

**不造跨端点缓存**（WP §性能）：v1 按选中 layer 现跑对应源，多 layer 会慢——已知 v1 限制。
契约同其它编排：成功返 dict，整体不抛（单个源失败记日志、跳过那一层）。
"""

from __future__ import annotations

import logging
from typing import Any

from bookscope.agent.citation_check import normalize_text
from bookscope.agent.consistency_scan import generate_consistency_scan
from bookscope.agent.entity_recall import generate_entity_recall
from bookscope.agent.foreshadow_arcs import generate_foreshadow_arcs
from bookscope.agent.motif_tracking import generate_motif_tracking

logger = logging.getLogger(__name__)

# 可选图层名——FE 分层开关与之一一对应。默认只开一两层（WP §53，治"糊一脸" + 控延迟）。
SUPPORTED_LAYERS: tuple[str, ...] = ("foreshadow", "motif", "contradiction", "entity")
DEFAULT_LAYERS: tuple[str, ...] = ("foreshadow", "contradiction")


def _foreshadow_annotations(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    session_id: str | None,
) -> list[dict[str, Any]]:
    """伏笔弧 → 注释。埋点处一条注释；resolved 实弧带 target_* 指向回收处。"""
    arcs = generate_foreshadow_arcs(
        full_text=full_text,
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        session_id=session_id,
    )
    if not arcs:  # None（失败）或 []（没挂得上原文的伏笔）——都没注释
        return []
    out: list[dict[str, Any]] = []
    for arc in arcs:
        # 埋点核不过的整条弧 BE 已滤掉，到这里 setup 必 verified；保险再判一次。
        if not arc.get("setup_verified"):
            continue
        resolved = arc.get("status") == "resolved" and arc.get("payoff_verified")
        out.append({
            "layer": "foreshadow",
            "type": "伏笔回收" if resolved else "断弧",
            "chapter": arc["setup_chapter"],
            "snippet": arc["setup_evidence"],
            "summary": arc.get("description", ""),
            # 跨章：已回收实弧指向回收处；断弧没回收，target 留空
            "target_chapter": arc["payoff_chapter"] if resolved else None,
            "target_snippet": arc["payoff_evidence"] if resolved else None,
        })
    return out


def _motif_annotations(
    *,
    motif: str,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    session_id: str | None,
) -> list[dict[str, Any]]:
    """母题复现 → 注释（每处一条，数据源已只返 verified）。"""
    motif = (motif or "").strip()
    if not motif:
        return []
    occ = generate_motif_tracking(
        motif=motif,
        full_text=full_text,
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        session_id=session_id,
    )
    if not occ:
        return []
    out: list[dict[str, Any]] = []
    for o in occ:
        if not o.get("verified"):  # 数据源已全 verified，显式守一道
            continue
        out.append({
            "layer": "motif",
            "type": f"母题「{motif}」",
            "chapter": o.get("chapter", 0),
            "snippet": o["snippet"],
            "summary": o.get("manifestation", ""),
            "target_chapter": None,
            "target_snippet": None,
        })
    return out


def _contradiction_annotations(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    session_id: str | None,
) -> list[dict[str, Any]]:
    """设定矛盾 → 注释。a 侧一条注释，target_* 指向 b 侧（两侧都已 verified）。"""
    contradictions = generate_consistency_scan(
        full_text=full_text,
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        session_id=session_id,
    )
    if not contradictions:
        return []
    out: list[dict[str, Any]] = []
    for c in contradictions:
        a = c.get("a") or {}
        b = c.get("b") or {}
        # 数据源已"两侧都命中才保留"，到这里 a/b 必 verified；保险再判。
        if not a.get("verified") or not b.get("verified"):
            continue
        out.append({
            "layer": "contradiction",
            "type": "设定矛盾",
            "chapter": a.get("chapter", 0),
            "snippet": a.get("snippet", ""),
            "summary": c.get("conflict", "") or c.get("topic", ""),
            "target_chapter": b.get("chapter", 0),
            "target_snippet": b.get("snippet", ""),
        })
    return out


def _entity_annotations(
    *,
    entity: str,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    session_id: str | None,
) -> list[dict[str, Any]]:
    """实体出现 → 注释（每处一条；数据源保留未核验，这里只收 verified）。"""
    entity = (entity or "").strip()
    if not entity:
        return []
    appearances = generate_entity_recall(
        entity=entity,
        full_text=full_text,
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        session_id=session_id,
    )
    if not appearances:
        return []
    out: list[dict[str, Any]] = []
    for ap in appearances:
        if not ap.get("verified"):  # entity_recall 保留未核验的，这里 evidence-first 滤掉
            continue
        out.append({
            "layer": "entity",
            "type": f"实体「{entity}」",
            "chapter": ap.get("chapter", 0),
            "snippet": ap["snippet"],
            "summary": ap.get("what", ""),
            "target_chapter": None,
            "target_snippet": None,
        })
    return out


def _chapter_texts_for(
    annotations: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """重建"有注释的那些章"的原文（含跨章注释指向的 target 章），按章号排序。

    阅读视图要显示原文；只返有注释牵涉到的章（含 target_chapter），有界、demo 友好，
    不把全书原文都灌给前端。同一章的 chunk 按 chunk_id 里的 r0 序号顺序拼接。
    """
    needed: set[int] = set()
    for a in annotations:
        ch = a.get("chapter")
        if isinstance(ch, int) and ch > 0:
            needed.add(ch)
        tch = a.get("target_chapter")
        if isinstance(tch, int) and tch > 0:
            needed.add(tch)
    if not needed:
        return []

    # 按 chapter 归拢 chunk，章内保持 chunks 原顺序（assembler 已按 r0 序号给出）。
    by_chapter: dict[int, list[str]] = {}
    for c in chunks:
        ch = c.get("chapter")
        if isinstance(ch, int) and ch in needed:
            by_chapter.setdefault(ch, []).append(c.get("text", ""))

    return [
        {"chapter": ch, "text": "".join(by_chapter.get(ch, []))}
        for ch in sorted(needed)
        if by_chapter.get(ch)  # 拿不到原文的章不返（章号纠偏后总能拿到）
    ]


def _tag_anchors(
    annotations: list[dict[str, Any]],
    chapters: list[dict[str, Any]],
) -> None:
    """给每条注释打 anchor：snippet 是它所属章原文的逐字子串就是 exact，否则 approx。

    判逐字用 citation_check 的 normalize_text（去空白 + 全半角标点归一）——和系统其它
    地方判"引用来自原文"同一把尺。所属章原文取不到时（理论上章号纠偏后总有）保守判
    approx。跨章注释同理对 target_snippet 在 target_chapter 原文里判 target_anchor。

    只有逐字可定位的（exact）才配在行间挂精确朱砂记号；转述类（approx）退批注栏，
    免得转述句乱挂章首冒充精确位置（WP §35）。
    """
    # 章原文归一化只做一遍（chapters 是 _chapter_texts_for 拼好的，已含 target 章）
    norm_by_chapter = {
        c["chapter"]: normalize_text(c.get("text", "")) for c in chapters
    }

    def _judge(snippet: str | None, chapter: object) -> str:
        if not snippet or not isinstance(chapter, int):
            return "approx"
        chap_text = norm_by_chapter.get(chapter)
        if not chap_text:
            return "approx"  # 拿不到所属章原文，保守判 approx
        return "exact" if normalize_text(snippet) in chap_text else "approx"

    for a in annotations:
        a["anchor"] = _judge(a.get("snippet"), a.get("chapter"))
        # 跨章注释：对 target_snippet 在 target_chapter 原文里判；无 target 留 None
        if a.get("target_snippet") and a.get("target_chapter") is not None:
            a["target_anchor"] = _judge(a.get("target_snippet"), a.get("target_chapter"))
        else:
            a["target_anchor"] = None


def generate_annotations(
    *,
    layers: list[str],
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    entity: str | None = None,
    motif: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """按选中的 layers 编排已有分析、收已核验结论映射成行间注释。

    **不跑新 LLM 抽取**——每个 layer 调对应的已建 generate_* 当数据源。verified=false 的
    结论一律不进（evidence-first，WP §42）。

    Args:
        layers: 想要的图层子集（``SUPPORTED_LAYERS`` 之一或多个）；未知名忽略。
        full_text: 整本书 cleaned 原文（喂数据源）。
        chunks: 全书 chunk（``chunk_id`` / ``chapter`` / ``text``）——给数据源核验 +
            提供章号 ground truth，也用来重建有注释那些章的原文。
        llm_client: duck-typed LLM client（透传给数据源；可被 _UsageRecorder 包一层记账）。
        model: 模型名。
        entity: ``entity`` 图层要查的实体名；该层选中而没给则跳过那一层。
        motif: ``motif`` 图层要查的母题名；该层选中而没给则跳过那一层。
        session_id: 透传给数据源（数据源各自关缓存防 poison）。

    Returns:
        ``{"annotations": [...], "chapters": [{"chapter", "text"}], "scanned": list[str]}``：

        - ``annotations``：按 ``(chapter, layer)`` 排序的注释列表，每条
          ``{layer, type, chapter, snippet, summary, target_chapter|None, target_snippet|None,
          anchor, target_anchor|None}``。``anchor`` = ``"exact"``（snippet 是所属章原文逐字
          子串，可挂精确行间记号）/ ``"approx"``（转述类，退批注栏不进行间，WP §35）；
          ``target_anchor`` 对跨章 ``target_snippet`` 同理判，无 target 为 ``None``。
        - ``chapters``：只含有注释牵涉到的章（含跨章 target 章）的原文，按章号排序。
        - ``scanned``：实际跑成功了的图层名列表（某层数据源抛错被跳过则不在其中）。
    """
    wanted = [ly for ly in layers if ly in SUPPORTED_LAYERS]
    annotations: list[dict[str, Any]] = []
    scanned: list[str] = []

    for layer in wanted:
        try:
            if layer == "foreshadow":
                part = _foreshadow_annotations(
                    full_text=full_text, chunks=chunks,
                    llm_client=llm_client, model=model, session_id=session_id,
                )
            elif layer == "motif":
                part = _motif_annotations(
                    motif=motif or "", full_text=full_text, chunks=chunks,
                    llm_client=llm_client, model=model, session_id=session_id,
                )
            elif layer == "contradiction":
                part = _contradiction_annotations(
                    full_text=full_text, chunks=chunks,
                    llm_client=llm_client, model=model, session_id=session_id,
                )
            else:  # entity
                part = _entity_annotations(
                    entity=entity or "", full_text=full_text, chunks=chunks,
                    llm_client=llm_client, model=model, session_id=session_id,
                )
        except Exception as exc:  # noqa: BLE001 — 单层失败不拖垮整次编排
            logger.warning(
                "annotations layer %s failed: %s: %s",
                layer, type(exc).__name__, exc,
            )
            continue
        annotations.extend(part)
        scanned.append(layer)

    # 按章号分组排序，同章内按图层名稳定排序（前端逐章渲染、章内逐条挂记号）。
    annotations.sort(key=lambda a: (a.get("chapter") or 0, a.get("layer", "")))
    chapters = _chapter_texts_for(annotations, chunks)
    # chapters 拼好后才有所属章原文，这时给每条注释打 anchor（exact / approx，WP §35）
    _tag_anchors(annotations, chapters)
    return {"annotations": annotations, "chapters": chapters, "scanned": scanned}


__all__ = [
    "DEFAULT_LAYERS",
    "SUPPORTED_LAYERS",
    "generate_annotations",
]
