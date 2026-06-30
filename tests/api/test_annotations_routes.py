"""标注路由 e2e 单测(WP-reading-workspace Phase C)。

走 TestClient 真打端点。命门四条:

1. hosted 下 CRUD 全通,响应**不外泄 owner_user_id**。
2. **隔离**:用户 A 看不到 / 改不了 / 删不了用户 B 的标注(不是本人的当 404)。
3. **书归属**:给不属于自己的书加 / 列标注 → 404(过 user_owns_session)。
4. **local 零账号面**:local 模式 /api/annotations 根本不挂 → 404,标注全走前端。

书归属靠 acc.add_document 记一条(user_owns_session 查 documents 表),不走真 ingest。
这条链是纯 CRUD,根本不调 LLM、不传 key——可放心全程跑。
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bookscope.api import auth, create_app, deployment

_ANCHOR = {
    "chapter": 3,
    "para_index": 2,
    "quote": "天下大势,分久必合",
    "prefix": "话说",
    "suffix": ",合久必分",
    "char_start": 5,
}


def _hdr(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def hosted(monkeypatch, tmp_path: Path) -> Iterator[TestClient]:
    monkeypatch.setenv("BOOKSCOPE_DEPLOYMENT_MODE", "hosted")
    monkeypatch.setenv("BOOKSCOPE_AUTH_SECRET", "test-secret")
    monkeypatch.setenv("BOOKSCOPE_ACCOUNTS_DB", str(tmp_path / "acc.db"))
    monkeypatch.setenv("BOOKSCOPE_RATELIMIT_DISABLED", "1")
    deployment._reset_accounts_store()
    with TestClient(create_app()) as client:
        yield client
    deployment._reset_accounts_store()


def _register_user_with_book(email: str, book_id: str) -> str:
    """建账号 + 记一本书的归属(让 user_owns_session 过),返回会话令牌。"""
    acc = deployment.get_accounts_store()
    user = acc.create_user(email=email, password="pw123456")
    acc.add_document(owner_user_id=user.id, doc_id=book_id, title=f"{email} 的书")
    return auth.issue_token(user.id)


def _create_payload(book_id: str, **over) -> dict:
    return {
        "book_session_id": book_id,
        "kind": "highlight",
        "anchor": _ANCHOR,
        "color": "seal",
        **over,
    }


# ---- CRUD ----

def test_create_then_list(hosted):
    token = _register_user_with_book("a@x.com", "book-1")
    r = hosted.post(
        "/api/annotations", json=_create_payload("book-1"), headers=_hdr(token)
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"]
    assert body["book_session_id"] == "book-1"
    assert body["kind"] == "highlight"
    assert body["anchor"]["quote"] == "天下大势,分久必合"
    # 不外泄归属字段
    assert "owner_user_id" not in body

    lst = hosted.get(
        "/api/annotations", params={"book_session_id": "book-1"}, headers=_hdr(token)
    )
    assert lst.status_code == 200
    annos = lst.json()["annotations"]
    assert len(annos) == 1 and annos[0]["id"] == body["id"]


def test_create_note_and_patch(hosted):
    token = _register_user_with_book("a@x.com", "book-1")
    created = hosted.post(
        "/api/annotations",
        json=_create_payload("book-1", kind="note", note_text="旧笔记", color=None),
        headers=_hdr(token),
    ).json()
    aid = created["id"]
    # 改笔记
    patched = hosted.patch(
        f"/api/annotations/{aid}",
        json={"note_text": "新笔记"},
        headers=_hdr(token),
    )
    assert patched.status_code == 200
    assert patched.json()["note_text"] == "新笔记"
    # updated_at 应推进(>= created_at)
    assert patched.json()["updated_at"] >= created["updated_at"]


def test_patch_can_clear_note(hosted):
    token = _register_user_with_book("a@x.com", "book-1")
    created = hosted.post(
        "/api/annotations",
        json=_create_payload("book-1", kind="note", note_text="待清空"),
        headers=_hdr(token),
    ).json()
    # 显式传 null 清空笔记
    patched = hosted.patch(
        f"/api/annotations/{created['id']}",
        json={"note_text": None},
        headers=_hdr(token),
    )
    assert patched.status_code == 200
    assert patched.json()["note_text"] is None


def test_delete(hosted):
    token = _register_user_with_book("a@x.com", "book-1")
    created = hosted.post(
        "/api/annotations", json=_create_payload("book-1"), headers=_hdr(token)
    ).json()
    assert (
        hosted.delete(
            f"/api/annotations/{created['id']}", headers=_hdr(token)
        ).status_code
        == 204
    )
    # 删完列表空
    lst = hosted.get(
        "/api/annotations", params={"book_session_id": "book-1"}, headers=_hdr(token)
    )
    assert lst.json()["annotations"] == []
    # 再删 → 404
    assert (
        hosted.delete(
            f"/api/annotations/{created['id']}", headers=_hdr(token)
        ).status_code
        == 404
    )


def test_mine_cross_book(hosted):
    token = _register_user_with_book("a@x.com", "book-1")
    deployment.get_accounts_store().add_document(
        owner_user_id=auth.verify_token(token), doc_id="book-2", title="第二本"
    )
    hosted.post("/api/annotations", json=_create_payload("book-1"), headers=_hdr(token))
    hosted.post(
        "/api/annotations",
        json=_create_payload("book-2", kind="note", note_text="在第二本"),
        headers=_hdr(token),
    )
    mine = hosted.get("/api/annotations/mine", headers=_hdr(token))
    assert mine.status_code == 200
    books = {a["book_session_id"] for a in mine.json()["annotations"]}
    assert books == {"book-1", "book-2"}


# ---- 隔离命门 ----

def test_isolation_list_get_patch_delete(hosted):
    ta = _register_user_with_book("a@x.com", "a-book")
    tb = _register_user_with_book("b@x.com", "b-book")
    a_anno = hosted.post(
        "/api/annotations", json=_create_payload("a-book"), headers=_hdr(ta)
    ).json()

    # B 列 A 的书 → 404(书不是 B 的)
    assert (
        hosted.get(
            "/api/annotations", params={"book_session_id": "a-book"}, headers=_hdr(tb)
        ).status_code
        == 404
    )
    # B 改 A 的标注 → 404(当不存在)
    assert (
        hosted.patch(
            f"/api/annotations/{a_anno['id']}",
            json={"note_text": "B 篡改"},
            headers=_hdr(tb),
        ).status_code
        == 404
    )
    # B 删 A 的标注 → 404
    assert (
        hosted.delete(
            f"/api/annotations/{a_anno['id']}", headers=_hdr(tb)
        ).status_code
        == 404
    )
    # B 的 /mine 看不到 A 的标注
    assert hosted.get("/api/annotations/mine", headers=_hdr(tb)).json()[
        "annotations"
    ] == []
    # A 的标注没被动过
    still = hosted.get(
        "/api/annotations", params={"book_session_id": "a-book"}, headers=_hdr(ta)
    ).json()["annotations"]
    assert len(still) == 1


def test_cannot_annotate_book_you_dont_own(hosted):
    ta = _register_user_with_book("a@x.com", "a-book")
    # A 给一本不属于自己的书加标注 → 404(user_owns_session 拦)
    r = hosted.post(
        "/api/annotations", json=_create_payload("someone-else-book"), headers=_hdr(ta)
    )
    assert r.status_code == 404


# ---- 鉴权 ----

def test_requires_login(hosted):
    _register_user_with_book("a@x.com", "book-1")
    # 没令牌 → 401
    assert hosted.get(
        "/api/annotations", params={"book_session_id": "book-1"}
    ).status_code == 401
    assert hosted.get("/api/annotations/mine").status_code == 401
    assert hosted.post("/api/annotations", json=_create_payload("book-1")).status_code == 401
    assert hosted.patch("/api/annotations/x", json={"note_text": "y"}).status_code == 401
    assert hosted.delete("/api/annotations/x").status_code == 401


def test_bad_token_401(hosted):
    assert (
        hosted.get(
            "/api/annotations",
            params={"book_session_id": "book-1"},
            headers=_hdr("garbage"),
        ).status_code
        == 401
    )


def test_create_validation_422(hosted):
    token = _register_user_with_book("a@x.com", "book-1")
    # 缺 anchor → 422
    r = hosted.post(
        "/api/annotations",
        json={"book_session_id": "book-1", "kind": "highlight"},
        headers=_hdr(token),
    )
    assert r.status_code == 422
    # kind 不在白名单 → 422
    r2 = hosted.post(
        "/api/annotations",
        json=_create_payload("book-1", kind="scribble"),
        headers=_hdr(token),
    )
    assert r2.status_code == 422


# ---- local 零账号面 ----

def test_local_mode_has_no_annotation_routes(monkeypatch, tmp_path):
    # 命门:local 模式 /api/annotations 根本没挂 → 404,标注全走前端 localStorage。
    monkeypatch.delenv("BOOKSCOPE_DEPLOYMENT_MODE", raising=False)
    monkeypatch.setenv("BOOKSCOPE_RATELIMIT_DISABLED", "1")
    deployment._reset_accounts_store()
    with TestClient(create_app()) as client:
        assert (
            client.get("/api/annotations", params={"book_session_id": "x"}).status_code
            == 404
        )
        assert client.get("/api/annotations/mine").status_code == 404
        assert (
            client.post("/api/annotations", json=_create_payload("x")).status_code
            == 404
        )
