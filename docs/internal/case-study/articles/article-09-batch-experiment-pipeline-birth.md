# 批量实验 Pipeline 的诞生：从手工 30 分钟到自动 10 分钟的研究 infra

> **状态**：草稿 · 作者未定稿
> **时段**：2026-04-27（第 26 轮当晚 · batch runner 第一次自己跑完 5 题的那一晚）
> **覆盖 commit / 数据**：`scripts/run_batch_r1.py`（新 · ~360 行）/ `scripts/compare_batches.py`（新 · ~170 行）/ `scripts/smoke_test_r1.py`（单题对照参考）/ `scripts/review_last_smoke.py`（第 25 轮 reviewer 调用入口）/ `bookscope/agent/reviewer.py` / `docs/internal/experiments/data/v2-batch-01.json`（手工 batch）/ `docs/internal/experiments/data/v3.1-minimax-batch-01.json`（runner 自动 batch）
> **视角**：研究 infra 工程
> **匿名化**：全文以"作者" / "项目负责人" / "副管理"等职能称谓指代

---

## 一、第 25 轮那一晚：5 题手工跑的 30 分钟

要写 batch runner 怎么诞生，先得把 batch runner 没有的那一晚记下来。

第 25 轮我刚把 reviewer agent 跑通——`reviewer_rubric_v1.md` + `reviewer.py` + `review_last_smoke.py` 一套，AI-as-judge pipeline 第一次完整闭环：v1 prompt 跑出 23/25，按 reviewer 挑出的两条 issue（"偏向诊断少开处方"、"answer-citation 章节号错位"）改出 v2 prompt，同题重跑 25/25。actionability 4→5、honesty 4→5。

那一晚的最后一件事，是把 v2 prompt 跑全 5 题作家诊断题、产出 `v2-batch-01.json` 作为 baseline。这个 JSON 后来成了第 26 轮一切对照的起点，但写它的那一晚特别难受。

流程是这样的：

1. 起一个终端，`set ASTRON_API_KEY=...` + `set BOOKSCOPE_SMOKE_QUESTION="<第一道作家题>"`，跑 `python scripts/smoke_test_r1.py`
2. 等大约 90 秒（astron-code-latest 在 32K 字书 + 1069 chunk 上一次 query 的真实耗时是 100s ± 30s）
3. smoke 跑完后控制台一大坨输出：question / 书名 / answer / citations / trace。把这一段 stdout 重定向到一个 `.txt` 文件
4. 切到第二个终端，`python scripts/review_last_smoke.py /path/to/that.txt`，调 reviewer。又等大约 30 秒
5. reviewer 跑完后输出一份评分报告：5 维分数 + per-dim comment + overall + top issues + single_most_valuable_improvement
6. 我把 question / answer / citations / trace_summary / scores / comments / overall 一条条手抄进 `v2-batch-01.json` 这个手写 JSON 文件。每条手抄要 3-5 分钟——尤其 answer 字段几千字中文，一不小心就漏个换行
7. 抄完一题。回到第 1 步，换下一道题

5 题。每题 query 90 秒 + reviewer 30 秒 + 上下文切换 + 手抄 = **单题 ~6 分钟实际占用**。理论下限 ~10 分钟，实际盯了 30 分钟，因为：

- 中间一题 reviewer JSON parse 失败，ASCII 引号转义炸了，要回去看 raw text、决定是 prompt 问题还是 parser 问题
- 中间另一题 reviewer 输出里某个 dim comment 引号没转义，手抄进 JSON 时 IDE 报红，要回到原始 stdout 去比对
- 切完终端忘了哪道题在跑，看错 question
- 网络一次不稳，astron 504，重跑

最折磨的不是这 30 分钟本身，是**这 30 分钟里我什么都不能干**。我必须坐在屏幕前盯着——每跑完一道题要立刻起下一道，不然就会忘了流程跑到哪。我没法去写 STATE，没法去翻 reviewer comments 里值得记的那两句，更没法去想"如果这次 reviewer 给的 single_most_valuable_improvement 是真的，那 v3 prompt 该往哪走"。

那一晚跑完后我看着 `v2-batch-01.json` 的 506 行手写 JSON，第一次清晰地意识到：**这个流程本身就是 BookScope 研究节奏的瓶颈**。reviewer 已经把"评判从作者人工挪到 AI"，但生成 → 审稿 → 归档这条流水线还卡在我手指上。

第 26 轮一开始作者说"继续，但是我们的 api 更新了。这次用的是 minimax，用的 2.7 的模型"。我没急着切 base_url。我先做了一件别的事——写 batch runner。

---

## 二、smoke 是单题调试入口，runner 是研究批跑入口——它们是两件不同的事

先说清楚为什么不直接改 `smoke_test_r1.py`。

smoke 这个脚本的设计目标是单题手动调试——它的全部价值就在"给你一道题、一个 provider、一段 stdout，让你看清楚 agent loop 这一次到底发生了什么"。它的 main flow 大概长这样：

```python
def main() -> int:
    provider = os.environ.get("BOOKSCOPE_SMOKE_PROVIDER", "deepseek")
    question = os.environ.get("BOOKSCOPE_SMOKE_QUESTION", DEFAULT_QUESTION)
    adapter, model = _build_adapter_and_model(provider)
    book, chunks, kg, vector_store = _load_book_session()
    # ...
    loop = AgentLoop(**loop_kwargs)
    result = loop.query(question)
    print("[answer]"); print(result.answer)
    print("[citations]"); print(json.dumps(result.citations, ...))
    print("[trace]"); print(json.dumps(result.trace.model_dump(), ...))
    return 0
```

它一题一题跑、一题一题看 stdout，是设计目的。如果我硬把它改成多题循环：

- `BOOKSCOPE_SMOKE_QUESTION` 这个 env var 怎么传 5 个？
- 中间一题失败要不要中断？smoke 默认中断（`return 3`）才能让我立刻看堆栈
- reviewer 要不要内嵌？smoke 现在不调 reviewer——内嵌就破坏了"单题最小路径"的简洁性
- 输出格式怎么定？stdout 一坨人类可读的文本和 JSON 文件需要的结构化 output 完全不同

把这些需求堆进 smoke 会让它变成一个臃肿的"既能单题又能批跑既能审稿又能不审稿"的开关怪物。每次调试都得想"我现在是哪一种模式"。第 17 轮砍掉 reranker、第 19 轮把 astron 在 API 层一等公民化的时候我已经吃过够多苦头，知道**两种调用形态用同一个 entry point 是技术债的常见入口**。

所以我决定：smoke 不动，新写 `run_batch_r1.py`。两个入口并存——smoke 是单题调试入口，runner 是研究批跑入口。它们共享底层（`_load_book_session` / `_build_adapter_and_model` 这两个 helper），但 main flow 各自独立。

实际共享是这样实现的：

```python
# scripts/run_batch_r1.py 顶部
from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
    _build_adapter_and_model,
    _load_book_session,
)
```

直接 import smoke 的两个内部 helper。`# type: ignore` 留着——`scripts/` 下没有 `__init__.py`，linter 不认这种跨脚本 import，但 runtime 走的是 `sys.path.insert(0, _PROJECT_ROOT)` 这条 hack 后的路径，能跑。要不要给 `scripts/` 加包结构？暂不——案例研究 infra 不该比研究本身复杂。

---

## 三、`run_batch_r1.py` 的设计骨架

整个 runner 大约 360 行。核心是三件事：

1. CLI 解析（`_parse_args`，~38 行）：从一个题集 JSON 读 N 题、把 batch_id / generator_prompt / citation_format / reviewer_rubric 这些"元信息"字段当 CLI 参数收
2. 一次 load book + 装配 backends（沿用 smoke 的 `_load_book_session` + `R0BookAssembler.build_all`），多题共享同一份 chunks / KG / vector store
3. N 题循环：每题调 `_run_one_question`，把 generator + reviewer 的产出装回结构化 dict，最后写到 `--output` 指定的 JSON

CLI 部分照抄不用解释，直接看第 2 步：

```python
print("[batch] 加载书 + 装配 backends ...")
book, chunks, kg, vector_store = _load_book_session()
assembler = R0BookAssembler(
    book_text=book,
    chunks=chunks,
    knowledge_graph=kg,
    session_vector_store=vector_store,
)
backends = assembler.build_all()
if backends["search"] is None:
    print("[batch] vector store 装配失败", file=sys.stderr)
    return 3

timeout_seconds = float(os.environ.get("BOOKSCOPE_SMOKE_TIMEOUT", "600"))
max_iter_env = os.environ.get("BOOKSCOPE_SMOKE_MAX_ITER")
loop_kwargs: dict[str, Any] = {
    "client": gen_adapter,
    "search_chunks_backend": backends["search"],
    "chapter_range_backend": backends["chapter_range"],
    "list_characters_backend": backends["list_characters"],
    "model": gen_model,
    "timeout_seconds": timeout_seconds,
}
if max_iter_env:
    loop_kwargs["max_iterations"] = int(max_iter_env)
loop = AgentLoop(**loop_kwargs)
```

关键是 `loop = AgentLoop(...)` 在 N 题循环**之外**构造一次。

这点从工程代价角度很重要。`_load_book_session` 这一步要做的事是：epub 解析（loader.py，按 ebooklib 路径）、chunk_book（按章节切 1069 chunk）、构造 BookKnowledgeGraph、构造 SessionVectorStore（BM25 索引建好，~1069 chunk 的 BM25 索引在我的笔电上要 800ms-1.2s）。这一坨在 32K 字 / 1069 chunk 的《明朝那些事儿》上单次约 3-5 秒。手工跑 5 题要重复 5 次——光 load book 就丢掉 15-25 秒。runner 一次 load 全程复用，省掉的不是 CPU 而是 wall-clock latency。

接下来是 N 题循环：

```python
results: list[dict[str, Any]] = []
t_batch_start = time.monotonic()
for idx, q in enumerate(questions, start=1):
    qid = q.get("id", f"q{idx}")
    qtype = q.get("type", "")
    qtype_desc = q.get("type_description", "")
    question = (q.get("smoke") or {}).get("question") or q.get("question")
    if not question:
        print(f"[batch] [{idx}/{len(questions)}] {qid} 跳过（缺 question）")
        continue
    print(f"[batch] [{idx}/{len(questions)}] {qid} [{qtype}]")
    print(f"   Q: {question[:100]}{'...' if len(question) > 100 else ''}")

    rec = _run_one_question(
        loop=loop,
        reviewer_client=review_adapter,
        reviewer_model=review_model,
        question=question,
        book_title=book_title,
        language=language,
    )
    rec_full: dict[str, Any] = {
        "id": qid,
        "type": qtype,
        "type_description": qtype_desc,
        **rec,
    }
    results.append(rec_full)

    smoke = rec.get("smoke", {})
    review = rec.get("review", {})
    err = rec.get("error")
    cite = smoke.get("citation_count", 0)
    dur = smoke.get("duration_s", 0)
    total = review.get("total")
    print(
        f"   → dur={dur}s cite={cite} "
        f"total={total if total is not None else 'N/A'} "
        f"{'ERR=' + err if err else ''}"
    )
    print()
```

每题打印一行单题状态——`dur=87.1s cite=5 total=18`——让我把电脑放着去写 STATE 时偶尔扫一眼终端就知道跑到第几题、有没有掉队。这是把"30 分钟必须盯屏幕"降到"10 分钟可以扫一眼"的关键 UX 设计。

写到这里我看了一眼：4 行 print。占总代码量大概 0.5%。但它决定了"我能不能在 runner 跑的时候同时干别的"。

---

## 四、`_run_one_question`：失败不中断的 try/except 设计

整个 batch runner 最关键的一段是 `_run_one_question`。它的设计前提是：**一道题失败不能拖垮 5 题**。

第 25 轮手工跑那一晚就被这件事咬过——第 3 题 reviewer JSON parse 失败，我得先 debug 这一题、再决定要不要把已经跑完的 1、2 题丢掉重新来。如果 batch 跑到第 3 题时整个进程崩溃，前两题 query 用掉的 ~3 分钟和 ~30 万 input token 全部白费。runner 必须把这种事故隔离到单题，让其他题继续。

实现是双层 try/except——loop 失败和 reviewer 失败分别处理：

```python
def _run_one_question(
    *,
    loop: Any,
    reviewer_client: Any,
    reviewer_model: str,
    question: str,
    book_title: str,
    language: str,
) -> dict[str, Any]:
    """跑一道题：generator → reviewer，返回单条 result dict。

    失败时（loop 抛异常 / reviewer JSON 解析失败）会把字段尽量填上
    并把 error 信息塞进结果，**不中断 batch**——避免一道题失败拖垮 5 题。
    """
    from bookscope.agent.errors import AgentError, LLMFormatError
    from bookscope.agent.reviewer import review_answer

    smoke: dict[str, Any] = {"question": question}
    review: dict[str, Any] = {}
    error: str | None = None

    t0 = time.monotonic()
    try:
        result = loop.query(question)
    except (AgentError, Exception) as exc:  # noqa: BLE001
        elapsed = time.monotonic() - t0
        smoke.update({
            "duration_s": round(elapsed, 1),
            "outcome_error": f"{type(exc).__name__}: {exc}",
        })
        error = f"loop_failed: {type(exc).__name__}"
        # trace 在异常上时也带上
        partial_trace = getattr(exc, "trace", None)
        if partial_trace is not None:
            try:
                smoke["trace_summary"] = _extract_trace_summary(partial_trace)
            except Exception:  # noqa: BLE001
                pass
        return {"smoke": smoke, "review": review, "error": error}

    elapsed = time.monotonic() - t0
    smoke.update({
        "duration_s": round(elapsed, 1),
        "answer": result.answer,
        "citations": result.citations,
        "citation_count": len(result.citations),
        "trace_summary": _extract_trace_summary(result.trace),
    })

    # reviewer
    try:
        review = review_answer(
            client=reviewer_client,
            model=reviewer_model,
            question=question,
            answer=result.answer,
            citations=result.citations,
            book_title=book_title,
            language=language,
        )
        scores = review.get("scores", {})
        if isinstance(scores, dict):
            review["total"] = sum(
                v for v in scores.values() if isinstance(v, (int, float))
            )
    except LLMFormatError as exc:
        error = f"reviewer_format_error: {exc}"
        review = {"_error": error, "_raw_text": getattr(exc, "raw_text", None)}
    except Exception as exc:  # noqa: BLE001
        error = f"reviewer_failed: {type(exc).__name__}: {exc}"
        review = {"_error": error}

    return {"smoke": smoke, "review": review, "error": error}
```

设计要点几条：

第一，**loop 失败时仍然挂 trace**。第 24 轮我加过一次诊断改进——给 `LLMFormatError` 异常挂 `.trace` 和 `.raw_text`。这次 batch runner 的 fail-soft 路径直接利用这个 trace：即便 query 抛异常，只要异常上有 partial trace，我们就把 `tool_calls` / `iterations` / token 数等字段抢救出来塞进结果。下次审 batch 时即便有题失败，也能看到"它跑了 3 轮调了 4 次 tool 才在第 4 次因为 timeout 挂掉"这种信息。

第二，**reviewer 失败要区分类型**。`LLMFormatError`（reviewer 输出 JSON 解析不出来）保留 raw_text 给后续诊断；其他异常（网络、quota、provider 端 500）只记 type 名。这两类 error 的修法完全不同——前者要看是不是 prompt 该改、parser autofix 该加；后者只是重跑就行。把它们混在一个 except 里会让"为什么 reviewer 炸了"的诊断变成猜谜。

第三，**所有失败路径都走 return，不 raise**。`smoke` / `review` / `error` 三个字段总是有，结构稳定。下游 `_build_summary` 拿到这条 record 时哪怕是 error 题也不会 crash，只是该题的 score 统计被跳过。

第四，注意 `total` 字段是在 runner 这边算的，不是 reviewer 自己给的。reviewer rubric 出 5 维分数（每维 1-5），runner 把 5 维求和写进 `review["total"]`。这个细节是从手抄 v2-batch-01.json 那一晚学到的——手抄时我自己边抄边算，每题都要 `5+5+5+5+5=25` 心算一次，错过两次。runner 算一次写一次，永远对。

---

## 五、`_extract_trace_summary` 与一个差点葬送两次 pilot 的字段名 bug

batch runner 还做了一件事：把 `LoopTrace` 这个 Pydantic 模型 model_dump 出来后**抽 summary 字段子集**，对齐 v2-batch-01.json 的手写结构。

```python
def _extract_trace_summary(trace: Any) -> dict[str, Any]:
    """从 LoopTrace 抽出 summary 字段子集（与 v2-batch-01 结构对齐）。

    LoopTrace 的字段名是 ``tool_calls``（不是 tool_invocations），每个
    dict 的工具名是 ``tool_name`` 字段——v2-batch-01.json 是手工填的所以
    用了别名 ``tool_call_names``，本函数做 surface mapping。
    """
    d = trace.model_dump() if hasattr(trace, "model_dump") else dict(trace)
    tool_calls = d.get("tool_calls") or []
    return {
        "iterations": d.get("iterations"),
        "duration_ms": d.get("duration_ms"),
        "total_input_tokens": d.get("total_input_tokens"),
        "total_output_tokens": d.get("total_output_tokens"),
        "outcome": d.get("outcome"),
        "tool_call_names": [
            tc.get("tool_name") for tc in tool_calls
            if isinstance(tc, dict) and tc.get("status") == "ok"
        ],
        "tool_call_count_total": len(tool_calls),
    }
```

这十几行代码差点葬送了第 26 轮整两次 pilot。

第一次写这个 helper 时我**记错了字段名**——记成 `tool_invocations` 和 `name`：

```python
# 错版（已修）
tool_invocations = d.get("tool_invocations") or []  # ← 字段不存在，永远空 list
return {
    ...
    "tool_call_names": [
        ti.get("name") for ti in tool_invocations  # ← 永远空
    ],
}
```

为什么会记错？因为 LoopTrace 这个 Pydantic 模型我已经一两个月没碰了，第 11 轮起草时取过一次决定 `tool_calls` 还是 `tool_invocations`、`name` 还是 `tool_name`，最后定的是前者。但写 batch runner 这天我凭印象敲。

后果是非常诡异的：第 26 轮 v3 pilot 跑完，trace_summary 显示 `tool_call_names: []`、`tool_call_count_total: 0`——5 轮迭代下 minimax 一次 tool 都没调。我看到这个数据立刻得出结论"MiniMax-M2.7 在公开书上靠记忆作答、训练污染"。这个结论其实**最终是对的**，但当时是基于错误数据得出的。

写出 v3.1 prompt 加 tool 强制约束之后，第二次 pilot 仍然显示 0 tool。我开始怀疑 minimax 是不是连 v3.1 的硬约束都不听。

直到第三次 pilot 失败前，我顺手 grep 了一下源码，才发现 LoopTrace 的真正字段是 `tool_calls`，每个元素的 key 是 `tool_name`——不是 `tool_invocations` 不是 `name`。

修两个字符串。第三次 pilot 跑通了，trace 显示 tool_calls 真实是 7（5 search + 1 chapter_range + 1 search）。

这是研究 infra 的"二阶 bug"——它不是产品代码的 bug，是观测代码的 bug。它的危险在于：**它会让你对产品本身做出错误诊断**。我差点根据"v3.1 强制 tool 之后仍 0 tool 调用"这个错误观察去再写一版 v3.2 prompt 加更狠的约束——而真实情况是 v3.1 已经起作用了，是我读取 trace 的代码在骗我。

修完之后 STATE 里我老老实实记了一句："**之前两次 pilot 的 0 tool 是误报**"。这句话比当时随手敲的代码更值钱——它是一份给未来三个月后的我自己的提醒：**写观测代码时要和产品代码同样严格**。

---

## 六、输出 schema：与 v2-batch-01.json 同结构

runner 的输出 JSON 结构和第 25 轮手写的 `v2-batch-01.json` **位对位对齐**，不另立 schema。原因很现实：未来 `compare_batches.py` 要把这两份对照报告拼起来；如果 schema 不齐，比较代码每对一个字段就要写 fallback。

输出顶层结构：

```python
out = {
    "batch_id": args.batch_id,
    "created_at": time.strftime("%Y-%m-%d"),
    "book": {
        "title": book_title,
        "path": str(getattr(book, "source_path", "test明朝那些事儿.epub")),
        "word_count": getattr(book, "word_count", None),
        "chunk_count": len(chunks),
    },
    "config": {
        "generator_provider": provider,
        "generator_model": gen_model,
        "generator_prompt": args.generator_prompt,
        "citation_format": args.citation_format,
        "kg_source": "manual_4_characters_朱元璋_李善长_徐达_常遇春",
        "vector_mode": "bm25_only",
        "reviewer_provider": review_provider,
        "reviewer_model": review_model,
        "reviewer_rubric": args.reviewer_rubric,
        "limitation": "reviewer 与生成方同 provider/model；存在自我偏袒风险"
        if review_provider == provider and review_model == gen_model
        else "reviewer 与生成方异 provider/model；可视为部分独立审稿",
    },
    "questions": results,
    "summary": summary,
}
```

几个值得说明的字段：

`config.generator_prompt` / `citation_format` / `reviewer_rubric` 这三项是**纯记录字段**——runner 不读它们做行为决策（实际 prompt 由 `loop.py` 里的硬编码 import 决定，loop.py 切一行就切版本）。但它们必须写进 JSON——三个月后回看 `v3.1-minimax-batch-01.json` 时，没有这三个字段我根本记不住"这是 v3.1 prompt 跑的还是 v3 跑的"。

`config.limitation` 是动态的——如果 reviewer provider/model 与 generator 一致，写"自我偏袒风险"；不一致写"部分独立审稿"。这是从第 25 轮 review_last_smoke.py 学来的：**limitation 不能埋在 README，要写在数据里**。三个月后回看一份 batch JSON 还需要去 grep README 找它的局限性，那个 batch 就废了。

`questions` 字段下每条记录的结构：

```json
{
  "id": "q1",
  "type": "节奏评估",
  "type_description": "...",
  "smoke": {
    "question": "...",
    "duration_s": 87.1,
    "answer": "...",
    "citations": [...],
    "citation_count": 5,
    "trace_summary": {
      "iterations": 3,
      "duration_ms": 87123,
      "total_input_tokens": 115639,
      "total_output_tokens": 2300,
      "outcome": "success",
      "tool_call_names": ["get_chapter_range", "search_chunks"],
      "tool_call_count_total": 2
    }
  },
  "review": {
    "scores": {...},
    "per_dimension_comment": {...},
    "overall": "...",
    "top_issues": [...],
    "single_most_valuable_improvement": "...",
    "total": 18
  },
  "error": null
}
```

注意 `tool_call_count_total` 这个字段——v2-batch-01.json 手写时我没加这个字段，因为手写时根本不知道 LoopTrace 内部 `tool_calls` 列表里有多少 `status != "ok"` 的失败调用（手写只能照抄成功的工具名）。runner 加这个字段是因为它**自动**能读到全量 tool_calls，包括失败的。后来这个字段在 v3.1 batch 的 q1 里救了一次——q1 的 `tool_call_names` 是 `["get_chapter_range", "search_chunks"]`（长度 2），`tool_call_count_total` 是 2，匹配。说明这一题没有失败 tool。如果有失败的话两个数会不等，而那个差值就是 debug 的入口。

`summary` 字段是 `_build_summary` 算出来的——5 题的 5 维平均分、平均 total、min/max、success_count、total_duration_s、token 总数。结构上和手写 v2-batch-01 也一致。

---

## 七、`compare_batches.py`：对照报告的极简设计

runner 的 sibling 是 `compare_batches.py`——把两份 batch JSON 拼成一份对照报告。整个脚本 ~170 行，核心三块：

1. `_print_config`：把两个 batch 的 config 字段打出来，让读者一眼看清"我现在比的是哪两组"
2. `_summary_diff`：总览均值差（average_total / 5 维 / min / max / 耗时 / token）
3. `_per_question_diff`：5 题逐题 winner / loser / tie，附 5 维差

`_print_config`：

```python
def _print_config(label: str, batch: dict[str, Any]) -> None:
    cfg = batch.get("config") or {}
    print(f"  {label}:")
    print(f"    batch_id        = {batch.get('batch_id')}")
    print(f"    generator       = {cfg.get('generator_provider')}/{cfg.get('generator_model')}")
    print(f"    generator_prompt= {cfg.get('generator_prompt')}")
    print(f"    reviewer        = {cfg.get('reviewer_provider')}/{cfg.get('reviewer_model')}")
    print(f"    reviewer_rubric = {cfg.get('reviewer_rubric')}")
    print(f"    limitation      = {cfg.get('limitation', '(none)')}")
```

每次跑对照之前先打一遍——"baseline 是 astron + v2 + reviewer_rubric_v1，candidate 是 minimax + v3.1 + reviewer_rubric_v1"。这是把**实验前提**显式化到报告头。三个月后看见这段头，对比 4.8 分差距时不会忘了 reviewer rubric 没动、generator 和 prompt 同时换了——这影响"4.8 分到底是 prompt 锅还是 generator 锅"的归因。

`_summary_diff` 的输出格式：

```
====================================================================
总体均值对比
====================================================================
指标                              baseline    candidate          Δ
--------------------------------------------------------------------
average_total (out of 25)            24.80        20.00       -4.80
  structural_judgment                 5.00         4.40       -0.60
  evidence_density                    5.00         3.60       -1.40
  honesty                             5.00         4.00       -1.00
  actionability                       4.80         3.60       -1.20
  cross_chapter_coherence             5.00         4.40       -0.60
min_total                            24.0         18.0
max_total                            25.0         23.0
success rate                         all          5/5
total duration (s)                  587.6        862.9
total input tokens                940389       569722
```

`evidence_density -1.4` 这一行是第 26 轮"训练污染"诊断的核心证据——它告诉我 candidate 在"原文密度"这一维退化最严重，而 structural_judgment / cross_chapter_coherence 退化只有 0.6（结构判断和跨章视野基本保住了）。这种**维度级**的差异如果只看 average_total -4.8，看不出来；只有 5 维分别打才能定位。

`_per_question_diff` 给每题 winner/loser 判定：

```python
for qid in ids:
    b = base_by_id.get(qid) or {}
    c = cand_by_id.get(qid) or {}
    bt = _safe_float((b.get("review") or {}).get("total"))
    ct = _safe_float((c.get("review") or {}).get("total"))
    # ...
    delta = None
    verdict = "n/a"
    if bt is not None and ct is not None:
        delta = ct - bt
        if delta > 0.5:
            verdict = "candidate WIN"; win += 1
        elif delta < -0.5:
            verdict = "candidate LOSE"; lose += 1
        else:
            verdict = "tie"; tie += 1
```

阈值 ±0.5——小于这个差认为是 reviewer 噪声，不算赢也不算输。这个数字是从手抄 v2 batch 那晚学到的：**同 prompt 同题同 reviewer 重复跑 reviewer 单题，分数会在 ±1 抖动**（reviewer 也是 LLM，有随机性）。0.5 这个阈值偏严，但能避免 25.0 vs 24.5 这种"差半分就喊 LOSE"的过度反应。

逐题块每题打 ~6 行：

```
  [q1] [节奏评估] candidate LOSE
    total : baseline=25.0  candidate=18.0  Δ=-7.0
    cite  : baseline=10  candidate=5  tool_calls=2
    dur(s): baseline=102.6  candidate=87.1
      structural_judgment: 5 → 4 (-1)
      evidence_density: 5 → 3 (-2)
      honesty: 5 → 4 (-1)
      actionability: 5 → 3 (-2)
      cross_chapter_coherence: 5 → 4 (-1)
```

`tool_calls=2` 这个字段是 candidate 才有的（baseline v2 batch 是手写没填 tool_call_count_total）。我刻意没回头补 baseline 的这个字段——三个月后看这份报告时，这个不对称本身就是 v2 → v3.1 流程演进的痕迹。

末尾汇总一句：`汇总: candidate WIN 0 / LOSE 5 / TIE 0`。这一行直接定调——5/5 全输，没有"有的题输有的题赢"的余地。如果是 3/2 这种比分，结论会复杂得多；5/0 让方向感很清晰。

整个脚本**不写文件**，纯 stdout——作者自己 copy 到 STATE / case-study 即可。这是有意的设计选择。要写文件意味着要决定文件名格式 / 路径 / 是否覆盖 / 是否带时间戳——这些决定每个都是另一个小 schema。pure stdout 让"对照"这个动作保持极简：跑命令、看输出、需要的话 copy 一份到 case-study 当证据。

---

## 八、第 26 轮那一晚：runner 在后台跑、人在另一边写 STATE

写完 runner 和 compare 大概 90 分钟。然后跑第 26 轮的 v3.1 batch。

我敲下：

```bash
MINIMAX_API_KEY=sk-cp-xxxxx \
PYTHONIOENCODING=utf-8 \
python scripts/run_batch_r1.py \
    --questions docs/internal/experiments/data/v2-batch-01.json \
    --output    docs/internal/experiments/data/v3.1-minimax-batch-01.json \
    --batch-id  v3.1-minimax-batch-01 \
    --generator-prompt loop_system_prompt_v3.1 \
    --citation-format  citation_format_v1 \
    --reviewer-rubric  reviewer_rubric_v1
```

回车。看到 `[batch] 加载书 + 装配 backends ...`，然后 `[batch] [1/5] q1 [节奏评估]`、`Q: 从第14章审问张士诚...`。

然后我打开了第二个窗口开始写 `docs/internal/STATE.md` 第 26 轮的执行链摘要。

终端那边每过一两分钟跳一行：

```
[batch] [1/5] q1 [节奏评估]
   Q: 从第14章审问张士诚，到第20章李善长之死，朱元璋清洗开国功臣的整条弧线在叙事节奏...
   → dur=87.1s cite=5 total=18

[batch] [2/5] q2 [支线密度]
   Q: 陈友谅作为朱元璋建国前最大的对手，在书里的描写集中分布在哪几章？...
   → dur=77.5s cite=5 total=19
```

我能在余光看到分数。q1=18、q2=19——比 baseline 25/25 退化了 6-7 分，方向已经很清楚了。但我没有打断 runner 去 debug——我让它继续跑，因为我知道：

1. 即便我现在看出有问题，也只能等 runner 跑完才有完整 5 题数据可信度
2. 跑完才能跑 compare_batches，才有总览
3. 中断 runner 等于丢掉前 2 题的 ~3 分钟

这个心态变化是研究 infra 装备齐全后的副产品——**我可以信任流程跑完再看**。手工跑那一晚我每一题跑完都要决定"要不要继续"，因为下一题怎么跑、跑什么 prompt 全在我手里；现在 runner 在跑，我在写，两件事并行。

batch 跑了 862.9 秒（~14 分钟）。runner stdout 末尾打：

```
[batch] 完成，写出 docs/internal/experiments/data/v3.1-minimax-batch-01.json
[batch] 总耗时 862.9s
[batch] 平均 total = 20.0
```

然后 compare_batches：

```bash
python scripts/compare_batches.py \
    --baseline docs/internal/experiments/data/v2-batch-01.json \
    --candidate docs/internal/experiments/data/v3.1-minimax-batch-01.json
```

看到 5 题逐题 LOSE、平均 20.0、`evidence_density -1.4`——**这就是第 26 轮"训练污染"诊断的全部数据来源**。15 分钟前我还在写 STATE 草稿"换了 minimax 之后会发生什么"，15 分钟后我已经有了完整的 5 题对照证据，可以把"训练污染"这件事写进结论。

总耗时复盘：

| 阶段 | 第 25 轮（手工） | 第 26 轮（runner） | 节省 |
|------|-----|-----|------|
| 5 题 query + reviewer | ~10 分钟（理论下限） | 14 分钟（runner 自动） | — |
| 上下文切换 + 手抄 | ~20 分钟 | 0 | -20 分钟 |
| **总计** | ~30 分钟（人盯屏） | ~15 分钟（自动）+ 0 上下文切换 | -15 分钟 wall clock + 解放注意力 |

第 26 轮 runner 实际跑得比第 25 轮手工还慢一点（862.9s vs 587.6s），主要是 minimax 单题平均比 astron 慢。但这不重要——**真正变的不是 5 题耗时，是 5 题期间作者的可用性**。

---

## 九、研究 infra 与产品 infra 的双轨

写完 `run_batch_r1.py` + `compare_batches.py` 这两个脚本后，BookScope 项目的"研究 infra"第一次有了清晰边界。

之前两条 infra 是混在一起的：

- **产品 infra**：`bookscope/agent/loop.py` / `bookscope/agent/adapters/` / `bookscope/agent/backends/` / `bookscope/api/` / `web/`——服务作家用户跑查询的所有东西
- **研究 infra**：`scripts/smoke_test_r1.py` / `bookscope/agent/reviewer.py` / `scripts/review_last_smoke.py` / `docs/internal/experiments/data/*.json` / `docs/internal/case-study/`——服务作者作为研究者本人评估产品质量、迭代 prompt 的所有东西

第 25 轮添加 reviewer agent 是研究 infra 的第一次重大扩张——从"我自己评分"挪到"AI 评分"。第 26 轮 batch runner + compare_batches 是第二次——从"我自己跑"挪到"runner 跑、我写 STATE"。

这两套 infra 互相喂数据：

```
作家题（研究 infra 出题）
        ↓
  AgentLoop.query（产品 infra 跑）
        ↓
  answer + citations + trace
        ↓
  reviewer.review_answer（研究 infra 审稿）
        ↓
  scores + comments + top_issues
        ↓
  compare_batches（研究 infra 对照）
        ↓
  prompt iteration（v1 → v2 → v3 → v3.1）
        ↓ 写回 bookscope/agent/prompts/
  AgentLoop.query 下一轮（产品 infra 跑）
        ↓
  ...
```

这是 BookScope 改进的正回路。第 25 轮第一次跑通——v1 → v2 prompt 升级，分数 +2。第 26 轮跑 v3.1 反向退化 -4.8——但这次"退化"也喂回 STATE，揭示了"公开书 baseline 已到天花板"这个研究发现，给第 27 轮指了三个候选方向（P1 真用例切换 / prompt 单变量分离 / provider 单变量分离）。

这条循环里**没有人盯屏的环节**。

这是研究 infra 的核心价值——**让 BookScope 的改进闭环不依赖作者注意力**。作者可以去做不可替代的事（NORTH_STAR 月度更新、用自己的稿子做 P1 自试、案例研究定稿），研究 infra 在背景里持续产生数据点。

---

## 十、未来的 batch 设计扩展空间

`run_batch_r1.py` 现在能做的事很有限——单 generator + 单 prompt 跑 N 题。下一步扩展空间已经在 STATE 第 27 轮候选方向里浮现：

**1. Cross-provider 自动盲评**

当前 reviewer 默认用与 generator 同 provider 同 model。`v2-batch-01.json` / `v3.1-minimax-batch-01.json` 的 limitation 字段都明示"自我偏袒风险"。

未来：reviewer 必须用**不同** provider + model。比如 generator=minimax + reviewer=anthropic、generator=astron + reviewer=deepseek。这要求 BookScope 同时持有多家 BYOK（当前作者只有 minimax + astron）。

实现层面 batch runner 已经支持——`BOOKSCOPE_REVIEW_PROVIDER` env var 可独立设置。只要作者 export 不同 key，runner 自动跨 provider。

**2. 多 prompt 同时跑（A/B 实验）**

当前 `loop.py` 切一行 `_LOOP_SYSTEM_PROMPT_PATH` 切版本。这意味着同一个 batch run 不能同时跑 v2 和 v3——要换 prompt 必须改 import 重启 runner。

候选改动：让 batch runner 接受 `--prompt-versions v2,v3,v3.1` 参数，N 题 × M prompt = N×M 次 query；输出按 (qid, prompt_version) 二维 key 组织。一晚跑出"3 个 prompt 在 5 题上的 15 个数据点"。

成本估算：单题 ~90s，5 题 × 3 prompt × ~90s = 22.5 分钟。仍然在"runner 跑、人写 STATE"的可承受范围。

**3. 单变量分离实验**

第 26 轮 v2+astron 24.8 vs v3.1+minimax 20.0，但 prompt 和 generator 同时换了——4.8 分差距到底是 prompt 锅还是 generator 锅，**不知道**。

完整 2×2 表需要四组：

| | prompt v2 | prompt v3.1 |
|---|---|---|
| astron | **24.8** ✓ 已有 | ? 未跑 |
| minimax | ? 未跑 | **20.0** ✓ 已有 |

跑满四组需要 2 × 14 分钟 = 28 分钟。runner 已经支持——把命令跑两次、改 generator + prompt 参数即可。等作者决定方向就跑。

**4. citation_coverage_ratio 二级 metric**

当前 reviewer 给 5 维 1-5 分；评判"原文密度"（evidence_density）部分依赖 reviewer 主观感受。

未来可以加一个**机械计算的二级 metric**：`citation_coverage_ratio = answer 中显式引用 citation 的句数 / answer 总句数`。这个数字不依赖 reviewer，是从 answer + citations 字段直接算出来的。它能交叉验证 reviewer 的 evidence_density 主观分。

第 26 轮的数据已经能撑这个 metric 的 hint——baseline 平均 11 条 citation / candidate 平均 5.6 条 citation。但要落到 ratio 还得算 answer 句数。这是 batch runner 后续的小扩展。

**5. 作家自己未公开稿子**

第 27 轮候选方向 a。把 `BOOKSCOPE_SMOKE_EPUB` 指到作者自己的 .docx / .epub 草稿，用同样 5 题模板（节奏 / 支线 / 伏笔 / 角色转变 / 设定漂移）跑。runner 的 generator/reviewer 路径不用动；变的是数据集——而且这是"训练污染"诊断之后唯一能让 evidence-from-text 价值稳定显现的场景。

写到这里我意识到：runner 当时设计成"读 questions JSON"而不是 hardcoded 5 题，这个决策无意中铺平了未来 P1 私域文本切换的路。换数据集只需要改 `--questions` 参数。

---

## 十一、反思：研究 infra 是案例研究的源代码

合上电脑前我想了一件事。

CLAUDE.md 第三节明确："唯一长期交付物是 `docs/internal/case-study/` 持续打磨的案例研究文档。代码是案例的实验产物，不是交付物本身。"

但案例研究的厚度依赖于实验数据点的密度。

如果第 26 轮我没有 batch runner、没有 compare_batches，5 题手工跑要 30 分钟、且失败成本高、上下文切换重。结果会是：第 26 轮我大概率只跑 q1 单题，看到 17/25 就停下、改 prompt、重跑——到一晚结束最多得到 2-3 个数据点。

而我现在手里有 v2-batch-01（5 题 baseline）+ v3-pilot（v3 prompt 单题，未启用 tool 强制）+ v3.1-pilot（v3.1 prompt 单题）+ v3.1-batch-01（v3.1 全 5 题）—— **22 个数据点**。这 22 个数据点支撑了"训练污染"这个诊断，也支撑了第 27 轮的方向决策。

3 个月后回看时，案例研究第 3 章（暂定写"训练污染暴露的那一晚"）能引用的是 22 个数据点，不是 3 个。读案例研究的人能自己核对 v3.1 的 5 维分数为什么 evidence_density 退化最严重——因为 JSON 还在那。

这就是研究 infra 与案例研究的关系：**研究 infra 不是案例研究的工具，是案例研究的源代码**。每个 batch JSON、每份 compare 报告，都是案例研究将来某一段论证的原始证据。

写工程脚本时我习惯关注"它解决了什么手工痛点"。但 batch runner 真正的长期价值不在解放第 26 轮那一晚的 30 分钟——而在让第 27 轮、第 30 轮、半年后的"案例研究最终定稿"时，作者能从 `docs/internal/experiments/data/` 翻出几十份带完整元信息的 batch JSON，每份都 schema 一致、字段齐全、limitation 明示。这些 JSON 集合起来就是 BookScope 这个案例研究的"实验史"。

副管理姿态下我经常说"不为每一步小决策停下请示"。batch runner 这件事我也没问作者——它是工程优化、auto-accept 范围内的动作。但写完之后我意识到这不是普通的工程优化。这是**研究节奏的相变**——把"实验跑"从一个需要人盯着的 manual ritual 变成可重复、低成本、零上下文切换的自动流程。

下一晚跑实验时，作者决定方向。runner 跑。我在另一边写 STATE。

不再有 30 分钟的上下文切换。

---

## 十二、本篇小结

第 26 轮的 batch runner + compare_batches 不是普通的工程优化，它是 BookScope 研究节奏的相变。

回顾这一晚的几个判断：

- **smoke 不动，新写 runner**：两种调用形态用同一个 entry point 是技术债的常见入口；smoke 是单题调试入口、runner 是研究批跑入口、两者并存
- **失败不中断**：双层 try/except 把 loop 失败和 reviewer 失败分开处理，一题崩不拖垮 5 题；trace 在异常上时也抢救
- **观测代码也要严格**：`tool_invocations` vs `tool_calls` 的字段名 bug 差点让我对产品做出错误诊断，研究 infra 的"二阶 bug"和产品 bug 同样危险
- **schema 对齐 v2 baseline**：未来对照报告依赖结构稳定，不另立 schema；limitation 字段写在数据里，不埋在 README
- **±0.5 阈值**：reviewer 自身有随机性，winner 判定要避免噪声放大
- **pure stdout 不写文件**：让"对照"这个动作保持极简
- **runner 在后台跑、人在另一边写 STATE**：研究 infra 的核心 UX 不是"快"，是"零注意力消耗"
- **研究 infra ↔ 产品 infra 双轨**：产品 infra 出数据、研究 infra 评估、评估反馈喂回 prompt——这条循环里没有人盯屏的环节
- **22 个数据点 vs 3 个数据点**：案例研究的厚度依赖于实验数据点的密度——研究 infra 是案例研究的源代码

第 26 轮的 22 个数据点支撑了一份关于"公开书 baseline 训练污染天花板"的研究发现。下一步要跑的实验——P1 私域文本切换、prompt 单变量分离、provider 单变量分离——会再产出几十个数据点。

每一个数据点都是案例研究最终定稿那天的一行原始证据。
