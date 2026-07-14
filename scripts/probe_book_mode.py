"""叙事型 vs 论述型"二分可行性 probe(exp035):靠书名 + 开头,能不能判一本书是叙事型
(人物 / 情节 / 事件推进)还是论述型(论点 / 概念 / 分析推进)。这是动线整理的根——"历史"标签
太粗,分不出叙事型历史(明朝→人物镜头)和论述型历史(安史 / 经济制裁→概念·学者镜头),导致人物镜头
和思想镜头在同一本书上重叠。判准了,才能按内容只上对应一套镜头。

轻分类(书名 + 开头 ~4000 字,不用长上下文),flash,便宜。对照人工预期,重点看历史书能不能分开。

go/no-go:清晰类(小说→叙事、理论→论述)全对 + 历史书正确分流(明朝叙事 vs 安史论述)+ 复跑稳定
→ GO 建后端加这一维 + 前端按它门控。错分历史 / 不稳 → 调 prompt(加目录信号)再验或 NO-GO。
flash,key .env。不 commit 生产、不动生产码。
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
import bookscope  # noqa: E402,F401 — 触发 .env

_MODEL = os.environ.get("BOOKSCOPE_SMOKE_MODEL", "deepseek-v4-flash")
_DS_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_OPENING_CHARS = 4000
_RUNS = 2  # 复跑看稳不稳

# 文件名子串 → 人工预期(不喂模型,只作对照)。重点:明朝 vs 安史 都是历史、要分开。
_EXPECT = {
    "三国演义": "叙事",
    "明朝那些事儿": "叙事",
    "亏成首富": "叙事",
    "杀死一只知更鸟": "叙事",
    "安史之乱": "论述",
    "制内市场": "论述",
    "底层逻辑": "论述",
    "毛泽东选集": "论述",
}

_SYSTEM = (
    "你是书籍类型判定助手。判断一本书是【叙事型】还是【论述型】:\n"
    "· 叙事型:以人物、情节、事件推进为主(小说、纪实故事、叙事体历史)。\n"
    "· 论述型:以论点、概念、分析、论证推进为主(理论、论文、分析性 / 研究性历史、思想类)。\n"
    "只据给的书名 + 开头判。注意:历史书两类都有——讲故事的叙事型 vs 做分析的论述型,别一律归一类。\n"
    '严格输出 JSON:{"label":"叙事" 或 "论述","reason":"一句依据"}'
)


def _title_from(path: Path) -> str:
    name = path.stem
    for p in ("test", "："):
        if name.startswith(p):
            name = name[len(p):]
    return name.strip()[:60]


def _parse(raw: str):
    from bookscope.agent.utils.json_parsing import (
        extract_first_json_object,
        strip_code_fence,
    )
    obj = extract_first_json_object(strip_code_fence(raw or ""))
    if obj is None:
        return None
    try:
        d = json.loads(obj)
        return d if isinstance(d, dict) else None
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设", file=sys.stderr)
        return 1
    from openai import OpenAI

    from bookscope.ingest.loader import load_text

    books = sorted((_ROOT / "tests" / "file").glob("test*.epub"))
    if not books:
        print("[probe] tests/file 没 epub", file=sys.stderr)
        return 1
    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=_DS_BASE)

    print(f"[probe] {len(books)} 本书;书名 + 开头 {_OPENING_CHARS} 字;{_RUNS} 复跑;model={_MODEL}\n")
    print(f"{'书':<22}{'预期':<5}{'判定(复跑)':<16}{'对?':<4} 理由")
    print("-" * 92)
    records = []
    n_ok = 0
    n_expected = 0
    hist = []  # 历史书专看
    for path in books:
        title = _title_from(path)
        exp = next((v for k, v in _EXPECT.items() if k in path.stem), None)
        try:
            opening = load_text(str(path)).raw_text[:_OPENING_CHARS]
        except Exception as exc:  # noqa: BLE001
            print(f"{title[:20]:<22} 载入失败 {type(exc).__name__}", file=sys.stderr)
            continue
        labels = []
        reason = ""
        for _ in range(_RUNS):
            resp = client.chat.completions.create(
                model=_MODEL,
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": f"书名:{title}\n\n开头:\n{opening}"}],
                temperature=1.0,
                max_tokens=2000,
            )
            d = _parse(resp.choices[0].message.content or "") or {}
            lab = str(d.get("label", "")).strip()
            labels.append("叙事" if "叙事" in lab else ("论述" if "论述" in lab else "?"))
            reason = str(d.get("reason", "") or reason)
        stable = len(set(labels)) == 1
        final = labels[0] if stable else "/".join(labels)
        ok = exp is not None and stable and labels[0] == exp
        if exp is not None:
            n_expected += 1
            n_ok += int(ok)
        mark = "✓" if ok else ("✗" if exp else "—")
        print(f"{title[:20]:<22}{(exp or '—'):<5}{final:<16}{mark:<4} {reason[:36]}")
        rec = {"book": path.stem, "title": title, "expect": exp,
               "labels": labels, "stable": stable, "ok": ok, "reason": reason}
        records.append(rec)
        if "历史" in path.stem or exp and path.stem.count("史"):
            hist.append(rec)
    print("-" * 92)
    acc = (n_ok / n_expected * 100) if n_expected else 0.0
    n_stable = sum(1 for r in records if r["stable"])
    # 历史书专项:明朝(叙事) vs 安史(论述)分开没有
    ming = next((r for r in records if "明朝" in r["book"]), None)
    anshi = next((r for r in records if "安史" in r["book"]), None)
    hist_split = bool(ming and anshi and ming["stable"] and anshi["stable"]
                      and ming["labels"][0] == "叙事" and anshi["labels"][0] == "论述")
    print(f"\n对预期 {n_ok}/{n_expected}={acc:.0f}% | 稳定 {n_stable}/{len(records)} | "
          f"历史书分流(明朝叙事 & 安史论述):{'✓' if hist_split else '✗'}")
    print("尺子:①清晰类全对 ②历史书分开(明朝≠安史)③复跑稳定")
    verdict = ("GO(建后端加维 + 前端门控)" if acc >= 85 and hist_split and n_stable >= len(records) - 1
               else "NO-GO / 调 prompt(加目录信号)再验")
    print(f"初判:{verdict}")

    out = _ROOT / "docs" / "internal" / "experiments" / "data" / "exp035-book-mode.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "probe": "exp035-book-mode", "model": _MODEL, "opening_chars": _OPENING_CHARS,
        "runs": _RUNS, "accuracy_pct": round(acc, 1), "n_stable": n_stable,
        "hist_split": hist_split, "verdict": verdict, "records": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
