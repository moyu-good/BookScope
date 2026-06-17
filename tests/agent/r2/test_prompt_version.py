"""WP0 prompt 版本链哨兵测试（2026-06-10）.

守护三件事——任何一件再被静默破坏，本套测试先叫：

1. 生产默认 prompt 版本 = ``CURRENT_PROMPT_VERSION``（防"重构搬家时
   常量值被冻结"复发——第 26 轮 v3.1 冻结三个月无人发现的直接教训）
2. env override ``BOOKSCOPE_LOOP_PROMPT_PATH`` 在 r2 加载层真生效
   （防旧 patch 机制那种"指向已删除模块"的静默失效）
3. ``LoopTrace.prompt_version`` 如实记录实际加载版本（版本是记录的
   事实，不是 CLI 口头标注——exp006 数据归属事故防再犯）

设计稿：``docs/internal/design/WP0-prompt-version-chain.md``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bookscope.agent._internal import loop_shared


def _final_json_text(answer: str, citations: list[dict[str, Any]]) -> str:
    return json.dumps({"answer": answer, "citations": citations}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# 1. 单一事实源哨兵
# ---------------------------------------------------------------------------


class TestPromptVersionSentinel:
    def test_current_version_is_v3_5(self):
        """生产默认版本断言——改版本必须有意识地改这条测试。"""
        assert loop_shared.CURRENT_PROMPT_VERSION == "v3.5"

    def test_default_path_derived_from_current_version(self):
        """路径由版本常量拼出（单一事实源），且文件真实存在。"""
        expected_name = (
            f"loop_system_prompt_{loop_shared.CURRENT_PROMPT_VERSION}.md"
        )
        assert loop_shared.SYSTEM_PROMPT_PATH.name == expected_name
        assert loop_shared.SYSTEM_PROMPT_PATH.is_file()

    def test_default_prompt_header_matches_version(self):
        """加载出的 prompt 文本头部自报版本号与常量一致——文件内容与
        文件名不许打架。"""
        text = loop_shared.SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        first_line = text.splitlines()[0]
        assert loop_shared.CURRENT_PROMPT_VERSION in first_line


# ---------------------------------------------------------------------------
# 2. 版本解析 + env override
# ---------------------------------------------------------------------------


class TestPromptPathResolution:
    def test_version_from_standard_filename(self):
        path = Path("loop_system_prompt_v3.5.md")
        assert loop_shared.prompt_version_from_path(path) == "v3.5"

    def test_version_from_nonstandard_filename_falls_back_to_stem(self):
        assert loop_shared.prompt_version_from_path(Path("custom.md")) == "custom"

    def test_no_override_resolves_default(self, monkeypatch):
        monkeypatch.delenv(loop_shared.PROMPT_PATH_ENV_VAR, raising=False)
        assert (
            loop_shared.resolve_system_prompt_path()
            == loop_shared.SYSTEM_PROMPT_PATH
        )
        assert (
            loop_shared.current_prompt_version()
            == loop_shared.CURRENT_PROMPT_VERSION
        )

    def test_env_override_takes_effect(self, tmp_path, monkeypatch):
        """override 不再走 patch 模块属性的死路——加载层直接读 env。"""
        override = tmp_path / "loop_system_prompt_vtest.md"
        override.write_text("# override prompt vtest", encoding="utf-8")
        monkeypatch.setenv(loop_shared.PROMPT_PATH_ENV_VAR, str(override))

        assert loop_shared.resolve_system_prompt_path() == override
        assert loop_shared.current_prompt_version() == "vtest"
        assert loop_shared.load_system_prompt(None) == "# override prompt vtest"


# ---------------------------------------------------------------------------
# 3. trace 如实记录
# ---------------------------------------------------------------------------


class TestTracePromptVersion:
    def test_trace_carries_default_version(
        self, r2_response_factory, r2_fake_client, make_r2_loop, monkeypatch
    ):
        """默认配置下 query 一次，trace.prompt_version = 生产默认版本。"""
        monkeypatch.delenv(loop_shared.PROMPT_PATH_ENV_VAR, raising=False)
        client = r2_fake_client(
            [
                r2_response_factory(
                    content=_final_json_text(
                        "答案", [{"chapter": 1, "snippet": "原文片段"}]
                    )
                )
            ]
        )
        loop = make_r2_loop(client)
        result = loop.query("这本书第一章讲了什么？")
        assert result.trace.prompt_version == loop_shared.CURRENT_PROMPT_VERSION

    def test_trace_reflects_override_version(
        self, r2_response_factory, r2_fake_client, make_r2_loop, tmp_path, monkeypatch
    ):
        """override 生效时 trace 如实反映 override 的版本，不撒谎。"""
        override = tmp_path / "loop_system_prompt_vtest.md"
        override.write_text(
            "# vtest\n回答任何问题都必须输出 JSON：answer + citations。",
            encoding="utf-8",
        )
        monkeypatch.setenv(loop_shared.PROMPT_PATH_ENV_VAR, str(override))

        client = r2_fake_client(
            [
                r2_response_factory(
                    content=_final_json_text(
                        "答案", [{"chapter": 1, "snippet": "原文片段"}]
                    )
                )
            ]
        )
        loop = make_r2_loop(client)
        result = loop.query("这本书第一章讲了什么？")
        assert result.trace.prompt_version == "vtest"

    def test_loop_trace_default_is_empty_for_legacy_data(self):
        """旧 batch JSON 没有该字段时反序列化不炸，默认空串。"""
        from bookscope.agent.models import LoopTrace

        trace = LoopTrace(protocol_version="r2")
        assert trace.prompt_version == ""
