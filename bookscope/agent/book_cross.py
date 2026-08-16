"""书×书 / 任意文档簇对照（P2 跨文本泛化）——学脉 crossdoc_reason 的题材无关版。

把「脊 + 一次全局推理」范式从论文簇 / 公文卷宗泛化到**任意长文档簇**：
- 每本书（或每个文档簇）先从自己的章脉提炼「书级主张/立场」（轻 LLM，喂章脉要点，
  不重读全文）——对应论文的 core_thesis、公文的文脉。
- 再把多本书的「书级主张」做一次跨文本全局推理，输出：
  nodes / edges（继承/反驳/补充/落地/检验）/ concept_evolution / disagreements / narrative
  ——结构与学脉 crossdoc.json 完全同构，直接喂 bookscope.report.service.render_report。
- 马恩差距就是两个 perspective 的对照；作者稿 vs 参考书同理；任意文档簇都行。

铁律（继承学脉试点）：
- 构建只喂「轻量脊」（章脉要点 / 主张），不重读全文
- 证据锚回真实单元（章号），锚不到丢
- 推断标「研判」，不盖「鉴」印（跨文本关系是推断，不是原文核验）
"""

from __future__ import annotations

import json
from typing import Any

# 跨文本关系五类（与报告渲染器 REL_META 同源）
RELATIONS = ["继承", "反驳", "补充", "落地", "检验"]

_PERSPECTIVE_PROMPT = """你是一位长文本分析专家。给你一本书（或一部长文档）的逐章要点（章号 + 每章关键事件/主张），请提炼这本书的「书级观点骨架」——不逐章复述，而是站在全书高度总结它真正想表达的东西。

**输出要求（严格遵守）**：只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块。顶层键必须且只有：
1. "title"：书名/文档名
2. "summary"：一句话全书主旨（80 字内）
3. "stance"：这本书的整体立场标签（如 现实主义/理想主义/实证/批判/叙事，2-6 字）
4. "claims"：数组，5-8 条全书核心主张/立场，每项 {"claim": "主张（30 字内）", "chapter": 代表章号, "kind": "主题|人物|方法|价值"} 

只依据提供的章脉要点，不编造；每一条 claim 都要能锚回代表章号。"""

_REASON_PROMPT = """你是一位跨文本对照分析专家。给你多本书（或长文档）的「书级观点骨架」（每本：书名/主旨/立场/核心主张），请做一次跨文本全局推理，理清它们之间的逻辑关系。

**输出要求（严格遵守）**：只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块。顶层键必须且只有这五个：
1. "nodes"：数组，每项 {"slug": "书名slug", "label": "短名", "stance": "一句话立场"}
2. "edges"：数组，每项 {"from": "slug", "to": "slug", "relation": "继承|反驳|补充|落地|检验", "rationale": "依据（锚到具体主张）"}
3. "concept_evolution"：数组，每项 {"concept": "概念名", "stages": [{"paper": "slug", "stage": "阶段名", "claim": "主张", "evidence": "锚到的主张原文"}]}
4. "disagreements"：数组，每项 {"question": "问题", "sides": [{"paper": "slug", "stance": "立场", "evidence": "锚到的主张"}]}
5. "narrative"：一段 200 字内的总体逻辑说明

关系定义：
- 继承：后文沿用/发展前文的主张
- 反驳：后文明确反对/推翻前文的主张
- 补充：后文提供并行机制或修正
- 落地：后文把前文的抽象主张具体化/实证化
- 检验：后文用数据/证据明确检验前文的假设

只依据提供的观点骨架，不编造；edges 的 from/to 必须真实存在于 nodes。"""


def _clean(text: Any) -> str:
    """清洗输入：去掉引号/特殊字符（DeepSeek 对嵌套引号输入偶发空响应）。"""
    if not text:
        return ""
    return (
        str(text)
        .replace('"', " ")
        .replace("'", " ")
        .replace("\u201c", " ").replace("\u201d", " ")
        .replace("\u2018", " ").replace("\u2019", " ")
        .replace("\n", " ")
        .replace("\\", " ")
        .strip()
    )


def _compact_spine(spine: list[dict], max_points_per_chapter: int = 3) -> str:
    """把章脉压成紧凑文本（每章取前几个事件/主张），喂给提炼 LLM。"""
    lines: list[str] = []
    for rec in sorted(spine, key=lambda r: r.get("chapter", 0)):
        ch = rec.get("chapter", "?")
        points = []
        for ev in (rec.get("events") or [])[:max_points_per_chapter]:
            s = str(ev).strip()
            if s and s not in points:
                points.append(s)
        for cl in (rec.get("claims") or [])[:max_points_per_chapter]:
            s = str(cl).strip()
            if s and s not in points:
                points.append(s)
        if points:
            lines.append(f"第{ch}章：{'；'.join(points)}")
    return "\n".join(lines)


def _ask_json(client: Any, model: str, system: str, user: str, max_tokens: int = 2000) -> dict:
    """调一次 LLM 并解析 JSON；失败返回空 dict（调用方降级）。"""
    resp = client._client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.2,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content or ""
    for _ in range(3):
        if content:
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass
        resp = client._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content or ""
    return {}


def build_book_perspective(
    *,
    spine: list[dict],
    book_title: str,
    slug: str,
    llm_client: Any,
    model: str,
) -> dict:
    """从一本的章脉提炼「书级观点骨架」（轻 LLM，喂章脉要点）。

    返回: {"title", "slug", "summary", "stance", "claims": [...]}。
    提炼失败时返回带 summary 的空骨架（不 break 对照）。
    """
    compact = _compact_spine(spine)
    user = f"【{book_title}】\n{compact}"
    data = _ask_json(llm_client, model, _PERSPECTIVE_PROMPT, user)
    if not data or not isinstance(data, dict):
        return {"title": book_title, "slug": slug, "summary": "", "stance": "", "claims": []}
    data.setdefault("title", book_title)
    data.setdefault("slug", slug)
    data.setdefault("summary", "")
    data.setdefault("stance", "")
    data.setdefault("claims", [])
    return data


def cross_book_reason(
    *,
    perspectives: list[dict],
    llm_client: Any,
    model: str,
) -> dict:
    """多本书对照推理：输出 nodes/edges/concept_evolution/disagreements/narrative。

    结构与学脉 crossdoc.json 同构，直接可喂报告渲染器。失败返回空结构。
    """
    if len(perspectives) < 2:
        return {"nodes": [], "edges": [], "concept_evolution": [], "disagreements": [], "narrative": ""}

    # 组装输入：每本书的 title/stance/claims 紧凑文本
    blocks = []
    for p in perspectives:
        claims = "；".join(f"{c.get('claim','')}(第{c.get('chapter','?')}章)" for c in p.get("claims", [])[:8])
        blocks.append(f"《{p.get('title','')}》立场：{p.get('stance','')}；主旨：{p.get('summary','')}；主张：{claims}")
    user = "\n\n".join(blocks)
    data = _ask_json(llm_client, model, _REASON_PROMPT, user, max_tokens=3000)
    if not data or not isinstance(data, dict):
        return {"nodes": [], "edges": [], "concept_evolution": [], "disagreements": [], "narrative": ""}

    return _sanitize_reason(data, perspectives)


def _sanitize_reason(data: dict, perspectives: list[dict]) -> dict:
    """锚定校验：nodes 的 slug 必须来自输入 perspectives；edges 的 from/to 必须存在。"""
    valid_slugs = {p.get("slug") for p in perspectives}
    nodes = [n for n in data.get("nodes", []) if n.get("slug") in valid_slugs]
    valid = {n["slug"] for n in nodes}
    edges = [
        e for e in data.get("edges", [])
        if e.get("from") in valid and e.get("to") in valid and e.get("relation") in RELATIONS
    ]
    return {
        "nodes": nodes,
        "edges": edges,
        "concept_evolution": data.get("concept_evolution", []),
        "disagreements": data.get("disagreements", []),
        "narrative": data.get("narrative", ""),
    }


def build_cross_book_report_input(
    *,
    perspectives: list[dict],
    reason: dict,
    meta: dict,
) -> dict:
    """把多本书 perspective + 对照推理结果组装成报告契约（crossdoc 模式）。

    每本书 = 一个"证据脊"（summary/claims 当核心内容），渲染器直接复用。
    """
    spines = {}
    for p in perspectives:
        slug = p.get("slug", "")
        claims = p.get("claims", [])
        citations = [
            {"quote": c.get("claim", ""), "role": f"第{c.get('chapter','?')}章 · {c.get('kind','')}"}
            for c in claims if c.get("claim")
        ]
        spines[slug] = {
            "_title": p.get("title", slug),
            "_slug": slug,
            "core_thesis": p.get("summary", ""),
            "theoretical_stance": {"label": p.get("stance", ""), "inference": True},
            "method": "",
            "key_citations": citations,
        }
    # 跨文本关系是推断（LLM 对照），不是原文核验——全部标「研判」，不盖「鉴」
    e1 = {slug: {"quotes": [{"quote": c.get("claim", ""), "verified": False} for c in p.get("claims", []) if c.get("claim")]} for slug, p in zip([x.get("slug","") for x in perspectives], perspectives)}
    return {
        "layout": "crossdoc",
        "meta": {
            "title": meta.get("title", "跨文本对照报告"),
            "subtitle": meta.get("subtitle", f"{len(perspectives)} 份文档 · 跨文本逻辑对照 · 关系为研判，锚回各书章号"),
            "seal": meta.get("seal", "书 鉴"),
            "nav_title": meta.get("nav_title", "对照 · 报告导航"),
            "unit_label": meta.get("unit_label", "份"),
            "generated_by": meta.get("generated_by", "书鉴 BookScope"),
        },
        "nodes": reason.get("nodes", []),
        "edges": reason.get("edges", []),
        "concept_evolution": reason.get("concept_evolution", []),
        "disagreements": reason.get("disagreements", []),
        "narrative": reason.get("narrative", ""),
        "spines": spines,
        "e1": e1,
        "quality": {"e2_mean": 0, "e3": None},
    }
