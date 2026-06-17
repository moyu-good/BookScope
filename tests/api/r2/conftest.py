"""``tests/api/r2`` 共用 fixture：autouse 锁 ``BOOKSCOPE_AGENT_PROTOCOL=r2``。

ADR-007 Sprint 6（commit ``88ab2d9``）把默认协议从 r1 切到 r2。父目录
``tests/api/conftest.py`` 用 autouse fixture 把 env 锁回 r1，保旧 22 个
按 Anthropic ``content_blocks`` / ``stop_reason`` 形态写的 mock 测试继续过。

本子目录的测试反向——必须走 r2 路径 / r2 ``loop_r2.AgentLoop`` / OpenAI
``choices`` 形态。下面这条 autouse fixture **强制覆盖父级 r1 锁**，把 env
拉回 r2。pytest fixture 解析按目录就近原则——子目录 autouse 在父目录
autouse 之后跑，所以子目录的 ``monkeypatch.setenv`` 是最终生效值。

ADR-007 Migration Plan 提到的"测试改造范围"在 Sprint 6 内只搭范式：本
conftest + 两个代表性测试（``test_agent_ask_r2.py`` happy path /
``test_error_handling_e2e_r2.py`` error path）。后续 Sprint 按这套 pattern
补全套测试。
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _lock_r2_protocol_for_api_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """强制锁 ``BOOKSCOPE_AGENT_PROTOCOL=r2``，覆盖父级 r1 锁。

    覆盖目的：``tests/api/conftest.py`` 默认锁 r1 给旧 mock 套兜底；本目录
    测试用 OpenAI ``choices`` 形态桩，必须走 r2 ``loop_r2.AgentLoop``，
    所以反向锁回 r2。
    """
    monkeypatch.setenv("BOOKSCOPE_AGENT_PROTOCOL", "r2")
