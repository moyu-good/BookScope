"""论证骨架树"可行性 probe(exp034):理论书能不能靠**原文**抽出论证结构——中心论点(主脉)+
主要论点 + 各自逻辑角色 + 谁撑谁——且引文锚原文、关系不悬空、别硬造层级。这是把「论点结构」从
平铺编号清单改成骨架树前的 evidence-first 闸。

跟老 probe 的分工:scripts/probe_argument_structure.py(6-17,WP-argument-structure)已验过**平铺
claim 抽取**(引用真实性 ≥90% + 反对主张不编支持=抗附和 GO)。本 probe 只补它没测的**结构层**:
thesis + 逻辑角色 + 论点间支撑关系 + 有没有真层级。

依托(prior-art,非发明):argument mining(Lawrence & Reed 2019;SciArg)——claim/premise +
support/attack 关系抽取;Toulmin(主张 + grounds)。角色集借 argumentation scheme 常见类型。

方法(制内市场公开理论书,整本长上下文,flash,L2 关,max_tokens 12000):一次调用让模型
①定全书中心论点(thesis,本书原话) ②抽主要论点,每个给 role + supports(直接撑/反哪个论点的 id
或 "thesis") + 原文原句 quote + brief。引文核验**复用已上线的 scholar_stance._quote_grounded**
(片段-OR-整书,治 exp022 那种整条子串假摔),probe 跟产品同一把尺子。

三把尺子(构念效度):
1. 能力:主脉 + 论点 + 角色眼校靠谱(人工看树)。
2. **grounding 命门**:每条论点的 quote 片段核锚原文,率 ≥~90%(引文真、论点不是编的)。
3. **结构真不真**:①关系不悬空(supports 端点都在论点集或 thesis) ②不退化成平铺(有挂到别的
   论点的真层级,而非所有论点一律"支撑 thesis"一层——那样树没意义)。

go/no-go:主脉+论点+角色靠谱 + grounding≥~90% + 关系不悬空 + 有真层级 → GO 重建论点结构成骨架树。
grounding 低 / 关系悬空 / 退化平铺 → NO-GO 或调 prompt 再验。不 commit 生产、不动生产码。
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

# 复用已上线、单测过的片段核验(整书 OR 语义),probe 跟产品同一把尺子。
from bookscope.agent.scholar_stance import _norm, _quote_grounded  # noqa: E402

_MODEL = os.environ.get("BOOKSCOPE_SMOKE_MODEL", "deepseek-v4-flash")
_DS_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_BOOK_PAT = "test制内市场*.epub"
_MAX_TOKENS = 12000

_ROLES = {"中心", "前提", "支撑", "递进", "反驳", "论据", "结论"}


def _parse(raw: str):
    from bookscope.agent.utils.json_parsing import (
        extract_first_json_object,
        strip_code_fence,
    )
    txt = strip_code_fence(raw or "")
    obj = extract_first_json_object(txt)
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
    found = sorted((_ROOT / "tests" / "file").glob(_BOOK_PAT))
    if not found:
        print(f"[probe] 理论书没找到({_BOOK_PAT})", file=sys.stderr)
        return 1
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"

    from openai import OpenAI

    from bookscope.ingest.loader import load_text

    book = load_text(str(found[0]))
    full_text = book.raw_text
    full_norm = _norm(full_text)
    print(f"[probe] {found[0].name} {len(full_text)} 字符;L2 关\n")

    preamble = (
        "你是严谨的学术论证分析助手。下面给你一本理论书的全书原文。\n"
        "任务:拆出这本书的**论证骨架**——中心论点 + 主要论点各自的逻辑角色和支撑关系。\n"
        "铁律(违反即失败):\n"
        "1. 只据本书原文判,不臆测、不用书外知识。每条论点必须能在原文找到刻画它的**原句**。\n"
        "2. 先定全书**中心论点**(thesis):作者最核心那句主张,用本书的话概括。\n"
        "3. 抽主要论点,每个给:role(逻辑角色,只从 中心/前提/支撑/递进/反驳/论据/结论 里选)、"
        "supports(它直接**撑**或**反**哪一个,填另一条论点的 id,或填 \"thesis\" 表示直接撑中心论点)、"
        "quote(本书原文里刻画它的原句,逐字照抄)、brief(一句)。\n"
        "4. 只连原文里**真有论证关系**的:别硬造层级,也别把所有论点一律挂到 thesis 凑平。"
        "论点之间有递进 / 支撑 / 反驳的,supports 指向那条论点的 id。\n\n"
        "=== 全书原文 ===\n"
    )
    user = (
        "严格只输出 JSON(不要别的话、不要围栏):\n"
        '{"thesis":{"claim":"中心论点,用本书话概括","quote":"原文原句","from_book":"依据"},'
        '"claims":[{"id":"c1","claim":"","role":"支撑","supports":"thesis|c2|...",'
        '"quote":"本书原文原句","brief":"一句"}]}\n'
        "id 用 c1/c2/... 好让 supports 互相指。尽量抽全主要论点,理清谁撑谁、谁反谁。"
    )

    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=_DS_BASE)
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "system", "content": preamble + full_text},
                  {"role": "user", "content": user}],
        temperature=1.0,
        max_tokens=_MAX_TOKENS,
    )
    dt = time.monotonic() - t0
    choice = resp.choices[0]
    fr = getattr(choice, "finish_reason", None)
    content = choice.message.content or ""
    reasoning = getattr(choice.message, "reasoning_content", None) or ""
    print(f"[probe] finish_reason={fr} content_len={len(content)} reasoning_len={len(reasoning)} {dt:.0f}s")
    obj = _parse(content)
    if not isinstance(obj, dict) or not isinstance(obj.get("claims"), list):
        print(f"[probe] 解析不出对象,content 头:\n{content[:300]}", file=sys.stderr)
        return 1

    thesis = obj.get("thesis") or {}
    claims = [c for c in obj["claims"] if isinstance(c, dict)]
    t_quote = str(thesis.get("quote", "") or "")
    t_grounded = _quote_grounded(t_quote, full_norm) if t_quote else False
    print(f"\n中心论点: {str(thesis.get('claim',''))[:70]}")
    print(f"  {'鉴锚' if t_grounded else '未锚'} 引文: {t_quote[:60]}\n")

    ids = {str(c.get("id", "")).strip() for c in claims if c.get("id")}
    valid_targets = ids | {"thesis", "", "None"}
    n_grounded = 0
    n_dangling = 0
    roles_seen: dict[str, int] = {}
    supports_thesis = 0
    print("=" * 80)
    for c in claims:
        cid = str(c.get("id", "")).strip()
        role = str(c.get("role", "")).strip()
        sup = str(c.get("supports", "") or "").strip()
        quote = str(c.get("quote", "") or "")
        g = _quote_grounded(quote, full_norm) if quote else False
        n_grounded += int(g)
        roles_seen[role] = roles_seen.get(role, 0) + 1
        dangling = sup not in valid_targets
        n_dangling += int(dangling)
        if sup == "thesis":
            supports_thesis += 1
        role_bad = "" if role in _ROLES else " role非法"
        sup_show = sup if not dangling else f"{sup}(悬空)"
        print(f"[{cid:<3}] {'OK' if g else '--'} role={role:<4}{role_bad} ->{sup_show:<8} {str(c.get('claim',''))[:42]}")
        if quote:
            print(f"       引文: {quote[:64]}")
    print("=" * 80)

    n = len(claims)
    gr = (n_grounded / n * 100) if n else 0.0
    non_thesis_rel = sum(
        1 for c in claims if str(c.get("supports", "")).strip() not in ("thesis", "", "None")
    )
    role_variety = len([r for r in roles_seen if r in _ROLES])
    print(f"\n论点 {n} 条 | grounding {n_grounded}/{n}={gr:.0f}% | 悬空关系 {n_dangling} | "
          f"直挂thesis {supports_thesis} | 挂到别的论点(真层级) {non_thesis_rel} | 角色种类 {role_variety}")
    print(f"角色分布: {roles_seen}")
    degenerate = non_thesis_rel == 0
    print("\n尺子:①主脉+论点+角色眼校靠谱 ②grounding>=~90% ③关系不悬空(悬空=0) "
          "④不退化平铺(有挂到别的论点的真层级)")
    verdict = (
        "GO(重建论点结构成骨架树)"
        if (gr >= 90 and n_dangling == 0 and not degenerate and n >= 3 and t_grounded)
        else "NO-GO / 调 prompt 再验(看上面哪条没过)"
    )
    print(f"初判:{verdict}")

    out = _ROOT / "docs" / "internal" / "experiments" / "data" / "exp034-argument-tree.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "probe": "exp034-argument-tree", "book": found[0].name, "model": _MODEL,
        "seconds": round(dt, 1), "thesis": thesis, "thesis_grounded": t_grounded,
        "n_claims": n, "grounding_pct": round(gr, 1), "n_dangling": n_dangling,
        "supports_thesis": supports_thesis, "non_thesis_rel": non_thesis_rel,
        "roles": roles_seen, "degenerate": degenerate, "verdict": verdict, "claims": claims,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
