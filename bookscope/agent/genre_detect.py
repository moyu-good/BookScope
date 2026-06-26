"""题材检测：轻量一次 LLM 调用，把一本书分到封闭题材集。

#10 genre 基建——以前 BookScope 没把"题材"落到数据，所有功能不分题材硬跑（论点结构
跑三国产怪就是这病）。这里只做一件事：拿书名 + 目录 + 开头一段，让模型分到封闭集

    {小说, 历史, 理论, 论文, 公文, 诗歌, 工具书, 其他}

落不进就退 "其他"。题材是分类不是引文，evidence-first 这里不强求，但取保守姿态：
解析失败 / 不在封闭集 / 模型含糊一律退 "其他"，宁可不分类也不乱贴标签。

一次调用、结果由调用方缓存进 session metadata（见 ``book_sessions.get_metadata``），
不每次重分。

题材轴映射（``genre_to_argument_axis``）：检测出的中文题材再压到 chapter_spine /
argument_structure 用的 ``theory`` / ``fiction`` 二元轴——理论 / 论文 = 论说类（theory），
其余 = 叙事 / 非论说（fiction）。论点结构据此对小说优雅退场。
"""

from __future__ import annotations

import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client

logger = logging.getLogger(__name__)

# 封闭题材集（落不进退 "其他"）。
GENRES: frozenset[str] = frozenset(
    {"小说", "历史", "理论", "论文", "公文", "诗歌", "工具书", "其他"}
)
"""检测的封闭集。模型只能从这里挑一个，落不进退 ``其他``。"""

FALLBACK_GENRE = "其他"
"""不确定 / 解析失败 / 不在封闭集时的保守兜底。"""

# 论说类题材：有"论证骨架"可梳理，论点结构功能跑这两类。其余退场。
_THEORY_GENRES = frozenset({"理论", "论文"})

DEFAULT_GENRE_MAX_TOKENS = 64
"""分类只需吐两三个字的题材名，给小预算够了。"""

_MAX_ATTEMPTS = 2

# 输入截断：分类不需要全本，开头几段 + 目录足够认出题材，多塞只是浪费 token。
_MAX_TITLE_CHARS = 200
_MAX_TOC_CHAPTERS = 40
_MAX_TOC_TITLE_CHARS = 60
_MAX_SAMPLE_CHARS = 3000

_SYSTEM_INSTRUCTION = (
    "你是一个文本题材分类器。下面给你一本书的书名、目录（若有）和开头一段原文，"
    "请判断它属于哪一类，只能从这个封闭集里挑一个：\n"
    "小说 / 历史 / 理论 / 论文 / 公文 / 诗歌 / 工具书 / 其他\n"
    "判断要点：\n"
    "- 小说：虚构叙事（含网络小说、历史小说、科幻、武侠等任意子类）\n"
    "- 历史：纪实性历史叙述 / 史书 / 通俗历史（非虚构的史实讲述）\n"
    "- 理论：成体系讲观点、提主张、做论证的著作（社科 / 哲学 / 政经理论等）\n"
    "- 论文：学术论文 / 研究报告（有摘要 / 文献 / 方法 / 结论结构）\n"
    "- 公文：党政机关公文 / 红头文件 / 规章制度 / 通知决定等\n"
    "- 诗歌：诗集 / 词集 / 韵文\n"
    "- 工具书：手册 / 词典 / 教程 / 操作指南等查阅型文本\n"
    "- 其他：明显不属于以上任何一类，或证据不足以判断\n"
    "拿不准就选 其他，不要硬猜。\n"
    "只回一个题材词，别的什么都不要说（不要解释、不要标点、不要引号）。"
)


def is_theory_genre(genre: str | None) -> bool:
    """这个题材算不算"论说类"（理论 / 论文）。``None`` 视作论说类（向后兼容）。"""
    if genre is None:
        return True
    return genre in _THEORY_GENRES


def genre_to_argument_axis(genre: str | None) -> str | None:
    """中文题材 → ``argument_structure`` 用的 ``theory`` / ``fiction`` 二元轴。

    - ``None`` → ``None``（端点没检测出题材时传 None，argument 按向后兼容照旧跑）
    - 理论 / 论文 → ``"theory"``（论点结构正常跑）
    - 其余（小说 / 历史 / 公文 / 诗歌 / 工具书 / 其他）→ ``"fiction"``（论点结构优雅退场）
    """
    if genre is None:
        return None
    return "theory" if genre in _THEORY_GENRES else "fiction"


def _build_user_message(
    *, title: str, toc_titles: list[str], sample_text: str
) -> str:
    """拼检测输入：书名 + 目录（章标题，截断）+ 开头原文（截断）。"""
    parts: list[str] = []
    title = (title or "").strip()[:_MAX_TITLE_CHARS]
    parts.append(f"书名：{title or '（无）'}")

    cleaned_toc = [
        t.strip()[:_MAX_TOC_TITLE_CHARS]
        for t in toc_titles[:_MAX_TOC_CHAPTERS]
        if t and t.strip()
    ]
    if cleaned_toc:
        parts.append("目录：\n" + "\n".join(cleaned_toc))

    sample = (sample_text or "").strip()[:_MAX_SAMPLE_CHARS]
    if sample:
        parts.append("开头原文：\n" + sample)

    return "\n\n".join(parts)


def _parse_genre(text: str | None) -> str:
    """从模型回复里抠出封闭集里的题材词；抠不到退 ``其他``。

    保守匹配：先看整段 strip 后是不是恰好一个题材词；不是就在文本里找第一个出现的
    封闭集词（防模型多嘴带标点 / 解释）。一个都没命中 → ``其他``。
    """
    raw = (text or "").strip()
    if not raw:
        return FALLBACK_GENRE
    # 去常见包裹（引号 / 句号 / 书名号），命中封闭集就用。
    stripped = raw.strip("。，、,.\"'《》“”‘’ \t\n")
    if stripped in GENRES:
        return stripped
    # 模型多嘴时在文本里找第一个出现的封闭集词。
    for g in sorted(GENRES, key=len, reverse=True):
        if g in raw:
            return g
    return FALLBACK_GENRE


def detect_genre(
    *,
    title: str,
    toc_titles: list[str],
    sample_text: str,
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_GENRE_MAX_TOKENS,
) -> str:
    """一次 LLM 调用判书的题材，返回封闭集里的一个词。

    保守：调用失败 / 解析不出 / 不在封闭集，一律退 ``其他``（永不抛错——题材是
    锦上添花的分类，挂了也不该让上层功能崩）。结果由调用方缓存进 session
    metadata，不每次重分。

    Args:
        title: 书名。
        toc_titles: 目录里的章标题（会截到前若干章，每条再截长度）。可空。
        sample_text: 开头一段原文（会截断）。可空，但和目录都空时只能靠书名。
        llm_client: provider-agnostic 的 LLMClient（BYOK）。
        model: 模型名。
        max_tokens: 分类输出预算，默认很小。

    Returns:
        封闭集 :data:`GENRES` 里的一个题材词；任何不确定退 ``其他``。
    """
    user_msg = _build_user_message(
        title=title, toc_titles=toc_titles, sample_text=sample_text
    )
    messages = [{"role": "user", "content": user_msg}]
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=_SYSTEM_INSTRUCTION,
                tools=[],
                messages=messages,
                max_tokens=max_tokens,
                cache_enabled=True,
            )
        except Exception as exc:  # noqa: BLE001 — 分类失败退兜底，不抛
            logger.warning(
                "genre_detect LLM call raised %s: %s (attempt %d/%d)",
                type(exc).__name__, exc, attempt, _MAX_ATTEMPTS,
            )
            continue
        genre = _parse_genre(llm_client.extract_final_text(response))
        if genre != FALLBACK_GENRE:
            return genre
        # 解析退兜底：再试一次（可能首次模型多嘴）；最后一轮就认了。
        logger.info(
            "genre_detect parse fell back to %s (attempt %d/%d)",
            FALLBACK_GENRE, attempt, _MAX_ATTEMPTS,
        )
    return FALLBACK_GENRE


__all__ = [
    "DEFAULT_GENRE_MAX_TOKENS",
    "FALLBACK_GENRE",
    "GENRES",
    "detect_genre",
    "genre_to_argument_axis",
    "is_theory_genre",
]
