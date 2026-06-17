"""``bookscope.agent.fast_path`` 单测（Sprint 5 BE 第二项 deliverable）。

覆盖：
1. ``_route_question`` 启发式分类——通识题 / 诊断题 / 边界样例
2. ``run_fast_path`` 1 search + 1 LLM 成功路径（含 trace.outcome 校验）
3. search backend 抛错 → 返回 None（触发 fallback）
4. LLM 调用失败 → 返回 None
5. env ``BOOKSCOPE_FAST_PATH_DISABLED=1`` → ``route_question`` 永远返回 ``"agent_loop"``
6. LLM 解析失败 → 返回 None
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

from bookscope.agent.fast_path import (
    ENV_DISABLED,
    FAST_SUBROUTES,
    _route_question,
    route_question,
    run_fast_path,
)
from bookscope.agent.tools.schemas import ChunkMatch

# ---------------------------------------------------------------------------
# 测试替身：复用 test_agent_loop 风格——本文件单独定义避免循环依赖
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


class _FakeAdapter:
    """实现 LLMClient Protocol 的最简 fake；按队列吐 response 或抛异常。

    本 fake 故意保留 r1 风格的 ``_FakeResponse`` 形态（``content`` block list
    + ``usage.input_tokens`` / ``usage.output_tokens``），用来证明 Backlog
    B-1 落地后 adapter 抽象层确实解耦了响应形态——同一份 ``fast_path`` 代
    码既能跑 r2 真实 adapter（OpenAI choices 形态），也能跑这套 r1 风格
    fake，不靠 protocol-aware sniffing。
    """

    def __init__(
        self,
        responses: list[_FakeResponse] | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._responses = list(responses or [])
        self._raise_exc = raise_exc
        self.call_count = 0
        self.last_kwargs: dict[str, Any] | None = None

    def messages_create(self, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_kwargs = kwargs
        if self._raise_exc is not None:
            raise self._raise_exc
        if not self._responses:
            raise AssertionError("FakeAdapter ran out of prepared responses")
        return self._responses.pop(0)

    def extract_final_text(self, response: Any) -> str:
        """从 r1 风格 ``_FakeResponse`` 抽 final 文本——拼所有 text block。"""
        if response is None:
            return ""
        blocks = getattr(response, "content", None) or []
        parts: list[str] = []
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text", "")
                if isinstance(t, str):
                    parts.append(t)
        return "\n".join(parts).strip()

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        """从 r1 风格 ``_FakeUsage`` 抽 ``(input_tokens, output_tokens)``。"""
        usage = getattr(response, "usage", None)
        if usage is None:
            return 0, 0
        return int(getattr(usage, "input_tokens", 0) or 0), int(
            getattr(usage, "output_tokens", 0) or 0
        )


class _FakeSearchBackend:
    """返回预置 ChunkMatch 列表；可注入 raise 触发 fallback 路径。"""

    def __init__(
        self,
        matches: list[ChunkMatch] | None = None,
        *,
        raise_exc: Exception | None = None,
    ) -> None:
        self._matches = matches or []
        self._raise_exc = raise_exc
        self.call_count = 0

    def retrieve(
        self,
        query: str,
        chapter_scope: tuple[int, int] | None,
        character_filter: list[str] | None,
        top_k: int,
    ) -> list[ChunkMatch]:
        self.call_count += 1
        if self._raise_exc is not None:
            raise self._raise_exc
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
# 1. 启发式分类
# ---------------------------------------------------------------------------


class TestRouteQuestion:
    """``_route_question`` 启发式分类覆盖。"""

    @pytest.mark.parametrize(
        "question",
        [
            "主要角色有哪几个？",
            "故事发生在哪个朝代？",
            "全书共有几章？",
            "主角是谁",
            "讲的是什么",
        ],
    )
    def test_general_questions_route_fast(self, question: str) -> None:
        """通识 / 评论 / 摘要 / 评分题样例必须路由到任一 fast 子类。

        Sprint 5.5 起 ``"fast"`` 拆为 4 子类；这一组样例不固定到具体子
        类，只断言不会落到 ``agent_loop``。具体子类归属看
        :class:`TestRouteSubrouteClassification`。
        """
        assert _route_question(question) in FAST_SUBROUTES

    @pytest.mark.parametrize(
        "question",
        [
            "主角性格转变是渐变还是硬扳？",
            "支线 A 的高潮章在哪一章？",
            "请分析全书的节奏铺垫策略",
            "评估第三章对主线的伏笔是否到位",
            "对比朱元璋和朱棣的塑造手法异同",
        ],
    )
    def test_diagnostic_questions_route_agent_loop(self, question: str) -> None:
        """诊断题样例必须路由到 agent_loop。"""
        assert _route_question(question) == "agent_loop"

    def test_borderline_keywords_conservative(self) -> None:
        """同时含列举词+判断词时保守 → agent_loop。"""
        # 含"几个"（fast 信号）也含"分析"（diagnostic 信号）→ agent_loop
        assert _route_question("分析全书主要角色有哪几个的塑造层次") == "agent_loop"

    def test_long_question_routes_agent_loop(self) -> None:
        """题面过长（>= 30 字）即使含通识词也走 agent_loop。

        长题大概率不是简单通识题，长度兜底是误判保护层；典型场景：
        用户把多个子问题写在一个长句里。
        """
        # 30+ 字、含"主要角色"（fast 信号）但无诊断词——纯靠长度兜底
        long_q = (
            "请帮我把这本书里所有主要角色的初次出场章节以及相关原文"
            "片段都列出来给我整理一份完整的资料"
        )
        # 验证设计前提：> 30 字
        assert len(long_q.replace(" ", "")) >= 30
        assert _route_question(long_q) == "agent_loop"

    def test_short_unknown_question_defaults_fast_general(self) -> None:
        """fast_path 砍 5 类到 2 类后：短题 + 无诊断词 → fast_general。

        与旧版本不同——旧路由 4 个 keyword set 全 miss 才兜底 agent_loop；
        新路由按字数主信号 + 诊断词兜底两条规则判定，短无诊断词 = 普通
        通识题，进 fast_general。
        """
        assert _route_question("这是一个普通问题") == "fast_general"

    def test_authors_strongest_argument_12_chars_routes_deep(self) -> None:
        """关键反例：``"作者最强的论点是什么？"`` 12 字也是深题。

        作者明示当前关键词路由"区分很差"——这题字数远低于 30 字阈值，
        但内容里"论点""最强""为什么"是判断词。诊断词兜底必须命中。
        """
        q = "作者最强的论点是什么？"
        assert len(re.sub(r"\s+", "", q)) < 30
        assert _route_question(q) == "agent_loop"

    def test_most_surprising_finding_routes_deep(self) -> None:
        """反例 2：``"这本书最让人意外的发现是什么？"`` —— 含"意外"。"""
        assert _route_question("这本书最让人意外的发现是什么？") == "agent_loop"

    def test_what_makes_it_unique_routes_deep(self) -> None:
        """反例 3：``"和同类书比，这本独到在哪里？"`` —— 含"独到""比"。"""
        assert _route_question("和同类书比，这本独到在哪里？") == "agent_loop"

    def test_simple_factual_routes_fast_general(self) -> None:
        """简单事实题样例 → fast_general 验证。"""
        assert _route_question("故事发生在什么时代？") == "fast_general"
        assert _route_question("主要角色有哪几个？") == "fast_general"

    def test_route_decision_only_emits_two_types(self) -> None:
        """route_question 当前实现只会返回 fast_general / agent_loop 两类。

        枚举一批样题，断言每一题的 route 都落在这两个值里——证明
        review / summary / rating 三类不再触发。
        """
        samples = [
            "主要角色有哪几个",
            "故事发生在哪个朝代",
            "这本书讲了什么",  # 旧路由会走 fast_review
            "请给个全书概括",  # 旧路由会走 fast_summary
            "这本书好看吗",  # 旧路由会走 fast_rating；新路由"如何"命中诊断
            "主角性格转变是渐变还是硬扳",
            "作者最强的论点是什么",
        ]
        seen = {_route_question(q) for q in samples}
        assert seen.issubset({"fast_general", "agent_loop"}), (
            f"unexpected route types: {seen}"
        )


# ---------------------------------------------------------------------------
# 2. run_fast_path 成功路径
# ---------------------------------------------------------------------------


class TestRunFastPathSuccess:
    def test_single_search_single_llm_returns_result(self) -> None:
        """通识题 1 search + 1 LLM call 成功返回带 citation 的结果。"""
        adapter = _FakeAdapter(
            [
                _FakeResponse(
                    content=[
                        _text_block(
                            _final_json_text(
                                "主要角色包括朱元璋。",
                                [{"chapter": 1, "snippet": "朱元璋称帝。"}],
                            )
                        )
                    ]
                )
            ]
        )
        search = _FakeSearchBackend(matches=[_make_chunk(1, "朱元璋称帝。")])
        result = run_fast_path(
            "主要角色有哪几个",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
        )
        assert result is not None
        assert result.answer == "主要角色包括朱元璋。"
        assert len(result.citations) == 1
        assert result.citations[0]["chapter"] == 1
        assert result.trace.outcome == "fast_path_success"
        assert result.trace.iterations == 1
        # 唯一一条 tool_call 应是 search_chunks
        assert len(result.trace.tool_calls) == 1
        assert result.trace.tool_calls[0]["tool_name"] == "search_chunks"
        assert result.trace.tool_calls[0]["status"] == "ok"
        assert search.call_count == 1
        assert adapter.call_count == 1

    def test_streaming_callback_emits_expected_event_sequence(self) -> None:
        """on_event callback 收到 iteration_start / tool_use / tool_result / final_answer。"""
        events: list[Any] = []
        adapter = _FakeAdapter(
            [
                _FakeResponse(
                    content=[
                        _text_block(
                            _final_json_text(
                                "答复。",
                                [{"chapter": 2, "snippet": "片段。"}],
                            )
                        )
                    ]
                )
            ]
        )
        search = _FakeSearchBackend(matches=[_make_chunk(2, "片段。")])
        result = run_fast_path(
            "讲的是什么",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
            on_event=events.append,
        )
        assert result is not None
        # 5 个事件按顺序：route_decision 入口首帧 + iter_start + tool_use
        # + tool_result + final_answer。route_decision 是 Sprint 路由可视化
        # 加的"开始一帧"——FE 立刻知道走 fast 哪类。
        types = [e.type for e in events]
        assert types == [
            "route_decision",
            "iteration_start",
            "tool_use",
            "tool_result",
            "final_answer",
        ]


# ---------------------------------------------------------------------------
# 3. fallback 路径
# ---------------------------------------------------------------------------


class TestRunFastPathFallback:
    def test_search_backend_raises_returns_none(self) -> None:
        """search backend 抛错 → 返回 None（触发上层 fallback）。"""
        adapter = _FakeAdapter([])  # 不应被调用
        search = _FakeSearchBackend(raise_exc=RuntimeError("vector store down"))
        result = run_fast_path(
            "主要角色有哪几个",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
        )
        assert result is None
        # LLM 不应该被调用
        assert adapter.call_count == 0

    def test_llm_call_raises_returns_none(self) -> None:
        """LLM 调用抛错 → 返回 None。"""
        adapter = _FakeAdapter(raise_exc=RuntimeError("connection reset"))
        search = _FakeSearchBackend(matches=[_make_chunk()])
        result = run_fast_path(
            "故事发生在哪个朝代",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
        )
        assert result is None
        assert search.call_count == 1

    def test_llm_returns_invalid_json_returns_none(self) -> None:
        """LLM 输出无法解析为 JSON → 返回 None。"""
        adapter = _FakeAdapter(
            [_FakeResponse(content=[_text_block("这不是 JSON 而且没结构")])]
        )
        search = _FakeSearchBackend(matches=[_make_chunk()])
        result = run_fast_path(
            "主要角色有哪几个",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
        )
        assert result is None

    def test_empty_search_result_returns_none(self) -> None:
        """search 返回空列表 → 没素材作答，返回 None。"""
        adapter = _FakeAdapter([])  # 不应被调用
        search = _FakeSearchBackend(matches=[])
        result = run_fast_path(
            "主要角色有哪几个",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
        )
        assert result is None
        assert adapter.call_count == 0


# ---------------------------------------------------------------------------
# 4. WP1 citation 可信链：auto_filled 标记 + verify 标注
# ---------------------------------------------------------------------------


class TestCitationTrustChain:
    """WP1（docs/internal/design/WP1-citation-trust-chain.md）fast_path 侧验收。"""

    def test_auto_filled_citation_marked(self) -> None:
        """LLM 没给 citations → 系统自动拼的那条带 auto_filled=True。"""
        adapter = _FakeAdapter(
            [
                _FakeResponse(
                    content=[
                        _text_block(json.dumps({"answer": "主角是朱元璋。", "citations": []}))
                    ]
                )
            ]
        )
        chunk_text = "朱元璋自幼家贫，后投军郭子兴麾下，屡立战功。"
        search = _FakeSearchBackend(matches=[_make_chunk(1, chunk_text)])
        result = run_fast_path(
            "主角是谁",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
        )
        assert result is not None
        cit = result.citations[0]
        assert cit["auto_filled"] is True
        # 自动拼的文本取自 chunk → 系统校验自然通过
        assert cit["verified"] is True
        assert cit["chunk_id"] == "r0-chunk-1"
        assert cit["match_score"] == 1.0

    def test_llm_citation_from_chunk_verified(self) -> None:
        """LLM 给的 citation 同样过校验层——原文 snippet 标 verified=True。"""
        chunk_text = "朱元璋自幼家贫，后投军郭子兴麾下，屡立战功。"
        adapter = _FakeAdapter(
            [
                _FakeResponse(
                    content=[
                        _text_block(
                            _final_json_text(
                                "主角是朱元璋。",
                                [{"chapter": 1, "snippet": "后投军郭子兴麾下，屡立战功。"}],
                            )
                        )
                    ]
                )
            ]
        )
        search = _FakeSearchBackend(matches=[_make_chunk(1, chunk_text)])
        result = run_fast_path(
            "主角是谁",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
        )
        assert result is not None
        cit = result.citations[0]
        assert cit.get("auto_filled") is None  # LLM 给的不该带 auto_filled
        assert cit["verified"] is True
        assert cit["chunk_id"] == "r0-chunk-1"

    def test_llm_fabricated_citation_unverified_but_kept(self) -> None:
        """编造 snippet → verified=False；只观测不执法，结果照常返回。"""
        adapter = _FakeAdapter(
            [
                _FakeResponse(
                    content=[
                        _text_block(
                            _final_json_text(
                                "主角是朱元璋。",
                                [{"chapter": 1, "snippet": "刘伯温夜观天象断言金陵有王气。"}],
                            )
                        )
                    ]
                )
            ]
        )
        search = _FakeSearchBackend(
            matches=[_make_chunk(1, "朱元璋自幼家贫，后投军郭子兴麾下。")]
        )
        result = run_fast_path(
            "主角是谁",
            search_backend=search,
            llm_client=adapter,
            model="deepseek-chat",
        )
        assert result is not None
        cit = result.citations[0]
        assert cit["verified"] is False
        assert cit["chunk_id"] is None


# ---------------------------------------------------------------------------
# 5. env 旁路
# ---------------------------------------------------------------------------


class TestEnvDisabled:
    def test_env_disabled_forces_agent_loop(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``BOOKSCOPE_FAST_PATH_DISABLED=1`` → route_question 一律返 agent_loop。"""
        monkeypatch.setenv(ENV_DISABLED, "1")
        # 即使是典型通识题也强制走 agent_loop
        assert route_question("主要角色有哪几个") == "agent_loop"

    def test_env_unset_uses_heuristic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env 未设置时遵循启发式判定。"""
        monkeypatch.delenv(ENV_DISABLED, raising=False)
        assert route_question("主要角色有哪几个") in FAST_SUBROUTES

    def test_env_other_value_uses_heuristic(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """env 设为非 ``"1"`` 时仍走启发式。"""
        monkeypatch.setenv(ENV_DISABLED, "0")
        assert route_question("主要角色有哪几个") in FAST_SUBROUTES
