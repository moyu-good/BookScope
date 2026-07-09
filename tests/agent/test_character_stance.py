"""character_stance.generate_character_stance 单测（立场判定 Toulmin）。

mock _invoke_client + 假 client，覆盖契约：
- 成功返 {name, pos, neg, pro, con, net, dispute, dispute_reason}，pro/con 各条挂 verified；
- 正反两方都保留（争议判断两方并陈，不 verify-filter 掉一方）；
- 清晰单边：一方原文里没有 → 空数组照样返（不硬凑）；
- net / dispute 越界夹回 [-5,5] / [0,5]；
- 解析失败返 None / net 为空返 None（重试后仍空）/ LLM 抛异常返 None。
"""

from __future__ import annotations

import json

from bookscope.agent import character_stance as cs

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": "操曰：吾始兴大义，为国除贼，何敢有他望。"},
    {"chunk_id": "c2", "chapter": 78, "text": "册立操为魏王，设天子旌旗，出警入跸。"},
]


class _FakeClient:
    def __init__(self, finals) -> None:  # noqa: ANN001
        self._texts = [finals] if isinstance(finals, str) else list(finals)
        self._i = 0

    def extract_final_text(self, resp):  # noqa: ANN001
        t = self._texts[min(self._i, len(self._texts) - 1)]
        self._i += 1
        return t


def _patch_invoke(monkeypatch, *, raises: Exception | None = None) -> None:
    def _fake(*_a, **_k):
        if raises is not None:
            raise raises
        return {"usage": {}}

    monkeypatch.setattr(cs, "_invoke_client", _fake)


def _gen(client, character="曹操"):  # noqa: ANN001
    return cs.generate_character_stance(
        character=character,
        full_text="x",
        chunks=_CHUNKS,
        llm_client=client,
        model="m",
        pos_label="尊汉扶主",
        neg_label="篡逆自立",
    )


def test_success_both_sides_kept_and_verified(monkeypatch):
    final = json.dumps(
        {
            "pro": [{"原文": "吾始兴大义，为国除贼", "说明": "讨贼扶汉"}],
            "con": [{"原文": "册立操为魏王，设天子旌旗", "说明": "僭越篡逆"}],
            "net": -2,
            "dispute": 4,
            "dispute_reason": "正反皆有硬证据",
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(final))
    assert r is not None
    assert r["name"] == "曹操" and r["pos"] == "尊汉扶主" and r["neg"] == "篡逆自立"
    assert len(r["pro"]) == 1 and len(r["con"]) == 1  # 两方都保留
    assert r["pro"][0]["verified"] is True  # 命中 c1
    assert r["con"][0]["verified"] is True  # 命中 c2
    assert r["net"] == -2 and r["dispute"] == 4


def test_clear_one_sided_empty_kept(monkeypatch):
    # 清晰尊汉：con 原文里没有 → 空数组照返，不硬凑
    final = json.dumps(
        {
            "pro": [{"原文": "吾始兴大义，为国除贼", "说明": "扶汉"}],
            "con": [],
            "net": 5,
            "dispute": 0,
            "dispute_reason": "一边倒",
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(final))
    assert r is not None
    assert len(r["pro"]) == 1 and r["con"] == []
    assert r["net"] == 5 and r["dispute"] == 0


def test_unverified_evidence_kept_flagged(monkeypatch):
    # 原文里查不到的 evidence 保留但 verified=False（两方并陈让人自己核，不剔）
    final = json.dumps(
        {"pro": [{"原文": "这句书里根本没有", "说明": "x"}], "con": [], "net": 3, "dispute": 1},
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(final))
    assert r is not None and len(r["pro"]) == 1
    assert r["pro"][0]["verified"] is False


def test_clamps_out_of_range(monkeypatch):
    final = json.dumps({"pro": [], "con": [], "net": -99, "dispute": 42}, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(final))
    assert r is not None and r["net"] == -5 and r["dispute"] == 5


def test_parse_fail_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    assert _gen(_FakeClient(["不是 json", "还不是 json"])) is None


def test_net_missing_returns_none(monkeypatch):
    # parse 成功但没 net（不是合法立场判断）→ 重试后仍无 → None
    final = json.dumps({"pro": [], "con": []}, ensure_ascii=False)
    _patch_invoke(monkeypatch)
    assert _gen(_FakeClient([final, final])) is None


def test_llm_exception_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    assert _gen(_FakeClient("{}")) is None


# ---------------------------------------------------------------------------
# batch_stance_positions —— 立场格局批量粗定位（probe exp032 GO）
# ---------------------------------------------------------------------------


def _batch(client, characters=None):  # noqa: ANN001
    return cs.batch_stance_positions(
        characters=characters if characters is not None else ["曹操", "诸葛亮", "董卓"],
        pos_label="尊汉扶主",
        neg_label="篡逆自立",
        full_text="x",
        llm_client=client,
        model="m",
    )


def test_batch_success_array(monkeypatch):
    final = json.dumps(
        [
            {"name": "曹操", "net": 0, "dispute": 4, "brief": "尊汉与篡逆两说皆有据"},
            {"name": "诸葛亮", "net": 5, "dispute": 0, "brief": "毕生扶汉"},
            {"name": "董卓", "net": -5, "dispute": 0, "brief": "废立擅权"},
        ],
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _batch(_FakeClient(final))
    assert r is not None and len(r) == 3
    by = {d["name"]: d for d in r}
    assert by["诸葛亮"]["net"] == 5 and by["董卓"]["net"] == -5
    assert by["曹操"]["dispute"] == 4 and by["曹操"]["brief"]


def test_batch_people_key_wrapper(monkeypatch):
    # 模型把数组裹在 {"people": [...]} 里也认；brief 缺省为空串
    final = json.dumps(
        {"people": [{"name": "曹操", "net": -1, "dispute": 3}]}, ensure_ascii=False
    )
    _patch_invoke(monkeypatch)
    r = _batch(_FakeClient(final), characters=["曹操"])
    assert r is not None and r[0]["name"] == "曹操" and r[0]["brief"] == ""


def test_batch_bracket_slice_fallback(monkeypatch):
    # 数组前后裹解释文字 → 兜底切首个 [...]
    final = '这是结果：\n[{"name": "曹操", "net": 0, "dispute": 3}]\n以上。'
    _patch_invoke(monkeypatch)
    r = _batch(_FakeClient(final), characters=["曹操"])
    assert r is not None and r[0]["name"] == "曹操" and r[0]["net"] == 0


def test_batch_clamps_and_skips_bad(monkeypatch):
    final = json.dumps(
        [
            {"name": "曹操", "net": -99, "dispute": 42},  # 越界夹回
            {"name": "", "net": 1},  # 空名跳过
            {"name": "关羽"},  # 无 net 跳过（不臆造位置）
            {"name": "貂蝉", "net": 2, "dispute": 1},  # 没请求的名字跳过
        ],
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _batch(_FakeClient(final), characters=["曹操", "关羽"])
    assert r is not None and len(r) == 1
    assert r[0]["name"] == "曹操" and r[0]["net"] == -5 and r[0]["dispute"] == 5


def test_batch_empty_characters_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    assert _batch(_FakeClient("[]"), characters=[]) is None


def test_batch_parse_fail_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    assert _batch(_FakeClient("既不是 json 也不是数组")) is None


def test_batch_all_items_bad_returns_none(monkeypatch):
    # 解析出数组但一个有效项都没有（全无 net / 全非请求名）→ None
    final = json.dumps(
        [{"name": "关羽"}, {"name": "赵云", "net": 3}], ensure_ascii=False
    )
    _patch_invoke(monkeypatch)
    assert _batch(_FakeClient(final), characters=["关羽"]) is None


def test_batch_llm_exception_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    assert _batch(_FakeClient("[]")) is None
