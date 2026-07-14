"""argument_structure.generate_argument_tree 单测（论点结构骨架树，probe exp034 GO）。

mock _invoke_client + 假 client，不打真 LLM（主 Claude 有 key 做 live 验）。覆盖契约：

- 成功成树：thesis + ≥2 论点，逐个带 role / supports / quote_verified；
- 引文核验片段兜底：verbatim 过、"……"拼接靠片段过（整条子串会挂，exp022/034 教训）；
- supports 悬空（指向不存在的 id）→ 落 "thesis"（不悬空，exp034 尺子③）；
- role 越界落「支撑」；重名 id 去重；
- graceful 空：非论说题材 / 抽不出 thesis / 有效论点 < 2 / 解析失败 / LLM 抛异常。
"""

from __future__ import annotations

import json

from bookscope.agent import argument_structure as arg

# 假"理论书"：一句中心论点 + 三句可锚的论点，句读用中文句号（归一后成 .）。
_BOOK = (
    "本书的中心论点是国家能力决定现代化的成败。"
    "现代国家的形成是现代化的起点和基础。"
    "有效治理比照搬西方模式更能增进长远福祉。"
    "大国无法在霸权体系里靠搭便车实现现代化。"
)
# verify_citations 用的最小 chunk（带原文）；quote_verified 走核验或片段兜底，都稳。
_CHUNKS = [{"chunk_id": "c1", "chapter": 1, "text": _BOOK}]


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

    monkeypatch.setattr(arg, "_invoke_client", _fake)


def _tree(client, *, genre: str | None = "theory"):  # noqa: ANN001
    return arg.generate_argument_tree(
        full_text=_BOOK, chunks=_CHUNKS, llm_client=client, model="m", genre=genre
    )


def test_success_tree(monkeypatch):
    final = json.dumps(
        {
            "thesis": {
                "claim": "国家能力决定现代化的成败",
                "quote": "本书的中心论点是国家能力决定现代化的成败",
                "from_book": "开篇点题",
            },
            "claims": [
                {
                    "id": "c1",
                    "claim": "建成现代国家是起点",
                    "role": "前提",
                    "supports": "thesis",
                    "quote": "现代国家的形成是现代化的起点和基础",
                    "brief": "起点",
                },
                {
                    "id": "c2",
                    "claim": "有效治理胜过照搬西方",
                    "role": "支撑",
                    "supports": "c1",
                    "quote": "有效治理比照搬西方模式更能增进长远福祉",
                    "brief": "治理",
                },
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _tree(_FakeClient(final))
    assert r["scanned"] is True
    assert r["thesis"]["claim"] == "国家能力决定现代化的成败"
    assert r["thesis"]["quote_verified"] is True
    assert len(r["claims"]) == 2
    by = {c["id"]: c for c in r["claims"]}
    assert by["c1"]["role"] == "前提" and by["c1"]["supports"] == "thesis"
    assert by["c2"]["supports"] == "c1"  # 真层级：挂到别的论点，不是一律挂 thesis
    assert by["c1"]["quote_verified"] is True and by["c2"]["quote_verified"] is True


def test_ellipsis_join_verified_by_fragment(monkeypatch):
    # 模型把不相邻两句用"……"拼一条 + 内嵌「」——整条子串比对必挂，靠片段核过
    final = json.dumps(
        {
            "thesis": {"claim": "国家能力决定现代化", "quote": "国家能力决定现代化的成败"},
            "claims": [
                {
                    "id": "c1",
                    "claim": "起点论",
                    "role": "前提",
                    "supports": "thesis",
                    "quote": "「现代国家的形成」是现代化的起点和基础……"
                    "大国无法在霸权体系里靠搭便车实现现代化",
                },
                {
                    "id": "c2",
                    "claim": "治理论",
                    "role": "支撑",
                    "supports": "thesis",
                    "quote": "有效治理比照搬西方模式更能增进长远福祉",
                },
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _tree(_FakeClient(final))
    assert r["scanned"] is True
    by = {c["id"]: c for c in r["claims"]}
    assert by["c1"]["quote_verified"] is True  # 拼接引文靠片段核过


def test_dangling_supports_falls_back_to_thesis(monkeypatch):
    final = json.dumps(
        {
            "thesis": {"claim": "中心", "quote": "国家能力决定现代化的成败"},
            "claims": [
                {
                    "id": "c1",
                    "claim": "甲",
                    "role": "支撑",
                    "supports": "c99",  # 指向不存在的 id → 悬空 → 落 thesis
                    "quote": "现代国家的形成是现代化的起点和基础",
                },
                {
                    "id": "c2",
                    "claim": "乙",
                    "role": "乱填角色",  # 越界 → 落「支撑」
                    "supports": "c1",
                    "quote": "有效治理比照搬西方模式更能增进长远福祉",
                },
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _tree(_FakeClient(final))
    by = {c["id"]: c for c in r["claims"]}
    assert by["c1"]["supports"] == "thesis"  # 悬空落 thesis
    assert by["c2"]["role"] == "支撑"  # 非法角色落支撑
    assert by["c2"]["supports"] == "c1"  # 有效指向保留


def test_dedup_ids(monkeypatch):
    final = json.dumps(
        {
            "thesis": {"claim": "中心", "quote": "国家能力决定现代化的成败"},
            "claims": [
                {"id": "c1", "claim": "甲", "role": "支撑", "supports": "thesis",
                 "quote": "现代国家的形成是现代化的起点和基础"},
                {"id": "c1", "claim": "重复 id", "role": "支撑", "supports": "thesis",
                 "quote": "有效治理比照搬西方模式更能增进长远福祉"},
                {"id": "c2", "claim": "乙", "role": "支撑", "supports": "thesis",
                 "quote": "有效治理比照搬西方模式更能增进长远福祉"},
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _tree(_FakeClient(final))
    ids = [c["id"] for c in r["claims"]]
    assert ids == ["c1", "c2"]  # 第二个 c1 被去重


def test_graceful_no_thesis(monkeypatch):
    final = json.dumps(
        {
            "thesis": {"claim": "", "quote": ""},
            "claims": [
                {"id": "c1", "claim": "甲", "role": "支撑", "supports": "thesis",
                 "quote": "现代国家的形成是现代化的起点和基础"},
                {"id": "c2", "claim": "乙", "role": "支撑", "supports": "thesis",
                 "quote": "有效治理比照搬西方模式更能增进长远福祉"},
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    assert _tree(_FakeClient(final)) == {"scanned": False, "thesis": None, "claims": []}


def test_graceful_fewer_than_two_claims(monkeypatch):
    final = json.dumps(
        {
            "thesis": {"claim": "中心", "quote": "国家能力决定现代化的成败"},
            "claims": [
                {"id": "c1", "claim": "只有一条", "role": "支撑", "supports": "thesis",
                 "quote": "现代国家的形成是现代化的起点和基础"},
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    assert _tree(_FakeClient(final)) == {"scanned": False, "thesis": None, "claims": []}


def test_graceful_non_theory_genre(monkeypatch):
    # 叙事题材（fiction）不跑树，直接 graceful（不调 LLM）
    _patch_invoke(monkeypatch)
    assert _tree(_FakeClient("{}"), genre="fiction") == {
        "scanned": False,
        "thesis": None,
        "claims": [],
    }


def test_graceful_parse_fail(monkeypatch):
    _patch_invoke(monkeypatch)
    r = _tree(_FakeClient(["不是 json", "还不是", "仍不是"]))
    assert r == {"scanned": False, "thesis": None, "claims": []}


def test_graceful_llm_exception(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    assert _tree(_FakeClient("{}")) == {"scanned": False, "thesis": None, "claims": []}
