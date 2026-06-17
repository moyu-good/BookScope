"""Sprint 4 第一波 r2 骨架接通验证。

ADR-007 D-1 ~ D-5 第一波（骨架落地，不切核心逻辑）的最小验证：

- ``LoopTrace.protocol_version`` 字段默认 r1，可显式置 r2
- ``_select_agent_loop_class`` 按 env flag 路由 r1 / r2
- r2 ``AgentLoop`` 骨架是 r1 ``AgentLoop`` 的子类（占位身份）

骨架阶段 r2 == r1 行为，因此本测试不验证协议差异；只验证骨架接通
正确——env flag 能切，trace 字段存在并能记录，子类身份不歪。
"""

from __future__ import annotations

import pytest

from bookscope.agent import _select_agent_loop_class
from bookscope.agent.loop_r2 import AgentLoop as R2AgentLoop
from bookscope.agent.models import LoopTrace


def test_loop_trace_protocol_version_default_r1() -> None:
    """不传 protocol_version 字段时，LoopTrace 默认 r1（向后兼容旧 trace 数据）。"""
    trace = LoopTrace()

    assert trace.protocol_version == "r1"


def test_loop_trace_protocol_version_explicit_r2() -> None:
    """显式传 protocol_version="r2" 应该被 Literal 类型接受并存住。"""
    trace = LoopTrace(protocol_version="r2")

    assert trace.protocol_version == "r2"


def test_select_agent_loop_class_default_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sprint 6 默认切到 r2——env 没设时返回 r2 AgentLoop（ADR-007 已批准）。

    撤回路径：显式 ``BOOKSCOPE_AGENT_PROTOCOL=r1`` 仍可回滚到 r1，作 Sprint 7
    删 r1 前的最后兜底窗口。
    """
    monkeypatch.delenv("BOOKSCOPE_AGENT_PROTOCOL", raising=False)

    selected = _select_agent_loop_class()

    assert selected is R2AgentLoop


def test_select_agent_loop_class_r2_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """env BOOKSCOPE_AGENT_PROTOCOL=r2 时返回 r2 AgentLoop（显式与默认一致）。"""
    monkeypatch.setenv("BOOKSCOPE_AGENT_PROTOCOL", "r2")

    selected = _select_agent_loop_class()

    assert selected is R2AgentLoop


