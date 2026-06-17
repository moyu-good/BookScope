"""exp-013 probe：人物关系图（anshi，长上下文）。

验 agent 能不能抽出可靠的人物关系网（每边带原文出处）+ 不编书里不存在的关系。
关系图=一堆边，每条边当一个 citation 验。3 题 × 3 次。
设计见 docs/internal/experiments/013-character-graph-probe.md。flash、key 从 .env、L2 关。
不 commit、不动生产。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import bookscope  # noqa: E402, F401 —— 触发 .env 自动加载

_MODEL = os.environ.get("BOOKSCOPE_SMOKE_MODEL", "deepseek-v4-flash")
_DS_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_RUNS = int(os.environ.get("PROBE_RUNS", "3"))
# 图输出比单点判断长得多，4000 会截断（run2 截/run3 空=reasoning 吃 token）。
# 抽图类 probe 默认拔到 8000，可 env 覆盖。
_MAX_TOKENS = int(os.environ.get("PROBE_MAX_TOKENS", "8000"))
_BOOK_PAT = "test安史之乱*.epub"

_CASES = [
    {"id": "Q1", "kind": "graph", "expect": "覆盖已知核心关系 + 每边带证据 + 复现",
     "question": "请通读全书，梳理主要人物之间的关系网：列出谁和谁有关系、是什么关系"
                 "（君臣 / 政敌 / 同盟 / 父子 / 亲族 / 同僚 等），**每一条关系都给出原文依据**"
                 "（引一句原文或指出具体章节情节）。书里没有直接关系的人物不要硬连。"},
    {"id": "N1", "kind": "pseudo_negative", "expect": "否——无直接交集",
     "question": "郭子仪和杨贵妃在本书里有没有直接关系或交集？只依据原文回答，没有就说没有。"},
    {"id": "N2", "kind": "pseudo_negative", "expect": "否——无直接交集",
     "question": "李泌和安禄山在本书里有没有直接交集或往来？只依据原文回答，没有就说没有。"},
]


def _resolve_book() -> str | None:
    found = sorted(_ROOT.glob(_BOOK_PAT))
    return str(found[0]) if found else None


def _usage_dict(usage) -> dict:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    try:
        return dict(usage)
    except Exception:  # noqa: BLE001
        return {k: getattr(usage, k) for k in dir(usage) if not k.startswith("_")}


def run_probe(full_text: str) -> list[dict]:
    from openai import OpenAI  # noqa: PLC0415

    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=_DS_BASE)
    system = (
        "你是严谨的长文本分析助手。下面给你一本书的全文。"
        "只根据这本书的原文回答问题，每个判断给出原文依据（引一句原句或指出章节），"
        "原文里找不到依据的不要编，宁可说没有。\n\n=== 全书原文 ===\n" + full_text
    )
    out = []
    for case in _CASES:
        for run in range(1, _RUNS + 1):
            t0 = time.monotonic()
            try:
                resp = client.chat.completions.create(
                    model=_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": case["question"]},
                    ],
                    temperature=1.0,
                    max_tokens=_MAX_TOKENS,
                )
                dt = time.monotonic() - t0
                ud = _usage_dict(resp.usage)
                ans = resp.choices[0].message.content or ""
                rec = {
                    "id": case["id"], "kind": case["kind"], "expect": case["expect"],
                    "run": run, "latency_s": round(dt, 1), "answer": ans,
                    "completion_tokens": ud.get("completion_tokens"),
                    "finish_reason": resp.choices[0].finish_reason,
                }
                print(f"[{case['id']}#{run}] {dt:5.1f}s out={rec['completion_tokens']} "
                      f"finish={rec['finish_reason']} len={len(ans)}")
            except Exception as e:  # noqa: BLE001
                rec = {"id": case["id"], "kind": case["kind"], "run": run, "error": repr(e)}
                print(f"[{case['id']}#{run}] ERROR {e!r}", file=sys.stderr)
            out.append(rec)
    return out


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设置（应从 .env 读）", file=sys.stderr)
        return 1
    epub = _resolve_book()
    if not epub:
        print(f"[probe] anshi epub 没找到（仓库根放 {_BOOK_PAT}）", file=sys.stderr)
        return 1
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"

    from bookscope.ingest.loader import load_text  # noqa: PLC0415

    full_text = load_text(epub).raw_text
    print(f"[probe] anshi 全文 {len(full_text)} 字符；{len(_CASES)} case × {_RUNS} 次；模型 {_MODEL}\n")

    recs = run_probe(full_text)
    ok = [r for r in recs if "error" not in r]
    print("\n" + "=" * 60)
    print(f"{len(ok)}/{len(recs)} 成功")
    print("判分人工：Q1 看收敛(核心关系全不全)+每边证据率+复现；N1/N2 看编没编不存在的关系")
    print("=" * 60)

    out_path = _ROOT / "docs" / "experiments" / "data" / "exp013-character-graph-anshi.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "probe": "exp013-character-graph", "book": "anshi", "model": _MODEL,
        "runs_per_case": _RUNS, "records": recs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
