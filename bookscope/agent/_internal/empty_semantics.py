"""evidence-first 空值三态(task #29 根一)——书侧整本功能的「空」分三态。

公文头要素那套三态(``doc_spine`` 的 present / absent_confirmed / unverified)铺到书侧
四个整本功能:设定一致性 / 伏笔回收 / 实体回溯 / 人物关系图。规格见
``docs/design/WP-evidence-empty-semantics.md`` 根一。

**问题**:这些功能遇到"结果空"一律落"待核 / 没找到",但"空"有两种意思天差地别——
扫了全书确实没有(笃定答案,常是用户最想知道的),跟真没扫到 / 扫失败(才该待核)混成一个,
把笃定的"无"显示得像系统故障。

**三态**(与 ``doc_spine`` 同枚举):

- ``present``      扫到了 + 有结果(列表非空)——现状不变,逐条展示。
- ``confirmed_empty`` **确证为无**——功能**真扫过全书**(有扫描证据)且结果空。这是笃定答案:
  全书自洽无矛盾 / 全书未出现这个实体 / 全书没有挂得上原文的伏笔。前端正面 / 笃定显示
  (善本风格的好消息),绝不显成系统故障。
- ``unverified``   **真没扫到 / 扫失败**——才显"待核 / 没扫到 / 重试"。

**evidence-first 死守(最关键,做错=危险的假安心)**:``confirmed_empty`` **只在功能真的扫过
全书 + 确实空时才标**。判据是 deterministic 的 ``scanned``——它由各 BE 模块的返回值定:
返回 ``None``(解析不出 / 调用失败 / 没有可扫的结构) = 没扫成 = ``scanned=False``;返回
列表(含空列表) = 扫成了。**LLM 只是返了空、没真扫到 ≠ 确证无**:那种情形 BE 会返
``None``(``scanned=False``),落 ``unverified``,绝不冒充确证无。这跟公报截断假装"确证一致
无弦外"是同一个危险,务必分清。

各功能的"扫了全书"扫描证据(各 BE 模块已保证):

- 设定一致性(``consistency_scan_from_spine``):章脉(整本压缩成的逐章摘要)被一次性喂进
  模型找前后矛盾。返列表 = 在全书摘要里扫过;``[]`` = 扫过且无矛盾 = 确证无矛盾。
- 伏笔回收(``foreshadow_from_spine``):章脉全书"埋点 + 事件流"一次跨章配对。返列表 = 扫过;
  ``[]`` / 没埋点 → 返 ``None``(scanned=False,unverified)。注意单条弧的 ``status="dangling"``
  (埋了没回收)是**另一层**确证——那是"这条伏笔确证未回收",由各弧自己带,不归这套列表级三态。
- 实体回溯(``generate_entity_recall``):整本原文进 context 回溯某实体。返列表 = 扫过全书;
  ``[]`` = 扫过且全书未出现该实体(probe 实测假阳性 0%) = 确证全书未出现。
- 人物关系图:**不归这套**——图是"画出存在的边",没有"给定两人、确证无边"的 per-pair 扫描;
  图里没那条边可能是边数帽 / 渲染过滤 / 合并去重,不是"确证两人无共现"。要做"确证无关系
  证据"得另开 per-pair 模式(同关系编年下钻),本轮不强做(见回报)。
"""

from __future__ import annotations

from typing import Any

# 三态枚举(与 doc_spine 的 HEAD_STATUS_* 同语义,书侧列表结果版)。
EMPTY_STATUS_PRESENT = "present"
EMPTY_STATUS_CONFIRMED_EMPTY = "confirmed_empty"
EMPTY_STATUS_UNVERIFIED = "unverified"
EMPTY_STATUSES: tuple[str, ...] = (
    EMPTY_STATUS_PRESENT,
    EMPTY_STATUS_CONFIRMED_EMPTY,
    EMPTY_STATUS_UNVERIFIED,
)


def classify_scan_result(result: list[Any] | None) -> str:
    """据 BE 模块的返回值给整本扫描结果定三态(deterministic,无脑补)。

    这是 evidence-first 的命门:``confirmed_empty`` **只**在 ``result`` 是真列表(扫成了)
    且为空时给。``None``(没扫成 / 失败)一律退 ``unverified`` —— 绝不把"模型返了空、没真扫到"
    冒充成"确证全书无"。

    Args:
        result: BE 模块的返回。``None`` = 没扫成(解析不出 / 调用失败 / 没有可扫结构);
            非空列表 = 扫到了有结果;空列表 = 扫过全书且确实没有(确证为无)。

    Returns:
        三态之一:
        - ``present``:``result`` 非空列表(有结果)。
        - ``confirmed_empty``:``result`` 是空列表(扫过全书 + 确实没有 = 确证为无)。
        - ``unverified``:``result`` 为 ``None``(没扫成 / 失败 = 真待核)。
    """
    if result is None:
        return EMPTY_STATUS_UNVERIFIED
    if len(result) == 0:
        return EMPTY_STATUS_CONFIRMED_EMPTY
    return EMPTY_STATUS_PRESENT


def is_confirmed_empty(result: list[Any] | None) -> bool:
    """``result`` 是不是"确证为无"(扫过全书 + 确实空)。便捷封装,语义同上。"""
    return classify_scan_result(result) == EMPTY_STATUS_CONFIRMED_EMPTY


__all__ = [
    "EMPTY_STATUSES",
    "EMPTY_STATUS_CONFIRMED_EMPTY",
    "EMPTY_STATUS_PRESENT",
    "EMPTY_STATUS_UNVERIFIED",
    "classify_scan_result",
    "is_confirmed_empty",
]
