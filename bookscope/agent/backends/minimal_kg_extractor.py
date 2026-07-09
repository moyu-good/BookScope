"""MinimalKGExtractor —— r1 代际的轻量 KG 提取占位（ADR-004 方案 B）。

### 为什么有这个模块

ADR-004 落地选型：r1 的 upload 链路需要产出一份最简的
``BookKnowledgeGraph``，只保证三个 r0 backend 真正会读的字段（角色的
``name`` / ``canonical_name`` / ``key_chapter_indices``）。v7 三阶段流水
线已归档到 ``legacy/v7/``，r1 主线不得依赖；所以本模块作为 **占位**
实现：一次单轮（或 map-reduce 多轮）LLM 调用，从 chunks 里抽出角色
清单。

### 与 adapter 层的关系（ADR-003）

本模块通过 :class:`LLMClient` Protocol 调用 LLM，**完全 provider-agnostic**。
DeepSeek / Anthropic / 未来的任何 provider 都能通过各自 adapter 注入，
不做硬绑。

### 质量边界

首版质量**弱于** v7 的三阶段流水线：

- 单轮 map-reduce，没有深挖阶段
- 无情感弧 / 角色成长分析（r1 三个 backend 不读这些字段）
- 依赖 LLM 能稳定返回 JSON；否则抛 ``LLMFormatError``

后续换 RAPTOR / GraphRAG / HippoRAG 等 SOTA 方法时，替换本类实现即可，
upload 路由与三个 backend 的签名都不变。
"""

from __future__ import annotations

import json
import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from bookscope.agent._internal.kg_book_cache import extract_book_kg_cached
from bookscope.agent._internal.kg_cache import extract_batch_cached
from bookscope.agent._internal.loop_shared import read_openai_finish_reason
from bookscope.agent.adapters import LLMClient
from bookscope.agent.errors import (
    ContentFiltered,
    ContextLimitExceeded,
    LLMFormatError,
    RateLimited,
)
from bookscope.agent.events import IngestCallback, IngestEvent
from bookscope.agent.utils.json_parsing import (
    autofix_control_chars_in_strings,
    autofix_stray_apostrophe_string_closer,
    autofix_unescaped_quotes_in_all_string_values,
)
from bookscope.models.schemas import (
    BookKnowledgeGraph,
    CharacterProfile,
    ChunkResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

PROMPT_PATH = Path(__file__).parent / "prompts" / "minimal_kg_extractor_v1.md"
"""system prompt 文件路径。初始化时一次性读进内存，避免每次 extract 都 I/O。"""

DEFAULT_MODEL: str = "deepseek-v4-flash"
"""默认 model；ADR-002 v2 的默认 provider 也走这个 model。"""

_EXTRACTION_TEMPERATURE: float = 0.0
"""KG 抽取温度。DeepSeek 官方调教表：代码/数据类任务用 0.0 求确定性。
抽实体是结构化任务，低温让同一批 chunk 的角色抽取结果更可复现。"""

DEFAULT_MAX_TOKENS: int = 8000
"""单次 LLM 调用的 ``max_tokens``。

原为 4000（按 non-reasoning model 估：角色 JSON 通常几百 token 就够）。但默认模型
``deepseek-v4-flash`` 是 reasoning model——它先在 ``reasoning_content`` 里想一大段，
这段**算进 ``max_tokens`` 预算**，预算不够时 ``content`` 直接返空、``finish_reason``
是 ``length``（exp008 / article-02 第七节实测过同款：output_tokens 上百、净 content 却
只剩几个字）。一个 60-chunk 的 batch（~9 万字符输入）让 flash 先想一轮再列几十个人名，
4000 会被 reasoning 挤空 content → ``_parse_characters_json`` 抛
``LLMFormatError("LLM text was empty")`` → 整批降级 jieba，而且是**每批**都白跑一次
LLM 才掉链子，整本 ingest 拖几分钟。提到 8000 给 reasoning + JSON 留够空间，跟全书
map-reduce 的其它功能（character_graph / chapter_spine / narrative_curve / timeline
等）一致的量级。"""

DEFAULT_MAX_CHUNKS_PER_BATCH: int = 60
"""单批 chunk 上限；超过则走 map-reduce。

选 60 的理由：按中文每 chunk ~1500 字符估算，60 个 chunk 约 9 万字符,
加上 prompt 与 JSON 输出预算仍能安全落在 32K context 内。"""

DEFAULT_MAX_WORKERS: int = 5
"""batch 并发上限默认值。

按 Sprint 5 loop tool 并行同样的 5 路上限，跟 provider rate-limit 留余地——
DeepSeek 默认 60 RPM，5 路并发不会单本书直接撞顶；调大需配合 provider 配额。
通过环境变量 ``BOOKSCOPE_KG_EXTRACT_MAX_WORKERS`` 覆盖。"""

ENV_MAX_WORKERS: str = "BOOKSCOPE_KG_EXTRACT_MAX_WORKERS"

DEFAULT_CONTENT_FILTER_RETRY_LIMIT: int = 3
"""KG batch 抽取被 provider 内容审查拒时的重试上限（第十六波加）。

照搬 reviewer / loop 第 31 轮 ContentFiltered 重试姿态——0-1 次重试同 input
（minimax 间歇 422 重试常能过），2 次起把中性化提示 append 进 system prompt 让
LLM 改用学术化措辞抽人名。超过上限才真降级 0 角色——把"被审查 = 不让分析"压到
最小。同 reviewer 默认 3 次。通过环境变量 ``BOOKSCOPE_KG_CONTENT_FILTER_RETRY_LIMIT``
覆盖。"""

ENV_CONTENT_FILTER_RETRY: str = "BOOKSCOPE_KG_CONTENT_FILTER_RETRY_LIMIT"

DEFAULT_JIEBA_NAME_MIN_LEN: int = 2
"""jieba NER 兜底过滤——人名最短字符数。低于此长度判为误标（单字"刘""王"等
姓氏被 nr 标的概率高，去掉减少噪音）。"""


_KG_NEUTRALIZE_HINT: str = (
    "\n\n[内部重试提示] 上一次抽取被 provider 内容审核拦截。"
    "请用中性、学术化措辞抽取人物姓名——避免在 entry 描述里复述敏感原文 / "
    "历史争议事件 / 政治判断。只关注：人名、canonical_name、出现章节号。"
    "JSON schema 严格保持原有形态不变。"
)
"""中性化重试提示——加在 system prompt 尾部不替换原 prompt。

照搬 reviewer `_KG_NEUTRALIZE_HINT` 设计，但针对 KG 抽取 task 改写：把 LLM 注意力
拉回"列人名"而非"评论敏感事件"。原 KG schema 字段约束保留，避免重试版本输出形态
跟主路径不一致。"""
"""环境变量名。设 1 即退化串行；设 N 限并发上限。"""


def _resolve_max_workers(explicit: int | None) -> int:
    """决定 batch 并发数。

    优先级：构造参数 > 环境变量 > 默认 5。任何 < 1 的值兜底成 1（串行）。
    """
    if explicit is not None:
        return max(1, explicit)
    raw = os.environ.get(ENV_MAX_WORKERS)
    if raw is None or not raw.strip():
        return DEFAULT_MAX_WORKERS
    try:
        parsed = int(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r, falling back to default %d",
            ENV_MAX_WORKERS,
            raw,
            DEFAULT_MAX_WORKERS,
        )
        return DEFAULT_MAX_WORKERS
    return max(1, parsed)


# ---------------------------------------------------------------------------
# MinimalKGExtractor
# ---------------------------------------------------------------------------


class MinimalKGExtractor:
    """最简 KG 提取器：从 chunks 抽出 ``CharacterProfile`` 列表。

    用法::

        extractor = MinimalKGExtractor(client=adapter, model="deepseek-v4-flash")
        kg = extractor.extract(chunks=chunks, book_title="明朝那些事儿")

    Args:
        client: :class:`LLMClient` Protocol 实现；由调用方按 provider
            选择 adapter 后注入。
        model: 模型名。默认 ``"deepseek-v4-flash"``；调用方可覆盖。
        max_tokens: 每次 LLM 调用的 ``max_tokens``。
        max_chunks_per_batch: 单批 chunk 上限；超过则走 map-reduce。
    """

    def __init__(
        self,
        client: LLMClient,
        *,
        model: str = DEFAULT_MODEL,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_chunks_per_batch: int = DEFAULT_MAX_CHUNKS_PER_BATCH,
        max_workers: int | None = None,
        on_ingest_event: IngestCallback | None = None,
        book_session_id: str = "",
    ) -> None:
        if max_chunks_per_batch < 1:
            raise ValueError(
                f"max_chunks_per_batch must be >= 1 (got {max_chunks_per_batch})"
            )
        self._client = client
        self._model = model
        self._max_tokens = max_tokens
        self._max_chunks_per_batch = max_chunks_per_batch
        self._max_workers = _resolve_max_workers(max_workers)
        self._system_prompt = self._load_system_prompt()
        # streaming progress hook（Sprint 6 第六步）。跟 AgentLoop callback
        # 同三原则：keyword-only / 异常包死 / trace 写完再 emit。callback
        # 为 None 时所有 emit 是 no-op，构造路径上零开销。
        self._on_ingest_event = on_ingest_event
        self._book_session_id = book_session_id

    # ------------------------------------------------------------------
    # 对外方法
    # ------------------------------------------------------------------

    def extract(
        self,
        chunks: list[ChunkResult],
        book_title: str,
        language: str = "zh",
    ) -> BookKnowledgeGraph:
        """从 chunks 抽取角色清单并打包成 ``BookKnowledgeGraph``。

        Args:
            chunks: r0 ingest 产出的 chunk 列表。空列表直接返回空 KG，
                不调 LLM。
            book_title: 书名；只用于填 KG 的 ``book_title`` 字段。
            language: 书的语种；同上。

        Returns:
            ``BookKnowledgeGraph``：只有 ``book_title`` / ``language`` /
            ``characters`` 有值；其它字段保持默认空。

        Raises:
            LLMFormatError: LLM 返回非 JSON、JSON 缺 ``characters`` 字段、
                或 characters 里的 entry 不符 schema。
            ProviderError 子类: LLM 调用网络 / 认证失败时从 adapter 透传
                （``ProviderUnavailable`` / ``RateLimited`` 等）。
        """
        if not chunks:
            # 空 chunks 走静默 fast path——emit 一对 started/done 给 FE 知道
            # ingest 已完成（虽然没有 batch），异常时也走 ingest_error。
            self._emit_ingest(
                event_type="ingest_started",
                total_batches=0,
            )
            self._emit_ingest(event_type="ingest_done")
            return BookKnowledgeGraph(
                book_title=book_title,
                language=language,
                characters=[],
            )

        # 切 batch 早算一次——用于 ``ingest_started`` 的 total_batches 字段。
        # 实际 ``_do_full_extract`` 内部会再切一次（值相同）。重复切几乎零
        # 成本（按 max_chunks_per_batch 等分一次），换 FE 上来就能算百分比。
        precomputed_batches = self._split_into_batches(chunks)
        total_batches = len(precomputed_batches)

        # ``ingest_started`` 在 book-level cache 判定之前 emit——book-level
        # 命中时 emit ``kg_cache_hit``（batch_index=None 表示整本命中）紧接
        # ``ingest_done``，FE 立刻知道整本秒进；miss 时继续 batch 抽取流。
        self._emit_ingest(
            event_type="ingest_started",
            total_batches=total_batches,
        )

        # book-level cache 命中观察——``extract_book_kg_cached`` 自己不暴露
        # 命中状态，这里用 sentinel：``extract_func`` 没被调到就是命中。
        extract_func_called = {"called": False}

        def _do_full_extract() -> BookKnowledgeGraph:
            """整本 KG 抽取链路：切 batch → 并发抽取 → merge → 打包。

            book-level cache miss 时被调；hit 时整段跳过。batch 级缓存
            仍在内部 ``_extract_from_batch`` 里生效，与本层叠加。
            """
            extract_func_called["called"] = True
            batches = precomputed_batches
            per_batch_entries = self._extract_all_batches(batches)
            # 保序：按 batch 在 batches 中的索引顺序铺平，跟串行行为一致。
            raw_entries: list[dict[str, Any]] = []
            for entries in per_batch_entries:
                raw_entries.extend(entries)

            profiles = self._merge_and_build_profiles(raw_entries)
            return BookKnowledgeGraph(
                book_title=book_title,
                language=language,
                characters=profiles,
            )

        # Sprint 6 第四步（2026-05-15）外加 book-level KG 缓存：
        # ``extract_book_kg_cached`` 按 ``(all_chunks_text_concat, system_prompt,
        # model)`` 整本 hash 命中——命中时直接返反序列化的 BookKnowledgeGraph，
        # 跳过整条 batch 切分 + 抽取 + merge 链路。与 batch 级 ``kg_cache.py``
        # 叠加：本层 miss 才走 batch 级缓存。详见 ``_internal/kg_book_cache.py``。
        try:
            kg = extract_book_kg_cached(
                all_chunks=chunks,
                system_prompt=self._system_prompt,
                model=self._model,
                extract_func=_do_full_extract,
            )
        except Exception as exc:
            # 抽取链路任一步抛异常——emit 一帧 ``ingest_error`` 再让异常透
            # 传上去（HTTP 层翻译 502 / 429 等不变）。FE SSE 流尾能拿到结构
            # 化错误，比裸 close stream 友好。
            self._emit_ingest(
                event_type="ingest_error",
                error_message=f"{type(exc).__name__}: {exc}",
            )
            raise

        if not extract_func_called["called"]:
            # book-level 缓存命中——extract_func 整段没被调到
            self._emit_ingest(
                event_type="kg_cache_hit",
                cached=True,
            )

        self._emit_ingest(event_type="ingest_done")
        return kg

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _load_system_prompt(self) -> str:
        """从磁盘加载 system prompt；构造时一次性读入。"""
        return PROMPT_PATH.read_text(encoding="utf-8")

    def _split_into_batches(
        self,
        chunks: list[ChunkResult],
    ) -> list[list[ChunkResult]]:
        """按 ``max_chunks_per_batch`` 切分 chunks。

        简单等分策略；未来若要按 token 预算做精细切分，可在这里改成
        累计字符数 / token 估算。
        """
        batches: list[list[ChunkResult]] = []
        for start in range(0, len(chunks), self._max_chunks_per_batch):
            batches.append(chunks[start : start + self._max_chunks_per_batch])
        return batches

    def _emit_ingest(
        self,
        *,
        event_type: str,
        total_batches: int | None = None,
        batch_index: int | None = None,
        cached: bool = False,
        error_message: str | None = None,
    ) -> None:
        """构造 IngestEvent 并调 callback；callback 抛异常时包死。

        三原则（同 AgentLoop streaming callback）：
        - keyword-only 默认 None（构造路径无 callback 时零开销）
        - 异常包死（用户 callback 抛任何错误都不能破坏 KG 抽取主链路）
        - trace 写入后再 emit（这里是计算后才 emit，保证 emit 时数据就位）
        """
        if self._on_ingest_event is None:
            return
        try:
            event = IngestEvent(
                event_type=event_type,  # type: ignore[arg-type]
                book_session_id=self._book_session_id,
                total_batches=total_batches,
                batch_index=batch_index,
                cached=cached,
                error_message=error_message,
            )
            self._on_ingest_event(event)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ingest event callback raised %s: %s; suppressed",
                type(exc).__name__,
                exc,
            )

    def _extract_all_batches(
        self,
        batches: list[list[ChunkResult]],
    ) -> list[list[dict[str, Any]]]:
        """对所有 batch 派发 LLM 抽取，返回 **跟 batches 同序** 的 entries 列表。

        调度策略：

        - ``len(batches) <= 1`` 或 ``max_workers == 1`` —— 直接串行，
          避免线程池开销。
        - 否则 ``ThreadPoolExecutor(max_workers=min(n, self._max_workers))``
          并发派发；用 ``dict[future, idx]`` + ``future.result()`` 写回
          位置 idx，**严格保序**（合并 ``key_chapter_indices`` 时顺序敏感
          ——同 canonical 的 name 取首次出现写法，乱序会导致 description
          指针随机化）。
        - 单 batch 抽取抛异常时**保留异常类型透传**：r0 ingest 期望
          ``LLMFormatError`` / ``ProviderError`` 子类一旦发生即终止整本，
          不做 partial 兜底（KG 残缺会让下游 r0 backend 读到错误的角色清单，
          静默丢 batch 比直接失败更危险）。
        """
        n = len(batches)
        if n == 0:
            return []
        if n == 1 or self._max_workers <= 1:
            return [
                self._extract_from_batch(batch, batch_index=idx)
                for idx, batch in enumerate(batches)
            ]

        results: list[list[dict[str, Any]] | None] = [None] * n
        max_workers = min(n, self._max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {
                executor.submit(self._extract_from_batch, batch, batch_index=idx): idx
                for idx, batch in enumerate(batches)
            }
            for future, idx in future_to_idx.items():
                # 异常直接 raise 出循环——透传到 extract() 调用方，让 r0
                # ingest 的错误处理决定如何兜底（当前是整本失败）。
                results[idx] = future.result()

        # mypy 兜底：上面循环已写满每个位置，None 不会留下。
        return [r if r is not None else [] for r in results]

    def _extract_from_batch(
        self,
        batch: list[ChunkResult],
        *,
        batch_index: int = 0,
    ) -> list[dict[str, Any]]:
        """对单个 batch 调一次 LLM，返回解析后的原始 character entries。

        entries 形如 ``[{"name", "canonical_name", "key_chapter_indices"}]``，
        即 LLM 原样返回；后续合并在 ``_merge_and_build_profiles`` 做。

        Sprint 6 第二阶段（2026-05-15）改走 ``adapter.extract_final_text``：
        Sprint 7 删 r1 后所有 adapter 默认吐 OpenAI plain dict
        （``{"choices": [...]}``），原模块级 ``_extract_text_from_response``
        按 Anthropic ``content`` block list 读，生产路径下 ``response.get("content")``
        恒为 ``None``，抛 ``LLMFormatError`` —— KG 提取静默 100% 失败。
        Backlog B-1 已把 ``extract_final_text`` 落到 ``LLMClient`` Protocol
        契约，直接走 adapter 让形态差异由各自 adapter 兜底，loop-shared
        与本 extractor 都不再 sniff 响应形态。

        Sprint 6 第二步（2026-05-15）外加 KG 缓存：``extract_batch_cached``
        按 ``(chunks, system_prompt, model)`` 做 SQLite 持久化命中——命中
        时直接返已解析的 entries list，跳过 LLM 调用 + ``extract_final_text``
        + ``_parse_characters_json`` 全套。详见 ``_internal/kg_cache.py``。
        """

        self._emit_ingest(
            event_type="kg_batch_started",
            batch_index=batch_index,
        )

        # batch-level 缓存命中观察——extract_batch_cached 不返命中状态，用
        # sentinel：_do_extract 若没被调到就是命中。命中时 emit kg_cache_hit
        # 在 batch_completed 之前（FE 看序列就知道"这帧零 LLM 调用"）。
        extract_called = {"called": False}

        def _do_extract() -> list[dict[str, Any]]:
            extract_called["called"] = True
            user_content = _format_batch_prompt(batch)
            retry_limit = int(
                os.environ.get(ENV_CONTENT_FILTER_RETRY, DEFAULT_CONTENT_FILTER_RETRY_LIMIT)
            )
            attempts = 0
            last_exc: Exception | None = None
            response: Any = None
            # 撞 finish_reason=length(reasoning 挤爆预算)时,加倍 max_tokens 重试一次再走 jieba。
            eff_max_tokens = self._max_tokens
            length_bumped = False

            # 通用 LLM 调用循环——ContentFiltered 走重试 + 中性化；其他 provider 错 /
            # 输出形态错都直接 break 走 jieba 兜底。作者第十六波明示——这条兜底
            # 不针对单本书 / 单 provider / 单错误模式，是 BookScope 对"任何
            # provider 任何错误下不让分析"的通用工程姿态。memory
            # `feedback_provider_agnostic_first.md` 兑现。
            while True:
                active_system = self._system_prompt
                if attempts >= 2:
                    active_system = self._system_prompt + _KG_NEUTRALIZE_HINT
                try:
                    response = self._client.messages_create(
                        model=self._model,
                        system=active_system,
                        tools=[],
                        messages=[{"role": "user", "content": user_content}],
                        max_tokens=eff_max_tokens,
                        # KG 抽实体是结构化确定性任务——DeepSeek 官方建议
                        # 代码/数据类用 temperature 0.0，少随机才稳。
                        temperature=_EXTRACTION_TEMPERATURE,
                    )
                except ContentFiltered as exc:
                    # 内容审查——重试 + 中性化救间歇 422 / minimax 政经题材常触发。
                    last_exc = exc
                    attempts += 1
                    if attempts > retry_limit:
                        break
                    continue
                except (RateLimited, ContextLimitExceeded) as exc:
                    # 暂态 quota / context 太大——重试烧时间无意义，走 jieba。
                    # ProviderUnavailable 不接住——auth / 网络挂是用户能修的配置
                    # 错，要冒给 API 层翻成 HTTP 错让用户看见（不该让"key 不对"翻面
                    # 成"空 KG"静默吞 / 用户以为书有问题）。
                    last_exc = exc
                    break
                # LLM 调用成功——下面解析输出。失败也走 jieba 兜底（autofix 链救
                # 不回的破 JSON / 形态错都不该让整 batch 0 角色）。
                try:
                    text = self._client.extract_final_text(response)
                    return _parse_characters_json(text)
                except LLMFormatError as exc:
                    # finish_reason=length = reasoning 挤爆 max_tokens、content 空(非真格式错)。
                    # 加倍预算重试一次再走 jieba:外国 / 人物密的书 8000 常不够,LLM 抽的名册比
                    # jieba 分音译名准(exp008 同款,见 reference_reasoning_model_token_budget)。
                    last_exc = exc
                    fr = read_openai_finish_reason(response) if response is not None else None
                    if fr == "length" and not length_bumped:
                        eff_max_tokens = min(eff_max_tokens * 2, 24000)
                        length_bumped = True
                        logger.info(
                            "kg_batch %d 撞 length,max_tokens %d→%d 重试一次",
                            batch_index,
                            self._max_tokens,
                            eff_max_tokens,
                        )
                        continue
                    break

            # 任何兜底分支统一走 jieba ——本地 NER 跟 provider 完全解耦，always
            # 出结果（无人名时 entries 为空，再真降级 0 角色）。
            jieba_entries = _jieba_extract_names(batch)
            exc_type = type(last_exc).__name__ if last_exc else "unknown"
            # finish_reason=length 的空 content 是 reasoning 挤爆 max_tokens 的信号
            # （不是模型真没抽到），跟破 JSON 的 format error 是两回事。把它单独点出来，
            # 别让"预算不够"伪装成"输出格式错"——排查时先看这个再动别的（article-02 清单）。
            fr = read_openai_finish_reason(response) if response is not None else None
            cause = (
                "（finish_reason=length，疑似 reasoning 挤爆 max_tokens）"
                if fr == "length"
                else ""
            )
            if jieba_entries:
                logger.warning(
                    "kg_batch %d LLM 兜底失败（%s%s），jieba 救回 %d 人名: %s",
                    batch_index,
                    exc_type,
                    cause,
                    len(jieba_entries),
                    last_exc,
                )
                return jieba_entries
            logger.warning(
                "kg_batch %d LLM 兜底失败（%s%s）/ jieba 也无人名 / 降级 0 角色: %s",
                batch_index,
                exc_type,
                cause,
                last_exc,
            )
            return []

        entries = extract_batch_cached(
            chunks=batch,
            system_prompt=self._system_prompt,
            model=self._model,
            extract_func=_do_extract,
        )
        if not extract_called["called"]:
            self._emit_ingest(
                event_type="kg_cache_hit",
                batch_index=batch_index,
                cached=True,
            )
        self._emit_ingest(
            event_type="kg_batch_completed",
            batch_index=batch_index,
        )
        return entries

    def _merge_and_build_profiles(
        self,
        raw_entries: list[dict[str, Any]],
    ) -> list[CharacterProfile]:
        """按 ``canonical_name`` 合并多个 batch 的原始 entries。

        合并规则：
        - 同 ``canonical_name`` 的 entry 合并成一条 ``CharacterProfile``。
        - ``name`` 取首次出现的写法（LLM 通常在每个 batch 给出一致写法）。
        - ``key_chapter_indices`` 做 **集合并集 + 升序排序**。
        - 其他 ``CharacterProfile`` 字段（aliases / description / ...）
          留默认值。本占位 extractor 不产出这些字段——它们当前在 r1 的
          三个 backend 里也都不读（见 ADR-004 的 "r1 实际消费" 分析）。
        """
        # canonical_name → 聚合状态
        merged: dict[str, dict[str, Any]] = {}
        for entry in raw_entries:
            canonical = entry.get("canonical_name") or entry.get("name") or ""
            canonical = canonical.strip()
            if not canonical:
                # 没名字的 entry 丢弃；LLM 偶尔会输出空串
                continue
            name = entry.get("name") or canonical
            name = str(name).strip() or canonical
            chapters_raw = entry.get("key_chapter_indices") or []

            bucket = merged.setdefault(
                canonical,
                {
                    "name": name,
                    "canonical": canonical,
                    "chapters": set(),
                },
            )
            for ch in chapters_raw:
                parsed = _coerce_int(ch)
                if parsed is not None and parsed >= 0:
                    bucket["chapters"].add(parsed)

        profiles: list[CharacterProfile] = []
        for canonical, bucket in merged.items():
            chapters_sorted = sorted(bucket["chapters"])
            profiles.append(
                CharacterProfile(
                    name=bucket["name"],
                    aliases=[],
                    key_chapter_indices=chapters_sorted,
                )
            )
            # 记录 canonical 差异到 description（r1 backend 当前不读，
            # 但保留信息，便于人工审阅 kg.json 时追溯）
            if canonical != bucket["name"]:
                profiles[-1].description = f"canonical: {canonical}"
        return profiles


# ---------------------------------------------------------------------------
# module-level helpers（独立函数便于单测）
# ---------------------------------------------------------------------------


def _format_batch_prompt(batch: list[ChunkResult]) -> str:
    """把一个 batch 的 chunks 拼成 user message 文本。

    每个 chunk 以 ``[chunk_index=N]`` header 开头，之后跟 chunk 原文。
    这样 LLM 能清晰识别来源，避免把不同 chunk 的文字混起来。
    """
    parts: list[str] = []
    for chunk in batch:
        parts.append(f"[chunk_index={chunk.index}]\n{chunk.text}")
    header = (
        "以下是书籍的若干文本片段。请按 system 指令返回严格的 JSON。\n\n"
    )
    return header + "\n\n".join(parts)


def _extract_text_from_response(response: Any) -> str:
    """从 Anthropic 风格 response 里提取所有 ``text`` block 的拼接文本。

    **历史 helper · 不在 KG 抽取主路径上**。Sprint 7 删 r1 后所有 adapter
    默认吐 OpenAI plain dict，主路径已切到 ``adapter.extract_final_text``
    （Backlog B-1 落地）。本 helper 留下来给：

    - 单测里需要直接读 Anthropic 形态 response 的少数场景
    - 测试 fake client 的 ``extract_final_text`` 默认实现（按 Anthropic 形态读）

    兼容两种形态：
    - Anthropic 风格 dict: ``{"content": [{"type": "text", "text": "..."}]}``
    - Anthropic SDK Message 对象（具备同名属性访问）

    Raises:
        LLMFormatError: response 结构异常、无任何 text 内容。
    """
    if response is None:
        raise LLMFormatError("LLM response is None")

    content = response.get("content") if isinstance(response, dict) else getattr(
        response, "content", None
    )
    if content is None:
        raise LLMFormatError("LLM response has no content field")
    if not isinstance(content, list):
        # 某些 adapter 可能直接把 str 放到 content——宽容处理
        content = [content]

    parts: list[str] = []
    for block in content:
        btype = block.get("type") if isinstance(block, dict) else getattr(
            block, "type", None
        )
        if btype == "text":
            text = block.get("text") if isinstance(block, dict) else getattr(
                block, "text", None
            )
            if isinstance(text, str):
                parts.append(text)
        elif isinstance(block, str):
            parts.append(block)

    joined = "\n".join(p for p in parts if p).strip()
    if not joined:
        raise LLMFormatError("LLM response contains no text content")
    return joined


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)


def _jieba_extract_names(batch: list[ChunkResult]) -> list[dict[str, Any]]:
    """jieba 本地 NER 兜底——把 batch 内 chunk 拼起来跑词性标注抽 ``nr`` 人名。

    LLM 重试上限耗尽时调（第三层兜底）。设计要点——

    - 跟 provider 完全解耦：不受内容审查 / 网络 / rate-limit 影响，always 出结果
    - 精度低于 LLM：jieba dict 漏当代人名（"郑永年"等不在 dict 里的不会被识别 nr）/
      偶尔误标普通词。作为最后兜底保"有总比 0 好"，不是替代 LLM 抽取
    - 输出 schema 跟 LLM 路径完全一致：``name`` / ``canonical_name`` / 空
      ``key_chapter_indices``（jieba 不识别章节归属，留空让消费方知道这是兜底数据）
    - 第十六波加 · chapter-09 第七节"冷门路径"模式 + memory
      ``feedback_provider_agnostic_first.md`` "BookScope 兜底而非让用户挑 AI" 兑现

    Args:
        batch: 单个 batch 的 chunks 列表。

    Returns:
        去重后的人名 entry 列表（短名 < ``DEFAULT_JIEBA_NAME_MIN_LEN`` 字符过滤掉）。
        无人名时返回空 list。
    """
    import jieba.posseg as pseg  # lazy import 避免冷启动跑 jieba

    all_text = "\n".join(c.text for c in batch)
    seen: set[str] = set()
    entries: list[dict[str, Any]] = []
    for word in pseg.cut(all_text):
        if word.flag != "nr":
            continue
        name = word.word.strip()
        if len(name) < DEFAULT_JIEBA_NAME_MIN_LEN or name in seen:
            continue
        seen.add(name)
        entries.append({
            "name": name,
            "canonical_name": name,
            "key_chapter_indices": [],
        })
    return entries


def _parse_with_autofix(json_slice: str, *, raw_head: str) -> Any:
    """三层 autofix 兜底 parser——KG path 跟 loop / reviewer 共用 autofix utils。

    Args:
        json_slice: 已经定位过的疑似 JSON 字符串（``_extract_first_json_object``
            的输出，或 ``_strip_code_fence`` 之后的 candidate）。
        raw_head: 原始 LLM 回复前 500 字——任何 autofix 都救不回时塞进 error
            消息便于 dogfood 诊断。

    Returns:
        ``json.loads`` 解析结果。

    Raises:
        LLMFormatError: 三层 autofix 全部不命中或修完仍 parse 失败。

    autofix 顺序——
    1. ``autofix_stray_apostrophe_string_closer`` 修裸单引号当 string 收束
       （minimax M2.7 出过几次）
    2. ``autofix_unescaped_quotes_in_all_string_values`` 修字符串值内裸双引号
       （第 24 轮 astron 触发）
    3. ``autofix_control_chars_in_strings`` 修控制字符（第 26 轮 minimax 触发）
    """
    try:
        return json.loads(json_slice)
    except json.JSONDecodeError:
        pass

    for autofix in (
        autofix_stray_apostrophe_string_closer,
        autofix_unescaped_quotes_in_all_string_values,
        autofix_control_chars_in_strings,
    ):
        fixed = autofix(json_slice)
        if fixed is None:
            continue
        try:
            return json.loads(fixed)
        except json.JSONDecodeError:
            continue

    raise LLMFormatError(
        "failed to parse JSON and 3-layer autofix did not apply; "
        f"raw text head=<<{raw_head}>>"
    ) from None


def _parse_characters_json(text: str) -> list[dict[str, Any]]:
    """把 LLM 回复的 JSON 字符串解析成 character entries 列表。

    流程：
    1. 先剥 ```json ... ``` 围栏（若有）。
    2. ``json.loads``；失败 → 尝试定位第一个顶层 ``{}`` 再 parse。
    3. 再失败 → 三层 autofix 链（裸单引号收束 / 控制字符 / 裸双引号）
       与 loop / reviewer 路径共用 ``utils.json_parsing`` 的 autofix。
       Sprint 6 第十六波 dogfood mingchao probe 揭出 KG path 零 autofix
       是 chapter-09 第七节"冷门路径"再复现——KG parser 跟 loop / reviewer
       parser 是兄弟 JSON 路径，前者长期没接 autofix 层是 prep 没覆盖到的盲点。
    4. 断言 ``characters`` 字段存在且为 list。
    5. 断言每条 entry 是 dict 且含 ``name`` / ``canonical_name``；
       ``key_chapter_indices`` 允许缺失（统一兜底为空 list）。

    Raises:
        LLMFormatError: 任何 parse / schema 失败。失败时把 raw text 前 500 字
            塞进消息便于 dogfood 诊断。
    """
    stripped = text.strip()
    if not stripped:
        raise LLMFormatError("LLM text was empty")

    candidate = _strip_code_fence(stripped)
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        sliced = _extract_first_json_object(candidate)
        if sliced is None:
            raise LLMFormatError(
                "LLM response is not valid JSON and contains no JSON object; "
                f"raw text head=<<{stripped[:500]}>>"
            ) from None
        obj = _parse_with_autofix(sliced, raw_head=stripped[:500])

    if not isinstance(obj, dict):
        raise LLMFormatError("LLM top-level JSON is not an object")
    if "characters" not in obj:
        raise LLMFormatError("LLM JSON missing 'characters' field")
    characters = obj["characters"]
    if not isinstance(characters, list):
        raise LLMFormatError("'characters' field must be a list")

    normalized: list[dict[str, Any]] = []
    for idx, entry in enumerate(characters):
        if not isinstance(entry, dict):
            raise LLMFormatError(f"characters[{idx}] is not an object")
        if "name" not in entry and "canonical_name" not in entry:
            raise LLMFormatError(
                f"characters[{idx}] missing both 'name' and 'canonical_name'"
            )
        name_val = entry.get("name")
        canonical_val = entry.get("canonical_name")
        if name_val is not None and not isinstance(name_val, str):
            raise LLMFormatError(f"characters[{idx}].name must be a string")
        if canonical_val is not None and not isinstance(canonical_val, str):
            raise LLMFormatError(
                f"characters[{idx}].canonical_name must be a string"
            )
        chapters_val = entry.get("key_chapter_indices", [])
        if chapters_val is None:
            chapters_val = []
        if not isinstance(chapters_val, list):
            raise LLMFormatError(
                f"characters[{idx}].key_chapter_indices must be a list"
            )
        normalized.append(
            {
                "name": name_val or canonical_val or "",
                "canonical_name": canonical_val or name_val or "",
                "key_chapter_indices": chapters_val,
            }
        )
    return normalized


def _strip_code_fence(text: str) -> str:
    """若 LLM 把 JSON 包在 ```json ... ``` 里，剥掉围栏。"""
    m = _CODE_FENCE_RE.match(text.strip())
    if m:
        return m.group(1).strip()
    return text


def _extract_first_json_object(text: str) -> str | None:
    """在自由文本里定位第一个顶层 JSON object（按花括号平衡）。

    与 :mod:`bookscope.agent.loop` 里的同名 helper 同算法；此处复制一份
    避免跨模块 import 循环风险。
    """
    depth = 0
    start_idx: int | None = None
    in_string = False
    escape = False
    for idx, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start_idx = idx
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx is not None:
                    return text[start_idx : idx + 1]
    return None


def _coerce_int(value: Any) -> int | None:
    """把 LLM 给的章节号 coerce 成 int。

    允许输入 int / 字符串形式的数字；其它形态（None / 浮点 / 非数字串）
    返回 ``None``，调用方丢弃。
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit():
            return int(s)
        try:
            f = float(s)
        except ValueError:
            return None
        if f.is_integer():
            return int(f)
        return None
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


__all__ = ["MinimalKGExtractor"]
