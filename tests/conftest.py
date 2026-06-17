"""全局 pytest 配置 —— Sprint 8 W2 加。

作用：autouse fixture 把模块级 SQLite 缓存的默认 DB 路径重定向到每个测试
独立的 tmp 文件，避免跨测试污染。当前覆盖：

- L2 LLM 调用缓存（``bookscope.agent._internal.llm_cache``，Sprint 8 W2）
- KG 抽取缓存（``bookscope.agent._internal.kg_cache``，Sprint 6 第二步）
- Book-level KG 缓存（``bookscope.agent._internal.kg_book_cache``，Sprint 6
  第四步）

为什么需要：

- 这两层都是模块级 SQLite 文件单例，默认路径分别落在 ``<repo>/.bookscope_
  cache/llm_cache.db`` 与 ``<repo>/.bookscope_cache/kg_cache.db``。多个
  测试在同 process 内跑时共享同一文件——测试 A 写入的 mock response /
  entries 会让测试 B 命中缓存返同一答案，但测试 B 的 fake client 期待
  自己的 response 序列，两边对不上就 fail
- 老测试 / 集成测试都可能触发缓存路径——KG 缓存对所有 ``MinimalKGExtractor``
  调用都生效，比 L2 触发面更大
- 干净方案：autouse fixture 给每个测试独立 DB 文件——既不动既有测试代码，
  又保证缓存代码路径在测试中真实执行（覆盖率不漏）

测试想验证缓存自身行为时（``tests/agent/_internal/test_llm_cache.py`` /
``test_kg_cache.py``），该测试模块自己用 ``monkeypatch.setenv`` 设独立路径
+ ``reset_*_singleton_for_test()`` 重建单例——本 fixture 不会冲突，因为
monkeypatch 是 per-test scope，本 fixture 也是 per-test scope。
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_llm_cache_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """每个测试用 tmp_path 独立 L2 缓存 DB 文件 + 强制重建 singleton。

    顺序约定：先 setenv 再 reset singleton——下次 ``_get_cache()`` 会按新
    env 重建指向 tmp 路径的 SQLiteCache。
    """
    monkeypatch.setenv(
        "BOOKSCOPE_LLM_CACHE_DB_PATH", str(tmp_path / "llm_cache.db")
    )
    # 延迟 import 避免 conftest import 期就触发 cache module 加载
    from bookscope.agent._internal.llm_cache import (
        reset_llm_cache_singleton_for_test,
    )

    reset_llm_cache_singleton_for_test()
    yield
    reset_llm_cache_singleton_for_test()


@pytest.fixture(autouse=True)
def _isolate_kg_cache_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """每个测试用 tmp_path 独立 KG 缓存 DB 文件 + 强制重建 singleton。

    同 L2 缓存的隔离套路——KG 缓存对所有 ``MinimalKGExtractor`` 调用都生
    效，跨测试共享同一磁盘 DB 会让 fake client 的 ``call_count`` 期望全
    部失真。
    """
    monkeypatch.setenv(
        "BOOKSCOPE_KG_CACHE_DB_PATH", str(tmp_path / "kg_cache.db")
    )
    from bookscope.agent._internal.kg_cache import (
        reset_kg_cache_singleton_for_test,
    )

    reset_kg_cache_singleton_for_test()
    yield
    reset_kg_cache_singleton_for_test()


@pytest.fixture(autouse=True)
def _isolate_kg_book_cache_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """每个测试用 tmp_path 独立 book-level KG 缓存 DB 文件 + 强制重建 singleton。

    与 batch 级 KG 缓存同库不同表——本 fixture 给 book-level 独立 DB 路径，
    避免现有 ``MinimalKGExtractor`` 集成测试因 book-level 命中而让 fake
    client ``call_count`` 期望失真。
    """
    monkeypatch.setenv(
        "BOOKSCOPE_KG_BOOK_CACHE_DB_PATH", str(tmp_path / "kg_book_cache.db")
    )
    from bookscope.agent._internal.kg_book_cache import (
        reset_book_kg_cache_singleton_for_test,
    )

    reset_book_kg_cache_singleton_for_test()
    yield
    reset_book_kg_cache_singleton_for_test()
