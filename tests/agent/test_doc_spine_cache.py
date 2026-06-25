"""Book-level 文脉缓存(1.6 红头文件)单测 —— 临时 db,不调真 LLM。

照 ``test_chapter_spine_cache.py`` 的范式。文脉缓存 key 比章脉少一维(不带 genre)。
"""

from __future__ import annotations

import bookscope.agent._internal.doc_spine_cache as dc


def _setup_temp(monkeypatch, tmp_path):  # noqa: ANN001, ANN202
    monkeypatch.setenv(dc.ENV_DB_PATH, str(tmp_path / "doc_spine_test.db"))
    monkeypatch.delenv(dc.ENV_DISABLED, raising=False)
    dc.reset_doc_spine_cache_singleton_for_test()


_CHUNKS = [
    {"chunk_id": "c0", "chapter": 1, "text": "应当于6月底前完成。"},
]
# 一份非空文脉(有真要素 + 有条款)。
_SPINE = {
    "schema_version": "v1",
    "head": [{"field": "发文字号", "value": "X发〔2024〕5号", "evidence": "X发〔2024〕5号",
              "verified": True, "match_score": 1.0}],
    "clauses": [{"chapter": 1, "matter": "试点", "instruction_type": "硬要求", "actor": "",
                 "deadline": "", "basis_ref": "", "evidence": "应当于6月底前完成。",
                 "verified": True, "match_score": 1.0}],
}
# 一份「空」文脉:头要素全留空 + 没条款(一次抽取失败的样子)。
_EMPTY_SPINE = {
    "schema_version": "v1",
    "head": [{"field": "发文字号", "value": "", "evidence": "", "verified": False,
              "match_score": 0.0}],
    "clauses": [],
}


def _counted(ret):  # noqa: ANN001, ANN202 — 返 (build_func, calls dict)
    calls = {"n": 0}

    def _build():
        calls["n"] += 1
        return ret

    return _build, calls


def _run(build, *, chunks=_CHUNKS, model="m"):  # noqa: ANN001, ANN202
    return dc.build_doc_spine_cached(all_chunks=chunks, model=model, build_func=build)


def test_miss_builds_then_hit_skips_build(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    build, calls = _counted(_SPINE)
    assert _run(build) == _SPINE
    assert _run(build) == _SPINE
    assert calls["n"] == 1                      # 第二次命中,不重建


def test_different_inputs_miss(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    build, calls = _counted(_SPINE)
    _run(build)
    _run(build, model="m2")                     # model 变
    _run(build, chunks=[{"chunk_id": "x", "chapter": 1, "text": "别的公文"}])  # chunks 变
    assert calls["n"] == 3                       # 三次输入各异,全 miss


def test_empty_spine_not_cached(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """头要素全留空 + 没条款 = 一次抽取失败,不写缓存(别把失败钉死)。"""
    _setup_temp(monkeypatch, tmp_path)
    build, calls = _counted(_EMPTY_SPINE)
    _run(build)
    _run(build)
    assert calls["n"] == 2                       # 空文脉不写缓存 → 第二次还得重建


def test_disabled_always_builds(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    monkeypatch.setenv(dc.ENV_DISABLED, "1")
    dc.reset_doc_spine_cache_singleton_for_test()
    build, calls = _counted(_SPINE)
    _run(build)
    _run(build)
    assert calls["n"] == 2                       # 关缓存 → 每次都建


def test_get_or_build_doc_spine_builds_once_then_caches(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _fake_build(**kwargs):  # noqa: ANN003, ANN202
        calls["n"] += 1
        return _SPINE

    monkeypatch.setattr(dc, "build_doc_spine", _fake_build)
    out1 = dc.get_or_build_doc_spine(chunks=_CHUNKS, llm_client=object(), model="m")
    out2 = dc.get_or_build_doc_spine(chunks=_CHUNKS, llm_client=object(), model="m")
    assert out1 == _SPINE and out2 == _SPINE
    assert calls["n"] == 1                       # facade 也走缓存:建一次,第二次命中
