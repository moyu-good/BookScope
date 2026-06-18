"""character_voice.generate_character_voice 单测（声口一致）。

mock _invoke_client + 假 client，覆盖契约：
- 成功返 {features, drift_items}，features 带 verified、drift 已 verify-filter；
- drift 核不过的整条丢（命根子之一：挂不上原文的 drift 不报）；
- features 核不过的留着标 verified=False（描述性特征不剔，前端淡化）；
- sample_too_small 透传（样本不足明说，不硬下 drift）；
- 解析失败返 None / LLM 抛异常返 None / 角色名空返 None；
- 章号纠偏 / 截断抢救 / 重试。
"""

from __future__ import annotations

import json

from bookscope.agent import character_voice as cv

_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": "张飞大喝：俺也一样！俺也一样！吓退百万曹军。"},
    {
        "chunk_id": "c2",
        "chapter": 8,
        "text": "张飞捻须沉吟，缓缓道：依在下浅见，此事当从长计议，徐徐图之。",
    },
]


class _FakeClient:
    """extract_final_text 按次回下一条（单条 str 或多条 list 测重试）。"""

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

    monkeypatch.setattr(cv, "_invoke_client", _fake)


def _gen(client, character="张飞"):  # noqa: ANN001
    return cv.generate_character_voice(
        character=character, full_text="x", chunks=_CHUNKS, llm_client=client, model="m"
    )


def test_success_features_kept_and_drift_verify_filtered(monkeypatch):
    # 一条特征命中 c1（verified）；一条 drift 命中 c2（章号纠偏到 8、verified、保留）
    final = json.dumps(
        {
            "sample_too_small": False,
            "features": [
                {"trait": "说话粗豪、爱重复", "evidence": "俺也一样！俺也一样！"}
            ],
            "drift_items": [
                {
                    "chapter": 99,
                    "quote": "依在下浅见，此事当从长计议，徐徐图之",
                    "reason": "粗人张飞不该文绉绉地说这话",
                }
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(final))
    assert r is not None
    assert r["sample_too_small"] is False
    assert len(r["features"]) == 1
    assert r["features"][0]["verified"] is True
    assert len(r["drift_items"]) == 1
    assert r["drift_items"][0]["verified"] is True
    assert r["drift_items"][0]["chapter"] == 8  # 99 → 真章号 8 纠偏


def test_unverified_drift_dropped(monkeypatch):
    # 命根子：drift 的 quote 原文里没有 → 整条丢（不报一面之词的 drift）
    final = json.dumps(
        {
            "features": [],
            "drift_items": [
                {"chapter": 5, "quote": "这句对白原文里根本没有", "reason": "编的"}
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(final))
    assert r is not None
    assert r["drift_items"] == []


def test_unverified_feature_kept_low_confidence(monkeypatch):
    # 特征核不过留着标 verified=False（描述性特征不剔，前端淡化）——区别于 drift 的剔除
    final = json.dumps(
        {
            "features": [
                {"trait": "语气", "evidence": "原文里没有这句代表对白"}
            ],
            "drift_items": [],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(final))
    assert len(r["features"]) == 1
    assert r["features"][0]["verified"] is False


def test_sample_too_small_passthrough(monkeypatch):
    # 命根子：样本不足明说，不硬下 drift 判定
    final = json.dumps(
        {"sample_too_small": True, "features": [], "drift_items": []},
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(final), character="路人甲")
    assert r is not None
    assert r["sample_too_small"] is True
    assert r["features"] == []
    assert r["drift_items"] == []


def test_stable_voice_empty_drift_is_valid(monkeypatch):
    # 声口很稳、没扫出 drift（features 有、drift 空）也是合法结果，不是 None
    final = json.dumps(
        {
            "features": [{"trait": "粗豪", "evidence": "俺也一样！俺也一样！"}],
            "drift_items": [],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(final))
    assert r is not None
    assert len(r["features"]) == 1
    assert r["drift_items"] == []


def test_drops_traitless_feature(monkeypatch):
    final = json.dumps(
        {
            "features": [
                {"evidence": "俺也一样！俺也一样！"},  # 缺 trait → 丢
                {"trait": "粗豪", "evidence": "俺也一样！俺也一样！"},
            ],
            "drift_items": [],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(final))
    assert len(r["features"]) == 1
    assert r["features"][0]["trait"] == "粗豪"


def test_parse_failure_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    assert _gen(_FakeClient("这不是 JSON，随便说点别的")) is None


def test_llm_raises_returns_none(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    assert _gen(_FakeClient("{}")) is None


def test_empty_character_returns_none(monkeypatch):
    _patch_invoke(monkeypatch)
    assert _gen(_FakeClient("{}"), character="  ") is None


def test_salvage_truncated(monkeypatch):
    # 截断 JSON（drift_items 数组没收尾）→ 抢救出已闭合的 feature + drift
    truncated = (
        '{"sample_too_small": false, "features": [{"trait": "粗豪", '
        '"evidence": "俺也一样！俺也一样！"}], "drift_items": [{"chapter": 8, '
        '"quote": "依在下浅见，此事当从长计议，徐徐图之", "reason": "太文"}, '
        '{"chapter": 9, "quote": "未闭合'
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(truncated))
    assert r is not None
    assert len(r["features"]) == 1
    assert len(r["drift_items"]) == 1  # 第二条截断丢，第一条抢救保留
    assert r["drift_items"][0]["verified"] is True


def test_retry_recovers_on_second_attempt(monkeypatch):
    good = json.dumps(
        {
            "features": [{"trait": "粗豪", "evidence": "俺也一样！俺也一样！"}],
            "drift_items": [],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _gen(_FakeClient(["坏 JSON", good]))  # 第一次坏、第二次好
    assert r is not None
    assert len(r["features"]) == 1
