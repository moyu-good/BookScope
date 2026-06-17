"""Reranker provider: SiliconFlow rerank API only（WP-reranker-api 设计稿）.

检索给 agent 的 top-k 准不准，是答案的地基。BM25 词面对不上、向量又把相关段
排到第 7、第 8 位的题，靠 rerank 把真正相关的那条提到前面（设计稿第 1 节）。

形状照搬 ``embedding_provider.py``：一个 ``RerankerProvider`` Protocol + 一个
SiliconFlow 实现 + 一个三段式工厂；只走 API，CPU 可跑，不碰 GPU 红线
（ADR-006 D-1 已把本地 cross-encoder 删干净）。

Provider 解析规则（``get_reranker_provider()``）：

- 总开关：``BOOKSCOPE_RERANK=on|off``，默认 ``off``。off 直接返回 ``None``，
  调用方跳过 rerank 走原排序——默认不拖慢没开的人。
- 显式：``BOOKSCOPE_RERANKER_PROVIDER=siliconflow`` 强制启用。
- 自动：``SILICONFLOW_API_KEY`` 存在即启用（跟 embedding 复用同一把 key）。
- 兜底：返回 ``None``，调用方退回 RRF/过滤后的原顺序（降级可见，不静默）。
"""

from __future__ import annotations

import logging
import os
from typing import Protocol, runtime_checkable

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class RerankerProvider(Protocol):
    """每个 rerank 后端都要满足的接口。"""

    @property
    def name(self) -> str:
        """可读的 provider 名，例 "SiliconFlow/BAAI/bge-reranker-v2-m3"。"""
        ...

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        """输入 query + 候选段文本列表，返回 ``[(原列表下标, 精排分), ...]``。

        - 返回的下标对回调用方传入的 ``documents`` 列表。
        - 分数是模型给的相关性，列表按精排分降序。
        - ``top_n`` 为 None 时返回全部候选的排序；给值时只返回前 ``top_n`` 条。
        """
        ...


# ---------------------------------------------------------------------------
# SiliconFlow rerank API
# ---------------------------------------------------------------------------

_SF_RERANK_URL = "https://api.siliconflow.cn/v1/rerank"
_SF_TIMEOUT = 30


class SiliconFlowRerankerProvider:
    """走 SiliconFlow rerank API 的精排实现（BYOK，跟 embedding 同域同鉴权）。"""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "BAAI/bge-reranker-v2-m3",
    ) -> None:
        self._api_key = api_key or os.environ.get("SILICONFLOW_API_KEY", "")
        self._model = model

    @property
    def name(self) -> str:
        return f"SiliconFlow/{self._model}"

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_n: int | None = None,
    ) -> list[tuple[int, float]]:
        if not documents:
            return []

        payload: dict[str, object] = {
            "model": self._model,
            "query": query,
            "documents": documents,
            # 只要下标和分数，原文本地有，不让 API 回传省流量。
            "return_documents": False,
        }
        if top_n is not None:
            payload["top_n"] = top_n

        resp = requests.post(
            _SF_RERANK_URL,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=_SF_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json()["results"]
        # 响应已按分降序，直接映射成 (index, relevance_score)。
        return [(item["index"], float(item["relevance_score"])) for item in results]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_reranker_provider() -> RerankerProvider | None:
    """按配置解析 rerank provider。

    解析顺序：

      0. 总开关 ``BOOKSCOPE_RERANK``（默认 ``off``）：不是 ``on`` 直接返回
         ``None``，连 key 都不看——默认关，不拖慢没开的人。
      1. ``BOOKSCOPE_RERANKER_PROVIDER=siliconflow``（显式）
      2. 自动检测：``SILICONFLOW_API_KEY`` 存在 → SiliconFlow
      3. ``None``（调用方退回原排序）
    """
    switch = os.environ.get("BOOKSCOPE_RERANK", "off").strip().lower()
    if switch != "on":
        logger.info("Reranker off (BOOKSCOPE_RERANK=%r) — skipping rerank", switch)
        return None

    explicit = os.environ.get("BOOKSCOPE_RERANKER_PROVIDER", "").strip().lower()

    if explicit == "siliconflow":
        logger.info("Reranker provider: SiliconFlow (explicit)")
        return SiliconFlowRerankerProvider()
    if explicit:
        logger.warning(
            "Unknown BOOKSCOPE_RERANKER_PROVIDER=%r; auto-detecting",
            explicit,
        )

    if os.environ.get("SILICONFLOW_API_KEY"):
        logger.info("Reranker provider: SiliconFlow (auto — API key found)")
        return SiliconFlowRerankerProvider()

    logger.info("BOOKSCOPE_RERANK=on but no SILICONFLOW_API_KEY — skipping rerank")
    return None
