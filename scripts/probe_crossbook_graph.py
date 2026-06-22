"""跨书验穷尽化人物/概念图:上传一本真书 → 跑 /api/agent/character-graph → 看边数/节点。

验 1.4 输出穷尽化对**不同题材的真书**都成立(不是只修三国):历史小说走 person、
理论书走 concept。用 tests/file/ 里的真书,别自己造。

跑法:python scripts/probe_crossbook_graph.py "<epub 路径>" [person|concept]
读仓库根 .env 的 key,走本地后端。不内联 key、不入库产物。
"""

from __future__ import annotations

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
MODEL = "deepseek-v4-flash"


def main() -> int:
    if not KEY:
        print("ERROR: 没有 DEEPSEEK_API_KEY(.env)")
        return 1
    if len(sys.argv) < 2:
        print("用法: python scripts/probe_crossbook_graph.py <epub 路径> [person|concept]")
        return 1
    path = Path(sys.argv[1])
    unit = sys.argv[2] if len(sys.argv) > 2 else "person"
    if not path.exists():
        print(f"ERROR: 找不到 {path}")
        return 1

    print(f"上传 {path.name} …")
    with path.open("rb") as fh:
        files = {"file": (path.name, fh, "application/epub+zip")}
        form = {
            "book_title": path.stem, "language": "zh",
            "provider": "deepseek", "api_key": KEY, "model": MODEL,
        }
        r = requests.post(BASE + "/api/books/upload", files=files, data=form, timeout=900)
    if r.status_code != 200:
        print(f"上传失败 {r.status_code}: {r.text[:300]}")
        return 1
    sid = r.json()["session_id"]
    meta = r.json()
    print(f"  session={sid} | chunks={meta.get('chunk_count')} | 角色={meta.get('character_count')}")

    print(f"跑 exhaustive {unit} 图(逐段并发,可能 1-2 分钟)…")
    body = {
        "book_session_id": sid, "unit": unit, "provider": "deepseek",
        "api_key": KEY, "model": MODEL,
    }
    g = requests.post(BASE + "/api/agent/character-graph", json=body, timeout=900)
    if g.status_code != 200:
        print(f"抽图失败 {g.status_code}: {g.text[:300]}")
        return 1
    d = g.json()
    nodes, edges, tr = d["nodes"], d["edges"], d.get("trace", {})
    print(f"\n=== {path.stem} · {unit} ===")
    print(f"节点 {len(nodes)} | 边 {len(edges)} | verified {tr.get('verified_edges')} | 旧单次帽=30")
    print("节点头 30:", "、".join(nodes[:30]))
    print("边样例:")
    for e in edges[:10]:
        print(f"  {e['source']} —{e['relation']}— {e['target']} | v {e.get('verified')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
