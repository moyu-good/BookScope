"""支线编织 = 章脉派生(轻 LLM)。ADR-010 出路 B 的一个视图。

**为什么有这个模块**:交汇天生**跨段**——支线 A 在前段推进、支线 B 在后段推进,两条在某章
相遇就是一次交汇。老实现 ``generate_subplot_weave_exhaustive`` 是 map-reduce 逐段跑的,每段
只看得见自己那几章,跨段的交汇根本配不上——支线 A 的活跃章在段 1、支线 B 的活跃章在段 5,
它们在第 60 章交汇,但没有哪一段同时看见这两条线,于是这个交汇系统性漏报。支线本身逐段抽
还凑合(``_merge_weave_segments`` 按名并活跃章拼得回整条线),交汇是 map-reduce 的死角。

做法:从章脉收**全书逐章梗概**(每章 events / 在场人物 / 主支线 / 关系)——一份紧凑的全书
清单 + **一次 LLM 调用**让模型一口气梳理支线、并在全书视野里找跨章交汇。一次看全书既不像
map-reduce 跨段瞎、也不像整本喂全文大书截断——跨段配对就该这么做(同伏笔回收
``foreshadow_from_spine``)。

**输出形态对齐老实现**:``{"subplots":[{name, active_chapters:[int], evidence}],
"intersections":[{subplots:[a,b], chapter, evidence}]}``,FE(SubplotWeave.tsx)照旧读。交汇这里
出**单条 evidence**(老 map-reduce 版出 a_evidence/b_evidence 双端,本派生版按出路 B 钉章号、
证据取章脉那章已核验的 evidence,FE 两个字段都回退到 evidence 也能画)。

**便宜 + 稳**:只发逐章梗概(不发原文),走 L2 缓存按清单命中,同书零成本。解析不出 / 抽不出
支线 → 返 None,端点照走(不 break)。支线 / 交汇都锚到章脉里**真有的章**(防 LLM 编章号),
交汇两条支线必须都在那一章活跃;evidence 取章脉那章已核验过的 evidence(章级锚,出路 B)。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.chapter_spine_evidence import (
    chapter_text_map as _chapter_text_map,
)
from bookscope.agent.chapter_spine_evidence import split_sentences
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_WEAVE_MAX_TOKENS = 24000
"""支线 + 逐章活跃 + 跨章交汇一大就长,加 reasoning 头,给足防截断。

deepseek-v4-flash 是 reasoning 模型,reasoning_content 算进 max_tokens(见
[[reference_reasoning_model_token_budget]])。给小了 reasoning 吃光预算、content 全空
(finish=length)。24000 覆盖三国(120 回)+ 余量;更大的书超了靠 ``_parse_weave`` 截断抢救兜底。
同 ``chapter_spine_foreshadow.DEFAULT_MATCH_MAX_TOKENS``。"""

_MAX_EVENTS_PER_CH = 3  # 每章梗概取前几条事件,够给模型认出支线又不撑爆 input
_MAX_PRESENT_PER_CH = 6  # 每章在场人物取前几个(认出"谁在场→哪条线在场")

_WEAVE_INSTR = (
    "下面 timeline 是这本书的逐章梗概(每章:发生的主要事件、在场人物、是否推进主线)。\n"
    "请基于**整本书的全局视野**做两件事:\n"
    "一、梳理这本书的**情节支线**——有哪几条情节支线、每条在哪些章活跃。\n"
    "  一条支线 = 一组围绕共同目标/冲突/人物群、有起有止地推进的事件序列(主线是贯穿全书\n"
    "  最粗的那条,支线时起时落)。只把真正成一条线的事件序列算作支线,书里零散互不相干的\n"
    "  次要提及不要硬凑成支线——宁可少切几条。\n"
    "二、找出**跨章交汇**——两条支线在某一章相遇(同场景碰头、互相因果影响、人物跨线流动)。\n"
    "  **关键**:支线 A 可能在前面几章活跃、支线 B 在后面几章活跃,它们在中间某一章交汇——\n"
    "  你看的是全书梗概,这种隔得远的交汇正是要你抓出来的。\n"
    "  只在两条支线**真的交汇**时才报;两条各自独立推进、人物不重叠的,不要凑数编交汇。\n"
    "  交汇章必须是这两条支线**都活跃**的那一章。\n"
    "只依据 timeline 给出的事件,不臆测、不编造书里没有的支线或交汇。\n"
    "严格输出 JSON(别的话别说、别加 markdown 代码围栏):\n"
    '{"subplots":[{"name":"支线名(一句话概括这条线)",'
    '"active_chapters":[这条支线活跃的章号整数,从小到大]}],'
    '"intersections":[{"subplots":["支线A名","支线B名"],"chapter":交汇章号整数}]}\n'
    "subplots 要列出全书**所有真正成型**的支线(含主线)——书里有多少条成型的线就列多少,\n"
    "几十回的大书往往十几二十条:别为了凑数把零散提及硬编成支线,也别为了精简漏掉真支线\n"
    "(漏掉成型的线比多列一条更糟)。intersections 里引用的支线名要和 subplots 里的 name 一致。"
)


def _collect_timeline(
    spine: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], set[int], dict[int, str], dict[int, str]]:
    """从章脉收逐章梗概(给模型认支线/交汇的线索)+ 全部章集 + 章级证据 + 章级事件文本。

    每章给:事件前几条、在场人物前几个、是否主线——够让模型在全书视野里认出"哪条线在这章
    推进、两条线在哪章碰头"。不发原文(走 L2 缓存按清单命中)。

    返回 (timeline, 全部章集, 章号→证据, 章号→事件文本)。末一项给"按线名现捞"拼 query 用:
    线名是模型概括的抽象短语,光拿它去原文按字面捞命中弱;加上这章的事件文本一起当检索词,
    更容易落到真讲这条线的那句。
    """
    timeline: list[dict[str, Any]] = []
    all_chs: set[int] = set()
    evidence: dict[int, str] = {}
    events_text: dict[int, str] = {}
    for rec in spine:
        if not isinstance(rec, dict):
            continue
        ch = rec.get("chapter")
        if not isinstance(ch, int):
            continue
        all_chs.add(ch)
        evidence[ch] = str(rec.get("evidence", "")).strip()
        events = rec.get("events")
        evs = (
            [
                str(e.get("event", e) if isinstance(e, dict) else e).strip()
                for e in events[:_MAX_EVENTS_PER_CH]
            ]
            if isinstance(events, list)
            else []
        )
        events_text[ch] = " ".join(e for e in evs if e)
        present = rec.get("present")
        ppl = (
            [str(p).strip() for p in present[:_MAX_PRESENT_PER_CH] if str(p).strip()]
            if isinstance(present, list)
            else []
        )
        entry: dict[str, Any] = {"章": ch, "事": [e for e in evs if e]}
        if ppl:
            entry["在场"] = ppl
        if rec.get("mainline") is False:  # 默认主线,只标支线章(省 token)
            entry["支线章"] = True
        timeline.append(entry)
    return timeline, all_chs, evidence, events_text


def _bigrams(text: str) -> set[str]:
    """拆 2-gram 当检索词(中文没空格切词,用 bigram 衡量某句像不像在讲这个)。"""
    e = re.sub(r"\s+", "", text or "")
    return {e[i : i + 2] for i in range(len(e) - 1)}


def _thread_evidence(
    chapter_text: str, thread_name: str, chapter_events: str
) -> str:
    """从一章原文里现捞最支撑"这条支线在这章的动静"的那句;线名不沾的句子不要、返空。

    线名是模型概括的抽象短语(如"赤壁备战线"),双层打分(同
    ``chapter_spine_relationship._pair_evidence`` 的思路):

    - 主键 = **线名 bigram 命中数**,必须 > 0——一句话连线名半个字都不沾,不可能是这条线的证据,
      宁可空着标灰(防"光靠 events 命中把无关句拉进来"的张冠李戴)。
    - 次键 = 这章 events 的 bigram 重叠数——线名沾上的句子里,再用"这章发生了什么"把最贴的那句
      顶上来。
    - 末键 = 短句优先(更聚焦)。

    捞不到(没有任何句子沾线名)→ 空串(没原文支撑不输出,FE 标灰)。
    """
    if not chapter_text or not thread_name:
        return ""
    name_bg = _bigrams(thread_name)
    if not name_bg:
        return ""
    event_bg = _bigrams(chapter_events)
    best: tuple[tuple[int, int, int], str] | None = None
    for s in split_sentences(chapter_text):
        name_hit = sum(1 for bg in name_bg if bg in s)
        if name_hit == 0:
            continue  # 连线名半个字都不沾 → 不是这条线的证据
        event_hit = sum(1 for bg in event_bg if bg in s)
        score = (name_hit, event_hit, -len(s))
        if best is None or score > best[0]:
            best = (score, s)
    return best[1] if best else ""


def _coerce_subplots(raw: Any, all_chs: set[int]) -> list[dict[str, Any]]:
    """归一支线:name 齐全 + 至少一个真章号才留;按 name 去重(先到先得)。"""
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name or name in seen:
            continue
        active: list[int] = []
        active_seen: set[int] = set()
        for ch in item.get("active_chapters") or []:
            if isinstance(ch, bool):  # bool 是 int 子类,单独挡掉
                continue
            if isinstance(ch, int) and ch in all_chs and ch not in active_seen:
                active_seen.add(ch)
                active.append(ch)
        if not active:  # 锚不到任何真章的支线丢掉(防 LLM 编)
            continue
        active.sort()
        seen.add(name)
        out.append({"name": name, "active_chapters": active})
    return out


def _coerce_intersections(
    raw: Any,
    subplots: list[dict[str, Any]],
    all_chs: set[int],
) -> list[dict[str, Any]]:
    """归一交汇:两条支线名都在 subplots 里、章号是真章、两条线都在那章活跃才留。

    "两条线都在交汇章活跃"是这张图最容易编的部分的守卫——既防 LLM 编不存在的交汇,也保证
    FE 画得出(交汇节点要落在两条泳道都亮着的那一列)。按 (支线对, 章) 去重。
    """
    if not isinstance(raw, list):
        return []
    active_by_name: dict[str, set[int]] = {
        sp["name"]: set(sp["active_chapters"]) for sp in subplots
    }
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        sp_pair = item.get("subplots")
        if not isinstance(sp_pair, list) or len(sp_pair) < 2:
            continue
        a = str(sp_pair[0]).strip()
        b = str(sp_pair[1]).strip()
        if not a or not b or a == b:
            continue
        if a not in active_by_name or b not in active_by_name:
            continue  # 引用了不存在的支线名 → 丢
        ch = item.get("chapter")
        if isinstance(ch, bool) or not isinstance(ch, int) or ch not in all_chs:
            continue
        # 双线守卫:交汇章里两条线都得活跃,否则这交汇站不住
        if ch not in active_by_name[a] or ch not in active_by_name[b]:
            continue
        key = (tuple(sorted((a, b))), ch)
        if key in seen:
            continue
        seen.add(key)
        out.append({"subplots": [a, b], "chapter": ch})
    out.sort(key=lambda x: x["chapter"])
    return out


def _parse_weave(text: str, all_chs: set[int]) -> dict[str, Any] | None:
    """把 LLM 的 ``{"subplots":[...],"intersections":[...]}`` 解析 + 归一;三层兜底。

    直解析 / 切首个对象 / 截断抢救(优先抠已闭合的 subplots,交汇截断就当空)。没抽出任何支线
    返 None。
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

    if isinstance(obj, dict):
        subplots = _coerce_subplots(obj.get("subplots"), all_chs)
        if subplots:
            intersections = _coerce_intersections(obj.get("intersections"), subplots, all_chs)
            return {"subplots": subplots, "intersections": intersections}

    # 截断抢救:flash reasoning 吃 token,交汇排在 subplots 后,截断多半丢后半段交汇——
    # 优先抠已闭合的 subplots,至少把泳道画出来(同 subplot_weave._salvage_truncated)。
    salv_sp = _coerce_subplots(salvage_closed_objects(candidate, '"subplots"') or [], all_chs)
    if salv_sp:
        salv_it = _coerce_intersections(
            salvage_closed_objects(candidate, '"intersections"') or [], salv_sp, all_chs
        )
        logger.warning(
            "chapter_spine_subplot: 主解析失败,从截断抢救到 %d 条支线、%d 处交汇",
            len(salv_sp),
            len(salv_it),
        )
        return {"subplots": salv_sp, "intersections": salv_it}
    return None


def subplot_weave_from_spine(
    *,
    spine: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    chunks: list[dict[str, Any]] | None = None,
    max_tokens: int = DEFAULT_WEAVE_MAX_TOKENS,
    cache_enabled: bool = True,
) -> dict[str, Any] | None:
    """章脉全书梗概一次 LLM 全局推理 → 支线 + 跨章交汇。任意环节空/抛 → None。

    形态对齐 ``generate_subplot_weave_exhaustive``:
    ``{"subplots":[{name, active_chapters:[int], evidence}],
    "intersections":[{subplots:[a,b], chapter, evidence}]}``。

    支线 / 交汇都锚到章脉里**真有的章**(过滤掉编出来的章号);交汇两条线必须都在交汇章活跃
    (双线守卫)。

    **证据怎么来**(病二·证据张冠李戴的修法):

    - 传了 ``chunks``(全书原文)→ 按"线名"在锚定章原文里**现捞**最支撑这条线的那句
      (``_thread_evidence``)。支线证据取它最早活跃章里真讲这条线的那句;交汇的 a_evidence /
      b_evidence 按**两条线各自的线名**分别现捞——两条线的证据本该不同,旧实现两个都回退到同
      一条章代表句,是额外的病,这里治掉。捞不到 → 空串、verified=False(FE 标灰,不硬塞无关
      原文)。
    - 没传 ``chunks``(向后兼容,端点未接线时)→ 保持旧行为:两端 evidence 取章脉那章的章代表句,
      a_evidence / b_evidence 都回退到同一条。
    """
    timeline, all_chs, evidence, events_text = _collect_timeline(spine)
    if not all_chs:
        return None
    chapter_text = _chapter_text_map(chunks) if chunks else {}

    user_content = json.dumps({"timeline": timeline}, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_WEAVE_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 抽取失败降级返 None,不 break 端点
        logger.warning(
            "chapter_spine_subplot: 调用抛 %s: %s;返 None", type(exc).__name__, exc
        )
        return None

    weave = _parse_weave(text, all_chs)
    if weave is None:
        return None

    # 支线 evidence:传了 chunks 就按线名在最早活跃章原文现捞,没传退回章脉那章的章代表句。
    for sp in weave["subplots"]:
        anchor = sp["active_chapters"][0]
        if chunks:
            ev = _thread_evidence(
                chapter_text.get(anchor, ""), sp["name"], events_text.get(anchor, "")
            )
        else:
            ev = evidence.get(anchor, "")
        sp["evidence"] = ev
        sp["verified"] = bool(ev)
        sp["match_score"] = 1.0 if ev else 0.0

    # 交汇:传了 chunks 就在交汇章原文里按 A 线名、B 线名**各自**现捞(两条线证据本该不同);
    # 没传则两端都退回交汇那章的章代表句(旧行为,a/b 同句)。
    for it in weave["intersections"]:
        ch = it["chapter"]
        if chunks:
            ch_text = chapter_text.get(ch, "")
            ch_events = events_text.get(ch, "")
            a_ev = _thread_evidence(ch_text, it["subplots"][0], ch_events)
            b_ev = _thread_evidence(ch_text, it["subplots"][1], ch_events)
            it["evidence"] = a_ev or b_ev
        else:
            a_ev = b_ev = evidence.get(ch, "")
            it["evidence"] = a_ev
        it["a_evidence"] = a_ev
        it["b_evidence"] = b_ev
        it["a_verified"] = bool(a_ev)
        it["b_verified"] = bool(b_ev)
        it["a_match_score"] = 1.0 if a_ev else 0.0
        it["b_match_score"] = 1.0 if b_ev else 0.0

    return weave


__all__ = ["DEFAULT_WEAVE_MAX_TOKENS", "subplot_weave_from_spine"]
