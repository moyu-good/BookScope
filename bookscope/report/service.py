"""书鉴报告引擎（report service）——BookScope 主轴交付层。

把「脊 + 视图数据」渲染成书鉴 / 批奏折风格的互动 HTML 报告。
纯函数：输入 = 报告契约 dict，输出 = HTML 字符串。不碰文件系统、不依赖试点路径、
不调 LLM——任何题材（书 / 公文 / 会议 / 论文簇 / 跨文本对照）都可复用。

起源：academic-vertical 试点 build_report_v2.py（2026-08-15 验证的书鉴渲染），
P0 阶段从试点提为引擎能力。设计稿：docs/internal/academic-vertical/design/WP-report-engine.md。

契约（report input）：
{
  "meta": {
    "title": str,            # 报告大标题
    "subtitle": str,         # 副标题
    "seal": str,             # 印章文字（书鉴 / 批奏折 / …）
    "nav_title": str,        # 侧边导航标题
    "unit_label": str,       # 证据脊计数单位（篇 / 章 / 份）
    "generated_by": str,     # 页脚来源说明
  },
  "nodes": [{"slug", "label", "stance"}],          # 关系图节点
  "edges": [{"from", "to", "relation", "rationale"}],  # 关系边（继承/反驳/补充/落地/检验）
  "concept_evolution": [{"concept", "stages": [{"stage","claim","paper","evidence"}]}],
  "disagreements": [{"question", "sides": [{"paper","stance","evidence"}]}],
  "narrative": str,                                # 总体逻辑
  "spines": {slug: {"_title","core_thesis","theoretical_stance":{"label","inference"},
                     "method","key_citations":[{"quote","role"}]}},
  "e1": {slug: {"quotes": [{"quote","verified"}]}},  # E1 引文核验结果
  "quality": {"e2_mean": float, "e3": {"correct": int, "total": int}},  # 门禁状态（可选）
  "ask": {"question", "answer", "sources": []},      # 预渲染追问（可选）
}
"""

from __future__ import annotations

import html
from typing import Any

# ---- 设计系统 token（书鉴美学 × 现代）----
TOKENS = {
    "cinnabar": "#B03A2E",      # 朱砂（主色）
    "cinnabar-deep": "#8E2A20",  # 朱砂深（hover）
    "cinnabar-soft": "#F5E6E3",  # 朱砂浅（背景）
    "ink": "#2B2622",            # 墨（正文）
    "ink-2": "#5A534C",          # 墨次（次要文本）
    "ink-3": "#8A8278",          # 墨淡（弱文本）
    "paper": "#F7F2E7",          # 宣纸（页面底）
    "paper-card": "#FFFCF5",     # 宣纸亮（卡片）
    "gold": "#9C7A2E",           # 描金（强调）
    "jade": "#2E7D5B",           # 玉（成功/继承）
    "indigo": "#3D5A99",         # 靛蓝（反驳）
    "violet": "#6A4E8E",         # 紫（检验）
    "border": "#E4DCCB",         # 边框
    "font-serif": '"Noto Serif SC","Songti SC","Source Han Serif SC",serif',
    "font-sans": '"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif',
    "radius": "10px",
    "shadow": "0 1px 3px rgba(43,38,34,.06), 0 4px 16px rgba(43,38,34,.05)",
}

# 跨文本关系五类（通用骨架：论文簇、书×书对照、公文卷宗共用）
REL_META = {
    "继承": {"color": TOKENS["jade"], "icon": "🧩", "label": "继承"},
    "反驳": {"color": TOKENS["indigo"], "icon": "⚔️", "label": "反驳"},
    "补充": {"color": TOKENS["cinnabar"], "icon": "➕", "label": "补充"},
    "落地": {"color": TOKENS["gold"], "icon": "🏗️", "label": "落地"},
    "检验": {"color": TOKENS["violet"], "icon": "🔬", "label": "检验"},
}

# 报告契约必填字段（校验用）
REQUIRED_META = ("title", "subtitle", "seal", "nav_title", "unit_label", "generated_by")
REQUIRED_TOP = ("meta", "nodes", "edges", "spines", "narrative")


def esc(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def build_css() -> str:
    return f""":root{{
  --cinnabar:{TOKENS['cinnabar']}; --cinnabar-deep:{TOKENS['cinnabar-deep']}; --cinnabar-soft:{TOKENS['cinnabar-soft']};
  --ink:{TOKENS['ink']}; --ink-2:{TOKENS['ink-2']}; --ink-3:{TOKENS['ink-3']};
  --paper:{TOKENS['paper']}; --paper-card:{TOKENS['paper-card']}; --gold:{TOKENS['gold']};
  --jade:{TOKENS['jade']}; --indigo:{TOKENS['indigo']}; --violet:{TOKENS['violet']}; --border:{TOKENS['border']};
  --font-serif:{TOKENS['font-serif']}; --font-sans:{TOKENS['font-sans']};
  --radius:{TOKENS['radius']}; --shadow:{TOKENS['shadow']};
}}
*{{box-sizing:border-box;margin:0;padding:0}}
html{{scroll-behavior:smooth}}
body{{background:var(--paper);color:var(--ink);font-family:var(--font-serif);line-height:1.75;font-size:16px}}
[data-theme="dark"]{{--paper:#201C18;--paper-card:#2A2520;--ink:#E8E0D2;--ink-2:#B5AC9E;--ink-3:#8A8278;--border:#3A342C;--cinnabar-soft:#3A2A26}}

/* 布局 */
.layout{{display:grid;grid-template-columns:220px 1fr;max-width:1280px;margin:0 auto;gap:32px;padding:24px}}
main{{min-width:0}}
@media(max-width:960px){{.layout{{grid-template-columns:1fr}}.sidebar{{display:none}}}}

/* 侧边导航 */
.sidebar{{position:sticky;top:24px;height:calc(100vh - 48px);overflow-y:auto;padding:20px;background:var(--paper-card);border:1px solid var(--border);border-radius:var(--radius);font-family:var(--font-sans)}}
.sidebar h4{{font-size:12px;letter-spacing:.12em;color:var(--ink-3);text-transform:uppercase;margin-bottom:12px}}
.sidebar a{{display:block;padding:7px 10px;margin:2px 0;color:var(--ink-2);text-decoration:none;border-radius:6px;font-size:14px;transition:all .15s}}
.sidebar a:hover{{background:var(--cinnabar-soft);color:var(--cinnabar)}}
.sidebar .count{{float:right;color:var(--ink-3);font-size:12px}}

/* 头部 */
.hero{{background:linear-gradient(135deg,var(--cinnabar-soft),transparent 60%);border-bottom:1px solid var(--border);padding:48px 24px 32px;text-align:center}}
.hero h1{{font-size:34px;color:var(--cinnabar);letter-spacing:.04em;margin-bottom:8px}}
.hero .subtitle{{color:var(--ink-2);font-size:15px;max-width:720px;margin:0 auto}}
.hero .seal{{display:inline-block;color:var(--cinnabar);border:2px solid var(--cinnabar);padding:2px 12px;border-radius:6px;font-weight:bold;font-size:14px;margin-top:12px;letter-spacing:.2em}}

/* 摘要卡 */
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px;max-width:1280px;margin:24px auto;padding:0 24px}}
.stat{{background:var(--paper-card);border:1px solid var(--border);border-radius:var(--radius);padding:18px 16px;box-shadow:var(--shadow);text-align:center}}
.stat .num{{font-size:28px;font-weight:bold;color:var(--cinnabar);font-family:var(--font-sans)}}
.stat .label{{font-size:13px;color:var(--ink-3);margin-top:4px;font-family:var(--font-sans)}}
.stat.pass .num{{color:var(--jade)}}
.stat.warn .num{{color:var(--gold)}}

/* 章节 */
section{{max-width:1280px;margin:0 auto;padding:32px 24px}}
section h2{{font-size:24px;color:var(--cinnabar);display:flex;align-items:center;gap:10px;margin-bottom:20px;padding-bottom:10px;border-bottom:2px solid var(--cinnabar)}}
section h2 .no{{font-family:var(--font-sans);font-size:13px;color:var(--ink-3);letter-spacing:.1em;border:1px solid var(--border);border-radius:6px;padding:2px 8px}}

.card{{background:var(--paper-card);border:1px solid var(--border);border-radius:var(--radius);padding:22px;margin:14px 0;box-shadow:var(--shadow)}}

/* 关系图 */
.graph-wrap{{position:relative;border:1px solid var(--border);border-radius:var(--radius);background:var(--paper-card);overflow:hidden}}
.graph-toolbar{{display:flex;gap:8px;padding:10px 14px;border-bottom:1px solid var(--border);flex-wrap:wrap;align-items:center;font-family:var(--font-sans)}}
.graph-toolbar .hint{{font-size:12px;color:var(--ink-3);margin-left:auto}}
.chip{{padding:4px 12px;border-radius:20px;font-size:12px;cursor:pointer;border:1px solid var(--border);background:var(--paper);transition:all .15s;font-family:var(--font-sans)}}
.chip.active{{background:var(--cinnabar);color:#fff;border-color:var(--cinnabar)}}
.chip[data-rel="继承"].active{{background:var(--jade);border-color:var(--jade)}}
.chip[data-rel="反驳"].active{{background:var(--indigo);border-color:var(--indigo)}}
.chip[data-rel="补充"].active{{background:var(--cinnabar);border-color:var(--cinnabar)}}
.chip[data-rel="落地"].active{{background:var(--gold);border-color:var(--gold)}}
.chip[data-rel="检验"].active{{background:var(--violet);border-color:var(--violet)}}
#graph-svg{{display:block;width:100%;cursor:grab}}
#graph-svg:active{{cursor:grabbing}}
#graph-svg text{{user-select:none;pointer-events:none}}

/* 引文 */
.quote{{background:var(--cinnabar-soft);border-left:4px solid var(--cinnabar);padding:12px 16px;border-radius:0 8px 8px 0;margin:10px 0}}
.quote .seal-mark{{display:inline-block;color:var(--cinnabar);border:1px solid var(--cinnabar);padding:0 7px;border-radius:4px;font-size:11px;font-weight:bold;margin-right:8px;vertical-align:1px}}
.quote.unverified{{background:rgba(138,130,120,.08);border-left-color:var(--ink-3)}}
.quote.unverified .seal-mark{{color:var(--ink-3);border-color:var(--ink-3)}}
.quote .role{{font-size:13px;color:var(--ink-3);margin-top:4px;font-family:var(--font-sans)}}

/* 证据脊折叠 */
details.spine{{background:var(--paper-card);border:1px solid var(--border);border-radius:var(--radius);margin:10px 0;box-shadow:var(--shadow);overflow:hidden}}
details.spine summary{{padding:16px 20px;cursor:pointer;font-weight:bold;display:flex;align-items:center;gap:12px;list-style:none}}
details.spine summary::-webkit-details-marker{{display:none}}
details.spine summary::before{{content:"▸";color:var(--cinnabar);transition:transform .2s}}
details.spine[open] summary::before{{transform:rotate(90deg)}}
details.spine summary .meta-line{{font-size:12px;color:var(--ink-3);font-weight:normal;font-family:var(--font-sans);margin-left:auto}}
details.spine .body{{padding:0 20px 20px}}
.tag{{display:inline-block;font-size:11px;padding:2px 10px;border-radius:20px;font-family:var(--font-sans);margin-right:6px;border:1px solid var(--border)}}
.tag.stance{{background:var(--cinnabar-soft);color:var(--cinnabar);border-color:transparent}}

/* 分歧 */
.dispute{{background:var(--paper-card);border:1px solid var(--border);border-left:4px solid var(--indigo);border-radius:var(--radius);padding:18px 20px;margin:12px 0;box-shadow:var(--shadow)}}
.dispute h3{{color:var(--indigo);font-size:17px;margin-bottom:10px}}
.side{{margin:8px 0 8px 14px;padding-left:12px;border-left:2px solid var(--border)}}
.side b{{color:var(--ink)}}

/* 概念演变 */
.evolution-stage{{display:grid;grid-template-columns:80px 1fr;gap:12px;padding:12px 0;border-bottom:1px dashed var(--border);align-items:start}}
.evolution-stage:last-child{{border-bottom:none}}
.evolution-stage .stage-label{{font-size:12px;font-weight:bold;color:var(--cinnabar);background:var(--cinnabar-soft);border-radius:6px;padding:4px 8px;text-align:center;font-family:var(--font-sans)}}
.evolution-stage .claim{{font-size:15px}}
.evolution-stage .paper{{font-size:12px;color:var(--ink-3);font-family:var(--font-sans)}}

/* 搜索 */
.search-box{{max-width:1280px;margin:0 auto;padding:0 24px}}
.search-box input{{width:100%;padding:12px 16px;border:1px solid var(--border);border-radius:var(--radius);background:var(--paper-card);font-family:var(--font-sans);font-size:14px;color:var(--ink);outline:none}}
.search-box input:focus{{border-color:var(--cinnabar);box-shadow:0 0 0 3px var(--cinnabar-soft)}}

/* 页脚 */
footer{{text-align:center;padding:40px 24px;color:var(--ink-3);font-size:13px;border-top:1px solid var(--border);margin-top:40px;font-family:var(--font-sans)}}

/* 暗色切换 */
.theme-toggle{{position:fixed;bottom:24px;right:24px;width:48px;height:48px;border-radius:50%;border:1px solid var(--border);background:var(--paper-card);cursor:pointer;font-size:20px;box-shadow:var(--shadow);z-index:100}}
"""


def build_graph_html(cd: dict) -> str:
    """可交互 SVG 关系图（拖拽 + 缩放 + 筛选）。"""
    nodes = cd.get("nodes", [])
    edges = cd.get("edges", [])
    # 分层布局：按节点序排 3 列
    cols = 3
    rows = (len(nodes) + cols - 1) // cols
    W, H = 900, 120 + rows * 150
    x_step, y_step = 280, 150
    pos = {}
    for i, nd in enumerate(nodes):
        c, r = i % cols, i // cols
        pos[nd["slug"]] = (140 + c * x_step, 90 + r * y_step)

    parts = [f'<svg id="graph-svg" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    for e in edges:
        if e["from"] not in pos or e["to"] not in pos:
            continue
        x1, y1 = pos[e["from"]]
        x2, y2 = pos[e["to"]]
        meta = REL_META.get(e.get("relation", ""), {})
        color = meta.get("color", TOKENS["ink-3"])
        rel = e.get("relation", "")
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 - 26
        parts.append(
            f'<g class="edge" data-rel="{esc(rel)}" opacity="0.8">'
            f'<path d="M{x1},{y1} Q{mx},{my + 26} {x2},{y2}" fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="6 3"/>'
            f'<circle cx="{mx}" cy="{my + 26}" r="3" fill="{color}"/>'
            f'<text x="{mx}" y="{my}" font-size="11" fill="{color}" text-anchor="middle" font-family="sans-serif">{esc(rel)}</text>'
            f'</g>'
        )
    for nd in nodes:
        x, y = pos[nd["slug"]]
        parts.append(
            f'<g class="node">'
            f'<rect x="{x - 108}" y="{y - 30}" width="216" height="60" rx="10" fill="var(--paper-card)" stroke="var(--cinnabar)" stroke-width="1.5"/>'
            f'<text x="{x}" y="{y - 6}" font-size="13" fill="var(--ink)" text-anchor="middle" font-weight="bold" font-family="serif">{esc(nd.get("label",""))}</text>'
            f'<text x="{x}" y="{y + 14}" font-size="10" fill="var(--ink-3)" text-anchor="middle" font-family="sans-serif">{esc((nd.get("stance","") or "")[:26])}</text>'
            f'</g>'
        )
    parts.append("</svg>")
    svg = "\n".join(parts)

    chips = "".join(
        f'<button class="chip active" data-rel="{esc(rel)}">{meta.get("icon","")} {esc(rel)}</button>'
        for rel, meta in REL_META.items()
    )
    return f"""<div class="graph-wrap">
  <div class="graph-toolbar">{chips}<span class="hint">拖拽平移 · 滚轮缩放 · 点标签筛选</span></div>
  {svg}
</div>
<script>
(function(){{
  const svg=document.getElementById('graph-svg');
  let dragging=false, sx=0, sy=0, tx=0, ty=0, scale=1;
  const inner=svg.querySelector('g')||svg;
  svg.addEventListener('mousedown',e=>{{dragging=true;sx=e.clientX;sy=e.clientY;}});
  window.addEventListener('mousemove',e=>{{
    if(!dragging)return;const dx=e.clientX-sx,dy=e.clientY-sy;tx+=dx;sy=e.clientY;ty+=dy;sx=e.clientX;
    svg.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{scale}})`;
    svg.style.transformOrigin='center';
  }});
  window.addEventListener('mouseup',()=>dragging=false);
  svg.addEventListener('wheel',e=>{{e.preventDefault();scale=Math.max(.5,Math.min(3,scale+(e.deltaY<0?.1:-.1)));svg.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{scale}})`;}},{{passive:false}});
  document.querySelectorAll('.chip').forEach(chip=>{{
    chip.addEventListener('click',()=>{{
      const rel=chip.dataset.rel,on=chip.classList.toggle('active');
      document.querySelectorAll('.edge').forEach(ed=>{{
        const show=on?ed.dataset.rel===rel:true;
        ed.style.display=show?'':'none';
      }});
    }});
  }});
}})();
</script>"""


def build_spines_html(spines: dict, e1: dict) -> tuple[str, int, int]:
    """证据脊列表（带 E1 核验状态）。"""
    items = []
    total_v = total_q = 0
    for slug in sorted(spines):
        s = spines[slug]
        e1_slug = e1.get(slug, {})
        vmap = {c.get("quote", ""): c.get("verified", False) for c in e1_slug.get("quotes", [])}
        stance = s.get("theoretical_stance", {})
        quotes_html = []
        for c in s.get("key_citations", []):
            ok = vmap.get(c.get("quote", ""), False)
            total_q += 1
            total_v += int(ok)
            quotes_html.append(
                f'<div class="quote{" unverified" if not ok else ""}">'
                f'<span class="seal-mark">{"鉴" if ok else "研判"}</span>'
                f'<em>"{esc(c.get("quote",""))}"</em>'
                f'<div class="role">{esc(c.get("role",""))}</div></div>'
            )
        n_cites = len(s.get("key_citations", []))
        items.append(
            f'<details class="spine" id="spine-{esc(slug)}">'
            f'<summary>{esc(s.get("_title",""))}'
            f'<span class="meta-line">{n_cites} 引文 · {esc(s.get("_slug",""))}</span></summary>'
            f'<div class="body">'
            f'<p style="margin-bottom:8px"><b>核心论点</b>：{esc(s.get("core_thesis",""))}</p>'
            f'<p style="margin-bottom:8px"><span class="tag stance">{esc(stance.get("label",""))}</span>'
            f'{"<span class=tag>研判</span>" if stance.get("inference") else ""}</p>'
            f'<p style="margin-bottom:8px"><b>方法</b>：{esc(s.get("method",""))}</p>'
            f'<p style="margin:12px 0 6px;font-family:var(--font-sans);font-size:13px;color:var(--ink-3)">关键引文（E1 核验 · 盖「鉴」印 / 未过标「研判」）</p>'
            + "".join(quotes_html) + "</div></details>"
        )
    return "\n".join(items), total_v, total_q


def build_concepts_html(cd: dict, labels: dict) -> str:
    out = []
    for ce in cd.get("concept_evolution", []):
        stages = "".join(
            f'<div class="evolution-stage">'
            f'<div class="stage-label">{esc(st.get("stage",""))}</div>'
            f'<div><div class="claim">{esc(st.get("claim",""))}</div>'
            f'<div class="paper">{esc(labels.get(st.get("paper",""), st.get("paper","")))} · 证据：{esc(st.get("evidence",""))}</div></div></div>'
            for st in ce.get("stages", [])
        )
        out.append(f'<div class="card"><h3 style="color:var(--cinnabar);margin-bottom:12px">「{esc(ce.get("concept",""))}」的演变</h3>{stages}</div>')
    return "\n".join(out)


def build_disputes_html(cd: dict, labels: dict) -> str:
    out = []
    for dg in cd.get("disagreements", []):
        sides = "".join(
            f'<div class="side"><b>{esc(labels.get(sd.get("paper",""), sd.get("paper","")))}</b>：{esc(sd.get("stance",""))}'
            f'<div style="font-size:13px;color:var(--ink-3);font-family:var(--font-sans)">证据：{esc(sd.get("evidence",""))}</div></div>'
            for sd in dg.get("sides", [])
        )
        out.append(f'<div class="dispute"><h3>❓ {esc(dg.get("question",""))}</h3>{sides}</div>')
    return "\n".join(out)


def build_seq_graph_html(cd: dict) -> str:
    """单文档（doc 模式）章节流图：章 1 → 章 2 → … 顺序链，可拖拽缩放。"""
    nodes = cd.get("nodes", [])
    n = len(nodes)
    W = max(640, 60 + n * 150)
    H = 220
    y = 110
    parts = [f'<svg id="graph-svg" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    for i, nd in enumerate(nodes):
        x = 60 + i * 150
        if i > 0:
            px = 60 + (i - 1) * 150
            parts.append(
                f'<g class="edge" data-rel="顺序" opacity="0.7">'
                f'<path d="M{px + 108},{y} L{x - 108},{y}" stroke="{TOKENS["ink-3"]}" stroke-width="1.5" marker-end="url(#arr)"/>'
                f'</g>'
            )
        parts.append(
            f'<g class="node">'
            f'<rect x="{x - 108}" y="{y - 26}" width="216" height="52" rx="8" fill="var(--paper-card)" stroke="var(--cinnabar)" stroke-width="1.5"/>'
            f'<text x="{x}" y="{y - 4}" font-size="12" fill="var(--ink)" text-anchor="middle" font-weight="bold" font-family="serif">{esc(nd.get("label",""))}</text>'
            f'<text x="{x}" y="{y + 14}" font-size="10" fill="var(--ink-3)" text-anchor="middle" font-family="sans-serif">{esc((nd.get("stance","") or "")[:24])}</text>'
            f'</g>'
        )
    parts.insert(1, '<defs><marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto">'
                    f'<path d="M0,0 L8,4 L0,8 z" fill="{TOKENS["ink-3"]}"/></marker></defs>')
    parts.append("</svg>")
    svg = "\n".join(parts)
    return f"""<div class="graph-wrap">
  <div class="graph-toolbar"><span style="font-family:var(--font-sans);font-size:13px;color:var(--ink-2)">📖 章序流</span><span class="hint">拖拽平移 · 滚轮缩放</span></div>
  {svg}
</div>
<script>
(function(){{
  const svg=document.getElementById('graph-svg');
  let dragging=false, sx=0, sy=0, tx=0, ty=0, scale=1;
  svg.addEventListener('mousedown',e=>{{dragging=true;sx=e.clientX;sy=e.clientY;}});
  window.addEventListener('mousemove',e=>{{
    if(!dragging)return;const dx=e.clientX-sx,dy=e.clientY-sy;tx+=dx;sy=e.clientY;ty+=dy;sx=e.clientX;
    svg.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{scale}})`;
    svg.style.transformOrigin='center';
  }});
  window.addEventListener('mouseup',()=>dragging=false);
  svg.addEventListener('wheel',e=>{{e.preventDefault();scale=Math.max(.2,Math.min(3,scale+(e.deltaY<0?.1:-.1)));svg.style.transform=`translate(${{tx}}px,${{ty}}px) scale(${{scale}})`;}},{{passive:false}});
}})();
</script>"""


def build_edges_list_html(cd: dict, labels: dict) -> str:
    """关系说明列表：每条边 from→to + 关系 + rationale（报告里可读的"为什么"）。"""
    edges = cd.get("edges", [])
    if not edges:
        return ""
    items = []
    for i, e in enumerate(edges):
        meta = REL_META.get(e.get("relation", ""), {})
        color = meta.get("color", TOKENS["ink-3"])
        icon = meta.get("icon", "🔗")
        frm = labels.get(e.get("from", ""), e.get("from", ""))
        to = labels.get(e.get("to", ""), e.get("to", ""))
        items.append(
            f'<div class="edge-note" style="display:flex;gap:10px;padding:10px 0;border-bottom:1px dashed var(--border)">'
            f'<span style="flex-shrink:0;width:14px;height:14px;border-radius:50%;background:{color};margin-top:3px"></span>'
            f'<div><div style="font-size:13px"><b>{esc(frm)}</b> '
            f'<span style="color:{color}">{icon} {esc(e.get("relation",""))}</span> '
            f'<b>{esc(to)}</b></div>'
            f'<div style="font-size:12px;color:var(--ink-2);margin-top:2px">{esc(e.get("rationale",""))}</div></div></div>'
        )
    return "\n".join(items)


def build_nav(cd: dict, n_spines: int, meta: dict) -> str:
    counts = {
        "nodes": len(cd.get("nodes", [])),
        "edges": len(cd.get("edges", [])),
        "concepts": len(cd.get("concept_evolution", [])),
        "disputes": len(cd.get("disagreements", [])),
    }
    unit = meta.get("unit_label", "篇")
    concepts_link = (
        f'<a href="#concepts">🔄 概念演变 <span class="count">{counts["concepts"]}</span></a>\n'
        if counts["concepts"] else ""
    )
    disputes_link = (
        f'<a href="#disputes">⚔️ 观点分歧 <span class="count">{counts["disputes"]}</span></a>\n'
        if counts["disputes"] else ""
    )
    return f"""<nav class="sidebar"><h4>{esc(meta.get("nav_title","报告导航"))}</h4>
<a href="#overview">📋 总览 <span class="count">{counts['nodes']} {unit}</span></a>
<a href="#graph">🕸️ 脉络关系 <span class="count">{counts['edges']} 关系</span></a>
<a href="#narrative">📖 总体逻辑</a>
{concepts_link}{disputes_link}<a href="#spines">📚 证据脊 <span class="count">{n_spines} {unit}</span></a>
</nav>"""


def validate_input(inp: dict) -> list[str]:
    """契约校验：返回缺失/错误清单，空列表 = 合法。"""
    errors: list[str] = []
    for key in REQUIRED_TOP:
        if key not in inp:
            errors.append(f"缺 {key}")
    meta = inp.get("meta", {})
    for key in REQUIRED_META:
        if key not in meta:
            errors.append(f"meta 缺 {key}")
    nodes = inp.get("nodes", [])
    for i, nd in enumerate(nodes):
        if "slug" not in nd or "label" not in nd:
            errors.append(f"nodes[{i}] 缺 slug/label")
    edges = inp.get("edges", [])
    for i, e in enumerate(edges):
        if e.get("relation") not in REL_META:
            errors.append(f"edges[{i}] 关系类型不在五类内: {e.get('relation')!r}")
    return errors


def render_report(inp: dict) -> str:
    """把报告契约渲染成完整 HTML 页面。"""
    meta = inp.get("meta", {})
    cd = {"nodes": inp.get("nodes", []), "edges": inp.get("edges", []),
          "concept_evolution": inp.get("concept_evolution", []),
          "disagreements": inp.get("disagreements", []),
          "narrative": inp.get("narrative", "")}
    spines = inp.get("spines", {})
    e1 = inp.get("e1", {})
    quality = inp.get("quality", {})
    ask = inp.get("ask") or {}

    labels = {n["slug"]: n["label"] for n in cd["nodes"]}
    layout = inp.get("layout", "crossdoc")  # crossdoc=跨文本对照 / doc=单文档(章节流)
    is_doc = layout == "doc"
    graph_html = build_seq_graph_html(cd) if is_doc else build_graph_html(cd)
    spines_html, tv, tq = build_spines_html(spines, e1)
    concepts_html = build_concepts_html(cd, labels) if not is_doc else ""
    disputes_html = build_disputes_html(cd, labels) if not is_doc else ""
    nav_html = build_nav(cd, len(spines), meta)

    e2_mean = quality.get("e2_mean", 0)
    e3 = quality.get("e3", {})
    e3_rate = f"{e3.get('correct', 0)}/{e3.get('total', 0)}" if e3 else "—"

    ask_answer_html = ""
    if ask.get("answer"):
        ask_answer_html = (f'<div class="ask-entry" style="background:var(--cinnabar-soft);border-left:4px solid var(--cinnabar);'
                           f'padding:14px 16px;border-radius:0 8px 8px 0;margin-bottom:10px">'
                           f'<b>❓ {esc(ask.get("question",""))}</b>'
                           f'<div style="margin-top:8px">{esc(ask.get("answer",""))}</div></div>')
        src = ask.get("sources", [])
        if src:
            ask_answer_html += (f'<div style="font-size:12px;color:var(--ink-3);font-family:var(--font-sans)">'
                                f'来源: {esc(", ".join(src))}</div>')

    unit = meta.get("unit_label", "篇")
    title = meta.get("title", "书鉴报告")
    spine_section_title = "各章要点" if is_doc else "各家证据脊"
    graph_caption = (
        "节点 = 章节 · 章序流（章脉已建，每章要点见证据脊）"
        if is_doc else
        "节点 = 单元 · 边 = 继承/反驳/补充/落地/检验（E3 独立核验）"
    )
    concepts_section = "" if is_doc else (
        f'  <section id="concepts"><h2><span class="no">肆</span>概念演变</h2>{concepts_html}</section>\n'
    )
    disputes_section = "" if is_doc else (
        f'  <section id="disputes"><h2><span class="no">伍</span>观点分歧</h2>{disputes_html}</section>\n'
    )

    page = f"""<!DOCTYPE html>
<html lang="zh" data-theme="light">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>书鉴 · {esc(title)}</title>
<style>{build_css()}</style>
</head>
<body>
<header class="hero">
  <h1>📜 {esc(title)}</h1>
  <p class="subtitle">{esc(meta.get("subtitle",""))}</p>
  <span class="seal">{esc(meta.get("seal","书 鉴"))}</span>
</header>

<div class="stats">
  <div class="stat"><div class="num">{len(spines)}</div><div class="label">证据脊</div></div>
  <div class="stat pass"><div class="num">{tv}/{tq}</div><div class="label">引文核验（E1）</div></div>
  <div class="stat pass"><div class="num">{e2_mean:.1f}/5</div><div class="label">证据脊质量（E2）</div></div>
  <div class="stat pass"><div class="num">{e3_rate}</div><div class="label">关系核验（E3）</div></div>
  {"" if is_doc else f'<div class="stat"><div class="num">{len(cd["edges"])}</div><div class="label">关系边</div></div><div class="stat"><div class="num">{len(cd["disagreements"])}</div><div class="label">观点分歧</div></div>'}
</div>

<div class="layout">{nav_html}
<main>
  <section id="overview"><h2><span class="no">壹</span>总览</h2>
    <div class="card">{esc(cd["narrative"])}</div>
  </section>

  <section id="graph"><h2><span class="no">贰</span>脉络关系</h2>{graph_html}
    <p style="font-size:13px;color:var(--ink-3);font-family:var(--font-sans);margin-top:10px">{graph_caption}</p>
    {"" if is_doc else f'<div class="card" style="margin-top:14px"><h3 style="font-size:15px;color:var(--cinnabar);margin-bottom:6px">关系说明</h3>{build_edges_list_html(cd, labels)}</div>'}
  </section>

  <section id="narrative"><h2><span class="no">叁</span>总体逻辑脉络</h2>
    <div class="card" style="font-size:16px">{esc(cd["narrative"])}</div>
  </section>

  {concepts_section}
  {disputes_section}

  <section id="spines"><h2><span class="no">{"肆" if is_doc else "陆"}</span>{spine_section_title}</h2>
    <div class="search-box" style="padding:0;margin-bottom:12px"><input id="spine-search" type="search" placeholder="🔍 搜索单元 / 论点 / 引文…"></div>
    {spines_html}
  </section>

  <section id="ask"><h2><span class="no">{"伍" if is_doc else "柒"}</span>追问</h2>
    <div class="card">
      <p style="font-size:14px;color:var(--ink-2);margin-bottom:12px">基于已入库的结构与关系脉络回答（不重读全文，轻量 LLM）。</p>
      <div style="display:flex;gap:8px">
        <input id="ask-input" type="text" placeholder="例如：这个理论后来是怎么被扩展的？" style="flex:1;padding:10px 14px;border:1px solid var(--border);border-radius:8px;background:var(--paper);font-family:var(--font-sans);font-size:14px;color:var(--ink);outline:none">
        <button id="ask-btn" style="padding:10px 20px;background:var(--cinnabar);color:#fff;border:none;border-radius:8px;cursor:pointer;font-family:var(--font-sans);font-size:14px">追问</button>
      </div>
      <div id="ask-answer" style="margin-top:14px;font-size:14px;white-space:pre-wrap">{ask_answer_html}</div>
    </div>
  </section>
</main>
</div>

<button class="theme-toggle" onclick="document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'light':'dark'" title="切换主题">🌓</button>

<footer>{esc(meta.get("generated_by","书鉴 BookScope"))} · E1 引文核验 {tv}/{tq} · E2 {e2_mean:.1f}/5 · E3 {e3_rate}</footer>

<script>
document.getElementById('spine-search').addEventListener('input',e=>{{
  const q=e.target.value.trim().toLowerCase();
  document.querySelectorAll('details.spine').forEach(d=>{{
    const txt=(d.textContent||'').toLowerCase();
    d.style.display=(!q||txt.includes(q))?'':'none';
  }});
}});
document.getElementById('ask-btn').addEventListener('click',()=>{{
  const q=document.getElementById('ask-input').value.trim();
  if(!q)return;
  const box=document.getElementById('ask-answer');
  box.innerHTML='<i style="color:var(--ink-3)">追问接口待接入（P3）——报告生成时可用 --ask 预渲染答案。</i>';
  box.scrollIntoView({{behavior:'smooth'}});
}});
document.getElementById('ask-input').addEventListener('keydown',e=>{{if(e.key==='Enter')document.getElementById('ask-btn').click();}});
</script>
</body></html>"""

    return page
