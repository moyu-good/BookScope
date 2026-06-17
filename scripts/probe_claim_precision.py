"""exp-015 probe：claim precision（引用-论断 entailment）。

验 LLM-judge 能不能可靠判"这段原文撑不撑得起这个论断"：真支撑别误伤（命根子）、
错配要揪出（召回）。手工标注 10 对（4 真支撑 + 6 错配涵盖三型），judge 各 3 次。
judge 只看一对、不需全书，便宜。设计见 docs/internal/experiments/015-claim-precision-probe.md。
flash、key 从 .env。不 commit、不动生产。
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import bookscope  # noqa: E402, F401

_MODEL = os.environ.get("BOOKSCOPE_SMOKE_MODEL", "deepseek-v4-flash")
_DS_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_RUNS = int(os.environ.get("PROBE_RUNS", "3"))

# 标注对：expect = 理想判定。kind 标错配子型，便于看判别力。
_PAIRS = [
    # --- 正例：真支撑（应 supported，误判即假阳性）---
    {"id": "P1", "expect": "supported", "kind": "genuine",
     "claim": "安禄山身兼范阳、平卢、河东三镇节度使。",
     "snippet": "安禄山是唐帝国的范阳、平卢、河东三镇节度使，手握重兵。"},
    {"id": "P2", "expect": "supported", "kind": "genuine",
     "claim": "安禄山是被亲生儿子安庆绪杀害的。",
     "snippet": "他是被亲生儿子安庆绪联合身边的亲信严庄一起暗杀的。"},
    {"id": "P3", "expect": "supported", "kind": "genuine",
     "claim": "本书认为杨贵妃没有实质性的政治权力。",
     "snippet": "杨贵妃只是一个花瓶而已，她和她的姐姐们很少获得实质性的政治权力。"},
    {"id": "P4", "expect": "supported", "kind": "genuine",
     "claim": "唐玄宗催促哥舒翰出潼关决战。",
     "snippet": "唐玄宗于是开始派使节催促哥舒翰出潼关东进决战。"},
    # --- 负例·完全无关（应 unsupported，最易揪）---
    {"id": "N1", "expect": "unsupported", "kind": "无关",
     "claim": "安禄山身兼范阳、平卢、河东三镇节度使。",
     "snippet": "杨贵妃只是一个花瓶而已，很少获得实质性的政治权力。"},
    {"id": "N2", "expect": "unsupported", "kind": "无关",
     "claim": "马嵬驿之变中杨贵妃被赐死。",
     "snippet": "府兵制起源于西魏，是一种兵农合一的军事制度。"},
    # --- 负例·提到但不支撑（因果未建立，难项）---
    {"id": "N3", "expect": "unsupported", "kind": "提到不撑",
     "claim": "杨贵妃的出现直接导致了唐玄宗怠政。",
     "snippet": "唐玄宗十分宠爱杨贵妃，两人感情深厚。"},
    {"id": "N4", "expect": "unsupported", "kind": "提到不撑",
     "claim": "府兵制的崩溃直接导致了安禄山起兵叛乱。",
     "snippet": "府兵制在玄宗朝中后期逐渐走向崩溃。"},
    # --- 负例·过度声称（号称/矛盾被夸成确实，难项）---
    {"id": "N5", "expect": "unsupported", "kind": "过度声称",
     "claim": "安禄山起兵时确实拥有二十万大军。",
     "snippet": "安禄山起兵时兵力约十五万，对外号称二十万。"},
    {"id": "N6", "expect": "unsupported", "kind": "过度声称",
     "claim": "郭子仪和李光弼关系亲密、配合无间。",
     "snippet": "郭子仪和李光弼两人互不服气，谁都统率不动对方。"},
]

_JUDGE_SYSTEM = (
    "你是严谨的事实核查助手。下面给你一个『论断』和一段『原文』。"
    "判断这段原文能不能真正支撑这个论断的核心主张。只输出 JSON（不要别的话）："
    '{"verdict": "supported" 或 "unsupported", "reason": "一句话理由"}。'
    "判定标准：原文必须真正支撑论断的核心主张才算 supported；"
    "只是提到了相关词语、或论断比原文说得更绝对（如把『号称』当『确实』、把『提到』当『因果』），"
    "都算 unsupported。"
)


def _judge(client, claim: str, snippet: str) -> tuple[str, str]:
    resp = client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": f"论断：{claim}\n原文：{snippet}"},
        ],
        temperature=1.0,
        max_tokens=2048,
    )
    raw = (resp.choices[0].message.content or "").strip()
    txt = raw
    if "```" in txt:
        txt = txt.split("```")[1] if txt.count("```") >= 2 else txt
        txt = txt.removeprefix("json").strip()
    try:
        obj = json.loads(txt[txt.find("{"): txt.rfind("}") + 1])
        return str(obj.get("verdict", "?")).lower(), str(obj.get("reason", ""))[:80]
    except Exception:  # noqa: BLE001
        low = raw.lower()
        if "unsupported" in low:
            return "unsupported", raw[:60]
        if "supported" in low:
            return "supported", raw[:60]
        return "?", raw[:60]


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设置", file=sys.stderr)
        return 1
    from openai import OpenAI  # noqa: PLC0415

    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=_DS_BASE)
    print(f"[probe] {len(_PAIRS)} 对 × {_RUNS} 次；模型 {_MODEL}\n")

    records = []
    for pair in _PAIRS:
        verdicts = []
        for _ in range(_RUNS):
            t0 = time.monotonic()
            try:
                v, reason = _judge(client, pair["claim"], pair["snippet"])
            except Exception as e:  # noqa: BLE001
                v, reason = "ERROR", repr(e)[:60]
            verdicts.append(v)
            print(f"[{pair['id']:3} {pair['kind']:6}] {time.monotonic()-t0:4.1f}s "
                  f"→ {v:12} {reason}")
        mode = Counter(verdicts).most_common(1)[0][0]
        ok = mode == pair["expect"]
        records.append({**{k: pair[k] for k in ("id", "expect", "kind")},
                        "verdicts": verdicts, "mode": mode, "correct": ok})
        print(f"     众数={mode} 期望={pair['expect']} {'✓' if ok else '✗'}\n")

    genuine = [r for r in records if r["kind"] == "genuine"]
    neg = [r for r in records if r["kind"] != "genuine"]
    fp = sum(1 for r in genuine if r["mode"] == "unsupported")
    recall = sum(1 for r in neg if r["mode"] == "unsupported")
    print("=" * 60)
    print(f"假阳性（正例被判 unsupported）= {fp}/{len(genuine)}")
    print(f"召回（负例揪出 unsupported）   = {recall}/{len(neg)}")
    for kind in ("无关", "提到不撑", "过度声称"):
        sub = [r for r in neg if r["kind"] == kind]
        hit = sum(1 for r in sub if r["mode"] == "unsupported")
        print(f"  - {kind}: {hit}/{len(sub)}")
    print("=" * 60)

    out_path = _ROOT / "docs" / "experiments" / "data" / "exp015-claim-precision.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {"probe": "exp015-claim-precision", "model": _MODEL, "runs_per_pair": _RUNS,
         "false_positive": f"{fp}/{len(genuine)}", "recall": f"{recall}/{len(neg)}",
         "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
