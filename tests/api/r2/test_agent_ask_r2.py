"""POST ``/api/agent/ask`` r2 路径核心覆盖测试。

ADR-007 Sprint 6 切默认 r2 后，``tests/api/test_agent_ask.py`` 整套 22 个
测试仍按 r1 Anthropic ``content_blocks`` 形态写——靠 ``tests/api/conftest.py``
autouse 锁 r1 兜底跑。本文件是 r2 路径的等价测试：

- 父目录 conftest 锁 r1，子目录 conftest 强制覆盖为 r2
- LLM 桩响应改为 OpenAI ``choices[0].message.tool_calls`` + ``finish_reason``
  形态，由 ``loop_r2.AgentLoop`` 直接消费

第一波（commit ``2d96e90``）只放了 1 个 happy path 作范式模板。本轮（Sprint 6
QA 第二波）按同 pattern 补 6 个核心测试：

1. ``happy_path`` —— 1 轮 tool_calls + 1 轮 stop final answer（原范式）
2. ``stream_happy_path`` —— SSE 链路 r2 形态（commit ``f98fa78`` audit 证 SSE
   层 r1/r2 等价，桩只翻 LLM 调用）
3. ``rate_limited_429`` —— RateLimitedError 重试链耗尽返 429
4. ``max_iterations_504`` —— MaxIterationsExceeded 返 504
5. ``llm_format_error_502`` —— r2 自然形态是 tool_calls 数组；format error 触发
   条件是"finish_reason=stop 但 content JSON 缺 citations"（非 adapter 翻译错）
6. ``deepseek_custom_base_url_routed`` —— deepseek + 自定义 base_url 路由
   （OpenAI 兼容端点；minimax 弃用后的接管路径，OpenAI 形态桩通用）
7. ``stream_review_event_after_final_answer`` —— streaming 末尾 review event
   在 r2 路径下正常 emit（reviewer 调用走另一条 build_review_client 路径）
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bookscope.agent.errors import RateLimited
from bookscope.agent.tools.schemas import ChapterText, CharacterRef, ChunkMatch
from bookscope.api import create_app
from bookscope.api.book_sessions import get_book_session_store
from bookscope.api.dependencies import reset_book_session_store_for_tests
from bookscope.api.routes import agent as agent_route_module

# ---------------------------------------------------------------------------
# OpenAI 形态响应桩
# ---------------------------------------------------------------------------


class _R2Usage:
    """OpenAI ``usage`` 替身：``prompt_tokens`` / ``completion_tokens``。"""

    def __init__(self, prompt_tokens: int = 10, completion_tokens: int = 5) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _R2Function:
    """OpenAI ``tool_call.function`` 替身——name + arguments JSON 字符串。"""

    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _R2ToolCall:
    """OpenAI ``ChatCompletionMessageToolCall`` 替身——id + type + function。"""

    def __init__(self, tc_id: str, name: str, arguments: str) -> None:
        self.id = tc_id
        self.type = "function"
        self.function = _R2Function(name, arguments)


class _R2Message:
    """OpenAI ``ChatCompletionMessage`` 替身。

    含 tool_calls 时 content 通常为 None；纯文本回复时 tool_calls 为 None。
    """

    def __init__(
        self,
        *,
        content: str | None = None,
        tool_calls: list[_R2ToolCall] | None = None,
    ) -> None:
        self.role = "assistant"
        self.content = content
        self.tool_calls = tool_calls or None


class _R2Choice:
    def __init__(self, message: _R2Message, finish_reason: str) -> None:
        self.message = message
        self.finish_reason = finish_reason


class _R2Response:
    """OpenAI ``ChatCompletion`` 替身：choices + usage。"""

    def __init__(self, choices: list[_R2Choice]) -> None:
        self.choices = choices
        self.usage = _R2Usage()


def _tool_call_response(
    *, name: str, arguments: dict[str, Any], call_id: str = "call_001"
) -> _R2Response:
    """构造一轮 OpenAI 形态 tool_calls 响应（``finish_reason="tool_calls"``）。"""
    tc = _R2ToolCall(call_id, name, json.dumps(arguments, ensure_ascii=False))
    msg = _R2Message(content=None, tool_calls=[tc])
    return _R2Response([_R2Choice(msg, finish_reason="tool_calls")])


def _final_text_response(answer: str, citations: list[dict[str, Any]]) -> _R2Response:
    """构造一轮 OpenAI 形态 final answer 响应（``finish_reason="stop"``）。"""
    payload = json.dumps(
        {"answer": answer, "citations": citations}, ensure_ascii=False
    )
    msg = _R2Message(content=payload, tool_calls=None)
    return _R2Response([_R2Choice(msg, finish_reason="stop")])


# ---------------------------------------------------------------------------
# Fake adapter / backends / assembler
# ---------------------------------------------------------------------------


class _R2FakeAdapter:
    """OpenAI 形态 fake adapter——按队列依次吐 r2 response，或抛固定异常。

    两种模式：

    - 预置 response 序列：依次弹出
    - ``raise_exc=Exc()``：每次 ``messages_create`` 调用都抛同一异常，用来测
      重试链耗尽路径
    """

    def __init__(
        self,
        responses: list[_R2Response] | None = None,
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
            raise AssertionError("_R2FakeAdapter ran out of prepared responses")
        return self._responses.pop(0)


class _FakeSearchBackend:
    def retrieve(
        self,
        query: str,
        chapter_scope: tuple[int, int] | None,
        character_filter: list[str] | None,
        top_k: int,
    ) -> list[ChunkMatch]:
        return [
            ChunkMatch(
                chunk_id="r0-chunk-1",
                chapter=1,
                text="朱元璋称帝。",
                relevance_score=1.0,
                contains_characters=[],
                source_version="r0",
            )
        ]


class _FakeChapterBackend:
    def total_words(self, start: int, end: int) -> int:
        return 100

    def get_chapters(self, start: int, end: int) -> list[ChapterText]:
        return []


class _FakeCharactersBackend:
    def characters_in(self, chapter: int) -> list[CharacterRef]:
        return []


class _FakeAssembler:
    """ducktype 替身——只暴露 ``build_all``。"""

    def build_all(self) -> dict[str, Any]:
        return {
            "search": _FakeSearchBackend(),
            "chapter_range": _FakeChapterBackend(),
            "list_characters": _FakeCharactersBackend(),
        }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _disable_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """走完整 AgentLoop，避开 fast path 启发式分流。

    fast path 在通识题上只调 1 search + 1 LLM call，会撞掉本测试预置的
    两轮响应序列。fast path 自身在 ``tests/api/test_routes_agent.py``
    单独验证。
    """
    monkeypatch.setenv("BOOKSCOPE_FAST_PATH_DISABLED", "1")


@pytest.fixture(autouse=True)
def _disable_reviewer_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认让路由层 reviewer 失败 → ``review = None``。

    _R2FakeAdapter 响应队列没预留 reviewer 调用；让 reviewer 抛错被
    ``_try_review_or_none`` 吞掉，主 ask 行为不变。
    """
    monkeypatch.setattr(
        agent_route_module,
        "review_answer",
        lambda **_: (_ for _ in ()).throw(RuntimeError("reviewer disabled in test")),
    )


@pytest.fixture(autouse=True)
def _detach_session_storage() -> None:
    """解绑 JSONFileSessionStorage——``_FakeAssembler`` 不可序列化。"""
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture()
def session_id() -> str:
    return "test-r2-book-42"


@pytest.fixture()
def client_with_session(
    session_id: str,
) -> tuple[TestClient, _FakeAssembler]:
    """注册带 fake assembler 的 session 后给出 TestClient。"""
    app = create_app()
    store = get_book_session_store()
    store.clear()
    assembler = _FakeAssembler()
    store.register(session_id, assembler)  # type: ignore[arg-type]
    with TestClient(app) as c:
        yield c, assembler
    store.clear()


def _install_fake_client(
    monkeypatch: pytest.MonkeyPatch,
    fake_adapter: _R2FakeAdapter,
    *,
    expect_provider: str | None = None,
) -> list[str]:
    """把 ``build_llm_client`` 替换成返回预设 ``_R2FakeAdapter``。

    Returns:
        list 收集调用时的 provider，便于断言 provider 路由分支。
    """
    captured: list[str] = []

    def fake_build(request: Any) -> Any:
        captured.append(request.provider)
        if expect_provider is not None:
            assert request.provider == expect_provider
        return fake_adapter

    monkeypatch.setattr(agent_route_module, "build_llm_client", fake_build)
    return captured


# ---------------------------------------------------------------------------
# r2 happy path
# ---------------------------------------------------------------------------


def test_agent_ask_r2_happy_path(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 路径 happy path：1 轮 tool_calls + 1 轮 stop final answer。

    断言点：

    - HTTP 200
    - ``answer`` / ``citations`` 解析正确
    - ``protocol_version == "r2"`` —— 证明走的是 ``loop_r2.AgentLoop``
    - ``trace.outcome == "success"``
    - adapter 被调 2 次
    """
    client, _assembler = client_with_session
    fake = _R2FakeAdapter(
        [
            _tool_call_response(
                name="search_chunks",
                arguments={"query": "开国"},
                call_id="call_001",
            ),
            _final_text_response(
                "第一章讲开国。",
                [{"chapter": 1, "snippet": "朱元璋称帝。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "第一章讲了什么？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "第一章讲开国。"
    # WP1 起 citation 由系统比对原文后附加 verified / chunk_id / match_score / match_type；
    # snippet 与 fake search 返回的 chunk 文本一致 → verified=True、逐字命中 → match_type=quote
    assert body["citations"] == [
        {
            "chapter": 1,
            "snippet": "朱元璋称帝。",
            "verified": True,
            "chunk_id": "r0-chunk-1",
            "match_score": 1.0,
            "match_type": "quote",
        }
    ]
    assert body["book_session_id"] == session_id
    assert body["protocol_version"] == "r2", (
        f"r2 锁定下响应必须含 protocol_version='r2'，实际：{body.get('protocol_version')!r}"
    )
    assert "trace" in body and isinstance(body["trace"], dict)
    assert body["trace"]["outcome"] == "success"
    assert fake.call_count == 2, (
        f"r2 happy path 应调 adapter 2 次（1 tool + 1 final），实际 {fake.call_count}"
    )


# ---------------------------------------------------------------------------
# r2 SSE 流式 happy path
# ---------------------------------------------------------------------------


def _parse_sse_frames(raw: str) -> list[tuple[str, dict[str, Any]]]:
    """把 SSE 原始文本拆成 ``(event_type, data_dict)`` 序列。

    与 r1 ``test_agent_ask.py`` 同名工具同实现——SSE 帧格式在 r1/r2 间共享，
    audit 报告 ``docs/internal/audit/streaming-r2-compatibility.md`` 已证 SSE 层解耦。
    """
    frames: list[tuple[str, dict[str, Any]]] = []
    for chunk in raw.split("\n\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        event_type = ""
        data_lines: list[str] = []
        for line in chunk.split("\n"):
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_lines.append(line[len("data:") :].strip())
        if event_type and data_lines:
            data = json.loads("\n".join(data_lines))
            frames.append((event_type, data))
    return frames


def test_agent_ask_stream_happy_path_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 路径 SSE 流：iteration_start / tool_use / tool_result / final_answer。

    chapter-05 第七节"未来工作面"点名要做的——OpenAI streaming chunk 与
    Anthropic SSE event 不同，但 BookScope 自己 emit 的 ``LoopEvent`` 在 SSE
    层与 r1 等价（commit ``f98fa78`` audit 报告已证）。本测试只翻 LLM 调用桩，
    SSE 解析复用同一套 ``_parse_sse_frames``。

    断言点：

    - status 200 + ``text/event-stream``
    - 帧序列：``route_decision → iteration_start → tool_use → tool_result →
      iteration_start → final_answer``（与 r1 等价测试同序）
    - ``final_answer`` data 含 ``answer`` / ``citations`` / ``iterations == 2``
    """
    client, _ = client_with_session
    fake = _R2FakeAdapter(
        [
            _tool_call_response(
                name="search_chunks",
                arguments={"query": "开国"},
                call_id="call_001",
            ),
            _final_text_response(
                "第一章讲开国。",
                [{"chapter": 1, "snippet": "朱元璋称帝。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)

    with client.stream(
        "POST",
        "/api/agent/ask/stream",
        json={
            "question": "第一章讲了什么？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        raw = "".join(resp.iter_text())

    frames = _parse_sse_frames(raw)
    types_in_order = [t for t, _ in frames]
    assert types_in_order == [
        "route_decision",
        "iteration_start",
        "tool_use",
        "tool_result",
        "iteration_start",
        "final_answer",
    ], f"r2 SSE 帧序列与 r1 等价测试不一致：{types_in_order}"
    final_data = frames[-1][1]
    assert final_data["answer"] == "第一章讲开国。"
    # WP1：SSE final_answer 帧里的 citation 同样带系统校验字段
    assert final_data["citations"] == [
        {
            "chapter": 1,
            "snippet": "朱元璋称帝。",
            "verified": True,
            "chunk_id": "r0-chunk-1",
            "match_score": 1.0,
            "match_type": "quote",
        }
    ]
    assert final_data["iterations"] == 2


# ---------------------------------------------------------------------------
# r2 错误路径：RateLimited / MaxIterationsExceeded / LLMFormatError
# ---------------------------------------------------------------------------


@pytest.fixture()
def _no_real_sleep_r2(monkeypatch: pytest.MonkeyPatch) -> None:
    """把 ``loop_r2.time.sleep`` patch 成 no-op。

    RateLimited 重试链默认退避 1s→2s→4s 累计 7s，会把测试拖慢；patch 路径与
    r1 ``loop.py`` 不同（``bookscope.agent.loop_r2.time.sleep`` vs
    ``bookscope.agent.loop.time.sleep``）。
    """

    def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("bookscope.agent.loop_r2.time.sleep", _no_sleep)


def test_agent_ask_rate_limited_429_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
    _no_real_sleep_r2: None,
) -> None:
    """r2 路径 adapter 全程抛 RateLimited → 重试上限耗尽 → HTTP 429。

    默认 ``rate_limit_retry_limit=3``：原始 1 次 + 重试 3 次 = 4 次调用都失败
    后向上抛。退避 sleep 已 patch 成 no-op。
    """
    client, _ = client_with_session
    fake = _R2FakeAdapter(raise_exc=RateLimited("429 Too Many Requests"))
    _install_fake_client(monkeypatch, fake)

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "分析这道题",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 429, resp.text
    assert resp.json()["detail"]["error_type"] == "RateLimited"
    assert fake.call_count == 4, (
        f"r2 RateLimited 应调 adapter 4 次（1 + 3 retries），实际 {fake.call_count}"
    )


def test_agent_ask_max_iterations_504_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 路径 adapter 永远返 tool_calls → 不收敛 → HTTP 504。

    准备 30 个 tool_calls 响应足够触发 ``max_iterations`` 上限。
    response body 应含 ``details.max_iterations`` 字段。
    """
    client, _ = client_with_session
    tool_resp = _tool_call_response(
        name="search_chunks",
        arguments={"query": "x"},
        call_id="call_001",
    )
    fake = _R2FakeAdapter([tool_resp for _ in range(30)])
    _install_fake_client(monkeypatch, fake)

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "分析这道题",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 504, resp.text
    body = resp.json()
    assert body["detail"]["error_type"] == "MaxIterationsExceeded"
    assert isinstance(body["detail"]["details"]["max_iterations"], int)


def test_agent_ask_llm_format_error_502_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 路径 LLM 在 ``finish_reason=stop`` 给出缺 citations 的 JSON → 502。

    r2 与 r1 触发条件的差异：r2 自然形态下 tool_calls 在数组里，"missing
    arguments" 是 LLM 字面输出错；这里测的是 final answer 解析失败链——
    finish_reason=stop 走文本分支，``_parse_final_answer`` 检出缺 citations
    抛 ``LLMFormatError``，``format_retry_limit=1`` 用完后翻 502。

    桩两轮 ``stop`` + 缺 citations，触发 1 次原始解析失败 + 1 次重试解析失败 →
    向上抛 LLMFormatError → 502。
    """
    client, _ = client_with_session
    bad_payload_1 = json.dumps({"answer": "缺 citations 字段"}, ensure_ascii=False)
    bad_payload_2 = json.dumps({"answer": "仍然没有 citations"}, ensure_ascii=False)
    fake = _R2FakeAdapter(
        [
            _R2Response(
                [
                    _R2Choice(
                        _R2Message(content=bad_payload_1, tool_calls=None),
                        finish_reason="stop",
                    )
                ]
            ),
            _R2Response(
                [
                    _R2Choice(
                        _R2Message(content=bad_payload_2, tool_calls=None),
                        finish_reason="stop",
                    )
                ]
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "分析这道题",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 502, resp.text
    assert resp.json()["detail"]["error_type"] == "LLMFormatError"


# ---------------------------------------------------------------------------
# provider 路由：deepseek + 自定义 base_url（OpenAI 兼容端点）
# ---------------------------------------------------------------------------


def test_agent_ask_deepseek_custom_base_url_routed_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 路径 provider=deepseek + 自定义 base_url 路由：``build_llm_client`` 收到 'deepseek'。

    r2 主格式是 OpenAI function calling；走代理 / 私有部署 / 其他 OpenAI 兼容
    endpoint 时由 deepseek + base_url 覆盖承载（minimax 弃用后的接管路径）。
    """
    client, _ = client_with_session
    fake = _R2FakeAdapter(
        [
            _final_text_response(
                "deepseek 直接作答。",
                [{"chapter": 1, "snippet": "原文片段。"}],
            )
        ]
    )
    captured = _install_fake_client(
        monkeypatch,
        fake,
        expect_provider="deepseek",
    )
    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "谁是主角",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
            "base_url": "https://openai-compat.example.com/v1",
        },
    )
    assert resp.status_code == 200, resp.text
    assert captured == ["deepseek"]
    body = resp.json()
    assert body["protocol_version"] == "r2"


# ---------------------------------------------------------------------------
# r2 SSE 流式 + reviewer event
# ---------------------------------------------------------------------------


def test_agent_ask_stream_does_not_emit_review_event_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """WP-reviewcard-userside-removal：SSE 流不再 emit ``review`` 事件。

    评分卡已从用户界面下线——reviewer 评分回路保留（开发期 batch / 日志还用），
    但不再通过 SSE 推给用户。本测试把 ``review_answer`` monkeypatch 成会返桩
    结果（即 reviewer 跑通），验证流里**仍然没有** ``review`` 帧、但 ``final_answer``
    照常给出。这是 review-SSE 边界切断后的回归护栏。
    """
    client, _ = client_with_session
    fake = _R2FakeAdapter(
        [
            _tool_call_response(
                name="search_chunks",
                arguments={"query": "x"},
                call_id="call_001",
            ),
            _final_text_response(
                "诊断答复。",
                [{"chapter": 1, "snippet": "片段。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)

    raw_review = {
        "scores": {
            "structural_judgment": 4,
            "evidence_density": 4,
            "honesty": 4,
            "actionability": 4,
            "cross_chapter_coherence": 4,
        },
        "per_dimension_comment": {
            "structural_judgment": "判断清晰",
            "evidence_density": "证据集中表层",
            "honesty": "敢说",
            "actionability": "有指引",
            "cross_chapter_coherence": "跨章节",
        },
        "overall": "整体可用。",
        "top_issues": ["证据偏表层"],
        "single_most_valuable_improvement": "补隐喻级伏笔。",
    }
    review_calls: list[dict] = []

    def _spy_review(**kwargs):
        review_calls.append(kwargs)
        return raw_review

    monkeypatch.setattr(agent_route_module, "review_answer", _spy_review)

    with client.stream(
        "POST",
        "/api/agent/ask/stream",
        json={
            "question": "诊断题：铺垫连贯吗？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    ) as resp:
        assert resp.status_code == 200
        raw = "".join(resp.iter_text())

    frames = _parse_sse_frames(raw)
    types_in_order = [t for t, _ in frames]
    # final_answer 照常给出
    assert "final_answer" in types_in_order
    # review 事件不再进用户 SSE 流
    assert "review" not in types_in_order, (
        f"review event 不应再出现在用户 SSE 流里；实际帧序列：{types_in_order}"
    )
    # 但 reviewer 回路本身仍跑（开发期 batch / 日志用）——确认被调用了一次
    assert len(review_calls) == 1, "reviewer 评分回路应保留并被调用一次"
