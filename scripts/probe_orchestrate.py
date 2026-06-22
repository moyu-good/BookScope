"""agent 模式端到端 live 验:上传三国 → 打 orchestrate SSE → 看规划 + 综合 + 证据。

验 WP-agent-mode §1 成功标准:① 模糊/跨维度目标规划出合理的功能组合;
② 综合每条结论挂得到原文(evidence-first)。

读仓库根 .env 的 key,走本地后端(BASE)。跑法:python scripts/probe_orchestrate.py
不内联 key、不入库产物。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

BASE = "http://127.0.0.1:8000"
KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
BOOK = Path("_demo_book/sanguo.epub")
GOAL = "帮我理清三国主要人物分属哪几个阵营、各阵营核心人物之间是什么关系"


def upload() -> str:
    with BOOK.open("rb") as fh:
        files = {"file": ("sanguo.epub", fh, "application/epub+zip")}
        form = {
            "book_title": "三国演义", "language": "zh",
            "provider": "deepseek", "api_key": KEY, "model": "deepseek-v4-flash",
        }
        r = requests.post(BASE + "/api/books/upload", files=files, data=form, timeout=900)
    r.raise_for_status()
    return r.json()["session_id"]


def main() -> None:
    if not KEY:
        print("ERROR: 没有 DEEPSEEK_API_KEY(.env)")
        return
    print("上传三国 ...")
    sid = upload()
    print(f"  session={sid}")
    body = {
        "book_session_id": sid, "provider": "deepseek",
        "api_key": KEY, "model": "deepseek-v4-flash", "goal": GOAL,
    }
    print(f"目标: {GOAL}\n打 orchestrate SSE(会跑几个分析、几分钟)...\n")

    events: list[tuple[str | None, object]] = []
    with requests.post(BASE + "/api/agent/orchestrate", json=body, stream=True, timeout=1800) as resp:
        if resp.status_code != 200:
            print(f"ERROR {resp.status_code}: {resp.text[:600]}")
            return
        ev: str | None = None
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                raw = line[5:].strip()
                try:
                    payload: object = json.loads(raw)
                except Exception:
                    payload = raw
                events.append((ev, payload))
                if ev == "step" and isinstance(payload, dict):
                    print(f"  · step 跑完: {payload.get('feature')}")

    by: dict[str, list[object]] = {}
    for e, p in events:
        by.setdefault(e or "?", []).append(p)

    print("\n=== plan(规划挑了啥)===")
    for p in by.get("plan", []):
        print(json.dumps(p, ensure_ascii=False)[:700])
    print(f"\n=== 跑了 {len(by.get('step', []))} 个功能 ===")
    for p in by.get("step", []):
        if isinstance(p, dict):
            print(f"  {p.get('feature')}: {str(p.get('summary'))[:60]}")

    print("\n=== synthesis(综合 + 证据)===")
    for p in by.get("synthesis", []):
        if not isinstance(p, dict):
            print("  非 dict:", str(p)[:300]); continue
        text = p.get("synthesis") or p.get("text") or ""
        cites = p.get("citations") or []
        print("综合文(头 500):", (text if isinstance(text, str) else json.dumps(text, ensure_ascii=False))[:500])
        with_snip = sum(1 for c in cites if isinstance(c, dict) and (c.get("snippet") or c.get("evidence")))
        verified = sum(1 for c in cites if isinstance(c, dict) and c.get("verified"))
        print(f"citations: {len(cites)} 条 | 带原文 {with_snip} | verified {verified}")
        for c in cites[:3]:
            if isinstance(c, dict):
                show = {k: c.get(k) for k in ("chapter", "verified", "snippet", "evidence") if c.get(k) is not None}
                print("  例:", json.dumps(show, ensure_ascii=False)[:220])

    if by.get("error"):
        print("\n=== ERROR 事件 ===")
        for p in by["error"]:
            print(" ", json.dumps(p, ensure_ascii=False)[:300] if isinstance(p, dict) else str(p)[:300])
    print(f"\n总事件 {len(events)} | 事件类型: {dict((k, len(v)) for k, v in by.items())}")


if __name__ == "__main__":
    main()
