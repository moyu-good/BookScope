"""章脉人名归并(ADR-010 整合隐患修):把同一人的多种叫法收成一个 canonical。

**为什么有这个模块**:章脉的人物维是逐章抽的,每章用原文当下的称呼(玄德/刘备/先主),
没合并。关系图 / 叙事流从章脉派生时,同一个人按不同叫法碎成好几个节点(三国实测:刘备和
刘玄德两个点、孔明和诸葛亮两个点)。

老路想借 KG 的 aliases 合并(``_kg_name_map``),但 ``MinimalKGExtractor`` 是 map-reduce
逐 batch 抽的——别名只在 batch 内局部可见,跨 batch 从不合并,实测零 aliases,name_map 全是
自映自、合并空转。

这里换思路:章脉建好后,把它里头出现的**所有人名**收齐(present + relations 对 + char_states),
一次 LLM 调用判同人、出一张 别名→canonical 表,喂给 ``relationship_graph_from_spine`` /
``narrative_flow_from_spine`` 的 ``name_map``。输入正好是章脉自己用的那批名字,不存在 KG 知道
的名字跟章脉用的名字对不上的根因;一次带全清单的交叉上下文判断,比逐 batch 局部抽更稳。

**便宜 + 稳**:只发人名清单(不发原文),走 L2 ``invoke_client_cached`` 按清单缓存,同书命中
零成本。归并失败 / 解析不出 → 返空表,关系图照画(只是不合并),不 break。归并只在 LLM **有
把握**时合并,拿不准各自单独成节点——宁可漏并不可错并(把五虎将并成一个人比碎裂更糟)。
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_CANON_MAX_TOKENS = 8000
"""归并输出 ∝ 送进去的人名条数;只送高频前 ``DEFAULT_CANON_MAX_NAMES`` 个,几千 token 够用。"""

DEFAULT_CANON_MAX_NAMES = 80
"""一次只归并按出场频次排前多少个人名。

为什么要封顶:大书章脉抽出几百个露面的人(三国实测 717 个),整批丢给 LLM 判同人,
deepseek-flash 这类 reasoning 模型会把整个 max_tokens 预算烧在 reasoning 上、content 吐空
(finish_reason=length,见 memory reference_reasoning_model_token_budget)——归并直接 0 条。

而且没必要:关系图只显示按连接度排前 40 的主干(``top_n=40``),别名碎裂只在高频主要人物间
要紧(刘备/刘玄德、孔明/诸葛亮);几百个一次性小角色既不碎裂、也进不了主干。取 2× 显示量(80)
当候选,既盖住显示的 40 + 边界别名变体,又把任务收到 reasoning 不爆的小规模。排在 80 名之外的
长尾人名,LLM 不判,改走 ``_fold_in_longtail_aliases`` 的零成本规则兜底(见下)。"""

_LONGTAIL_ALIAS_MIN_LEN = 2
"""长尾别名兜底:只收**长度 ≥ 这个**的短名。

单字名(操/超/亮)歧义太大——"操"既是"曹操"的字、也可能撞别人;一个字当子串太容易误中,
保守起见单字一律不靠规则合并(要合也得 LLM 在 top-80 里看上下文判)。"""

_LONGTAIL_ALIAS_MAX_LEN = 3
"""长尾别名兜底:只收**长度 ≤ 这个**的短名。

要兜的是"裸字/号"这类碎裂(玄德 freq=6 没合进刘备),它们都短(2-3 字)。更长的名字基本是
独立全名,不该靠子串规则往别人身上并——长度封顶把误合面再收一道。"""

_CANON_INSTR = (
    "下面是一本书里出现的人物称呼清单(逐章抽出来的,同一个人可能有大名、字、号、小名、"
    "尊称、官称等好几种叫法,比如 刘备/玄德/刘玄德/先主 都是一个人)。\n"
    "请判断哪些称呼指的是同一个人,把它们归成一组,每组给一个最通行的本名当 canonical。\n"
    "规则:\n"
    "1. 只在你**有把握**是同一人时才合并;拿不准就让它单独成一组,别硬凑(错并比漏并更糟)。\n"
    "2. canonical 用清单里最常见、最正式的那个本名。\n"
    "3. 清单里每个称呼都要出现在某一组里,不漏不重。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"groups":[{"canonical":"本名","aliases":["称呼1","称呼2"]}]}'
)


def _name_frequencies(spine: list[dict[str, Any]]) -> Counter[str]:
    """数章脉里每个人名的出场频次——present 每章一次 + relations 每次入对一次 + char_states 一次。

    频次≈连接度,用来排"哪些是主要人物"。present/relations/char_states 任一非 list 都跳过(防脏数据)。
    """
    freq: Counter[str] = Counter()
    for rec in spine:
        if not isinstance(rec, dict):
            continue
        present = rec.get("present")
        if isinstance(present, list):
            for name in present:
                if isinstance(name, str) and name.strip():
                    freq[name.strip()] += 1
        relations = rec.get("relations")
        if isinstance(relations, list):
            for rel in relations:
                if not isinstance(rel, dict):
                    continue
                pair = rel.get("pair")
                if isinstance(pair, list) and len(pair) == 2:
                    for p in pair:
                        s = str(p).strip()
                        if s:
                            freq[s] += 1
        char_states = rec.get("char_states")
        if isinstance(char_states, list):
            for st in char_states:
                if isinstance(st, dict):
                    s = str(st.get("name", "")).strip()
                    if s:
                        freq[s] += 1
    return freq


def collect_spine_names(spine: list[dict[str, Any]]) -> list[str]:
    """把章脉里出现的所有人名收齐去重——present + relations 的对 + char_states 的 name。

    返回**排序**后的去重清单(给报告 / 全量统计用)。归并实际只送其中高频的前若干个,见
    ``build_spine_name_map``。
    """
    return sorted(_name_frequencies(spine))


def _top_names_by_frequency(spine: list[dict[str, Any]], limit: int) -> list[str]:
    """按出场频次取前 ``limit`` 个人名(同频按名字排,保证确定性 → L2 缓存 key 稳)。

    返回**排序**后的候选(送 LLM 前再排一次,顺序不影响判断、只为缓存命中稳)。
    """
    freq = _name_frequencies(spine)
    ranked = sorted(freq, key=lambda n: (-freq[n], n))[:limit]
    return sorted(ranked)


def _parse_groups(text: str, names: set[str]) -> dict[str, str]:
    """把 LLM 的 ``{"groups":[{canonical, aliases}]}`` 解析成 别名→canonical 表。

    只收 alias 在 ``names`` 里的(防 LLM 把没出现过的名字塞进来);canonical 不限,允许它给一个
    清单里没单独出现、但更通行的本名当节点标签。解析不出 → 返空表(等于不合并)。
    """
    raw = (text or "").strip()
    if not raw:
        return {}
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

    groups: list[Any]
    if isinstance(obj, dict) and isinstance(obj.get("groups"), list):
        groups = obj["groups"]
    else:
        salvaged = salvage_closed_objects(candidate, '"groups"')
        if not salvaged:
            return {}
        logger.warning("chapter_spine_canon: 主解析失败,从截断抢救到 %d 组", len(salvaged))
        groups = salvaged

    name_map: dict[str, str] = {}
    for grp in groups:
        if not isinstance(grp, dict):
            continue
        canonical = str(grp.get("canonical", "")).strip()
        if not canonical:
            continue
        aliases = grp.get("aliases")
        if not isinstance(aliases, list):
            continue
        for alias in aliases:
            a = str(alias).strip()
            if a and a in names:
                name_map[a] = canonical
    return name_map


def _fold_in_longtail_aliases(
    name_map: dict[str, str], all_names: list[str]
) -> dict[str, str]:
    """把 top-80 之外、LLM 没看过的**低频短名**用零成本规则归一到已确定的本名。

    **要修的病**(#13):"刘玄德"(高频、进了 LLM 候选)被合进"刘备",但裸"玄德"(freq=6、排
    80 名外)永远进不了候选 → 关系图里"玄德"碎成独立节点。任何书主角的低频别名都这么碎,不只
    demo。简单抬 ``DEFAULT_CANON_MAX_NAMES`` 会把 reasoning 模型的 token 烧爆(见该常量注释),
    所以改用**不调 LLM** 的子串规则兜底。

    **规则(保守,高置信才合,宁漏不错)**:
    一个还没归一的短名 ``t``(长度在 ``[_LONGTAIL_ALIAS_MIN_LEN, _LONGTAIL_ALIAS_MAX_LEN]``),
    若它是 LLM **已确定的某一组**里某个称呼(该组的 canonical 或别名都算)的**真子串**
    (``t in 称呼 and t != 称呼``),且**全局只有这一组**有称呼含它,就把 ``t`` 归到那组的
    canonical。命中多组(歧义)一律不合,各自留着。

    **为什么不爆 token**:纯字符串比对,0 次 LLM 调用。

    **为什么不错合**:
    1. 只比 LLM **已经判过、已合并**的称呼——锚是"刘玄德⊂里的玄德",不是凭空猜;
    2. 子串要求**严格包含且不等**,曹操和马腾不会因都姓"曹/马"而合(全名互不为子串);
    3. **歧义即弃**:``t`` 若被多组的称呼都含(如某短名同时是两个不同人称呼的一部分),不合;
    4. 单字名(长度 1)直接不收(``_LONGTAIL_ALIAS_MIN_LEN=2``)——"操"这种一字太容易误中;
    5. 只往 ``t`` **真子串**的称呼上并,不会把"曹操"并进"操"(方向固定:短名找含它的长称呼)。

    Args:
        name_map: LLM 出的 别名→canonical 表(可能空——LLM 失败时上游传 ``{}``)。
        all_names: 章脉里出现的**全部**人名(含长尾),来自 ``collect_spine_names``。

    Returns:
        在 ``name_map`` 基础上**补**了长尾别名的新表(不改原表)。补不出就原样返回。
    """
    # 已被 LLM 归一过的称呼集合:左边的别名 + 右边的 canonical 都算"已确定锚"。
    resolved = set(name_map) | set(name_map.values())
    if not resolved:
        return dict(name_map)

    # 每个 canonical 组的全部称呼:canonical 自己 + 所有映射到它的别名。
    group_appellations: dict[str, set[str]] = {}
    for alias, canonical in name_map.items():
        group_appellations.setdefault(canonical, set()).update({canonical, alias})

    out = dict(name_map)
    for t in all_names:
        t = t.strip()
        if not (_LONGTAIL_ALIAS_MIN_LEN <= len(t) <= _LONGTAIL_ALIAS_MAX_LEN):
            continue
        if t in resolved:
            continue  # 已是某组的称呼 / canonical,LLM 已处理,别动
        # 找所有"某称呼真包含 t"的组;只在唯一一组命中时才合(歧义即弃)。
        hit_canonicals = {
            canonical
            for canonical, appels in group_appellations.items()
            for appel in appels
            if t in appel and t != appel
        }
        if len(hit_canonicals) == 1:
            out[t] = next(iter(hit_canonicals))
    return out


def build_spine_name_map(
    *,
    spine: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_names: int = DEFAULT_CANON_MAX_NAMES,
    max_tokens: int = DEFAULT_CANON_MAX_TOKENS,
    cache_enabled: bool = True,
) -> dict[str, str]:
    """从章脉里**高频前 ``max_names`` 个**人名,一次 LLM 调用判同人,出 别名→canonical 表。

    喂给关系图/叙事流的 ``name_map``。只送高频候选(不是全量),既盖住关系图实际显示的主干、
    又把任务收到 reasoning 模型不爆 max_tokens 的小规模(见 ``DEFAULT_CANON_MAX_NAMES``)。
    只发人名清单(不发原文),走 L2 缓存按清单命中。0/1 个名字没什么可并的、直接返恒等表。
    LLM 调用 / 解析任一步出意外都返空表——关系图照画(``_canon`` 拿空表走原样),绝不 break。

    **LLM 判完再过一道长尾兜底**(``_fold_in_longtail_aliases``,#13):top-80 之外的低频短名
    (如裸"玄德" freq=6)进不了 LLM 候选,靠零成本子串规则归一到已确定的本名——不抬
    ``max_names``(防 token 爆)、保守只合高置信(防错合)。LLM 整个失败(空表)时长尾也无锚可
    依,兜底原样返空,关系图照画。
    """
    names = _top_names_by_frequency(spine, max_names)
    if len(names) <= 1:
        return {n: n for n in names}

    user_content = json.dumps({"names": names}, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_CANON_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 归并失败降级成不合并,不能 break 关系图
        logger.warning(
            "chapter_spine_canon: 归并调用抛 %s: %s;返空表(不合并)", type(exc).__name__, exc
        )
        return {}

    name_map = _parse_groups(text, set(names))
    # LLM 只看了高频前 max_names;长尾低频短名(玄德 freq=6)用零成本规则补归一(#13)。
    return _fold_in_longtail_aliases(name_map, collect_spine_names(spine))


__all__ = [
    "DEFAULT_CANON_MAX_NAMES",
    "DEFAULT_CANON_MAX_TOKENS",
    "build_spine_name_map",
    "collect_spine_names",
]
