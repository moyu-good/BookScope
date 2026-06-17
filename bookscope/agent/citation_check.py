"""citation 校验层 —— 把"引用来自原文"从 LLM 自称变成系统比对的事实。

设计出处：``docs/internal/design/WP1-citation-trust-chain.md``（2026-06-10 过闸）。

工作方式：``AgentLoop.query`` / ``run_fast_path`` 在一次查询内登记所有
工具返回的原文（证据登记表），final answer 解析成功后调
:func:`verify_citations` 给每条 citation 附加四个字段：

- ``verified``：snippet 能否在登记过的原文里找到（精确子串或 3-gram
  containment ≥ :data:`CONTAINMENT_THRESHOLD`）
- ``chunk_id``：命中的登记条目 id；没命中为 ``None``
- ``match_score``：匹配分（精确命中 1.0；否则最大 containment，两位小数）
- ``match_type``：证据强度三态——``"quote"`` 逐字命中 / ``"paraphrase"``
  诚实转述（过阈值但非逐字）/ ``"none"`` 未核验。把"verified 二元"细化成
  用户能分辨可信度的三档（exp-008 发现程序校验分不开逐字与转述，这里分开）。

**首版只观测不执法**：unverified 的 citation 不删除、不重答、不改
answer——先把 verified 率变成可观测量（钱学森控制论：观测先于执法），
拿到真实分布数据后再定 enforcement 策略。

纯标准库实现，不引入新依赖（Karpathy 简洁原则）。
"""

from __future__ import annotations

CONTAINMENT_THRESHOLD: float = 0.6
"""3-gram containment 的 verified 阈值。

工程起点值，留调——阈值标定实验不在 WP1 首版做（见设计稿"不做什么"）。
"""

_NGRAM_SIZE: int = 3
"""字符 n-gram 的 n。中文场景 3 字一组已能区分改写与编造。"""

# 全角标点 → 半角等价物。归一化的目的：LLM 引用原文时常把全半角标点
# 互换（"，"↔","、中文引号↔ASCII 引号），这不该影响"是否原文"的判定。
_PUNCT_TRANSLATION = str.maketrans({
    "，": ",",
    "。": ".",
    "！": "!",
    "？": "?",
    "；": ";",
    "：": ":",
    "“": '"',  # 左双引号 “
    "”": '"',  # 右双引号 ”
    "‘": "'",  # 左单引号 ‘
    "’": "'",  # 右单引号 ’
    "（": "(",
    "）": ")",
    "【": "[",
    "】": "]",
    "《": "<",
    "》": ">",
    "、": ",",
    "—": "-",
    "…": ".",
})


def normalize_text(s: str) -> str:
    """归一化文本：去掉所有空白字符，全角标点转半角。

    比对前两边都过这一层，让空白差异与全半角标点差异不影响匹配。
    """
    no_space = "".join(s.split())
    return no_space.translate(_PUNCT_TRANSLATION)


def char_ngram_containment(needle: str, haystack: str, n: int = _NGRAM_SIZE) -> float:
    """needle 的字符 n-gram 集合有多大比例出现在 haystack 里，返回 0-1。

    containment 而不是 Jaccard：haystack（整个 chunk）天然比 needle
    （一句引用）长得多，Jaccard 会被 haystack 的体量稀释；containment
    只问"引用里的碎片有多少真在原文里"，方向正确。

    needle 太短凑不出一个 n-gram 时返回 0.0（无法判定按不命中处理）。
    """
    if len(needle) < n or len(haystack) < n:
        return 0.0
    needle_grams = {needle[i : i + n] for i in range(len(needle) - n + 1)}
    if not needle_grams:
        return 0.0
    haystack_grams = {haystack[i : i + n] for i in range(len(haystack) - n + 1)}
    hit = sum(1 for g in needle_grams if g in haystack_grams)
    return hit / len(needle_grams)


def verify_citations(
    citations: list[dict],
    evidence: dict[str, dict],
) -> list[dict]:
    """对每条 citation 比对证据登记表，附加 verified / chunk_id / match_score。

    Args:
        citations: final answer 解析出的引用列表，每条至少含
            ``chapter`` + ``snippet``。原有字段不动，新字段附加。
        evidence: 证据登记表，``{chunk_id: {"chapter": int, "text": str}}``。

    Returns:
        同一批 citation dict（原地附加后返回）。标注算法：

        1. snippet 归一化后是任一登记 chunk 归一化文本的精确子串
           → ``verified=True, match_score=1.0, chunk_id=命中者``
        2. 否则对全部登记 chunk 求最大 3-gram containment：
           ≥ :data:`CONTAINMENT_THRESHOLD` → ``verified=True`` + 命中 chunk_id；
           < 阈值 → ``verified=False, chunk_id=None``，``match_score`` 记
           最大值（供观测分布用）。
    """
    # 登记表归一化只做一遍，不在每条 citation 里重复算
    normalized_evidence = {
        cid: normalize_text(str(entry.get("text", "")))
        for cid, entry in evidence.items()
    }

    for cit in citations:
        snippet = normalize_text(str(cit.get("snippet", "")))

        best_score = 0.0
        best_chunk_id: str | None = None
        exact_hit: str | None = None

        for cid, norm_text in normalized_evidence.items():
            if not snippet or not norm_text:
                continue
            if snippet in norm_text:
                exact_hit = cid
                break
            score = char_ngram_containment(snippet, norm_text)
            if score > best_score:
                best_score = score
                best_chunk_id = cid

        if exact_hit is not None:
            cit["verified"] = True
            cit["chunk_id"] = exact_hit
            cit["match_score"] = 1.0
            cit["match_type"] = "quote"  # 逐字命中（归一化后精确子串）
        elif best_score >= CONTAINMENT_THRESHOLD:
            cit["verified"] = True
            cit["chunk_id"] = best_chunk_id
            cit["match_score"] = round(best_score, 2)
            cit["match_type"] = "paraphrase"  # 诚实转述（n-gram 覆盖过阈值但非逐字）
        else:
            cit["verified"] = False
            cit["chunk_id"] = None
            cit["match_score"] = round(best_score, 2)
            cit["match_type"] = "none"  # 未核验（原文里找不到对应）

    return citations


__all__ = [
    "CONTAINMENT_THRESHOLD",
    "char_ngram_containment",
    "normalize_text",
    "verify_citations",
]
