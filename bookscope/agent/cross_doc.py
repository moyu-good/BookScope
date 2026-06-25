"""文件间层(1.6 红头文件杀手价值核心)——一摞公文文脉一次全局推理出文件之间的关系。

**它是什么**:书籍引擎是「一本书内分章」,没有「文件之间」这一层。公文场景天然多份一起看,
一摞同主题 / 同政策线的文件之间有依据 / 落实 / 废止 / 修改 / 上下级的关系——这层把每份文脉里
的「依据引用 / 机关 / 成文日期」抽出来,连成一张关系网。设计稿
`docs/design/WP-1.6-redhead-vertical-design.md` §1.3 定的就是这一层,§3.1 的依据链网络从它派生。

**怎么建(套现成的机器)**:走 `project_chapter_spine_turn` 反复验证的「脊 + 一次全局推理 +
锚回真实单元」范式,单元从「章」换成「文件」——正是 ``concept_evolution_from_spine`` /
``consistency_scan_from_spine`` 那台机器:

1. **从每份文脉收紧凑清单**(不发全文):每份的 字号 / 文种 / 机关 / 成文日期 + 每条款的
   事项 / 依据引用。
2. **一次 LLM 全局推理**(走 ``invoke_client_cached``)把这摞文件之间的关系全推出来。
3. **锚回真实单元**:from_doc / to_doc 必须对到这摞文件里真实存在的发文字号(锚不到丢);
   kind 必须落进封闭集 ``RELATION_KINDS``(落不进丢);chapter_anchor 锚到 A 文脉真实存在的
   条款序号(锚不到退空)。

**证据不进记录**(沿用 ADR-010 出路 B「章级锚 + 点开现取」,同关系图边):关系只钉到「A 文件
第几条」,证据后面前端点开按需取(取那句「根据 B……」的原文),抽取输出不翻倍。

**文件身份 = 发文字号优先,没字号退标题**:字号是公文身份证(机关代字 + 年份 + 序号),有就用
它对齐,最稳。可人大常委会通过的地方法规(广东 / 广州条例)只有公布令、不带「X发〔年〕号」——
这类没字号的文件用**标题**当 anchor id,否则整个进不了网络(实测依据链网 None 的根因之一)。
而且真实依据关系是**按标题引的**:广东条例正文「根据《优化营商环境条例》制定本条例」引的是
标题不是字号,所以引用解析表把字号 + 归一标题都映回 anchor,按标题引的依据也捞得出来。
机关名归一复用 ``build_spine_name_map``(「财政部」「财」「该部」归一份节点),只用在 docs 节点
标签的机关名上——文件本身靠 anchor 对齐,不靠机关名。

铁律:**只 import 现有模块的 helper,一行不改** doc_spine / chapter_spine 等;不碰端点 /
fixture / 前端。这一层只产出文件间关系记录 + 节点清单,三个跨文件视图(依据链网络 / 政策演变 /
上下级一致性)从它派生是后面的事。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.chapter_spine_canon import build_spine_name_map
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_CROSS_DOC_MAX_TOKENS = 16000
"""一次全局推理把一摞文件的关系全吐出来的 max_tokens。

deepseek-v4-flash 把 reasoning_content 算进 max_tokens(见
[[reference_reasoning_model_token_budget]])。关系条数 ∝ 文件对数,加 reasoning 头;
Phase 1 限 3-5 份文件,16000 够吐完;真撑爆靠 ``_parse_relations`` 截断抢救兜底。"""

# 文件间关系封闭集(设计稿 §1.3)。LLM 推出的 kind 必须落进这五类,落不进就丢这条关系——
# 不让模型自造一个关系类型(同 doc_spine 的文种 / 指令类型封闭集纪律)。
RELATION_KINDS: tuple[str, ...] = (
    "依据",    # A 引 B 当上位依据(「根据 B……」)——A 站在 B 之下
    "落实",    # A 是为落实 / 贯彻 B 而发(下位文件执行上位部署)
    "废止",    # A 明文废止 B(B 自 A 起失效)
    "修改",    # A 修改 / 补充 B 的部分条款(B 仍有效,被改过)
    "上下级",  # A、B 是同一政策线上的上下级行文关系(无更具体的依据 / 落实定性时的兜底)
)

# 头要素里这几个字段是文件间链的原料 / 节点画像。
# 锚定优先靠发文字号(机关代字 + 年份 + 序号,公文身份证);可地方法规(广东 / 广州条例)常
# **没有发文字号**——人大常委会通过的条例只有公布令、不带「X发〔年〕号」。这类文件用**标题**
# 当锚 id(广东条例 ≡《广东省优化营商环境条例》)。而且真实依据关系是**按标题引的**:广东条例
# 正文写「根据《优化营商环境条例》制定本条例」——引的是标题不是字号。只靠字号锚定,这种没字号
# 的地方法规整个进不了网络、按标题引的依据全漏(实测依据链网 None 的根因)。
_HEAD_ID_FIELD = "发文字号"
_HEAD_DOC_TYPE_FIELD = "文种"
_HEAD_ORG_FIELD = "发文机关"
_HEAD_DATE_FIELD = "成文日期"
_HEAD_TITLE_FIELD = "标题事由"

_INSTR = (
    "下面 docs 是一摞党政机关公文,每份给了一个 **id(文件标识)**——有发文字号的就是字号,"
    "没有字号的地方法规用它的标题——以及 文种、发文机关、成文日期、标题,还有这份文件每条款的 "
    "事项 和 依据引用(这条引了哪份上位文件的字号或标题)。\n"
    "请通读这一摞文件,把**文件之间**的关系全推出来——谁依据谁、谁落实谁、谁废止谁、谁修改谁、"
    "谁是谁的上下级。严格只依据给出的清单(尤其 依据引用),不臆测、不编造。\n"
    "**特别注意按标题引的依据**:有的文件正文写「根据《某某条例》制定本条例」「依据《某某意见》」"
    "——被引的《某某条例》如果就是这摞文件里某一份(看它的标题对得上),就是一条「依据」关系,"
    "别因为引的是标题不是字号就漏掉。\n"
    "每条关系:\n"
    "- from_doc:关系发起方的 **id**(必须是上面某份 docs 的 id——字号或标题,照抄那个 id)。\n"
    "- to_doc:关系指向方的 **id**(必须是上面某份 docs 的 id;指向清单外的文件就别列)。\n"
    "- kind:**只能填以下五个之一**,按关系实质判,落不进就别列这条:\n"
    "  - 依据:from 引 to 当上位依据(from 文件里有「根据 to……」「依据《to 的标题》」)。\n"
    "  - 落实:from 是为落实 / 贯彻 to 而发的下位文件。\n"
    "  - 废止:from 明文废止 to。\n"
    "  - 修改:from 修改 / 补充 to 的部分条款。\n"
    "  - 上下级:from、to 在同一政策线上是上下级行文,但没有上面更具体的定性时填这个。\n"
    "- chapter_anchor:这条关系来自 **from_doc 文件的第几条款**(整数条款序号;说不清留空 / 不填)。\n"
    "- note:一句话说清这是什么关系。\n"
    "**只列清单里坐实得了的关系,宁缺毋滥。from / to 必须都是清单里真实的 id,"
    "kind 必须落进那五类。**\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"relations":[{"from_doc":"","to_doc":"","kind":"依据","chapter_anchor":条款序号整数,"note":""}]}'
)

_USER_MSG = "请按上面的要求推出文件之间的关系。"


def _head_value(spine: dict[str, Any], field: str) -> str:
    """从一份文脉的 head 里取某个要素的 value(抽不到 / 没核到都返空串)。

    head 是 ``[{field, value, evidence, verified, match_score}]``,按 field 找那条取 value。
    """
    head = spine.get("head")
    if not isinstance(head, list):
        return ""
    for el in head:
        if isinstance(el, dict) and el.get("field") == field:
            return str(el.get("value", "")).strip()
    return ""


def _clause_numbers(spine: dict[str, Any]) -> set[int]:
    """一份文脉里真实存在的条款序号集——chapter_anchor 要锚到这里头(防 LLM 编条款号)。"""
    nums: set[int] = set()
    clauses = spine.get("clauses")
    if isinstance(clauses, list):
        for cl in clauses:
            if isinstance(cl, dict) and isinstance(cl.get("chapter"), int):
                nums.add(cl["chapter"])
    return nums


def _norm_title(s: str) -> str:
    """标题归一(给「按标题引」的匹配用):去书名号《》和首尾空白。

    正文引用写「根据《优化营商环境条例》」,标题事由抽出来可能是「优化营商环境条例」(不带书名号)
    也可能带——两边都去掉《》再比,才对得上。只做最轻的归一:不动正文字、不模糊匹配,避免错连
    (evidence-first:宁可漏连不可错连)。
    """
    return (s or "").strip().strip("《》").strip()


def _doc_anchor_id(spine: dict[str, Any]) -> tuple[str, str, str]:
    """一份文脉的锚 id + 字号 + 标题。

    返 ``(anchor_id, 字号, 标题事由)``:有字号就拿字号当 anchor_id(公文身份证,最稳);没字号
    (地方法规常见)退标题当 anchor_id。两者都没有 → anchor_id 空(这份进不了文件间网络)。
    """
    num = _head_value(spine, _HEAD_ID_FIELD)
    title = _head_value(spine, _HEAD_TITLE_FIELD)
    anchor = num or title
    return anchor, num, title


def _collect_inventory(
    doc_spines: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],     # 给 LLM 的紧凑清单(每份带 id = 字号或标题)
    dict[str, set[int]],      # anchor_id → 该文件真实存在的条款序号集(锚 chapter_anchor 用)
    list[dict[str, Any]],     # docs 节点清单(给前端画节点)
    set[str],                 # 全部真实 anchor_id
    dict[str, str],           # 引用串(字号 / 归一标题)→ anchor_id(把按标题/字号引的解析回 id)
]:
    """从一摞文脉收 紧凑清单 + anchor→条款序号集 + docs 节点 + 真实 anchor 集 + 引用解析表。

    锚 id 优先发文字号,没字号(地方法规常见)退标题——靠 ``_doc_anchor_id`` 判。两者都没有的
    文脉对不上、进不了文件间网络。同一 anchor 重复只留第一份。

    **引用解析表**(这次修的核心):把每份的字号 + 归一标题都映到它的 anchor_id。这样 LLM 或本地
    抽取拿到的 from/to 不管是字号还是「《标题》」,都能解析回真实 anchor——广东条例正文「根据
    《优化营商环境条例》」引的标题就能对到 722 条例那份。
    """
    digest: list[dict[str, Any]] = []
    clause_nums: dict[str, set[int]] = {}
    docs: list[dict[str, Any]] = []
    real_ids: set[str] = set()
    ref_to_id: dict[str, str] = {}

    for spine in doc_spines:
        if not isinstance(spine, dict):
            continue
        anchor, num, title = _doc_anchor_id(spine)
        if not anchor or anchor in real_ids:
            continue  # 没字号也没标题 / 重复:不进文件间网络
        real_ids.add(anchor)

        doc_type = _head_value(spine, _HEAD_DOC_TYPE_FIELD)
        org = _head_value(spine, _HEAD_ORG_FIELD)
        date = _head_value(spine, _HEAD_DATE_FIELD)
        clause_nums[anchor] = _clause_numbers(spine)

        # 引用解析表:字号、归一标题都指回这份的 anchor(按字号引、按标题引都能解析回来)。
        if num:
            ref_to_id.setdefault(num, anchor)
        nt = _norm_title(title)
        if nt:
            ref_to_id.setdefault(nt, anchor)

        # 紧凑清单:每份的身份 + 每条款的 事项 / 依据引用(只发链原料,不发全文)。
        clauses_brief: list[dict[str, Any]] = []
        clauses = spine.get("clauses")
        if isinstance(clauses, list):
            for cl in clauses:
                if not isinstance(cl, dict) or not isinstance(cl.get("chapter"), int):
                    continue
                matter = str(cl.get("matter", "")).strip()
                basis = str(cl.get("basis_ref", "")).strip()
                if not matter and not basis:
                    continue  # 这条既没事项又没引用,对推关系没用,省 token
                brief: dict[str, Any] = {"条款": cl["chapter"]}
                if matter:
                    brief["事项"] = matter
                if basis:
                    brief["依据引用"] = basis
                clauses_brief.append(brief)

        digest.append({
            "id": anchor,        # 字号或标题,LLM 拿它当 from/to
            "字号": num,         # 可能空(地方法规)
            "文种": doc_type,
            "发文机关": org,
            "成文日期": date,
            "标题": title,
            "条款": clauses_brief,
        })
        docs.append({
            "字号": anchor,      # 节点 id 沿用 anchor(前端 / 视图层按它对齐,字段名保持「字号」不动)
            "文种": doc_type,
            "机关": org,
            "成文日期": date,
            "标题": title,
        })

    return digest, clause_nums, docs, real_ids, ref_to_id


def _org_name_map(
    docs: list[dict[str, Any]],
    *,
    llm_client: Any,
    model: str,
    cache_enabled: bool,
) -> dict[str, str]:
    """机关名归一:复用 ``build_spine_name_map`` 把「财政部」「财」「该部」归一份。

    ``build_spine_name_map`` 吃的是「章脉」形态(逐条 ``{present: [人名]}``),这里造一份合成 mini
    章脉——每份文件的发文机关当一个「人名」塞进 ``present``——借同一台归并机器判同机关。只用在
    docs 节点标签的机关名上(文件本身靠字号对齐,不靠机关名,所以归并失败也不影响关系锚定)。
    机关名 ≤1 个没什么可并的,直接返恒等表省一次调用。
    """
    orgs = [str(d.get("机关", "")).strip() for d in docs]
    orgs = sorted({o for o in orgs if o})
    if len(orgs) <= 1:
        return {o: o for o in orgs}
    pseudo_spine = [{"chapter": i + 1, "present": [o]} for i, o in enumerate(orgs)]
    return build_spine_name_map(
        spine=pseudo_spine,
        llm_client=llm_client,
        model=model,
        cache_enabled=cache_enabled,
    )


def _parse_relations(text: str) -> list[dict[str, Any]] | None:
    """解析 ``{"relations":[...]}``;三层兜底(直解析 / 切首个对象 / 截断抢救)。

    空数组(这摞文件之间没关系)是合法结果返 ``[]``;彻底解析不出返 ``None``。
    同 ``concept_evolution._parse_stages`` 的结构,数组键换成 ``"relations"``。
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
    if isinstance(obj, dict) and isinstance(obj.get("relations"), list):
        return obj["relations"]
    salvaged = salvage_closed_objects(candidate, '"relations"')
    if salvaged:
        logger.warning(
            "cross_doc: 主解析失败,从截断抢救到 %d 条关系", len(salvaged)
        )
        return salvaged
    return None


def _resolve_ref(raw: str, real_ids: set[str], ref_to_id: dict[str, str]) -> str:
    """把一个 from/to 引用串解析回真实 anchor_id;解析不到返空串(丢这条,不编)。

    解析顺序:① 本身就是真实 anchor → 直接用;② 去书名号归一后命中引用表(字号 / 标题)→ 用表里
    的 anchor。命中不了就空——evidence-first,锚不到这摞里真实文件的引用一律不输出。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    if s in real_ids:
        return s
    nt = _norm_title(s)
    if nt in ref_to_id:
        return ref_to_id[nt]
    if s in ref_to_id:
        return ref_to_id[s]
    return ""


def _coerce_relation(
    item: Any,
    real_ids: set[str],
    clause_nums: dict[str, set[int]],
    ref_to_id: dict[str, str],
) -> dict[str, Any] | None:
    """把一条关系记录归一并锚回真实单元;锚不到 / 落不进封闭集 → 返 None(丢这条)。

    - from_doc / to_doc 经 ``_resolve_ref`` 解析回真实 anchor_id(字号或标题都认);解析不到丢
      (防 LLM 编引用 / 引清单外文件)。
    - from == to 丢(文件不跟自己有关系)。
    - kind 必须落进 ``RELATION_KINDS``(落不进丢,不自造关系类型)。
    - chapter_anchor 锚到 from_doc 文脉真实存在的条款序号;锚不到(越界 / 非整数 / 缺)退 None
      (这条关系仍立,只是说不清来自第几条;不靠猜填一个条款号)。
    """
    if not isinstance(item, dict):
        return None
    from_doc = _resolve_ref(str(item.get("from_doc", "")), real_ids, ref_to_id)
    to_doc = _resolve_ref(str(item.get("to_doc", "")), real_ids, ref_to_id)
    if not from_doc or not to_doc:
        return None  # 锚不到真实文件:丢(立身之本,不编不存在的引用)
    if from_doc == to_doc:
        return None
    kind = str(item.get("kind", "")).strip()
    if kind not in RELATION_KINDS:
        return None  # 落不进封闭集:丢(不自造关系类型)

    anchor = item.get("chapter_anchor")
    chapter_anchor: int | None = None
    if isinstance(anchor, int) and not isinstance(anchor, bool):
        if anchor in clause_nums.get(from_doc, set()):
            chapter_anchor = anchor  # 锚到 from_doc 真实条款序号才留

    return {
        "from_doc": from_doc,
        "to_doc": to_doc,
        "kind": kind,
        "chapter_anchor": chapter_anchor,
        "note": str(item.get("note", "")).strip(),
    }


def _local_basis_relations(
    doc_spines: list[dict[str, Any]],
    real_ids: set[str],
    ref_to_id: dict[str, str],
) -> list[dict[str, Any]]:
    """本地兜底:扫每份文脉条款的 ``basis_ref``,引到这摞里另一份文件就直接坐实一条「依据」关系。

    为什么要这道本地兜底:依据关系是公文最硬的一类——``basis_ref`` 是文脉建构时从条款正文抽出来
    的「根据《X》/依据《X》」,X 的字号 / 标题是**正文里真出现的字**,不是模型现编。只要 X 解析得
    回这摞里另一份文件,这条「依据」就坐实了,不该靠 LLM 全局推理碰运气(实测它会漏按标题引的)。
    这里不调 LLM、纯解析,把这种铁关系先捞出来;LLM 推出的关系再并进去(去重)。

    锚 from = 这份文件的 anchor,to = basis_ref 解析到的 anchor,chapter_anchor = 该条款序号
    (basis_ref 就来自这一条,锚得准)。解析不到 / 引自己 → 丢。
    """
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for spine in doc_spines:
        if not isinstance(spine, dict):
            continue
        anchor, _num, _title = _doc_anchor_id(spine)
        if anchor not in real_ids:
            continue
        clauses = spine.get("clauses")
        if not isinstance(clauses, list):
            continue
        for cl in clauses:
            if not isinstance(cl, dict):
                continue
            basis = str(cl.get("basis_ref", "")).strip()
            if not basis:
                continue
            to_id = _resolve_ref(basis, real_ids, ref_to_id)
            if not to_id or to_id == anchor:
                continue  # 引清单外文件 / 引自己:丢
            key = (anchor, to_id)
            if key in seen:
                continue
            seen.add(key)
            ch = cl.get("chapter")
            out.append({
                "from_doc": anchor,
                "to_doc": to_id,
                "kind": "依据",
                "chapter_anchor": ch if isinstance(ch, int) and not isinstance(ch, bool) else None,
                "note": f"正文据「{basis}」",
            })
    return out


def cross_doc_relations_from_spines(
    *,
    doc_spines: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_CROSS_DOC_MAX_TOKENS,
    cache_enabled: bool = True,
) -> dict[str, Any] | None:
    """一摞文脉一次全局推理出文件之间的关系 → ``{relations, docs}``。失败 / 没关系 → ``None``。

    套「脊 + 一次全局推理 + 锚回真实单元」范式(同 ``concept_evolution_from_spine``),单元从
    「章」换成「文件」、**文件身份 = 发文字号优先,没字号(地方法规)退标题**。

    关系来自两路并起来:
    - **本地兜底**(``_local_basis_relations``,纯解析不调 LLM):扫条款 ``basis_ref`` 里「根据
      《X》」引到这摞里另一份的,直接坐实「依据」关系——这是正文里真出现的字,最硬,先捞。
    - **LLM 全局推理**(一次调用):落实 / 废止 / 修改 / 上下级这些 basis_ref 兜不住的关系,以及
      本地没捞全的依据。两路按 (from,to,kind) 去重并起来,本地的留在前(先 append)。

    Args:
        doc_spines: 一摞文脉(每份 = ``build_doc_spine`` 的产出,含 ``head`` / ``clauses``)。
        llm_client: duck-typed LLM client(同 AgentLoop / 章脉)。
        model: 模型名。
        max_tokens: 一次全局推理的 max_tokens(默认 16000,Phase 1 限 3-5 份够用)。
        cache_enabled: 是否走 L2 缓存(默认开,同一卷宗重开零成本)。

    Returns:
        ``{
            "relations": [{from_doc, to_doc, kind, chapter_anchor, note}],
            "docs": [{字号, 文种, 机关, 成文日期, 标题}],
        }``——relations 是文件间关系记录(证据不进记录,沿 ADR-010 出路 B 点开现取),
        docs 给前端画节点。``字号`` 字段实为 anchor(字号或标题),视图层按它对齐。
        少于 2 份能锚的文件(凑不成「文件之间」)/ 两路都没锚到任何真实关系 → ``None``(端点返
        空态:依据链网络这类跨文件视图骨子里要 ≥2 份相关文件才有意义)。LLM 那一路调用失败 /
        解析不出**不再直接返 None**:只要本地兜底捞到了关系,照样出图(链不全塌)。
    """
    if not isinstance(doc_spines, list):
        return None
    digest, clause_nums, docs, real_ids, ref_to_id = _collect_inventory(doc_spines)
    if len(real_ids) < 2:
        return None  # 凑不成「文件之间」(跨文件视图要 ≥2 份能锚的文件)

    # 机关名归一(只动 docs 节点标签;文件靠 anchor 对齐,不受此影响)。
    org_map = _org_name_map(
        docs, llm_client=llm_client, model=model, cache_enabled=cache_enabled
    )
    if org_map:
        for d in docs:
            org = str(d.get("机关", "")).strip()
            if org:
                d["机关"] = org_map.get(org, org)

    relations: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(rel: dict[str, Any] | None) -> None:
        if rel is None:
            return
        # (from, to, kind) 去重——同一对同一类关系只留一条(留首条,通常 chapter_anchor 也带着)。
        key = (rel["from_doc"], rel["to_doc"], rel["kind"])
        if key in seen:
            return
        seen.add(key)
        relations.append(rel)

    # 第一路:本地 basis_ref 兜底(纯解析,最硬,先 append 占位)。
    for rel in _local_basis_relations(doc_spines, real_ids, ref_to_id):
        _add(rel)

    # 第二路:LLM 全局推理(失败 / 解析不出只 warning,不拖垮本地那路)。
    user_content = json.dumps({"docs": digest}, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
        parsed = _parse_relations(text)
    except Exception as exc:  # noqa: BLE001 — 调用失败:本地那路还在,不返 None
        logger.warning("cross_doc: 全局推理抛 %s: %s;只用本地兜底关系", type(exc).__name__, exc)
        parsed = None
    if parsed:
        for item in parsed:
            _add(_coerce_relation(item, real_ids, clause_nums, ref_to_id))

    if not relations:
        return None  # 两路都没锚到任何真实关系:端点返空态

    relations.sort(key=lambda r: (r["from_doc"], r["to_doc"], r["kind"]))
    return {"relations": relations, "docs": docs}


__all__ = [
    "DEFAULT_CROSS_DOC_MAX_TOKENS",
    "RELATION_KINDS",
    "cross_doc_relations_from_spines",
]
