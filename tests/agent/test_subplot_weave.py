"""subplot_weave.generate_subplot_weave 单测（WP-subplot-weave）。

mock LLM（monkeypatch _invoke_client）+ 假 client，覆盖契约：
支线 + 交汇拼装 / 支线证据核验 / 交汇双端守卫（一端没命中就丢）/ 章号纠偏 /
parse 失败→None / 没支线→None / LLM 抛错→None / 截断抢救 / 去代码围栏 / 重试 /
active_chapters 归一去重升序 / 自交汇与缺端证据的交汇丢弃。
不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import subplot_weave as sw

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 3,
     "text": "玄德同关羽、张飞来到庄前。玄德下马，亲叩柴门。孔明昼寝未起，玄德拱立阶下。"},
    {"chunk_id": "c2", "chapter": 7,
     "text": "操执玄德手，同入小亭，已设樽俎。二人对坐，开怀畅饮，共论天下英雄。"},
    {"chunk_id": "c3", "chapter": 12,
     "text": "周瑜请孔明入帐议事，水路交兵，当以何兵器为先。孔明笑曰大江之上以弓箭为先。"},
]


class _FakeClient:
    def __init__(self, final_text: str, usage=(120, 30)) -> None:
        self._final = final_text
        self._usage = usage

    def extract_usage_tokens(self, resp):  # noqa: ANN001
        return self._usage

    def extract_final_text(self, resp):  # noqa: ANN001
        return self._final


def _patch_invoke(monkeypatch, *, raises: Exception | None = None):
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return {"usage": {}}
    monkeypatch.setattr(sw, "_invoke_client", _fake)


def test_success_builds_subplots_and_verifies_intersection(monkeypatch):
    weave_json = json.dumps({
        "subplots": [
            {"name": "三顾茅庐线", "active_chapters": [3],
             "evidence": "孔明昼寝未起，玄德拱立阶下"},
            {"name": "煮酒论英雄线", "active_chapters": [7],
             "evidence": "操执玄德手，同入小亭"},
            {"name": "赤壁备战线", "active_chapters": [12],
             "evidence": "周瑜请孔明入帐议事"},
        ],
        "intersections": [
            {"subplots": ["三顾茅庐线", "赤壁备战线"], "chapter": 12,
             "a_evidence": "孔明笑曰大江之上以弓箭为先",
             "b_evidence": "周瑜请孔明入帐议事"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="（整本书……）", chunks=_CHUNKS,
        llm_client=_FakeClient(weave_json), model="deepseek-v4-flash",
    )
    assert r is not None
    assert [s["name"] for s in r["subplots"]] == ["三顾茅庐线", "煮酒论英雄线", "赤壁备战线"]
    # 三条支线 evidence 都命中各自 chunk → verified
    assert all(s["verified"] for s in r["subplots"])
    # 交汇两端都命中 c3（章 12）→ 保留 + 双端 verified
    assert len(r["intersections"]) == 1
    inter = r["intersections"][0]
    assert inter["a_verified"] is True
    assert inter["b_verified"] is True
    assert inter["chapter"] == 12  # 真章号纠偏


def test_fabricated_subplot_evidence_unverified_but_kept(monkeypatch):
    """支线 evidence 编的（原文没有）→ verified=False，但泳道保留（主观构念不剔）。"""
    weave_json = json.dumps({
        "subplots": [
            {"name": "凭空捏造的支线", "active_chapters": [5],
             "evidence": "书里根本不存在的杜撰句子拿来测假阳性支线"},
        ],
        "intersections": [],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(weave_json), model="m",
    )
    assert r is not None
    assert len(r["subplots"]) == 1
    assert r["subplots"][0]["verified"] is False  # 没命中
    assert r["subplots"][0]["active_chapters"] == [5]  # 泳道仍在


def test_fake_intersection_dropped_when_one_side_uncited(monkeypatch):
    """伪交汇：一端原文核不过 → 整条交汇丢弃（双端守卫命根子）。"""
    weave_json = json.dumps({
        "subplots": [
            {"name": "线甲", "active_chapters": [3], "evidence": "孔明昼寝未起"},
            {"name": "线乙", "active_chapters": [7], "evidence": "操执玄德手"},
        ],
        "intersections": [
            {"subplots": ["线甲", "线乙"], "chapter": 3,
             "a_evidence": "孔明昼寝未起，玄德拱立阶下",  # 命中 c1
             "b_evidence": "这一端是编出来的、原文里没有的句子"},  # 没命中
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(weave_json), model="m",
    )
    assert r is not None
    assert r["intersections"] == []  # 一条腿站不住 → 不画


def test_parse_failure_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS,
        llm_client=_FakeClient("这不是 JSON，随便说点别的"), model="m",
    )
    assert r is None


def test_no_subplots_returns_none(monkeypatch):
    """没切出任何支线的编织图没意义 → None。"""
    weave_json = json.dumps({"subplots": [], "intersections": []}, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(weave_json), model="m",
    )
    assert r is None


def test_llm_raises_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient("{}"), model="m",
    )
    assert r is None


def test_active_chapters_normalized(monkeypatch):
    """active_chapters 去重 + 升序 + 非整数剔除。"""
    weave_json = json.dumps({
        "subplots": [
            {"name": "线", "active_chapters": [7, 3, 7, "五", 1],
             "evidence": "孔明昼寝未起"},
        ],
        "intersections": [],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(weave_json), model="m",
    )
    assert r is not None
    assert r["subplots"][0]["active_chapters"] == [1, 3, 7]


def test_self_intersection_and_missing_name_dropped(monkeypatch):
    """同名自交汇 / 缺第二条支线名的交汇丢弃。"""
    weave_json = json.dumps({
        "subplots": [{"name": "线甲", "active_chapters": [3], "evidence": "孔明昼寝未起"}],
        "intersections": [
            {"subplots": ["线甲", "线甲"], "chapter": 3,
             "a_evidence": "孔明昼寝未起", "b_evidence": "玄德拱立阶下"},  # 自交汇
            {"subplots": ["线甲"], "chapter": 3,
             "a_evidence": "孔明昼寝未起", "b_evidence": "玄德拱立阶下"},  # 缺第二条
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(weave_json), model="m",
    )
    assert r is not None
    assert r["intersections"] == []


def test_subplot_name_dedup(monkeypatch):
    """同名支线去重（先到先得）。"""
    weave_json = json.dumps({
        "subplots": [
            {"name": "线", "active_chapters": [3], "evidence": "孔明昼寝未起"},
            {"name": "线", "active_chapters": [7], "evidence": "操执玄德手"},
        ],
        "intersections": [],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(weave_json), model="m",
    )
    assert r is not None
    assert len(r["subplots"]) == 1
    assert r["subplots"][0]["active_chapters"] == [3]


def test_strips_code_fence(monkeypatch):
    inner = json.dumps({
        "subplots": [{"name": "线", "active_chapters": [3], "evidence": "孔明昼寝未起"}],
        "intersections": [],
    }, ensure_ascii=False)
    weave_json = "```json\n" + inner + "\n```"
    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(weave_json), model="m",
    )
    assert r is not None
    assert len(r["subplots"]) == 1


def test_salvages_truncated_json(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的支线，不整张图丢掉返 None。"""
    truncated = (
        '{"subplots": ['
        '{"name": "线甲", "active_chapters": [1, 2], "evidence": "孔明昼寝未起"},'
        '{"name": "线乙", "active_chapters": [3], "evidence": "操执玄德手"},'
        '{"name": "线丙", "active_cha'  # 这条被截断
    )
    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(truncated), model="m",
    )
    assert r is not None  # 没整张图丢掉
    assert [s["name"] for s in r["subplots"]] == ["线甲", "线乙"]  # 抢救到 2 条
    assert r["intersections"] == []  # 交汇没吐完 → 空


def test_retry_on_first_parse_failure(monkeypatch):
    """第一次 parse 失败 → 重试一次，第二次成功。"""
    good = json.dumps({
        "subplots": [{"name": "线", "active_chapters": [3], "evidence": "孔明昼寝未起"}],
        "intersections": [],
    }, ensure_ascii=False)
    seq = ["这不是 JSON", good]

    class _SeqClient:
        def extract_usage_tokens(self, resp):  # noqa: ANN001
            return (10, 5)

        def extract_final_text(self, resp):  # noqa: ANN001
            return seq.pop(0)

    _patch_invoke(monkeypatch)
    r = sw.generate_subplot_weave(
        full_text="x", chunks=_CHUNKS, llm_client=_SeqClient(), model="m",
    )
    assert r is not None
    assert len(r["subplots"]) == 1
