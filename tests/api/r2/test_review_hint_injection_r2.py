"""``previous_review`` 注入 system_prompt 端到端 r2 等价测试。

源文件：``tests/api/test_review_hint_injection.py``（r1 形态，18 个测试）。
本文件覆盖其中 11 个走 HTTP 路由的测试翻 r2 形态——剩下 7 个元测试（直接
调 ``_format_dimension_comments`` / ``_format_top_issues`` /
``_resolve_extra_system_prompt`` 等 helper）r1/r2 共享同一实现，复制无价值：

跳过的 7 个元测试：
- ``test_format_dimension_comments_fixed_order``
- ``test_format_dimension_comments_skips_missing_and_empty``
- ``test_format_dimension_comments_all_empty_returns_fallback``
- ``test_format_top_issues_empty_returns_fallback``
- ``test_format_top_issues_bullets``
- ``test_resolve_extra_system_prompt_none_when_no_review``
- ``test_resolve_extra_system_prompt_exception_path_returns_none``

r2 vs r1 的核心差异：

- LLM 桩响应形态：r2 用 OpenAI ``choices`` + ``finish_reason``，由
  ``loop_r2.AgentLoop`` 直接消费。共用桩在 ``tests/api/r2/_mocks.py``。
- system_prompt 注入路径：``_resolve_extra_system_prompt`` 在路由层把
  addendum 拼好后传给 ``AgentLoopCls(... extra_system_prompt=...)``——这条
  注入语义在 r1 / r2 完全等价（``AgentLoop`` / ``loop_r2.AgentLoop`` 构造
  签名相同）。本测试用 ``R2FakeAdapter(record_system=True)`` 捕获每次
  ``messages_create`` 收到的 ``system`` kw，断言 addendum 文本片段。
- reviewer 没参与：``previous_review`` 是上一次 reviewer 的输出 dict，
  本轮 generator 消费它做改进——本轮自己**不再调** reviewer。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bookscope.agent.tools.schemas import ChapterText, CharacterRef, ChunkMatch
from bookscope.api import create_app
from bookscope.api.book_sessions import get_book_session_store
from bookscope.api.dependencies import reset_book_session_store_for_tests
from bookscope.api.routes import agent as agent_route_module

from ._mocks import R2FakeAdapter, r2_final_text_response, r2_tool_call_response

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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _two_round_responses() -> list[Any]:
    """1 轮 tool_calls + 1 轮 final answer——agent_loop 主路径最简序列。"""
    return [
        r2_tool_call_response(name="search_chunks", arguments={"query": "结构"}),
        r2_final_text_response(
            "重答。",
            [{"chapter": 1, "snippet": "朱元璋称帝。"}],
        ),
    ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _disable_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """走完整 ``loop_r2.AgentLoop``——稳定可断言 system_prompt。"""
    monkeypatch.setenv("BOOKSCOPE_FAST_PATH_DISABLED", "1")


@pytest.fixture(autouse=True)
def _disable_reviewer_in_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    """让路由层 reviewer 失败 → ``review = None``——测试不需要二次 review。"""
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
    return "test-review-hint-injection-r2"


@pytest.fixture()
def client_and_adapter(
    session_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, R2FakeAdapter]:
    """构造 TestClient + 注册 session + 安装记录 system_prompt 的 fake adapter。"""
    app = create_app()
    store = get_book_session_store()
    store.clear()
    store.register(session_id, _FakeAssembler())  # type: ignore[arg-type]

    fake = R2FakeAdapter(_two_round_responses(), record_system=True)
    monkeypatch.setattr(agent_route_module, "build_llm_client", lambda _req: fake)

    with TestClient(app) as c:
        yield c, fake
    store.clear()


def _post_ask(
    client: TestClient,
    session_id: str,
    *,
    previous_review: dict[str, Any] | None = None,
) -> Any:
    body: dict[str, Any] = {
        "question": "第一章的结构判断是什么？",
        "book_session_id": session_id,
        "provider": "deepseek",
        "api_key": "sk-fake-key-1234",
    }
    if previous_review is not None:
        body["previous_review"] = previous_review
    return client.post("/api/agent/ask", json=body)


# ---------------------------------------------------------------------------
# Tests · 端到端 ask
# ---------------------------------------------------------------------------


def test_ask_without_previous_review_no_addendum_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """默认无 previous_review 时 system_prompt 不含 addendum 段。"""
    client, fake = client_and_adapter
    resp = _post_ask(client, session_id)
    assert resp.status_code == 200, resp.text
    assert fake.call_count >= 1
    for sp in fake.system_prompts:
        assert "上一次回答这道题" not in sp
        assert "reviewer 评分" not in sp


def test_ask_with_previous_review_addendum_in_prompt_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """含 previous_review 时 system_prompt 末尾有 addendum 段。"""
    client, fake = client_and_adapter
    resp = _post_ask(
        client,
        session_id,
        previous_review={
            "total_score": 14,
            "dimension_comments": {
                "structural_judgment": "判断模糊",
                "evidence_density": "证据稀",
                "honesty": "诚实可",
                "actionability": "可操作差",
                "cross_chapter_coherence": "跨章节缺",
            },
            "top_issues": ["缺铺垫举证", "结构判断绕"],
        },
    )
    assert resp.status_code == 200, resp.text
    sp = fake.system_prompts[0]
    assert "上一次回答这道题" in sp
    assert "reviewer 评分 14/25" in sp
    assert sp.rfind("上一次回答这道题") > 0


def test_addendum_includes_score_and_comments_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """addendum 含总分 + 5 维评语 + top_issues。"""
    client, fake = client_and_adapter
    _post_ask(
        client,
        session_id,
        previous_review={
            "total_score": 11,
            "dimension_comments": {
                "structural_judgment": "判断弱在 X",
                "evidence_density": "原文证据少",
                "honesty": "保留够",
                "actionability": "操作不具体",
                "cross_chapter_coherence": "只看第一章",
            },
            "top_issues": ["铺垫举证不够", "节奏判断绕了一圈没落地"],
        },
    )
    sp = fake.system_prompts[0]
    assert "11/25" in sp
    assert "判断弱在 X" in sp
    assert "原文证据少" in sp
    assert "保留够" in sp
    assert "操作不具体" in sp
    assert "只看第一章" in sp
    assert "铺垫举证不够" in sp
    assert "节奏判断绕了一圈没落地" in sp


def test_addendum_dimension_order_fixed_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """5 维顺序按 rubric_v1：structural_judgment 在前。"""
    client, fake = client_and_adapter
    _post_ask(
        client,
        session_id,
        previous_review={
            "total_score": 20,
            "dimension_comments": {
                "cross_chapter_coherence": "C",
                "structural_judgment": "S",
                "honesty": "H",
                "actionability": "A",
                "evidence_density": "E",
            },
            "top_issues": [],
        },
    )
    sp = fake.system_prompts[0]
    p_s = sp.find("判断而非复述：S")
    p_e = sp.find("证据厚度：E")
    p_h = sp.find("诚实度：H")
    p_a = sp.find("可操作：A")
    p_c = sp.find("跨章节视野：C")
    assert -1 < p_s < p_e < p_h < p_a < p_c


def test_addendum_chinese_labels_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """addendum 用中文维度标签——不暴露英文 key。"""
    client, fake = client_and_adapter
    _post_ask(
        client,
        session_id,
        previous_review={
            "total_score": 18,
            "dimension_comments": {
                "structural_judgment": "x",
                "evidence_density": "x",
                "honesty": "x",
                "actionability": "x",
                "cross_chapter_coherence": "x",
            },
            "top_issues": [],
        },
    )
    sp = fake.system_prompts[0]
    assert "判断而非复述" in sp
    assert "证据厚度" in sp
    assert "诚实度" in sp
    assert "可操作" in sp
    assert "跨章节视野" in sp
    addendum_start = sp.find("上一次回答这道题")
    assert addendum_start > 0
    addendum = sp[addendum_start:]
    assert "structural_judgment" not in addendum
    assert "cross_chapter_coherence" not in addendum


def test_addendum_handles_missing_dimensions_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """dimension_comments 缺一两个维度时——缺的整行跳过，剩的正常拼。"""
    client, fake = client_and_adapter
    _post_ask(
        client,
        session_id,
        previous_review={
            "total_score": 12,
            "dimension_comments": {
                "structural_judgment": "判断弱",
            },
            "top_issues": ["X"],
        },
    )
    sp = fake.system_prompts[0]
    assert "判断而非复述：判断弱" in sp
    assert "证据厚度：" not in sp
    assert "诚实度：" not in sp


def test_addendum_handles_all_dimensions_missing_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """dimension_comments 完全为空——"（无 5 维评语）"兜底。"""
    client, fake = client_and_adapter
    _post_ask(
        client,
        session_id,
        previous_review={
            "total_score": 0,
            "dimension_comments": {},
            "top_issues": ["X"],
        },
    )
    sp = fake.system_prompts[0]
    assert "（无 5 维评语）" in sp


def test_addendum_handles_empty_top_issues_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """top_issues 空——"（无）"兜底。"""
    client, fake = client_and_adapter
    _post_ask(
        client,
        session_id,
        previous_review={
            "total_score": 22,
            "dimension_comments": {"structural_judgment": "好"},
            "top_issues": [],
        },
    )
    sp = fake.system_prompts[0]
    assert "主要问题：\n（无）" in sp


def test_previous_review_invalid_format_returns_422_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """``previous_review`` 含非法字段——Pydantic 422，不进 routes 逻辑。

    硬约束"格式异常 fallback 跳过注入不崩"是指 routes 内部 helper 层
    fallback；Pydantic 验证层异常该 422 还是 422，不放进去再降级。
    """
    client, _ = client_and_adapter
    resp = _post_ask(
        client,
        session_id,
        previous_review={
            "total_score": 99,  # ge=0, le=25 → 422
            "dimension_comments": {},
            "top_issues": [],
        },
    )
    assert resp.status_code == 422


def test_previous_review_top_issues_too_long_returns_422_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """``top_issues`` 超过 5 条直接 422。"""
    client, _ = client_and_adapter
    resp = _post_ask(
        client,
        session_id,
        previous_review={
            "total_score": 10,
            "dimension_comments": {},
            "top_issues": ["a", "b", "c", "d", "e", "f"],
        },
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Tests · stream 端点同步支持
# ---------------------------------------------------------------------------


def test_stream_endpoint_also_supports_previous_review_r2(
    client_and_adapter: tuple[TestClient, R2FakeAdapter],
    session_id: str,
) -> None:
    """``/api/agent/ask/stream`` 也走 ``_resolve_extra_system_prompt``。

    监听 stream 端点跑完一次，检查 fake adapter 收到的 ``system_prompt``
    是否带 addendum——r2 路径下 ``loop_r2.AgentLoop`` 同样消费
    ``extra_system_prompt``。
    """
    client, fake = client_and_adapter
    body = {
        "question": "第一章的结构判断是什么？",
        "book_session_id": session_id,
        "provider": "deepseek",
        "api_key": "sk-fake-key-1234",
        "previous_review": {
            "total_score": 13,
            "dimension_comments": {"structural_judgment": "判断模糊"},
            "top_issues": ["缺铺垫举证"],
        },
    }
    with client.stream("POST", "/api/agent/ask/stream", json=body) as resp:
        assert resp.status_code == 200
        for _ in resp.iter_text():
            pass
    assert fake.call_count >= 1
    sp = fake.system_prompts[0]
    assert "上一次回答这道题" in sp
    assert "13/25" in sp
    assert "判断模糊" in sp
    assert "缺铺垫举证" in sp
