"""声口一致：给一个角色，整本进 context 归拢他的对白、刻画语言特征、标出"这句不像他说的"。

设计：WP-character-voice（probe GO：判别成立、三类对抗假阳性 0%）。

作家写长篇最容易翻车的地方之一——第 5 章那个粗豪武夫，到第 80 章嘴里冒出文绉绉的排比。
读者说不清哪不对，只觉得"出戏"。这件事把这种违和落成可定位、挂着原文的一条条提示。

和「人物弧线」不是一回事：弧线管动机/性格转变合不合理，声口管说话腔调一不一致。一个人物
可以性格没变而口吻飘了（作者手滑），也可以性格大变而口吻该跟着变（合理，不该报）。所以
这件事的命根子全在"别把合理的口吻变化判成 drift"。

复用 [[project_wholebook_feature_pattern]]：长上下文整本进 context + 结构化 JSON +
三守卫（够 token / 关缓存 / 重试 + 截断抢救）。每个特征、每条 drift 判定挂原文过
verify_citations。两种证据处理不同（设计 §4）：

1. **语言特征（features）**——保留全部，verified=false 的留着标低置信（前端淡化），
   evidence-first 但不剔（特征是描述性的，读者点开自己核）。
2. **drift 提示（drift_items）**——verify-filter：核不过的整条丢（同 study_cards），
   挂不上原文的 drift 是 agent 一面之词，不报。

命根子（probe 守住的，写进 prompt）：合理的剧情驱动口吻变化别报 drift、样本不足明说
不硬判、不把别人的话算到他头上。

契约：成功返 ``{features, drift_items}`` dict，**任意环节失败返 None**；角色对白太少
返 ``{features: [], drift_items: [], sample_too_small: True}``（合法，不是失败）。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent.citation_check import verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_VOICE_MAX_TOKENS = 8000
"""特征（每条挂代表对白）+ 多条 drift（每条挂原文 + 一句为什么）比单点判断长——给 8000
留 reasoning 头，防截断/空（同关系图/弧线/叙事流）。"""

_MAX_ATTEMPTS = 2
_MAX_FEATURES = 12
_MAX_DRIFT = 20

_SYSTEM_INSTRUCTION = (
    "你是 BookScope 的声口分析助手。下面 === 全书原文 === 之后是一整本书的全文。"
    "用户会给一个角色。请只根据这本书的原文，做两件事：\n"
    "一、把这个角色全书的对白归拢起来，刻画他说话的腔调，列出几条语言特征"
    "（口头禅、句式长短、文白程度、用词偏好、语气）。每条特征挂 1 句最能代表"
    "这条腔调的原文对白当依据。\n"
    "二、标出哪几句对白「不像他说的」（声口飘了）。每条挂上那句对白的原文 + "
    "所在章 + 一句话说明为什么觉得不像。\n"
    "三条铁律（违反就是冤枉好句子，宁可少报也别犯）：\n"
    "1. 角色在剧情里确实有理由换腔调（受了刺激变冷峻、地位变了说话端着、装扮成"
    "别人），这是合理的剧情驱动变化，**不算 drift，不要报**。只报那种没来由、"
    "像作者手滑写串了的违和。\n"
    "2. 这个角色全书对白很少、样本不够刻画稳定腔调时，**明说样本不足，不硬下 "
    "drift 判定**——把 sample_too_small 标 true，features 和 drift 给空或极少。\n"
    "3. 只算这个角色自己说的话。**别的角色说的话不要算到他头上**，更不要因为某句"
    "有特色就硬说成是他说的。\n"
    "只依据原文，不臆测、不编造。snippet 必须是原文里这个角色逐字说过的对白。\n"
    "严格输出 JSON（不要别的话、不要 markdown 代码围栏）：\n"
    '{"sample_too_small": false, '
    '"features": [{"trait": "这条语言特征", "evidence": "代表这条腔调的原文对白逐字片段"}], '
    '"drift_items": [{"chapter": 章号整数, "quote": "那句不像他说的对白原文逐字片段", '
    '"reason": "为什么觉得不像他说的"}]}\n'
    "features 最多约 6 条、宁可少而准；drift 默认从严，没把握的不报、空数组也没关系。"
)

_BOOK_DELIMITER = "\n\n=== 全书原文 ===\n"


def _coerce_features(raw: Any) -> list[dict[str, Any]]:
    """收编语言特征。trait 缺/空 → 丢（没特征名画不出卡）；evidence 可缺（缺则核不过、
    标低置信）。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        trait = str(item.get("trait", "")).strip()
        if not trait:
            continue
        out.append(
            {"trait": trait, "evidence": str(item.get("evidence", "")).strip()}
        )
        if len(out) >= _MAX_FEATURES:
            break
    return out


def _coerce_drift(raw: Any) -> list[dict[str, Any]]:
    """收编 drift 提示。quote 缺/空 → 丢（drift 没原文对白没法核也没法摆）；chapter
    非整数退 0、reason 可缺。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("quote", "")).strip()
        if not quote:
            continue
        ch = item.get("chapter")
        out.append(
            {
                "chapter": ch if isinstance(ch, int) else 0,
                "quote": quote,
                "reason": str(item.get("reason", "")).strip(),
            }
        )
        if len(out) >= _MAX_DRIFT:
            break
    return out


def _coerce(raw: Any) -> dict[str, Any] | None:
    """结构合法（dict 含 features / drift_items 任一为列表）→ 收编后的
    ``{sample_too_small, features, drift_items}``；结构非法 → ``None``（触发抢救/重试）。

    features 与 drift_items 都空、且 sample_too_small 不为 true 时也算合法结果（书里这个
    角色声口很稳、没扫出 drift），不返 None。"""
    if not isinstance(raw, dict):
        return None
    has_features = isinstance(raw.get("features"), list)
    has_drift = isinstance(raw.get("drift_items"), list)
    if not has_features and not has_drift:
        return None
    return {
        "sample_too_small": bool(raw.get("sample_too_small", False)),
        "features": _coerce_features(raw.get("features")),
        "drift_items": _coerce_drift(raw.get("drift_items")),
    }


def _salvage_truncated(text: str) -> dict[str, Any] | None:
    """从截断的 JSON 里把 ``features`` / ``drift_items`` 两个数组里已闭合的完整对象抠出来。

    特征 + 多条 drift 一大就可能被截断成半截 JSON（flash 把 reasoning_content 算进
    max_tokens），整段 json.loads 必败。括号匹配逐个抠完整 {...}，拼部分结果比整张丢掉好
    （同 entity_recall / study_cards 抢救）。两个数组任一抢到东西就算有效。
    """
    features = _salvage_array(text, '"features"')
    drift = _salvage_array(text, '"drift_items"')
    if features is None and drift is None:
        return None
    return _coerce(
        {
            "sample_too_small": False,
            "features": features or [],
            "drift_items": drift or [],
        }
    )


def _salvage_array(text: str, key: str) -> list[Any] | None:
    """从 ``text`` 里 ``key`` 指向的 JSON 数组里抠出已闭合的完整对象列表（截断抢救通用）。"""
    idx = text.find(key)
    if idx == -1:
        return None
    start = text.find("[", idx)
    if start == -1:
        return None
    raw_items: list[Any] = []
    i = start + 1
    n = len(text)
    while i < n:
        while i < n and text[i] not in "{]":  # 跳到下一个对象起点；遇 ] 收工
            i += 1
        if i >= n or text[i] == "]":
            break
        depth = 0
        in_str = False
        esc = False
        closed = False
        j = i
        while j < n:  # 括号匹配抠一个完整 {...}，跳过字符串内的括号
            ch = text[j]
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        closed = True
                        break
            j += 1
        if not closed:
            break  # 最后一个对象被截断 → 停
        try:
            raw_items.append(json.loads(text[i:j]))
        except json.JSONDecodeError:
            pass
        i = j
    return raw_items or None


def _parse_voice(text: str) -> dict[str, Any] | None:
    """解析模型输出的声口 JSON。正常失败 → 抢救截断的数组 → 仍不行返 None。"""
    raw = (text or "").strip()
    if not raw:
        return None
    candidate = _strip_code_fence(raw)
    obj: Any = None
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        sliced = _extract_first_json_object(candidate)
        if sliced is not None:
            try:
                obj = json.loads(sliced)
            except json.JSONDecodeError:
                obj = None
    result = _coerce(obj)
    if result is not None:
        return result
    salvaged = _salvage_truncated(candidate)
    if salvaged is not None:
        logger.warning(
            "character_voice: 主解析失败，从截断输出抢救到 %d 特征 / %d drift",
            len(salvaged["features"]),
            len(salvaged["drift_items"]),
        )
        return salvaged
    logger.warning("character_voice parse failed; raw head=%r", candidate[:200])
    return None


def _verify(result: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """核验两部分证据，处理方式不同（设计 §4）。

    - **features**：保留全部，每条 evidence 过 verify_citations 标 verified + 真章号纠偏
      （核不过的留着、前端标低置信）。无 evidence 的天然 verified=False。
    - **drift_items**：verify-filter——quote 核不过的整条丢（同 study_cards），章号纠偏。
    """
    evidence_map = {
        str(c["chunk_id"]): {"chapter": c.get("chapter", 0), "text": c.get("text", "")}
        for c in chunks
        if c.get("chunk_id")
    }

    for feat in result["features"]:
        cits = [{"snippet": feat["evidence"]}]
        verify_citations(cits, evidence_map)
        vc = cits[0]
        feat["verified"] = bool(vc.get("verified", False))
        feat["match_score"] = vc.get("match_score", 0.0)
        cid = vc.get("chunk_id")
        true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
        feat["chapter"] = true_ch if isinstance(true_ch, int) and true_ch > 0 else 0

    kept_drift: list[dict[str, Any]] = []
    for d in result["drift_items"]:
        # 带上 LLM 自报章号当多命中消歧弱先验（真章号在 verify 后用 chunk_id 覆盖）；
        # chapter 为 0 = 模型没报，不传，退回确定性首个。
        self_ch = d.get("chapter")
        cit: dict[str, Any] = {"snippet": d["quote"]}
        if isinstance(self_ch, int) and self_ch > 0:
            cit["chapter"] = self_ch
        cits = [cit]
        verify_citations(cits, evidence_map)
        vc = cits[0]
        if not vc.get("verified"):
            continue  # 挂不上原文的 drift 不报（agent 一面之词）
        cid = vc.get("chunk_id")
        true_ch = evidence_map.get(cid, {}).get("chapter") if cid else None
        if isinstance(true_ch, int) and true_ch > 0:
            d["chapter"] = true_ch  # 命中 chunk 的真章号纠偏，别让作家拿错章号翻稿
        d["verified"] = True
        d["match_score"] = vc.get("match_score", 0.0)
        kept_drift.append(d)
    kept_drift.sort(key=lambda x: x["chapter"])
    result["drift_items"] = kept_drift
    return result


def generate_character_voice(
    *,
    character: str,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_VOICE_MAX_TOKENS,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """归拢一个角色的对白、刻画语言特征、标 voice drift；失败返 ``None``。

    Args:
        character: 要分析的角色名（角色列表可复用人物图抽出的节点）。
        full_text: 整本书 cleaned 原文。
        chunks: 全书 chunk dict（含 ``chunk_id`` / ``chapter`` / ``text``），给 evidence
            做证据登记表 + 提供章号 ground truth。
        llm_client: duck-typed LLM client（同 AgentLoop / character_arc）。
        model: 模型名。
        max_tokens: 单次 LLM 调用 max_tokens（默认 8000）。
        session_id: 仅签名兼容——本任务关缓存（防坏响应被 poison）。

    Returns:
        ``{"sample_too_small": bool, "features": [{trait, evidence, verified, match_score,
        chapter}], "drift_items": [{chapter, quote, reason, verified, match_score}]}``——
        features 保留全部（含核不过的，标低置信）；drift_items verify-filter（核不过的丢）。
        任意失败 ``None``；角色名为空 ``None``。
    """
    _ = session_id  # 关缓存：本任务出结构化 JSON，坏响应不该被缓存 poison
    character = (character or "").strip()
    if not character:
        return None
    system = _SYSTEM_INSTRUCTION + _BOOK_DELIMITER + full_text
    messages = [
        {"role": "user", "content": f"请分析角色「{character}」的声口一致性。"}
    ]
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=messages,
                max_tokens=max_tokens,
                cache_enabled=False,
            )
        except Exception as exc:  # noqa: BLE001 — 包死，重试 / 返 None
            logger.warning(
                "character_voice LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        result = _parse_voice(llm_client.extract_final_text(response))
        if result is not None:
            return _verify(result, chunks)
        logger.warning(
            "character_voice parse failed (attempt %d/%d)", attempt, _MAX_ATTEMPTS
        )
    return None


__all__ = ["DEFAULT_VOICE_MAX_TOKENS", "generate_character_voice"]
