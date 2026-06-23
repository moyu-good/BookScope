"""argument_structure.generate_argument_structure_exhaustive 单测（穷尽化 map-reduce）。

monkeypatch 模块里的 run_segments 返两段造好的条目，验证：同一 claim 跨段去重、
不同章 claim 按章重排 + order 重编号 1..N、合并后 evidence 过核验命中。不调真 LLM。
"""

from __future__ import annotations

from bookscope.agent import argument_structure as ar

# 两段原文当证据登记表：让合并后的 evidence 逐字命中并纠偏章号。
_CHUNKS = [
    {"chunk_id": "c1", "chapter": 1, "text": "制内市场是国家主导型政治经济的核心机制。"},
    {"chunk_id": "c2", "chapter": 4, "text": "政府通过制度安排把市场嵌入国家治理框架。"},
]


def _cl(order, claim, chapter, evidence):  # noqa: ANN001
    return {"order": order, "claim": claim, "chapter": chapter, "evidence": evidence}


def _patch_segments(monkeypatch, outs) -> None:  # noqa: ANN001
    """替掉模块里的 run_segments，直接喂两段造好的条目列表（不过 LLM）。"""
    monkeypatch.setattr(ar, "run_segments", lambda **_k: outs)


def _gen(monkeypatch, outs):  # noqa: ANN001
    _patch_segments(monkeypatch, outs)
    return ar.generate_argument_structure_exhaustive(
        chunks=_CHUNKS, llm_client=object(), model="m"
    )


def test_dedups_reorders_and_reverifies(monkeypatch):
    # 第二段的「市场嵌入治理」章号 99 错，evidence 命中 c2 应纠到 4；
    # 「制内市场」跨两段重复，按 claim 去重只留首见（第一段的 order/chapter）。
    seg1 = [
        _cl(1, "制内市场是核心机制", 1, "制内市场是国家主导型政治经济的核心机制"),
        _cl(2, "市场嵌入治理", 99, "政府通过制度安排把市场嵌入国家治理框架"),
    ]
    seg2 = [
        _cl(1, "制内市场是核心机制", 1, "制内市场是国家主导型政治经济的核心机制"),  # 跨段重复
    ]
    cls = _gen(monkeypatch, [seg1, seg2])
    assert cls is not None and len(cls) == 2  # 重复的 claim 去掉一条
    # 按章号重排：c1(章1) 在前、c2 纠偏到章4 在后
    assert [c["chapter"] for c in cls] == [1, 4]
    # order 按重排后重新编号 1..N（不沿用段内序号）
    assert [c["order"] for c in cls] == [1, 2]
    assert cls[0]["claim"] == "制内市场是核心机制"
    assert cls[1]["claim"] == "市场嵌入治理"
    # 合并后一次性核验：两条 evidence 都逐字命中
    assert all(c["verified"] for c in cls)


def test_empty_merge_returns_none(monkeypatch):
    assert _gen(monkeypatch, [[], []]) is None


def test_drops_claimless_items(monkeypatch):
    # key_fn 返 None（claim 字段缺）的条目应被 merge_by_key 丢掉。
    seg = [
        _cl(1, "制内市场是核心机制", 1, "制内市场是国家主导型政治经济的核心机制"),
        {"order": 2, "chapter": 4, "evidence": "无 claim 字段"},
    ]
    cls = _gen(monkeypatch, [seg])
    assert cls is not None and len(cls) == 1
    assert cls[0]["claim"] == "制内市场是核心机制"
