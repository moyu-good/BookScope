"""章脉人名归并(chapter_spine_canon)单测 —— 收名 / 解析分组 / build 装配。

收名 + 解析是纯件,直接喂数据;build_spine_name_map 用 fake client 喂分组 JSON,关缓存不调真 LLM。
"""

from __future__ import annotations

import json

import bookscope.agent.chapter_spine_canon as canon


# ── collect_spine_names ──────────────────────────────────────────────────────
def test_collect_names_from_present_relations_states() -> None:
    spine = [
        {"chapter": 1, "present": ["刘备", "关羽"],
         "relations": [{"pair": ["玄德", "张飞"], "note": "x"}],
         "char_states": [{"name": "曹操", "state": "南下"}]},
        {"chapter": 2, "present": ["刘备", ""],  # 空串丢掉
         "relations": [{"pair": ["孔明"], "note": "坏对丢掉"}]},
    ]
    names = canon.collect_spine_names(spine)
    assert names == sorted({"刘备", "关羽", "玄德", "张飞", "曹操"})
    assert "" not in names
    assert "孔明" not in names  # pair 长度非 2 不收


def test_collect_names_tolerates_garbage() -> None:
    spine = [{"chapter": 1, "present": None, "relations": "坏", "char_states": 3}, "不是dict"]
    assert canon.collect_spine_names(spine) == []


# ── _parse_groups ────────────────────────────────────────────────────────────
def test_parse_groups_builds_alias_map() -> None:
    names = {"刘备", "玄德", "刘玄德", "先主", "诸葛亮", "孔明"}
    text = json.dumps({"groups": [
        {"canonical": "刘备", "aliases": ["刘备", "玄德", "刘玄德", "先主"]},
        {"canonical": "诸葛亮", "aliases": ["诸葛亮", "孔明"]},
    ]})
    m = canon._parse_groups(text, names)
    assert m["玄德"] == "刘备" and m["先主"] == "刘备" and m["刘玄德"] == "刘备"
    assert m["孔明"] == "诸葛亮"


def test_parse_groups_drops_alias_not_in_names() -> None:
    # LLM 塞了清单里没出现过的名字,不收(防污染)
    names = {"刘备", "玄德"}
    text = json.dumps({"groups": [
        {"canonical": "刘备", "aliases": ["玄德", "刘大耳"]},  # 刘大耳 不在 names
    ]})
    m = canon._parse_groups(text, names)
    assert m == {"玄德": "刘备"}


def test_parse_groups_salvages_truncated() -> None:
    names = {"刘备", "玄德", "关羽", "云长"}
    # 第二组没闭合 + 外层没收尾 → 主 parse 必败,从第一组抢救
    truncated = (
        '{"groups": [{"canonical": "刘备", "aliases": ["玄德"]}, '
        '{"canonical": "关羽", "aliases": ["云长'
    )
    m = canon._parse_groups(truncated, names)
    assert m == {"玄德": "刘备"}


def test_parse_groups_garbage_returns_empty() -> None:
    assert canon._parse_groups("不是 JSON 也不是分组", {"甲"}) == {}
    assert canon._parse_groups("", {"甲"}) == {}
    # 有 JSON 但没 groups 字段
    assert canon._parse_groups('{"foo": 1}', {"甲"}) == {}


# ── build_spine_name_map ─────────────────────────────────────────────────────
class _FakeClient:
    """回固定分组 JSON 的 fake client;记下最后一次 system / user 便于断言。"""

    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.last_kwargs: dict = {}

    def messages_create(self, **kwargs):  # noqa: ANN003, ANN201
        self.last_kwargs = kwargs
        return {"_fake": True}

    def extract_final_text(self, resp):  # noqa: ANN001, ANN201
        return self._payload


def test_build_name_map_merges_aliases() -> None:
    spine = [
        {"chapter": 1, "present": ["玄德", "关羽"],
         "relations": [{"pair": ["玄德", "孔明"], "note": "x"}]},
        {"chapter": 2, "present": ["刘备", "诸葛亮"]},
    ]
    payload = json.dumps({"groups": [
        {"canonical": "刘备", "aliases": ["刘备", "玄德"]},
        {"canonical": "诸葛亮", "aliases": ["诸葛亮", "孔明"]},
    ]})
    client = _FakeClient(payload)
    m = canon.build_spine_name_map(
        spine=spine, llm_client=client, model="m", cache_enabled=False
    )
    assert m["玄德"] == "刘备" and m["孔明"] == "诸葛亮"
    # 发出去的是排序后的人名清单,没夹原文
    user = json.loads(client.last_kwargs["messages"][0]["content"])
    assert user["names"] == sorted({"玄德", "关羽", "孔明", "刘备", "诸葛亮"})


def test_build_name_map_single_name_short_circuits() -> None:
    spine = [{"chapter": 1, "present": ["独此一人"]}]

    class _Boom:
        def messages_create(self, **kwargs):  # noqa: ANN003, ANN201
            raise AssertionError("0/1 个名字不该调 LLM")

        def extract_final_text(self, resp):  # noqa: ANN001, ANN201
            raise AssertionError

    m = canon.build_spine_name_map(spine=spine, llm_client=_Boom(), model="m")
    assert m == {"独此一人": "独此一人"}


def test_build_name_map_llm_failure_returns_empty() -> None:
    spine = [{"chapter": 1, "present": ["甲", "乙"]}]

    class _Boom:
        def messages_create(self, **kwargs):  # noqa: ANN003, ANN201
            raise RuntimeError("provider 挂了")

        def extract_final_text(self, resp):  # noqa: ANN001, ANN201
            return ""

    m = canon.build_spine_name_map(
        spine=spine, llm_client=_Boom(), model="m", cache_enabled=False
    )
    assert m == {}  # 失败降级成不合并,关系图照画


# ── _fold_in_longtail_aliases(#13:长尾低频别名兜底)────────────────────────────
def test_fold_longtail_merges_low_freq_substring() -> None:
    # LLM 已把高频"刘玄德"合进"刘备";裸"玄德"是长尾(排不进 LLM 候选),
    # 应靠子串规则归到刘备——这是 #13 要修的核心病。
    name_map = {"刘备": "刘备", "刘玄德": "刘备"}
    all_names = ["刘备", "刘玄德", "玄德", "关羽"]
    out = canon._fold_in_longtail_aliases(name_map, all_names)
    assert out["玄德"] == "刘备"
    assert "关羽" not in out  # 不沾任何已确定称呼,不误合


def test_fold_longtail_unique_substring_merges() -> None:
    # "云长"只被"关云长"这一组的称呼含 → 唯一命中,合进关羽。
    name_map = {"关云长": "关羽", "关羽": "关羽", "赵云": "赵云"}
    out = canon._fold_in_longtail_aliases(name_map, ["关云长", "关羽", "赵云", "云长"])
    assert out["云长"] == "关羽"


def test_fold_longtail_no_merge_on_ambiguity() -> None:
    # "子龙"假设同时是两组称呼的真子串 → 歧义,谁都不合(宁漏不错)。
    name_map = {"赵子龙": "赵云", "赵云": "赵云", "诸葛子龙X": "别人"}
    out = canon._fold_in_longtail_aliases(
        name_map, ["赵子龙", "赵云", "诸葛子龙X", "子龙"]
    )
    assert "子龙" not in out  # 两组都含"子龙",歧义即弃


def test_fold_longtail_single_char_not_merged() -> None:
    # 单字"操"⊂"曹操",但单字歧义太大,MIN_LEN=2 直接挡掉不合(保守防误中)。
    name_map = {"曹操": "曹操", "孟德": "曹操"}
    out = canon._fold_in_longtail_aliases(name_map, ["曹操", "孟德", "操"])
    assert "操" not in out


def test_fold_longtail_no_merge_different_people_same_surname() -> None:
    # 马超 / 马腾 同姓不同人:谁都不是谁的子串,绝不能因都姓"马"而合。
    name_map = {"马超": "马超", "马腾": "马腾"}
    out = canon._fold_in_longtail_aliases(name_map, ["马超", "马腾"])
    assert out.get("马超") == "马超" and out.get("马腾") == "马腾"


def test_fold_longtail_empty_map_returns_empty() -> None:
    # LLM 整个失败(空表)→ 长尾无锚可依,原样返空,不凭空造合并。
    out = canon._fold_in_longtail_aliases({}, ["玄德", "刘备", "关羽"])
    assert out == {}


def test_fold_longtail_skips_too_long_name() -> None:
    # 超过 MAX_LEN 的长尾全名不靠子串往别人身上并(只兜 2-3 字的碎裂)。
    name_map = {"诸葛亮": "诸葛亮", "诸葛孔明": "诸葛亮"}
    # "诸葛孔明"已在表里(是别名);构造一个 4 字未归一名验证不被规则乱合
    out = canon._fold_in_longtail_aliases(name_map, ["诸葛亮", "诸葛孔明", "诸葛瞻"])
    assert "诸葛瞻" not in out  # 4 字超 MAX_LEN,不合(且本就不该合,是另一个人)


def test_build_name_map_folds_longtail_end_to_end() -> None:
    # 端到端:章脉里"刘玄德"高频(进 LLM 合并)、"玄德"低频长尾;
    # build 出的表两者都该指向刘备。
    spine = [
        {"chapter": i, "present": ["刘玄德", "关羽"]} for i in range(1, 10)
    ] + [{"chapter": 99, "present": ["玄德"]}]  # 玄德只露一次=长尾
    payload = json.dumps({"groups": [
        {"canonical": "刘备", "aliases": ["刘玄德"]},
    ]})
    client = _FakeClient(payload)
    m = canon.build_spine_name_map(
        spine=spine, llm_client=client, model="m", cache_enabled=False
    )
    assert m["刘玄德"] == "刘备"  # LLM 合的
    assert m["玄德"] == "刘备"  # 长尾兜底合的(#13)
