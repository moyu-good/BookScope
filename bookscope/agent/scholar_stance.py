"""学者立场谱：理论书跟哪些思想家对话、各自站在本书核心争论的哪一极。

设计缘起：立场格局（阵营 + 命运）是叙事镜头，套理论书别扭——被引学者没处境、没二元
阵营。给理论书做合身镜头：一次长上下文让模型①定本书自己的核心争论轴（用本书的话）；
②开放抽取书里对话的学者，有立场的摆到轴上、逐个挂原文原句。probe exp033 在《制内市场》
真语料上验过 GO：grounding（片段归一）≥90% + 塞的假学者名全被判 stance_stated=false
（假阳性 ≤20%）。

依托（prior-art，非发明）：

- Stance detection（SemEval-2016 T6）：对 target 判 favor/against/**none**；none 类治
  "只提名没讲立场"——本模块的 ``stance_stated=false``。
- Citation function（Teufel）/ 引文情感（Athar）：本书对被引者是支持 / 对立 / 借用。
- Toulmin（``character_stance`` 已用）：主张 + grounds（原文原句）。

复用整本书功能套路（``project_wholebook_feature_pattern``）：book-first 长上下文（书在前、
指令在后，冲 DeepSeek 前缀缓存）+ 结构化 JSON + ``finish_reason=length`` 加倍重试
（reasoning 挤爆 max_tokens 的救法，同 ``minimal_kg_extractor``）。缓存开着——同一本书同一
谱答案稳定，命中省整本 input token（同 :func:`suggest_stance_axis`）。

引文核验（命门，exp022/exp033 教训）：**绝不整条引文子串比对**——模型爱把不相邻的句子用
"……"拼成一条、还内嵌「」，整条比对必挂。按**片段**核：归一（去空白 + 全角标点转半角 +
删引号 / 角括号）后按省略号 / 句读切成 ≥8 字片段，任一片段是归一后原书子串就认
``quote_verified``。归一层复用 :func:`bookscope.agent.citation_check.normalize_text`；OR
语义 + 整书（非 chunk）比对是本功能特有，故单独实现（现成 ``_loose_verify`` 是 chunk 级 +
多片段 AND 语义，不匹配本 spec）。

graceful 退场：抽不出轴、或有立场的学者 < 2 个 → ``scanned=False``，前端不画谱
（evidence-first：判不出不硬造，同 :func:`suggest_stance_axis`）。

契约：返 ``{scanned, axis|None, scholars:[{name, stance_stated, pole, position, quote,
quote_verified, brief}]}``；任意环节判不出返 ``{"scanned": False, "axis": None,
"scholars": []}``（本函数不返 None——总给前端一个可渲染的形状）。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent._internal.loop_shared import read_openai_finish_reason
from bookscope.agent.citation_check import normalize_text
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_SCHOLAR_STANCE_MAX_TOKENS = 12000
"""密集理论书 + 输出带每个学者的原文引文，比批量立场长；flash 把 reasoning 算进 max_tokens，
4000 会撞 ``finish_reason=length`` 空返（exp033 实测），给到 12000 打底，length 再加倍重试。"""

_LENGTH_BUMP_CAP = 24000
"""``finish_reason=length`` 加倍重试的 max_tokens 上限（同 ``minimal_kg_extractor``）。"""

_MAX_ATTEMPTS = 3
"""调用尝试上限：够 length 加倍一次 + 抛错重试一次的余量。"""

_MIN_STANCE_SCHOLARS = 2
"""有立场（且带引文）的学者少于此数就不画谱——谱立不住，graceful 退场。"""

_MIN_FRAG = 8
"""片段核验里一个片段够长才拿去核（CJK 字符数，同 probe exp033 的 ≥8）。"""

# 归一：normalize_text 已去空白 + 全角标点转半角（，。；：！？“”‘’《》【】…— 等），
# 这里再删角括号「」『』 + ASCII 引号——专治模型引用时内嵌「」/ 给术语加引号（exp022）。
_QUOTE_STRIP = str.maketrans({c: None for c in "「」『』\"'`"})

# 片段切分：省略号（归一后 …→. 故表现为 2+ 点）或句读（。！？；，归一后已是半角）。模型爱用
# "……"拼不相邻句，切开逐段核才不被整条拼接坑。
_FRAG_SPLIT = re.compile(r"\.{2,}|[.!?;,]")


def _norm(s: str) -> str:
    """归一化：复用 :func:`normalize_text`（去空白 + 全角标点转半角）再删角括号 / 引号。"""
    return normalize_text(s or "").translate(_QUOTE_STRIP)


def _quote_grounded(quote: str, full_norm: str) -> bool:
    """按片段核 ``quote`` 是否锚原书：归一后按省略号 / 句读切 ≥8 字片段，任一是 ``full_norm``
    子串即认。

    绝不整条子串比对——模型把不相邻句用"……"拼一条、内嵌「」，整条必挂（exp022/exp033
    教训）。片段全 <8 字（碎）时退回整条归一串核，守精度不放拼接进来。
    """
    qn = _norm(quote)
    if len(qn) < _MIN_FRAG:
        return False
    frags = [f for f in _FRAG_SPLIT.split(qn) if len(f) >= _MIN_FRAG]
    if not frags:
        return qn in full_norm
    return any(f in full_norm for f in frags)


def _parse(raw: str) -> dict | None:
    obj = _extract_first_json_object(_strip_code_fence(raw or ""))
    if obj is None:
        return None
    try:
        parsed = json.loads(obj)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _clean_pole(pole: Any, stated: bool) -> str:
    """pole 收敛到 ``{a, b, 中, ""}``：只提名（未表态）一律空；表态的取 a/b/中，越界落中。"""
    if not stated:
        return ""
    p = str(pole or "").strip()
    return p if p in ("a", "b", "中") else "中"


def _clean_position(position: Any) -> int:
    """position 夹回 ``[-5, 5]``；给不出数字按 0（居中）。"""
    try:
        return max(-5, min(5, int(position)))
    except (TypeError, ValueError):
        return 0


def _mentions(name: str, full_text: str) -> int:
    """数这个学者在书里被提多少次(全名或姓,取较大者)——当十字轴横轴"被讨论的分量"。
    可数、grounded、不靠 LLM 猜(同人物象限横轴=戏份的道理)。外文名取 · 末段当姓。"""
    n = (name or "").strip()
    if not n:
        return 0
    counts = [full_text.count(n)]
    surname = n.split("·")[-1]
    if surname and surname != n and len(surname) >= 2:
        counts.append(full_text.count(surname))
    return max(counts)


def scholar_stance_spectrum(
    *,
    full_text: str,
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_SCHOLAR_STANCE_MAX_TOKENS,
    book_session_id: str | None = None,
) -> dict[str, Any]:
    """一次长上下文抽本书核心争论轴 + 对话学者各自的立场；判不出返 graceful 空。

    ``book_session_id`` 仅签名兼容（同 ``character_stance`` 的 ``session_id``）——本任务开
    缓存（同书同谱稳定，book-first 前缀缓存省整本 input token）。

    Returns:
        ``{"scanned": bool, "axis": {pole_a, pole_b, from_book}|None,
        "scholars": [{name, stance_stated, pole, position, quote, quote_verified,
        brief}]}``。抽不出轴 / 有立场学者 < 2 → ``{"scanned": False, "axis": None,
        "scholars": []}``。
    """
    _ = book_session_id
    graceful: dict[str, Any] = {"scanned": False, "axis": None, "scholars": []}

    instruction = (
        "你是严谨的学术著作立场分析助手。\n"
        "任务：这本书在跟哪些学者 / 思想家对话？各自站在**本书核心争论**的哪一极？\n"
        "铁律（违反即失败）：\n"
        "1. 只据本书原文判。**不许用你自己知道的这些学者的观点**——哪怕你知道某人主张什么，"
        "本书没写就不算。每条立场必须能在原文里找到刻画他立场的**原句**。\n"
        "2. 先定这本书自己的核心争论轴：一条，两极（pole_a / pole_b），用本书的话概括。\n"
        "3. 逐个学者：stance_stated=本书有没有明说 / 刻画他的立场（true/false）。"
        "只提到名字 / 引用数据、没讲立场 = false，**这种绝不许编立场**。\n"
        "4. 有立场（true）才给：pole（a/b/中）+ quote（本书原文里刻画其立场的原句，逐字照抄，"
        "别改字）+ position + brief。\n"
        "5. position = 立场位置整数（-5..5）：-5 = 紧贴 pole_a 一极 .. 0 = 居中 .. "
        "+5 = 紧贴 pole_b 一极。只提名（stance_stated=false）的一律给 0。"
    )
    system = build_longctx_system(full_text, instruction)
    user = (
        "严格只输出 JSON（不要别的话、不要 markdown 围栏）：\n"
        '{"axis":{"pole_a":"","pole_b":"","from_book":"这条轴的依据，用本书原话概括"},'
        '"scholars":[{"name":"","stance_stated":true,"pole":"a|b|中","position":0,'
        '"quote":"本书原文原句","brief":"一句"}]}\n'
        "把本书真讨论的学者尽量抽全：有立场的、只提名的都列。只提名的 stance_stated=false、"
        "pole 留空、position=0、quote 留空，绝不给它编立场。"
    )

    eff_max_tokens = max_tokens
    length_bumped = False
    obj: dict | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=[{"role": "user", "content": user}],
                max_tokens=eff_max_tokens,
                cache_enabled=True,
            )
        except Exception as exc:  # noqa: BLE001 — 包死，重试 / 返 graceful
            logger.warning(
                "scholar_stance LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        parsed = _parse(llm_client.extract_final_text(response))
        if isinstance(parsed, dict) and isinstance(parsed.get("scholars"), list):
            obj = parsed
            break
        # 解析不出对象 / 没 scholars 数组：可能 reasoning 挤爆 max_tokens
        # （finish_reason=length），加倍预算重试一次（同 minimal_kg_extractor）；
        # 非 length 的解析失败不硬重试（重试同 prompt 大概率同结果，白烧 token）。
        fr = read_openai_finish_reason(response)
        if fr == "length" and not length_bumped:
            eff_max_tokens = min(eff_max_tokens * 2, _LENGTH_BUMP_CAP)
            length_bumped = True
            logger.info(
                "scholar_stance 撞 finish_reason=length，max_tokens→%d 重试一次",
                eff_max_tokens,
            )
            continue
        logger.warning(
            "scholar_stance 解析不出 JSON 对象（attempt %d/%d, finish_reason=%s）",
            attempt, _MAX_ATTEMPTS, fr,
        )
        break

    if obj is None:
        return graceful

    # ---- 核心争论轴 ----
    axis_raw = obj.get("axis")
    if not isinstance(axis_raw, dict):
        return graceful
    pole_a = str(axis_raw.get("pole_a", "")).strip()
    pole_b = str(axis_raw.get("pole_b", "")).strip()
    if not pole_a or not pole_b:
        return graceful  # 抽不出核心争论轴 → 不画谱（evidence-first）
    axis = {
        "pole_a": pole_a,
        "pole_b": pole_b,
        "from_book": str(axis_raw.get("from_book", "")).strip(),
    }

    # ---- 学者（逐个片段核引文）----
    full_norm = _norm(full_text)
    scholars: list[dict[str, Any]] = []
    seen: set[str] = set()
    n_stated = 0
    for s in obj["scholars"]:
        if not isinstance(s, dict):
            continue
        name = str(s.get("name", "")).strip()
        if not name or name in seen:  # 空名 / 重名跳过
            continue
        seen.add(name)
        stated = bool(s.get("stance_stated"))
        # 只提名的绝不留立场痕迹：quote / pole / position 全清空，防前端把它画上谱
        quote = str(s.get("quote", "") or "").strip() if stated else ""
        verified = _quote_grounded(quote, full_norm) if quote else False
        if stated and quote:
            n_stated += 1
        scholars.append(
            {
                "name": name,
                "stance_stated": stated,
                "pole": _clean_pole(s.get("pole"), stated),
                "position": _clean_position(s.get("position")) if stated else 0,
                "quote": quote,
                "quote_verified": verified,
                "brief": str(s.get("brief", "") or "").strip(),
                # 十字轴横轴:被本书讨论的分量(核心 ↔ 边缘)。只提名的也数,给前端排布用。
                "mentions": _mentions(name, full_text),
            }
        )

    if n_stated < _MIN_STANCE_SCHOLARS:
        return graceful  # 有立场的学者太少 → 谱立不住，退回不画

    return {"scanned": True, "axis": axis, "scholars": scholars}


__all__ = ["DEFAULT_SCHOLAR_STANCE_MAX_TOKENS", "scholar_stance_spectrum"]
