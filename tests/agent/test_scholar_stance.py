"""scholar_stance.scholar_stance_spectrum 单测（学者立场谱，probe exp033 GO）。

mock _invoke_client + 假 client，不打真 LLM（主 Claude 有 key 做 live 验）。覆盖契约：

- 片段核验 :func:`_quote_grounded`：单条逐字过、"……"拼接靠片段过（整条子串会挂）、
  内嵌「」剥掉过、杜撰的挂、太短的挂——这是命门（exp022/exp033 教训）；
- 成功成谱：抽出轴 + ≥2 有立场学者，逐个挂 quote_verified；
- 只提名（stance_stated=false）：pole / position / quote 全清空，不摆上谱、不计入门槛；
- 未核上的引文保留但 quote_verified=false（不剔，前端标待核）；
- position 越界夹回 [-5,5]、重名去重、pole 越界落"中"；
- graceful 空：抽不出轴 / 有立场学者 < 2 / 解析失败 / LLM 抛异常 → scanned=False。
"""

from __future__ import annotations

import json

from bookscope.agent import scholar_stance as ss

# 假"理论书"：三句可锚的学者立场 + 一句"只提名不展开"，句读用中文句号（归一后成 .）。
_BOOK = (
    "本书的核心论点是国家能力决定市场的边界。"
    "张五常主张产权清晰是市场运转的前提。"
    "科尔奈提出短缺经济是计划体制的必然产物。"
    "诺斯只是被顺带提及，本书没有展开他的立场。"
)
_BOOK_NORM = ss._norm(_BOOK)


# ---------------------------------------------------------------------------
# _quote_grounded —— 片段核验（命门）
# ---------------------------------------------------------------------------


def test_grounded_verbatim_single_fragment():
    assert ss._quote_grounded("产权清晰是市场运转的前提", _BOOK_NORM) is True


def test_grounded_ellipsis_join_passes_by_fragment():
    # 模型把不相邻两句用"……"拼一条、还内嵌「」——整条子串比对必挂，靠片段核过
    quote = "「产权清晰」是市场运转的前提……短缺经济是计划体制的必然产物"
    assert ss._norm(quote) not in _BOOK_NORM  # 整条拼接不在原书（证明片段核的必要）
    assert ss._quote_grounded(quote, _BOOK_NORM) is True  # 拆片段后每段都在 → 认


def test_grounded_inner_corner_brackets_stripped():
    # 模型给术语加「」，剥掉后逐字命中
    assert ss._quote_grounded("「短缺经济」是计划体制的必然产物", _BOOK_NORM) is True


def test_grounded_hallucinated_quote_fails():
    assert ss._quote_grounded("本书从未出现过的一句彻底杜撰的话", _BOOK_NORM) is False


def test_grounded_too_short_fails():
    assert ss._quote_grounded("国家能力", _BOOK_NORM) is False  # <8 字，核不动


# ---------------------------------------------------------------------------
# scholar_stance_spectrum —— 整体契约
# ---------------------------------------------------------------------------


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

    monkeypatch.setattr(ss, "_invoke_client", _fake)


def _spectrum(client):  # noqa: ANN001
    return ss.scholar_stance_spectrum(full_text=_BOOK, llm_client=client, model="m")


def test_success_spectrum(monkeypatch):
    final = json.dumps(
        {
            "axis": {
                "pole_a": "国家能力",
                "pole_b": "市场自发",
                "from_book": "国家能力决定市场的边界",
            },
            "scholars": [
                {
                    "name": "张五常",
                    "stance_stated": True,
                    "pole": "b",
                    "position": 4,
                    "quote": "产权清晰是市场运转的前提",
                    "brief": "偏市场自发",
                },
                {
                    "name": "科尔奈",
                    "stance_stated": True,
                    "pole": "a",
                    "position": -3,
                    "quote": "短缺经济是计划体制的必然产物",
                    "brief": "计划体制批判",
                },
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _spectrum(_FakeClient(final))
    assert r["scanned"] is True
    assert r["axis"]["pole_a"] == "国家能力" and r["axis"]["pole_b"] == "市场自发"
    assert len(r["scholars"]) == 2
    by = {s["name"]: s for s in r["scholars"]}
    assert by["张五常"]["pole"] == "b" and by["张五常"]["position"] == 4
    assert by["张五常"]["quote_verified"] is True
    assert by["科尔奈"]["quote_verified"] is True


def test_ellipsis_join_verified_through_spectrum(monkeypatch):
    # "……"拼接的引文在整条流程里也靠片段核过
    final = json.dumps(
        {
            "axis": {"pole_a": "国家能力", "pole_b": "市场自发", "from_book": "x"},
            "scholars": [
                {
                    "name": "张五常",
                    "stance_stated": True,
                    "pole": "b",
                    "position": 4,
                    "quote": "「产权清晰」是市场运转的前提……短缺经济是计划体制的必然产物",
                },
                {
                    "name": "科尔奈",
                    "stance_stated": True,
                    "pole": "a",
                    "position": -3,
                    "quote": "短缺经济是计划体制的必然产物",
                },
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _spectrum(_FakeClient(final))
    assert r["scanned"] is True
    by = {s["name"]: s for s in r["scholars"]}
    assert by["张五常"]["quote_verified"] is True


def test_only_mentioned_cleared_and_not_counted(monkeypatch):
    # 只提名（stance_stated=false）：pole/position/quote 全清空，且不计入 ≥2 门槛
    final = json.dumps(
        {
            "axis": {"pole_a": "国家能力", "pole_b": "市场自发", "from_book": "x"},
            "scholars": [
                {
                    "name": "张五常",
                    "stance_stated": True,
                    "pole": "b",
                    "position": 4,
                    "quote": "产权清晰是市场运转的前提",
                },
                {
                    "name": "科尔奈",
                    "stance_stated": True,
                    "pole": "a",
                    "position": -3,
                    "quote": "短缺经济是计划体制的必然产物",
                },
                # 只提名却带了立场痕迹 —— 必须被清空
                {
                    "name": "诺斯",
                    "stance_stated": False,
                    "pole": "a",
                    "position": 5,
                    "quote": "本书没写的立场",
                    "brief": "顺带提及",
                },
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _spectrum(_FakeClient(final))
    assert r["scanned"] is True
    nuo = next(s for s in r["scholars"] if s["name"] == "诺斯")
    assert nuo["stance_stated"] is False
    assert nuo["pole"] == "" and nuo["position"] == 0 and nuo["quote"] == ""
    assert nuo["quote_verified"] is False


def test_unverified_quote_kept_flagged(monkeypatch):
    # 有立场但引文杜撰 → 保留、quote_verified=false（不剔，前端标待核）；仍计入门槛
    final = json.dumps(
        {
            "axis": {"pole_a": "国家能力", "pole_b": "市场自发", "from_book": "x"},
            "scholars": [
                {
                    "name": "张五常",
                    "stance_stated": True,
                    "pole": "b",
                    "position": 4,
                    "quote": "产权清晰是市场运转的前提",
                },
                {
                    "name": "杜撰君",
                    "stance_stated": True,
                    "pole": "a",
                    "position": -3,
                    "quote": "本书根本没有的一句杜撰立场描述",
                },
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _spectrum(_FakeClient(final))
    assert r["scanned"] is True
    du = next(s for s in r["scholars"] if s["name"] == "杜撰君")
    assert du["quote"] and du["quote_verified"] is False


def test_clamps_dedup_and_pole_fallback(monkeypatch):
    final = json.dumps(
        {
            "axis": {"pole_a": "A", "pole_b": "B", "from_book": "x"},
            "scholars": [
                {
                    "name": "甲",
                    "stance_stated": True,
                    "pole": "b",
                    "position": 99,  # 越界夹回 5
                    "quote": "产权清晰是市场运转的前提",
                },
                {
                    "name": "甲",  # 重名跳过
                    "stance_stated": True,
                    "pole": "a",
                    "position": -99,
                    "quote": "短缺经济是计划体制的必然产物",
                },
                {
                    "name": "乙",
                    "stance_stated": True,
                    "pole": "zzz",  # 越界 → 落"中"
                    "position": -50,  # 越界夹回 -5
                    "quote": "短缺经济是计划体制的必然产物",
                },
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _spectrum(_FakeClient(final))
    assert r["scanned"] is True and len(r["scholars"]) == 2  # 甲去重后只一份
    by = {s["name"]: s for s in r["scholars"]}
    assert by["甲"]["position"] == 5
    assert by["乙"]["pole"] == "中" and by["乙"]["position"] == -5


def test_graceful_fewer_than_two_stated(monkeypatch):
    final = json.dumps(
        {
            "axis": {"pole_a": "国家能力", "pole_b": "市场自发", "from_book": "x"},
            "scholars": [
                {
                    "name": "张五常",
                    "stance_stated": True,
                    "pole": "b",
                    "position": 4,
                    "quote": "产权清晰是市场运转的前提",
                },
                {"name": "诺斯", "stance_stated": False},
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _spectrum(_FakeClient(final))
    assert r == {"scanned": False, "axis": None, "scholars": []}


def test_graceful_no_axis(monkeypatch):
    final = json.dumps(
        {
            "axis": {"pole_a": "", "pole_b": "", "from_book": ""},
            "scholars": [
                {
                    "name": "张五常",
                    "stance_stated": True,
                    "pole": "b",
                    "position": 4,
                    "quote": "产权清晰是市场运转的前提",
                },
                {
                    "name": "科尔奈",
                    "stance_stated": True,
                    "pole": "a",
                    "position": -3,
                    "quote": "短缺经济是计划体制的必然产物",
                },
            ],
        },
        ensure_ascii=False,
    )
    _patch_invoke(monkeypatch)
    r = _spectrum(_FakeClient(final))
    assert r == {"scanned": False, "axis": None, "scholars": []}


def test_graceful_parse_fail(monkeypatch):
    _patch_invoke(monkeypatch)
    r = _spectrum(_FakeClient(["不是 json", "还不是 json", "仍不是 json"]))
    assert r == {"scanned": False, "axis": None, "scholars": []}


def test_graceful_llm_exception(monkeypatch):
    _patch_invoke(monkeypatch, raises=RuntimeError("boom"))
    r = _spectrum(_FakeClient("{}"))
    assert r == {"scanned": False, "axis": None, "scholars": []}
