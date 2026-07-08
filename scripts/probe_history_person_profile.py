"""史书垂直前置 probe：人物志字段能不能从原文可靠抽 + 锚住(三国演义,公版)。

设计见 docs/design/WP-history-vertical.md 第四节。本 probe 回答一件事——
史书人物网要的 {籍贯 / 官职生涯 / 生平大事 / 势力归属} 四类字段,LLM 能不能从
书的原文可靠抽出来 + 每条锚到原文,而不是编史书没明说的?抽不准 → 就不做这些字段
(只做现成数据能拼的关系+在场+命运),别硬编。

方法学接 exp-010(长上下文抽取)+ exp-013(结构化 JSON 抽取 + 边粒度 verify_citations):
- 整本进 system 固定段(长上下文,缓存友好),让模型对 5 个主要人物各抽结构化档案,
  每个字段带 evidence 原文片段。
- 每条 evidence 当一条 citation 过 verify_citations(全书 456 chunk 建证据表),
  得 match_type(quote 逐字 / paraphrase 转述 / none 锚不住)。
- 跑 PROBE_RUNS 次(默认 2,第 2 次起命中 DeepSeek 服务端缓存),看字段稳定性。

四项核验(设计稿第四节):
1. 准不准:籍贯/官职跟公认史实对得上吗(脚本预置公认答案表当人工对照素材)。
2. 锚不锚得住:每条 evidence 能在书里字符串命中吗(verify_citations,锚不住率)。
3. 编造率(命门):evidence 锚不住(match_type=none)= 强编造信号;字段值靠人工比对。
4. 覆盖:5 人里几个抽出可用档案、几个太稀。

go/no-go:准 + 锚得住 + 编造率低(≤10-15%)→ GO 建后端人物志;编造率高/锚不住 → no-go,
史书档案只做现成数据能拼的(关系+在场+命运),不上籍贯官职。

三国公版,数据可留仓。flash、key 从 .env(memory 里的 DeepSeek key),L2 关。不 commit、不动生产。
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
_P_MISS, _P_HIT, _P_OUT = 0.14, 0.0028, 0.28  # USD/1M flash(同 exp-010 账本)
_RUNS = int(os.environ.get("PROBE_RUNS", "2"))
_BOOK_PAT = "test三国演义*.epub"
_MAX_TOKENS = 8000  # 档案输出长,参 character_graph(exp-013 图 ~5-6k token)

# 挑 5 个主要人物。三国演义籍贯/官职极丰富,是绝佳测试靶。
_PERSONS = ["刘备", "关羽", "曹操", "诸葛亮", "孙权"]

# 公认史实/演义答案表(人工判分对照素材,不喂给模型)。
# 只列可人工硬判的籍贯 + 标志性官职/头衔,供报告核"准不准"。
# 来源:演义文本 + 通行三国史常识(陈寿《三国志》级公认),用于人工比对不作程序判分。
_GROUND_TRUTH = {
    "刘备": {
        "籍贯": "涿郡涿县(幽州涿郡)",
        "官职关键词": ["平原相", "豫州牧", "左将军", "汉中王", "蜀汉昭烈帝/皇帝"],
        "势力": "蜀/蜀汉(先为汉室宗亲、织席贩履起家)",
    },
    "关羽": {
        "籍贯": "河东解良(河东郡解县)",
        "官职关键词": ["偏将军", "汉寿亭侯", "前将军", "荡寇将军", "襄阳太守"],
        "势力": "蜀/刘备阵营",
    },
    "曹操": {
        "籍贯": "沛国谯县",
        "官职关键词": ["典军校尉", "兖州牧", "司空", "丞相", "魏王"],
        "势力": "魏/曹魏(挟天子以令诸侯)",
    },
    "诸葛亮": {
        "籍贯": "琅琊阳都(徐州琅琊郡)",
        "官职关键词": ["军师中郎将", "军师将军", "丞相", "武乡侯", "益州牧"],
        "势力": "蜀/蜀汉(刘备三顾茅庐请出)",
    },
    "孙权": {
        "籍贯": "吴郡富春",
        "官职关键词": ["讨虏将军", "会稽太守", "吴王", "吴大帝/皇帝", "车骑将军"],
        "势力": "吴/东吴(继承父兄孙坚孙策基业)",
    },
}

_SYSTEM_PREAMBLE = (
    "你是严谨的史书人物档案抽取助手。下面给你《三国演义》全书原文。\n"
    "你的任务:根据这本书的原文,抽取指定人物的档案字段。\n"
    "铁律:每个字段值都必须能在原文里找到依据,evidence 必须是原文的逐字片段"
    "(原样摘录、不改写、不概括)。原文里没有明说的,一律填空或写「原文未提及」,"
    "绝对不要用你的历史知识补全、不要编造原文没有的内容。"
    "宁可字段空着,也不要写一个原文里查不到的值。\n\n"
    "=== 《三国演义》全书原文 ===\n"
)

# 每人一次抽取的字段 schema 指令。evidence 全部要求逐字原文片段。
_PERSON_INSTRUCTION_TMPL = (
    "请只依据上面《三国演义》原文,抽取人物「{name}」的档案。\n"
    "严格输出 JSON(不要别的话、不要 markdown 代码围栏):\n"
    "{{\n"
    '  "name": "{name}",\n'
    '  "籍贯": {{"value": "籍贯(如河东解良,原文没明说就填\\"原文未提及\\")", '
    '"evidence": "证明籍贯的原文逐字片段,没有就填空字符串"}},\n'
    '  "官职生涯": [{{"官职": "官职或头衔名", '
    '"evidence": "该官职出现处的原文逐字片段"}}],\n'
    '  "生平大事": [{{"事件": "一件生平大事的简述", '
    '"evidence": "该事件的原文逐字片段"}}],\n'
    '  "势力": {{"value": "所属势力(如蜀/魏/吴,原文没明说就填\\"原文未提及\\")", '
    '"evidence": "证明势力归属的原文逐字片段,没有就填空字符串"}}\n'
    "}}\n"
    "官职生涯尽量按原文出现顺序列全(3-8 条);生平大事列原文着墨的重大节点(3-8 条)。"
    "每条 evidence 都要是能在原文里逐字找到的片段,找不到原文依据的字段/条目就不要列。"
)


def _resolve_book() -> str | None:
    found = sorted((_ROOT / "tests" / "file").glob(_BOOK_PAT))
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


def _parse_profile(raw: str) -> dict | None:
    """从 LLM 输出抠出档案 JSON(复用生产 parse 工具)。"""
    from bookscope.agent.utils.json_parsing import (  # noqa: PLC0415
        extract_first_json_object,
        strip_code_fence,
    )

    txt = strip_code_fence(raw)
    obj = extract_first_json_object(txt)
    if obj is None:
        return None
    try:
        return json.loads(obj)
    except Exception:  # noqa: BLE001
        return None


def _collect_evidence_citations(profile: dict) -> list[dict]:
    """把档案里所有字段的 evidence 收成 citation 列表(过 verify_citations 用)。

    每条带 _field 标签(籍贯/官职/大事/势力)+ _value(字段值),方便报告按字段归类。
    verify_citations 认 snippet 字段;chapter 传 None(不做章号消歧,只问能不能锚住)。
    """
    cits: list[dict] = []

    def _add(field: str, value: str, ev):
        if not isinstance(ev, str):
            ev = "" if ev is None else str(ev)
        cits.append({"snippet": ev, "chapter": None, "_field": field, "_value": value})

    jiguan = profile.get("籍贯") or {}
    if isinstance(jiguan, dict):
        _add("籍贯", str(jiguan.get("value", "")), jiguan.get("evidence", ""))

    shili = profile.get("势力") or {}
    if isinstance(shili, dict):
        _add("势力", str(shili.get("value", "")), shili.get("evidence", ""))

    for item in profile.get("官职生涯") or []:
        if isinstance(item, dict):
            _add("官职", str(item.get("官职", "")), item.get("evidence", ""))

    for item in profile.get("生平大事") or []:
        if isinstance(item, dict):
            _add("大事", str(item.get("事件", "")), item.get("evidence", ""))

    return cits


def run_probe(full_text: str, evidence_map: dict) -> list[dict]:
    """整本进 system 固定段,每人顺序抽 _RUNS 次(第 2 次起命中缓存)。"""
    from openai import OpenAI  # noqa: PLC0415

    from bookscope.agent.citation_check import verify_citations  # noqa: PLC0415

    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=_DS_BASE)
    system = _SYSTEM_PREAMBLE + full_text

    out = []
    for name in _PERSONS:
        instruction = _PERSON_INSTRUCTION_TMPL.format(name=name)
        for run in range(1, _RUNS + 1):
            t0 = time.monotonic()
            try:
                resp = client.chat.completions.create(
                    model=_MODEL,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": instruction},
                    ],
                    temperature=1.0,
                    max_tokens=_MAX_TOKENS,
                )
                dt = time.monotonic() - t0
                ud = _usage_dict(resp.usage)
                ans = resp.choices[0].message.content or ""
                profile = _parse_profile(ans)

                # 核验每条 evidence 的锚定
                anchored = None
                if profile is not None:
                    cits = _collect_evidence_citations(profile)
                    # verify_citations 原地附加 verified/match_type/match_score
                    verify_citations(cits, evidence_map)
                    anchored = cits

                rec = {
                    "name": name, "run": run, "latency_s": round(dt, 1),
                    "parsed_ok": profile is not None,
                    "profile": profile,
                    "anchored_citations": anchored,
                    "prompt_tokens": ud.get("prompt_tokens"),
                    "completion_tokens": ud.get("completion_tokens"),
                    "cache_hit": ud.get("prompt_cache_hit_tokens"),
                    "cache_miss": ud.get("prompt_cache_miss_tokens"),
                    "finish_reason": resp.choices[0].finish_reason,
                    "_raw_text": ans if profile is None else None,  # parse 失败留 raw 供诊断
                }

                # 单人核验统计
                if anchored is not None:
                    nq = sum(1 for c in anchored if c.get("match_type") == "quote")
                    npar = sum(1 for c in anchored if c.get("match_type") == "paraphrase")
                    nnone = sum(1 for c in anchored if c.get("match_type") == "none")
                    ntot = len(anchored)
                    print(f"[{name}#{run}] {dt:5.1f}s out={rec['completion_tokens']} "
                          f"finish={rec['finish_reason']} | 字段{ntot}条 "
                          f"逐字{nq} 转述{npar} 锚不住{nnone}")
                else:
                    print(f"[{name}#{run}] {dt:5.1f}s out={rec['completion_tokens']} "
                          f"finish={rec['finish_reason']} | PARSE FAIL len={len(ans)}")
            except Exception as e:  # noqa: BLE001
                rec = {"name": name, "run": run, "error": repr(e)}
                print(f"[{name}#{run}] ERROR {e!r}", file=sys.stderr)
            out.append(rec)
    return out


def _summarize(recs: list[dict]) -> dict:
    """按人 + 全局汇总四项核验(锚住率/编造信号/覆盖),字段值准确靠人工比对。"""
    ok = [r for r in recs if "error" not in r and r.get("parsed_ok")]

    # 全局锚定分布(所有人所有 run 的 evidence 条目)
    g_quote = g_par = g_none = g_tot = 0
    per_person: dict[str, dict] = {}

    for r in ok:
        cits = r.get("anchored_citations") or []
        nq = sum(1 for c in cits if c.get("match_type") == "quote")
        npar = sum(1 for c in cits if c.get("match_type") == "paraphrase")
        nnone = sum(1 for c in cits if c.get("match_type") == "none")
        ntot = len(cits)
        g_quote += nq
        g_par += npar
        g_none += nnone
        g_tot += ntot

        name = r["name"]
        pp = per_person.setdefault(name, {
            "runs": 0, "quote": 0, "paraphrase": 0, "none": 0, "total_fields": 0,
            "官职数": [], "大事数": [],
        })
        pp["runs"] += 1
        pp["quote"] += nq
        pp["paraphrase"] += npar
        pp["none"] += nnone
        pp["total_fields"] += ntot
        prof = r.get("profile") or {}
        pp["官职数"].append(len(prof.get("官职生涯") or []))
        pp["大事数"].append(len(prof.get("生平大事") or []))

    for name, pp in per_person.items():
        tot = pp["total_fields"] or 1
        pp["锚住率_逐字+转述"] = round((pp["quote"] + pp["paraphrase"]) / tot, 3)
        pp["锚不住率_编造信号"] = round(pp["none"] / tot, 3)

    anchored_rate = (g_quote + g_par) / g_tot if g_tot else 0.0
    none_rate = g_none / g_tot if g_tot else 0.0

    return {
        "全局": {
            "字段总条数": g_tot,
            "逐字命中": g_quote,
            "转述命中": g_par,
            "锚不住": g_none,
            "锚住率_逐字加转述": round(anchored_rate, 3),
            "锚不住率_编造信号": round(none_rate, 3),
        },
        "按人": per_person,
    }


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设置(应从 .env / memory 读)", file=sys.stderr)
        return 1
    epub = _resolve_book()
    if not epub:
        print(f"[probe] 三国 epub 没找到(tests/file/ 放 {_BOOK_PAT})", file=sys.stderr)
        return 1
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"  # 关 L2,DeepSeek 服务端缓存真命中可测

    from bookscope.agent.citation_check import build_evidence_map  # noqa: PLC0415
    from bookscope.ingest.book_chunker import chunk_book  # noqa: PLC0415
    from bookscope.ingest.loader import load_text  # noqa: PLC0415

    book = load_text(epub)
    full_text = book.raw_text
    chunks = chunk_book(book)
    # 建证据登记表:每 chunk 一条 {chunk_id, chapter, text},核 evidence 锚定用
    evidence_map = build_evidence_map([
        {"chunk_id": f"c-{c.index}", "chapter": c.chapter, "text": c.text}
        for c in chunks
    ])
    print(f"[probe] 三国全文 {len(full_text)} 字符,{len(chunks)} chunk;"
          f"模型 {_MODEL};{len(_PERSONS)} 人 × {_RUNS} 次;L2 关\n")

    recs = run_probe(full_text, evidence_map)
    summary = _summarize(recs)

    ok = [r for r in recs if "error" not in r]
    cost = sum(_cost_usd(r.get("cache_hit"), r.get("cache_miss"), r.get("completion_tokens"))
               for r in ok)
    parsed = sum(1 for r in ok if r.get("parsed_ok"))

    g = summary["全局"]
    print("\n" + "=" * 64)
    print(f"覆盖:{parsed}/{len(recs)} 次成功 parse")
    print(f"全局字段 {g['字段总条数']} 条 | 逐字 {g['逐字命中']} 转述 {g['转述命中']} "
          f"锚不住 {g['锚不住']}")
    print(f"锚住率(逐字+转述)= {g['锚住率_逐字加转述']:.1%}")
    print(f"锚不住率(编造信号)= {g['锚不住率_编造信号']:.1%}")
    print(f"总成本 ~${cost:.4f}")
    print("-" * 64)
    print("按人锚不住率(编造信号):")
    for name, pp in summary["按人"].items():
        print(f"  {name}: 锚住 {pp['锚住率_逐字+转述']:.1%} / "
              f"锚不住 {pp['锚不住率_编造信号']:.1%} "
              f"(官职均 {sum(pp['官职数'])/max(len(pp['官职数']),1):.1f} 条 / "
              f"大事均 {sum(pp['大事数'])/max(len(pp['大事数']),1):.1f} 条)")
    print("=" * 64)
    print("人工判分:读 profile 的籍贯/官职值对 _GROUND_TRUTH 核准不准;")
    print("         锚不住(none)的 evidence 逐条看是不是模型脑补(命门:编造率)")
    print("=" * 64)

    out_path = (_ROOT / "docs" / "internal" / "experiments" / "data"
                / "exp022-history-person-profile-sanguo.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "probe": "exp022-history-person-profile",
        "book": "三国演义(全二册,公版)",
        "model": _MODEL,
        "runs_per_person": _RUNS,
        "persons": _PERSONS,
        "num_chunks": len(chunks),
        "ground_truth_ref": _GROUND_TRUTH,
        "summary": summary,
        "cost_usd": round(cost, 4),
        "records": recs,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
