"""立场判定（Toulmin）：给一个角色 + 一条可配的立场轴（pos ↔ neg），整本进 context
正反取证 + 综合倾向 + 争议度，每条证据挂原文。

设计缘起：旧 ⑧ 立场象限把"曹操是否尊汉"这种千年争议压成一个确定分（-4）+ 单句证据 ——
拍脑袋 + 假精确 + 单证据，犯"算法依托真实"机制层。改用 Toulmin：主张 + 正据 + 反据 +
把握度（争议度）。probe exp024 在三国真语料上验过四项 GO：
  1. 平衡取证：真争议的人（曹操）pro/con 两边都拿硬证据，不 cherry-pick；
  2. 争议度校准：曹操 dispute 明显高于清晰的（诸葛亮/董卓 = 0）；
  3. 不假平衡：清晰的人反方留空，不为显平衡硬编；
  4. 锚定：pro/con evidence 都锚原文。

轴可配（作者要求"每本书按分析换轴"）：pos_label / neg_label 由调用方给 —— 三国 =
尊汉扶主 / 篡逆自立；安史 = 忠唐 / 附燕；别的书换别的。此模块不认死某条轴。

复用 [[project_wholebook_feature_pattern]]：长上下文整本进 context + 结构化 JSON + 三守卫
（够 token / 关缓存防 poison / 重试 + salvage）。pro/con 每条 evidence 过 verify_citations
挂锚，核不过标 verified=false（前端标待核，不剔 —— 争议判断本就该两方并陈让人自己看）。

契约：成功返 ``{name, pos, neg, pro, con, net, dispute, dispute_reason}``；任意环节失败返 None。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached as _invoke_client
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_STANCE_MAX_TOKENS = 3200
"""正反两组证据（各带原文 + 一句说明）+ net + dispute + 理由，比单点判断长，给足头防截断/空。"""

DEFAULT_BATCH_STANCE_MAX_TOKENS = 4000
"""批量一次给一二十人各一个 net/dispute/依据，比单人长，给足头防截断（probe exp032）。"""

_MAX_ATTEMPTS = 2
_MAX_EVID = 8  # 单边证据条数上限，防跑飞


def _build_system(full_text: str, pos: str, neg: str) -> str:
    instruction = (
        f"你是严谨的人物立场判定助手。判定指定人物在「{pos} ↔ {neg}」这条轴上的立场。\n"
        "铁律：\n"
        f"1. 正反两方证据都要从原文里找：偏「{pos}」的证据(pro) 与 偏「{neg}」的证据(con)，"
        "分开列。每条 evidence 必须是原文逐字片段（原样摘录）。\n"
        "2. 哪一方原文里确实找不到，就列空数组 []，绝不为了显得平衡而硬编、绝不编原文没有的话。\n"
        f"3. net = 综合倾向整数（-5 偏{neg} .. 0 中立 .. +5 偏{pos}）。\n"
        "4. dispute = 争议度整数(0-5)：当且仅当正反两方都有硬证据、真两难时才高；一边倒就低。"
    )
    return build_longctx_system(full_text, instruction)


def _parse(raw: str) -> dict | None:
    obj = _extract_first_json_object(_strip_code_fence(raw or ""))
    if obj is None:
        return None
    try:
        parsed = json.loads(obj)
        return parsed if isinstance(parsed, dict) else None
    except Exception:  # noqa: BLE001
        return None


def _clean_side(items: Any) -> list[dict]:
    out: list[dict] = []
    for e in items or []:
        if isinstance(e, dict) and str(e.get("原文", "")).strip():
            out.append({"原文": str(e["原文"]), "说明": str(e.get("说明", ""))})
        if len(out) >= _MAX_EVID:
            break
    return out


def generate_character_stance(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    character: str,
    pos_label: str,
    neg_label: str,
    max_tokens: int = DEFAULT_STANCE_MAX_TOKENS,
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """整本进 context，给 ``character`` 在 ``pos_label ↔ neg_label`` 轴上正反取证；失败返 None。

    ``session_id`` 仅签名兼容——本任务关缓存（出结构化 JSON，坏响应不该被缓存 poison）。
    """
    _ = session_id
    system = _build_system(full_text, pos_label, neg_label)
    user = (
        f"判定人物「{character}」。严格输出 JSON（不要别的话、不要 markdown 围栏）：\n"
        '{\n  "pro": [{"原文": "原文逐字片段", "说明": "为何偏' + pos_label + '"}],\n'
        '  "con": [{"原文": "原文逐字片段", "说明": "为何偏' + neg_label + '"}],\n'
        '  "net": 综合倾向整数-5到5,\n  "dispute": 争议度整数0到5,\n'
        '  "dispute_reason": "为何是这个争议度（一句）"\n}\n'
        "pro / con 各列原文真有的；哪方没有就空数组。每条 evidence 能在原文逐字找到。"
    )
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            response = _invoke_client(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=[{"role": "user", "content": user}],
                max_tokens=max_tokens,
                cache_enabled=False,
            )
        except Exception as exc:  # noqa: BLE001 — 包死，重试 / 返 None
            logger.warning(
                "character_stance LLM call raised %s: %s (attempt %d)",
                type(exc).__name__, exc, attempt,
            )
            continue
        parsed = _parse(llm_client.extract_final_text(response))
        if parsed is None or parsed.get("net") is None:
            logger.warning("character_stance parse/net 空 (attempt %d/%d)", attempt, _MAX_ATTEMPTS)
            continue

        pro = _clean_side(parsed.get("pro"))
        con = _clean_side(parsed.get("con"))
        # pro/con 每条 evidence 过原文核验，挂 verified
        evmap = build_evidence_map(chunks)
        cits: list[dict] = []
        for side, arr in (("pro", pro), ("con", con)):
            for i, e in enumerate(arr):
                cits.append({"snippet": e["原文"], "chapter": None, "_s": side, "_i": i})
        verify_citations(cits, evmap)
        for c in cits:
            (pro if c["_s"] == "pro" else con)[c["_i"]]["verified"] = c.get("match_type") != "none"

        net = int(parsed.get("net", 0) or 0)
        dispute = int(parsed.get("dispute", 0) or 0)
        return {
            "name": character,
            "pos": pos_label,
            "neg": neg_label,
            "pro": pro,
            "con": con,
            "net": max(-5, min(5, net)),
            "dispute": max(0, min(5, dispute)),
            "dispute_reason": str(parsed.get("dispute_reason", "")),
        }
    return None


def _parse_batch(raw: str) -> list | None:
    """批量输出是 JSON 数组：先直接 loads（数组 / ``{"people": [...]}``），再兜底切首个 ``[...]``。

    ``extract_first_json_object`` 抠的是 ``{...}`` 对象，抠不了顶层数组，所以这里单开一个
    数组专用解析（照 probe exp032 的 ``_parse`` 那套，已在三国真语料上验过）。
    """
    txt = _strip_code_fence(raw or "")
    try:
        obj = json.loads(txt)
    except Exception:  # noqa: BLE001
        obj = None
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict) and isinstance(obj.get("people"), list):
        return obj["people"]
    i, j = txt.find("["), txt.rfind("]")
    if 0 <= i < j:
        try:
            arr = json.loads(txt[i : j + 1])
            return arr if isinstance(arr, list) else None
        except Exception:  # noqa: BLE001
            return None
    return None


def batch_stance_positions(
    *,
    characters: list[str],
    pos_label: str,
    neg_label: str,
    full_text: str,
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_BATCH_STANCE_MAX_TOKENS,
) -> list[dict[str, Any]] | None:
    """一次把多个 ``characters`` 同时定位到「``pos_label`` ↔ ``neg_label``」轴上；判不出返 None。

    立场格局主视图靠这个：批量一次给每人一个 ``{name, net, dispute, brief}``，不是一个个点
    （那是懒加载的毛病）。probe exp032 在三国真语料上验过——批量 net 跟单人 Toulmin net
    对得上（|Δ|≤2、方向不反），但批量对争议判得**浅**，所以这里只做**粗定位**：真争议要靠
    点开某人跑 :func:`generate_character_stance` 的单人 Toulmin 才显（evidence-first 机制层，
    别把批量 dispute 当权威）。

    与单人 Toulmin 的两点不同：

    - **不取证**：批量只给 net/dispute/一句依据，不拿 pro/con 原文（那太长、一次判一二十人塞
      不下也判不深）——取证是点开单人时的事。
    - **cache_enabled=True**：同一本书 + 同一批人 + 同一轴，答案稳定，命中省 token（同
      :func:`suggest_stance_axis`）；单人 Toulmin 关缓存是因为要每条证据现核，批量没这需求。

    轴由调用方按书给（不认死某条轴）。任意环节失败（调用抛错 / 解析不出数组 / 一个有效项都没）
    返 None，让前端不画象限、优雅退回按需点人。
    """
    names = [str(c).strip() for c in characters if str(c).strip()]
    if not names:
        return None
    instruction = (
        f"判定下面列出的每一个人物在「{pos_label} ↔ {neg_label}」这条轴上的立场，一次性全给。\n"
        "铁律：\n"
        f"1. 只据原文判，别臆测。身份本身不代表立场（比如某一方的臣属不一定就偏{pos_label}，"
        f"权臣不一定就偏{neg_label}），看原文里的行为。\n"
        f"2. net = 综合倾向整数（-5 偏{neg_label} .. 0 中立 .. +5 偏{pos_label}）。\n"
        "3. dispute = 争议度整数（0-5）：正反两方原文都有硬证据、真两难时才高；一边倒就低。\n"
        "4. brief = 一句话依据，据原文，别编。"
    )
    system = build_longctx_system(full_text, instruction)
    names_line = "、".join(names)
    user = (
        f"给这些人物一次性全部定位：{names_line}。\n"
        "严格只输出 JSON 数组（不要别的话、不要 markdown 围栏），每人一项：\n"
        '[{"name": "人名", "net": 整数-5到5, "dispute": 整数0到5, "brief": "一句依据"}]'
    )
    try:
        response = _invoke_client(
            llm_client,
            model=model,
            system=system,
            tools=[],
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            cache_enabled=True,
        )
    except Exception as exc:  # noqa: BLE001 — 包死，返 None
        logger.warning(
            "batch_stance_positions LLM call raised %s: %s", type(exc).__name__, exc
        )
        return None
    arr = _parse_batch(llm_client.extract_final_text(response))
    if not isinstance(arr, list):
        logger.warning("batch_stance_positions 解析不出 JSON 数组")
        return None

    requested = set(names)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in arr:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        # 只收请求过的人（不画没问过的名字，防模型顺口带出的臆造项污染格局）；去重
        if not name or name not in requested or name in seen:
            continue
        raw_net = item.get("net")
        if raw_net is None:  # 没给倾向就不臆造位置，跳过这一项
            continue
        try:
            net = int(raw_net)
        except (TypeError, ValueError):
            continue
        try:
            dispute = int(item.get("dispute", 0) or 0)
        except (TypeError, ValueError):
            dispute = 0
        out.append(
            {
                "name": name,
                "net": max(-5, min(5, net)),
                "dispute": max(0, min(5, dispute)),
                "brief": str(item.get("brief", "")),
            }
        )
        seen.add(name)
    return out or None


def suggest_stance_axis(
    *,
    sample_text: str,
    llm_client: Any,
    model: str,
    max_tokens: int = 1000,
) -> dict[str, str] | None:
    """据书的节选建议一对立场轴标签（正端 ↔ 负端，各 ≤8 字）；判不出返 None。

    立场象限的轴不该写死成三国的「尊汉扶主 / 篡逆自立」——每本书围绕的对立不同（安史 =
    忠唐 / 附燕，别的书别的）。这里拿书的节选（书名 + 正文前若干字）让 LLM 判本书围绕的核心
    立场 / 阵营对立，给一对默认标签当前端起点，用户仍可改。

    命根子（evidence-first）：书里没有明显立场对立的（工具书 / 诗集 / 纯理论），返 None、
    不硬造——prompt 明写"判不出就返空"。任意环节失败（调用抛错 / 解析不出 / pos 或 neg 空）
    都返 None，让前端退回用户自己填。缓存开着——同一本书节选反复问答案稳定，命中省 token。

    Returns:
        ``{"pos": "...", "neg": "..."}``（各非空）；判不出 / 失败返 None。
    """
    system = (
        "你是文本立场分析助手。给你一本书的开头节选，判断这本书围绕的核心立场 / 阵营对立"
        "是什么，用一对简短对立标签概括（各不超过 8 个字），例如：\n"
        "  尊汉扶主 ↔ 篡逆自立（三国）、忠唐 ↔ 附燕（安史之乱）、革命 ↔ 保皇。\n"
        "只有这本书确实围绕某条立场 / 阵营对立展开时才给标签；工具书 / 诗集 / 纯理论 / 说明文"
        "这类没有明显立场对立的，判不出就返空，绝不硬造。\n\n"
        f"【书的节选】\n{sample_text}"
    )
    user = (
        "严格只输出 JSON（不要别的话、不要 markdown 围栏）：\n"
        '{"pos": "正端标签", "neg": "负端标签"}\n'
        "两个标签各不超过 8 字、互为对立。判不出这本书的核心立场对立，就输出 "
        '{"pos": "", "neg": ""}。'
    )
    try:
        response = _invoke_client(
            llm_client,
            model=model,
            system=system,
            tools=[],
            messages=[{"role": "user", "content": user}],
            max_tokens=max_tokens,
            cache_enabled=True,
        )
    except Exception as exc:  # noqa: BLE001 — 包死，返 None
        logger.warning(
            "suggest_stance_axis LLM call raised %s: %s", type(exc).__name__, exc
        )
        return None
    parsed = _parse(llm_client.extract_final_text(response))
    if parsed is None:
        return None
    pos = str(parsed.get("pos", "")).strip()
    neg = str(parsed.get("neg", "")).strip()
    if not pos or not neg:
        return None
    return {"pos": pos, "neg": neg}
