"""exp-011 probe：设定一致性 / 前后矛盾（anshi + 控制注入）。

往 anshi 副本注入 2 处干净矛盾（ground truth 已知），测 agent 能不能找到、
且不在没矛盾处编矛盾。复用 exp-010 长上下文形态。每题 3 次取众数。

设计见 docs/internal/experiments/011-consistency-contradiction-probe.md。
flash、key 从 .env、L2 关。不 commit、不动生产。
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
_BOOK_PAT = "test安史之乱*.epub"

# 注入的矛盾：(早段位置比例, 早段句, 晚段位置比例, 晚段句)。
_INJECTIONS = [
    (0.18, "\n（编者注补充：安禄山是个左撇子，平日惯用左手持物。）\n",
     0.72, "\n（另据载，安禄山曾用右手狠狠挥动马鞭督战。）\n"),
    (0.30, "\n（数字补记：安禄山起兵时麾下兵力约十五万。）\n",
     0.76, "\n（后文又称，安禄山起兵时统率的是二十万大军。）\n"),
]

_CASES = [
    {"id": "CP1", "kind": "positive", "expect": "找到左/右手矛盾",
     "question": "本书里关于安禄山惯用左手还是右手，前后描述有没有互相矛盾的地方？"
                 "如有，请把矛盾的两处都引出来。"},
    {"id": "CP2", "kind": "positive", "expect": "找到兵力数字矛盾",
     "question": "本书里关于安禄山起兵时的兵力数字，前后说法一致吗？"
                 "如有不一致，请把不同的说法都引出来。"},
    {"id": "CN1", "kind": "pseudo_negative", "expect": "无矛盾",
     "question": "本书里关于唐玄宗是不是皇帝、他的身份地位，前后有没有自相矛盾的地方？"
                 "只依据原文回答，没有就说没有。"},
    {"id": "CN2", "kind": "pseudo_negative", "expect": "无矛盾",
     "question": "本书里关于安史之乱的主谋是不是安禄山，前后说法有没有冲突？"
                 "只依据原文回答，没有就说没有。"},
]


def _resolve_book() -> str | None:
    found = sorted(_ROOT.glob(_BOOK_PAT))
    return str(found[0]) if found else None


def _inject(text: str) -> str:
    """在指定比例位置的最近换行后插入句子，模拟跨章矛盾。"""
    inserts: list[tuple[int, str]] = []
    for early_p, early_s, late_p, late_s in _INJECTIONS:
        for ratio, sent in ((early_p, early_s), (late_p, late_s)):
            pos = int(len(text) * ratio)
            nl = text.find("\n", pos)
            inserts.append((nl if nl != -1 else pos, sent))
    # 从后往前插，避免位移
    for pos, sent in sorted(inserts, key=lambda x: -x[0]):
        text = text[:pos] + sent + text[pos:]
    return text


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
        "只根据这本书的原文回答问题，每个判断给出原文依据（引出原句）。"
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
                    max_tokens=4000,
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

    raw = load_text(epub).raw_text
    full_text = _inject(raw)
    print(f"[probe] anshi 原文 {len(raw)} → 注入后 {len(full_text)} 字符；"
          f"{len(_CASES)} case × {_RUNS} 次；模型 {_MODEL}\n")

    recs = run_probe(full_text)
    ok = [r for r in recs if "error" not in r]
    print("\n" + "=" * 60)
    print(f"{len(ok)}/{len(recs)} 成功")
    print("判分人工：读 answer 对 §4（正例找没找到植入矛盾 / 伪负例有没有编矛盾 / 引用真不真）")
    print("=" * 60)

    out_path = _ROOT / "docs" / "experiments" / "data" / "exp011-consistency-anshi.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "probe": "exp011-consistency", "book": "anshi", "model": _MODEL,
        "runs_per_case": _RUNS,
        "injections": [{"c1_left_pos": i[0], "c1_right_pos": i[2]} for i in _INJECTIONS[:1]],
        "records": recs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
