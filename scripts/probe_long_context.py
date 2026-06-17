"""exp-009 probe：长上下文 vs RAG（anshi）。

A arm = 整本书塞进 system 固定段、flash 直接答（稳定前缀复用 DeepSeek 服务端缓存）。
B arm = 当前 RAG agent loop（复用 smoke_test_r1 装书 + AgentLoop）。
同一组题（exp002 五道全书结构诊断题 + 2 道事实锚），head-to-head + 缓存/成本/延迟。

设计见 docs/internal/experiments/009-long-context-vs-rag-probe.md。flash、key 从 .env、BookScope L2 关。
不 commit、不动生产。书名按 test安史之乱*.epub glob 定位，不硬编原始文件名。
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
if str(_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_ROOT / "scripts"))

import bookscope  # noqa: E402, F401 —— 触发 .env 自动加载

_MODEL = os.environ.get("BOOKSCOPE_SMOKE_MODEL", "deepseek-v4-flash")
_DS_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
# 价目（USD/1M，2026-06 flash）：miss 0.14 / hit 0.0028 / output 0.28
_P_MISS, _P_HIT, _P_OUT = 0.14, 0.0028, 0.28


_BOOK_GLOB = {"anshi": "test安史之乱*.epub", "zhinei": "test制内市场*.epub"}


def _resolve_book(book: str) -> str | None:
    pat = _BOOK_GLOB.get(book, "")
    found = sorted(_ROOT.glob(pat)) if pat else []
    return str(found[0]) if found else None


def _load_questions(book: str) -> list[dict]:
    if book == "anshi":
        p = _ROOT / "docs" / "experiments" / "data" / "exp002-anshi-questions.json"
        qs = [
            {"id": q["id"], "category": q["category"], "question": q["smoke"]["question"]}
            for q in json.loads(p.read_text(encoding="utf-8"))["questions"]
        ]
        # 2 道事实锚：测长上下文别在简单检索题上反而输
        qs += [
            {"id": "a1", "category": "事实锚",
             "question": "安禄山起兵前身兼哪几个节度使？他起兵打的旗号（借口）是什么？"},
            {"id": "a2", "category": "事实锚",
             "question": "马嵬驿之变里禁军最终逼死了谁？杨贵妃的结局是什么？"},
        ]
        return qs
    # zhinei（理论书，跟 anshi 历史书不同类型，验跨题材）：3 道全书结构题 + golden 真题锚
    qs = [
        {"id": "g1", "category": "核心概念",
         "question": "这本书'制内市场'这个核心概念指什么？作者怎么定义、怎么论证它的？"},
        {"id": "g2", "category": "论证结构",
         "question": "全书的论证结构是怎样的——核心论点在哪几章铺垫、在哪几章用案例回扣？论证链闭环吗？"},
        {"id": "g3", "category": "立场一致性",
         "question": "作者对'国家与市场关系'的核心立场，从前往后是否一致？哪几章立场最强、哪几章最弱？"},
    ]
    gp = _ROOT / "docs" / "experiments" / "data" / "golden-retrieval-zhinei.json"
    try:
        data = json.loads(gp.read_text(encoding="utf-8"))
        for i, q in enumerate((data.get("queries") or [])[:4], start=1):
            text = q.get("query") or q.get("question")
            if text:
                qs.append({"id": f"r{i}", "category": q.get("query_type", "检索题"), "question": text})
    except Exception:  # noqa: BLE001
        pass
    return qs


def _usage_dict(usage) -> dict:
    if usage is None:
        return {}
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    try:
        return dict(usage)
    except Exception:  # noqa: BLE001
        return {k: getattr(usage, k) for k in dir(usage) if not k.startswith("_")}


def arm_a_long_context(full_text: str, questions: list[dict]) -> list[dict]:
    """A：整本书进 system 固定段，逐题问，顺序跑让第 2 问起命中缓存。"""
    from openai import OpenAI  # noqa: PLC0415

    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=_DS_BASE)
    system = (
        "你是严谨的长文本分析助手。下面给你一本书的全文。"
        "只根据这本书的原文回答问题，每个判断给出原文依据（标出大致章节或引一句原句），"
        "原文里找不到依据的不要编，宁可说没有。\n\n=== 全书原文 ===\n" + full_text
    )
    out = []
    for q in questions:
        t0 = time.monotonic()
        try:
            resp = client.chat.completions.create(
                model=_MODEL,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": q["question"]},
                ],
                temperature=1.0,
                max_tokens=4000,
            )
            dt = time.monotonic() - t0
            ud = _usage_dict(resp.usage)
            ans = resp.choices[0].message.content or ""
            rec = {
                "id": q["id"], "category": q["category"], "latency_s": round(dt, 1),
                "answer": ans,
                "prompt_tokens": ud.get("prompt_tokens"),
                "completion_tokens": ud.get("completion_tokens"),
                "cache_hit": ud.get("prompt_cache_hit_tokens"),
                "cache_miss": ud.get("prompt_cache_miss_tokens"),
                "finish_reason": resp.choices[0].finish_reason,
            }
            print(f"[A] {q['id']:4} {dt:5.1f}s prompt={rec['prompt_tokens']} "
                  f"hit={rec['cache_hit']} miss={rec['cache_miss']} out={rec['completion_tokens']} "
                  f"finish={rec['finish_reason']} ans_len={len(ans)}")
        except Exception as e:  # noqa: BLE001
            rec = {"id": q["id"], "category": q["category"], "error": repr(e)}
            print(f"[A] {q['id']:4} ERROR {e!r}", file=sys.stderr)
        out.append(rec)
    return out


def arm_b_rag(questions: list[dict]) -> list[dict]:
    """B：当前 RAG agent loop（复用 smoke_test_r1 装书）。"""
    from smoke_test_r1 import _build_adapter_and_model, _load_book_session  # noqa: PLC0415

    from bookscope.agent import AgentLoop  # noqa: PLC0415
    from bookscope.agent.backends.r0_assembler import R0BookAssembler  # noqa: PLC0415

    book, chunks, kg, vs = _load_book_session()
    assembler = R0BookAssembler(
        book_text=book, chunks=chunks, knowledge_graph=kg, session_vector_store=vs,
    )
    backends = assembler.build_all()
    adapter, model = _build_adapter_and_model("deepseek")
    loop = AgentLoop(
        client=adapter,
        search_chunks_backend=backends["search"],
        chapter_range_backend=backends["chapter_range"],
        list_characters_backend=backends["list_characters"],
        model=model,
        timeout_seconds=float(os.environ.get("BOOKSCOPE_SMOKE_TIMEOUT", "300")),
    )
    out = []
    for q in questions:
        t0 = time.monotonic()
        try:
            r = loop.query(q["question"])
            dt = time.monotonic() - t0
            tr = {}
            trace = getattr(r, "trace", None)
            if trace is not None and hasattr(trace, "model_dump"):
                tr = trace.model_dump()
            ans = getattr(r, "answer", "") or ""
            cites = getattr(r, "citations", []) or []
            rec = {
                "id": q["id"], "category": q["category"], "latency_s": round(dt, 1),
                "answer": ans, "citations": len(cites),
                "input_tokens": tr.get("total_input_tokens"),
                "cache_hit": tr.get("cache_hit_tokens"),
                "cache_miss": tr.get("cache_miss_tokens"),
                "output_tokens": tr.get("total_output_tokens"),
                "iterations": tr.get("iterations"),
            }
            print(f"[B] {q['id']:4} {dt:5.1f}s in={rec['input_tokens']} "
                  f"hit={rec['cache_hit']} iters={rec['iterations']} cites={rec['citations']} ans_len={len(ans)}")
        except Exception as e:  # noqa: BLE001
            rec = {"id": q["id"], "category": q["category"], "error": repr(e)}
            print(f"[B] {q['id']:4} ERROR {e!r}", file=sys.stderr)
        out.append(rec)
    return out


def _cost_usd(hit, miss, out_tok) -> float:
    h = (hit or 0) / 1e6 * _P_HIT
    m = (miss or 0) / 1e6 * _P_MISS
    o = (out_tok or 0) / 1e6 * _P_OUT
    return h + m + o


def main() -> int:
    import argparse  # noqa: PLC0415
    parser = argparse.ArgumentParser(description="exp-009 长上下文 vs RAG probe")
    parser.add_argument("--book", default="anshi", choices=sorted(_BOOK_GLOB))
    args = parser.parse_args()
    book_name = args.book

    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设置（应从 .env 读）", file=sys.stderr)
        return 1
    epub = _resolve_book(book_name)
    if not epub:
        print(f"[probe] {book_name} epub 没找到（仓库根放 {_BOOK_GLOB[book_name]}）", file=sys.stderr)
        return 1
    os.environ["BOOKSCOPE_SMOKE_EPUB"] = epub
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"  # 关 L2，DeepSeek 服务端缓存真命中可测

    from bookscope.ingest.loader import load_text  # noqa: PLC0415

    bk = load_text(epub)
    full_text = bk.raw_text
    print(f"[probe] {book_name} 全文 {len(full_text)} 字符；模型 {_MODEL}；L2 关")

    questions = _load_questions(book_name)
    print(f"[probe] {len(questions)} 题\n")

    print("=== A arm：长上下文（整本进 context）===")
    a = arm_a_long_context(full_text, questions)
    print("\n=== B arm：当前 RAG agent loop ===")
    b = arm_b_rag(questions)

    # 汇总
    a_ok = [r for r in a if "error" not in r]
    a_cache_q2 = a_ok[1:]  # 第 2 问起才谈缓存命中
    tot_hit = sum((r.get("cache_hit") or 0) for r in a_cache_q2)
    tot_prompt = sum((r.get("prompt_tokens") or 0) for r in a_cache_q2)
    a_rate = (tot_hit / tot_prompt) if tot_prompt else 0.0
    a_cost = sum(_cost_usd(r.get("cache_hit"), r.get("cache_miss"), r.get("completion_tokens")) for r in a_ok)
    b_ok = [r for r in b if "error" not in r]
    b_cost = sum(_cost_usd(r.get("cache_hit"), r.get("cache_miss"), r.get("output_tokens")) for r in b_ok)

    print("\n" + "=" * 60)
    print(f"[A] 第2问起缓存命中率 = {a_rate:.1%}（hit {tot_hit}/{tot_prompt}）")
    print(f"[A] 总成本 ~${a_cost:.4f} | 平均延迟 {sum(r['latency_s'] for r in a_ok)/max(1,len(a_ok)):.1f}s")
    print(f"[B] 总成本 ~${b_cost:.4f} | 平均延迟 {sum(r['latency_s'] for r in b_ok)/max(1,len(b_ok)):.1f}s")
    print("=" * 60)

    out_path = _ROOT / "docs" / "experiments" / "data" / f"exp009-long-context-vs-rag-{book_name}.json"
    out_path.write_text(json.dumps({
        "probe": "exp009-long-context-vs-rag",
        "book": book_name, "model": _MODEL, "n_questions": len(questions),
        "summary": {
            "a_cache_rate_q2plus": round(a_rate, 4),
            "a_cost_usd": round(a_cost, 4), "b_cost_usd": round(b_cost, 4),
        },
        "arm_a_long_context": a, "arm_b_rag": b,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
