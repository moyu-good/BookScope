"""穷尽化(1.4)的可复用件:分段 + 并发 + 按章 map-reduce。

重型逐章功能(多维叙事曲线 / 叙事流……每章带 evidence、多字段)单次调用扛不住整本——
叫它覆盖 120 章会被 max_tokens 截断到几章。改 map-reduce:**按字符预算分段 → 每段单独
逐章抽(段内章少、远不到帽)→ 按章 concat 去重**。章是 disjoint 的,所以"合并"就是拼接 +
去重,比关系图的 edge 合并还简单。

紧凑逐章(节奏曲线:每章只一句)不用这个——拆帽 + 加 max_tokens 单次就够。判据见
memory project_exhaustive_extraction_pattern。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent._internal.loop_shared import read_openai_finish_reason

logger = logging.getLogger(__name__)

DEFAULT_CHAR_BUDGET = 40000
# 每段最多多少章（ADR-010 D-7）。穷尽化每段输出 ∝ 段里章数 × 每章带证据的结构,真正撑爆
# max_tokens 的是输出不是输入。短章书(网文 2-3 千字/章)一个 4 万字段塞十六七章 → 输出顶爆
# 8000 截断(probe 实测全维 3/4 爆、情节维 17 章已吃到 5759)。所以段大小要同时受"字数"和
# "章数"两个闸约束,谁先到谁断段。长章书(明朝 ~5.6k 字/章 → 一段才 7 章)字数先到、章闸不咬,
# 行为不变。chunks 不带 chapter 时章闸不触发(向后兼容)。12 章留足 8000 余量。
DEFAULT_MAX_CHAPTERS = 12
DEFAULT_WORKERS = 6
ENV_WORKERS = "BOOKSCOPE_EXHAUSTIVE_WORKERS"

# 截断兜底拆段递归深度上限（1.5.2 丢章修复）。某段截断、连一条都没抢救到时，把这段按章
# 对半拆小重抽——6 章塞不下就拆 3、再塞不下拆 1（单章总塞得下，是下限）。每拆一层章数至少
# 减半，6→3→2→1 四层足够；这个硬上限只是防御性兜底，防极端 chunk 把递归拖深。降到单章仍
# 截断 = 这一章本身塞不下（极罕见），保留抢救到的（可能空）不再拆。
_SPLIT_MAX_DEPTH = 4


def segment_chunks(
    chunks: list[dict[str, Any]],
    char_budget: int = DEFAULT_CHAR_BUDGET,
    max_chapters: int | None = DEFAULT_MAX_CHAPTERS,
) -> list[list[dict[str, Any]]]:
    """按字符预算 + 章数上限把全书 chunks 切成若干段（保序，不打散单个 chunk）。

    断段条件:当前段非空,且 **要么** 加上这个 chunk 超字符预算,**要么**(ADR-010 D-7)
    这个 chunk 引入一个新章、而当前段已攒满 ``max_chapters`` 个不同章——谁先到谁断。
    ``max_chapters=None`` 退回纯字符预算。chunk 不带 ``chapter`` 时章闸不触发(向后兼容)。
    """
    segments: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    cur_len = 0
    cur_chapters: set[Any] = set()
    for c in chunks:
        t = str(c.get("text", ""))
        ch = c.get("chapter")
        over_chars = bool(cur) and cur_len + len(t) > char_budget
        new_chapter = ch is not None and ch not in cur_chapters
        over_chapters = (
            bool(cur)
            and max_chapters is not None
            and new_chapter
            and len(cur_chapters) >= max_chapters
        )
        if over_chars or over_chapters:
            segments.append(cur)
            cur = []
            cur_len = 0
            cur_chapters = set()
        cur.append(c)
        cur_len += len(t)
        if ch is not None:
            cur_chapters.add(ch)
    if cur:
        segments.append(cur)
    return segments


def _split_segment_by_chapter(
    seg: list[dict[str, Any]],
) -> list[list[dict[str, Any]]] | None:
    """把一段按 ``chapter`` 对半拆成两个更小子段（截断兜底用，1.5.2 丢章修复）。

    按 chunk 的真 ``chapter`` 把段切两半：前一半章一个子段、后一半章一个子段（同章的多个
    chunk 不拆散，整章跟着走）。返回两个子段；**拆不动时返 ``None``**——段不带 chapter（向后
    兼容路，没法按章拆）或整段只剩一个章（单章已是下限，再拆没意义）。每拆一层章数至少减半，
    保证递归收敛。
    """
    chapters: list[Any] = []
    for c in seg:
        ch = c.get("chapter")
        if ch is not None and ch not in chapters:
            chapters.append(ch)
    if len(chapters) < 2:  # 不带章号 或 只有单章 → 拆不动
        return None
    mid = len(chapters) // 2
    first_half = set(chapters[:mid])
    first: list[dict[str, Any]] = []
    second: list[dict[str, Any]] = []
    for c in seg:
        (first if c.get("chapter") in first_half else second).append(c)
    if not first or not second:  # 兜底：万一全落一边，当拆不动
        return None
    return [first, second]


def resolve_workers(explicit: int | None, default: int = DEFAULT_WORKERS) -> int:
    """逐段并发数：构造参数 > 环境变量 > 默认；< 1 兜底 1（串行）。"""
    if explicit is not None:
        return max(1, explicit)
    raw = os.environ.get(ENV_WORKERS)
    if not raw or not raw.strip():
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def run_segments(
    *,
    chunks: list[dict[str, Any]],
    instruction: str,
    user_msg: str,
    parse_fn: Callable[[str], list[dict[str, Any]] | None],
    llm_client: Any,
    model: str,
    max_tokens: int,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    max_chapters: int | None = DEFAULT_MAX_CHAPTERS,
    max_workers: int | None = None,
    cache_enabled: bool = True,
    continue_fn: Callable[
        [list[dict[str, Any]], list[dict[str, Any]]], list[dict[str, Any]]
    ]
    | None = None,
) -> list[list[dict[str, Any]]]:
    """map 引擎：按字符预算分段 → 并发逐段抽 → 返回**每段**解析出的条目列表（不合并）。

    每段用 ``build_longctx_system(段原文, instruction)`` 跑一次（段内条目数远小于功能自带的
    ~40 帽，所以不必改 instruction）。``parse_fn`` 把单段输出解析成 ``[{...}]``。单段失败 /
    解析不出 → 该段返 ``[]``，不拖垮整体。reduce（合并）由调用方按各功能的 key 决定，所以这里
    只返回 ``list[每段条目列表]``，保段序（段按章序排，所以"先出现"= 章靠前的段）。

    ``max_chapters`` 透传给 ``segment_chunks`` 当章闸（1.5.2 方案 B）：默认沿用全局
    ``DEFAULT_MAX_CHAPTERS=12``，章脉 char/plot 重维传更小的专用值让单段输出不爆 max_tokens。

    ``continue_fn``（1.5.2 方案 C）：某段 **finish_reason=length 截断且只抢救回部分章** 时，
    用 ``continue_fn(seg, partial)`` 再发一次"只抽差掉的章"的调用，返回补抽到的条目，append 进
    该段结果——把"截断悄悄丢章"变"截断补抽回来"。``None`` 则不补抽（截断时记 warning 后照旧返
    抢救到的部分）。截断判定靠 ``finish_reason``（1.5.2 方案 A），不再盲抢救。

    **截断且一条都没抢救到**（1.5.2 丢章修复）：旧逻辑直接跳过整段、约 6 章全丢。改成把这段
    按章对半拆小递归重抽（``_split_segment_by_chapter`` → ``run_segment(sub, depth+1)``），段太
    大塞不下就拆成更小窗口分别抽，逐章是兜底下限——保证每章都被覆盖、不丢。拆有 ``_SPLIT_MAX_DEPTH``
    深度上限防无限递归；不带 chapter 字段的段拆不动，仍按旧行为放弃（返空）。这只在"截断且抢救
    为 0"分支触发，不动 ``max_chapters`` 的默认值。

    缓存默认开：同段同书重看直接命中（map-reduce 下坏段只跳过、不一坏全挂，开缓存安全）。
    """
    segments = segment_chunks(chunks, char_budget, max_chapters)
    if not segments:
        return []

    def run_segment(seg: list[dict[str, Any]], depth: int = 0) -> list[dict[str, Any]]:
        seg_text = "".join(str(c.get("text", "")) for c in seg)
        system = build_longctx_system(seg_text, instruction)
        try:
            resp = invoke_client_cached(
                llm_client,
                model=model,
                system=system,
                tools=[],
                messages=[{"role": "user", "content": user_msg}],
                max_tokens=max_tokens,
                cache_enabled=cache_enabled,
            )
        except Exception as exc:  # noqa: BLE001 — 单段失败跳过
            logger.warning("exhaustive 段调用抛 %s: %s；跳过该段", type(exc).__name__, exc)
            return []
        # 方案 A：先读 finish_reason，把"截没截"变成可观测量，再解析。
        truncated = read_openai_finish_reason(resp) == "length"
        try:
            parsed = parse_fn(llm_client.extract_final_text(resp)) or []
        except Exception as exc:  # noqa: BLE001
            logger.warning("exhaustive 段解析抛 %s；跳过该段", type(exc).__name__)
            return []
        if not truncated:
            return parsed
        # finish_reason=length：这段被输出长度截断了（不是"模型真没抽到"）。
        if not parsed:
            # 截断且一条都没抢救到——旧逻辑直接跳过整段（约 6 章全丢，正是 1.5.2 的丢章
            # bug）。改成把这段按章对半拆小重抽：段太大塞不下就拆成更小窗口分别抽，逐章
            # 是兜底下限（单章总塞得下）。密集段多花几次调用，换"每章都被覆盖、不丢"。
            return _split_and_retry(seg, depth)
        logger.warning(
            "exhaustive 段被 max_tokens 截断，抢救到 %d 条%s",
            len(parsed),
            "，续抽补完" if continue_fn is not None else "（未配续抽，丢掉差掉的章）",
        )
        if continue_fn is None:
            return parsed
        # 方案 C：对差掉的章续抽补完，append 进本段结果。续抽自身也可能再截断，但
        # continue_fn 内部按"还差哪些章"递减，最终收敛；这里只负责 append。
        try:
            extra = continue_fn(seg, parsed) or []
        except Exception as exc:  # noqa: BLE001 — 续抽失败不拖垮主结果
            logger.warning("exhaustive 段续抽抛 %s；保留已抢救的部分", type(exc).__name__)
            return parsed
        if extra:
            parsed = [*parsed, *extra]
        return parsed

    def _split_and_retry(
        seg: list[dict[str, Any]], depth: int
    ) -> list[dict[str, Any]]:
        """截断且抢救为 0 的兜底：按章把这段对半拆小，对每个子段递归重抽，再拼起来。

        拆分按 chunk 的 ``chapter`` 走（不在章内切），保证每个子段都是完整的章——逐章抽
        不会把一章劈两半。子段章数严格递减（取前一半章），降到单章是下限（单章总塞得下）。
        ``depth`` 防御性硬上限 ``_SPLIT_MAX_DEPTH``；段不带 chapter（向后兼容路）或只剩
        单章却仍截断 → 没法再拆，记 warning 后放弃该段（返空）。
        """
        sub_segments = _split_segment_by_chapter(seg)
        if depth >= _SPLIT_MAX_DEPTH or sub_segments is None or len(sub_segments) < 2:
            logger.warning(
                "exhaustive 段被 max_tokens 截断且抢救为 0，已无法再拆小（深度 %d / 子段 %d）；"
                "放弃该段",
                depth,
                0 if sub_segments is None else len(sub_segments),
            )
            return []
        logger.warning(
            "exhaustive 段被 max_tokens 截断且抢救为 0，按章拆成 %d 个更小子段重抽（深度 %d→%d）",
            len(sub_segments),
            depth,
            depth + 1,
        )
        out: list[dict[str, Any]] = []
        for sub in sub_segments:
            out.extend(run_segment(sub, depth + 1))
        return out

    workers = resolve_workers(max_workers)
    if workers <= 1 or len(segments) <= 1:
        return [run_segment(s) for s in segments]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(run_segment, segments))


def merge_by_chapter(outs: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """reduce（逐章型）：跨段按 ``chapter`` concat 去重（保先出现）→ 升序。

    章是 disjoint 的（每段一段连续章），合并就是拼接 + 按章去重。用于 character_flow /
    narrative_curve 这类"每章一条"的逐章功能。
    """
    seen: set[int] = set()
    merged: list[dict[str, Any]] = []
    for lst in outs:
        for item in lst:
            ch = item.get("chapter")
            if not isinstance(ch, int) or ch in seen:
                continue
            seen.add(ch)
            merged.append(item)
    merged.sort(key=lambda c: c["chapter"])
    return merged


def merge_by_key(
    outs: list[list[dict[str, Any]]], *, key_fn: Callable[[dict[str, Any]], Any]
) -> list[dict[str, Any]]:
    """reduce（列表型）：跨段把条目 concat，按 ``key_fn(item)`` 去重（保先出现）。

    用于 timeline / foreshadow / argument 这类"全书一批条目"的列表功能——同一条目可能在
    相邻段都被抽到（如跨段的事件、伏笔），按身份 key 去重。``key_fn`` 返回 ``None`` 的条目
    丢弃。``order`` 之类的序号字段由调用方在合并后重排（段内序号跨段会重复）。
    """
    seen: set[Any] = set()
    merged: list[dict[str, Any]] = []
    for lst in outs:
        for item in lst:
            try:
                k = key_fn(item)
            except Exception:  # noqa: BLE001 — key 取不出就当无法去重，丢
                continue
            if k is None or k in seen:
                continue
            seen.add(k)
            merged.append(item)
    return merged


def _point_sig(p: dict[str, Any]) -> tuple:
    """子点整条签名(全字段)——给"同 key 可多条"的字段去重用,只去完全相同的重条。"""
    return tuple(sorted((kk, str(vv)) for kk, vv in p.items()))


def merge_keyed_points(
    outs: list[list[dict[str, Any]]],
    *,
    key_fn: Callable[[dict[str, Any]], Any],
    point_fields: list[str],
    point_key: str = "chapter",
    multi_per_key_fields: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    """reduce（带子点型）：按 ``key_fn`` 合并条目，每个条目内的子点列表跨段并集。

    用于 character_arc（key=角色名，子点=points）/ relationship_timeline（key=无向对，
    子点=points + turning_points）这类"每个实体一串逐章子点"的功能。合并规则：

    - 标量字段（relation 等）：保先出现段的值（段序见 ``run_segments``：``ThreadPoolExecutor.map``
      按输入序返回，故段序==chunks 列表序；只有当 chunks 本身按章升序时"先=靠前章"才成立）。
    - ``point_fields`` 里每个字段：跨段 concat 去重 + 按 ``point_key`` 升序。去重方式分两种：
      默认按 ``point_key``（每章至多一条，如 points 的逐章强度）；列在 ``multi_per_key_fields``
      里的字段改按**整条签名**去重（同章可多条，如 turning_points 同一章可有多个不同转折，
      只去完全重复的）。

    ``key_fn`` 返回 ``None`` 的条目丢弃。
    """
    order: list[Any] = []
    bucket: dict[Any, dict[str, Any]] = {}
    for lst in outs:
        for item in lst:
            try:
                k = key_fn(item)
            except Exception:  # noqa: BLE001
                continue
            if k is None:
                continue
            if k not in bucket:
                merged_item = {kk: vv for kk, vv in item.items() if kk not in point_fields}
                for f in point_fields:
                    merged_item[f] = []
                bucket[k] = merged_item
                order.append(k)
            tgt = bucket[k]
            for f in point_fields:
                src = item.get(f)
                if not isinstance(src, list):
                    continue
                full = f in multi_per_key_fields
                seen_pts: set[Any] = {
                    (_point_sig(p) if full else p.get(point_key))
                    for p in tgt[f]
                    if isinstance(p, dict)
                }
                for p in src:
                    if not isinstance(p, dict):
                        continue
                    dk = _point_sig(p) if full else p.get(point_key)
                    if dk in seen_pts:
                        continue
                    seen_pts.add(dk)
                    tgt[f].append(p)
    out: list[dict[str, Any]] = []
    for k in order:
        item = bucket[k]
        for f in point_fields:
            item[f].sort(
                key=lambda p: p.get(point_key)
                if isinstance(p.get(point_key), int)
                else 0
            )
        out.append(item)
    return out


def mapreduce_per_chapter(
    *,
    chunks: list[dict[str, Any]],
    instruction: str,
    user_msg: str,
    parse_fn: Callable[[str], list[dict[str, Any]] | None],
    llm_client: Any,
    model: str,
    max_tokens: int,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    max_chapters: int | None = DEFAULT_MAX_CHAPTERS,
    max_workers: int | None = None,
    cache_enabled: bool = True,
    correct_fn: Callable[[list[dict[str, Any]], list[dict[str, Any]]], None] | None = None,
    continue_fn: Callable[
        [list[dict[str, Any]], list[dict[str, Any]]], list[dict[str, Any]]
    ]
    | None = None,
    sweep_missing_chapters: bool = False,
) -> list[dict[str, Any]]:
    """按章 map-reduce 便捷壳：``run_segments`` → (逐段章号纠偏) → ``merge_by_chapter``。

    用于 character_flow / narrative_curve 这类"每章一条"的逐章功能。

    **``correct_fn`` 必须在合并前逐段跑（不是合并后一次性）**：模型读到的是正文里的章标题，
    多卷书每卷标题从「第一章」重数（如明朝那些事儿:全局第 86 章正文标题写「第十一章」），模型
    照标题自报 11 → 跟前段真第 11 章撞号。若按模型自报章号先 merge 去重，后段整章会被当重复
    丢掉（明朝实测 158 章只剩 30）。所以这里在 merge **之前**逐段把每段结果的章号纠偏成命中
    chunk 的真章号（``correct_fn(seg, chunks)`` 原地改），再按真章号去重。``correct_fn=None``
    则不纠偏（调用方自行处理）。

    ``max_chapters`` / ``continue_fn`` 透传给 ``run_segments``（1.5.2 方案 B/C）：默认沿用全局
    章闸 12、不续抽，调用方（章脉）按需传更小章闸 + 续抽回调。

    ``sweep_missing_chapters``（1.5.2 兜底不变量）：合并完后拿"喂进来的章"和"抽出来的章"一比，
    缺哪章就**单章重抽哪章**（``max_chapters=1``，单章总塞得下）。截断的恢复路有好几条（抢救为 0
    拆小、抢救部分续抽……）任一条没补全都会悄悄漏章；这条兜底不管漏在哪条路，最后统一按"每个
    喂入章都必须出现"这个不变量补齐，是最稳的那道闸。只在调用方显式开启 + 有 ``correct_fn``（章号
    可信）时生效；单章重抽后仍缺（极罕见，单章自身仍爆 token）记 warning、不再静默。
    """
    outs = run_segments(
        chunks=chunks,
        instruction=instruction,
        user_msg=user_msg,
        parse_fn=parse_fn,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_chapters=max_chapters,
        max_workers=max_workers,
        cache_enabled=cache_enabled,
        continue_fn=continue_fn,
    )
    if correct_fn is not None:
        for seg in outs:
            correct_fn(seg, chunks)
    merged = merge_by_chapter(outs)
    if not (sweep_missing_chapters and correct_fn is not None):
        return merged
    # 兜底不变量:喂进来的章必须都在输出里。缺的单章重抽——堵住所有截断丢章模式。
    expected = sorted(
        {c["chapter"] for c in chunks if isinstance(c.get("chapter"), int) and c["chapter"] >= 1}
    )
    have = {m["chapter"] for m in merged if isinstance(m.get("chapter"), int)}
    missing = [ch for ch in expected if ch not in have]
    if not missing:
        return merged
    logger.warning(
        "exhaustive 兜底不变量:合并后仍缺 %d 章,单章重抽 %s",
        len(missing),
        missing[:20],
    )
    miss_set = set(missing)
    miss_chunks = [c for c in chunks if c.get("chapter") in miss_set]
    sweep_outs = run_segments(
        chunks=miss_chunks,
        instruction=instruction,
        user_msg=user_msg,
        parse_fn=parse_fn,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_chapters=1,  # 每章单独成段,单章总塞得下
        max_workers=max_workers,
        cache_enabled=cache_enabled,
        continue_fn=continue_fn,
    )
    for seg in sweep_outs:
        correct_fn(seg, chunks)
    for m in merge_by_chapter(sweep_outs):
        ch = m.get("chapter")
        if ch not in have:
            merged.append(m)
            have.add(ch)
    merged.sort(key=lambda c: c["chapter"])
    still = [ch for ch in missing if ch not in have]
    if still:
        logger.warning(
            "exhaustive 兜底后仍缺 %d 章(单章仍爆 token/抽空):%s", len(still), still[:20]
        )
    return merged


__all__ = [
    "segment_chunks",
    "resolve_workers",
    "run_segments",
    "merge_by_chapter",
    "merge_by_key",
    "merge_keyed_points",
    "mapreduce_per_chapter",
    "DEFAULT_CHAR_BUDGET",
]
