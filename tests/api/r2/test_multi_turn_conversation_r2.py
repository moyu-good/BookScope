"""多轮对话端到端集成测试（ADR-009 Phase 1a，r2 形态）。

覆盖 D-1 / D-3 / D-4：

- conversation_id 回显 + 新对话生成 id
- turn_index 从 1 起、追问递增
- 第二问续上 conversation_id 时，上一轮的答案 + 引用进了 system **可变段**
  （前情提要注入）
- **缓存前缀守护**：前情提要绝不进 fixed_system 固定前缀——两轮发出的
  fixed_system 段逐字相同（缓存命中前提）
- 零回归：不带 conversation_id 时响应仍带 conversation_id/turn_index，
  且行为与现状一致（system 不含前情提要）

system_prompt 捕获走 ``R2FakeAdapter(record_system=True)``——loop_r2 把
fixed_system + addendum + 前情提要拼成 ``system`` kw 传给 adapter。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from bookscope.agent.tools.schemas import ChapterText, CharacterRef, ChunkMatch
from bookscope.api import create_app
from bookscope.api.book_sessions import get_book_session_store
from bookscope.api.conversation_store import JSONFileConversationStore
from bookscope.api.dependencies import (
    get_conversation_store,
    reset_book_session_store_for_tests,
)
from bookscope.api.routes import agent as agent_route_module

from ._mocks import (
    R2FakeAdapter,
    r2_final_text_response,
    r2_raw_text_response,
    r2_tool_call_response,
)

# 前情提要注入段的锚点文案（与 routes/agent.py 的 _build_conversation_recap 一致）
_RECAP_MARKER = "【前情提要】"

# 追问改写 prompt（v2）的锚点——adapter 凭它把"改写调用"与"loop 调用"分开
_REWRITE_PROMPT_MARKER = "追问改写助手"


class _RewriteAwareAdapter(R2FakeAdapter):
    """在 R2FakeAdapter 之上识别"追问改写"调用（ADR-009 Phase 1b）。

    指代消解的改写 LLM 调用与 agent loop 的调用共用同一个 client。改写
    调用的 system 是 v2 改写 prompt（含 ``追问改写助手`` 锚点）；本 adapter
    碰到这种调用就返回一个固定的改写结果，**不消耗** loop 的 response 队列，
    让原有 Phase 1a 断言（loop 拿满 two_round 序列）继续成立。
    """

    def __init__(self, *args: Any, rewrite_text: str = "改写后的独立问题", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.rewrite_text = rewrite_text
        self.rewrite_calls = 0
        # loop 调用（非改写）看到的 user message——按调用顺序记下，
        # 用来断言进 loop 的是改写后的独立问题。
        self.loop_user_messages: list[str] = []

    def messages_create(self, **kwargs: Any) -> Any:
        system = str(kwargs.get("system", ""))
        if _REWRITE_PROMPT_MARKER in system:
            self.rewrite_calls += 1
            return r2_raw_text_response(self.rewrite_text)
        messages = kwargs.get("messages") or []
        for msg in messages:
            if isinstance(msg, dict) and msg.get("role") == "user":
                self.loop_user_messages.append(str(msg.get("content", "")))
                break
        return super().messages_create(**kwargs)


# ---------------------------------------------------------------------------
# Fake backends / assembler
# ---------------------------------------------------------------------------


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
    def build_all(self) -> dict[str, Any]:
        return {
            "search": _FakeSearchBackend(),
            "chapter_range": _FakeChapterBackend(),
            "list_characters": _FakeCharactersBackend(),
        }


def _two_round_responses() -> list[Any]:
    """1 轮 tool_calls + 1 轮 final answer——agent_loop 主路径最简序列。"""
    return [
        r2_tool_call_response(name="search_chunks", arguments={"query": "结构"}),
        r2_final_text_response(
            "第一问的答案：节奏前密后疏。",
            [{"chapter": 1, "snippet": "朱元璋称帝。", "chunk_id": "r0-chunk-1"}],
        ),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _disable_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """走完整 loop_r2.AgentLoop——稳定可断言 system_prompt。"""
    monkeypatch.setenv("BOOKSCOPE_FAST_PATH_DISABLED", "1")


@pytest.fixture(autouse=True)
def _disable_reviewer_in_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_route_module,
        "review_answer",
        lambda **_: (_ for _ in ()).throw(RuntimeError("reviewer disabled in test")),
    )


@pytest.fixture(autouse=True)
def _detach_session_storage() -> None:
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture()
def session_id() -> str:
    return "test-multi-turn-r2"


@pytest.fixture()
def conv_store(tmp_path: Path) -> JSONFileConversationStore:
    return JSONFileConversationStore(root=tmp_path)


@pytest.fixture()
def make_client(
    session_id: str,
    conv_store: JSONFileConversationStore,
    monkeypatch: pytest.MonkeyPatch,
):
    """工厂：每次造一个新 TestClient + 装一个吐 two_round 序列的 fake adapter。

    每次 ask 用一个新 adapter（按队列吐 response），但共用同一个 conv_store
    （tmp_path），所以多轮能续上。返回 ``(client, adapter_holder)``，
    adapter_holder 是个 list，记下每次 ask 用的 adapter 供断言 system_prompt。
    """
    app = create_app()
    app.dependency_overrides[get_conversation_store] = lambda: conv_store
    store = get_book_session_store()
    store.clear()
    store.register(session_id, _FakeAssembler())  # type: ignore[arg-type]

    adapters: list[R2FakeAdapter] = []

    def _next_adapter(_req: Any) -> R2FakeAdapter:
        fake = _RewriteAwareAdapter(_two_round_responses(), record_system=True)
        adapters.append(fake)
        return fake

    monkeypatch.setattr(agent_route_module, "build_llm_client", _next_adapter)

    client = TestClient(app)
    yield client, adapters
    store.clear()
    app.dependency_overrides.clear()


def _post_ask(
    client: TestClient,
    session_id: str,
    *,
    question: str = "第一章的结构判断是什么？",
    conversation_id: str | None = None,
) -> Any:
    body: dict[str, Any] = {
        "question": question,
        "book_session_id": session_id,
        "provider": "deepseek",
        "api_key": "sk-fake-key-1234",
    }
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return client.post("/api/agent/ask", json=body)


# ---------------------------------------------------------------------------
# Tests · conversation_id / turn_index 契约
# ---------------------------------------------------------------------------


def test_new_conversation_echoes_id_and_turn_one(make_client, session_id: str) -> None:
    """不带 conversation_id：服务端生成 id 回显，turn_index=1。"""
    client, _ = make_client
    resp = _post_ask(client, session_id)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["conversation_id"]  # 非空
    assert body["turn_index"] == 1


def test_follow_up_increments_turn_index(make_client, session_id: str) -> None:
    """续上同一 conversation_id：turn_index 递增、id 原样回显。"""
    client, _ = make_client
    r1 = _post_ask(client, session_id, question="节奏前密后疏吗？")
    conv_id = r1.json()["conversation_id"]
    assert r1.json()["turn_index"] == 1

    r2 = _post_ask(
        client, session_id, question="具体哪几章最稀？", conversation_id=conv_id
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["conversation_id"] == conv_id  # 回显同一 id
    assert r2.json()["turn_index"] == 2

    r3 = _post_ask(
        client, session_id, question="第 40 章后加个事件行吗？", conversation_id=conv_id
    )
    assert r3.json()["turn_index"] == 3


def test_unknown_conversation_id_falls_back_to_new(
    make_client, session_id: str
) -> None:
    """续不上的 id（不存在）兜底当新对话：turn_index=1 + 换了个新 id。"""
    client, _ = make_client
    resp = _post_ask(
        client, session_id, conversation_id="no-such-conversation-id"
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["turn_index"] == 1
    assert body["conversation_id"] != "no-such-conversation-id"


# ---------------------------------------------------------------------------
# Tests · 前情提要注入
# ---------------------------------------------------------------------------


def test_first_turn_has_no_recap(make_client, session_id: str) -> None:
    """第一问没有上一轮——system 不含前情提要段。"""
    client, adapters = make_client
    _post_ask(client, session_id)
    sp = adapters[0].system_prompts[0]
    assert _RECAP_MARKER not in sp


def test_follow_up_injects_previous_answer_and_citations(
    make_client, session_id: str
) -> None:
    """第二问续上时，上一轮的答案 + 引用进了 system 前情提要段。"""
    client, adapters = make_client
    r1 = _post_ask(client, session_id, question="节奏前密后疏吗？")
    conv_id = r1.json()["conversation_id"]

    _post_ask(
        client, session_id, question="具体哪几章最稀？", conversation_id=conv_id
    )
    # 第二次 ask 用的是 adapters[1]
    sp = adapters[1].system_prompts[0]
    assert _RECAP_MARKER in sp
    # 上一轮的答案进了前情提要
    assert "第一问的答案：节奏前密后疏。" in sp
    # 上一轮的引用片段也进了
    assert "朱元璋称帝。" in sp
    # 上一问的题面也在
    assert "节奏前密后疏吗？" in sp


def test_recap_goes_after_fixed_prefix_not_into_it(
    make_client, session_id: str
) -> None:
    """缓存前缀守护：前情提要在 system 末尾可变段，不在 fixed_system 固定前缀。

    判定：第二问的 system 里，前情提要锚点出现在 citation_format_hint 之后
    （固定前缀 = base_prompt + citation_hint，前情提要必须在它之后）。
    """
    client, adapters = make_client
    r1 = _post_ask(client, session_id, question="节奏前密后疏吗？")
    conv_id = r1.json()["conversation_id"]
    _post_ask(
        client, session_id, question="哪几章最稀？", conversation_id=conv_id
    )

    sp = adapters[1].system_prompts[0]
    recap_pos = sp.find(_RECAP_MARKER)
    assert recap_pos > 0
    # 固定前缀的尾部锚点：citation_format_hint 里的内容应在前情提要之前。
    # 用 "---" 分隔符 + 前情提要标记的相对位置间接确认：前情提要是最后一段。
    # 直接验证：前情提要之前的内容里不含第二问的题面（题面在 user message）。
    prefix = sp[:recap_pos]
    assert "哪几章最稀？" not in prefix


def test_fixed_prefix_identical_across_turns(make_client, session_id: str) -> None:
    """缓存命中前提：第一问与第二问的 fixed_system 固定前缀逐字相同。

    fixed_system = system 去掉末尾的前情提要段。第二问比第一问只多了前情
    提要这一段可变内容——把它切掉后，两轮的固定前缀必须逐字一致。
    """
    client, adapters = make_client
    r1 = _post_ask(client, session_id, question="节奏前密后疏吗？")
    conv_id = r1.json()["conversation_id"]
    _post_ask(
        client, session_id, question="哪几章最稀？", conversation_id=conv_id
    )

    sp1 = adapters[0].system_prompts[0]  # 第一问 system（无前情提要）
    sp2 = adapters[1].system_prompts[0]  # 第二问 system（含前情提要）

    # 第二问把前情提要段切掉后，应与第一问的 system 逐字相同。
    # 前情提要前面带了 "\n\n---\n" 分隔；找到 "---" 边界做精确切割。
    sep = "\n\n---\n" + _RECAP_MARKER
    sep_pos = sp2.find(sep)
    assert sep_pos > 0, "前情提要应以 '\\n\\n---\\n' 分隔接在固定段之后"
    sp2_fixed = sp2[:sep_pos]
    assert sp2_fixed == sp1


# ---------------------------------------------------------------------------
# Tests · 零回归（D-4 第 4 条）
# ---------------------------------------------------------------------------


def test_trace_carries_conversation_fields(make_client, session_id: str) -> None:
    """trace 里盖上了 conversation_id / turn_index（测量仪器）。"""
    client, _ = make_client
    resp = _post_ask(client, session_id)
    body = resp.json()
    trace = body["trace"]
    assert trace["conversation_id"] == body["conversation_id"]
    assert trace["turn_index"] == 1


# ---------------------------------------------------------------------------
# Tests · 指代消解（ADR-009 Phase 1b，D-2）
# ---------------------------------------------------------------------------


def test_first_turn_no_rewrite_call(make_client, session_id: str) -> None:
    """新对话第一问没有历史—— 不触发改写调用（零回归）。"""
    client, adapters = make_client
    _post_ask(client, session_id, question="节奏前密后疏吗？")
    assert adapters[0].rewrite_calls == 0
    # loop 收到的就是原题（loop 多次调用都带同一条 user message）
    assert all(m == "节奏前密后疏吗？" for m in adapters[0].loop_user_messages)
    assert adapters[0].loop_user_messages  # 至少 emit 过一次


def test_follow_up_feeds_rewritten_question_to_loop(
    make_client, session_id: str
) -> None:
    """续上对话的追问—— 改写后的独立问题进 loop（喂给检索/路由）。"""
    client, adapters = make_client
    r1 = _post_ask(client, session_id, question="节奏前密后疏吗？")
    conv_id = r1.json()["conversation_id"]

    _post_ask(
        client, session_id, question="具体哪几章最稀？", conversation_id=conv_id
    )
    # 第二次 ask 用 adapters[1]：先改写一次，loop 收到的是改写版而非残句
    assert adapters[1].rewrite_calls == 1
    assert adapters[1].loop_user_messages  # loop 跑过
    assert all(m == "改写后的独立问题" for m in adapters[1].loop_user_messages)
    assert "具体哪几章最稀？" not in adapters[1].loop_user_messages


def test_follow_up_persists_rewritten_question(
    make_client, session_id: str, conv_store: JSONFileConversationStore
) -> None:
    """改写结果存进 conversation_store 的 rewritten_question 字段。"""
    client, _ = make_client
    r1 = _post_ask(client, session_id, question="节奏前密后疏吗？")
    conv_id = r1.json()["conversation_id"]
    _post_ask(
        client, session_id, question="具体哪几章最稀？", conversation_id=conv_id
    )

    turns = conv_store.get_turns(session_id, conv_id)
    # 第一轮没历史—— rewritten_question 留空
    assert turns[0]["question"] == "节奏前密后疏吗？"
    assert turns[0]["rewritten_question"] == ""
    # 第二轮是追问—— 原题存 question，改写版存 rewritten_question
    assert turns[1]["question"] == "具体哪几章最稀？"
    assert turns[1]["rewritten_question"] == "改写后的独立问题"


def test_unknown_conversation_id_no_rewrite(make_client, session_id: str) -> None:
    """续不上的 id 兜底当新对话—— 没历史所以不改写。"""
    client, adapters = make_client
    _post_ask(client, session_id, conversation_id="no-such-conversation-id")
    assert adapters[0].rewrite_calls == 0
