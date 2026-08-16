"""逻辑梳理 + 可视化综合报告渲染器。

输入是各分析端点的 JSON 结果（narrative_curve / character_graph / timeline /
recap / concept_evolution / argument_structure / foreshadow_arcs / consistency_scan 等），
输出一份移动端优先、可分享的独立 HTML。纯函数，不调 LLM。
"""

from __future__ import annotations

import html
from typing import Any


def _esc(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _build_css() -> str:
    return """
:root{--cinnabar:#B03A2E;--cinnabar-deep:#8E2A20;--cinnabar-soft:#F5E6E3;--ink:#2B2622;--ink-2:#5A534C;--ink-3:#8A8278;--paper:#F7F2E7;--paper-card:#FFFCF5;--gold:#9C7A2E;--jade:#2E7D5B;--indigo:#3D5A99;--violet:#6A4E8E;--border:#E4DCCB;--radius:12px;--shadow:0 1px 3px rgba(43,38,34,.06),0 4px 16px rgba(43,38,34,.05)}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
[data-theme="dark"]{--paper:#201C18;--paper-card:#2A2520;--ink:#E8E0D2;--ink-2:#B5AC9E;--ink-3:#8A8278;--border:#3A342C;--cinnabar-soft:#3A2A26}
body{background:var(--paper);color:var(--ink);font-family:"Noto Serif SC","Songti SC","Source Han Serif SC",serif;line-height:1.7;font-size:16px}
.theme-toggle{position:fixed;bottom:16px;right:16px;width:44px;height:44px;border-radius:50%;border:1px solid var(--border);background:var(--paper-card);cursor:pointer;font-size:18px;box-shadow:var(--shadow);z-index:100}
.print-btn{position:fixed;bottom:16px;right:70px;height:44px;padding:0 16px;border-radius:22px;border:1px solid var(--border);background:var(--paper-card);cursor:pointer;font-size:14px;box-shadow:var(--shadow);z-index:100;font-family:"Noto Sans SC",sans-serif;color:var(--ink)}
.search-box{max-width:1200px;margin:0 auto 12px;padding:0}
.search-box input{width:100%;padding:10px 14px;border:1px solid var(--border);border-radius:10px;background:var(--paper-card);font-family:"Noto Sans SC",sans-serif;font-size:14px;color:var(--ink);outline:none}
.search-box input:focus{border-color:var(--cinnabar);box-shadow:0 0 0 3px var(--cinnabar-soft)}
@media print{.theme-toggle,.print-btn{display:none!important}.hero{padding:24px 16px}section{padding:16px}.card{box-shadow:none;break-inside:avoid}}
.hero{background:linear-gradient(135deg,var(--cinnabar-soft),transparent 65%);border-bottom:1px solid var(--border);padding:42px 20px 30px;text-align:center}
.hero h1{font-size:28px;color:var(--cinnabar);letter-spacing:.04em;margin-bottom:8px}
.hero .subtitle{color:var(--ink-2);font-size:14px;max-width:720px;margin:0 auto}
.hero .seal{display:inline-block;color:var(--cinnabar);border:2px solid var(--cinnabar);padding:2px 12px;border-radius:6px;font-weight:bold;font-size:13px;margin-top:12px;letter-spacing:.2em}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;max-width:1200px;margin:22px auto;padding:0 16px}
.stat{background:var(--paper-card);border:1px solid var(--border);border-radius:var(--radius);padding:16px 12px;box-shadow:var(--shadow);text-align:center}
.stat .num{font-size:26px;font-weight:bold;color:var(--cinnabar);font-family:"Noto Sans SC","PingFang SC",sans-serif}
.stat .label{font-size:12px;color:var(--ink-3);margin-top:4px;font-family:"Noto Sans SC","PingFang SC",sans-serif}
section{max-width:1200px;margin:0 auto;padding:28px 16px}
section h2{font-size:22px;color:var(--cinnabar);display:flex;align-items:center;gap:10px;margin-bottom:16px;padding-bottom:10px;border-bottom:2px solid var(--cinnabar)}
section h2 .no{font-family:"Noto Sans SC",sans-serif;font-size:12px;color:var(--ink-3);letter-spacing:.1em;border:1px solid var(--border);border-radius:6px;padding:2px 8px}
.card{background:var(--paper-card);border:1px solid var(--border);border-radius:var(--radius);padding:18px;margin:12px 0;box-shadow:var(--shadow)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.point{display:flex;gap:12px;padding:10px 0;border-bottom:1px dashed var(--border)}
.point:last-child{border-bottom:none}
.badge{flex-shrink:0;min-width:44px;text-align:center;background:var(--cinnabar-soft);color:var(--cinnabar);border-radius:8px;font-size:12px;font-weight:bold;padding:4px 6px;height:fit-content;font-family:"Noto Sans SC",sans-serif}
.quote{background:var(--cinnabar-soft);border-left:4px solid var(--cinnabar);padding:10px 14px;border-radius:0 8px 8px 0;margin:8px 0;font-size:14px}
.quote .seal{display:inline-block;color:var(--cinnabar);border:1px solid var(--cinnabar);padding:0 6px;border-radius:4px;font-size:11px;font-weight:bold;margin-right:6px}
.quote.unverified{background:rgba(138,130,120,.08);border-left-color:var(--ink-3)}
.quote.unverified .seal{color:var(--ink-3);border-color:var(--ink-3)}
.arc{display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-bottom:1px dashed var(--border)}
.arc .status{flex-shrink:0;font-size:12px;padding:2px 10px;border-radius:20px;font-family:"Noto Sans SC",sans-serif}
.arc .status.resolved{background:var(--jade);color:#fff}
.arc .status.dangling{background:var(--gold);color:#fff}
.claim{display:flex;gap:12px;padding:10px 0;border-bottom:1px dashed var(--border)}
.claim .no{flex-shrink:0;width:28px;height:28px;border-radius:50%;background:var(--cinnabar);color:#fff;display:flex;align-items:center;justify-content:center;font-size:13px;font-family:"Noto Sans SC",sans-serif}
.graph-wrap{background:var(--paper-card);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;box-shadow:var(--shadow)}
.graph-wrap svg{display:block;width:100%;height:auto}
.graph-wrap .dim{opacity:.12}
.graph-wrap .node-highlight{filter:drop-shadow(0 0 6px rgba(176,58,46,.55))}
.chart-wrap{background:var(--paper-card);border:1px solid var(--border);border-radius:var(--radius);padding:12px;overflow-x:auto}
.chart-wrap svg{min-width:680px;width:100%;height:auto}
.curve-detail{background:var(--paper-card);border:1px solid var(--border);border-radius:var(--radius);padding:14px;margin-top:12px;box-shadow:var(--shadow)}
.curve-detail h4{color:var(--cinnabar);margin-bottom:8px}
.curve-detail .event{font-size:14px;padding:6px 0;border-bottom:1px dashed var(--border)}
.verify-toggle{display:inline-block;margin-top:12px;padding:6px 14px;border-radius:20px;border:1px solid var(--jade);background:var(--paper-card);color:var(--jade);cursor:pointer;font-size:13px;font-family:"Noto Sans SC",sans-serif}
body.verified-only .quote.unverified{display:none}
footer{text-align:center;padding:32px 16px;color:var(--ink-3);font-size:13px;border-top:1px solid var(--border);margin-top:32px;font-family:"Noto Sans SC",sans-serif}
@media(max-width:640px){body{font-size:15px}.hero{padding:28px 14px 22px}.hero h1{font-size:22px}.hero .subtitle{font-size:13px}.stats{grid-template-columns:repeat(2,1fr);gap:10px;padding:0 12px}.stat{padding:12px 8px}.stat .num{font-size:22px}section{padding:20px 14px}section h2{font-size:18px}.card{padding:14px}.grid{grid-template-columns:1fr}.graph-wrap{overflow-x:auto;-webkit-overflow-scrolling:touch}.graph-wrap svg{min-width:600px}.theme-toggle{width:40px;height:40px;bottom:12px;right:12px;font-size:16px}.print-btn{height:38px;padding:0 12px;font-size:13px;bottom:12px;right:62px}}
"""


def _curve_svg(chapters: list[dict]) -> str:
    if not chapters:
        return '<p style="color:var(--ink-3)">暂无叙事曲线数据。</p>'
    n = len(chapters)
    W = max(680, n * 28 + 80)
    H = 240
    top = 30
    bottom = 210
    max_h = max((c.get("event_count", 0) + c.get("turning_count", 0) for c in chapters), default=1)
    max_h = max(max_h, 1)
    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" style="min-width:680px">']
    # grid lines
    for i in range(5):
        y = bottom - (bottom - top) * i / 4
        parts.append(f'<line x1="30" y1="{y:.1f}" x2="{W-20}" y2="{y:.1f}" stroke="var(--border)" stroke-dasharray="4 4"/>')
    for i, c in enumerate(chapters):
        ch = c.get("chapter", i + 1)
        x = 50 + i * (W - 80) / max(n - 1, 1)
        h = max(2, (c.get("event_count", 0) + c.get("turning_count", 0)) / max_h * (bottom - top))
        y = bottom - h
        color = "var(--cinnabar)" if c.get("is_turning") else "var(--gold)"
        parts.append(
            f'<rect class="curve-bar" data-curve="{ch}" x="{x-8:.1f}" y="{y:.1f}" width="16" height="{h:.1f}" rx="3" fill="{color}" opacity="0.85" style="cursor:pointer">'
            f'<title>第{ch}章 · {c.get("event_count",0)}事件</title></rect>'
        )
        if c.get("is_turning"):
            parts.append(f'<circle cx="{x:.1f}" cy="{max(top-4, y-6):.1f}" r="5" fill="var(--cinnabar)"><title>转折章</title></circle>')
    parts.append("</svg>")
    details = []
    for c in chapters[:60]:
        ch = c.get("chapter", 0)
        events = c.get("events", []) or []
        ev_html = "".join(
            f'<div class="event"><span class="seal" style="color:var(--cinnabar);border:1px solid var(--cinnabar);padding:0 5px;border-radius:4px;font-size:11px;margin-right:6px">{"鉴" if e.get("verified") else "研判"}</span>{_esc(e.get("text",""))}</div>'
            for e in events[:20]
        )
        if not ev_html:
            ev_html = '<div style="color:var(--ink-3);font-size:13px">本章暂无事件明细。</div>'
        details.append(
            f'<div class="curve-detail" id="curve-detail-{ch}" style="display:none">'
            f'<h4>第{ch}章 · 事件明细</h4>{ev_html}</div>'
        )
    return ('<div class="chart-wrap">' + "".join(parts) + "</div>"
            + "".join(details)
            + '<script>document.querySelectorAll(".curve-bar").forEach(bar=>{bar.addEventListener("click",()=>{const ch=bar.dataset.curve;document.querySelectorAll(".curve-detail").forEach(d=>d.style.display="none");const el=document.getElementById("curve-detail-"+ch);if(el)el.style.display="block";});});</script>')


def _graph_svg(graph: dict, limit: int = 36) -> str:
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if not nodes:
        return '<p style="color:var(--ink-3)">暂无关系图数据。</p>'
    # 按度取前 limit 个节点，并只保留这些节点之间的边
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.get("source", "")] = degree.get(e.get("source", ""), 0) + 1
        degree[e.get("target", "")] = degree.get(e.get("target", ""), 0) + 1
    top = sorted(nodes, key=lambda x: degree.get(x, 0), reverse=True)[:limit]
    top_set = set(top)
    keep_edges = [e for e in edges if e.get("source") in top_set and e.get("target") in top_set]
    n = len(top)
    if n == 0:
        return '<p style="color:var(--ink-3)">暂无关系图数据。</p>'
    W, H = 800, 640
    cx, cy = W / 2, H / 2
    r = min(W, H) / 2 - 70
    import math
    pos = {}
    for i, name in enumerate(top):
        ang = -90 + i * 360 / n
        rad = ang * math.pi / 180
        pos[name] = (cx + r * math.cos(rad), cy + r * math.sin(rad))
    parts = [f'<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    for e in keep_edges[:120]:
        a, b = pos.get(e.get("source")), pos.get(e.get("target"))
        if not a or not b:
            continue
        src = _esc(e.get("source", ""))
        tgt = _esc(e.get("target", ""))
        parts.append(
            f'<line class="graph-edge" data-a="{src}" data-b="{tgt}" x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" '
            f'stroke="var(--border)" stroke-width="{min(3, max(1, e.get("strength", 1)))}" opacity="0.6"/>'
        )
    for name in top:
        x, y = pos[name]
        safe = _esc(name)
        parts.append(
            f'<g class="graph-node" data-node="{safe}" style="cursor:pointer">'
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="16" fill="var(--cinnabar-soft)" stroke="var(--cinnabar)" stroke-width="1.5"/>'
            f'<text x="{x:.1f}" y="{y+4:.1f}" font-size="11" fill="var(--ink)" text-anchor="middle" font-family="sans-serif">{_esc(name[:6])}</text>'
            f'</g>'
        )
    parts.append("</svg>")
    legend = '<p style="font-size:13px;color:var(--ink-3);font-family:sans-serif;margin-top:8px">点击人物高亮其关系；再点空白处取消。</p>'
    script = (
        "<script>"
        "document.querySelectorAll('.graph-node').forEach(node=>{"
        "node.addEventListener('click',e=>{e.stopPropagation();const name=node.dataset.node;const active=node.classList.contains('active');"
        "document.querySelectorAll('.graph-node').forEach(n=>n.classList.remove('active','node-highlight'));"
        "document.querySelectorAll('.graph-edge').forEach(ed=>ed.classList.remove('dim'));"
        "if(!active){node.classList.add('active','node-highlight');"
        "document.querySelectorAll('.graph-node').forEach(n=>{if(n!==node)n.classList.add('dim');});"
        "document.querySelectorAll('.graph-edge').forEach(ed=>{const on=ed.dataset.a===name||ed.dataset.b===name;ed.classList.toggle('dim',!on);if(on)ed.style.stroke='var(--cinnabar)';else ed.style.stroke='';});"
        "}else{document.querySelectorAll('.graph-edge').forEach(ed=>ed.style.stroke='');}"
        "});});"
        "document.querySelector('.graph-wrap').addEventListener('click',e=>{if(e.target.tagName==='svg'){"
        "document.querySelectorAll('.graph-node').forEach(n=>n.classList.remove('active','node-highlight','dim'));"
        "document.querySelectorAll('.graph-edge').forEach(ed=>{ed.classList.remove('dim');ed.style.stroke='';});"
        "}});"
        "</script>"
    )
    return '<div class="graph-wrap">' + "".join(parts) + "</div>" + legend + script


def _timeline_html(timeline: dict) -> str:
    events = timeline.get("events", [])
    if not events:
        return '<p style="color:var(--ink-3)">暂无时间线数据。</p>'
    items = []
    for e in events[:80]:
        v = e.get("verified", False)
        items.append(
            f'<div class="point"><span class="badge">第{e.get("chapter","?")}章</span>'
            f'<div><div style="font-weight:bold">{_esc(e.get("event",""))}</div>'
            f'<div class="quote{" unverified" if not v else ""}"><span class="seal">{"鉴" if v else "研判"}</span>{_esc(e.get("evidence",""))}</div></div></div>'
        )
    return ('<div class="search-box"><input type="search" placeholder="🔍 搜索时间线…" data-filter="timeline"></div>'
            '<div class="card" data-list="timeline">' + "".join(items) + "</div>")


def _recap_html(recap: dict) -> str:
    points = recap.get("points", [])
    if not points:
        return '<p style="color:var(--ink-3)">暂无逻辑主线数据。</p>'
    items = []
    for p in points[:50]:
        v = p.get("verified", False)
        items.append(
            f'<div class="point"><span class="badge">{p.get("order","?")}</span>'
            f'<div><div style="font-weight:bold">{_esc(p.get("point",""))}</div>'
            f'<div class="quote{" unverified" if not v else ""}"><span class="seal">{"鉴" if v else "研判"}</span>{_esc(p.get("snippet",""))}</div></div></div>'
        )
    return ('<div class="search-box"><input type="search" placeholder="🔍 搜索逻辑主线…" data-filter="recap"></div>'
            '<div class="card" data-list="recap">' + "".join(items) + "</div>")


def _concept_html(concept: dict) -> str:
    stages = concept.get("stages", [])
    if not stages:
        return '<p style="color:var(--ink-3)">暂无概念演变数据。</p>'
    items = []
    for st in stages:
        v = st.get("verified", False)
        items.append(
            f'<div class="point"><span class="badge">第{st.get("chapter","?")}章</span>'
            f'<div><div style="font-weight:bold">{_esc(st.get("development",""))}</div>'
            f'<div class="quote{" unverified" if not v else ""}"><span class="seal">{"鉴" if v else "研判"}</span>{_esc(st.get("snippet",""))}</div></div></div>'
        )
    return f'<div class="card"><h3 style="color:var(--cinnabar);margin-bottom:10px">「{_esc(concept.get("concept",""))}」的演变</h3>{"".join(items)}</div>'

def _character_arc_html(arc: dict) -> str:
    characters = arc.get("characters", [])
    if not characters:
        return '<p style="color:var(--ink-3)">暂无角色弧线数据。</p>'
    # 按出场点数量/最高戏份取核心角色
    def _score(c: dict) -> int:
        pts = c.get("points", [])
        return max([p.get("presence", 0) for p in pts] or [0]) * 100 + len(pts)

    top = sorted(characters, key=_score, reverse=True)[:8]
    cards = []
    for c in top:
        name = c.get("name", "?")
        pts = c.get("points", [])
        if not pts:
            continue
        W, H = 320, 100
        pad = 8
        max_f = max([abs(p.get("fortune", 0)) for p in pts] + [1])
        xs = [pad + i * (W - 2 * pad) / max(len(pts) - 1, 1) for i in range(len(pts))]
        ys = [H / 2 - (p.get("fortune", 0) / max_f) * (H / 2 - 12) for p in pts]
        line = " ".join(f"{xs[i]:.1f},{ys[i]:.1f}" for i in range(len(pts)))
        points_html = ""
        for p in pts[-4:]:
            v = p.get("verified", False)
            note = p.get("note") or p.get("evidence") or ""
            points_html += (
                f'<div class="point"><span class="badge">第{p.get("chapter","?")}章</span>'
                f'<div><div style="font-size:14px">{_esc(note)}</div>'
                f'<div class="quote{" unverified" if not v else ""}" style="font-size:13px"><span class="seal">{"鉴" if v else "研判"}</span>{_esc(p.get("evidence",""))}</div></div></div>'
            )
        cards.append(
            f'<div class="card"><h3 style="color:var(--cinnabar);margin-bottom:6px">{_esc(name)}</h3>'
            f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto;background:var(--paper-card)">'
            f'<line x1="{pad}" y1="{H/2}" x2="{W-pad}" y2="{H/2}" stroke="var(--border)" stroke-dasharray="4 4"/>'
            f'<polyline points="{line}" fill="none" stroke="var(--cinnabar)" stroke-width="2"/>'
            f'</svg>'
            f'<div style="margin-top:8px">{points_html}</div></div>'
        )
    return '<div class="grid">' + "".join(cards) + "</div>"



def _argument_html(argument: dict) -> str:
    claims = argument.get("claims", [])
    if not claims:
        return '<p style="color:var(--ink-3)">暂无论证结构数据。</p>'
    items = []
    for c in claims[:60]:
        v = c.get("verified", False)
        items.append(
            f'<div class="claim"><span class="no">{c.get("order","?")}</span>'
            f'<div><div style="font-weight:bold">{_esc(c.get("claim",""))}</div>'
            f'<div class="quote{" unverified" if not v else ""}"><span class="seal">{"鉴" if v else "研判"}</span>{_esc(c.get("evidence",""))}</div></div></div>'
        )
    return ('<div class="search-box"><input type="search" placeholder="🔍 搜索论证结构…" data-filter="argument"></div>'
            '<div class="card" data-list="argument">' + "".join(items) + "</div>")


def _foreshadow_html(foreshadow: dict) -> str:
    arcs = foreshadow.get("arcs", [])
    if not arcs:
        return '<p style="color:var(--ink-3)">暂无伏笔弧数据。</p>'
    items = []
    for a in arcs[:40]:
        status = a.get("status", "dangling")
        cls = "resolved" if status == "resolved" else "dangling"
        label = "已回收" if status == "resolved" else "断弧"
        payoff = f"第{a.get('payoff_chapter','?')}章" if a.get("payoff_chapter") else "未回收"
        items.append(
            f'<div class="arc"><span class="status {cls}">{label}</span>'
            f'<div><div style="font-weight:bold">{_esc(a.get("description",""))}</div>'
            f'<div style="font-size:13px;color:var(--ink-2);margin-top:2px">埋点 第{a.get("setup_chapter","?")}章 → {payoff}</div>'
            f'<div class="quote">{_esc(a.get("setup_evidence",""))}</div>'
            f'{"<div class=quote>" + _esc(a.get("payoff_evidence","")) + "</div>" if a.get("payoff_evidence") else ""}'
            f'</div></div>'
        )
    return '<div class="card">' + "".join(items) + "</div>"

def _writing_technique_html(technique: dict) -> str:
    items = technique.get("techniques", [])
    if not items:
        return '<p style="color:var(--ink-3)">暂无写作技法数据。</p>'
    cards = []
    for t in items[:24]:
        v = t.get("verified", False)
        cards.append(
            f'<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px">'
            f'<h3 style="color:var(--cinnabar);font-size:16px">{_esc(t.get("technique",""))}</h3>'
            f'<span class="badge">第{t.get("chapter","?")}章</span></div>'
            f'<p style="font-size:14px;color:var(--ink-2);margin:6px 0">{_esc(t.get("how",""))}</p>'
            f'<div class="quote{" unverified" if not v else ""}"><span class="seal">{"鉴" if v else "研判"}</span>{_esc(t.get("snippet",""))}</div></div>'
        )
    return '<div class="grid">' + "".join(cards) + "</div>"


def _motif_html(motif: dict) -> str:
    occurrences = motif.get("occurrences", [])
    if not occurrences:
        return '<p style="color:var(--ink-3)">暂无母题追踪数据。</p>'
    items = []
    for o in occurrences[:40]:
        v = o.get("verified", False)
        items.append(
            f'<div class="point"><span class="badge">第{o.get("chapter","?")}章</span>'
            f'<div><div style="font-weight:bold">{_esc(o.get("manifestation",""))}</div>'
            f'<div class="quote{" unverified" if not v else ""}"><span class="seal">{"鉴" if v else "研判"}</span>{_esc(o.get("snippet",""))}</div></div></div>'
        )
    return f'<div class="card"><h3 style="color:var(--cinnabar);margin-bottom:10px">「{_esc(motif.get("motif",""))}」的母题追踪</h3>{"".join(items)}</div>'



def _chapters_overview_html(chapters: list[dict]) -> str:
    if not chapters:
        return '<p style="color:var(--ink-3)">暂无章节速览数据。</p>'
    shown = chapters[:200]
    items = []
    for c in shown:
        ch = c.get("chapter", "?")
        turn = " 🔺" if c.get("is_turning") else ""
        pov = c.get("pov") or ""
        items.append(
            f'<div class="card" style="padding:10px 12px;margin:6px 0">'
            f'<div style="display:flex;justify-content:space-between;gap:8px;align-items:center;flex-wrap:wrap">'
            f'<b>第{ch}章{turn}</b><span style="font-size:12px;color:var(--ink-3);font-family:sans-serif">{c.get("event_count",0)} 事件 · {_esc(pov)}</span></div>'
            f'</div>'
        )
    note = f'<p style="font-size:13px;color:var(--ink-3);font-family:sans-serif;margin-top:8px">共 {len(chapters)} 章，先展示前 {len(shown)} 章速览。</p>' if len(chapters) > len(shown) else ""
    return '<div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(220px,1fr))">' + "".join(items) + "</div>" + note


def _phases_html(phases: dict) -> str:
    items = phases.get("phases", [])
    if not items:
        return '<p style="color:var(--ink-3)">暂无情节阶段数据（论述型文档通常不切阶段）。</p>'
    cards = []
    for i, p in enumerate(items, 1):
        v = p.get("verified", False)
        cards.append(
            f'<div class="card"><div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">'
            f'<h3 style="color:var(--cinnabar);font-size:17px">{i}. {_esc(p.get("name",""))}</h3>'
            f'<span class="badge">第{p.get("start_ch","?")}-{p.get("end_ch","?")}章</span></div>'
            f'<p style="font-size:15px;margin:8px 0">{_esc(p.get("gist",""))}</p>'
            f'<div class="quote{" unverified" if not v else ""}"><span class="seal">{"鉴" if v else "研判"}</span>{_esc(p.get("evidence",""))}</div></div>'
        )
    return '<div class="grid">' + "".join(cards) + "</div>"


def _consistency_html(consistency: dict) -> str:
    contradictions = consistency.get("contradictions", [])
    if not contradictions:
        return '<p style="color:var(--ink-3)">暂无前后矛盾数据。</p>'
    items = []
    for c in contradictions[:20]:
        a = c.get("a", {})
        b = c.get("b", {})
        items.append(
            f'<div class="card"><h3 style="color:var(--indigo);font-size:16px;margin-bottom:8px">⚠️ {_esc(c.get("topic",""))}</h3>'
            f'<div style="font-size:14px;color:var(--ink-2);margin-bottom:8px">{_esc(c.get("conflict",""))}</div>'
            f'<div class="quote">第{a.get("chapter","?")}章 · {_esc(a.get("snippet",""))}</div>'
            f'<div class="quote">第{b.get("chapter","?")}章 · {_esc(b.get("snippet",""))}</div></div>'
        )
    return "".join(items)


def _verified_stats(data: dict) -> tuple[int, int]:
    total = 0
    verified = 0

    def _add(items: list[dict]) -> None:
        nonlocal total, verified
        for it in items:
            if not isinstance(it, dict):
                continue
            total += 1
            if it.get("verified"):
                verified += 1

    _add(data.get("recap", {}).get("points", []))
    _add(data.get("timeline", {}).get("events", []))
    _add(data.get("argument_structure", {}).get("claims", []))
    _add(data.get("concept_evolution", {}).get("stages", []))
    _add(data.get("writing_technique", {}).get("techniques", []))
    _add(data.get("motif_tracking", {}).get("occurrences", []))
    _add(data.get("narrative_phases", {}).get("phases", []))
    for c in data.get("character_arc", {}).get("characters", []):
        _add(c.get("points", []))
    return verified, total


def render_visual_report(data: dict) -> str:
    meta = data.get("meta", {})
    book = meta.get("book", "长文档")
    title = meta.get("title", f"《{book}》逻辑梳理与可视化")
    subtitle = meta.get("subtitle", "从几百万字里梳理主线、人物、事件、概念、论证与伏笔")
    curve = data.get("narrative_curve", {})
    graph = data.get("character_graph", {})
    timeline = data.get("timeline", {})
    recap = data.get("recap", {})
    concept = data.get("concept_evolution", {})
    argument = data.get("argument_structure", {})
    foreshadow = data.get("foreshadow_arcs", {})
    consistency = data.get("consistency_scan", {})
    character_arc = data.get("character_arc", {})
    writing_technique = data.get("writing_technique", {})
    motif = data.get("motif_tracking", {})
    phases = data.get("narrative_phases", {})
    verified_count, verified_total = _verified_stats(data)

    stats = [
        ("章", len(curve.get("chapters", [])) or len(timeline.get("events", []))),
        ("人物", len(graph.get("nodes", []))),
        ("事件", len(timeline.get("events", []))),
        ("主线要点", len(recap.get("points", []))),
        ("论证", len(argument.get("claims", []))),
        ("伏笔", len(foreshadow.get("arcs", []))),
        ("技法", len(writing_technique.get("techniques", []))),
        ("核验", f'{verified_count}/{verified_total}'),
    ]
    stat_html = "".join(
        f'<div class="stat"><div class="num">{_esc(v)}</div><div class="label">{_esc(k)}</div></div>'
        for k, v in stats
    )

    sections = f"""
<section id="recap"><h2><span class="no">壹</span>逻辑主线</h2>{_recap_html(recap)}</section>
<section id="phases"><h2><span class="no">贰</span>情节阶段</h2>{_phases_html(phases)}</section>
<section id="chapters"><h2><span class="no">叁</span>章节速览</h2>{_chapters_overview_html(curve.get("chapters", []))}</section>
<section id="curve"><h2><span class="no">肆</span>叙事曲线</h2>{_curve_svg(curve.get("chapters", []))}<p style="font-size:13px;color:var(--ink-3);font-family:sans-serif;margin-top:8px">纵轴 = 每章事件密度；朱砂点 = 转折章。</p></section>
<section id="graph"><h2><span class="no">伍</span>人物/概念关系图</h2>{_graph_svg(graph)}<p style="font-size:13px;color:var(--ink-3);font-family:sans-serif;margin-top:8px">按关联度取核心节点，边越粗关系越强。</p></section>
<section id="character-arc"><h2><span class="no">陆</span>核心人物弧线</h2>{_character_arc_html(character_arc)}</section>
<section id="timeline"><h2><span class="no">柒</span>事件时间线</h2>{_timeline_html(timeline)}</section>
<section id="concept"><h2><span class="no">捌</span>概念演变</h2>{_concept_html(concept)}</section>
<section id="argument"><h2><span class="no">玖</span>论证结构</h2>{_argument_html(argument)}</section>
<section id="writing"><h2><span class="no">拾</span>写作技法</h2>{_writing_technique_html(writing_technique)}</section>
<section id="motif"><h2><span class="no">拾壹</span>母题追踪</h2>{_motif_html(motif)}</section>
<section id="foreshadow"><h2><span class="no">拾贰</span>伏笔与回收</h2>{_foreshadow_html(foreshadow)}</section>
<section id="consistency"><h2><span class="no">拾叁</span>前后一致性</h2>{_consistency_html(consistency)}</section>
"""

    return f"""<!DOCTYPE html>
<html lang="zh" data-theme="light">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>书鉴 · {_esc(title)}</title>
<style>{_build_css()}</style>
</head>
<body>
<header class="hero"><h1>📜 {_esc(title)}</h1><p class="subtitle">{_esc(subtitle)}</p><span class="seal">书 鉴</span><br><button class="verify-toggle" onclick="document.body.classList.toggle('verified-only');this.textContent=document.body.classList.contains('verified-only')?'显示全部（含研判）':'只看已核验'">只看已核验</button></header>
<div class="stats">{stat_html}</div>
{sections}
<button class="print-btn" onclick="window.print()" title="导出/打印 PDF">🖨️ 导出</button>
<button class="theme-toggle" onclick="document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark'" title="切换主题">🌓</button>
<footer>BookScope · 逻辑梳理与可视化报告 · 所有引文均回原文核验 · 生成时间 {_esc(__import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M"))}</footer>
<script>
document.querySelectorAll('[data-filter]').forEach(input=>{{
  input.addEventListener('input',()=>{{
    const q=input.value.trim().toLowerCase();
    const list=document.querySelector('[data-list="'+input.dataset.filter+'"]');
    if(!list)return;
    list.querySelectorAll('.point,.claim,.arc').forEach(el=>{{
      el.style.display=(!q||(el.textContent||'').toLowerCase().includes(q))?'':'none';
    }});
  }});
}});
</script>
</body>
</html>"""
