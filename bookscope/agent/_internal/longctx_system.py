"""整本进上下文的 system 拼装：book-first，保 DeepSeek 前缀缓存跨功能命中。

DeepSeek 的 prompt 前缀缓存只缓存「从头起的最长公共前缀」。各「整本进上下文」
功能（人物关系图 / 长上下文答题 / 伏笔弧线 / 节奏曲线……）原本都按
``功能指令 + 书`` 拼 system——指令在前，各功能指令不同，前缀在指令处就分叉，
分叉点之后那段「书」（占输入 95%+）进不了公共前缀，于是**每个功能都把整本书
当 cache-miss 重付一遍**。一个目标连跑 3-4 个功能时尤其塌，命中率上不去。

修法是 **book-first**：让「书」当稳定前导前缀，功能专属指令挪到书**之后**。

    [所有功能一致的前导] + 书 + [分隔] + 功能指令 [+ 可选变化尾段]

前导 + 书这一段 byte 完全一致 → 跨功能、跨重复调用都命中同一段公共前缀 →
第一次 miss、后面全 hit。指令挪到书后语义不变：模型读完整本书再读「请抽取
……」照样懂。

所有整本功能都走 :func:`build_longctx_system`，别再各自手拼 ``指令 + 书``。
"""

from __future__ import annotations

# 所有整本功能共用的前导。必须 byte 一致——这是 DeepSeek 前缀缓存的公共前缀起点。
# 只说「下面是一整本书的完整原文，读完后面会给你具体任务」这类与功能无关的话，
# 不带任何功能专属措辞，否则前缀就在这里分叉了。
LONGCTX_PREAMBLE = (
    "你是严谨的长文本分析助手。下面 === 全书原文 === 之后是一整本书的完整原文。"
    "请先通读全书，再看本书原文之后给你的具体任务要求作答。"
)

# 书的起始分隔。前导 + 这个分隔 + 书构成跨功能不变的公共前缀。
BOOK_DELIMITER = "\n\n=== 全书原文 ===\n"

# 书与功能指令之间的分隔。指令落在书之后（变化段，但已在公共前缀末端之后）。
INSTRUCTION_DELIMITER = "\n\n=== 任务要求 ===\n"


def build_longctx_system(
    full_text: str,
    instruction: str,
    *,
    suffix: str | None = None,
) -> str:
    """拼出 book-first 的 system 串：前导 + 书 + 功能指令 [+ 变化尾段]。

    前导（``LONGCTX_PREAMBLE``）+ 书（``full_text``）这一段对所有功能 byte 一致，
    是 DeepSeek 前缀缓存的公共前缀；功能专属 ``instruction`` 落在书之后，跨功能
    不同也不破前缀。

    Args:
        full_text: 整本书 cleaned 原文。同一本书每次调用必须 byte 一致才命中缓存。
        instruction: 功能专属指令（抽什么 / 输出什么 JSON 形态等），挪到书之后。
        suffix: 可选变化尾段（如长上下文重答时 reviewer 的批评摘要），拼在指令更后
            面。每次都变的内容才放这里，绝不要放进前导或书。

    Returns:
        拼好的 system 字符串。
    """
    system = LONGCTX_PREAMBLE + BOOK_DELIMITER + full_text + INSTRUCTION_DELIMITER + instruction
    if suffix:
        system = system + "\n\n" + suffix
    return system


__all__ = ["build_longctx_system", "LONGCTX_PREAMBLE", "BOOK_DELIMITER", "INSTRUCTION_DELIMITER"]
