"""foreshadow_arcs.generate_foreshadow_arcs 单测（WP-foreshadow-payoff-arcs）。

mock LLM（monkeypatch _invoke_client）+ 假 client，覆盖契约：
伏笔配对 + 两端原文核验 / 章号纠偏 / 已回收实弧（resolved）/ 断弧两路（payoff null +
回收 evidence 核不过）/ 埋点核不过整条丢 / parse 失败→None / LLM 抛错→None /
截断抢救 / 去代码围栏 / 重试。不跑真 LLM。
"""

from __future__ import annotations

import json

from bookscope.agent import foreshadow_arcs as fa

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 2,
     "text": "墙角那柄断剑落满灰尘，老仆叮嘱少年莫要去碰，说它伤过人，认主。"},
    {"chunk_id": "c2", "chapter": 9,
     "text": "决战之夜，少年拔起墙角断剑，剑身嗡鸣认主，一剑挑落贼首。"},
    {"chunk_id": "c3", "chapter": 4,
     "text": "城东来了个白衣郎中，看了一眼少年的手相便摇头走了，再没出现。"},
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
    monkeypatch.setattr(fa, "_invoke_client", _fake)


def test_resolved_arc_builds_and_verifies(monkeypatch):
    """埋点 + 回收两端都挂上原文 → status=resolved，两端章号都被真章号纠偏。"""
    arcs_json = json.dumps({
        "arcs": [
            {"description": "墙角断剑认主，后来成了少年的兵器",
             "setup_chapter": 1, "payoff_chapter": 8,  # 模型自报章号偏，应被纠偏
             "setup_evidence": "墙角那柄断剑落满灰尘，老仆叮嘱少年莫要去碰",
             "payoff_evidence": "少年拔起墙角断剑，剑身嗡鸣认主，一剑挑落贼首"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="（整本书……）", chunks=_CHUNKS,
        llm_client=_FakeClient(arcs_json), model="deepseek-v4-flash",
    )
    assert r is not None
    assert len(r) == 1
    arc = r[0]
    assert arc["status"] == "resolved"
    assert arc["setup_verified"] is True
    assert arc["payoff_verified"] is True
    assert arc["setup_chapter"] == 2  # 命中 c1 真章号纠偏（模型自报 1）
    assert arc["payoff_chapter"] == 9  # 命中 c2 真章号纠偏（模型自报 8）


def test_dangling_arc_payoff_null(monkeypatch):
    """模型自己说没回收（payoff_chapter=null）→ status=dangling，回收端清空。"""
    arcs_json = json.dumps({
        "arcs": [
            {"description": "白衣郎中看了手相就走，再没出现",
             "setup_chapter": 4, "payoff_chapter": None,
             "setup_evidence": "城东来了个白衣郎中，看了一眼少年的手相便摇头走了",
             "payoff_evidence": ""},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arcs_json), model="m",
    )
    assert r is not None
    assert len(r) == 1
    arc = r[0]
    assert arc["status"] == "dangling"
    assert arc["setup_verified"] is True
    assert arc["setup_chapter"] == 4
    assert arc["payoff_chapter"] is None
    assert arc["payoff_evidence"] == ""
    assert arc["payoff_verified"] is False


def test_unverified_payoff_degrades_to_dangling(monkeypatch):
    """模型给了回收章 + 一段原文里没有的回收 evidence（伪回收）→ 降级成断弧，
    绝不强行画实弧（断弧假阳性的反面：宁可漏标回收也不冤报实弧）。"""
    arcs_json = json.dumps({
        "arcs": [
            {"description": "断剑认主",
             "setup_chapter": 2, "payoff_chapter": 9,
             "setup_evidence": "墙角那柄断剑落满灰尘，老仆叮嘱少年莫要去碰",
             "payoff_evidence": "书里根本没有的杜撰回收句子拿来测伪回收"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arcs_json), model="m",
    )
    assert r is not None
    assert len(r) == 1
    arc = r[0]
    assert arc["status"] == "dangling"  # 回收核不过 → 当断弧
    assert arc["payoff_chapter"] is None
    assert arc["payoff_evidence"] == ""
    assert arc["payoff_verified"] is False


def test_unverified_setup_drops_whole_arc(monkeypatch):
    """埋点 evidence 原文里没有 → 整条弧丢（连埋点都站不住，不算伏笔）。"""
    arcs_json = json.dumps({
        "arcs": [
            {"description": "编出来的伏笔",
             "setup_chapter": 3, "payoff_chapter": 9,
             "setup_evidence": "书里根本没有的杜撰埋点句子",
             "payoff_evidence": "少年拔起墙角断剑，剑身嗡鸣认主，一剑挑落贼首"},
            {"description": "真伏笔留着",
             "setup_chapter": 2, "payoff_chapter": 9,
             "setup_evidence": "墙角那柄断剑落满灰尘，老仆叮嘱少年莫要去碰",
             "payoff_evidence": "少年拔起墙角断剑，剑身嗡鸣认主，一剑挑落贼首"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arcs_json), model="m",
    )
    assert r is not None
    assert len(r) == 1  # 埋点核不过的那条被滤掉
    assert r[0]["description"] == "真伏笔留着"


def test_sorted_by_setup_chapter(monkeypatch):
    """多条弧按 setup_chapter 升序。"""
    arcs_json = json.dumps({
        "arcs": [
            {"description": "晚埋的", "setup_chapter": 4, "payoff_chapter": None,
             "setup_evidence": "城东来了个白衣郎中，看了一眼少年的手相便摇头走了",
             "payoff_evidence": ""},
            {"description": "早埋的", "setup_chapter": 2, "payoff_chapter": 9,
             "setup_evidence": "墙角那柄断剑落满灰尘，老仆叮嘱少年莫要去碰",
             "payoff_evidence": "少年拔起墙角断剑，剑身嗡鸣认主，一剑挑落贼首"},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arcs_json), model="m",
    )
    assert r is not None
    assert [a["setup_chapter"] for a in r] == [2, 4]


def test_parse_failure_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS,
        llm_client=_FakeClient("这不是 JSON，随便说点别的"), model="m",
    )
    assert r is None


def test_empty_arcs_returns_none(monkeypatch):
    arcs_json = json.dumps({"arcs": []}, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arcs_json), model="m",
    )
    assert r is None  # 没弧的图没意义


def test_all_setup_unverified_returns_empty_list(monkeypatch):
    """parse 出弧但全部埋点核不过 → 返回空 list（不是 None，扫过了只是都没站住）。"""
    arcs_json = json.dumps({
        "arcs": [
            {"description": "编的", "setup_chapter": 3, "payoff_chapter": None,
             "setup_evidence": "书里根本没有的杜撰埋点", "payoff_evidence": ""},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arcs_json), model="m",
    )
    assert r == []  # 扫过、解析成功，但没有挂得上原文的伏笔


def test_llm_raises_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient("{}"), model="m",
    )
    assert r is None


def test_non_integer_setup_chapter_dropped(monkeypatch):
    """setup_chapter 非整数的条目丢弃；整数的保留。"""
    arcs_json = json.dumps({
        "arcs": [
            {"description": "章号坏", "setup_chapter": "二", "payoff_chapter": None,
             "setup_evidence": "墙角那柄断剑落满灰尘", "payoff_evidence": ""},
            {"description": "好的", "setup_chapter": 2, "payoff_chapter": None,
             "setup_evidence": "墙角那柄断剑落满灰尘，老仆叮嘱少年莫要去碰",
             "payoff_evidence": ""},
        ],
    }, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arcs_json), model="m",
    )
    assert r is not None
    assert [a["setup_chapter"] for a in r] == [2]


def test_strips_code_fence(monkeypatch):
    inner = json.dumps({
        "arcs": [
            {"description": "断剑", "setup_chapter": 2, "payoff_chapter": None,
             "setup_evidence": "墙角那柄断剑落满灰尘，老仆叮嘱少年莫要去碰",
             "payoff_evidence": ""},
        ],
    }, ensure_ascii=False)
    arcs_json = "```json\n" + inner + "\n```"
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(arcs_json), model="m",
    )
    assert r is not None
    assert len(r) == 1


def test_salvages_truncated_json(monkeypatch):
    """reasoning 吃 token 致 JSON 截断 → 抢救已闭合的弧，不整张图丢掉返 None。"""
    truncated = (
        '{"arcs": ['
        '{"description": "断剑认主", "setup_chapter": 2, "payoff_chapter": null, '
        '"setup_evidence": "墙角那柄断剑落满灰尘，老仆叮嘱少年莫要去碰", '
        '"payoff_evidence": ""},'
        '{"description": "白衣郎中", "setup_chapter": 4, "payoff_chapter": null, '
        '"setup_evidence": "城东来了个白衣郎中，看了一眼少年的手相便摇头走了", '
        '"payoff_evidence": ""},'
        '{"description": "截断的第三条", "setup_chapter": 5, "setu'  # 截断
    )
    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_FakeClient(truncated), model="m",
    )
    assert r is not None  # 没整张图丢掉
    assert [a["setup_chapter"] for a in r] == [2, 4]  # 抢救到 2 条，截断的第 3 条丢弃


def test_retry_on_first_parse_failure(monkeypatch):
    """第一次 parse 失败 → 重试一次，第二次成功。"""
    good = json.dumps({
        "arcs": [
            {"description": "断剑", "setup_chapter": 2, "payoff_chapter": None,
             "setup_evidence": "墙角那柄断剑落满灰尘，老仆叮嘱少年莫要去碰",
             "payoff_evidence": ""},
        ],
    }, ensure_ascii=False)
    seq = ["这不是 JSON", good]

    class _SeqClient:
        def extract_usage_tokens(self, resp):  # noqa: ANN001
            return (10, 5)

        def extract_final_text(self, resp):  # noqa: ANN001
            return seq.pop(0)

    _patch_invoke(monkeypatch)
    r = fa.generate_foreshadow_arcs(
        full_text="x", chunks=_CHUNKS, llm_client=_SeqClient(), model="m",
    )
    assert r is not None
    assert len(r) == 1
