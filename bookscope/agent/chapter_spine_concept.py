"""概念演进 = 章脉派生(轻 LLM)。ADR-010 出路 B 的一个视图。

**为什么改章脉派生**:概念演进天生**跨全书**——一个核心概念从第几章提出、哪几章展开、到哪章
深化,要按章序串起整本才看得清。老实现 ``generate_concept_evolution`` 整本一次进 context,大书
截断,被截掉的后半本里这个概念怎么深化的就丢了,"全程演进"打折。

做法:从章脉收**全书逐章主张(claims,理论书)+ 事件 / 人物处境(小说当线索)**当紧凑清单,
**一次 LLM 调用**让模型挑出和这个概念相关的章、按章序排出演进阶段。章脉是"整本压缩成结构",
一次看全书既不截断、又串得起全程。

**为主理论书,小说退而求其次**:概念演进主打理论 / 论说书(章脉有 claims 维)。小说没 claims,
退用 events + char_states 当线索——能跟"权谋""忠义"这类母题在小说里的演变,但不如理论书的概念
追踪准。两类都能跑,不空着。

**证据**:每阶段锚到章脉里真实的章。传了 ``chunks``(全书原文)时,snippet 按「这阶段的
development + 概念名」在那章原文里**现捞**最相关那句——证的是「这个概念在这章这么发展」,不是
那章最显眼的别的事(老做法取章脉那条章代表句,会张冠李戴)。没传 ``chunks`` 时回退老行为(取章
脉那章已核验的 evidence),向后兼容。命根子=书里没有这个概念返空、不编;这阶段在那章原文捞不到
支撑句也丢(同老版 verify-filter 的语义升级)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.chapter_spine_evidence import find_supporting_sentences
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_CONCEPT_MAX_TOKENS = 32000
"""阶段条数 ∝ 概念在全书出现的章,加 reasoning 头,给足防截断。

deepseek-v4-flash 是 reasoning 模型,reasoning_content 算进 max_tokens(见
[[reference_reasoning_model_token_budget]])。三国实测密集概念(如「权谋」)能排到 50 阶段
(``_MAX_STAGES`` 帽),每阶段带一句 development + 长 reasoning,24000 会被截在中途(靠抢救
只捞回前几条)。给 32000 让密集概念也吐得完;再大靠 ``_parse_stages`` 截断抢救兜底。"""

_MAX_STAGES = 50
_MAX_CLAIMS_PER_CH = 5
_MAX_STATES_PER_CH = 4
_MAX_EVENTS_PER_CH = 3

_CONCEPT_INSTR = (
    "下面 chapters 是一本书逐章的紧凑摘要:claims 是这章提出 / 论证的主张、states 是主要人物的"
    "处境、events 是主要事件。用户会给一个**概念**。\n"
    "请在这份全书摘要里挑出和这个概念相关的章,**按章节先后**排出它的演进——每个阶段在哪章、"
    "这一处概念被怎么提出 / 用 / 深化 / 转义。\n"
    "- order 从 1 起递增,按 chapter 升序。\n"
    "- 只挑摘要里**确实涉及**这个概念的章,只据摘要、不编。\n"
    "- **书里没有这个概念就返回空数组,绝不编造演进。**\n"
    "development 用一句话说清这一处概念怎么发展。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"stages":[{"order":序号整数,"chapter":章号整数,"development":"这一处概念怎么发展"}]}'
)


def _collect_inventory(
    spine: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[int], dict[int, str]]:
    """从章脉收 逐章摘要清单 + 章集 + 章号→已核验证据。

    每章摘出 claims(理论书主线)/states/events 拼成紧凑清单当输入;原文证据不进输入
    (只在出结果时按章号取章脉那章已核验的 evidence)。返回 (digest, 全部章集, 章号→evidence)。
    """
    digest: list[dict[str, Any]] = []
    all_chs: set[int] = set()
    evidence: dict[int, str] = {}
    for rec in spine:
        if not isinstance(rec, dict):
            continue
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        all_chs.add(ch)
        evidence[ch] = str(rec.get("evidence", "")).strip()

        entry: dict[str, Any] = {"章": ch}
        cl = rec.get("claims")
        if isinstance(cl, list):
            claims = [str(c).strip() for c in cl[:_MAX_CLAIMS_PER_CH] if str(c).strip()]
            if claims:
                entry["claims"] = claims
        cs = rec.get("char_states")
        if isinstance(cs, list):
            states: list[str] = []
            for s in cs[:_MAX_STATES_PER_CH]:
                if isinstance(s, dict):
                    name = str(s.get("name", "")).strip()
                    state = str(s.get("state", "")).strip()
                    if name and state:
                        states.append(f"{name}:{state}")
                    elif state:
                        states.append(state)
            if states:
                entry["states"] = states
        ev = rec.get("events")
        if isinstance(ev, list):
            events = [
                str(e.get("event", e) if isinstance(e, dict) else e).strip()
                for e in ev[:_MAX_EVENTS_PER_CH]
            ]
            events = [e for e in events if e]
            if events:
                entry["events"] = events
        digest.append(entry)
    return digest, all_chs, evidence


def _parse_stages(text: str) -> list[dict[str, Any]] | None:
    """解析 ``{"stages":[...]}``;三层兜底(直解析 / 切首个对象 / 截断抢救)。

    空数组(概念不在书)是合法结果返 ``[]``;彻底解析不出返 ``None``。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    candidate = strip_code_fence(raw)
    obj: Any = None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        sliced = extract_first_json_object(candidate)
        if sliced is not None:
            try:
                obj = json.loads(sliced)
            except json.JSONDecodeError:
                obj = None
    if isinstance(obj, dict) and isinstance(obj.get("stages"), list):
        return obj["stages"]
    salvaged = salvage_closed_objects(candidate, '"stages"')
    if salvaged:
        logger.warning(
            "chapter_spine_concept: 主解析失败,从截断抢救到 %d 阶段", len(salvaged)
        )
        return salvaged
    return None


def _bigrams(text: str) -> list[str]:
    """把概括过的文本拆 2-gram 当检索词(中文没空格切词,用 bigram 衡量某句像不像在讲这件事)。"""
    e = re.sub(r"\s+", "", text or "")
    return list({e[i : i + 2] for i in range(len(e) - 1)})


def _chapter_text_map(chunks: list[dict[str, Any]]) -> dict[int, str]:
    """章号 → 该章全部 chunk 原文拼接。给每阶段按「概念怎么发展」在该章原文里现捞证据用。

    同 ``chapter_spine_relationship._chapter_text_map`` 的做法(各功能自留一份,免跨模块耦合)。
    """
    by_ch: dict[int, list[str]] = {}
    for c in chunks:
        ch = c.get("chapter")
        txt = str(c.get("text", ""))
        if isinstance(ch, int) and txt:
            by_ch.setdefault(ch, []).append(txt)
    return {ch: "\n".join(parts) for ch, parts in by_ch.items()}


def concept_evolution_from_spine(
    *,
    concept: str,
    spine: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    chunks: list[dict[str, Any]] | None = None,
    max_tokens: int = DEFAULT_CONCEPT_MAX_TOKENS,
    cache_enabled: bool = True,
) -> list[dict[str, Any]] | None:
    """章脉全书摘要一次 LLM 排概念演进阶段 → 阶段 list。失败返 ``None``,概念不在书返 ``[]``。

    阶段形态同 ``generate_concept_evolution``:``{order, chapter, development, snippet, verified}``。
    chapter 必须是章脉真实章(防 LLM 编)。snippet 来源:传了 ``chunks`` 就按「这阶段
    development + 概念名」在那章原文现捞那句(证「这概念在这章这么发展」,不张冠李戴);没传
    ``chunks`` 回退到章脉那章已核验的章代表句(老行为,向后兼容)。两种来源都遵守「snippet 空就
    丢这阶段」——传了 ``chunks`` 时它防的是「这阶段在那章原文捞不到支撑句」,语义比章级锚更对。
    按 chapter 升序、重编 order;同章只留一个(同章重复阶段没意义)。
    """
    concept = (concept or "").strip()
    if not concept:
        return None
    digest, all_chs, evidence = _collect_inventory(spine)
    if not all_chs:
        return None
    chapter_text = _chapter_text_map(chunks) if chunks else None

    user_content = json.dumps(
        {"concept": concept, "chapters": digest}, ensure_ascii=False
    )
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_CONCEPT_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 调用失败降级返 None,不 break 端点
        logger.warning(
            "chapter_spine_concept: 演进调用抛 %s: %s;返 None", type(exc).__name__, exc
        )
        return None

    parsed = _parse_stages(text)
    if parsed is None:
        return None

    out: list[dict[str, Any]] = []
    seen_ch: set[int] = set()
    for st in parsed:
        if not isinstance(st, dict):
            continue
        ch = st.get("chapter")
        if not isinstance(ch, int) or ch not in all_chs or ch in seen_ch:
            continue  # 锚到真实章(防编);同章去重
        development = str(st.get("development", "")).strip()
        if chapter_text is not None:
            # 现捞:按「概念名 + 这阶段 development 拆的 bigram」在那章原文找最相关那句。
            # development 是 LLM 概括过的整句,当不了精确子串(中文也没空格切词),拆 2-gram 衡量
            # 「哪句最像在讲这概念这么发展」(同 evidence_for_event 思路);捞不到留空。
            terms = [concept, *_bigrams(development)]
            hits = find_supporting_sentences(chapter_text.get(ch, ""), terms, top_k=1)
            snip = hits[0] if hits else ""
        else:
            snip = evidence.get(ch, "")  # 没传 chunks:回退章脉那章章代表句(老行为)
        if not snip:
            continue  # 捞不到支撑句 / 章脉那章没留证据:丢这阶段(立身之本)
        seen_ch.add(ch)
        out.append({
            "chapter": ch,
            "development": development,
            "snippet": snip,
            "verified": True,
        })
        if len(out) >= _MAX_STAGES:
            break
    out.sort(key=lambda s: s["chapter"])
    for i, s in enumerate(out, start=1):
        s["order"] = i  # 按章序重编 order
    # order 放最前(同老版字段顺序习惯,前端不依赖顺序但读着顺)
    out = [
        {"order": s["order"], "chapter": s["chapter"], "development": s["development"],
         "snippet": s["snippet"], "verified": s["verified"]}
        for s in out
    ]
    return out  # 可空(概念不在书 / 锚不到真实章)


__all__ = ["DEFAULT_CONCEPT_MAX_TOKENS", "concept_evolution_from_spine"]
