"""POST ``/api/agent/ask`` 题型路由 + reviewer 集成 r2 等价测试。

源文件：``tests/api/test_routes_agent.py``（r1 形态，9 个测试）。本文件把
9 个全部翻成 r2（OpenAI ``choices`` / ``finish_reason`` / ``message.tool_calls``）
形态——fast_path 启发式 / 诊断题走完整 agent_loop / env disable / 4 个
reviewer variant / fast_path 失败回退。

r2 vs r1 差异点：

- LLM 桩响应形态：r1 用 Anthropic ``content_blocks`` + ``stop_reason``；r2
  用 OpenAI ``choices[0].message`` + ``finish_reason``。共用桩在
  ``tests/api/r2/_mocks.py``。
- reviewer 路径：``review_answer`` 在路由层是被 monkeypatch 整个替换的——
  reviewer 自己内部用啥 protocol 跟主 ask 的 generator 解耦，所以 reviewer
  桩与 r1 共用（``_stub_reviewer_returning`` / ``_stub_reviewer_raising``
  直接返 dict / 抛 Exception，不经 LLM 调用）。
- fast_path：``run_fast_path`` 在 r2 下与 r1 共用同一段代码（fast_path 不走
  ``loop_r2.AgentLoop``，自己直接调一次 LLM 解析 JSON）——fast_path 桩响应
  形态仍是 OpenAI ``choices`` + 文本 content。

reviewer helper（``_good_review_dict`` / ``_stub_reviewer_*``）与 r1 同实现，
本文件局部复制——reviewer 形态是 5 维 dict，与 protocol 无关。
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from bookscope.agent.errors import ProviderUnavailable
from bookscope.agent.tools.schemas import ChapterText, CharacterRef, ChunkMatch
from bookscope.api import create_app
from bookscope.api.book_sessions import get_book_session_store
from bookscope.api.dependencies import reset_book_session_store_for_tests
from bookscope.api.routes import agent as agent_route_module

from ._mocks import (
    R2FakeAdapter,
    r2_final_text_response,
    r2_raw_text_response,
    r2_tool_call_response,
)

# ---------------------------------------------------------------------------
# Fake backends / assembler（与 r1 等价测试形态相同，r1/r2 不区分）
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
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _detach_storage_and_enable_fast_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """每用例前清 store；显式取消 ``BOOKSCOPE_FAST_PATH_DISABLED`` 让启发式生效。"""
    monkeypatch.delenv("BOOKSCOPE_FAST_PATH_DISABLED", raising=False)
    reset_book_session_store_for_tests()
    yield
    reset_book_session_store_for_tests()


@pytest.fixture(autouse=True)
def _disable_reviewer_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认让路由层 reviewer 失败 → ``review = None``。

    各测试预置的 R2FakeAdapter response 序列没预留 reviewer 调用；让
    ``review_answer`` 抛错被 ``_try_review_or_none`` 吞掉。需要测 review 的
    用例自己 monkeypatch 回去。
    """
    monkeypatch.setattr(
        agent_route_module,
        "review_answer",
        lambda **_: (_ for _ in ()).throw(RuntimeError("reviewer disabled in test")),
    )


@pytest.fixture()
def session_id() -> str:
    return "test-book-routing-r2"


@pytest.fixture()
def client_with_session(session_id: str) -> tuple[TestClient, _FakeAssembler]:
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
    fake_adapter: R2FakeAdapter,
) -> None:
    monkeypatch.setattr(
        agent_route_module,
        "build_llm_client",
        lambda request: fake_adapter,
    )


# ---------------------------------------------------------------------------
# reviewer 桩 helpers（与 r1 等价测试同实现——reviewer 是 dict 形态，与
# protocol 无关）
# ---------------------------------------------------------------------------


def _stub_reviewer_returning(
    monkeypatch: pytest.MonkeyPatch,
    raw: dict[str, Any],
) -> None:
    monkeypatch.setattr(
        agent_route_module,
        "review_answer",
        lambda **_: raw,
    )


def _stub_reviewer_raising(
    monkeypatch: pytest.MonkeyPatch,
    exc: BaseException,
) -> None:
    def _raise(**_: Any) -> dict[str, Any]:
        raise exc

    monkeypatch.setattr(agent_route_module, "review_answer", _raise)


def _good_review_dict(*, total: int = 20) -> dict[str, Any]:
    """构造一份合规 reviewer 输出，5 个维度均分到 ``total``。"""
    base = max(0, min(5, total // 5))
    remainder = total - base * 5
    dims = ["structural_judgment", "evidence_density", "honesty",
            "actionability", "cross_chapter_coherence"]
    scores: dict[str, int] = {}
    for i, name in enumerate(dims):
        scores[name] = min(5, base + (1 if i == 0 and remainder > 0 else 0))
    return {
        "scores": scores,
        "per_dimension_comment": {name: f"{name} 评语" for name in dims},
        "overall": "整体反馈尚可，可加厚证据。",
        "top_issues": ["证据集中表层", "缺跨章节视野"],
        "single_most_valuable_improvement": "补一条隐喻级伏笔。",
    }


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


def test_general_question_fast_path_works_under_r2_protocol(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """r2 下通识题走 fast_path 一次成功，不再 fallback 到 agent_loop。

    Backlog B-1（2026-05-15）后 ``bookscope/agent/fast_path.py`` 通过
    adapter Protocol 方法 ``extract_final_text`` / ``extract_usage_tokens``
    拿干净文本，r2 真实 adapter 跟 ``R2FakeAdapter`` 都按 OpenAI choices
    形态实现。一次 LLM call 就拿到答案，``trace.outcome`` 是
    ``fast_path_success``、``route_type`` 是 ``fast_general``——不再多调
    1 次 LLM 后 fallback 到 agent_loop。

    上一波 QA 加的 ``test_general_question_fast_path_falls_back_under_r2_protocol``
    守护的是修复前的临时行为（fast_path 解析失败 → 落 agent_loop），docstring
    标"未来 fast_path r2 化时测试会失败提醒重写"——本测试就是重写后的正向版本。

    桩序列：fast_path 一次调用拿到答案就返回，agent_loop 用不到。
    """
    client, _ = client_with_session
    fake = R2FakeAdapter(
        [
            # fast_path 这一次拿到 r2 形态 final → 直接 parse 成功
            r2_final_text_response(
                "主要角色有朱元璋。",
                [{"chapter": 1, "snippet": "朱元璋称帝。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "主要角色有哪几个？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # fast_path 一次成功——outcome 标记 fast_path_success，route_type fast_general
    assert body["trace"]["outcome"] == "fast_path_success"
    assert body["route_type"] == "fast_general"
    assert body["protocol_version"] == "r2"
    assert body["answer"] == "主要角色有朱元璋。"
    # 仅 1 次 LLM 调用——不再 fallback
    assert fake.call_count == 1


def test_diagnostic_question_routes_to_agent_loop_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """诊断题走完整 ``loop_r2.AgentLoop``：1 轮 tool_calls + 1 轮 stop final。"""
    client, _ = client_with_session
    fake = R2FakeAdapter(
        [
            r2_tool_call_response(name="search_chunks", arguments={"query": "性格"}),
            r2_final_text_response(
                "渐变。",
                [{"chapter": 1, "snippet": "片段。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "主角性格转变是渐变还是硬扳？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trace"]["outcome"] == "success"
    assert body["protocol_version"] == "r2"
    assert fake.call_count == 2


def test_env_disabled_forces_general_question_through_agent_loop_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """env ``BOOKSCOPE_FAST_PATH_DISABLED=1`` 时通识题也强制走 ``loop_r2``。"""
    monkeypatch.setenv("BOOKSCOPE_FAST_PATH_DISABLED", "1")
    client, _ = client_with_session
    fake = R2FakeAdapter(
        [
            r2_tool_call_response(name="search_chunks", arguments={"query": "角色"}),
            r2_final_text_response(
                "答复。",
                [{"chapter": 1, "snippet": "片段。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "主要角色有哪几个？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trace"]["outcome"] == "success"
    assert body["protocol_version"] == "r2"
    assert fake.call_count == 2


def test_agent_ask_includes_review_when_reviewer_succeeds_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """reviewer 跑通时 review 字段填充：5 维 + ``overall_score`` + ``suggest_redo``。"""
    monkeypatch.setenv("BOOKSCOPE_FAST_PATH_DISABLED", "1")
    client, _ = client_with_session
    fake = R2FakeAdapter(
        [
            r2_tool_call_response(name="search_chunks", arguments={"query": "x"}),
            r2_final_text_response(
                "诊断答复。",
                [{"chapter": 1, "snippet": "原文。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)
    _stub_reviewer_returning(monkeypatch, _good_review_dict(total=20))

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "主角性格转变是渐变还是硬扳？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    review = resp.json()["review"]
    assert review is not None
    assert review["overall_score"] == 20
    assert review["suggest_redo"] is False
    assert set(review["dimensions"].keys()) == {
        "structural_judgment",
        "evidence_density",
        "honesty",
        "actionability",
        "cross_chapter_coherence",
    }
    assert all(0 <= d["score"] <= 5 for d in review["dimensions"].values())
    assert review["overall_comment"]
    assert review["top_issues"]


def test_agent_ask_review_none_when_reviewer_raises_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """reviewer 抛 ``ProviderUnavailable`` → ``review = None``，主 ask 仍 200。"""
    monkeypatch.setenv("BOOKSCOPE_FAST_PATH_DISABLED", "1")
    client, _ = client_with_session
    fake = R2FakeAdapter(
        [
            r2_tool_call_response(name="search_chunks", arguments={"query": "x"}),
            r2_final_text_response(
                "答复。",
                [{"chapter": 1, "snippet": "片段。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)
    _stub_reviewer_raising(monkeypatch, ProviderUnavailable("reviewer down"))

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "主角铺垫连贯吗？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["review"] is None


def test_agent_ask_review_none_when_reviewer_returns_malformed_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """reviewer 返非法 dict（缺 ``scores``）→ ``review = None``，主 ask 仍 200。"""
    monkeypatch.setenv("BOOKSCOPE_FAST_PATH_DISABLED", "1")
    client, _ = client_with_session
    fake = R2FakeAdapter(
        [
            r2_tool_call_response(name="search_chunks", arguments={"query": "x"}),
            r2_final_text_response(
                "答复。",
                [{"chapter": 1, "snippet": "片段。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)
    _stub_reviewer_returning(monkeypatch, {"overall": "无评分字段"})

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "支线 X 出场密度如何？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["review"] is None


def test_agent_ask_review_suggests_redo_when_below_threshold_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """``overall_score < 18`` → ``suggest_redo == True``。"""
    monkeypatch.setenv("BOOKSCOPE_FAST_PATH_DISABLED", "1")
    client, _ = client_with_session
    fake = R2FakeAdapter(
        [
            r2_tool_call_response(name="search_chunks", arguments={"query": "x"}),
            r2_final_text_response(
                "薄弱答复。",
                [{"chapter": 1, "snippet": "片段。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)
    # 5 维 × 3 分 = 15 < 18
    _stub_reviewer_returning(monkeypatch, _good_review_dict(total=15))

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "支线塑造单薄吗？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    review = resp.json()["review"]
    assert review is not None
    assert review["overall_score"] == 15
    assert review["suggest_redo"] is True


def test_agent_ask_review_does_not_suggest_redo_at_threshold_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """``overall_score == 18`` → ``suggest_redo == False``（严格小于）。"""
    monkeypatch.setenv("BOOKSCOPE_FAST_PATH_DISABLED", "1")
    client, _ = client_with_session
    fake = R2FakeAdapter(
        [
            r2_tool_call_response(name="search_chunks", arguments={"query": "x"}),
            r2_final_text_response(
                "及格答复。",
                [{"chapter": 1, "snippet": "片段。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)
    raw = {
        "scores": {
            "structural_judgment": 4,
            "evidence_density": 4,
            "honesty": 4,
            "actionability": 3,
            "cross_chapter_coherence": 3,
        },
        "per_dimension_comment": {
            "structural_judgment": "ok",
            "evidence_density": "ok",
            "honesty": "ok",
            "actionability": "ok",
            "cross_chapter_coherence": "ok",
        },
        "overall": "及格",
        "top_issues": [],
        "single_most_valuable_improvement": "n/a",
    }
    _stub_reviewer_returning(monkeypatch, raw)

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "节奏 ok 吗？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    review = resp.json()["review"]
    assert review is not None
    assert review["overall_score"] == 18
    assert review["suggest_redo"] is False


def test_fast_path_garbage_output_falls_back_to_agent_loop_r2(
    client_with_session: tuple[TestClient, _FakeAssembler],
    monkeypatch: pytest.MonkeyPatch,
    session_id: str,
) -> None:
    """fast_path LLM 输出乱码 → 自动 fallback 到 ``loop_r2.AgentLoop``。

    与上一个 ``..._fast_path_falls_back...`` 测试的差异：上面那条测的是 **r2
    形态在 fast_path 当前 r1-only 解析路径下 fallback** —— 即使 LLM 输出
    "正确"，protocol mismatch 也会 fallback。本测试测**LLM 输出本身就乱码**
    的 fallback 路径——即使 fast_path 哪天 r2 化了，乱码输入仍应 fallback。

    桩序列：
    1. fast_path：``r2_raw_text_response("非结构化回复无 JSON")`` —— content
       是文本但解析 JSON 失败
    2-3. agent_loop 兜底两轮
    """
    client, _ = client_with_session
    fake = R2FakeAdapter(
        [
            r2_raw_text_response("非结构化回复无 JSON"),
            r2_tool_call_response(name="search_chunks", arguments={"query": "角色"}),
            r2_final_text_response(
                "兜底答复。",
                [{"chapter": 1, "snippet": "原文。"}],
            ),
        ]
    )
    _install_fake_client(monkeypatch, fake)

    resp = client.post(
        "/api/agent/ask",
        json={
            "question": "主要角色有哪几个？",
            "book_session_id": session_id,
            "provider": "deepseek",
            "api_key": "sk-test-0123456789",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["trace"]["outcome"] == "success"
    assert body["protocol_version"] == "r2"
    assert fake.call_count == 3
