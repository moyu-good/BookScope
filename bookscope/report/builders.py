"""书侧报告组装器——章脉 → 报告契约（doc 模式）。

输入：章脉记录列表（chapter_spine 产物，每条=一章，带 events/claims/evidence/
verified 等），输出：可直接喂 ``bookscope.report.service.render_report`` 的契约 dict。
纯函数，不碰缓存/文件/LLM——读缓存与组装分离（端点侧先 peek 章脉再调本函数）。
"""

from __future__ import annotations

import re

from typing import Any


def _chapter_title(rec: dict, idx: int) -> str:
    t = str(rec.get("title", "") or "").strip()
    return f"第{rec.get('chapter', idx + 1)}章 {t}".rstrip()


def _thesis(rec: dict) -> str:
    """章要点摘要：事件/主张各取前几条，拼成一句话。"""
    events = rec.get("events") or []
    claims = rec.get("claims") or []
    parts: list[str] = []
    for e in events[:2]:
        s = str(e).strip()
        if s and s not in parts:
            parts.append(s)
    for c in claims[:2]:
        s = str(c).strip()
        if s and s not in parts:
            parts.append(s)
    return "；".join(parts) if parts else "（本章无要点记录）"


def build_structure_report(chunks: list[dict], meta: dict) -> dict:
    """秒级零 LLM 结构报告：章节结构 + 每章首段（无章脉也能出）。

    给渐进交付当快速层：用户丢书进来立刻有东西看（结构版），深度章脉后台补建后
    同一入口自动升级成完整书鉴报告。纯本地、零 token、零 LLM。
    """
    # 按章分组，保序
    groups: dict[int, list[dict]] = {}
    for c in chunks:
        ch = c.get("chapter")
        if ch is None:
            ch = 0
        groups.setdefault(ch, []).append(c)

    nodes: list[dict[str, Any]] = []
    spines: dict[str, dict[str, Any]] = {}
    e1: dict[str, dict[str, Any]] = {}

    for ch in sorted(groups):
        ccs = groups[ch]
        slug = f"ch{ch}"
        text = "\n".join(str(c.get("text", "")) for c in ccs)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = ""
        if lines:
            # 首行像章头（第X章 / 序章 等）就当标题，正文从第二行起
            head = lines[0]
            if re.match(r"^(第[0-9零一二三四五六七八九十百千]+章|序章|楔子|引子|尾声)", head):
                title = head[:30]
                body = "\n".join(lines[1:])
            else:
                body = text
        else:
            body = ""
        # 首段摘要：取正文前 ~120 字（零 LLM）
        excerpt = re.sub(r"\s+", " ", body).strip()[:120]
        label = title or f"第{ch}章"
        nodes.append({"slug": slug, "label": label[:20], "stance": ""})
        spines[slug] = {
            "_title": label,
            "_slug": slug,
            "core_thesis": excerpt or "（本章暂无正文）",
            "theoretical_stance": {"label": "", "inference": False},
            "method": "",
            "key_citations": [],
        }
        e1[slug] = {"quotes": []}

    total = len(groups)
    return {
        "layout": "doc",
        "meta": {
            "title": meta["title"],
            "subtitle": meta.get(
                "subtitle", f"结构版 · 共 {total} 章 · 深度章脉后台构建中，可先看章节结构与首段"
            ),
            "seal": meta.get("seal", "书 鉴"),
            "nav_title": meta.get("nav_title", "书鉴 · 报告导航"),
            "unit_label": meta.get("unit_label", "章"),
            "generated_by": meta.get("generated_by", "书鉴 BookScope"),
        },
        "nodes": nodes,
        "edges": [],
        "concept_evolution": [],
        "disagreements": [],
        "narrative": meta.get(
            "narrative", f"结构版报告：全书 {total} 章。深度章脉（每章要点 + 引文核验）"
                          f"后台构建中，构建完成后同一入口自动升级为完整书鉴报告。"
        ),
        "spines": spines,
        "e1": e1,
        "quality": {"e2_mean": 0, "e3": None},
    }


def build_book_report(spine: list[dict], meta: dict) -> dict:
    """章脉 → doc 模式报告契约。

    spine: 章脉缓存记录列表（每章一条）。
    meta: 必含 title / subtitle / seal / nav_title / unit_label / generated_by，
          可选 extra_title（书名）。
    """
    nodes: list[dict[str, Any]] = []
    spines: dict[str, dict[str, Any]] = {}
    e1: dict[str, dict[str, Any]] = {}

    for idx, rec in enumerate(spine):
        slug = f"ch{rec.get('chapter', idx + 1)}"
        label = _chapter_title(rec, idx)
        stance = "主线" if rec.get("mainline") else ("支线" if rec.get("mainline") is False else "")
        nodes.append({"slug": slug, "label": label[:20], "stance": stance})
        evidence = str(rec.get("evidence", "") or "").strip()
        citations = [{"quote": evidence, "role": "章证据"}] if evidence else []
        verified = bool(rec.get("verified", False))
        spines[slug] = {
            "_title": label,
            "_slug": slug,
            "core_thesis": _thesis(rec),
            "theoretical_stance": {"label": stance or "—", "inference": False},
            "method": "",
            "key_citations": citations,
        }
        e1[slug] = {"quotes": [{"quote": evidence, "verified": verified}]} if evidence else {"quotes": []}

    total = len(spine)
    return {
        "layout": "doc",
        "meta": {
            "title": meta["title"],
            "subtitle": meta.get(
                "subtitle", f"{total} 章 · 章脉已建 · 每章要点锚回原文，核验通过盖「鉴」印"
            ),
            "seal": meta.get("seal", "书 鉴"),
            "nav_title": meta.get("nav_title", "书鉴 · 报告导航"),
            "unit_label": meta.get("unit_label", "章"),
            "generated_by": meta.get("generated_by", "书鉴 BookScope"),
        },
        "nodes": nodes,
        "edges": [],
        "concept_evolution": [],
        "disagreements": [],
        "narrative": meta.get("narrative", f"全书 {total} 章。以下为各章要点与证据脊（章脉产物），"
                                          f"每条证据经引文核验，通过盖「鉴」印。"),
        "spines": spines,
        "e1": e1,
        "quality": {"e2_mean": 0, "e3": None},
    }
