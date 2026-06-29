"""账号 + 文档归属数据层单测(1.6.2 Phase 1a)。

全程内存 SQLite(``:memory:``),不碰真盘、不调 LLM,跑得飞快。
重点压**数据隔离**这个命门:一个用户绝不该看见 / 删得动另一个用户的文档。
"""

from __future__ import annotations

import pytest

from bookscope.store.accounts import (
    AccountsStore,
    DuplicateEmailError,
    User,
    hash_password,
    verify_password,
)


@pytest.fixture
def store() -> AccountsStore:
    s = AccountsStore(":memory:")
    yield s
    s.close()


# ---- 密码哈希 ----

def test_hash_is_not_plaintext():
    h = hash_password("hunter2")
    assert h != "hunter2"
    assert h.startswith("$argon2")


def test_verify_password_roundtrip():
    h = hash_password("correct horse")
    assert verify_password(h, "correct horse") is True
    assert verify_password(h, "wrong") is False


def test_verify_password_bad_hash_returns_false():
    # 哈希损坏不抛异常,稳稳返 False。
    assert verify_password("not-a-real-hash", "whatever") is False


# ---- 账号 ----

def test_create_user_returns_user_without_hash(store: AccountsStore):
    u = store.create_user(email="a@x.com", password="pw123456")
    assert isinstance(u, User)
    assert u.email == "a@x.com"
    assert u.id
    # 对外视图绝不带 password_hash。
    assert "password_hash" not in u.model_dump()


def test_create_user_duplicate_email_raises(store: AccountsStore):
    store.create_user(email="dup@x.com", password="pw123456")
    with pytest.raises(DuplicateEmailError):
        store.create_user(email="dup@x.com", password="another")


def test_create_user_duplicate_email_is_case_insensitive(store: AccountsStore):
    store.create_user(email="Mixed@X.com", password="pw123456")
    with pytest.raises(DuplicateEmailError):
        store.create_user(email="mixed@x.com", password="pw123456")


def test_create_user_blank_email_or_password_raises(store: AccountsStore):
    with pytest.raises(ValueError):
        store.create_user(email="   ", password="pw123456")
    with pytest.raises(ValueError):
        store.create_user(email="ok@x.com", password="")


def test_get_user_by_email_and_id(store: AccountsStore):
    u = store.create_user(email="find@x.com", password="pw123456", phone="13800000000")
    by_email = store.get_user_by_email("find@x.com")
    by_id = store.get_user_by_id(u.id)
    assert by_email is not None and by_email.id == u.id
    assert by_id is not None and by_id.email == "find@x.com"
    assert by_email.phone == "13800000000"


def test_get_user_by_email_case_insensitive(store: AccountsStore):
    store.create_user(email="Case@X.com", password="pw123456")
    assert store.get_user_by_email("case@x.com") is not None


def test_get_user_missing_returns_none(store: AccountsStore):
    assert store.get_user_by_email("nobody@x.com") is None
    assert store.get_user_by_id("no-such-id") is None


def test_verify_credentials_correct(store: AccountsStore):
    u = store.create_user(email="login@x.com", password="s3cret-pw")
    got = store.verify_credentials(email="login@x.com", password="s3cret-pw")
    assert got is not None and got.id == u.id


def test_verify_credentials_wrong_password_returns_none(store: AccountsStore):
    store.create_user(email="login2@x.com", password="s3cret-pw")
    assert store.verify_credentials(email="login2@x.com", password="nope") is None


def test_verify_credentials_unknown_email_returns_none(store: AccountsStore):
    # 查无此人也返 None(不区分密码错 / 无此人,防枚举),且不抛。
    assert store.verify_credentials(email="ghost@x.com", password="whatever") is None


# ---- 文档归属:隔离命门 ----

def test_add_and_list_own_documents(store: AccountsStore):
    a = store.create_user(email="a@x.com", password="pw123456")
    store.add_document(owner_user_id=a.id, doc_id="doc-1", title="明朝那些事儿")
    store.add_document(owner_user_id=a.id, doc_id="doc-2", title="三国演义")
    docs = store.list_documents(a.id)
    assert {d.id for d in docs} == {"doc-1", "doc-2"}
    assert all(d.owner_user_id == a.id for d in docs)


def test_list_documents_isolation(store: AccountsStore):
    a = store.create_user(email="a@x.com", password="pw123456")
    b = store.create_user(email="b@x.com", password="pw123456")
    store.add_document(owner_user_id=a.id, doc_id="a-doc", title="A 的书")
    # B 列自己的文档:看不到 A 的。
    assert store.list_documents(b.id) == []


def test_get_owned_document_isolation(store: AccountsStore):
    a = store.create_user(email="a@x.com", password="pw123456")
    b = store.create_user(email="b@x.com", password="pw123456")
    store.add_document(owner_user_id=a.id, doc_id="a-doc", title="A 的书")
    # A 拿自己的拿得到;B 拿 A 的 = 当不存在,返 None。
    assert store.get_owned_document(owner_user_id=a.id, doc_id="a-doc") is not None
    assert store.get_owned_document(owner_user_id=b.id, doc_id="a-doc") is None


def test_owns_isolation(store: AccountsStore):
    a = store.create_user(email="a@x.com", password="pw123456")
    b = store.create_user(email="b@x.com", password="pw123456")
    store.add_document(owner_user_id=a.id, doc_id="a-doc", title="A 的书")
    assert store.owns(owner_user_id=a.id, doc_id="a-doc") is True
    assert store.owns(owner_user_id=b.id, doc_id="a-doc") is False


def test_delete_document_only_own(store: AccountsStore):
    a = store.create_user(email="a@x.com", password="pw123456")
    b = store.create_user(email="b@x.com", password="pw123456")
    store.add_document(owner_user_id=a.id, doc_id="a-doc", title="A 的书")
    # B 删 A 的:删不动,返 False,文档还在。
    assert store.delete_document(owner_user_id=b.id, doc_id="a-doc") is False
    assert store.owns(owner_user_id=a.id, doc_id="a-doc") is True
    # A 删自己的:删得动。
    assert store.delete_document(owner_user_id=a.id, doc_id="a-doc") is True
    assert store.owns(owner_user_id=a.id, doc_id="a-doc") is False


def test_delete_user_cascades_documents(store: AccountsStore):
    a = store.create_user(email="a@x.com", password="pw123456")
    store.add_document(owner_user_id=a.id, doc_id="a-doc", title="A 的书")
    assert store.delete_user(a.id) is True
    # 账号没了,名下文档归属连带删干净(ON DELETE CASCADE)。
    assert store.get_user_by_id(a.id) is None
    assert store.list_documents(a.id) == []


def test_delete_missing_user_returns_false(store: AccountsStore):
    assert store.delete_user("no-such-id") is False


def test_persists_to_real_file(tmp_path):
    # 落真盘:写一个 store、关掉、重开,数据还在。
    db = tmp_path / "accounts.db"
    s1 = AccountsStore(db)
    u = s1.create_user(email="persist@x.com", password="pw123456")
    s1.add_document(owner_user_id=u.id, doc_id="d1", title="留得住吗")
    s1.close()

    s2 = AccountsStore(db)
    assert s2.get_user_by_email("persist@x.com") is not None
    assert len(s2.list_documents(u.id)) == 1
    s2.close()
