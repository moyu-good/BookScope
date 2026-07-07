"""Book-level 卷层缓存(WP-hierarchical-spine)单测 —— 临时 db,不调真 LLM。

覆盖:miss 建一次→hit 跳过、输入各异全 miss、短书 None 用哨兵缓存(不白跑)、空列表不缓存、
关缓存每次都建、peek 只对可用卷层命中、get_or_build 门面也走缓存。
"""

from __future__ import annotations

import bookscope.agent._internal.chapter_arc_cache as ac


def _setup_temp(monkeypatch, tmp_path):  # noqa: ANN001, ANN202
    monkeypatch.setenv(ac.ENV_DB_PATH, str(tmp_path / "arc_test.db"))
    monkeypatch.delenv(ac.ENV_DISABLED, raising=False)
    ac.reset_arc_cache_singleton_for_test()


_CHUNKS = [
    {"chunk_id": "c0", "chapter": 1, "text": "甲"},
    {"chunk_id": "c1", "chapter": 2, "text": "乙"},
]
_ARCS = [{"chapter_span": [1, 10], "title": "一", "evidence_chapters": [3]}]


def _counted(ret):  # noqa: ANN001, ANN202 — 返 (build_func, calls dict)
    calls = {"n": 0}

    def _build():
        calls["n"] += 1
        return ret

    return _build, calls


def _run(build, *, chunks=_CHUNKS, model="m", genre="fiction", min_chapters=40):  # noqa: ANN001, ANN202
    return ac.build_arc_layer_cached(
        all_chunks=chunks, model=model, genre=genre,
        min_chapters=min_chapters, build_func=build,
    )


def test_miss_builds_then_hit_skips_build(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    build, calls = _counted(_ARCS)
    assert _run(build) == _ARCS
    assert _run(build) == _ARCS
    assert calls["n"] == 1                       # 第二次命中,不重建


def test_different_inputs_miss(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    build, calls = _counted(_ARCS)
    _run(build)
    _run(build, genre="theory")                  # genre 变
    _run(build, model="m2")                      # model 变
    _run(build, min_chapters=30)                 # 阈值变 → 不同 key
    _run(build, chunks=[{"chunk_id": "x", "chapter": 1, "text": "丙"}])  # chunks 变
    assert calls["n"] == 5                        # 五次输入各异,全 miss


def test_short_book_none_cached_via_sentinel(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    # 短书构建返 None → 用哨兵缓存;第二次命中哨兵直接返 None,不重跑守卫 c
    _setup_temp(monkeypatch, tmp_path)
    build, calls = _counted(None)
    assert _run(build) is None
    assert _run(build) is None
    assert calls["n"] == 1                        # None 也缓存 → 第二次命中不重建


def test_empty_list_not_cached(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    # 空列表([])≠短书(None):空列表当失败,不写缓存,免得钉死
    _setup_temp(monkeypatch, tmp_path)
    build, calls = _counted([])
    _run(build)
    _run(build)
    assert calls["n"] == 2                        # 空列表不缓存 → 第二次还得重建


def test_disabled_always_builds(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    monkeypatch.setenv(ac.ENV_DISABLED, "1")
    ac.reset_arc_cache_singleton_for_test()
    build, calls = _counted(_ARCS)
    _run(build)
    _run(build)
    assert calls["n"] == 2                        # 关缓存 → 每次都建


def test_peek_hits_only_usable_arcs(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    # 没建过 → peek 返 None
    assert ac.peek_arc_cache(all_chunks=_CHUNKS, model="m") is None
    # 建一次卷层后 → peek 命中返卷层
    build, _ = _counted(_ARCS)
    _run(build)
    assert ac.peek_arc_cache(all_chunks=_CHUNKS, model="m", min_chapters=40) == _ARCS


def test_peek_short_book_sentinel_returns_none(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    # 短书哨兵已缓存 → peek 返 None(短书当「无卷层/不用建」,和真 miss 对调用方一样)
    _setup_temp(monkeypatch, tmp_path)
    build, _ = _counted(None)
    _run(build)
    assert ac.peek_arc_cache(all_chunks=_CHUNKS, model="m") is None


def test_get_or_build_arc_layer_builds_once_then_caches(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    _setup_temp(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _fake_build(**kwargs):  # noqa: ANN003, ANN202
        calls["n"] += 1
        return _ARCS

    monkeypatch.setattr(ac, "build_arc_layer", _fake_build)
    out1 = ac.get_or_build_arc_layer(
        spine=[{"chapter": 1}], all_chunks=_CHUNKS, llm_client=object(), model="m"
    )
    out2 = ac.get_or_build_arc_layer(
        spine=[{"chapter": 1}], all_chunks=_CHUNKS, llm_client=object(), model="m"
    )
    assert out1 == _ARCS and out2 == _ARCS
    assert calls["n"] == 1                        # 门面也走缓存:建一次,第二次命中


def test_get_or_build_arc_layer_passes_min_chapters_to_key(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    # 显式传 min_chapters 时,缓存键用同一值(不同阈值算不同 key)
    _setup_temp(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _fake_build(**kwargs):  # noqa: ANN003, ANN202
        calls["n"] += 1
        return _ARCS

    monkeypatch.setattr(ac, "build_arc_layer", _fake_build)
    ac.get_or_build_arc_layer(
        spine=[{"chapter": 1}], all_chunks=_CHUNKS, llm_client=object(), model="m",
        min_chapters=20,
    )
    ac.get_or_build_arc_layer(
        spine=[{"chapter": 1}], all_chunks=_CHUNKS, llm_client=object(), model="m",
        min_chapters=50,
    )
    assert calls["n"] == 2                        # 两个阈值 → 两个 key → 各建一次
