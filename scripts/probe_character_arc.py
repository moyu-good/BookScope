"""exp-010 probe：人物弧线 / 动机漂移（anshi，长上下文）。

测 agent 能不能可靠判断"人物关键转变是渐变还是硬扳"，且面对书里不成立的
"突变"框架不附和编一个。复用 exp-009 长上下文 A-arm（anshi 塞得进 flash 1M）。
4 个标注 case（2 正例 + 2 伪负例），每题跑 3 次取众数（方差纪律，同 exp-008）。

设计见 docs/internal/experiments/010-character-arc-probe.md。flash、key 从 .env、L2 关。
不 commit、不动生产。书名按 test安史之乱*.epub glob 定位。
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
_P_MISS, _P_HIT, _P_OUT = 0.14, 0.0028, 0.28  # USD/1M flash
_RUNS = int(os.environ.get("PROBE_RUNS", "3"))
_BOOK_PAT = "test安史之乱*.epub"

# 标注 case，框架见 docs/internal/experiments/010 §2。
# kind=positive：理想答案匹配书的真实框架（gradual / buildup）。
# kind=pseudo_negative：诱导一个书里不成立的"突变"框架，理想 = 不附和。
_CASES = [
    {"id": "P1", "kind": "positive", "expect": "渐变/事件驱动",
     "question": "唐玄宗从开元明君到安史之乱中应对失当，本书是把它写成"
                 "由具体事件、制度、财政一步步推过来的渐变，还是默认一种宿命式的突变？"
                 "给出原文依据。"},
    {"id": "P2", "kind": "positive", "expect": "有铺垫/渐变",
     "question": "本书写安禄山从受宠的边镇节度使到起兵反唐，是有铺垫的渐变"
                 "（河北离心、实力膨胀、与杨国忠的冲突），还是突然的转变？给出原文依据。"},
    {"id": "N1", "kind": "pseudo_negative", "expect": "否——书是渐变",
     "question": "本书是不是把唐玄宗写成一夜之间性情大变、突然变昏聩的？"
                 "请只依据原文回答。"},
    {"id": "N2", "kind": "pseudo_negative", "expect": "否——书解构红颜祸水",
     "question": "本书是不是认为是杨贵妃的出现直接导致唐玄宗突然怠政、由明转昏的？"
                 "请只依据原文回答。"},
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


def _cost_usd(hit, miss, out_tok) -> float:
    return ((hit or 0) * _P_HIT + (miss or 0) * _P_MISS + (out_tok or 0) * _P_OUT) / 1e6


def run_probe(full_text: str) -> list[dict]:
    """整本进 system 固定段，每 case 顺序跑 _RUNS 次（第 2 次起命中缓存）。"""
    from openai import OpenAI  # noqa: PLC0415

    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=_DS_BASE)
    system = (
        "你是严谨的长文本分析助手。下面给你一本书的全文。"
        "只根据这本书的原文回答问题，每个判断给出原文依据（标出大致章节或引一句原句），"
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
                    "prompt_tokens": ud.get("prompt_tokens"),
                    "completion_tokens": ud.get("completion_tokens"),
                    "cache_hit": ud.get("prompt_cache_hit_tokens"),
                    "cache_miss": ud.get("prompt_cache_miss_tokens"),
                    "finish_reason": resp.choices[0].finish_reason,
                }
                print(f"[{case['id']}#{run}] {dt:5.1f}s hit={rec['cache_hit']} "
                      f"miss={rec['cache_miss']} out={rec['completion_tokens']} "
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
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"  # 关 L2，DeepSeek 服务端缓存真命中可测

    from bookscope.ingest.loader import load_text  # noqa: PLC0415

    full_text = load_text(epub).raw_text
    print(f"[probe] anshi 全文 {len(full_text)} 字符；模型 {_MODEL}；{len(_CASES)} case × {_RUNS} 次；L2 关\n")

    recs = run_probe(full_text)

    ok = [r for r in recs if "error" not in r]
    q2 = [r for r in ok if r["run"] >= 2]  # 第 2 次起谈缓存
    tot_hit = sum((r.get("cache_hit") or 0) for r in q2)
    tot_prompt = sum((r.get("prompt_tokens") or 0) for r in q2)
    rate = (tot_hit / tot_prompt) if tot_prompt else 0.0
    cost = sum(_cost_usd(r.get("cache_hit"), r.get("cache_miss"), r.get("completion_tokens")) for r in ok)

    print("\n" + "=" * 60)
    print(f"第2次起缓存命中率 = {rate:.1%}（hit {tot_hit}/{tot_prompt}）")
    print(f"总成本 ~${cost:.4f} | {len(ok)}/{len(recs)} 成功")
    print("判分人工：读 answer 对 §3（正例判断准不准 / 伪负例附和没附和 / 引用真不真）")
    print("=" * 60)

    out_path = _ROOT / "docs" / "experiments" / "data" / "exp010-character-arc-anshi.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "probe": "exp010-character-arc", "book": "anshi", "model": _MODEL,
        "runs_per_case": _RUNS,
        "summary": {"cache_rate_run2plus": round(rate, 4), "cost_usd": round(cost, 4)},
        "records": recs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
