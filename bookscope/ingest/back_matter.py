"""书末非正文区剔除（#48）——书末的参考文献 / 注释 / 附录 / 索引 / 后记 / 致谢。

整本书功能（时间线 / 伏笔 / 章脉等 map-reduce）的共享上游是 ``_long_context_inputs``，
它把整本书切成 chunks 再喂 LLM。若出版社 / 排版把参考文献等并进最后一章（无独立章号），
map-reduce 会把书末区当正文抽，产出"最后一章事件爆炸"类假象。本模块把这类区域
从 full_text 与 chunks 两侧剔掉。

识别**保守**（宁漏不误杀）：
1. 该 chunk 在最后一个有章号的正文章之后；
2. 首行（去空白/标点后）命中书末区标题关键词（参考文献 / 注释 / 附录 / 索引 / 后记 /
   致谢，含英文常见写法），且行首标题短（< 40 字，防正文句子误中）；
3. 从首个命中点之后全部剔除（书末区是连续尾部块）。

不满足以上任一条 → 原样返回（不动数据）。
"""

from __future__ import annotations

import re
from typing import Any

# 书末区标题关键词（按行首匹配；中英常见写法）
_BACK_MATTER_PATTERNS = (
    r"参考文献",
    r"注释",
    r"附录",
    r"索引",
    r"后记",
    r"致谢",
    r"references",
    r"bibliography",
    r"appendix",
    r"notes",
    r"index",
    r"acknowledg",
)
_COMPILED = [re.compile(p, re.IGNORECASE) for p in _BACK_MATTER_PATTERNS]
_MAX_TITLE_LEN = 20


def _looks_like_back_matter_title(line: str) -> bool:
    """首行是否像书末区标题：去空白/常见标点后，**行首**命中关键词且整行短。"""
    t = re.sub(r"[\s\u3000——\-—_·.。:：、，,()（）\[\]【】]", "", line)
    if not t or len(t) > _MAX_TITLE_LEN:
        return False
    for pat in _COMPILED:
        if pat.match(t):
            return True
    return False


def exclude_back_matter(
    full_text: str,
    chunks: list[Any],
) -> tuple[str, list[Any]]:
    """从全文与 chunks 两侧剔除书末非正文区；无法保守判断时原样返回。"""
    if not chunks:
        return full_text, chunks

    # 候选：首行命中书末标题的 chunk
    candidates = []
    for c in chunks:
        text = getattr(c, "text", "") or ""
        first_line = text.splitlines()[0] if text else ""
        if _looks_like_back_matter_title(first_line):
            candidates.append(c)

    # 保守判定：取按 index 序第一个候选，要求**其后没有章号更大的 chunk**
    # （书末区 = 尾部连续块；参考文献出现在书中、后面还有更新的章 → 不动）。
    cut: int | None = None
    for c in candidates:
        max_after = max(
            (x.chapter for x in chunks if x.index > c.index and x.chapter is not None),
            default=None,
        )
        if max_after is None or max_after <= (c.chapter or 0):
            cut = c.index
            break
    if cut is None:
        return full_text, chunks

    kept = [c for c in chunks if c.index < cut]
    if not kept:
        return full_text, chunks

    # 3) full_text 同步截到 cut chunk 的起点：逐行找 cut 首行（去空白比较，防行内格式差异）
    cut_text = next((getattr(c, "text", "") for c in chunks if c.index == cut), "")
    cut_first = re.sub(r"\s+", "", cut_text.splitlines()[0]) if cut_text else ""
    if cut_first:
        for i, ln in enumerate(full_text.splitlines()):
            if re.sub(r"\s+", "", ln) == cut_first:
                full_text = "\n".join(full_text.splitlines()[:i])
                break
    return full_text, kept
