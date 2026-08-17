"""基于 ECharts 的高质量可视化报告渲染器。

用成熟可视化引擎替代手绘 SVG，保证图表专业、可交互。
配色保持书鉴原设计系统。
"""

from __future__ import annotations

import html
import json
from typing import Any


def _esc(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _css() -> str:
    return """
:root{
  --cinnabar:#B03A2E; --cinnabar-deep:#8E2A20; --cinnabar-soft:#F5E6E3;
  --ink:#2B2622; --ink-2:#5A534C; --ink-3:#8A8278;
  --paper:#F7F2E7; --paper-card:#FFFCF5; --gold:#9C7A2E; --jade:#2E7D5B;
  --indigo:#3D5A99; --violet:#6A4E8E; --border:#E4DCCB;
  --serif:"Noto Serif SC","Songti SC","Source Han Serif SC",serif;
  --sans:"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--paper);color:var(--ink);font-family:var(--serif);line-height:1.9;font-size:17px}
.wrap{max-width:960px;margin:0 auto;padding:56px 28px 80px}
header{padding-bottom:32px;border-bottom:1px solid var(--border);margin-bottom:36px}
.kicker{font-family:var(--sans);font-size:12px;letter-spacing:.2em;color:var(--ink-3);text-transform:uppercase;margin-bottom:14px}
h1{font-size:38px;line-height:1.25;font-weight:800}
.subtitle{font-size:17px;color:var(--ink-2);margin-top:10px;max-width:680px}
.meta{font-family:var(--sans);font-size:13px;color:var(--ink-3);margin-top:18px;display:flex;gap:20px;flex-wrap:wrap}
.seal{display:inline-block;border:1px solid var(--cinnabar);color:var(--cinnabar);border-radius:3px;padding:2px 12px;font-size:12px;letter-spacing:.3em;font-family:var(--sans);margin-top:16px}
.toc{margin:32px 0;padding-bottom:10px;border-bottom:1px solid var(--border)}
.toc .toc-title{font-family:var(--sans);font-size:12px;letter-spacing:.2em;color:var(--ink-3);margin-bottom:10px}
.toc a{display:inline-block;color:var(--ink-2);text-decoration:none;font-size:14px;font-family:var(--sans);margin:0 18px 6px 0}
.toc a:hover{color:var(--cinnabar)}
section{margin-bottom:48px}
h2{font-size:24px;font-weight:800;padding-bottom:10px;border-bottom:1px solid var(--border);margin-bottom:18px;display:flex;align-items:baseline;gap:10px}
h2 .no{font-family:var(--sans);font-size:12px;color:var(--ink-3);letter-spacing:.1em}
.chart{width:100%;height:420px;margin:16px 0}
.chart.small{height:300px}
p{color:var(--ink-2);margin-bottom:14px}
.summary{font-size:19px;line-height:2.1;color:var(--ink);padding-left:20px;border-left:3px solid var(--cinnabar);margin-bottom:20px}
ol.args{list-style:none;counter-reset:arg;margin:0}
ol.args>li{counter-increment:arg;padding:20px 0 20px 52px;border-bottom:1px solid var(--border);position:relative}
ol.args>li:last-child{border-bottom:none}
ol.args>li::before{content:counter(arg,decimal-leading-zero);position:absolute;left:0;top:22px;font-family:var(--sans);font-size:13px;color:var(--cinnabar)}
.claim{font-size:18px;color:var(--ink);font-weight:700}
blockquote{margin:10px 0 0;padding-left:16px;border-left:2px solid var(--border);color:var(--ink-2);font-size:15px}
blockquote .src{font-family:var(--sans);font-size:12px;color:var(--ink-3);display:block;margin-top:4px}
.timeline{list-style:none;margin:0;padding-left:20px;border-left:1px solid var(--border)}
.timeline>li{position:relative;padding:0 0 22px 20px}
.timeline>li::before{content:"";position:absolute;left:-25px;top:8px;width:9px;height:9px;border-radius:50%;background:var(--cinnabar);border:2px solid var(--paper)}
.timeline .ch{font-family:var(--sans);font-size:12px;color:var(--ink-3)}
.timeline .dev{font-size:17px;color:var(--ink)}
.qa{border-top:1px solid var(--border);padding-top:20px}
.qa .q{font-size:19px;font-weight:800;margin-bottom:8px}
.qa .a{font-size:16px;color:var(--ink-2);line-height:2}
.qa .src{font-family:var(--sans);font-size:13px;color:var(--ink-3);margin-top:10px}
.method{font-family:var(--sans);font-size:13px;color:var(--ink-3);line-height:1.9}
.method b{color:var(--ink-2)}
footer{margin-top:56px;padding-top:20px;border-top:1px solid var(--border);font-family:var(--sans);font-size:12px;color:var(--ink-3);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
@media(max-width:640px){
  .wrap{padding:32px 16px 60px}
  h1{font-size:27px}
  h2{font-size:20px}
  body{font-size:16px}
  .chart{height:320px}
  .chart.small{height:260px}
  ol.args>li{padding-left:0;padding-top:22px}
  ol.args>li::before{left:0;top:24px}
}
"""


def render_echarts_report(data: dict) -> str:
    meta = data.get("meta", {})
    title = meta.get("title", "逻辑梳理报告")
    subtitle = meta.get("subtitle", "")
    generated = meta.get("generated_by", "书鉴 BookScope")

    recap = data.get("recap", {})
    argument = data.get("argument_structure", {})
    concept = data.get("concept_evolution", {})
    graph = data.get("character_graph", {})
    curve = data.get("narrative_curve", {})
    timeline = data.get("timeline", {})
    ask = data.get("ask", {})

    points = recap.get("points", []) or []
    narrative = "；".join(str(p.get("point", "")) for p in points[:8]) or "（暂无主线数据）"
    claims = argument.get("claims", []) or []

    # 逻辑图数据
    flow_nodes = []
    flow_edges = []
    labels = [str(c.get("claim", ""))[:12] for c in claims[:5]] or ["起点", "发展", "转折", "结论", "收束"]
    for i, lab in enumerate(labels):
        flow_nodes.append({"id": f"n{i}", "name": lab, "symbolSize": 46, "itemStyle": {"color": "#B03A2E" if i in (0, len(labels)-1) else "#9C7A2E"}, "label": {"fontSize": 12}})
        if i > 0:
            flow_edges.append({"source": f"n{i-1}", "target": f"n{i}", "lineStyle": {"color": "#E4DCCB", "width": 2}})
    flow_option = {
        "tooltip": {},
        "animationDurationUpdate": 500,
        "series": [{
            "type": "graph", "layout": "none", "data": flow_nodes, "links": flow_edges,
            "roam": True, "draggable": True,
            "label": {"show": True, "position": "bottom", "color": "#2B2622"},
            "lineStyle": {"color": "#E4DCCB", "width": 2, "curveness": 0.1},
            "emphasis": {"focus": "adjacency", "lineStyle": {"width": 3}},
        }]
    }

    # 人物关系图
    g_nodes = graph.get("nodes", []) or []
    g_edges = graph.get("edges", []) or []
    degree = {}
    for e in g_edges:
        degree[e.get("source","")] = degree.get(e.get("source",""), 0) + 1
        degree[e.get("target","")] = degree.get(e.get("target",""), 0) + 1
    top = sorted(g_nodes, key=lambda x: degree.get(x,0), reverse=True)[:30]
    top_set = set(top)
    graph_data = [{"name": n, "symbolSize": 18 + min(degree.get(n,0), 20), "itemStyle": {"color": "#B03A2E"}} for n in top]
    graph_links = [{"source": e.get("source"), "target": e.get("target"), "lineStyle": {"width": min(e.get("strength",1),3), "color": "#E4DCCB"}} for e in g_edges if e.get("source") in top_set and e.get("target") in top_set][:100]
    graph_option = {
        "tooltip": {},
        "series": [{
            "type": "graph", "layout": "force", "data": graph_data, "links": graph_links,
            "roam": True, "draggable": True,
            "force": {"repulsion": 120, "edgeLength": 80},
            "label": {"show": True, "position": "right", "fontSize": 10, "color": "#5A534C"},
            "lineStyle": {"color": "#E4DCCB", "width": 1, "opacity": 0.6},
            "emphasis": {"focus": "adjacency"},
        }]
    }

    # 叙事曲线
    chapters = curve.get("chapters", []) or []
    curve_option = {
        "tooltip": {"trigger": "axis"},
        "grid": {"left": 40, "right": 20, "top": 30, "bottom": 40},
        "xAxis": {"type": "category", "data": [f"第{c.get('chapter','?')}章" for c in chapters[:60]], "axisLine": {"lineStyle": {"color": "#8A8278"}}},
        "yAxis": {"type": "value", "name": "事件密度", "axisLine": {"lineStyle": {"color": "#8A8278"}}},
        "series": [{
            "name": "事件", "type": "bar", "data": [c.get("event_count",0) for c in chapters[:60]],
            "itemStyle": {"color": "#B03A2E", "opacity": 0.8},
        }, {
            "name": "转折", "type": "scatter", "data": [[i, c.get("event_count",0)+2] for i,c in enumerate(chapters[:60]) if c.get("is_turning")],
            "symbolSize": 10, "itemStyle": {"color": "#9C7A2E"},
        }]
    }

    # 事件时间线
    events = timeline.get("events", []) or []
    timeline_html = ""
    if events:
        lis = []
        for e in events[:20]:
            lis.append(f'<li><span class="ch">第{e.get("chapter","?")}章</span><div class="dev">{_esc(e.get("event",""))}</div></li>')
        timeline_html = '<ul class="timeline">' + "".join(lis) + "</ul>"
    else:
        timeline_html = "<p>暂无事件时间线数据。</p>"

    # 论证结构
    args_html = ""
    if claims:
        lis = []
        for i, c in enumerate(claims[:16], 1):
            ev = c.get("evidence", "")
            verified = c.get("verified", False)
            mark = "鉴" if verified else "研判"
            ev_html = f'<blockquote>{_esc(ev)}<span class="src">{mark} · 第{c.get("chapter","?")}章</span></blockquote>' if ev else ""
            lis.append(f'<li><div class="claim">{_esc(c.get("claim",""))}</div>{ev_html}</li>')
        args_html = '<ol class="args">' + "".join(lis) + "</ol>"
    else:
        args_html = "<p>暂无论证数据。</p>"

    # 概念演变
    stages_html = ""
    if concept.get("stages"):
        lis = []
        for s in concept["stages"][:10]:
            ev = s.get("snippet", "")
            verified = s.get("verified", False)
            mark = "鉴" if verified else "研判"
            ev_html = f'<blockquote>{_esc(ev)}<span class="src">{mark}</span></blockquote>' if ev else ""
            lis.append(f'<li><span class="ch">第{s.get("chapter","?")}章</span><div class="dev">{_esc(s.get("development",""))}</div>{ev_html}</li>')
        stages_html = '<ul class="timeline">' + "".join(lis) + "</ul>"
    else:
        stages_html = "<p>暂无概念演变数据。</p>"

    ask_html = ""
    if ask.get("question"):
        src = ""
        if ask.get("sources"):
            src = f'<div class="src">来源：{_esc("、".join(ask.get("sources", [])))}</div>'
        ask_html = f'<div class="qa"><div class="q">{_esc(ask.get("question",""))}</div><div class="a">{_esc(ask.get("answer",""))}</div>{src}</div>'

    return f"""<!DOCTYPE html>
<html lang="zh" data-theme="light">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{_esc(title)}</title>
<script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
<style>{_css()}</style>
</head>
<body>
<div class="wrap">
  <header>
    <div class="kicker">BookScope · 深度逻辑梳理</div>
    <h1>{_esc(title)}</h1>
    <p class="subtitle">{_esc(subtitle)}</p>
    <span class="seal">书 鉴</span>
    <div class="meta"><span>{_esc(generated)}</span><span>引文均回原文核验</span></div>
  </header>

  <div class="toc"><div class="toc-title">目录</div>
    <a href="#summary">逻辑主线</a><a href="#flow">逻辑推进</a><a href="#graph">人物关系</a><a href="#curve">叙事曲线</a><a href="#args">论证结构</a><a href="#concept">概念演变</a><a href="#events">事件时间线</a><a href="#qa">追问</a><a href="#method">方法</a>
  </div>

  <section id="summary"><h2><span class="no">壹</span>逻辑主线</h2><p class="summary">{_esc(narrative)}</p></section>
  <section id="flow"><h2><span class="no">贰</span>逻辑推进</h2><div id="flowChart" class="chart small"></div></section>
  <section id="graph"><h2><span class="no">叁</span>人物关系</h2><div id="graphChart" class="chart"></div></section>
  <section id="curve"><h2><span class="no">肆</span>叙事曲线</h2><div id="curveChart" class="chart"></div></section>
  <section id="args"><h2><span class="no">伍</span>论证结构</h2>{args_html}</section>
  <section id="concept"><h2><span class="no">陆</span>概念演变</h2>{stages_html}</section>
  <section id="events"><h2><span class="no">柒</span>事件时间线</h2>{timeline_html}</section>
  <section id="qa"><h2><span class="no">捌</span>追问</h2>{ask_html if ask_html else '<p>暂无追问。</p>'}</section>
  <section id="method"><h2><span class="no">玖</span>方法说明</h2><div class="method"><p><b>数据来源：</b>本地原文。</p><p><b>分析方式：</b>AI 从原文抽取论点、概念与主线，再由核验器回原文逐字比对。</p><p><b>判定标识：</b>「鉴」= 原文逐字命中；「研判」= 模型推断。</p><p><b>使用建议：</b>本报告是辅助梳理，重要结论请回到原文核对。</p></div></section>

  <footer><span>{_esc(title)}</span><span>BookScope · 书鉴</span></footer>
</div>
<script>
const flowOption = {json.dumps(flow_option, ensure_ascii=False)};
const graphOption = {json.dumps(graph_option, ensure_ascii=False)};
const curveOption = {json.dumps(curve_option, ensure_ascii=False)};
const charts = [
  ['flowChart', flowOption],
  ['graphChart', graphOption],
  ['curveChart', curveOption],
];
window.addEventListener('load', () => {{
  charts.forEach(([id, option]) => {{
    const el = document.getElementById(id);
    if (el && window.echarts) {{
      const chart = echarts.init(el);
      chart.setOption(option);
      window.addEventListener('resize', () => chart.resize());
    }}
  }});
}});
</script>
</body>
</html>"""
