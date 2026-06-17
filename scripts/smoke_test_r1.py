"""r1-agent-loop 端到端 smoke test 脚本。

**请勿放入 CI**：本脚本会调用真 DeepSeek / Anthropic API，消耗用户
BYOK 额度。仅作者本地手动跑一次，用于确认"FastAPI + agent loop +
adapter + r0 backends"整条链路是否跑通。

用法::

    export DEEPSEEK_API_KEY=sk-xxxxxxxxx
    python scripts/smoke_test_r1.py
    # 或者换 provider（Anthropic）
    export ANTHROPIC_API_KEY=sk-ant-xxxxxxxxx
    BOOKSCOPE_SMOKE_PROVIDER=anthropic python scripts/smoke_test_r1.py

可选环境变量:

  - ``BOOKSCOPE_SMOKE_QUESTION``  默认 "这本书里主要有哪几个角色？"
  - ``BOOKSCOPE_SMOKE_PROVIDER``  "deepseek"（默认）/ "anthropic"
  - ``BOOKSCOPE_SMOKE_MODEL``     覆盖默认模型名（可选）
  - ``BOOKSCOPE_SMOKE_EPUB``      覆盖默认 epub 路径
  - ``BOOKSCOPE_SMOKE_TIMEOUT``   AgentLoop 单次 query 总时长上限（秒）
                                  默认 600；慢 provider 可调大
  - ``BOOKSCOPE_SMOKE_MAX_ITER``  AgentLoop 最大迭代数；默认沿用库内置
  - ``BOOKSCOPE_SMOKE_EXTRACT_KG``  "1" 显式打开真 KG 抽取（走
                                  ``MinimalKGExtractor``）；默认关，用
                                  手工 4 角色 KG。**真抽取代价高**：
                                  32K 字书 × 60 chunk/batch ≈ 18 次
                                  LLM 调用约 30 分钟 / 几十万到上百万 token
  - ``BOOKSCOPE_SMOKE_KG_CHUNK_LIMIT``  只用前 N 个 chunk 做 KG 抽取，
                                  控制成本；默认全量（0 或未设）
  - ``BOOKSCOPE_SMOKE_REVIEW``    "1" 在 outcome=success 后自动调
                                  reviewer 审稿（复用
                                  ``scripts/review_last_smoke.py`` 的
                                  ``build_reviewer_client`` /
                                  ``print_report``）。reviewer 默认走
                                  ``BOOKSCOPE_REVIEW_PROVIDER`` /
                                  ``BOOKSCOPE_REVIEW_MODEL``（默认
                                  deepseek / deepseek-v4-flash）。reviewer 失败
                                  仅打印 warning，不影响 smoke 退出码。
                                  outcome=failure / timeout / max_iter
                                  时不触发 reviewer。

默认优先加载项目根 ``test明朝那些事儿.epub``；若文件不存在或加载失败，
fallback 到一段内置的 3 章样本（含 3-5 角色）。
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

# Windows 控制台默认编码可能是 cp932 / cp936，中文打印会炸。
# 本脚本全流程都打印中文，直接把 stdout / stderr 切到 UTF-8。
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001 — 非标准 stream 忽略
    pass

# 让脚本可以脱离 `pip install -e .` 直接跑
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


DEFAULT_EPUB = _PROJECT_ROOT / "test明朝那些事儿.epub"
DEFAULT_QUESTION = "这本书里主要有哪几个角色？"

# 内置 fallback 文本：3 章，4 个角色，够 agent 调 tool 跑一次完整流程。
_FALLBACK_TEXT = """\
第一章 开国

朱元璋出生于乱世，年少丧父，历经磨难。他加入红巾军，靠韬略与胆识
一步步崛起。李善长是他最早的谋士，为他出谋划策；徐达和常遇春则是
他最倚重的武将。

第二章 开疆

徐达率军北伐，将元廷残部逐出中原。常遇春每战必先登，威名远播。
朱元璋称帝建国，国号大明，年号洪武。李善长被封韩国公，位极人臣。

第三章 风云

胡惟庸一案震动朝野，李善长受牵连。朱元璋借此整顿朝纲，大明王朝
进入新的阶段。徐达病逝，常遇春早逝，开国功臣渐次凋零。
"""


# ---------------------------------------------------------------------------
# 加载 BookText / chunks / KG
# ---------------------------------------------------------------------------


def _load_book_session() -> tuple[Any, list[Any], Any, Any]:
    """返回 (book_text, chunks, kg, vector_store)。

    首选从 epub 加载；epub 不存在或加载失败时 fallback 到内置样本。
    KG 用最简构造：从 chunks 里粗略扫一遍，把出现的角色名装进 KG。
    """
    from bookscope.ingest.book_chunker import chunk_book
    from bookscope.ingest.loader import load_text
    from bookscope.models.schemas import (
        BookKnowledgeGraph,
        BookText,
        CharacterProfile,
    )

    epub_path_env = os.environ.get("BOOKSCOPE_SMOKE_EPUB")
    epub_path = Path(epub_path_env) if epub_path_env else DEFAULT_EPUB

    book: Any
    try:
        if epub_path.exists():
            print(f"[smoke] 加载 epub: {epub_path}")
            book = load_text(epub_path)
            book.language = "zh"
        else:
            raise FileNotFoundError(epub_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke] 无法加载 epub（{exc}），回退到内置样本")
        book = BookText(title="明朝片段", raw_text=_FALLBACK_TEXT, language="zh")

    print(f"[smoke] 书名: {book.title}，字数: {book.word_count}")

    chunks = chunk_book(book)
    print(f"[smoke] 切分 chunk 数: {len(chunks)}")

    # 构造最简 KG：手工列几位核心角色 + 章节索引。fallback 模式下
    # 角色名与文本一致；真实 epub 下 agent 会自己通过 tool 探查。
    known_characters = ["朱元璋", "李善长", "徐达", "常遇春"]
    # 第 15 轮之后 ChunkResult 有 chapter 字段；优先走 schema，缺失再 regex
    raw: set[int] = set()
    for c in chunks:
        ch = getattr(c, "chapter", None)
        if ch is None:
            ch = _guess_chunk_chapter(c.text)
        if ch is not None:
            raw.add(ch)
    all_chapters = sorted(raw)
    characters = [
        CharacterProfile(
            name=name,
            key_chapter_indices=all_chapters or [1],
        )
        for name in known_characters
    ]
    kg = BookKnowledgeGraph(
        book_title=book.title,
        language="zh",
        characters=characters,
    )

    # 构造 vector store（BM25 足以跑通；embedding provider 未配时自动降级）
    vector_store = _build_vector_store(chunks)

    return book, chunks, kg, vector_store


def _guess_chunk_chapter(text: str) -> int | None:
    """从 chunk 首行 header 粗略抽章节号，仅用于 KG key_chapter_indices。"""
    import re

    head = text.split("\n", 1)[0]
    m = re.search(r"第([一二三四五六七八九十百千零\d]+)[章回]", head)
    if not m:
        return None
    lit = m.group(1)
    if lit.isdigit():
        return int(lit)
    # 中文数字简化映射（smoke 脚本只需覆盖 1-20）
    cn = {
        "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
    }
    if lit in cn:
        return cn[lit]
    if lit.startswith("十") and len(lit) == 2:
        return 10 + cn.get(lit[1], 0)
    if lit.endswith("十") and len(lit) == 2:
        return cn.get(lit[0], 0) * 10
    return None


def _build_vector_store(chunks: list[Any]) -> Any:
    """构造 BM25-only vector store（不依赖真 embedding provider）。"""
    from bookscope.store.vector_store import SessionVectorStore

    # enable_vector=False 避免在 smoke test 中真跑 embedding（成本 / 环境）
    return SessionVectorStore(chunks, enable_vector=False)


def _maybe_extract_real_kg(
    *,
    adapter: Any,
    model: str,
    chunks: list[Any],
    book_title: str,
    language: str = "zh",
) -> Any | None:
    """按 BOOKSCOPE_SMOKE_EXTRACT_KG 开关决定是否真跑 MinimalKGExtractor。

    打开时走 :class:`MinimalKGExtractor`，返回真 KG（`BookKnowledgeGraph`）；
    关闭时返回 ``None``，调用方保留手工 KG。

    ``BOOKSCOPE_SMOKE_KG_CHUNK_LIMIT`` 可把 extractor 的输入限制到前 N 个
    chunk，便于快速验证路径，代价远小于全量抽取。
    """
    if os.environ.get("BOOKSCOPE_SMOKE_EXTRACT_KG") != "1":
        return None

    from bookscope.agent.backends.minimal_kg_extractor import MinimalKGExtractor

    limit_env = os.environ.get("BOOKSCOPE_SMOKE_KG_CHUNK_LIMIT", "").strip()
    try:
        limit = int(limit_env) if limit_env else 0
    except ValueError:
        print(
            f"[smoke] BOOKSCOPE_SMOKE_KG_CHUNK_LIMIT 非整数 {limit_env!r}，忽略",
            file=sys.stderr,
        )
        limit = 0

    source_chunks = chunks[:limit] if limit > 0 else chunks
    print(
        f"[smoke] 真 KG 抽取：MinimalKGExtractor，chunk 输入 "
        f"{len(source_chunks)} / {len(chunks)}（limit={limit or '全量'}）"
    )
    t0 = time.monotonic()
    extractor = MinimalKGExtractor(client=adapter, model=model)
    kg = extractor.extract(
        chunks=source_chunks, book_title=book_title, language=language,
    )
    elapsed = time.monotonic() - t0
    print(
        f"[smoke] 真 KG 抽取完成：{len(kg.characters)} 角色，耗时 {elapsed:.1f}s"
    )
    return kg


# ---------------------------------------------------------------------------
# 构造 adapter + loop
# ---------------------------------------------------------------------------


def _build_adapter_and_model(provider: str) -> tuple[Any, str]:
    """根据 provider 与环境变量构造 adapter；返回 (adapter, model 名)。"""
    from bookscope.agent import AnthropicAdapter, DeepSeekAdapter

    if provider == "deepseek":
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "环境变量 DEEPSEEK_API_KEY 未设置。请先 export 后再跑。"
            )
        model = os.environ.get("BOOKSCOPE_SMOKE_MODEL") or "deepseek-v4-flash"
        return DeepSeekAdapter(api_key=api_key), model
    if provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "环境变量 ANTHROPIC_API_KEY 未设置。请先 export 后再跑。"
            )
        model = os.environ.get("BOOKSCOPE_SMOKE_MODEL") or "claude-sonnet-4-6"
        return AnthropicAdapter(api_key=api_key), model
    raise RuntimeError(
        f"未知 provider: {provider!r}"
        "（支持 deepseek / anthropic）"
    )


# ---------------------------------------------------------------------------
# Reviewer 集成（第 27 轮 Task #27.5）
# ---------------------------------------------------------------------------


def _maybe_run_reviewer(
    *,
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
    book_title: str,
    language: str,
) -> None:
    """smoke outcome=success 后，按 ``BOOKSCOPE_SMOKE_REVIEW=1`` 触发审稿。

    复用 ``scripts/review_last_smoke.py`` 的 ``build_reviewer_client`` /
    ``print_report`` 公开函数。reviewer 失败（key 缺失、网络错、JSON
    parse 错）只打 warning，**不**抛异常，调用方不做任何错误码处理。
    """
    if os.environ.get("BOOKSCOPE_SMOKE_REVIEW") != "1":
        return

    try:
        from bookscope.agent.reviewer import review_answer  # noqa: PLC0415
        from scripts.review_last_smoke import (  # noqa: PLC0415 — 延迟导入
            build_reviewer_client,
            print_report,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[smoke] reviewer 模块导入失败（{type(exc).__name__}: {exc}），跳过审稿",
            file=sys.stderr,
        )
        return

    print()
    print("-" * 60)
    print("[smoke] BOOKSCOPE_SMOKE_REVIEW=1，触发 reviewer 审稿...")

    try:
        client, model, provider = build_reviewer_client()
    except Exception as exc:  # noqa: BLE001
        print(
            f"[smoke] reviewer 配置错误（{type(exc).__name__}: {exc}），跳过审稿",
            file=sys.stderr,
        )
        return

    try:
        review = review_answer(
            client=client,
            model=model,
            question=question,
            answer=answer,
            citations=citations,
            book_title=book_title,
            language=language,
        )
    except Exception as exc:  # noqa: BLE001
        print(
            f"[smoke] reviewer 调用失败（{type(exc).__name__}: {exc}），跳过审稿",
            file=sys.stderr,
        )
        raw = getattr(exc, "raw_text", None)
        if raw:
            print("[smoke] ---- raw reviewer output ----", file=sys.stderr)
            print(raw, file=sys.stderr)
        return

    fields = {
        "question": question,
        "book_title": book_title,
        "answer": answer,
        "citations": citations,
    }
    try:
        print_report(fields=fields, review=review, provider=provider, model=model)
    except Exception as exc:  # noqa: BLE001
        print(
            f"[smoke] reviewer 报告打印失败（{type(exc).__name__}: {exc}），忽略",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------


def main() -> int:
    provider = os.environ.get("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")
    question = os.environ.get("BOOKSCOPE_SMOKE_QUESTION", DEFAULT_QUESTION)

    print(f"[smoke] provider = {provider}")
    print(f"[smoke] question = {question}")
    print("-" * 60)

    try:
        adapter, model = _build_adapter_and_model(provider)
    except RuntimeError as exc:
        print(f"[smoke] 配置错误: {exc}", file=sys.stderr)
        return 1

    book, chunks, kg, vector_store = _load_book_session()

    # 如作者显式要求（BOOKSCOPE_SMOKE_EXTRACT_KG=1），走真 KG 抽取覆盖手工 KG。
    # 默认跳过——KG 抽取代价远高于单次 agent query，不适合每跑一次 smoke 都跑。
    try:
        real_kg = _maybe_extract_real_kg(
            adapter=adapter,
            model=model,
            chunks=chunks,
            book_title=book.title,
            language=getattr(book, "language", "zh") or "zh",
        )
    except Exception as exc:  # noqa: BLE001 — extractor 失败不能阻塞链路
        print(
            f"[smoke] 真 KG 抽取失败（{type(exc).__name__}: {exc}），"
            "继续使用手工 KG",
            file=sys.stderr,
        )
        real_kg = None
    if real_kg is not None:
        kg = real_kg

    from bookscope.agent import AgentLoop
    from bookscope.agent.backends.r0_assembler import R0BookAssembler

    assembler = R0BookAssembler(
        book_text=book,
        chunks=chunks,
        knowledge_graph=kg,
        session_vector_store=vector_store,
    )
    backends = assembler.build_all()
    if backends["search"] is None:
        print("[smoke] 警告：vector store 装配失败，search_chunks 不可用。", file=sys.stderr)
        return 2

    timeout_seconds = float(os.environ.get("BOOKSCOPE_SMOKE_TIMEOUT", "600"))
    max_iter_env = os.environ.get("BOOKSCOPE_SMOKE_MAX_ITER")
    loop_kwargs: dict[str, Any] = {
        "client": adapter,
        "search_chunks_backend": backends["search"],
        "chapter_range_backend": backends["chapter_range"],
        "list_characters_backend": backends["list_characters"],
        "model": model,
        "timeout_seconds": timeout_seconds,
    }
    if max_iter_env:
        loop_kwargs["max_iterations"] = int(max_iter_env)
    loop = AgentLoop(**loop_kwargs)

    print(f"[smoke] 使用模型 {model}；发起查询...")
    t0 = time.monotonic()
    try:
        result = loop.query(question)
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke] agent loop 失败: {type(exc).__name__}: {exc}", file=sys.stderr)
        # 第 N 次诊断：即便 timeout / max_iter / tool_error / format_error
        # 也 dump trace + 如有 raw_text（format_error 特有）也 dump
        partial_trace = getattr(exc, "trace", None)
        if partial_trace is not None:
            print("[smoke] ---- partial trace ----", file=sys.stderr)
            try:
                print(
                    json.dumps(
                        partial_trace.model_dump(), ensure_ascii=False, indent=2
                    )
                )
            except Exception as dump_exc:  # noqa: BLE001
                print(f"[smoke] trace dump 失败: {dump_exc}", file=sys.stderr)
        raw_text = getattr(exc, "raw_text", None)
        if raw_text is not None:
            print("[smoke] ---- raw LLM final text ----", file=sys.stderr)
            print(raw_text)
        return 3

    elapsed = time.monotonic() - t0
    print(f"[smoke] 完成（{elapsed:.1f}s）")
    print("=" * 60)
    print("[answer]")
    print(result.answer)
    print()
    print("[citations]")
    print(json.dumps(result.citations, ensure_ascii=False, indent=2))
    print()
    print("[trace]")
    print(json.dumps(result.trace.model_dump(), ensure_ascii=False, indent=2))

    # 第 27 轮 Task #27.5：按需触发 reviewer。失败 != smoke 失败。
    _maybe_run_reviewer(
        question=question,
        answer=result.answer,
        citations=result.citations,
        book_title=book.title,
        language=getattr(book, "language", "zh") or "zh",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
