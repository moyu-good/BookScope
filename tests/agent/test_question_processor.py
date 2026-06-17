"""``question_processor`` —— 长题预处理引擎单测。

覆盖范围：
1. ``ProcessedQuestion`` dataclass 形态（frozen / 字段齐全）
2. 主入口 ``process_question`` 三个核心 happy path（simple / complex / 指定章节）
3. 三种失败 fallback（LLM 抛 / JSON 非法 / timeout）
4. ``QuestionProcessedEvent`` dataclass 形态
5. agent_loop 接入：长题触发 / 短题跳过 / env flag 关闭

设计：不跑真 LLM，自带 fakes 保隔离；只验证拆题、章节、难度 normalise
逻辑 + emit 时机，不重测 loop 主流程的其它路径。
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest

from bookscope.agent.events import QuestionProcessedEvent
from bookscope.agent.question_processor import (
    MAX_SUBQUESTIONS,
    ProcessedQuestion,
    _extract_first_json_object,
    _parse_processor_json,
    build_system_addendum,
    process_question,
    rewrite_followup,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self) -> None:
        self.input_tokens = 10
        self.output_tokens = 5


class _FakeResponse:
    def __init__(
        self,
        content: list[dict[str, Any]],
        *,
        stop_reason: str = "end_turn",
    ) -> None:
        self.content = content
        self.stop_reason = stop_reason
        self.usage = _FakeUsage()


class _FakeAdapter:
    """单步 LLMClient fake——按 ``responses`` 队列依次返回。"""

    def __init__(self, responses: list[_FakeResponse] | None = None) -> None:
        self._responses = list(responses or [])
        self.call_count = 0
        self.last_system: str | None = None
        self.last_messages: list[dict[str, Any]] | None = None

    def messages_create(self, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_system = kwargs.get("system")
        self.last_messages = kwargs.get("messages")
        if not self._responses:
            raise AssertionError("FakeAdapter ran out of prepared responses")
        return self._responses.pop(0)


class _RaisingAdapter:
    """messages_create 直接抛异常——模拟 transport 失败。"""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.call_count = 0

    def messages_create(self, **kwargs: Any) -> Any:
        self.call_count += 1
        raise self._exc


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _processor_response(payload: dict[str, Any]) -> _FakeResponse:
    return _FakeResponse(content=[_text_block(json.dumps(payload, ensure_ascii=False))])


# ---------------------------------------------------------------------------
# 1. ProcessedQuestion dataclass
# ---------------------------------------------------------------------------


class TestProcessedQuestionDataclass:
    def test_processed_question_dataclass_frozen(self) -> None:
        pq = ProcessedQuestion(
            original_question="问题",
            subquestions=["子问"],
            recommended_chapters=[1, 2],
            difficulty="simple",
            processing_duration_seconds=0.3,
        )
        assert pq.original_question == "问题"
        assert pq.subquestions == ["子问"]
        assert pq.recommended_chapters == [1, 2]
        assert pq.difficulty == "simple"
        with pytest.raises(dataclasses.FrozenInstanceError):
            pq.original_question = "改了"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. process_question happy path
# ---------------------------------------------------------------------------


class TestProcessQuestionHappyPath:
    def test_process_question_simple_returns_one_subquestion(self) -> None:
        adapter = _FakeAdapter(
            responses=[
                _processor_response(
                    {
                        "subquestions": ["第 3 章燕王起兵的导火索"],
                        "recommended_chapters": [3],
                        "difficulty": "simple",
                    }
                )
            ]
        )
        result = process_question(
            "第 3 章里燕王起兵的导火索是什么"
            "需要看具体哪一段就好",
            adapter,
        )
        assert result.subquestions == ["第 3 章燕王起兵的导火索"]
        assert result.recommended_chapters == [3]
        assert result.difficulty == "simple"
        assert adapter.call_count == 1

    def test_process_question_complex_returns_multiple(self) -> None:
        adapter = _FakeAdapter(
            responses=[
                _processor_response(
                    {
                        "subquestions": [
                            "朱元璋为什么废除丞相制度",
                            "废相对明朝后来政治格局的影响",
                            "前几章是怎么铺垫废相这一步的",
                        ],
                        "recommended_chapters": None,
                        "difficulty": "complex",
                    }
                )
            ]
        )
        result = process_question(
            "朱元璋为什么要废除丞相制度？这个决定对后来明朝的政治格局有什么影响？",
            adapter,
        )
        assert len(result.subquestions) == 3
        assert result.recommended_chapters is None
        assert result.difficulty == "complex"

    def test_process_question_recommended_chapters_specific(self) -> None:
        adapter = _FakeAdapter(
            responses=[
                _processor_response(
                    {
                        "subquestions": ["前几章如何铺垫废相"],
                        "recommended_chapters": [1, 2, 3],
                        "difficulty": "medium",
                    }
                )
            ]
        )
        result = process_question("废相的铺垫在前几章是怎么写的，节奏怎样", adapter)
        assert result.recommended_chapters == [1, 2, 3]

    def test_process_question_recommended_chapters_null_for_whole_book(self) -> None:
        adapter = _FakeAdapter(
            responses=[
                _processor_response(
                    {
                        "subquestions": ["作者最强论点"],
                        "recommended_chapters": None,
                        "difficulty": "complex",
                    }
                )
            ]
        )
        result = process_question("整本书作者最想表达的核心论点究竟是什么", adapter)
        assert result.recommended_chapters is None

    def test_process_question_truncates_excess_subquestions(self) -> None:
        """LLM 返回 5 个子问 → 截到前 3 个。"""
        adapter = _FakeAdapter(
            responses=[
                _processor_response(
                    {
                        "subquestions": ["q1", "q2", "q3", "q4", "q5"],
                        "recommended_chapters": None,
                        "difficulty": "medium",
                    }
                )
            ]
        )
        result = process_question("原题不重要这里测截断", adapter)
        assert len(result.subquestions) == MAX_SUBQUESTIONS
        assert result.subquestions == ["q1", "q2", "q3"]

    def test_process_question_invalid_difficulty_defaults_medium(self) -> None:
        adapter = _FakeAdapter(
            responses=[
                _processor_response(
                    {
                        "subquestions": ["q1"],
                        "recommended_chapters": None,
                        "difficulty": "very-hard",  # 非法
                    }
                )
            ]
        )
        result = process_question("测难度兜底逻辑测难度兜底逻辑测难度兜底", adapter)
        assert result.difficulty == "medium"

    def test_process_question_invalid_chapters_defaults_none(self) -> None:
        adapter = _FakeAdapter(
            responses=[
                _processor_response(
                    {
                        "subquestions": ["q1"],
                        "recommended_chapters": ["one", "two"],  # 非 int
                        "difficulty": "simple",
                    }
                )
            ]
        )
        result = process_question("测章节兜底逻辑测章节兜底逻辑", adapter)
        assert result.recommended_chapters is None


# ---------------------------------------------------------------------------
# 3. fallback 路径
# ---------------------------------------------------------------------------


class TestProcessQuestionFallback:
    def test_process_question_llm_failure_fallback(self) -> None:
        adapter = _RaisingAdapter(RuntimeError("network down"))
        original = "原题保留原题保留原题保留原题保留"
        result = process_question(original, adapter)
        assert result.original_question == original
        assert result.subquestions == [original]
        assert result.recommended_chapters is None
        assert result.difficulty == "medium"
        assert result.processing_duration_seconds == 0.0

    def test_process_question_json_parse_failure_fallback(self) -> None:
        adapter = _FakeAdapter(
            responses=[
                _FakeResponse(content=[_text_block("not json at all {{{")])
            ]
        )
        original = "JSON 非法时也要 fallback 不抛"
        result = process_question(original, adapter)
        assert result.subquestions == [original]

    def test_process_question_timeout_fallback(self) -> None:
        """模拟 transport 层抛 TimeoutError（processor 不区分异常类型）。"""
        adapter = _RaisingAdapter(TimeoutError("LLM timeout"))
        original = "超时也要 fallback 不阻断主 loop"
        result = process_question(original, adapter)
        assert result.subquestions == [original]
        assert result.difficulty == "medium"

    def test_process_question_empty_subquestions_fallback_to_original(self) -> None:
        adapter = _FakeAdapter(
            responses=[
                _processor_response(
                    {
                        "subquestions": [],
                        "recommended_chapters": None,
                        "difficulty": "simple",
                    }
                )
            ]
        )
        original = "空 subquestions 列表也兜底到原题"
        result = process_question(original, adapter)
        assert result.subquestions == [original]


# ---------------------------------------------------------------------------
# 4. QuestionProcessedEvent
# ---------------------------------------------------------------------------


class TestQuestionProcessedEvent:
    def test_question_processed_event_dataclass(self) -> None:
        ev = QuestionProcessedEvent(
            iteration=0,
            original="原题",
            subquestions=["子1", "子2"],
            recommended_chapters=[1, 2],
            difficulty="complex",
            duration_seconds=0.42,
        )
        assert ev.type == "question_processed"
        assert ev.original == "原题"
        assert ev.subquestions == ["子1", "子2"]
        assert ev.recommended_chapters == [1, 2]
        assert ev.difficulty == "complex"
        assert ev.iteration == 0
        with pytest.raises(dataclasses.FrozenInstanceError):
            ev.original = "改了"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 5. build_system_addendum
# ---------------------------------------------------------------------------


class TestBuildSystemAddendum:
    def test_build_addendum_multi_subquestions_with_chapters(self) -> None:
        pq = ProcessedQuestion(
            original_question="X",
            subquestions=["子1", "子2"],
            recommended_chapters=[1, 3],
            difficulty="complex",
        )
        s = build_system_addendum(pq)
        assert "子1" in s
        assert "子2" in s
        assert "第 1, 3 章" in s
        assert "complex" in s

    def test_build_addendum_single_subquestion_no_chapters(self) -> None:
        pq = ProcessedQuestion(
            original_question="X",
            subquestions=["仅一个子问"],
            recommended_chapters=None,
            difficulty="simple",
        )
        s = build_system_addendum(pq)
        assert "仅一个子问" in s
        assert "第" not in s.split("难度评估")[0] or "用户问题：仅一个子问" in s
        assert "simple" in s


# ---------------------------------------------------------------------------
# 6. AgentLoop 接入（已删）
# ---------------------------------------------------------------------------
#
# Sprint 7（2026-05-15）r1 ``loop.py`` 退役。本节原有 4 个 integration 测试
# （long_question_triggers / short_question_skips / env_flag_disables /
# processor_failure_does_not_block）用 Anthropic ``content_blocks`` 形态
# stub 响应直接驱动 ``bookscope.agent.AgentLoop``——AgentLoop 切到 r2 之后
# r2 期望 OpenAI ``tool_calls`` 形态，原 stub 不再匹配。
#
# 这 4 条 integration 跟着 r1 退役一起删；本文件留下的 unit 测试
# （TestProcessedQuestionDataclass / TestProcessQuestionHappyPath /
# TestProcessQuestionFallback / TestQuestionProcessedEvent /
# TestBuildSystemAddendum / TestParseProcessorJsonFallbacks）覆盖
# ``process_question`` 自身全部行为，loop 触发 question_processor 的接线
# 改由 r2 测试套在未来 Sprint 补一条 r2 形态 integration 即可（audit
# §3.3 漏判，Sprint 7 ③b 现场修正）。


# ---------------------------------------------------------------------------
# 7. _parse_processor_json 三层兜底
# ---------------------------------------------------------------------------


class TestParseProcessorJsonFallbacks:
    """dogfood 实测 minimax M2.7 等 reasoning model 输出格式坑点回归。

    三层剥：围栏 / <think>...</think> / 第一个 {...}。任一覆盖即可正常 parse。
    """

    def test_parse_strips_think_block(self) -> None:
        """reasoning model 内联 <think>...</think> 块剥掉再 parse。"""
        text = (
            '<think>let me analyze this question carefully</think>'
            '{"subquestions": ["q1"], "recommended_chapters": null, "difficulty": "simple"}'
        )
        obj = _parse_processor_json(text)
        assert obj["subquestions"] == ["q1"]
        assert obj["difficulty"] == "simple"

    def test_parse_handles_text_before_json(self) -> None:
        """JSON 前面带解释文字——靠 _extract_first_json_object 剥主体。"""
        text = (
            "Here is the JSON you requested:\n"
            '{"subquestions": ["q1"], "difficulty": "medium"}'
        )
        obj = _parse_processor_json(text)
        assert obj["subquestions"] == ["q1"]

    def test_parse_handles_text_after_json(self) -> None:
        """JSON 后面带 note——括号配对扫到第一个完整对象就停。"""
        text = (
            '{"subquestions": ["q1"], "difficulty": "complex"}\n'
            "Note: this is my best attempt."
        )
        obj = _parse_processor_json(text)
        assert obj["subquestions"] == ["q1"]
        assert obj["difficulty"] == "complex"

    def test_parse_handles_think_with_braces(self) -> None:
        """<think> 里写了花括号文本——剥 think 块后剩下才是真 JSON。"""
        text = (
            '<think>I should output {wrong: braces, not real json}</think>'
            '{"subquestions": ["actual"], "difficulty": "simple"}'
        )
        obj = _parse_processor_json(text)
        assert obj["subquestions"] == ["actual"]

    def test_parse_handles_nested_objects(self) -> None:
        """嵌套对象——深度计数走到最外层 } 才返回。"""
        text = '{"a": {"b": {"c": 1}}, "subquestions": ["x"]}'
        obj = _parse_processor_json(text)
        assert obj["a"] == {"b": {"c": 1}}
        assert obj["subquestions"] == ["x"]

    def test_parse_handles_braces_in_string(self) -> None:
        """字符串内出现 ``}``——in_string 状态机不计入深度。"""
        text = '{"subquestions": ["value with } inside"], "difficulty": "simple"}'
        obj = _parse_processor_json(text)
        assert obj["subquestions"] == ["value with } inside"]

    def test_extract_first_json_object_returns_none_when_no_brace(self) -> None:
        """纯文本无 ``{`` —— helper 返 None。"""
        assert _extract_first_json_object("no json here at all") is None

    def test_parse_handles_think_block_with_fenced_json(self) -> None:
        """围栏 + think 块 + 解释文字三件套全在一起。"""
        text = (
            "```json\n"
            '<think>analyzing...</think>\n'
            'Here it is: {"subquestions": ["q1"], "difficulty": "medium"}\n'
            "```"
        )
        obj = _parse_processor_json(text)
        assert obj["subquestions"] == ["q1"]


# ---------------------------------------------------------------------------
# 7b. flash 真实响应形态：plain dict + reasoning 截断（exp008）
# ---------------------------------------------------------------------------


def _flash_plain_dict_response(
    content: str | None, *, finish_reason: str = "stop"
) -> dict[str, Any]:
    """复刻 DeepSeekAdapter._response_to_plain_dict 吐给 processor 的形态。

    生产里 flash 走 OpenAI 兼容端点，adapter 把 ``ChatCompletion`` 转成这种
    plain dict（``choices[0].message.content`` + ``usage``）。processor 拿到的
    就是它，不是 SDK 对象——单测必须用同一形态才算真覆盖到生产路径。
    """
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": content},
                "finish_reason": finish_reason,
            }
        ],
        "usage": {"prompt_tokens": 771, "completion_tokens": 159},
    }


class _PlainDictAdapter:
    """按 ``responses`` 队列返回 plain dict（flash adapter 归一化后的形态）。"""

    def __init__(self, responses: list[Any]) -> None:
        self._responses = list(responses)
        self.call_count = 0
        self.last_messages: list[dict[str, Any]] | None = None

    def messages_create(self, **kwargs: Any) -> Any:
        self.call_count += 1
        self.last_messages = kwargs.get("messages")
        if not self._responses:
            raise AssertionError("PlainDictAdapter ran out of prepared responses")
        return self._responses.pop(0)


class TestFlashShapeResponse:
    """flash 经 adapter 归一化后的 plain dict 形态——拆题要能正确解析。

    exp008 烟测根因回归：``response missing both 'choices' and 'content'``。
    实测是 reasoning model 把 ``max_tokens`` 吃光、正文 ``content`` 返空串，
    不是响应畸形（``choices`` 一直都在）。
    """

    def test_flash_plain_dict_content_parses(self) -> None:
        """正常 flash 响应（content 有 JSON）—— 拆题正确取到子问。"""
        payload = json.dumps(
            {
                "subquestions": ["第10章埋设在后文是否回收", "回收点章节与原文引用"],
                "recommended_chapters": [10],
                "difficulty": "medium",
            },
            ensure_ascii=False,
        )
        adapter = _PlainDictAdapter([_flash_plain_dict_response(payload)])
        result = process_question("第10章这处埋设在后文有没有被回收这道题够长了", adapter)
        assert result.subquestions == ["第10章埋设在后文是否回收", "回收点章节与原文引用"]
        assert result.recommended_chapters == [10]
        assert result.difficulty == "medium"
        assert adapter.call_count == 1

    def test_flash_reasoning_truncated_empty_content_falls_back(self) -> None:
        """reasoning 吃光预算、content 返空串、finish_reason=length —— 干净 fallback。

        断言：choices 在但 content 空时不再误报"缺 choices"，而是当成截断
        fallback 到原题（subquestions=[original]），不抛、不阻断主流程。
        """
        adapter = _PlainDictAdapter(
            [_flash_plain_dict_response("", finish_reason="length")]
        )
        original = "reasoning 吃光预算时拆题也要兜底到原题不能炸"
        result = process_question(original, adapter)
        assert result.subquestions == [original]
        assert result.difficulty == "medium"

    def test_extract_text_distinguishes_truncation_from_malformed(self) -> None:
        """choices 在但 content 空 → 报截断错因；压根没 choices → 报缺字段。"""
        from bookscope.agent.question_processor import _extract_text

        truncated = {
            "choices": [{"message": {"content": ""}, "finish_reason": "length"}]
        }
        with pytest.raises(ValueError, match="message.content 为空"):
            _extract_text(truncated)

        malformed = {"usage": {"prompt_tokens": 1}}
        with pytest.raises(ValueError, match="missing both 'choices' and 'content'"):
            _extract_text(malformed)


# ---------------------------------------------------------------------------
# 8. 指代消解 · rewrite_followup（ADR-009 Phase 1b，D-2）
# ---------------------------------------------------------------------------


def _rewrite_response(text: str) -> _FakeResponse:
    """改写调用返回一行纯文本（不是 JSON）——模拟 v2 prompt 的输出形态。"""
    return _FakeResponse(content=[_text_block(text)])


def _openai_response(content: str) -> _FakeResponse:
    """OpenAI 形态 response 替身——content 在 choices[0].message.content。

    r2 生产默认 DeepSeek 走这个形态；用来验证 _extract_text 两种形态都接。
    """

    class _Msg:
        def __init__(self, c: str) -> None:
            self.content = c

    class _Choice:
        def __init__(self, c: str) -> None:
            self.message = _Msg(c)

    resp = _FakeResponse(content=[])
    resp.choices = [_Choice(content)]  # type: ignore[attr-defined]
    resp.content = None  # type: ignore[assignment]
    return resp


class TestRewriteFollowup:
    """``rewrite_followup`` 单元行为：有历史改写、无历史不改写、失败 fallback。"""

    def test_no_history_returns_none(self) -> None:
        """没历史（None）—— 不改写，返回 None，不发 LLM 调用。"""
        adapter = _FakeAdapter(responses=[])
        out = rewrite_followup("具体哪几章最稀？", adapter, conversation_history=None)
        assert out is None
        assert adapter.call_count == 0

    def test_empty_history_returns_none(self) -> None:
        """历史空列表—— 同样不改写。"""
        adapter = _FakeAdapter(responses=[])
        out = rewrite_followup("具体哪几章最稀？", adapter, conversation_history=[])
        assert out is None
        assert adapter.call_count == 0

    def test_with_history_rewrites_to_standalone(self) -> None:
        """带历史的追问—— 调一次 LLM，返回改写后的独立问题。"""
        adapter = _FakeAdapter(
            responses=[_rewrite_response("这本书节奏最稀疏的是哪几章")]
        )
        history = [
            {"question": "这本书节奏是不是前密后疏？", "answer": "是的，前二十章密集……"}
        ]
        out = rewrite_followup(
            "具体哪几章最稀？", adapter, conversation_history=history
        )
        assert out == "这本书节奏最稀疏的是哪几章"
        assert adapter.call_count == 1
        # 历史的问与答都拼进了改写调用的 user message
        user_msg = adapter.last_messages[0]["content"]
        assert "前密后疏" in user_msg
        assert "具体哪几章最稀？" in user_msg

    def test_rewrite_llm_failure_returns_none(self) -> None:
        """改写 LLM 抛—— fallback 返 None（用原题），不抛异常。"""
        adapter = _RaisingAdapter(RuntimeError("network down"))
        history = [{"question": "节奏前密后疏吗", "answer": "是的"}]
        out = rewrite_followup("哪几章最稀？", adapter, conversation_history=history)
        assert out is None
        assert adapter.call_count == 1

    def test_rewrite_empty_output_returns_none(self) -> None:
        """改写返回空串—— 当作没改写，返回 None。"""
        adapter = _FakeAdapter(responses=[_rewrite_response("   ")])
        history = [{"question": "节奏前密后疏吗", "answer": "是的"}]
        out = rewrite_followup("哪几章最稀？", adapter, conversation_history=history)
        assert out is None

    def test_rewrite_strips_fence_and_prefix(self) -> None:
        """模型多嘴包了代码围栏 / "改写为：" 前缀—— 清掉只留问题本身。"""
        adapter = _FakeAdapter(
            responses=[_rewrite_response("```\n改写为：第 12 到 18 章节奏密度如何\n```")]
        )
        history = [{"question": "节奏前密后疏吗", "answer": "是的"}]
        out = rewrite_followup("那几章呢？", adapter, conversation_history=history)
        assert out == "第 12 到 18 章节奏密度如何"

    def test_rewrite_reads_openai_shape_response(self) -> None:
        """r2 生产 DeepSeek 走 OpenAI 形态—— 改写也要能从 choices 抽文本。"""
        adapter = _FakeAdapter(
            responses=[_openai_response("朱元璋这个人物后面有没有变化")]
        )
        history = [{"question": "朱元璋前期怎么写的", "answer": "谨慎隐忍"}]
        out = rewrite_followup("后面有没有变化？", adapter, conversation_history=history)
        assert out == "朱元璋这个人物后面有没有变化"

    def test_rewrite_only_uses_recent_turns(self) -> None:
        """历史超过上限只取最近几轮—— 太早的轮次不进改写 prompt。"""
        adapter = _FakeAdapter(responses=[_rewrite_response("改写结果")])
        history = [
            {"question": "最早一问MARK_OLD", "answer": "答0"},
            {"question": "中间一问", "answer": "答1"},
            {"question": "再一问", "answer": "答2"},
            {"question": "最近一问", "answer": "答3"},
        ]
        rewrite_followup("这个呢？", adapter, conversation_history=history)
        user_msg = adapter.last_messages[0]["content"]
        # 默认上限 3 轮——最早那轮（第 4 早）被截掉
        assert "MARK_OLD" not in user_msg
        assert "最近一问" in user_msg


# ---------------------------------------------------------------------------
# 9. process_question 接通指代消解（ADR-009 Phase 1b）
# ---------------------------------------------------------------------------


class TestProcessQuestionWithHistory:
    """``process_question`` 带 conversation_history 时先改写再拆题。"""

    def test_no_history_rewritten_question_is_none(self) -> None:
        """无历史—— rewritten_question 留 None，行为与单轮一致（零回归）。"""
        adapter = _FakeAdapter(
            responses=[
                _processor_response(
                    {
                        "subquestions": ["子问"],
                        "recommended_chapters": None,
                        "difficulty": "medium",
                    }
                )
            ]
        )
        result = process_question("整本书核心论点究竟是什么这道题够长了吧", adapter)
        assert result.rewritten_question is None
        assert adapter.call_count == 1  # 只有拆题调用，没有改写调用

    def test_with_history_rewrites_then_splits(self) -> None:
        """有历史—— 先改写（调用 1）再基于改写问题拆题（调用 2）。"""
        adapter = _FakeAdapter(
            responses=[
                _rewrite_response("这本书节奏最稀疏的是哪几章"),
                _processor_response(
                    {
                        "subquestions": ["节奏最稀疏的章节"],
                        "recommended_chapters": None,
                        "difficulty": "medium",
                    }
                ),
            ]
        )
        history = [
            {"question": "节奏前密后疏吗", "answer": "是的，前二十章密集"}
        ]
        result = process_question(
            "具体哪几章最稀？", adapter, conversation_history=history
        )
        assert result.rewritten_question == "这本书节奏最稀疏的是哪几章"
        # 拆题调用收到的是改写后的问题，不是残句原题
        assert result.original_question == "具体哪几章最稀？"
        split_user_msg = adapter.last_messages[0]["content"]
        assert split_user_msg == "这本书节奏最稀疏的是哪几章"
        assert adapter.call_count == 2

    def test_rewrite_succeeds_but_split_fails_keeps_rewrite(self) -> None:
        """改写成功、拆题挂了—— fallback 仍带回改写结果（检索还能用上）。"""
        adapter = _FakeAdapter(
            responses=[
                _rewrite_response("改写后的独立问题"),
                _FakeResponse(content=[_text_block("not json at all {{{")]),
            ]
        )
        history = [{"question": "上一问", "answer": "上一答"}]
        result = process_question(
            "这一残句问题", adapter, conversation_history=history
        )
        # 拆题 fallback 到原题，但 rewritten_question 保留改写结果
        assert result.subquestions == ["这一残句问题"]
        assert result.rewritten_question == "改写后的独立问题"
