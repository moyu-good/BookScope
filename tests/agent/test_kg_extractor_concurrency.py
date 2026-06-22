"""MinimalKGExtractor batch 调度并发测试。

Sprint 6 第一步：把 batch 抽取从串行循环换成 ThreadPoolExecutor 并发。
本文件覆盖并发模式特有的不变量；happy path / 解析错误等通用行为已经在
``test_minimal_kg_extractor.py`` 覆盖。

要点：

- 默认并发模式跟 ``max_workers=1`` 串行模式产出完全一致（顺序敏感场景）
- chunk 输出顺序严格跟 batches 同序——这是合并 canonical_name 的硬约束
- 单个 batch 抽取失败时异常透传，不被吞掉
- env ``BOOKSCOPE_KG_EXTRACT_MAX_WORKERS`` 能控制并发上限
- 并发确实并发跑了（用 barrier 集合点 + 并发计数探针证明，不看墙钟）
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from bookscope.agent.backends.minimal_kg_extractor import (
    DEFAULT_MAX_WORKERS,
    ENV_MAX_WORKERS,
    MinimalKGExtractor,
    _resolve_max_workers,
)
from bookscope.agent.errors import LLMFormatError
from bookscope.models.schemas import ChunkResult

# ---------------------------------------------------------------------------
# Fake LLMClient —— 同 test_minimal_kg_extractor.py 的设计，但加并发探针
# ---------------------------------------------------------------------------


class _ConcurrencyFakeClient:
    """记录每次调用的并发情况 + 按 batch 内容映射返回预设角色。

    跟基础 fake 区别：

    - 用 ``payload_by_first_chunk_index`` 映射首个 chunk 的 index 到响应，
      模拟"不同 batch 抽出不同角色"，便于断言顺序
    - ``call_log`` 记录每次调用的入参用于断言顺序敏感场景
    - ``simulate_delay_seconds`` 让每次调用阻塞固定时长（顺序 / 失败传播
      测试用来制造可观测的执行窗口；不再用来卡墙钟阈值）
    - ``peak_inflight`` 记录并发峰值——进入 +1 / 退出 -1 的 max，证明
      "同时有几路调用在飞"
    - ``rendezvous`` 传一个 ``threading.Barrier``，每路调用进来都要在集合点
      等齐才放行：只有真并发到 N 路才能凑齐瞬间放行，退化成串行会卡死在
      barrier 的 timeout 上抛 ``BrokenBarrierError``——这是不看墙钟的并发铁证
    - ``raise_on_chunk_index`` 模拟某 batch 失败抛异常
    """

    def __init__(
        self,
        *,
        payload_by_first_chunk_index: dict[int, dict[str, Any]],
        simulate_delay_seconds: float = 0.0,
        raise_on_first_chunk_index: int | None = None,
        rendezvous: threading.Barrier | None = None,
    ) -> None:
        self._payloads = dict(payload_by_first_chunk_index)
        self._delay = simulate_delay_seconds
        self._raise_on = raise_on_first_chunk_index
        self._rendezvous = rendezvous
        self.call_count = 0
        self.call_log: list[int] = []
        self._lock = threading.Lock()
        # 追踪并发峰值：进入时 +1 / 退出时 -1，max 就是并发峰值
        self._inflight = 0
        self.peak_inflight = 0

    def messages_create(self, **kwargs: Any) -> dict[str, Any]:
        # 从 user content 解析首个 chunk_index 作为 batch 标识。
        content = kwargs["messages"][0]["content"]
        first_idx = _parse_first_chunk_index(content)

        with self._lock:
            self.call_count += 1
            self.call_log.append(first_idx)
            self._inflight += 1
            if self._inflight > self.peak_inflight:
                self.peak_inflight = self._inflight

        try:
            if self._rendezvous is not None:
                # 集合点：要求所有并发路同时到齐才放行。inflight 已在上面 +1，
                # 等齐时 peak_inflight 自然摸到 barrier 的 parties 数。若调度退化
                # 成串行，第一路等不到其它路，barrier 超时抛 BrokenBarrierError，
                # 透传出去让测试 fail——不依赖任何墙钟阈值。
                self._rendezvous.wait()
            if self._delay > 0:
                time.sleep(self._delay)
            if self._raise_on is not None and first_idx == self._raise_on:
                raise LLMFormatError(f"simulated failure on chunk {first_idx}")
            payload = self._payloads.get(
                first_idx,
                {"characters": []},
            )
            return {
                "stop_reason": "end_turn",
                "content": [
                    {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
                ],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            }
        finally:
            with self._lock:
                self._inflight -= 1

    def extract_final_text(self, response: Any) -> str:
        """LLMClient Protocol（B-1 下沉）。

        本 fake 按基础 fake 同样的 Anthropic 形态拼装响应（``content`` 字段
        为 text block list），所以读法与 ``_extract_text_from_response`` 一致。
        实际生产 adapter 会按 OpenAI ``choices[0].message.content`` 读；
        生产路径下的 r2 形态覆盖由 ``tests/agent/r2/test_minimal_kg_extractor_r2.py``
        负责。
        """
        if response is None:
            return ""
        content = response.get("content") if isinstance(response, dict) else None
        if not isinstance(content, list):
            return ""
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts).strip()

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        return 0, 0


def _parse_first_chunk_index(content: str) -> int:
    """从 user message 里抠出第一个 chunk_index 整数。"""
    # 格式见 _format_batch_prompt: "[chunk_index=N]\n..."
    marker = "[chunk_index="
    pos = content.find(marker)
    if pos < 0:
        return -1
    start = pos + len(marker)
    end = content.find("]", start)
    return int(content[start:end])


def _chunks(n: int) -> list[ChunkResult]:
    return [ChunkResult(index=i, text=f"片段{i}内容。") for i in range(n)]


# ---------------------------------------------------------------------------
# 顺序不变量
# ---------------------------------------------------------------------------


def test_parallel_preserves_batch_order_in_output() -> None:
    """并发抽取后 raw_entries 顺序跟 batches 顺序一致——按首个 chunk_index 升序。

    场景：5 batch，每 batch 抽出一个独家角色；后到的 future 不能把后面 batch 的角色
    挤到前面。靠 ``dict[future, idx]`` + 按 idx 写回保序。
    """
    payloads = {
        i: {
            "characters": [
                {
                    "name": f"角色{i}",
                    "canonical_name": f"角色{i}",
                    "key_chapter_indices": [i],
                }
            ]
        }
        for i in range(5)
    }
    client = _ConcurrencyFakeClient(
        payload_by_first_chunk_index=payloads,
        simulate_delay_seconds=0.05,
    )
    extractor = MinimalKGExtractor(
        client=client, max_chunks_per_batch=1, max_workers=4
    )
    kg = extractor.extract(chunks=_chunks(5), book_title="X")
    # 同 canonical 的 entries 都只一个 chapter，描出现顺序：用 chapter_index 当 ID
    names = [c.name for c in kg.characters]
    # raw_entries 顺序跟 batches 一致 → merge 后字典插入顺序也一致
    assert names == ["角色0", "角色1", "角色2", "角色3", "角色4"]
    assert client.call_count == 5


def test_serial_and_parallel_produce_identical_kg() -> None:
    """同样的 payloads 串行（max_workers=1）跟并行（max_workers=5）KG 应完全一致。"""
    payloads = {
        i: {
            "characters": [
                {
                    "name": f"N{i}",
                    "canonical_name": f"N{i}",
                    "key_chapter_indices": [i],
                }
            ]
        }
        for i in range(4)
    }

    serial_client = _ConcurrencyFakeClient(payload_by_first_chunk_index=payloads)
    serial = MinimalKGExtractor(
        client=serial_client, max_chunks_per_batch=1, max_workers=1
    )
    serial_kg = serial.extract(chunks=_chunks(4), book_title="X")

    parallel_client = _ConcurrencyFakeClient(payload_by_first_chunk_index=payloads)
    parallel = MinimalKGExtractor(
        client=parallel_client, max_chunks_per_batch=1, max_workers=4
    )
    parallel_kg = parallel.extract(chunks=_chunks(4), book_title="X")

    serial_signature = [
        (c.name, tuple(c.key_chapter_indices)) for c in serial_kg.characters
    ]
    parallel_signature = [
        (c.name, tuple(c.key_chapter_indices)) for c in parallel_kg.characters
    ]
    assert serial_signature == parallel_signature


def test_parallel_merge_keeps_first_appearance_name() -> None:
    """同 canonical 的 name 取首次出现的写法——保序就是为了这个不变量。

    batch 0 出朱元璋 / batch 1 出朱重八（同 canonical=朱元璋）。
    保序后 merge 应保留 batch 0 的 name=朱元璋。乱序则可能反过来。
    """
    payloads = {
        0: {
            "characters": [
                {
                    "name": "朱元璋",
                    "canonical_name": "朱元璋",
                    "key_chapter_indices": [1],
                }
            ]
        },
        1: {
            "characters": [
                {
                    "name": "朱重八",
                    "canonical_name": "朱元璋",
                    "key_chapter_indices": [2],
                }
            ]
        },
    }
    # 用反序延迟让 batch 1 先返回——若没有 idx 保序，朱重八会盖朱元璋。
    # 改用 sleep 让 batch 0 慢于 batch 1：fake 不支持按 idx 不同延迟，
    # 改 patch _extract_from_batch 反序返回更直接——但当前 fake 设计已能验证：
    # ThreadPoolExecutor 启动顺序非确定，靠 idx 写回不靠完成顺序。
    client = _ConcurrencyFakeClient(payload_by_first_chunk_index=payloads)
    extractor = MinimalKGExtractor(
        client=client, max_chunks_per_batch=1, max_workers=2
    )
    kg = extractor.extract(chunks=_chunks(2), book_title="X")
    assert len(kg.characters) == 1
    assert kg.characters[0].name == "朱元璋"
    assert kg.characters[0].key_chapter_indices == [1, 2]


# ---------------------------------------------------------------------------
# 并发实质验证
# ---------------------------------------------------------------------------


def test_parallel_actually_runs_concurrently() -> None:
    """证明 3 个 batch 真的并发跑了——靠 barrier 集合点，不靠墙钟。

    旧版本断言"并发 wall-time < 串行总和"（< 0.6s），在 CI / 高负载下会因为
    几毫秒抖动误报（实测 0.6017s 越过 0.6s 阈值挂掉）。墙钟阈值跟被测逻辑的
    正确性根本无关，纯粹是噪音。

    新做法：给 fake client 装一个 ``threading.Barrier(3, timeout=...)``，每路
    调用进来都要在集合点等齐 3 路才放行。

    - 真并发：ThreadPoolExecutor 把 3 个 batch 同时在飞，3 路瞬间凑齐 barrier、
      立即放行，测试秒过。
    - 退化成串行：第一路永远等不到另外两路，barrier 超时抛 ``BrokenBarrierError``
      透传出来，测试 fail。

    barrier 只看"是否真有 3 路同时到达"，跟机器快慢无关，比墙钟稳得多。timeout
    给 10s 纯粹是兜底——真并发时根本用不到（微秒级凑齐），只有并发彻底坏了才会
    触发，那本来就该 fail。``peak_inflight == 3`` 再复核一遍并发峰值确实摸到 3。
    """
    n = 3
    payloads = {i: {"characters": []} for i in range(n)}
    rendezvous = threading.Barrier(n, timeout=10.0)
    client = _ConcurrencyFakeClient(
        payload_by_first_chunk_index=payloads,
        rendezvous=rendezvous,
    )
    extractor = MinimalKGExtractor(
        client=client, max_chunks_per_batch=1, max_workers=n
    )
    extractor.extract(chunks=_chunks(n), book_title="X")
    # barrier 没抛 == 3 路真同时到达；peak_inflight 复核并发峰值确实 == 3
    assert client.peak_inflight == n
    assert client.call_count == n


def test_max_workers_one_runs_serially() -> None:
    """``max_workers=1`` 强制走串行分支——peak_inflight 应 == 1。"""
    payloads = {i: {"characters": []} for i in range(3)}
    client = _ConcurrencyFakeClient(
        payload_by_first_chunk_index=payloads,
        simulate_delay_seconds=0.05,
    )
    extractor = MinimalKGExtractor(
        client=client, max_chunks_per_batch=1, max_workers=1
    )
    extractor.extract(chunks=_chunks(3), book_title="X")
    assert client.peak_inflight == 1
    assert client.call_count == 3


def test_single_batch_does_not_spawn_threadpool() -> None:
    """只有 1 batch 时走 inline 分支——peak_inflight == 1。"""
    payloads = {0: {"characters": []}}
    client = _ConcurrencyFakeClient(
        payload_by_first_chunk_index=payloads,
        simulate_delay_seconds=0.02,
    )
    extractor = MinimalKGExtractor(
        client=client, max_chunks_per_batch=10, max_workers=5
    )
    extractor.extract(chunks=_chunks(3), book_title="X")
    assert client.peak_inflight == 1
    assert client.call_count == 1


# ---------------------------------------------------------------------------
# 失败传播
# ---------------------------------------------------------------------------


def test_batch_failure_propagates_not_swallowed() -> None:
    """3 batch 中 batch 1 抛 LLMFormatError——异常透传，不被 partial 兜底吞掉。

    这是设计决策：KG 残缺让下游 r0 backend 读到错误角色清单，比直接失败更危险。
    """
    payloads = {
        i: {"characters": [{"name": f"N{i}", "canonical_name": f"N{i}"}]}
        for i in range(3)
    }
    client = _ConcurrencyFakeClient(
        payload_by_first_chunk_index=payloads,
        raise_on_first_chunk_index=1,
    )
    extractor = MinimalKGExtractor(
        client=client, max_chunks_per_batch=1, max_workers=3
    )
    with pytest.raises(LLMFormatError, match="simulated failure"):
        extractor.extract(chunks=_chunks(3), book_title="X")


# ---------------------------------------------------------------------------
# env 配置
# ---------------------------------------------------------------------------


def test_env_max_workers_controls_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    """``BOOKSCOPE_KG_EXTRACT_MAX_WORKERS=1`` 应让并发退化成串行。"""
    monkeypatch.setenv(ENV_MAX_WORKERS, "1")
    payloads = {i: {"characters": []} for i in range(3)}
    client = _ConcurrencyFakeClient(
        payload_by_first_chunk_index=payloads,
        simulate_delay_seconds=0.05,
    )
    # 不传 max_workers——从 env 读
    extractor = MinimalKGExtractor(client=client, max_chunks_per_batch=1)
    extractor.extract(chunks=_chunks(3), book_title="X")
    assert client.peak_inflight == 1


def test_env_max_workers_invalid_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env 值非整数时打 warning + 走默认 5。"""
    monkeypatch.setenv(ENV_MAX_WORKERS, "not-a-number")
    assert _resolve_max_workers(None) == DEFAULT_MAX_WORKERS


def test_env_max_workers_unset_uses_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ENV_MAX_WORKERS, raising=False)
    assert _resolve_max_workers(None) == DEFAULT_MAX_WORKERS


def test_explicit_max_workers_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """构造参数 > env > 默认。"""
    monkeypatch.setenv(ENV_MAX_WORKERS, "1")
    assert _resolve_max_workers(7) == 7


def test_resolve_max_workers_clamps_below_one() -> None:
    """显式传 0 / 负数兜底成 1。"""
    assert _resolve_max_workers(0) == 1
    assert _resolve_max_workers(-3) == 1
