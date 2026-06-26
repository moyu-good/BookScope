"""从文脉 / 文件间层派生三个跨文件视图(1.6 红头文件 Phase 1)——同 ADR-010 出路 B。

设计稿 `docs/design/WP-1.6-redhead-vertical-design.md` 第三部分定的三个跨文件杀手视图,各占一
个独立维度(`feedback_viz_distinct_identity`,别像 1.5.1 那样撞脸):

- **依据链关联网(空间维)** ``dependency_graph_from_cross_doc``——谁连谁。纯聚合、0 次 LLM,
  从文件间层(``cross_doc.cross_doc_relations_from_spines`` 的产出)直接整成星图:节点 = 文件 /
  机关、边 = 依据 / 落实 / 废止 / 修改 / 上下级。照 ``relationship_graph_from_spine`` 的聚合骨架,
  但单元从「人物对」换成「文件→文件有向边」。映射前端 ``CharacterGraph`` / ``starSky``。
- **政策演变时间线(时间维)** ``policy_evolution_from_spines``——怎么变。照搬
  ``chapter_spine_concept.concept_evolution_from_spine`` 整套:从各文脉收紧凑清单 → 一次 LLM 按
  **成文日期序**排演变阶段、每阶段标「相对上一份改了什么」→ 锚回真实文件。映射前端
  ``ConceptEvolution``。
- **上下级一致性核查(冲突维)** ``level_consistency_from_spines``——哪里对不上。照搬
  ``chapter_spine_consistency.consistency_scan_from_spine`` 整套:按机关层级收清单 → 一次 LLM 找
  「上位说 X、下位说 X'」对照条、标 走样 / 加码 / 漏落实 / 一致 → 锚回两份文件 + 各自条款。双向守卫
  照搬 + 换公文版「不算走样的情形」;两端证据任一空就丢(cry wolf 代价大,读者可能拿去办事 / 申诉)。

**证据为根**:阶段 / 冲突 / 边锚不到真实文件 + 条款的丢。证据不进上层记录——点开现取(同 ADR-010
出路 B):依据链网络的边只钉「from 文件第几条」,前端点开按需取那句「根据……」;政策演变 / 上下级
一致性两个 LLM 视图的 snippet 取**那条款文脉里已核验过的 evidence**(文脉建构时每条款 evidence
已过 ``verify_citations``),锚不到该条款 / 该条款没留证据就丢这阶段 / 这条冲突。

**题材自适应(§5.3)**:没有上下级关系的一摞(全平级 / 单文件)→ ``level_consistency_from_spines``
返 None,不硬造。

铁律:**只 import 现有模块的 helper,一行不改** doc_spine / cross_doc / chapter_spine 系列 /
端点 / fixture / 前端。这一层只产出三个视图的契约,接端点 / 前端是后面的事。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.citation_check import normalize_text, verify_citations
from bookscope.agent.redhead_codebook import codebook_block
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

# ── 公用:从文脉 head / clauses 取值的小工具(同 cross_doc 的取值口径)──────────────

_HEAD_ID_FIELD = "发文字号"
_HEAD_DOC_TYPE_FIELD = "文种"
_HEAD_ORG_FIELD = "发文机关"
_HEAD_DATE_FIELD = "成文日期"
_HEAD_TITLE_FIELD = "标题事由"


def _head_value(spine: dict[str, Any], field: str) -> str:
    """从一份文脉的 head 里取某要素的 value(抽不到 / 没核到都返空串)。口径同 cross_doc。"""
    head = spine.get("head")
    if not isinstance(head, list):
        return ""
    for el in head:
        if isinstance(el, dict) and el.get("field") == field:
            return str(el.get("value", "")).strip()
    return ""


def _doc_anchor(spine: dict[str, Any]) -> str:
    """一份文脉的 anchor id:发文字号优先,没字号(地方法规)退标题。口径同 cross_doc。

    政策演变 / 上下级一致性两个视图也得跟 cross_doc 一样认没字号的地方法规——只认字号,广东 /
    广州条例整个进不来,演变断档、上下级落差也凑不出(实测两视图 None 的根因之一)。
    """
    return _head_value(spine, _HEAD_ID_FIELD) or _head_value(spine, _HEAD_TITLE_FIELD)


def _norm_title(s: str) -> str:
    """标题归一(给引用匹配用):去书名号《》和首尾空白。口径同 cross_doc。"""
    return (s or "").strip().strip("《》").strip()


def _build_ref_map(doc_spines: list[dict[str, Any]]) -> dict[str, str]:
    """造 引用串(字号 / 归一标题)→ anchor 表:模型给的 doc/upper/lower 不管填字号还是标题都解析得回。

    某份靠字号当 anchor(722),但模型也可能用它的标题来指——这表把字号 + 归一标题都映回 anchor,
    两种叫法都认。同 cross_doc 的引用解析表,只是这边用在 policy/level 两个视图。
    """
    ref: dict[str, str] = {}
    for spine in doc_spines:
        if not isinstance(spine, dict):
            continue
        anchor = _doc_anchor(spine)
        if not anchor:
            continue
        num = _head_value(spine, _HEAD_ID_FIELD)
        title = _norm_title(_head_value(spine, _HEAD_TITLE_FIELD))
        if num:
            ref.setdefault(num, anchor)
        if title:
            ref.setdefault(title, anchor)
        ref.setdefault(anchor, anchor)
    return ref


def _resolve_doc_ref(raw: str, real_nums: set[str], ref_map: dict[str, str]) -> str:
    """把模型给的文件标识解析回真实 anchor;解析不到返空串(丢这条,不编)。口径同 cross_doc。"""
    s = (raw or "").strip()
    if not s:
        return ""
    if s in real_nums:
        return s
    nt = _norm_title(s)
    if nt in ref_map:
        return ref_map[nt]
    if s in ref_map:
        return ref_map[s]
    return ""


def _clause_evidence_map(spine: dict[str, Any]) -> dict[int, str]:
    """一份文脉里 条款序号 → 该条款已核验的 evidence(原文片段)。

    文脉建构时每条款 evidence 已过 ``verify_citations``,这里只取那句已核过的原文当 snippet
    (政策演变 / 上下级一致性的「点开现取」在这一层落地——不另搜原文,取文脉那条已核的证据)。
    """
    out: dict[int, str] = {}
    clauses = spine.get("clauses")
    if isinstance(clauses, list):
        for cl in clauses:
            if isinstance(cl, dict) and isinstance(cl.get("chapter"), int):
                out[cl["chapter"]] = str(cl.get("evidence", "")).strip()
    return out


def _any_clause_evidence(ev_map: dict[int, str]) -> str:
    """整份文脉里任挑一句已核证据当兜底(没指定条款锚时,文件级 snippet 用)。"""
    for snip in ev_map.values():
        if snip:
            return snip
    return ""


def _bigrams(text: str) -> list[str]:
    """概括过的文本拆 2-gram(中文没空格切词);同概念演进 / 一致性扫描的检索词拆法。"""
    e = re.sub(r"\s+", "", text or "")
    return list({e[i : i + 2] for i in range(len(e) - 1)})


# ════════════════════════════════════════════════════════════════════════════
# 视图一:依据链关联网(空间维)——纯聚合,0 次 LLM
# ════════════════════════════════════════════════════════════════════════════


def dependency_graph_from_cross_doc(
    cross_doc_result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """依据链关联网视图:把文件间层 ``{relations, docs}`` 整成星图 ``{nodes, edges}``。

    **纯聚合、0 次 LLM**(关系 / 节点都已在 ``cross_doc_relations_from_spines`` 里推好、锚好),
    照 ``relationship_graph_from_spine`` 的聚合骨架,但:
    - 节点 = 文件(字号)+ 机关(docs 给的),不是人物。文件节点带 文种 / 机关 / 成文日期画像;
      机关节点单列(同一机关多文件时,机关是枢纽节点)。``kind="文件" | "机关"`` 让前端分色。
    - 边 = 关系记录,**有向**(依据 / 落实有上下游,比人物关系强方向性):``from_doc → to_doc``,
      带 ``kind``(关系类型)、``chapter_anchor``(来源条款,可空)、``note``。不带 upfront evidence
      (点开现取,同关系图边章级锚)。

    输出契约(接前端 CharacterGraph / starSky,节点换文件 / 机关、边换依据链):
    ``{
        "nodes": [{"id": 字号或机关名, "kind": "文件"|"机关", "label", "文种", "机关", "成文日期"}],
        "edges": [{"source": from字号, "target": to字号, "kind", "chapter_anchor", "note"}],
    }``。
    输入为 None(文件间层没凑出关系)/ 没有任何边 → 返 None(端点返空态:依据链网络要 ≥2 份相关
    文件、≥1 条边才有意义)。
    """
    if not isinstance(cross_doc_result, dict):
        return None
    relations = cross_doc_result.get("relations")
    docs = cross_doc_result.get("docs")
    if not isinstance(relations, list) or not relations:
        return None  # 没边不画(同关系图:只画有关系的)
    if not isinstance(docs, list):
        docs = []

    # 文件节点:每份一节点,id = 字号(唯一身份证),带画像。同时收机关用于机关节点。
    file_nodes: dict[str, dict[str, Any]] = {}
    org_of: dict[str, str] = {}     # 字号 → 机关名(给机关节点连边用)
    for d in docs:
        if not isinstance(d, dict):
            continue
        num = str(d.get("字号", "")).strip()
        if not num or num in file_nodes:
            continue
        org = str(d.get("机关", "")).strip()
        file_nodes[num] = {
            "id": num,
            "kind": "文件",
            "label": num,
            "文种": str(d.get("文种", "")).strip(),
            "机关": org,
            "成文日期": str(d.get("成文日期", "")).strip(),
        }
        if org:
            org_of[num] = org

    # 边:有向、去重((from,to,kind) 只留首条,通常带着 chapter_anchor)。
    edges: list[dict[str, Any]] = []
    seen_edge: set[tuple[str, str, str]] = set()
    edge_nums: set[str] = set()     # 进过边的字号(没节点画像也得补个节点,免得边悬空)
    for rel in relations:
        if not isinstance(rel, dict):
            continue
        src = str(rel.get("from_doc", "")).strip()
        tgt = str(rel.get("to_doc", "")).strip()
        kind = str(rel.get("kind", "")).strip()
        if not src or not tgt or not kind or src == tgt:
            continue
        key = (src, tgt, kind)
        if key in seen_edge:
            continue
        seen_edge.add(key)
        edges.append({
            "source": src,
            "target": tgt,
            "kind": kind,
            "chapter_anchor": _clause_or_none(rel.get("chapter_anchor")),
            "note": str(rel.get("note", "")).strip(),
        })
        edge_nums.add(src)
        edge_nums.add(tgt)

    if not edges:
        return None  # 关系全是自指 / 空,没边可画

    # 边端点若没在 docs 里(理论上不该,cross_doc 已锚真实字号;防御性补个最小文件节点)。
    for num in edge_nums:
        if num not in file_nodes:
            file_nodes[num] = {
                "id": num, "kind": "文件", "label": num,
                "文种": "", "机关": org_of.get(num, ""), "成文日期": "",
            }

    # 机关节点 + 「机关→所辖文件」隶属边:同一机关辖多份文件时,机关当枢纽星(前端分色)。
    org_files: dict[str, list[str]] = {}
    for num, org in org_of.items():
        if num in file_nodes:  # 只连进了图的文件
            org_files.setdefault(org, []).append(num)
    org_nodes: list[dict[str, Any]] = []
    for org, nums in org_files.items():
        org_id = f"机关:{org}"          # 加前缀,免得机关名和某个字号撞 id
        org_nodes.append({
            "id": org_id, "kind": "机关", "label": org,
            "文种": "", "机关": org, "成文日期": "",
        })
        for num in nums:
            edges.append({
                "source": org_id, "target": num, "kind": "发文",
                "chapter_anchor": None, "note": f"{org}发布",
            })

    nodes = sorted(file_nodes.values(), key=lambda n: n["id"]) + sorted(
        org_nodes, key=lambda n: n["id"]
    )
    edges.sort(key=lambda e: (e["kind"] != "发文", e["source"], e["target"], e["kind"]))
    return {"nodes": nodes, "edges": edges}


# ════════════════════════════════════════════════════════════════════════════
# 视图二:政策演变时间线(时间维)——照搬 concept_evolution 整套
# ════════════════════════════════════════════════════════════════════════════

DEFAULT_POLICY_MAX_TOKENS = 16000
"""一次 LLM 排政策演变阶段的 max_tokens。

阶段条数 ∝ 这摞文件份数(Phase 1 限 3-5 份),加 reasoning 头(deepseek-v4-flash 把
reasoning_content 算进 max_tokens,见 [[reference_reasoning_model_token_budget]])。给 16000
够吐完;真撑爆靠 ``_parse_stages`` 截断抢救兜底。"""

_MAX_POLICY_STAGES = 30
_MAX_CLAUSE_REQS_PER_DOC = 6   # 每份取前几条「关键要求」当线索,够看演变又不撑爆 input

_POLICY_INSTR = (
    "下面 docs 是一摞围绕同一主题的党政机关公文,每份给了一个 **id(文件标识,有字号的是字号,"
    "没字号的地方法规是标题)**,以及 文种、发文机关、成文日期、标题事由和这份文件的几条关键要求"
    "(事项)。用户会给一个**政策主题**。\n"
    "请在这摞文件里挑出和这个主题相关的文件,**按成文日期先后**排出这项政策的演变——每个阶段"
    "对应哪份文件(填它的 id)、这一份相对上一份在要求上**改了什么**"
    "(新增 / 收紧 / 放宽 / 删去 / 调整)。\n"
    "- order 从 1 起递增,按成文日期升序。\n"
    "- 只挑清单里**确实涉及**这个主题的文件,只据清单、不编。\n"
    "- **这摞文件里没有这个主题就返回空数组,绝不编造演变。**\n"
    "- 第一份是政策起点(没有「上一份」),change 写它确立了什么;之后每份说清相对上一份的变化。\n"
    "change 用一句话说清这一步改了什么。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"stages":[{"order":序号整数,"doc":"对应文件的 id","change":"相对上一份改了什么"}]}'
)

_USER_MSG_POLICY = "请按上面的要求排出政策演变。"


def _collect_policy_inventory(
    doc_spines: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],         # 给 LLM 的紧凑清单
    set[str],                     # 全部真实字号(锚 doc 用)
    dict[str, str],               # 字号 → 成文日期(排序用)
    dict[str, dict[int, str]],    # 字号 → {条款序号: 已核 evidence}(现取 snippet 用)
]:
    """从一摞文脉收 紧凑清单 + 真实 anchor 集 + anchor→成文日期 + anchor→条款证据表。

    锚 id 优先发文字号,没字号(地方法规)退标题(同 cross_doc 的 ``_doc_anchor``)。两者都没的
    文脉排出演变阶段也对不上,丢。同 anchor 重复只留第一份。每份摘 标题事由 + 前几条款事项当
    「关键要求」线索。
    """
    digest: list[dict[str, Any]] = []
    real_nums: set[str] = set()
    date_of: dict[str, str] = {}
    ev_of: dict[str, dict[int, str]] = {}

    for spine in doc_spines:
        if not isinstance(spine, dict):
            continue
        anchor = _doc_anchor(spine)
        if not anchor or anchor in real_nums:
            continue
        real_nums.add(anchor)
        date_of[anchor] = _head_value(spine, _HEAD_DATE_FIELD)
        ev_of[anchor] = _clause_evidence_map(spine)

        reqs: list[str] = []
        clauses = spine.get("clauses")
        if isinstance(clauses, list):
            for cl in clauses:
                if not isinstance(cl, dict):
                    continue
                matter = str(cl.get("matter", "")).strip()
                if matter:
                    reqs.append(matter)
                if len(reqs) >= _MAX_CLAUSE_REQS_PER_DOC:
                    break

        digest.append({
            "id": anchor,
            "字号": _head_value(spine, _HEAD_ID_FIELD),
            "文种": _head_value(spine, _HEAD_DOC_TYPE_FIELD),
            "发文机关": _head_value(spine, _HEAD_ORG_FIELD),
            "成文日期": date_of[anchor],
            "标题事由": _head_value(spine, _HEAD_TITLE_FIELD),
            "关键要求": reqs,
        })
    return digest, real_nums, date_of, ev_of


def _parse_stages(text: str) -> list[dict[str, Any]] | None:
    """解析 ``{"stages":[...]}``;三层兜底(直解析 / 切首个对象 / 截断抢救)。同 concept 版。

    空数组(主题不在这摞文件)是合法结果返 ``[]``;彻底解析不出返 ``None``。
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
        logger.warning("cross_doc_views[policy]: 主解析失败,从截断抢救到 %d 阶段", len(salvaged))
        return salvaged
    return None


def policy_evolution_from_spines(
    *,
    doc_spines: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    topic: str | None = None,
    max_tokens: int = DEFAULT_POLICY_MAX_TOKENS,
    cache_enabled: bool = True,
) -> list[dict[str, Any]] | None:
    """一摞文脉一次 LLM 排政策演变阶段 → 阶段 list。失败返 ``None``,主题不在这摞文件返 ``[]``。

    照搬 ``concept_evolution_from_spine`` 整套:「概念」换「政策主题」、「章序」换「成文日期序」、
    「章」换「文件(字号)」。

    Args:
        doc_spines: 一摞文脉(每份 = ``build_doc_spine`` 的产出)。
        topic: 政策主题(用户给的)。``None`` / 空时不绑主题,让模型按这摞文件整体的政策线排演变。
        max_tokens / cache_enabled: 同其它跨文件视图。

    Returns:
        阶段 list,每条 ``{order, doc, change, snippet, verified}``——
        - ``doc`` 必须是这摞文件里真实的发文字号(防 LLM 编)。
        - ``snippet`` 取那份文脉某条款已核验的 evidence(点开现取的落地;没指定条款锚就取该文件
          任一已核证据),**取不到就丢这阶段**(立身之本,锚不到原文不输出)。
        - 按成文日期升序、同一文件只留一个、重编 order。
        少于 1 份有字号的文件 / 一次推理失败 / 解析不出 / 锚不到任何真实文件 → ``None``。
    """
    if not isinstance(doc_spines, list):
        return None
    digest, real_nums, date_of, ev_of = _collect_policy_inventory(doc_spines)
    if not real_nums:
        return None
    ref_map = _build_ref_map(doc_spines)

    topic = (topic or "").strip()
    payload: dict[str, Any] = {"docs": digest}
    if topic:
        payload["topic"] = topic
    user_content = json.dumps(payload, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_POLICY_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 调用失败降级返 None,不 break 端点
        logger.warning(
            "cross_doc_views[policy]: 演变调用抛 %s: %s;返 None", type(exc).__name__, exc
        )
        return None

    parsed = _parse_stages(text)
    if parsed is None:
        return None

    out: list[dict[str, Any]] = []
    seen_doc: set[str] = set()
    for st in parsed:
        if not isinstance(st, dict):
            continue
        doc = _resolve_doc_ref(str(st.get("doc", "")), real_nums, ref_map)
        if not doc or doc in seen_doc:
            continue  # 锚到真实文件(字号或标题都认,防编);同一文件去重
        snippet = _any_clause_evidence(ev_of.get(doc, {}))
        if not snippet:
            continue  # 这份文脉没留任何已核证据:丢这阶段(锚不到原文不输出)
        seen_doc.add(doc)
        out.append({
            "doc": doc,
            "change": str(st.get("change", "")).strip(),
            "snippet": snippet,
            "verified": True,
        })

    # 按成文日期升序(字符串比较;成文日期形如「2024年5月8日」,同年同月按字符序基本对——
    # Phase 1 这摞文件少,日期歧义留待规模化)。没日期的排末尾。
    out.sort(key=lambda s: date_of.get(s["doc"], "") or "￿")
    out = out[:_MAX_POLICY_STAGES]
    for i, s in enumerate(out, start=1):
        s["order"] = i
    out = [
        {"order": s["order"], "doc": s["doc"], "change": s["change"],
         "snippet": s["snippet"], "verified": s["verified"]}
        for s in out
    ]
    return out  # 可空(主题不在这摞文件 / 锚不到真实文件)


# ════════════════════════════════════════════════════════════════════════════
# 视图二·加一层:政策措辞 diff(逐字比)——新闻在 delta 里,不在新增的话里
# ════════════════════════════════════════════════════════════════════════════
#
# WP-redhead-deep-reading-lenses「读弦外·措辞 diff」:政策的新闻藏在措辞变化里——
# 鼓励→应当(升格)、严格→合理(松绑)、某提法删了(转向)。「阶段列举」(上面那层)说
# 「每份相对上一份改了什么」是一句话概括;这层往下钉到**关键提法逐字怎么变的**:同主题一组
# 公文里,找一个 topic_point(同一件事/同一提法),把它在两份文件里的**原话**摆出来——
# before(旧措辞 + 来自哪份)→ after(新措辞 + 来自哪份),direction 标方向(升格/松绑/收紧/
# 转向/新增/删除),basis 一句话说凭措辞里哪个词判的方向。
#
# evidence-first(立身之本):before / after 的措辞必须是**原文逐字**、过 ``verify_citations``
# 锚得到各自文件的已核证据池,锚不到的 diff 整条丢——绝不留对不上原文的 diff。direction 是
# **研判口径**(推断),靠 codebook 约束力阶梯判,但它只是给摆出来的逐字 before/after 贴个方向
# 标签,不放宽 before/after 的逐字证据要求。
#
# 向后兼容:这是**新增的一层**,独立函数、独立产出,``policy_evolution_from_spines`` 的阶段
# 输出 + 字段一个不动(端点已有的 stages 契约不破)。主 Claude 接 schema 时把 diff 作为政策演变
# 响应里**新增的一个字段**(如 ``wording_diffs``),与 stages 并列。

DEFAULT_POLICY_DIFF_MAX_TOKENS = 16000
"""一次 LLM 找措辞 diff 的 max_tokens。同政策演变量级。

diff 条数 ∝ 这摞文件里跨版本变了措辞的关键提法数(Phase 1 限 3-5 份,通常几条),加 reasoning 头
(deepseek-v4-flash 把 reasoning_content 算进 max_tokens,见 reference_reasoning_model_token_budget)。
给 16000 够吐完;真撑爆靠 ``_parse_diffs`` 截断抢救兜底。"""

_MAX_POLICY_DIFFS = 30
_MAX_CLAUSE_QUOTES_PER_DOC = 8
"""每份取前几条已核证据原文喂给 LLM 当「可引的原话池」——够找措辞变化又不撑爆 input。"""

# 措辞变化方向(封闭集,带证据撑;不让模型自造)。前四个是「同一提法改了措辞」的方向判读
# (套 codebook 约束力阶梯),后两个是「提法整段进/出」。落不进封闭集的 diff 丢。
POLICY_DIFF_DIRECTIONS: tuple[str, ...] = (
    "升格",  # 约束力升:鼓励/支持 → 应当/必须(要动真格了)
    "松绑",  # 约束力降:严格控制 → 合理调控 / 强制 → 鼓励(放宽)
    "收紧",  # 门槛/标准/口径收窄(范围缩小、条件加严)
    "转向",  # 提法换了方向/口径(不是单纯升降,是改了味)
    "新增",  # 旧版没有、新版加上的提法(before 缺位)
    "删除",  # 旧版有、新版删掉的提法(after 缺位)
)

# before / after 整段缺位(新增 / 删除)是允许的——一侧无原话另一侧必须逐字可锚。
_PRESENCE_OPTIONAL_DIRECTIONS: frozenset[str] = frozenset({"新增", "删除"})

_POLICY_DIFF_INSTR = (
    "下面 docs 是一摞围绕同一主题的党政机关公文,每份给了一个 **id(文件标识,有字号的是字号,"
    "没字号的地方法规是标题)**、文种 / 发文机关 / 成文日期 / 标题事由,以及这份文件里**几条已核"
    "原文片段(quotes)**。用户可能给一个**政策主题**。\n"
    "你的任务:在这摞文件里找出同一件事 / 同一个提法**跨文件措辞变了**的地方,逐条做措辞 diff。"
    "**政策的新闻藏在措辞变化的 delta 里**——「鼓励」升成「应当」、「严格控制」降成「合理调控」、"
    "某提法被删了 / 新加了——不在新增的客套话里。盯**关键提法的措辞变化**,别记流水账。\n"
    "每条 diff 给:\n"
    "- topic_point:这条 diff 针对的同一件事 / 同一提法(短、准,如「补贴标准的约束力」"
    "「准入门槛」)。\n"
    "- before:旧措辞——必须是某份较早文件里的**逐字原话**(从该文件的 quotes 里原样摘,"
    "一个字都别改)。before_doc 填这句来自哪份文件的 id。\n"
    "- after:新措辞——必须是某份较晚文件里的**逐字原话**(从该文件的 quotes 里原样摘)。"
    "after_doc 填这句来自哪份文件的 id。\n"
    "- direction:措辞变化的方向,只能填以下之一(按上面措辞刻度判):\n"
    "    · 升格:约束力升(鼓励/支持 → 应当/必须),要动真格了。\n"
    "    · 松绑:约束力降(严格 → 合理、强制 → 鼓励),放宽了。\n"
    "    · 收紧:门槛/标准/口径收窄(范围缩小、条件加严)。\n"
    "    · 转向:提法换了方向/口径(改了味,不是单纯升降)。\n"
    "    · 新增:旧版没有、新版加上的提法——这时 before 留空、只填 after + after_doc。\n"
    "    · 删除:旧版有、新版删掉的提法——这时 after 留空、只填 before + before_doc。\n"
    "- basis:一句话说清你凭措辞里**哪个词**判成这个方向的(锚措辞,如「『鼓励』变『应当』,"
    "约束力从倡导升到强制」),别空说。\n"
    "硬规矩:\n"
    "①before / after 必须是 quotes 里**真有**的逐字原文,一个字都不能编、不能改写、不能拼接。"
    "对不上原话的 diff 宁可不写——系统会逐字核,对不上的会被丢。\n"
    "②方向是「同一提法改了措辞」时(升格/松绑/收紧/转向),before 和 after **都要有**,且来自"
    "**不同**文件;只有「新增」「删除」才允许一侧留空。\n"
    "③只挑措辞**确实变了**的关键提法;两份说法一样(只是换个字眼意思没变)的别列。\n"
    "④这摞文件里找不到任何措辞变化就返回空数组,**绝不为了凑数编 diff**。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"diffs":[{"topic_point":"","before":"","before_doc":"","after":"","after_doc":"",'
    '"direction":"升格","basis":""}]}'
)

_USER_MSG_POLICY_DIFF = "请按上面的要求,找出跨文件的关键提法措辞变化,逐条做措辞 diff。"


def _collect_policy_quotes(
    doc_spines: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],            # 给 LLM 的紧凑清单(每份带已核原话池)
    set[str],                        # 全部真实 anchor
    dict[str, str],                  # anchor → 成文日期(排序用)
    dict[str, dict[str, dict]],      # anchor → 该文件证据登记表(verify_citations 用)
]:
    """收 紧凑清单(每份带前几条已核原话)+ anchor 集 + anchor→成文日期 + anchor→证据登记表。

    和 ``_collect_policy_inventory`` 同口径取 anchor / 日期,但这层多收两样:
    - 给 LLM 的 ``quotes``:每份前几条**已核 evidence 原文**(不是 matter 概括)——diff 要逐字比,
      得让模型从真原话里摘 before/after,不能让它凭概括编措辞。
    - per-doc 证据登记表:``{anchor: {chunk_id: {chapter, text}}}``,后面拿 ``verify_citations``
      逐字核 before/after 确在**对应文件**的原话池里(锚不到就丢)。
    """
    digest: list[dict[str, Any]] = []
    real_nums: set[str] = set()
    date_of: dict[str, str] = {}
    ev_table_of: dict[str, dict[str, dict]] = {}

    for spine in doc_spines:
        if not isinstance(spine, dict):
            continue
        anchor = _doc_anchor(spine)
        if not anchor or anchor in real_nums:
            continue
        real_nums.add(anchor)
        date_of[anchor] = _head_value(spine, _HEAD_DATE_FIELD)

        quotes: list[str] = []
        ev_table: dict[str, dict] = {}
        clauses = spine.get("clauses")
        if isinstance(clauses, list):
            for cl in clauses:
                if not isinstance(cl, dict) or not isinstance(cl.get("chapter"), int):
                    continue
                snip = str(cl.get("evidence", "")).strip()
                if not snip:
                    continue
                # 证据登记表:整份文脉所有已核 evidence 都进表(逐字核 before/after 用),
                # chunk_id 用「anchor#条款序号」唯一标识。
                ev_table[f"{anchor}#{cl['chapter']}"] = {
                    "chapter": cl["chapter"], "text": snip,
                }
                # 给 LLM 的可引原话池只摘前几条,免得 input 撑爆。
                if len(quotes) < _MAX_CLAUSE_QUOTES_PER_DOC:
                    quotes.append(snip)
        ev_table_of[anchor] = ev_table

        digest.append({
            "id": anchor,
            "文种": _head_value(spine, _HEAD_DOC_TYPE_FIELD),
            "发文机关": _head_value(spine, _HEAD_ORG_FIELD),
            "成文日期": date_of[anchor],
            "标题事由": _head_value(spine, _HEAD_TITLE_FIELD),
            "quotes": quotes,
        })
    return digest, real_nums, date_of, ev_table_of


def _parse_diffs(text: str) -> list[dict[str, Any]] | None:
    """解析 ``{"diffs":[...]}``;三层兜底(直解析 / 切首个对象 / 截断抢救)。同 ``_parse_stages``。

    空数组(这摞文件没措辞变化)是合法结果返 ``[]``;彻底解析不出返 ``None``。
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
    if isinstance(obj, dict) and isinstance(obj.get("diffs"), list):
        return obj["diffs"]
    salvaged = salvage_closed_objects(candidate, '"diffs"')
    if salvaged:
        logger.warning("cross_doc_views[diff]: 主解析失败,从截断抢救到 %d 条 diff", len(salvaged))
        return salvaged
    return None


def _wording_verbatim(quote: str, ev_table: dict[str, dict]) -> bool:
    """这句措辞在某份文件的已核原话池里**逐字**锚得到吗(归一化后精确子串)。

    走和证据层一样的核验路径(``verify_citations``),但只认 ``match_type == "quote"``——
    措辞 diff 的命门是「逐字」,n-gram 转述(paraphrase)对 diff 不够:措辞变没变的判断本身就靠
    一个字一个字对,转述命中说明模型改写了原话,这条 diff 的 before/after 就不可信,丢。

    ev_table 为该文件的证据登记表 ``{chunk_id: {chapter, text}}``;空池 / 空 quote → False。
    """
    q = (quote or "").strip()
    if not q or not ev_table:
        return False
    cits = [{"snippet": q}]
    verify_citations(cits, ev_table)
    return cits[0].get("match_type") == "quote"


def policy_wording_diff_from_spines(
    *,
    doc_spines: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    topic: str | None = None,
    max_tokens: int = DEFAULT_POLICY_DIFF_MAX_TOKENS,
    cache_enabled: bool = True,
) -> list[dict[str, Any]] | None:
    """一摞文脉一次 LLM 找跨文件**措辞 diff** → diff list。失败返 ``None``,没措辞变化返 ``[]``。

    政策演变「阶段列举」(``policy_evolution_from_spines``)往下钻一层:不是「每份改了什么」的一句话
    概括,而是钉到**关键提法逐字怎么变的**——同主题一组公文里,把同一件事的旧措辞 / 新措辞**原话**
    摆出来,标方向(升格/松绑/收紧/转向/新增/删除)。direction 靠 codebook 约束力阶梯判。

    **evidence-first(立身之本)**:before / after 必须是**原文逐字**、过 ``verify_citations`` 锚到
    **各自文件**的已核证据池(只认逐字命中 quote,不认转述),锚不到的 diff 整条丢。direction 是
    研判口径(推断),只给逐字 before/after 贴方向标签,不放宽逐字证据要求。

    **向后兼容**:独立函数、独立产出,不碰 ``policy_evolution_from_spines`` 的阶段输出。

    Args:
        doc_spines: 一摞文脉(每份 = ``build_doc_spine`` 的产出)。
        topic: 政策主题(可选)。``None`` / 空时让模型按这摞文件整体找措辞变化。
        max_tokens / cache_enabled: 同其它跨文件视图。

    Returns:
        diff list,每条 ``{topic_point, before, before_doc, after, after_doc, direction,
        basis, verified}``——
        - before_doc / after_doc 必须是这摞文件里真实的 anchor(防 LLM 编;字号或标题都认)。
        - direction 落进 ``POLICY_DIFF_DIRECTIONS`` 封闭集(落不进丢)。
        - before / after 必须在**各自文件**的已核证据池里逐字锚得到(``verified=True``);「新增」
          只核 after、「删除」只核 before,其余两侧都核——**任一该核的侧锚不到就丢这条**。
        - 按 after 文件的成文日期升序(没日期排末尾),同 ``(topic_point, before, after)`` 去重。
        少于 2 份有 anchor 的文件 / 一次推理失败 / 解析不出 / 全被守卫滤掉 → ``None`` / ``[]``。
    """
    if not isinstance(doc_spines, list):
        return None
    digest, real_nums, date_of, ev_table_of = _collect_policy_quotes(doc_spines)
    # 措辞 diff 是跨文件比,至少要两份有 anchor 的文件才谈得上「变化」。
    if len(real_nums) < 2:
        return None
    ref_map = _build_ref_map(doc_spines)

    topic = (topic or "").strip()
    payload: dict[str, Any] = {"docs": digest}
    if topic:
        payload["topic"] = topic
    user_content = json.dumps(payload, ensure_ascii=False)
    # codebook 约束力阶梯进 system,统一升格/松绑的判读口径(WP「共享资产:codebook 一次建多处用」)。
    system = _POLICY_DIFF_INSTR + "\n" + codebook_block()
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=system,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 调用失败降级返 None,不 break 端点
        logger.warning(
            "cross_doc_views[diff]: 措辞 diff 调用抛 %s: %s;返 None", type(exc).__name__, exc
        )
        return None

    parsed = _parse_diffs(text)
    if parsed is None:
        return None

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for d in parsed:
        if not isinstance(d, dict):
            continue
        direction = str(d.get("direction", "")).strip()
        if direction not in POLICY_DIFF_DIRECTIONS:
            continue  # 落不进封闭集:丢(不自造方向)

        topic_point = str(d.get("topic_point", "")).strip()
        before = str(d.get("before", "")).strip()
        after = str(d.get("after", "")).strip()
        before_doc = _resolve_doc_ref(str(d.get("before_doc", "")), real_nums, ref_map)
        after_doc = _resolve_doc_ref(str(d.get("after_doc", "")), real_nums, ref_map)

        presence_optional = direction in _PRESENCE_OPTIONAL_DIRECTIONS
        # before 侧:除「新增」(允许旧版无此提法)外都要逐字锚到 before_doc 的原话池。
        before_ok = True
        if not (presence_optional and direction == "新增"):
            before_ok = (
                bool(before)
                and bool(before_doc)
                and _wording_verbatim(before, ev_table_of.get(before_doc, {}))
            )
        # after 侧:除「删除」(允许新版删掉此提法)外都要逐字锚到 after_doc 的原话池。
        after_ok = True
        if not (presence_optional and direction == "删除"):
            after_ok = (
                bool(after)
                and bool(after_doc)
                and _wording_verbatim(after, ev_table_of.get(after_doc, {}))
            )
        if not before_ok or not after_ok:
            continue  # 该核的侧措辞对不上原文:丢(立身之本)

        # 「改了措辞」类(非新增/删除)必须 before/after 来自不同文件——同文件内不算跨文件演变。
        if not presence_optional and before_doc == after_doc:
            continue

        key = (topic_point, normalize_text(before), normalize_text(after))
        if key in seen:
            continue
        seen.add(key)

        out.append({
            "topic_point": topic_point,
            "before": before,
            "before_doc": before_doc,
            "after": after,
            "after_doc": after_doc,
            "direction": direction,
            "basis": str(d.get("basis", "")).strip(),
            "verified": True,
        })

    # 按 after 文件成文日期升序(diff 落在「变成什么」那一刻);没日期排末尾。新增/删除取有的那侧。
    def _diff_date(item: dict[str, Any]) -> str:
        anchor = item["after_doc"] or item["before_doc"]
        return date_of.get(anchor, "") or "￿"

    out.sort(key=_diff_date)
    return out[:_MAX_POLICY_DIFFS]  # 可空(没措辞变化 / 全被守卫滤掉)


# ════════════════════════════════════════════════════════════════════════════
# 视图三:上下级一致性核查(冲突维)——照搬 consistency_scan 整套
# ════════════════════════════════════════════════════════════════════════════

DEFAULT_LEVEL_MAX_TOKENS = 16000
"""一次 LLM 找上下级走样的 max_tokens。同政策演变量级,Phase 1 限 3-5 份够用。"""

# 机关层级:从机关名 / 文种行文方向判出谁是上位。数字越小越靠上(中央 1 < 省 2 < 市 3 < 县 4)。
# 判不准退 0(未知层级)——未知层级之间不强判上下级,交给 LLM 据清单实质判。
#
# 覆盖地方法规的发文机关:地方性法规是**人大常委会**发的(「广东省人民代表大会常务委员会」),
# 不是政府发文。这类机关名里总带「省 / 市 / 县」前缀,所以省 / 市 / 县这几个子串关键词已经能
# 判出层级——广东省人大常委会含「省」判 2,广州市人大常委会含「市」判 3。中央一级补上「全国
# 人民代表大会」(全国人大常委会发的国家级法律),免得只靠「全国」漏掉变体。匹配取「最具体
# (数字最大)」那级,省市县字样优先于部委。
#
# 变通主体也得认出层级(立法法的变通权主体):自治区(2)/自治州(3)/自治县·民族乡(4),还有
# 经济特区(有授权立法权,按市判 3,补「经济特区」串以防只写「XX经济特区」漏判)。这些主体的差异
# 默认走「合法变通」而非走样(见 ``_has_variation_authority`` + ``_LEVEL_INSTR`` 的抵触/变通区分)。
# 注意:**不放裸「区」**当层级关键词——「区」太含糊(自治区是省级、市辖区是县级、经济特区另算),
# 放进去会把「内蒙古自治区」误判成 4。自治区走「自治区」判 2、经济特区走「经济特区」判 3,市辖区
# 这种没法只从「区」字判准,宁可退 0 也不误判。
_LEVEL_KEYWORDS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, ("中共中央", "国务院", "中央", "全国人民代表大会", "全国", "部", "委", "国家")),
    (2, ("省", "自治区", "直辖市")),
    (3, ("市", "地区", "自治州", "州", "盟", "经济特区")),
    (4, ("县", "自治县", "民族乡", "旗", "乡", "镇")),
)

# 有法定变通权的主体关键词(立法法):民族自治地方(自治区 / 自治州 / 自治县 / 民族乡)的自治条例 /
# 单行条例,以及经济特区的授权立法,对上位法可作**合法变通**——它们和上位「不一致」不等于「抵触」,
# 不该报为走样。命中即给这份文件打「变通权」标,喂进 prompt 让模型据此走抵触/变通区分。
_VARIATION_ORG_KEYWORDS: tuple[str, ...] = (
    "自治区", "自治州", "自治县", "民族乡", "经济特区",
)

# 走样类型封闭集(冲突维标签,带证据撑;不让模型自造)。"一致" / 合法变通 是自洽、不进结果。
#
# 「抵触」是立法法术语的本名(下位法违反上位法),和「走样」同义但更准——把它进封闭集,让模型
# 能直接用法理术语标真正的违法,和合法变通划清界(变通不进任何标签)。
DEVIATION_TYPES: tuple[str, ...] = (
    "抵触",      # 下位违反上位法(立法法本名;真正该报的违法)
    "走样",      # 下位把上位的要求改了味(方向 / 标准变了)
    "加码",      # 下位层层加码(标准 / 力度超出上位)
    "漏落实",    # 上位有要求、下位没接住
)

_MIN_LEVEL = 0


def _org_level(org: str) -> int:
    """从发文机关名判机关层级:1 中央 / 2 省 / 3 市 / 4 县;判不准退 0(未知)。

    从最具体的层级往上匹配(先看县 / 市,再省,最后中央)——「某省某市政府」既含「省」又含「市」,
    取更具体的「市」(层级数更大)。判不准的(没命中任何关键词)退 0,不强判。
    """
    o = org or ""
    best = _MIN_LEVEL
    for level, kws in _LEVEL_KEYWORDS:
        if any(k in o for k in kws):
            best = max(best, level)  # 取最具体(数字最大)的层级
    return best


def _has_variation_authority(org: str) -> bool:
    """这份文件的发文机关有没有法定变通权(立法法):民族自治地方 / 经济特区。

    有的话,它和上位法「不一致」默认是**合法变通**(自治条例 / 单行条例 / 授权因地制宜),不是抵触,
    不该报为走样——这个标喂进 ``_LEVEL_INSTR`` 让模型据此压掉对合法变通的误报(降 cry wolf)。
    """
    o = org or ""
    return any(k in o for k in _VARIATION_ORG_KEYWORDS)


def _collect_level_inventory(
    doc_spines: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],         # 给 LLM 的紧凑清单(带 层级 标注)
    set[str],                     # 全部真实字号
    dict[str, int],               # 字号 → 层级
    dict[str, dict[int, str]],    # 字号 → {条款序号: 已核 evidence}
]:
    """从一摞文脉收 紧凑清单(标好层级)+ 真实 anchor 集 + anchor→层级 + anchor→条款证据表。

    锚 id 优先发文字号,没字号(地方法规)退标题(同 cross_doc 的 ``_doc_anchor``)。每份按发文
    机关判层级(``_org_level``),把层级标进清单当线索。
    """
    digest: list[dict[str, Any]] = []
    real_nums: set[str] = set()
    level_of: dict[str, int] = {}
    ev_of: dict[str, dict[int, str]] = {}

    for spine in doc_spines:
        if not isinstance(spine, dict):
            continue
        anchor = _doc_anchor(spine)
        if not anchor or anchor in real_nums:
            continue
        real_nums.add(anchor)
        org = _head_value(spine, _HEAD_ORG_FIELD)
        level_of[anchor] = _org_level(org)
        ev_of[anchor] = _clause_evidence_map(spine)

        clauses_brief: list[dict[str, Any]] = []
        clauses = spine.get("clauses")
        if isinstance(clauses, list):
            for cl in clauses:
                if not isinstance(cl, dict) or not isinstance(cl.get("chapter"), int):
                    continue
                matter = str(cl.get("matter", "")).strip()
                if not matter:
                    continue
                clauses_brief.append({
                    "条款": cl["chapter"],
                    "事项": matter,
                    "指令类型": str(cl.get("instruction_type", "")).strip(),
                })

        digest.append({
            "id": anchor,
            "字号": _head_value(spine, _HEAD_ID_FIELD),
            "文种": _head_value(spine, _HEAD_DOC_TYPE_FIELD),
            "发文机关": org,
            "层级": level_of[anchor],   # 1 中央 2 省 3 市 4 县,0 未知
            "变通权": _has_variation_authority(org),  # 民族自治地方 / 经济特区:不一致默认合法变通
            "条款": clauses_brief,
        })
    return digest, real_nums, level_of, ev_of


def _has_hierarchy(level_of: dict[str, int]) -> bool:
    """这摞文件里有没有上下级落差——题材自适应(§5.3):全平级 / 单文件 → 没上下级可查。

    至少要有两个**不同的已知层级**(>0)才算有上下级。全是同一层级(平级商洽,如一摞「函」)、
    或层级全未知、或只有一份 → False,上层据此返 None,不硬造一致性核查。
    """
    known = {lv for lv in level_of.values() if lv > _MIN_LEVEL}
    return len(known) >= 2


_LEVEL_INSTR = (
    "下面 docs 是同一主题、不同层级党政机关发的一摞公文(层级:1=中央 2=省 3=市 4=县,0=层级未知;"
    "每份还带「变通权」标:true 表示这份是民族自治地方〔自治区 / 自治州 / 自治县 / 民族乡〕或经济"
    "特区发的,依立法法对上位法有法定的变通权)。每份给了一个 **id(文件标识,有字号是字号,没字号"
    "的地方法规是标题)**、文种 / 发文机关 / 层级 / 变通权,以及每条款的 事项 / 指令类型。\n"
    "请按立法法的法理,只找出下位文件**真正抵触上位法**的地方——下位违反上位的强制要求,或上位有"
    "明确要求下位完全没接住。这才该报;合法的地方差异不报。\n"
    "deviation 只能填以下之一(按实质判,落不进就别列这条):\n"
    "- 抵触:下位违反上位法的强制规定(立法法本名,真正的违法,最该报)。\n"
    "- 走样:下位把上位的要求改了味(方向 / 口径变了,实质上偏离上位)。\n"
    "- 加码:下位层层加码(标准 / 力度超出上位要求,擅自加重)。\n"
    "- 漏落实:上位有明确要求,下位文件里完全没接住。\n"
    "**关键:区分「抵触」和「合法的不一致」。下位跟上位不一样,不等于抵触。以下都是【合法变通 / "
    "正常落实】,绝不要列:**\n"
    "① 同一件事的不同口径 / 表述(意思一致只是措辞不同);\n"
    "② 合理的下位细化(上位定原则、下位定具体办法,是正常落实不是抵触);\n"
    "③ 上位明确授权下位自定 / 因地制宜的事项(下位据此细化是被授权的,合法变通);\n"
    "④ 不同阶段的合理调整(政策随时间推进的正常演进);\n"
    "⑤ **「变通权」为 true 的文件**(民族自治地方的自治条例 / 单行条例、经济特区授权立法):它们依"
    "立法法可以对上位法作变通规定,和上位**不一致是合法变通,不是抵触**——除非明显超出变通授权的"
    "边界(如违反法律 / 行政法规的基本原则),否则一律不报。\n"
    "- upper 必须是层级**更靠上**(层级数更小)的那份文件 id,lower 是更靠下的;两份必须层级不同。\n"
    "- 只依据给出的清单,别编清单里没有的对不上。错把合法变通报成抵触,比漏报一条更糟"
    "(读者可能拿这个结论去办事 / 申诉,误报会害人)。\n"
    "topic 写涉及的事项;detail 用一句话说清下位哪里抵触了上位。\n"
    "upper_clause / lower_clause 写各自文件里涉及这条的**条款序号整数**(说不清留空 / 不填)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"deviations":[{"topic":"涉及的事项","detail":"下位哪里抵触上位","deviation":"抵触",'
    '"upper":"上位文件 id","lower":"下位文件 id",'
    '"upper_clause":条款序号整数,"lower_clause":条款序号整数}]}'
)

_USER_MSG_LEVEL = "请按上面的要求找出上下级对不上的地方。"


def _parse_deviations(text: str) -> list[dict[str, Any]] | None:
    """解析 ``{"deviations":[...]}``;三层兜底。空数组(都一致)返 ``[]``,解析不出返 ``None``。"""
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
    if isinstance(obj, dict) and isinstance(obj.get("deviations"), list):
        return obj["deviations"]
    salvaged = salvage_closed_objects(candidate, '"deviations"')
    if salvaged:
        logger.warning(
            "cross_doc_views[level]: 主解析失败,从截断抢救到 %d 条走样", len(salvaged)
        )
        return salvaged
    return None


def _clause_or_none(v: Any) -> int | None:
    """把 LLM 给的条款号归一:真整数才留(排掉 bool),否则 None(说不清就不硬填一个条款号)。"""
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _level_snippet(ev_map: dict[int, str], clause: Any) -> str:
    """一处走样的某一侧 snippet:指定了真实条款锚就取那条款已核 evidence,否则取该文件任一已核证据。

    取不到(该条款没留证据 / 整份文脉没任何已核证据)→ 空串,交给下游「任一空就丢」守卫拦掉这条
    (不 cry wolf:坐实不了的走样不出)。
    """
    if isinstance(clause, int) and not isinstance(clause, bool):
        snip = ev_map.get(clause, "")
        if snip:
            return snip
    return _any_clause_evidence(ev_map)


def level_consistency_from_spines(
    *,
    doc_spines: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int = DEFAULT_LEVEL_MAX_TOKENS,
    cache_enabled: bool = True,
) -> list[dict[str, Any]] | None:
    """一摞文脉一次 LLM 找上下级走样 → 走样 list。失败 / 没上下级关系返 ``None``,都一致返 ``[]``。

    照搬 ``consistency_scan_from_spine`` 整套:「前后章矛盾」换「上下级文件要求不一致」、「a/b 章」
    换「上位 / 下位文件」、双向守卫的「不算矛盾」换公文版「不算走样」。

    **题材自适应(§5.3)**:这摞文件全平级 / 单文件 / 层级全未知(凑不出上下级落差)→ 返
    ``None``,不硬造(没有上下级关系的一摞,上下级一致性这个视图本就该掉)。

    Returns:
        走样 list,每条 ``{topic, detail, deviation,
        upper:{doc, clause, snippet, verified}, lower:{doc, clause, snippet, verified}}``——
        - upper / lower 必须是真实字号、且 upper 层级严格高于 lower(防 LLM 编 / 把平级当上下级)。
        - deviation 落进 ``DEVIATION_TYPES`` 封闭集(抵触 / 走样 / 加码 / 漏落实;落不进丢)。
        - 两侧 snippet 取各自文脉那条款已核 evidence(点开现取),**任一侧取不到就丢这条**
          (双向守卫,不 cry wolf)。
        **抵触 vs 合法变通**(立法法,见 ``_LEVEL_INSTR``):只报下位真违反上位的抵触 / 走样 / 加码 /
        漏落实;民族自治地方(自治区 / 自治州 / 自治县 / 民族乡)的自治条例 / 单行条例、经济特区授权
        立法、上位授权的因地制宜——这类和上位「不一致」是合法变通,不报(降 cry wolf)。
        按 topic 去重。一次推理失败 / 解析不出 / 候选全被守卫滤掉 → 视情况返 ``None`` / ``[]``。
    """
    if not isinstance(doc_spines, list):
        return None
    digest, real_nums, level_of, ev_of = _collect_level_inventory(doc_spines)
    if not real_nums or not _has_hierarchy(level_of):
        return None  # 没上下级落差:这个视图本就该掉(题材自适应)
    ref_map = _build_ref_map(doc_spines)

    user_content = json.dumps({"docs": digest}, ensure_ascii=False)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=_LEVEL_INSTR,
            tools=[],
            messages=[{"role": "user", "content": user_content}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        text = llm_client.extract_final_text(resp)
    except Exception as exc:  # noqa: BLE001 — 调用失败降级返 None,不 break 端点
        logger.warning(
            "cross_doc_views[level]: 核查调用抛 %s: %s;返 None", type(exc).__name__, exc
        )
        return None

    parsed = _parse_deviations(text)
    if parsed is None:
        return None

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for c in parsed:
        if not isinstance(c, dict):
            continue
        upper = _resolve_doc_ref(str(c.get("upper", "")), real_nums, ref_map)
        lower = _resolve_doc_ref(str(c.get("lower", "")), real_nums, ref_map)
        # 锚到真实文件(字号或标题都认)+ 两份不同 + upper 层级严格高于 lower(防编 / 防把平级当上下级)
        if not upper or not lower or upper == lower:
            continue
        up_lv, lo_lv = level_of.get(upper, _MIN_LEVEL), level_of.get(lower, _MIN_LEVEL)
        if up_lv <= _MIN_LEVEL or lo_lv <= _MIN_LEVEL or up_lv >= lo_lv:
            continue  # 层级未知 / upper 不比 lower 靠上(数字更小才更靠上):不当上下级走样
        deviation = str(c.get("deviation", "")).strip()
        if deviation not in DEVIATION_TYPES:
            continue  # 落不进封闭集:丢(不自造走样类型)
        topic = str(c.get("topic", "")).strip()
        detail = str(c.get("detail", "")).strip()
        key = topic or detail
        if not key or key in seen:
            continue

        up_clause = c.get("upper_clause")
        lo_clause = c.get("lower_clause")
        up_snip = _level_snippet(ev_of.get(upper, {}), up_clause)
        lo_snip = _level_snippet(ev_of.get(lower, {}), lo_clause)
        if not up_snip or not lo_snip:
            continue  # 任一侧坐实不了:丢(双向守卫,cry wolf 代价大)

        seen.add(key)
        out.append({
            "topic": topic,
            "detail": detail,
            "deviation": deviation,
            "upper": {"doc": upper, "clause": _clause_or_none(up_clause),
                      "snippet": up_snip, "verified": True},
            "lower": {"doc": lower, "clause": _clause_or_none(lo_clause),
                      "snippet": lo_snip, "verified": True},
        })

    out.sort(key=lambda x: (x["upper"]["doc"], x["lower"]["doc"]))
    return out  # 可空(都一致 / 候选全被守卫滤掉)


__all__ = [
    "DEFAULT_LEVEL_MAX_TOKENS",
    "DEFAULT_POLICY_DIFF_MAX_TOKENS",
    "DEFAULT_POLICY_MAX_TOKENS",
    "DEVIATION_TYPES",
    "POLICY_DIFF_DIRECTIONS",
    "dependency_graph_from_cross_doc",
    "level_consistency_from_spines",
    "policy_evolution_from_spines",
    "policy_wording_diff_from_spines",
]
