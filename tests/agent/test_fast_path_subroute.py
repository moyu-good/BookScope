"""``fast_path`` 子路由分类单测（Sprint 5.5 PE deliverable）。

Sprint 5.5 把单一 ``"fast"`` 路径拆为四类：

- ``fast_general``：列举 / 通识题（"主要角色有哪几个"）
- ``fast_review``：评论题（"这本书讲了什么"）
- ``fast_summary``：摘要题（"全书梗概"）
- ``fast_rating``：评分题（"值得看吗"）

本文件覆盖：

1. 4 子类各自题面正确归类（每类至少 2 题）
2. 优先级判定：rating > review > summary > general
3. 诊断词压所有 fast 子类（"分析…讲了什么" → agent_loop）
4. ``run_fast_path`` 接 ``subroute`` 参数后能选到对应 prompt
"""

from __future__ import annotations

import json
from typing import Any

from bookscope.agent.fast_path import (
    _FAST_PATH_PROMPT_PATHS,
    _load_subroute_prompt,
    run_fast_path,
)
from bookscope.agent.tools.schemas import ChunkMatch

# ---------------------------------------------------------------------------
# 测试替身：本文件单独定义避免循环依赖
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, input_tokens: int = 12, output_tokens: int = 8) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeResponse:
    def __init__(self, content: list[dict[str, Any]]) -> None:
        self.content = content
        self.stop_reason = "end_turn"
        self.usage = _FakeUsage()


class _CapturingAdapter:
    """记录每次 messages_create 的 system 字段，方便断言走了哪份 prompt。

    r1 风格响应——extract_final_text 读 ``content`` block list、
    extract_usage_tokens 读 ``input_tokens`` / ``output_tokens``。
    """

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.last_system: str | None = None
        self.call_count = 0

    def messages_create(self, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_system = kwargs.get("system")
        return self._response

    def extract_final_text(self, response: Any) -> str:
        blocks = getattr(response, "content", None) or []
        parts: list[str] = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts).strip()

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0
        return int(getattr(usage, "input_tokens", 0) or 0), int(
            getattr(usage, "output_tokens", 0) or 0
        )


class _FakeSearchBackend:
    def __init__(self, matches: list[ChunkMatch]) -> None:
        self._matches = matches
        self.call_count = 0

    def retrieve(
        self,
        query: str,
        chapter_scope: tuple[int, int] | None,
        character_filter: list[str] | None,
        top_k: int,
    ) -> list[ChunkMatch]:
        self.call_count += 1
        return list(self._matches)


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _final_json_text(answer: str, citations: list[dict[str, Any]]) -> str:
    return json.dumps({"answer": answer, "citations": citations}, ensure_ascii=False)


def _make_chunk(chapter: int = 1, text: str = "原文片段") -> ChunkMatch:
    return ChunkMatch(
        chunk_id=f"r0-chunk-{chapter}",
        chapter=chapter,
        text=text,
        relevance_score=1.0,
        contains_characters=[],
        source_version="r0",
    )


# ---------------------------------------------------------------------------
# 1. 子路由归类测试（fast_path 砍 5 类到 2 类后已删）
# ---------------------------------------------------------------------------
#
# 历史 Sprint 5.5 把 fast 分成 4 子类（general / review / summary / rating）
# 并各自校验题面归类。当前轮把路由判定简化成"字数主信号 + 诊断词兜底"
# 后，路由只产生 ``fast_general`` 和 ``agent_loop`` 两类——review / summary
# / rating 三类的归类语义已经不存在。
#
# 路由判定本身的覆盖在 ``test_fast_path.py::TestRouteQuestion`` 里。本
# 文件只保留 prompt 加载相关的 contract 测试。


# ---------------------------------------------------------------------------
# 2. prompt 加载与传递（保留）
# ---------------------------------------------------------------------------


class TestSubroutePromptLoading:
    """``run_fast_path`` 接 subroute 后能选到对应 prompt。"""

    def test_all_four_prompt_files_exist(self) -> None:
        """4 份 prompt 文件都已落盘。"""
        for subroute, path in _FAST_PATH_PROMPT_PATHS.items():
            assert path.exists(), f"{subroute} prompt missing: {path}"
            assert path.read_text(encoding="utf-8").strip(), f"{subroute} 文件空"

    def test_load_each_subroute_returns_distinct_prompt(self) -> None:
        """4 份 prompt 文本互不相同——证明分类有效拆分了风格。"""
        general = _load_subroute_prompt("fast_general")
        review = _load_subroute_prompt("fast_review")
        summary = _load_subroute_prompt("fast_summary")
        rating = _load_subroute_prompt("fast_rating")
        assert len({general, review, summary, rating}) == 4

    def test_unknown_subroute_falls_back_to_v1(self) -> None:
        """未知 subroute → 回退 v1 兜底（不抛异常）。"""
        text = _load_subroute_prompt("fast_unknown_xxx")
        assert "BookScope" in text or "原文片段" in text

    def test_legacy_fast_alias_maps_to_general(self) -> None:
        """``"fast"`` 字面量向后兼容映射到 fast_general。"""
        assert _load_subroute_prompt("fast") == _load_subroute_prompt("fast_general")

    def test_run_fast_path_uses_review_prompt_when_subroute_review(self) -> None:
        """subroute=fast_review 时 LLM call 拿到的 system 应是评论题 prompt。"""
        adapter = _CapturingAdapter(
            _FakeResponse(
                content=[
                    _text_block(
                        _final_json_text(
                            "这是一本……",
                            [{"chapter": 1, "snippet": "片段。"}],
                        )
                    )
                ]
            )
        )
        search = _FakeSearchBackend(matches=[_make_chunk(1, "片段。")])
        result = run_fast_path(
            "这本书讲了什么",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
            subroute="fast_review",
        )
        assert result is not None
        assert adapter.last_system is not None
        # review prompt 关键标记词
        assert "评论者" in adapter.last_system or "维基词条" in adapter.last_system

    def test_run_fast_path_uses_rating_prompt_when_subroute_rating(self) -> None:
        """subroute=fast_rating 时 system 应是评分题 prompt。"""
        adapter = _CapturingAdapter(
            _FakeResponse(
                content=[
                    _text_block(
                        _final_json_text(
                            "值得看，但……",
                            [{"chapter": 1, "snippet": "片段。"}],
                        )
                    )
                ]
            )
        )
        search = _FakeSearchBackend(matches=[_make_chunk(1, "片段。")])
        result = run_fast_path(
            "这本书写得怎么样",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
            subroute="fast_rating",
        )
        assert result is not None
        # rating prompt 标记词
        assert "推荐" in adapter.last_system  # type: ignore[operator]
