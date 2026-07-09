"""学者立场谱"可行性 probe(exp033):理论书里引的学者,能不能靠**本书原文**摆到本书的
核心争论轴上——且不靠模型训练里认识这些名人硬编。这是给理论书做新镜头(替掉不适配的
立场格局)前的 evidence-first 命门闸。

背景:立场格局是叙事镜头(阵营 + 命运),套理论书别扭(被引学者没处境、没二元阵营)。
option 2 = 给理论书做合身镜头「学者立场谱」:书跟哪些思想家对话、各自站在本书核心争论的哪一极。
但这些学者(科尔奈 / 诺斯 / 张五常…)模型训练里就认识,直接问必背常识 → 破 evidence-first。
所以先验:开放抽取 + 客观查两件事。

依托(prior-art,非发明):
- Stance detection(SemEval-2016 T6):对 target 判 favor/against/**none**;none 类治"只提名没讲立场"。
- Citation function(Teufel)/ 引文情感(Athar):本书对被引者是支持 / 对立 / 借用。
- Toulmin(已用于 character_stance):claim + grounds(原文)。

方法(制内市场公开书,整本进长上下文,flash,L2 关):一次调用让模型
①定本书自己的核心争论轴(用本书的话);②开放抽取书里对话的学者,逐个标 stance_stated,
有立场的给 pole + **逐字原文引文** + brief;③对额外塞的**假学者名**,必须标 stance_stated=false。

三把尺子(构念效度):
1. 能力:抽出的有立场学者是本书真讨论的(人工眼校 plausibility)。
2. **evidence-first 命门(硬闸)**:每条立场的 quote 必须在原书里找得到(strict 逐字 + loose 归一)。
   grounding 率目标 ~100%;编了书里没有的引文 = 幻觉。
3. **抗附和(硬闸)**:塞的假名字,模型判 stance_stated=false;编出立场 = 假阳性。假阳性率 ≤ 20%。

go/no-go:grounding≥~90% + 假学者全被拒(假阳性≤20%)+ 轴和学者集眼校靠谱 → GO 设计 + 建
「学者立场谱」后端。grounding 低 / 假名字被编立场 → NO-GO,回去想别的(或退到只做"被引学者名册")。
flash,key .env,L2 关。不 commit 生产、不动生产码。
"""
from __future__ import annotations

import json
import os
import re
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
_BOOK_PAT = "test制内市场*.epub"
_MAX_TOKENS = 12000  # 密集理论书 + 输出带原文引文;flash reasoning 挤 max_tokens,给够免 length 空返

# 塞进去的假学者名(书里绝不可能有;模型若给出立场 = 凭常识编 = 破 evidence-first)。
# 取"像真经济学家但查无此人"的名,别用一眼假的(那太好拒)。
_FAKE_NAMES = ["范德海姆", "柯立芝·瓦尔多", "李慕白教授"]


def _parse(raw: str):
    from bookscope.agent.utils.json_parsing import strip_code_fence
    txt = strip_code_fence(raw or "")
    try:
        obj = json.loads(txt)
        if isinstance(obj, dict):
            return obj
    except Exception:  # noqa: BLE001
        pass
    i, j = txt.find("{"), txt.rfind("}")
    if 0 <= i < j:
        try:
            return json.loads(txt[i : j + 1])
        except Exception:  # noqa: BLE001
            return None
    return None


def _norm(s: str) -> str:
    """归一:去空白 + 统一标点(繁简不动,先看引号 / 省略号 / 括号差异),给 loose grounding 用。"""
    s = s or ""
    s = re.sub(r"\s+", "", s)
    trans = str.maketrans({
        "“": "\"", "”": "\"", "‘": "'", "’": "'", "，": ",", "。": ".",
        "；": ";", "：": ":", "（": "(", "）": ")", "、": ",", "…": ".",
        "—": "-", "《": "<", "》": ">",
    })
    return s.translate(trans)


def _grounded(quote: str, full: str, full_norm: str) -> tuple[bool, bool]:
    """(strict 逐字子串, loose 归一后前 12 字子串)。省略号 / 引号差异靠 loose 兜。"""
    q = (quote or "").strip()
    if len(q) < 6:
        return (False, False)
    strict = q in full
    qn = _norm(q)
    # 引文可能带省略号跨断;取归一后最长的一段(按省略号切)找命中,或前 12 字
    segs = [seg for seg in re.split(r"\.{2,}|\.\.\.|…", _norm(quote)) if len(seg) >= 8]
    loose = False
    probe_seg = max(segs, key=len) if segs else qn
    if len(probe_seg) >= 8:
        loose = probe_seg[: max(12, len(probe_seg) // 2)] in full_norm or probe_seg in full_norm
    return (strict, loose)


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

    from bookscope.ingest.book_chunker import chunk_book
    from bookscope.ingest.loader import load_text

    book = load_text(str(found[0]))
    full_text = book.raw_text
    full_norm = _norm(full_text)
    n_chunks = len(chunk_book(book))
    print(f"[probe] {found[0].name} {len(full_text)} 字符 {n_chunks} chunk;"
          f"假名字 {len(_FAKE_NAMES)} 个;L2 关\n")

    preamble = (
        "你是严谨的学术著作立场分析助手。下面给你一本理论书的全书原文。\n"
        "任务:这本书在跟哪些学者 / 思想家对话?各自站在**本书核心争论**的哪一极?\n"
        "铁律(违反即失败):\n"
        "1. 只据本书原文判。**不许用你自己知道的这些学者的观点**——哪怕你知道某人主张什么,"
        "本书没写就不算。每条立场必须能在原文里找到刻画他立场的**原句**。\n"
        "2. 先定这本书自己的核心争论轴:一条,两极(pole_a / pole_b),用本书的话概括。\n"
        "3. 逐个学者:stance_stated=本书有没有明说 / 刻画他的立场(true/false)。"
        "只提到名字 / 引用数据、没讲立场 = false,**这种绝不许编立场**。\n"
        "4. 有立场(true)才给:pole(a/b/中)+ quote(本书原文里刻画其立场的原句,逐字照抄,别改字)+ brief。\n"
        "5. 我在末尾额外点名的人,若本书没刻画其立场,老实标 stance_stated=false,别用常识补。\n\n"
        "=== 全书原文 ===\n"
    )
    fake_line = "、".join(_FAKE_NAMES)
    user = (
        "严格输出 JSON(不要别的话、不要围栏):\n"
        '{"axis":{"pole_a":"","pole_b":"","from_book":"这条轴的依据,用本书原话概括"},'
        '"scholars":[{"name":"","stance_stated":true,"pole":"a|b|中","quote":"本书原文原句","brief":"一句"}]}\n'
        "先把本书真讨论的学者尽量抽全(有立场的、只提名的都列,只提名的 stance_stated=false)。\n"
        f"另外**务必**把这几个名字也各列一项(它们大概率不在书里,那就 stance_stated=false,别编):{fake_line}。"
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
    print(f"[probe] finish_reason={fr} content_len={len(content)} reasoning_len={len(reasoning)} "
          f"用时{dt:.0f}s")
    obj = _parse(content)
    if not isinstance(obj, dict) or not isinstance(obj.get("scholars"), list):
        if fr == "length":
            print("[probe] finish_reason=length:reasoning 挤爆 max_tokens,content 空。"
                  f"当前 max_tokens={_MAX_TOKENS},再调大或让模型少推理。", file=sys.stderr)
        print(f"[probe] 解析不出对象,content 头:\n{content[:300]}", file=sys.stderr)
        return 1

    axis = obj.get("axis") or {}
    scholars = [s for s in obj["scholars"] if isinstance(s, dict)]
    print(f"[probe] 一次调用 {dt:.0f}s;抽到 {len(scholars)} 个学者项\n")
    print(f"核心争论轴:{axis.get('pole_a','?')}  ↔  {axis.get('pole_b','?')}")
    print(f"  依据(本书):{axis.get('from_book','')}\n")

    fake_set = set(_FAKE_NAMES)
    records = []
    n_stated = 0          # 声称有立场的
    n_grounded_strict = 0
    n_grounded_loose = 0
    fake_hits = []        # 假名字被编了立场
    print("=" * 78)
    for s in scholars:
        name = str(s.get("name", "")).strip()
        stated = bool(s.get("stance_stated"))
        pole = s.get("pole", "")
        quote = str(s.get("quote", "") or "")
        is_fake = name in fake_set
        strict = loose = False
        if stated and quote:
            n_stated += 1
            strict, loose = _grounded(quote, full_text, full_norm)
            n_grounded_strict += int(strict)
            n_grounded_loose += int(loose)
        if is_fake and stated:
            fake_hits.append(name)
        tag = "假名" if is_fake else ("有立场" if stated else "只提名")
        g = "" if not (stated and quote) else (" ✓锚" if strict else (" ~锚" if loose else " ✗未锚!"))
        records.append({
            "name": name, "is_fake": is_fake, "stance_stated": stated, "pole": pole,
            "quote": quote, "brief": s.get("brief", ""),
            "grounded_strict": strict, "grounded_loose": loose,
        })
        print(f"[{tag:<5}] {name:<10} pole={str(pole):<4}{g}")
        if stated and quote:
            print(f"         引文: {quote[:70]}")
        if s.get("brief"):
            print(f"         ├ {s['brief'][:70]}")
    print("=" * 78)

    gs = (n_grounded_strict / n_stated * 100) if n_stated else 0.0
    gl = (n_grounded_loose / n_stated * 100) if n_stated else 0.0
    fake_listed = [r["name"] for r in records if r["is_fake"]]
    fp_rate = (len(fake_hits) / len(fake_listed) * 100) if fake_listed else 0.0
    print(f"\n有立场声称 {n_stated} 条 | grounding 逐字 {n_grounded_strict}/{n_stated}={gs:.0f}% "
          f"归一 {n_grounded_loose}/{n_stated}={gl:.0f}%")
    print(f"假学者 {len(fake_listed)} 个被点名,其中被编出立场(假阳性)= {len(fake_hits)} "
          f"{fake_hits} → 假阳性率 {fp_rate:.0f}%")
    print("\n尺子:①轴 + 学者集眼校靠谱 ②grounding(归一)≥~90% ③假阳性≤20%")
    verdict = "GO(可设计学者立场谱后端)" if (gl >= 90 and fp_rate <= 20 and n_stated >= 3) \
        else "NO-GO / 需再验(grounding 低或假名字被编立场)"
    print(f"初判:{verdict}")

    out = _ROOT / "docs" / "internal" / "experiments" / "data" / "exp033-scholar-stance.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "probe": "exp033-scholar-stance", "book": found[0].name, "model": _MODEL,
        "n_chunks": n_chunks, "seconds": round(dt, 1),
        "axis": axis, "fake_names": _FAKE_NAMES,
        "n_stated": n_stated, "grounding_strict_pct": round(gs, 1),
        "grounding_loose_pct": round(gl, 1), "false_positive_pct": round(fp_rate, 1),
        "fake_hits": fake_hits, "verdict": verdict, "records": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
