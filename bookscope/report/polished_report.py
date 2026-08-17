"""高质量书稿式报告渲染器。

目标：像一本认真排版的小书/深度研究文档。
- 封面头 + 目录 + 章节 + 行内引用 + 图表 + 追问 + 方法说明
- 不用卡片堆叠，用排版、留白、细线、引用块。
"""

from __future__ import annotations

import html
from typing import Any


def _esc(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _css() -> str:
    return """
:root{
  --ink:#25211C; --ink-2:#5A5248; --ink-3:#948B7E;
  --paper:#FAF7F0; --line:#E2D9C8; --accent:#A63A2B; --accent-soft:#F4E6E0;
  --serif:"Noto Serif SC","Songti SC","Source Han Serif SC",serif;
  --sans:"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--paper);color:var(--ink);font-family:var(--serif);line-height:1.9;font-size:17px}
.wrap{max-width:820px;margin:0 auto;padding:64px 36px 100px}
header{padding-bottom:36px;border-bottom:1px solid var(--line);margin-bottom:36px}
.kicker{font-family:var(--sans);font-size:12px;letter-spacing:.2em;color:var(--ink-3);text-transform:uppercase;margin-bottom:16px}
h1{font-size:40px;line-height:1.25;font-weight:800;letter-spacing:.01em}
.subtitle{font-size:17px;color:var(--ink-2);margin-top:12px;max-width:640px;line-height:1.8}
.meta{font-family:var(--sans);font-size:13px;color:var(--ink-3);margin-top:20px;display:flex;flex-wrap:wrap;gap:8px 20px}
.seal{display:inline-block;border:1px solid var(--accent);color:var(--accent);border-radius:3px;padding:2px 12px;font-size:12px;letter-spacing:.3em;font-family:var(--sans);margin-top:18px}
.toc{margin:36px 0;padding:0 0 8px;border-bottom:1px solid var(--line)}
.toc .toc-title{font-family:var(--sans);font-size:12px;letter-spacing:.2em;color:var(--ink-3);margin-bottom:12px}
.toc a{display:block;color:var(--ink-2);text-decoration:none;font-size:15px;padding:5px 0;border-bottom:1px dashed var(--line);font-family:var(--sans)}
.toc a:last-child{border-bottom:none}
.toc a:hover{color:var(--accent)}
section{margin-bottom:52px}
h2{font-size:24px;font-weight:800;color:var(--ink);padding-bottom:10px;border-bottom:1px solid var(--line);margin-bottom:22px;display:flex;align-items:baseline;gap:12px}
h2 .no{font-family:var(--sans);font-size:12px;color:var(--ink-3);letter-spacing:.12em}
p{color:var(--ink-2);margin-bottom:16px}
.summary{font-size:19px;line-height:2.1;color:var(--ink);padding:8px 0 8px 22px;border-left:3px solid var(--accent);margin:0 0 20px}
.flow{width:100%;height:auto;margin:18px 0;background:transparent}
ol.args{list-style:none;counter-reset:arg;margin:0}
ol.args>li{counter-increment:arg;padding:22px 0 22px 56px;border-bottom:1px solid var(--line);position:relative}
ol.args>li:last-child{border-bottom:none}
ol.args>li::before{content:counter(arg,decimal-leading-zero);position:absolute;left:0;top:24px;font-family:var(--sans);font-size:13px;color:var(--accent);letter-spacing:.05em}
.claim{font-size:18px;color:var(--ink);font-weight:700;line-height:1.7}
.cite{font-family:var(--sans);font-size:12px;color:var(--accent);vertical-align:super;margin-left:3px}
blockquote{margin:12px 0 0;padding:2px 0 2px 18px;border-left:2px solid var(--line);color:var(--ink-2);font-size:15px;line-height:1.8}
blockquote .src{font-family:var(--sans);font-size:12px;color:var(--ink-3);display:block;margin-top:4px}
.timeline{list-style:none;margin:0;padding-left:22px;border-left:1px solid var(--line)}
.timeline>li{position:relative;padding:0 0 26px 22px}
.timeline>li::before{content:"";position:absolute;left:-27px;top:8px;width:9px;height:9px;border-radius:50%;background:var(--accent);border:2px solid var(--paper)}
.timeline .ch{font-family:var(--sans);font-size:12px;color:var(--ink-3);letter-spacing:.05em}
.timeline .dev{font-size:17px;color:var(--ink);margin-top:2px}
.qa{border-top:1px solid var(--line);padding-top:22px}
.qa .q{font-size:19px;font-weight:800;color:var(--ink);margin-bottom:10px}
.qa .a{font-size:16px;color:var(--ink-2);line-height:2}
.qa .src{font-family:var(--sans);font-size:13px;color:var(--ink-3);margin-top:12px}
.method{font-family:var(--sans);font-size:13px;color:var(--ink-3);line-height:1.9}
.method b{color:var(--ink-2)}
footer{margin-top:60px;padding-top:22px;border-top:1px solid var(--line);font-family:var(--sans);font-size:12px;color:var(--ink-3);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
@media(max-width:640px){
  .wrap{padding:36px 20px 70px}
  h1{font-size:28px}
  h2{font-size:20px}
  body{font-size:16px}
  ol.args>li{padding-left:0;padding-top:24px}
  ol.args>li::before{left:0;top:26px}
  .timeline{padding-left:14px}
}
"""


def _flow_svg(labels: list[str]) -> str:
    n = len(labels)
    if n < 2:
        return ""
    W = max(640, n * 170)
    H = 120
    parts = [f'<svg class="flow" viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg">']
    for i, label in enumerate(labels):
        x = 60 + i * (W - 120) / max(n - 1, 1)
        if i > 0:
            px = 60 + (i - 1) * (W - 120) / max(n - 1, 1)
            parts.append(f'<line x1="{px+80:.1f}" y1="60" x2="{x-80:.1f}" y2="60" stroke="var(--line)" stroke-width="1.5"/>')
        parts.append(
            f'<text x="{x:.1f}" y="38" font-size="13" fill="var(--ink)" text-anchor="middle" font-family="var(--sans)" font-weight="600">{_esc(label)}</text>'
            f'<circle cx="{x:.1f}" cy="60" r="5" fill="var(--accent)"/>'
        )
    parts.append("</svg>")
    return "".join(parts)


def render_polished_report(data: dict) -> str:
    meta = data.get("meta", {})
    title = meta.get("title", "逻辑梳理报告")
    subtitle = meta.get("subtitle", "")
    generated = meta.get("generated_by", "书鉴 BookScope")

    recap = data.get("recap", {})
    argument = data.get("argument_structure", {})
    concept = data.get("concept_evolution", {})
    ask = data.get("ask", {})

    points = recap.get("points", []) or []
    narrative = "；".join(str(p.get("point", "")) for p in points[:8]) or "（暂无主线数据）"

    claims = argument.get("claims", []) or []
    args_html = ""
    if claims:
        lis = []
        for i, c in enumerate(claims[:16], 1):
            ev = c.get("evidence", "")
            verified = c.get("verified", False)
            mark = "鉴" if verified else "研判"
            ev_html = f'<blockquote>{_esc(ev)}<span class="src">{mark} · 第{c.get("chapter","?")}章</span></blockquote>' if ev else ""
            lis.append(
                f'<li><div class="claim">{_esc(c.get("claim",""))}</div>{ev_html}</li>'
            )
        args_html = "<ol class=\"args\">" + "".join(lis) + "</ol>"
    else:
        args_html = "<p>暂无论证数据。</p>"

    stages_html = ""
    if concept.get("stages"):
        lis = []
        for s in concept["stages"][:10]:
            ev = s.get("snippet", "")
            verified = s.get("verified", False)
            mark = "鉴" if verified else "研判"
            ev_html = f'<blockquote>{_esc(ev)}<span class="src">{mark}</span></blockquote>' if ev else ""
            lis.append(
                f'<li><span class="ch">第{s.get("chapter","?")}章</span><div class="dev">{_esc(s.get("development",""))}</div>{ev_html}</li>'
            )
        stages_html = "<ul class=\"timeline\">" + "".join(lis) + "</ul>"
    else:
        stages_html = "<p>暂无概念演变数据。</p>"

    # 逻辑流程图：从论证结构前几条提炼阶段
    flow_labels = [str(c.get("claim", ""))[:10] for c in claims[:4]] or ["起点", "发展", "转折", "结论"]
    flow_html = _flow_svg(flow_labels)

    ask_html = ""
    if ask.get("question"):
        src = ""
        if ask.get("sources"):
            src = f'<div class="src">来源：{_esc("、".join(ask.get("sources", [])))}</div>'
        ask_html = (
            f'<div class="qa"><div class="q">{_esc(ask.get("question",""))}</div>'
            f'<div class="a">{_esc(ask.get("answer",""))}</div>{src}</div>'
        )

    toc = """
<div class="toc"><div class="toc-title">目录</div>
<a href="#summary">一、逻辑主线</a>
<a href="#flow">二、逻辑推进</a>
<a href="#args">三、论证结构</a>
<a href="#concept">四、概念演变</a>
<a href="#qa">五、追问</a>
<a href="#method">六、方法说明</a>
</div>"""

    return f"""<!DOCTYPE html>
<html lang="zh" data-theme="light">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{_esc(title)}</title>
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

  {toc}

  <section id="summary">
    <h2><span class="no">壹</span>逻辑主线</h2>
    <p class="summary">{_esc(narrative)}</p>
  </section>

  <section id="flow">
    <h2><span class="no">贰</span>逻辑推进</h2>
    {flow_html}
    <p>这张图是全书论证的推进骨架：从总判断出发，经过价值肯定、立场批判，最后落到具体成就。</p>
  </section>

  <section id="args">
    <h2><span class="no">叁</span>论证结构</h2>
    {args_html}
  </section>

  <section id="concept">
    <h2><span class="no">肆</span>概念演变</h2>
    {stages_html}
  </section>

  <section id="qa">
    <h2><span class="no">伍</span>追问</h2>
    {ask_html if ask_html else '<p>暂无追问。</p>'}
  </section>

  <section id="method">
    <h2><span class="no">陆</span>方法说明</h2>
    <div class="method">
      <p><b>数据来源：</b>本地原文。</p>
      <p><b>分析方式：</b>AI 从原文抽取论点、概念与主线，再由核验器回原文逐字比对。</p>
      <p><b>判定标识：</b>「鉴」= 原文逐字命中；「研判」= 模型推断。</p>
      <p><b>使用建议：</b>本报告是辅助梳理，重要结论请回到原文核对。</p>
    </div>
  </section>

  <footer>
    <span>{_esc(title)}</span>
    <span>BookScope · 书鉴</span>
  </footer>
</div>
</body>
</html>"""
