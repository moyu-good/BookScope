"""r0 backend 适配：把 r0 KG 角色数据包装成 r1 ``CharacterIndexBackend``。

本文件把 r0 代际 KG 抽取阶段产出的 ``CharacterProfile`` 列表包装成
r1 ADR-001 的 ``CharacterIndexBackend`` Protocol 实现，供
``list_characters_in_chapter`` tool 调用。

### r0 数据能力评估（2026-04-20 梳理）

r0 的 ``bookscope.models.schemas.CharacterProfile`` 字段中与本 tool
直接相关的是 ``name / aliases / key_chapter_indices``——**章节粒度**的
角色出场记录。但 ADR-001 的 ``CharacterRef`` 还额外要两项数据：

1. ``mention_count``：该角色在某章节中的提及次数。r0 KG 层只记录
   "此角色在章 X 出现过"，没有做 **次数** 统计。
2. ``first_appearance_position``：该角色在章节内首次出现的相对位置
   ``[0, 1]``。r0 根本没跟踪 chunk 内 / 章节内的字符偏移量。

因此本 backend 不能只靠 r0 原生数据，必须**由调用方在构造时外部提供
（或让 backend 自动降级）两份补齐映射**：``mention_counts`` 和
``first_positions``。若缺失则回退为粗粒度默认值（次数 = 1、位置 = 0.0），
表达"至少出现一次、位置在章节开头"的最弱断言——**绝不回去硬改 r0**
（那是代际级改动，该缺口已登记到 ``docs/internal/STATE.md`` 的"需作者决策"区）。

### 适配假设

- ``chapter_character_map`` 的构造可以直接从一组 ``CharacterProfile``
  的 ``key_chapter_indices`` 反转生成，本模块顺手提供
  ``build_chapter_character_map`` helper。外部也可传入精心构造的 map
  覆盖默认逻辑（例如真跑了字级 NER 统计之后的精确倒排）。
- ``characters_in`` 的返回按 ``mention_count`` 降序（ADR-001 要求）。
  若所有角色的 mention_count 都回退到 1，则排序稳定即按 chapter_character_map
  中的出现顺序。

### 为什么不改 r0

和 ``R0SearchChunksBackend`` / ``R0ChapterRangeBackend`` 的做法一致：
r0 原生的 `CharacterProfile` 缺 ``mention_count`` / ``first_appearance_position``
是代际级缺口，副管理不得自行扩 r0 schema。workaround 统一为
"构造参数外部注入"。
"""

from __future__ import annotations

from collections.abc import Mapping

from bookscope.agent.tools.schemas import CharacterRef
from bookscope.models.schemas import CharacterProfile

# ---------------------------------------------------------------------------
# 默认值常量
# ---------------------------------------------------------------------------

DEFAULT_MENTION_COUNT: int = 1
"""r0 缺 ``mention_count`` 统计时的兜底值。

取 1 的理由：``CharacterRef.mention_count`` schema 约束 ``ge=1``；
同时语义上"角色被列在 ``key_chapter_indices`` 里"等同于"至少出现一次"。
"""

DEFAULT_FIRST_POSITION: float = 0.0
"""r0 缺 ``first_appearance_position`` 统计时的兜底值。

取 0.0 的理由：``CharacterRef.first_appearance_position`` schema 约束
``[0.0, 1.0]``；0.0 表达"章节开头"这个最弱的可接受位置断言。
"""


# ---------------------------------------------------------------------------
# Helper：由 CharacterProfile 列表反转生成章节→角色名 map
# ---------------------------------------------------------------------------


def build_chapter_character_map(
    profiles: list[CharacterProfile],
) -> dict[int, list[str]]:
    """由 ``CharacterProfile`` 列表反转生成 ``chapter → 角色名列表`` 映射。

    这是 r0 → r1 的"常见装配路径"：r0 KG 天然是"角色 → 章节列表"结构
    （``CharacterProfile.key_chapter_indices``），而 r1 的
    ``list_characters_in_chapter`` 需要反向查询 "章节 → 角色列表"。

    返回值的字典：
    - key：章节号（来自 ``CharacterProfile.key_chapter_indices`` 的元素）
    - value：在该章节出现的角色 ``name`` 列表，按入参 ``profiles`` 顺序排列

    一个角色出现在多个章节时会被加入多个 bucket；若多个角色同章节则
    按 ``profiles`` 列表顺序依次 append。

    Args:
        profiles: r0 KG 产出的角色清单。空列表合法，返回空 dict。

    Returns:
        ``chapter → 角色名列表`` 的反转索引。
    """
    result: dict[int, list[str]] = {}
    for profile in profiles:
        for chapter in profile.key_chapter_indices:
            # setdefault 避免 KeyError，同时保持顺序插入语义。
            result.setdefault(chapter, []).append(profile.name)
    return result


# ---------------------------------------------------------------------------
# R0ListCharactersBackend
# ---------------------------------------------------------------------------


class R0ListCharactersBackend:
    """把 r0 ``CharacterProfile`` 列表包装成 r1 ``CharacterIndexBackend``。

    构造参数：

    Args:
        character_profiles: r0 KG 产出的角色清单。用于把章节里出现的
            角色 ``name`` 映射到 canonical name（这里实现为
            "profile.name 本身即为 canonical"——r0 没有单独的 canonical
            字段，主名称就是标准形态；aliases 保留但不参与本 backend
            的检索）。
        chapter_character_map: ``chapter → 角色名列表`` 的倒排索引。
            通常由 ``build_chapter_character_map(character_profiles)``
            派生，也可以由上层按更精确的统计（真字级 NER）外部注入。
        mention_counts: 可选。``(chapter, character_name) → mention_count``
            的精确次数统计。缺失的 (chapter, name) 组合回退为
            ``DEFAULT_MENTION_COUNT``（1）。
        first_positions: 可选。``(chapter, character_name) → first_appearance_position``
            的精确位置统计（``[0, 1]`` 区间）。缺失的 (chapter, name)
            组合回退为 ``DEFAULT_FIRST_POSITION``（0.0）。
    """

    def __init__(
        self,
        character_profiles: list[CharacterProfile],
        *,
        chapter_character_map: dict[int, list[str]],
        mention_counts: Mapping[tuple[int, str], int] | None = None,
        first_positions: Mapping[tuple[int, str], float] | None = None,
    ) -> None:
        self._profiles: list[CharacterProfile] = list(character_profiles)
        # 构造 name → profile 索引，便于 O(1) 查 canonical name。
        # r0 没有单独 canonical 字段，就把 profile.name 当作 canonical。
        self._name_to_profile: dict[str, CharacterProfile] = {
            profile.name: profile for profile in self._profiles
        }
        # 深拷贝 chapter_character_map 的 list 值，避免外部修改影响内部状态。
        self._chapter_to_characters: dict[int, list[str]] = {
            chapter: list(names) for chapter, names in chapter_character_map.items()
        }
        self._mention_counts: dict[tuple[int, str], int] = (
            dict(mention_counts) if mention_counts else {}
        )
        self._first_positions: dict[tuple[int, str], float] = (
            dict(first_positions) if first_positions else {}
        )

    # ------------------------------------------------------------------
    # CharacterIndexBackend Protocol 实现
    # ------------------------------------------------------------------

    def characters_in(self, chapter: int) -> list[CharacterRef]:
        """返回该章节中出现的全部角色，按 ``mention_count`` 降序。

        流程：
        1. 校验 ``chapter >= 1``（< 1 抛 ``ValueError``，不静默返回空）。
        2. 从 ``chapter_character_map[chapter]`` 拿该章节的角色名 list；
           缺失 → 返回空列表（章节无角色，合理降级，不抛异常）。
        3. 对每个角色名查 ``character_profiles`` 拿 canonical name；
           profile 缺失 → 回退为 ``name == canonical_name``
           （把 map 里的原始字符串当 canonical 用）。
        4. 拼装 ``CharacterRef``（name / canonical_name / mention_count /
           first_appearance_position / source_version="r0"），
           按 ``mention_count`` 降序返回。

        Args:
            chapter: 章节号，必须 >= 1。

        Returns:
            按 ``mention_count`` 降序的 ``CharacterRef`` 列表；
            章节无角色时为空列表。

        Raises:
            ValueError: 当 ``chapter < 1`` 时；ADR-001 的 input schema
                本已守住这一点，此处作为深度防御（允许 backend 脱离
                dispatcher 被直接调用，例如 agent loop 的 dry-run）。
        """
        if chapter < 1:
            raise ValueError(f"chapter must be >= 1 (got {chapter})")

        names_in_chapter = self._chapter_to_characters.get(chapter, [])
        if not names_in_chapter:
            return []

        refs: list[CharacterRef] = []
        for name in names_in_chapter:
            canonical_name = self._resolve_canonical(name)
            mention_count = self._mention_counts.get(
                (chapter, name),
                DEFAULT_MENTION_COUNT,
            )
            first_pos = self._first_positions.get(
                (chapter, name),
                DEFAULT_FIRST_POSITION,
            )
            refs.append(
                CharacterRef(
                    name=name,
                    canonical_name=canonical_name,
                    mention_count=mention_count,
                    first_appearance_position=first_pos,
                    source_version="r0",
                )
            )

        # ADR-001 要求按 mention_count 降序；Python 的 sort 稳定，
        # 同 mention_count 的条目保留输入顺序。
        refs.sort(key=lambda r: r.mention_count, reverse=True)
        return refs

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _resolve_canonical(self, name: str) -> str:
        """把章节中出现的原始称呼解析为 canonical name。

        r0 没有单独 canonical 字段：``CharacterProfile.name`` 本身就是
        标准形态，``aliases`` 列表里才是别名。因此本方法优先级：

        1. name 本身命中某 profile 的 ``name`` → canonical 就是它自己。
        2. name 命中某 profile 的 ``aliases`` → canonical 回到该 profile 的 ``name``。
        3. 都不命中（map 里混入了未登记的角色名）→ 回退为 name 自身
           （把原始称呼当 canonical 用，让 agent 至少拿到可用字符串）。
        """
        profile = self._name_to_profile.get(name)
        if profile is not None:
            return profile.name
        # 尝试在 aliases 里找
        for p in self._profiles:
            if name in p.aliases:
                return p.name
        # 都没命中时回退
        return name
