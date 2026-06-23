"""Book-level 章脉缓存(ADR-010 第5步)单测 —— 临时 db,不调真 LLM。"""

from __future__ import annotations

import bookscope.agent._internal.chapter_spine_cache as sc


def _setup_temp(monkeypatch, tmp_path):  # noqa: ANN001, ANN202
    monkeypatch.setenv(sc.ENV_DB_PATH, str(tmp_path / "spine_test.db"))
    monkeypatch.delenv(sc.ENV_DISABLED, raising=False)
    sc.reset_spine_cache_singleton_for_test()


_CHUNKS = [
    {"chunk_id": "c0", "chapter": 1, "text": "甲"},
    {"chunk_id": "c1", "chapter": 2, "text": "乙"},
]
_SPINE = [{"chapter": 1, "tension": 5, "present": ["甲"], "evidence": "x"}]


def _counted(ret):  # noqa: ANN001, ANN202 — 返 (build_func, calls dict)
    calls = {"n": 0}

    def _build():
        calls["n"] += 1
        return ret

    return _build, calls


def _run(build, *, chunks=_CHUNKS, model="m", genre="fiction"):  # noqa: ANN001, ANN202
    return sc.build_chapter_spine_cached(
        all_chunks=chunks, model=model, genre=genre, build_func=build
    )


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
    _run(build, genre="theory")                 # genre 变
    _run(build, model="m2")                     # model 变
    _run(build, chunks=[{"chunk_id": "x", "chapter": 1, "text": "丙"}])  # chunks 变
    assert calls["n"] == 4                       # 四次输入各异,全 miss


def test_empty_spine_not_cached(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    build, calls = _counted([])
    _run(build)
    _run(build)
    assert calls["n"] == 2                       # 空章脉不写缓存 → 第二次还得重建


def test_disabled_always_builds(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    monkeypatch.setenv(sc.ENV_DISABLED, "1")
    sc.reset_spine_cache_singleton_for_test()
    build, calls = _counted(_SPINE)
    _run(build)
    _run(build)
    assert calls["n"] == 2                       # 关缓存 → 每次都建


def test_get_or_build_spine_builds_once_then_caches(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _fake_build(**kwargs):  # noqa: ANN003, ANN202
        calls["n"] += 1
        return _SPINE

    monkeypatch.setattr(sc, "build_chapter_spine", _fake_build)
    out1 = sc.get_or_build_spine(chunks=_CHUNKS, llm_client=object(), model="m")
    out2 = sc.get_or_build_spine(chunks=_CHUNKS, llm_client=object(), model="m")
    assert out1 == _SPINE and out2 == _SPINE
    assert calls["n"] == 1                       # facade 也走缓存:建一次,第二次命中
