"""立场判定"做硬"前置 probe(exp024):争议判断能不能正反取证、不 cherry-pick、争议度校得准。

背景:⑧ 立场象限原来把"曹操是否尊汉"这种千年争议压成一个确定分(-5)+ 单句证据 —— 拍脑袋 +
假精确 + 单证据,犯"算法依托真实"机制层。改用 Toulmin(主张 + 正据 + 反据 + 把握/争议度)。
先 probe 验这套抽取靠不靠谱,再改图。

方法(接 exp022 长上下文抽取 + 构念效度 probe playbook):整本进长上下文,逼模型对每个人
分开列 pro(尊汉扶主证据)/ con(篡逆自立证据),给 net(综合倾向)+ dispute(争议度)。
每条 pro/con evidence 过 verify_citations 核锚定。

四项核验:
1. 平衡取证:真争议的人(曹操)pro/con 两边都拿出硬证据(≥2/≥2),不是一边倒。
2. 争议度校准:曹操 dispute 明显高于清晰的(诸葛亮/董卓/关羽)。
3. 不假平衡:清晰的人(诸葛亮尊汉)con 该空/弱,模型不为显平衡硬编。
4. 锚定:pro/con evidence 都锚得住原文。

go/no-go:四项过 → GO 建 Toulmin 立场抽取 + 改 ⑧ 纵轴(争议点带不确定);否则机制不牢,再想。
三国公版,数据可留。flash,key 从 .env,L2 关。不 commit、不动生产。
"""
from __future__ import annotations
import json, os, sys, time
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
_BOOK_PAT = "test三国演义*.epub"
_MAX_TOKENS = 3000

# 六人:争议度的人工预期(不喂模型,只作校准对照)
_FIGURES = ["曹操", "诸葛亮", "董卓", "孙权", "关羽", "司马懿"]
_EXPECT_DISPUTE = {
    "曹操": "高（尊汉 vs 篡逆千年争议）",
    "诸葛亮": "低（明确尊汉扶主）",
    "董卓": "低（明确篡逆）",
    "孙权": "中（割据自立、非尊汉非直接篡汉）",
    "关羽": "低（明确尊汉，只降汉帝）",
    "司马懿": "中高（专权奠基篡位，但生前未篡）",
}

_PREAMBLE = (
    "你是严谨的史书人物立场判定助手。下面给你《三国演义》全书原文。\n"
    "任务：判定指定人物在「尊汉扶主 ↔ 篡逆自立」这条轴上的立场。\n"
    "铁律：\n"
    "1. 正反两方证据都要从原文里找：尊汉扶主的证据(pro) 与 篡逆自立的证据(con)，分开列。\n"
    "2. 每条 evidence 必须是原文逐字片段（原样摘录）。哪一方原文里确实找不到，就列空数组 []，"
    "绝不为了显得平衡而硬编、绝不编原文没有的话。\n"
    "3. net = 综合倾向整数（-5 篡逆自立 .. 0 中立 .. +5 尊汉扶主）。\n"
    "4. dispute = 争议度整数(0-5)：当且仅当正反两方都有硬证据、真两难时才高；一边倒就低。\n\n"
    "=== 《三国演义》全书原文 ===\n"
)
_INSTR = (
    "判定人物「{name}」。严格输出 JSON（不要别的话、不要 markdown 围栏）：\n"
    '{{\n  "name": "{name}",\n'
    '  "pro": [{{"原文": "尊汉扶主的原文逐字片段", "说明": "为何算尊汉"}}],\n'
    '  "con": [{{"原文": "篡逆自立的原文逐字片段", "说明": "为何算篡逆自立"}}],\n'
    '  "net": 综合倾向整数-5到5,\n'
    '  "dispute": 争议度整数0到5,\n'
    '  "dispute_reason": "为何是这个争议度（一句）"\n}}\n'
    "pro / con 各列原文真有的（0-6 条）；哪方没有就空数组。每条 evidence 能在原文逐字找到。"
)


def _resolve_book():
    found = sorted((_ROOT / "tests" / "file").glob(_BOOK_PAT))
    return str(found[0]) if found else None


def _parse(raw: str):
    from bookscope.agent.utils.json_parsing import extract_first_json_object, strip_code_fence
    obj = extract_first_json_object(strip_code_fence(raw))
    try:
        return json.loads(obj) if obj else None
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设", file=sys.stderr)
        return 1
    epub = _resolve_book()
    if not epub:
        print("[probe] 三国 epub 没找到", file=sys.stderr)
        return 1
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"

    from openai import OpenAI
    from bookscope.agent.citation_check import build_evidence_map, verify_citations
    from bookscope.ingest.book_chunker import chunk_book
    from bookscope.ingest.loader import load_text

    book = load_text(epub)
    full_text = book.raw_text
    chunks = chunk_book(book)
    evmap = build_evidence_map(
        [{"chunk_id": f"c-{c.index}", "chapter": c.chapter, "text": c.text} for c in chunks]
    )
    print(f"[probe] 三国 {len(full_text)} 字符 {len(chunks)} chunk;{len(_FIGURES)} 人;L2 关\n")

    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=_DS_BASE)
    system = _PREAMBLE + full_text
    records = []
    for name in _FIGURES:
        t0 = time.monotonic()
        try:
            resp = client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": _INSTR.format(name=name)},
                ],
                temperature=1.0,
                max_tokens=_MAX_TOKENS,
            )
            prof = _parse(resp.choices[0].message.content or "")
            pro = (prof or {}).get("pro") or []
            con = (prof or {}).get("con") or []
            # 核验 pro/con evidence
            cits = [{"snippet": e.get("原文", ""), "chapter": None, "_side": "pro"} for e in pro if isinstance(e, dict)]
            cits += [{"snippet": e.get("原文", ""), "chapter": None, "_side": "con"} for e in con if isinstance(e, dict)]
            verify_citations(cits, evmap)
            pro_ok = sum(1 for c in cits if c["_side"] == "pro" and c.get("match_type") != "none")
            con_ok = sum(1 for c in cits if c["_side"] == "con" and c.get("match_type") != "none")
            rec = {
                "name": name, "profile": prof, "anchored": cits,
                "n_pro": len(pro), "n_con": len(con),
                "pro_verified": pro_ok, "con_verified": con_ok,
                "net": (prof or {}).get("net"), "dispute": (prof or {}).get("dispute"),
            }
            print(f"[{name}] {time.monotonic()-t0:4.0f}s  pro {len(pro)}(锚{pro_ok}) / con {len(con)}(锚{con_ok})  "
                  f"net={rec['net']} dispute={rec['dispute']}  | 预期争议 {_EXPECT_DISPUTE[name]}")
        except Exception as e:  # noqa: BLE001
            rec = {"name": name, "error": repr(e)}
            print(f"[{name}] ERROR {e!r}", file=sys.stderr)
        records.append(rec)

    print("\n" + "=" * 66)
    print("四项核验(人工读数据判):")
    print("1 平衡取证:曹操 pro/con 是否都 ≥2 硬证据")
    print("2 争议度校准:曹操 dispute 是否明显高于诸葛亮/董卓/关羽")
    print("3 不假平衡:诸葛亮 con 是否空/弱(没为平衡硬编篡逆)")
    print("4 锚定:pro/con evidence 锚得住率")
    print("-" * 66)
    for r in records:
        if "error" in r:
            continue
        print(f"  {r['name']}: net={r['net']} dispute={r['dispute']} | "
              f"pro {r['n_pro']}/锚{r['pro_verified']}  con {r['n_con']}/锚{r['con_verified']}")
    print("=" * 66)

    out = _ROOT / "docs" / "internal" / "experiments" / "data" / "exp024-toulmin-stance-sanguo.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "probe": "exp024-toulmin-stance",
        "book": "三国演义(全二册,公版)",
        "model": _MODEL,
        "figures": _FIGURES,
        "expect_dispute_ref": _EXPECT_DISPUTE,
        "num_chunks": len(chunks),
        "records": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
