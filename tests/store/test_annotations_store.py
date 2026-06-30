"""标注数据层单测(WP-reading-workspace Phase C)。

全程内存 SQLite,不碰真盘、不调 LLM。重点压**数据隔离**这个命门:一个用户绝不该
看见 / 改得动 / 删得动另一个用户的标注;删账号连带删干净;锚点整列 JSON 进出无损;
**任何字段都没有 key**(红线)。
"""

from __future__ import annotations

import pytest

from bookscope.store.accounts import AccountsStore, Annotation

_ANCHOR = {
    "chapter": 3,
    "para_index": 2,
    "quote": "天下大势,分久必合",
    "prefix": "话说",
    "suffix": ",合久必分",
    "char_start": 5,
}


@pytest.fixture
def store() -> AccountsStore:
    s = AccountsStore(":memory:")
    yield s
    s.close()


def _user(store: AccountsStore, email: str):
    return store.create_user(email=email, password="pw123456")


# ---- 基本 CRUD ----

def test_add_returns_annotation_with_id(store: AccountsStore):
    a = _user(store, "a@x.com")
    anno = store.add_annotation(
        owner_user_id=a.id,
        book_session_id="book-1",
        kind="highlight",
        anchor=_ANCHOR,
        color="seal",
    )
    assert isinstance(anno, Annotation)
    assert anno.id
    assert anno.owner_user_id == a.id
    assert anno.book_session_id == "book-1"
    assert anno.kind == "highlight"
    assert anno.anchor == _ANCHOR  # 锚点整列 JSON 进出无损
    assert anno.color == "seal"
    assert anno.note_text is None
    assert anno.created_at and anno.updated_at


def test_add_honors_explicit_id(store: AccountsStore):
    a = _user(store, "a@x.com")
    anno = store.add_annotation(
        owner_user_id=a.id,
        book_session_id="book-1",
        kind="note",
        anchor=_ANCHOR,
        note_text="前端发的 id",
        annotation_id="anno-fixed-1",
    )
    assert anno.id == "anno-fixed-1"
    got = store.get_owned_annotation(owner_user_id=a.id, annotation_id="anno-fixed-1")
    assert got is not None and got.note_text == "前端发的 id"


def test_list_by_user_and_by_book(store: AccountsStore):
    a = _user(store, "a@x.com")
    store.add_annotation(
        owner_user_id=a.id, book_session_id="book-1", kind="bookmark", anchor=_ANCHOR
    )
    store.add_annotation(
        owner_user_id=a.id, book_session_id="book-1", kind="highlight", anchor=_ANCHOR
    )
    store.add_annotation(
        owner_user_id=a.id, book_session_id="book-2", kind="note", anchor=_ANCHOR
    )
    # 跨书汇总:三条都在
    assert len(store.list_annotations_by_user(a.id)) == 3
    # 只列某本书:两条
    book1 = store.list_annotations_by_user(a.id, book_session_id="book-1")
    assert len(book1) == 2
    assert all(x.book_session_id == "book-1" for x in book1)


def test_update_note_and_color(store: AccountsStore):
    a = _user(store, "a@x.com")
    anno = store.add_annotation(
        owner_user_id=a.id,
        book_session_id="book-1",
        kind="note",
        anchor=_ANCHOR,
        note_text="旧笔记",
        color="ink",
    )
    updated = store.update_annotation(
        owner_user_id=a.id,
        annotation_id=anno.id,
        note_text="新笔记",
        color="seal",
    )
    assert updated is not None
    assert updated.note_text == "新笔记"
    assert updated.color == "seal"
    # 没改的字段保持
    assert updated.kind == "note"
    assert updated.anchor == _ANCHOR


def test_update_can_clear_nullable_fields(store: AccountsStore):
    a = _user(store, "a@x.com")
    anno = store.add_annotation(
        owner_user_id=a.id,
        book_session_id="book-1",
        kind="highlight",
        anchor=_ANCHOR,
        note_text="有笔记",
        color="seal",
    )
    updated = store.update_annotation(
        owner_user_id=a.id,
        annotation_id=anno.id,
        clear_note_text=True,
        clear_color=True,
    )
    assert updated is not None
    assert updated.note_text is None
    assert updated.color is None


def test_update_anchor(store: AccountsStore):
    a = _user(store, "a@x.com")
    anno = store.add_annotation(
        owner_user_id=a.id, book_session_id="book-1", kind="highlight", anchor=_ANCHOR
    )
    new_anchor = {**_ANCHOR, "chapter": 9, "quote": "改了的引文"}
    updated = store.update_annotation(
        owner_user_id=a.id, annotation_id=anno.id, anchor=new_anchor
    )
    assert updated is not None and updated.anchor == new_anchor


def test_delete(store: AccountsStore):
    a = _user(store, "a@x.com")
    anno = store.add_annotation(
        owner_user_id=a.id, book_session_id="book-1", kind="bookmark", anchor=_ANCHOR
    )
    assert store.delete_annotation(owner_user_id=a.id, annotation_id=anno.id) is True
    assert (
        store.get_owned_annotation(owner_user_id=a.id, annotation_id=anno.id) is None
    )
    # 再删一次:删不动,返 False
    assert store.delete_annotation(owner_user_id=a.id, annotation_id=anno.id) is False


# ---- 隔离命门:别人的看不见 / 改不动 / 删不动 ----

def test_list_isolation(store: AccountsStore):
    a = _user(store, "a@x.com")
    b = _user(store, "b@x.com")
    store.add_annotation(
        owner_user_id=a.id, book_session_id="book-1", kind="highlight", anchor=_ANCHOR
    )
    # B 列自己的:看不到 A 的
    assert store.list_annotations_by_user(b.id) == []
    # B 按 A 的书号列:照样空(隔离在 owner_user_id,不在 book)
    assert store.list_annotations_by_user(b.id, book_session_id="book-1") == []


def test_get_isolation(store: AccountsStore):
    a = _user(store, "a@x.com")
    b = _user(store, "b@x.com")
    anno = store.add_annotation(
        owner_user_id=a.id, book_session_id="book-1", kind="note", anchor=_ANCHOR
    )
    # A 拿得到自己的;B 拿 A 的 = 当不存在,返 None
    assert (
        store.get_owned_annotation(owner_user_id=a.id, annotation_id=anno.id)
        is not None
    )
    assert (
        store.get_owned_annotation(owner_user_id=b.id, annotation_id=anno.id) is None
    )


def test_update_isolation(store: AccountsStore):
    a = _user(store, "a@x.com")
    b = _user(store, "b@x.com")
    anno = store.add_annotation(
        owner_user_id=a.id,
        book_session_id="book-1",
        kind="note",
        anchor=_ANCHOR,
        note_text="A 的笔记",
    )
    # B 改 A 的:改不动,返 None,内容没变
    assert (
        store.update_annotation(
            owner_user_id=b.id, annotation_id=anno.id, note_text="B 来篡改"
        )
        is None
    )
    still = store.get_owned_annotation(owner_user_id=a.id, annotation_id=anno.id)
    assert still is not None and still.note_text == "A 的笔记"


def test_delete_isolation(store: AccountsStore):
    a = _user(store, "a@x.com")
    b = _user(store, "b@x.com")
    anno = store.add_annotation(
        owner_user_id=a.id, book_session_id="book-1", kind="bookmark", anchor=_ANCHOR
    )
    # B 删 A 的:删不动,返 False,标注还在
    assert (
        store.delete_annotation(owner_user_id=b.id, annotation_id=anno.id) is False
    )
    assert (
        store.get_owned_annotation(owner_user_id=a.id, annotation_id=anno.id)
        is not None
    )


# ---- 删除权:删账号连带删标注(ON DELETE CASCADE) ----

def test_delete_user_cascades_annotations(store: AccountsStore):
    a = _user(store, "a@x.com")
    store.add_annotation(
        owner_user_id=a.id, book_session_id="book-1", kind="highlight", anchor=_ANCHOR
    )
    store.add_annotation(
        owner_user_id=a.id, book_session_id="book-2", kind="note", anchor=_ANCHOR
    )
    assert store.delete_user(a.id) is True
    # 账号没了,名下标注连带删干净
    assert store.list_annotations_by_user(a.id) == []


def test_persists_to_real_file(tmp_path):
    db = tmp_path / "accounts.db"
    s1 = AccountsStore(db)
    u = s1.create_user(email="persist@x.com", password="pw123456")
    s1.add_annotation(
        owner_user_id=u.id,
        book_session_id="book-1",
        kind="note",
        anchor=_ANCHOR,
        note_text="留得住吗",
    )
    s1.close()

    s2 = AccountsStore(db)
    rows = s2.list_annotations_by_user(u.id)
    assert len(rows) == 1
    assert rows[0].note_text == "留得住吗"
    assert rows[0].anchor == _ANCHOR  # JSON 落盘再读回无损
    s2.close()


# ---- 红线:标注表没有任何 key 字段 ----

def test_no_key_column_in_annotations(store: AccountsStore):
    cols = {
        r["name"]
        for r in store._conn.execute("PRAGMA table_info(annotations)")  # noqa: SLF001
    }
    assert not any("key" in c.lower() for c in cols), cols
    # 模型对外视图也不含 key
    a = _user(store, "a@x.com")
    anno = store.add_annotation(
        owner_user_id=a.id, book_session_id="book-1", kind="note", anchor=_ANCHOR
    )
    dumped = anno.model_dump()
    assert not any("key" in k.lower() for k in dumped)
