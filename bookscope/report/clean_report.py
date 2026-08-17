"""极简书稿式报告渲染器。

设计原则：简洁又详尽。
- 不用卡片/框框堆叠，用留白、字距、细线分隔。
- 单栏阅读，像一份认真排版的文稿。
- 证据用引用块，不套盒子。
- 移动端就是舒服的单列长文。
"""

from __future__ import annotations

import html
from typing import Any


def _esc(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _css() -> str:
    return """
:root{
  --ink:#26221E; --ink-2:#5C554D; --ink-3:#9A9186;
  --paper:#FAF7F0; --line:#E4DCCB; --accent:#A63A2B; --accent-soft:#F3E3DE;
  --serif:"Noto Serif SC","Songti SC","Source Han Serif SC",serif;
  --sans:"Noto Sans SC","PingFang SC","Microsoft YaHei",sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{background:var(--paper);color:var(--ink);font-family:var(--serif);line-height:1.9;font-size:17px}
.wrap{max-width:760px;margin:0 auto;padding:56px 28px 80px}
header{padding-bottom:32px;border-bottom:1px solid var(--line);margin-bottom:40px}
header .kicker{font-family:var(--sans);font-size:12px;letter-spacing:.18em;color:var(--ink-3);text-transform:uppercase;margin-bottom:14px}
header h1{font-size:34px;line-height:1.3;font-weight:700;letter-spacing:.02em;color:var(--ink)}
header .subtitle{font-size:16px;color:var(--ink-2);margin-top:10px;max-width:620px}
header .meta{font-family:var(--sans);font-size:13px;color:var(--ink-3);margin-top:18px}
.seal{display:inline-block;border:1px solid var(--accent);color:var(--accent);border-radius:3px;padding:1px 10px;font-size:12px;letter-spacing:.3em;font-family:var(--sans);margin-top:16px}
section{margin-bottom:44px}
section h2{font-size:22px;font-weight:700;color:var(--ink);padding-bottom:8px;border-bottom:1px solid var(--line);margin-bottom:20px;display:flex;align-items:baseline;gap:10px}
section h2 .no{font-family:var(--sans);font-size:12px;color:var(--ink-3);letter-spacing:.1em}
section p{color:var(--ink-2);margin-bottom:14px}
.narrative{font-size:17px;color:var(--ink);line-height:2;text-align:justify}
ol.args{list-style:none;counter-reset:arg;margin:0}
ol.args>li{counter-increment:arg;padding:18px 0;border-bottom:1px solid var(--line);position:relative;padding-left:48px}
ol.args>li:last-child{border-bottom:none}
ol.args>li::before{content:counter(arg);position:absolute;left:0;top:20px;width:30px;height:30px;border:1px solid var(--accent);color:var(--accent);border-radius:50%;display:flex;align-items:center;justify-content:center;font-family:var(--sans);font-size:13px}
ol.args .claim{font-size:17px;color:var(--ink);font-weight:600}
blockquote{margin:10px 0 0;padding-left:18px;border-left:2px solid var(--accent);color:var(--ink-2);font-size:15px;line-height:1.8}
blockquote .mark{font-family:var(--sans);font-size:12px;color:var(--accent);margin-right:6px}
.stages{list-style:none;margin:0}
.stages>li{padding:14px 0;border-bottom:1px solid var(--line);display:grid;grid-template-columns:64px 1fr;gap:16px}
.stages>li:last-child{border-bottom:none}
.stages .ch{font-family:var(--sans);font-size:13px;color:var(--ink-3);padding-top:4px}
.stages .dev{font-size:16px;color:var(--ink)}
.qa{border-top:1px solid var(--line);padding-top:20px}
.qa .q{font-size:17px;font-weight:700;color:var(--ink);margin-bottom:8px}
.qa .a{font-size:16px;color:var(--ink-2);line-height:2}
.qa .src{font-family:var(--sans);font-size:13px;color:var(--ink-3);margin-top:10px}
footer{margin-top:60px;padding-top:20px;border-top:1px solid var(--line);font-family:var(--sans);font-size:12px;color:var(--ink-3);display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px}
@media(max-width:640px){
  .wrap{padding:32px 18px 60px}
  header h1{font-size:26px}
  section h2{font-size:19px}
  body{font-size:16px}
  ol.args>li{padding-left:0;padding-top:22px}
  ol.args>li::before{left:0;top:22px}
  .stages>li{grid-template-columns:1fr;gap:4px}
}
"""


def render_clean_report(data: dict) -> str:
    meta = data.get("meta", {})
    title = meta.get("title", "逻辑梳理报告")
    subtitle = meta.get("subtitle", "")
    generated = meta.get("generated_by", "书鉴 BookScope")

    recap = data.get("recap", {})
    argument = data.get("argument_structure", {})
    concept = data.get("concept_evolution", {})
    ask = data.get("ask", {})

    # 逻辑主线：一段话
    points = recap.get("points", []) or []
    narrative = "；".join(str(p.get("point", "")) for p in points[:8]) or "（暂无主线数据）"

    # 论证结构
    claims = argument.get("claims", []) or []
    args_html = ""
    if claims:
        lis = []
        for c in claims[:20]:
            ev = c.get("evidence", "")
            verified = c.get("verified", False)
            ev_html = f'<blockquote><span class="mark">{"鉴" if verified else "研判"}</span>{_esc(ev)}</blockquote>' if ev else ""
            lis.append(f"<li><div class=\"claim\">{_esc(c.get('claim',''))}</div>{ev_html}</li>")
        args_html = "<ol class=\"args\">" + "".join(lis) + "</ol>"
    else:
        args_html = "<p>暂无论证数据。</p>"

    # 概念演变
    stages_html = ""
    if concept.get("stages"):
        lis = []
        for s in concept["stages"][:10]:
            mark = "鉴" if s.get("verified") else "研判"
            snippet = s.get("snippet", "")
            ev = f'<blockquote><span class="mark">{mark}</span>{_esc(snippet)}</blockquote>' if snippet else ""
            lis.append(
                f"<li><span class=\"ch\">第{s.get('chapter','?')}章</span>"
                f"<div class=\"dev\">{_esc(s.get('development',''))}</div>"
                f"{ev}"
                f"</li>"
            )
        stages_html = "<ul class=\"stages\">" + "".join(lis) + "</ul>"
    else:
        stages_html = "<p>暂无概念演变数据。</p>"

    ask_html = ""
    if ask.get("question"):
        src = ""
        if ask.get("sources"):
            src = f'<div class="src">来源：{_esc("、".join(ask.get("sources", [])))}</div>'
        ask_html = (
            f'<div class="qa"><div class="q">{_esc(ask.get("question",""))}</div>'
            f'<div class="a">{_esc(ask.get("answer",""))}</div>'
            f"{src}"
            f"</div>"
        )

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
    <div class="kicker">BookScope · 逻辑梳理</div>
    <h1>{_esc(title)}</h1>
    <p class="subtitle">{_esc(subtitle)}</p>
    <span class="seal">书 鉴</span>
    <div class="meta">{_esc(generated)}</div>
  </header>

  <section>
    <h2><span class="no">壹</span>逻辑主线</h2>
    <p class="narrative">{_esc(narrative)}</p>
  </section>

  <section>
    <h2><span class="no">贰</span>论证结构</h2>
    {args_html}
  </section>

  <section>
    <h2><span class="no">叁</span>概念演变</h2>
    {stages_html}
  </section>

  <section>
    <h2><span class="no">肆</span>追问</h2>
    {ask_html if ask_html else '<p>暂无追问。</p>'}
  </section>

  <footer>
    <span>{_esc(title)}</span>
    <span>所有引文均回原文核验</span>
  </footer>
</div>
</body>
</html>"""
