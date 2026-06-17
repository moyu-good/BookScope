"""``R0ListCharactersBackend`` 单测。

关键原则：**不跑真 KG 抽取**（不调 LLM、不跑 NER/relation extractor）。
直接用 mock ``CharacterProfile`` 列表喂给 backend，验证 Protocol 一致性、
边界、降级与 dispatcher 集成。

覆盖点：
- Protocol 结构型一致（``CharacterIndexBackend``）
- ``characters_in`` 正常路径：返回 ``CharacterRef``、``source_version == "r0"``
- canonical_name 解析：主名 / 别名命中
- ``mention_count`` 显式 / 默认回退
- ``first_appearance_position`` 显式 / 默认回退
- ``chapter < 1`` 抛 ``ValueError``
- 章节无角色返回空列表（不抛）
- ``build_chapter_character_map`` helper 正确反转
- Dispatcher 集成：通过 ``list_characters_in_chapter(params, backend)`` 走全链路
"""

from __future__ import annotations

import inspect

import pytest

from bookscope.agent.backends import (
    R0ListCharactersBackend,
    build_chapter_character_map,
)
from bookscope.agent.backends.r0_list_characters import (
    DEFAULT_FIRST_POSITION,
    DEFAULT_MENTION_COUNT,
)
from bookscope.agent.tools import CharacterIndexBackend
from bookscope.agent.tools.list_characters_in_chapter import (
    ListCharactersInChapterInput,
    list_characters_in_chapter,
)
from bookscope.agent.tools.schemas import CharacterRef
from bookscope.models.schemas import CharacterProfile

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _profile(
    name: str,
    key_chapter_indices: list[int],
    aliases: list[str] | None = None,
) -> CharacterProfile:
    """制造一个最小 ``CharacterProfile``。"""
    return CharacterProfile(
        name=name,
        aliases=aliases or [],
        key_chapter_indices=key_chapter_indices,
    )


@pytest.fixture()
def sample_profiles() -> list[CharacterProfile]:
    """三个 mock 角色，覆盖多章节出现和别名场景。"""
    return [
        _profile("角色A", key_chapter_indices=[1, 2, 3], aliases=["小A"]),
        _profile("角色B", key_chapter_indices=[1, 3], aliases=[]),
        _profile("角色C", key_chapter_indices=[1], aliases=["阿C", "C君"]),
    ]


@pytest.fixture()
def sample_chapter_map(sample_profiles) -> dict[int, list[str]]:
    """由 sample_profiles 派生的章节→角色名倒排索引。"""
    return build_chapter_character_map(sample_profiles)


# ---------------------------------------------------------------------------
# Protocol 结构型检查
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    def test_backend_satisfies_character_index_backend_protocol(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """``R0ListCharactersBackend`` 必须满足 ``CharacterIndexBackend`` Protocol。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        assert hasattr(backend, "characters_in")
        assert callable(backend.characters_in)

        # 签名参数包含 chapter
        sig = inspect.signature(backend.characters_in)
        assert "chapter" in sig.parameters

        # structural typing：赋值给 Protocol 变量不应报错
        typed: CharacterIndexBackend = backend
        assert callable(typed.characters_in)


# ---------------------------------------------------------------------------
# characters_in 正常路径
# ---------------------------------------------------------------------------


class TestCharactersInHappyPath:
    def test_chapter_one_returns_three_character_refs_with_r0_tag(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """章节 1 有 3 个角色，每条是 ``CharacterRef`` 且 ``source_version == "r0"``。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        refs = backend.characters_in(1)

        assert len(refs) == 3
        assert all(isinstance(r, CharacterRef) for r in refs)
        assert all(r.source_version == "r0" for r in refs)

    def test_canonical_name_matches_profile_name(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """每条返回的 ``canonical_name`` 应匹配对应 profile 的 ``name``。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        refs = backend.characters_in(1)
        names = {r.canonical_name for r in refs}
        assert names == {"角色A", "角色B", "角色C"}

    def test_mention_count_and_position_defaults_within_schema_bounds(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """缺省时 ``mention_count`` 和 ``first_appearance_position`` 都应在 schema 范围内。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        refs = backend.characters_in(1)
        for r in refs:
            assert r.mention_count >= 1
            assert 0.0 <= r.first_appearance_position <= 1.0

    def test_single_character_chapter(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """章节 2 只有角色 A 出现。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        refs = backend.characters_in(2)
        assert len(refs) == 1
        assert refs[0].canonical_name == "角色A"


# ---------------------------------------------------------------------------
# canonical_name 解析：主名 / 别名
# ---------------------------------------------------------------------------


class TestCanonicalNameResolution:
    def test_alias_resolves_to_profile_name(self, sample_profiles):
        """如果 chapter_character_map 里用的是别名，canonical_name 应回到主名。"""
        # 手工构造一个用别名而非主名的 map
        map_with_alias = {5: ["小A", "阿C"]}
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=map_with_alias,
        )
        refs = backend.characters_in(5)
        assert len(refs) == 2
        # name 保留原始称呼，canonical_name 指向主名
        names_to_canonical = {r.name: r.canonical_name for r in refs}
        assert names_to_canonical["小A"] == "角色A"
        assert names_to_canonical["阿C"] == "角色C"

    def test_unknown_name_falls_back_to_itself(self, sample_profiles):
        """map 里出现的未登记名字，canonical_name 回退为 name 本身。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map={7: ["匿名路人"]},
        )
        refs = backend.characters_in(7)
        assert len(refs) == 1
        assert refs[0].name == "匿名路人"
        assert refs[0].canonical_name == "匿名路人"


# ---------------------------------------------------------------------------
# mention_count / first_position 覆盖与回退
# ---------------------------------------------------------------------------


class TestMentionCountsAndPositions:
    def test_explicit_mention_counts_are_used(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """显式提供 ``mention_counts`` 时应使用之（不回退到默认）。"""
        mention_counts = {
            (1, "角色A"): 10,
            (1, "角色B"): 3,
            (1, "角色C"): 5,
        }
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
            mention_counts=mention_counts,
        )
        refs = backend.characters_in(1)
        counts = {r.canonical_name: r.mention_count for r in refs}
        assert counts == {"角色A": 10, "角色B": 3, "角色C": 5}

    def test_missing_mention_count_falls_back_to_default(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """缺失 ``mention_counts`` 时回退为 ``DEFAULT_MENTION_COUNT``（= 1）。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        refs = backend.characters_in(1)
        for r in refs:
            assert r.mention_count == DEFAULT_MENTION_COUNT

    def test_partial_mention_counts_mixes_explicit_and_default(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """部分提供 ``mention_counts`` 时，未提供的键使用默认值。"""
        mention_counts = {(1, "角色A"): 7}  # 只给 A
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
            mention_counts=mention_counts,
        )
        refs = backend.characters_in(1)
        counts = {r.canonical_name: r.mention_count for r in refs}
        assert counts["角色A"] == 7
        assert counts["角色B"] == DEFAULT_MENTION_COUNT
        assert counts["角色C"] == DEFAULT_MENTION_COUNT

    def test_explicit_first_positions_are_used(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """显式提供 ``first_positions`` 时应使用之（不回退到默认）。"""
        first_positions = {
            (1, "角色A"): 0.1,
            (1, "角色B"): 0.5,
            (1, "角色C"): 0.9,
        }
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
            first_positions=first_positions,
        )
        refs = backend.characters_in(1)
        positions = {r.canonical_name: r.first_appearance_position for r in refs}
        assert positions["角色A"] == pytest.approx(0.1)
        assert positions["角色B"] == pytest.approx(0.5)
        assert positions["角色C"] == pytest.approx(0.9)

    def test_missing_first_position_falls_back_to_default(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """缺失 ``first_positions`` 时回退为 ``DEFAULT_FIRST_POSITION``（= 0.0）。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        refs = backend.characters_in(1)
        for r in refs:
            assert r.first_appearance_position == pytest.approx(DEFAULT_FIRST_POSITION)


# ---------------------------------------------------------------------------
# 排序：按 mention_count 降序
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_results_sorted_by_mention_count_descending(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """ADR-001 要求返回按 ``mention_count`` 降序。"""
        mention_counts = {
            (1, "角色A"): 3,
            (1, "角色B"): 10,
            (1, "角色C"): 7,
        }
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
            mention_counts=mention_counts,
        )
        refs = backend.characters_in(1)
        counts = [r.mention_count for r in refs]
        assert counts == sorted(counts, reverse=True)
        assert counts == [10, 7, 3]


# ---------------------------------------------------------------------------
# 边界：chapter < 1 / 章节无角色
# ---------------------------------------------------------------------------


class TestBoundaries:
    def test_chapter_zero_raises_value_error(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """``chapter < 1`` 抛 ``ValueError`` 而非静默返回。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        with pytest.raises(ValueError, match=r"chapter must be >= 1"):
            backend.characters_in(0)

    def test_negative_chapter_raises_value_error(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        with pytest.raises(ValueError):
            backend.characters_in(-5)

    def test_chapter_without_characters_returns_empty_list(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """章节在 map 中不存在时返回空列表（不抛异常）。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        refs = backend.characters_in(999)
        assert refs == []

    def test_empty_profiles_empty_map_works(self):
        """空 profile + 空 map 的 backend 可以构造并返回空列表。"""
        backend = R0ListCharactersBackend(
            [],
            chapter_character_map={},
        )
        assert backend.characters_in(1) == []


# ---------------------------------------------------------------------------
# build_chapter_character_map helper
# ---------------------------------------------------------------------------


class TestBuildChapterCharacterMap:
    def test_reverses_single_character_multi_chapter(self):
        """单个角色出现在多章节：应被放到多个 chapter bucket。"""
        profiles = [_profile("角色X", key_chapter_indices=[1, 2, 5])]
        result = build_chapter_character_map(profiles)
        assert result == {1: ["角色X"], 2: ["角色X"], 5: ["角色X"]}

    def test_multiple_characters_same_chapter_preserves_order(self):
        """多个角色同章节：bucket 内按 profile 列表顺序。"""
        profiles = [
            _profile("角色A", key_chapter_indices=[1]),
            _profile("角色B", key_chapter_indices=[1]),
            _profile("角色C", key_chapter_indices=[1]),
        ]
        result = build_chapter_character_map(profiles)
        assert result == {1: ["角色A", "角色B", "角色C"]}

    def test_empty_profile_list_returns_empty_dict(self):
        """空 profile 列表应返回空 dict。"""
        result = build_chapter_character_map([])
        assert result == {}

    def test_complex_cross_chapter_mixing(self, sample_profiles):
        """综合场景：sample_profiles 的章节反转应符合预期。

        sample_profiles：
        - 角色A：chapters [1, 2, 3]
        - 角色B：chapters [1, 3]
        - 角色C：chapters [1]
        期望：
        - chapter 1: [A, B, C]
        - chapter 2: [A]
        - chapter 3: [A, B]
        """
        result = build_chapter_character_map(sample_profiles)
        assert result == {
            1: ["角色A", "角色B", "角色C"],
            2: ["角色A"],
            3: ["角色A", "角色B"],
        }

    def test_profile_with_empty_key_chapters_contributes_nothing(self):
        """``key_chapter_indices`` 为空的 profile 不应影响 map。"""
        profiles = [
            _profile("活跃", key_chapter_indices=[1, 2]),
            _profile("沉默", key_chapter_indices=[]),
        ]
        result = build_chapter_character_map(profiles)
        assert result == {1: ["活跃"], 2: ["活跃"]}


# ---------------------------------------------------------------------------
# Dispatcher 集成：通过 list_characters_in_chapter(params, backend) 走全链路
# ---------------------------------------------------------------------------


class TestDispatcherIntegration:
    def test_end_to_end_returns_character_refs(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """通过 dispatcher 调用应返回与直接调用 backend 相同的结果。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        params = ListCharactersInChapterInput(chapter=1)
        refs = list_characters_in_chapter(params, backend)

        assert len(refs) == 3
        assert all(isinstance(r, CharacterRef) for r in refs)
        assert all(r.source_version == "r0" for r in refs)

    def test_dispatcher_empty_chapter_returns_empty_list(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """章节无角色时 dispatcher 返回空列表（不抛）。"""
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
        )
        params = ListCharactersInChapterInput(chapter=42)  # 不在 map 中
        refs = list_characters_in_chapter(params, backend)
        assert refs == []

    def test_dispatcher_preserves_ordering(
        self,
        sample_profiles,
        sample_chapter_map,
    ):
        """dispatcher 透传 backend 的 mention_count 降序排序。"""
        mention_counts = {
            (1, "角色A"): 1,
            (1, "角色B"): 5,
            (1, "角色C"): 3,
        }
        backend = R0ListCharactersBackend(
            sample_profiles,
            chapter_character_map=sample_chapter_map,
            mention_counts=mention_counts,
        )
        params = ListCharactersInChapterInput(chapter=1)
        refs = list_characters_in_chapter(params, backend)
        assert [r.canonical_name for r in refs] == ["角色B", "角色C", "角色A"]
