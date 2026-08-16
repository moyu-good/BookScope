"""Book-level 章脉缓存(ADR-010 第5步)单测 —— 临时 db,不调真 LLM。"""

from __future__ import annotations

import threading
import time

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
_SPINE_TWO = [
    {"chapter": 1, "tension": 5, "present": ["甲"], "evidence": "x"},
    {"chapter": 2, "tension": 6, "present": ["乙"], "evidence": "y"},
]


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
        return _SPINE_TWO

    monkeypatch.setattr(sc, "build_chapter_spine", _fake_build)
    out1 = sc.get_or_build_spine(chunks=_CHUNKS, llm_client=object(), model="m")
    out2 = sc.get_or_build_spine(chunks=_CHUNKS, llm_client=object(), model="m")
    assert out1 == _SPINE_TWO and out2 == _SPINE_TWO
    assert calls["n"] == 1                       # facade 也走缓存:建一次,第二次命中


def test_chapter_level_incremental_only_builds_changed_chapter(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """按章增量：改第 2 章内容 → 只重跑第 2 章，第 1 章缓存照用。"""
    _setup_temp(monkeypatch, tmp_path)
    calls: list[list[dict]] = []

    def _fake_build(**kwargs):  # noqa: ANN003, ANN202
        built = []
        for rec in _SPINE_TWO:
            # 只返回这次传入 chunks 里出现的章（模拟真实 build 只处理子集）
            if any(c["chapter"] == rec["chapter"] for c in kwargs["chunks"]):
                built.append(dict(rec))
        calls.append(kwargs["chunks"])
        return built

    monkeypatch.setattr(sc, "build_chapter_spine", _fake_build)

    # 首次：两章都缺 → 一次建两章
    sc.get_or_build_spine(chunks=_CHUNKS, llm_client=object(), model="m")
    assert len(calls) == 1
    assert {c["chapter"] for c in calls[0]} == {1, 2}

    # 第 2 章改了（文本乙→乙2）
    changed = [
        {"chunk_id": "c0", "chapter": 1, "text": "甲"},
        {"chunk_id": "c1", "chapter": 2, "text": "乙2"},
    ]
    out = sc.get_or_build_spine(chunks=changed, llm_client=object(), model="m")
    # 只多建了一次，且这次只传了第 2 章的 chunks
    assert len(calls) == 2
    assert {c["chapter"] for c in calls[1]} == {2}
    # 返回 = 第 1 章旧缓存 + 第 2 章新建
    by_ch = {r["chapter"]: r for r in out}
    assert by_ch[1]["tension"] == 5  # 第 1 章来自旧缓存（没重跑）
    assert by_ch[2]["tension"] == 6
    assert len(out) == 2


def test_peek_returns_partial_spine(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """渐进：只建了第 1 章时 peek 返回部分，spine_build_progress 报 1/2。"""
    _setup_temp(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _fake_build(**kwargs):  # noqa: ANN003, ANN202
        calls["n"] += 1
        return [dict(_SPINE[0])]  # 只返回第 1 章

    monkeypatch.setattr(sc, "build_chapter_spine", _fake_build)
    sc.get_or_build_spine(chunks=_CHUNKS, llm_client=object(), model="m")
    partial = sc.peek_spine_cache(chunks=_CHUNKS, model="m")
    assert [r["chapter"] for r in partial] == [1]
    prog = sc.spine_build_progress(chunks=_CHUNKS, model="m")
    assert prog["built"] == 1 and prog["total"] == 2
    assert prog["missing_chapters"] == [2]


def test_single_flight_concurrent_same_key_builds_once(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """单飞:两个线程并发建同一条章脉,只该真建一遍(预热 + viz 点击撞上时不重复建)。"""
    _setup_temp(monkeypatch, tmp_path)
    calls = {"n": 0}
    started = threading.Event()  # leader 已进入 build_func
    release = threading.Event()  # 测试放行 leader 完成(制造重叠窗口)

    def _slow_build():  # noqa: ANN202
        calls["n"] += 1
        started.set()
        release.wait(3.0)
        return _SPINE

    results: dict[str, list] = {}

    def _worker(tag: str) -> None:
        results[tag] = _run(_slow_build)

    t1 = threading.Thread(target=_worker, args=("a",))
    t1.start()
    assert started.wait(3.0)          # 等 leader 真进了 build(此时 inflight 已登记这条 key)
    t2 = threading.Thread(target=_worker, args=("b",))
    t2.start()
    time.sleep(0.1)                   # 给 t2 时间走到"等 leader"分支
    release.set()                     # 放行 leader 完成、写缓存、放行等待方
    t1.join(5.0)
    t2.join(5.0)
    assert calls["n"] == 1            # 并发同 key 只建一遍
    assert results["a"] == _SPINE and results["b"] == _SPINE  # 两个线程拿到同一条章脉


def test_single_flight_different_keys_dont_block(monkeypatch, tmp_path) -> None:  # noqa: ANN001
    """不同 key 各建各的,单飞不该把它们串起来(别误伤并发不同书)。"""
    _setup_temp(monkeypatch, tmp_path)
    build, calls = _counted(_SPINE)
    _run(build)                                   # key1
    _run(build, model="m2")                       # key2:不同 key,照常各建
    assert calls["n"] == 2
