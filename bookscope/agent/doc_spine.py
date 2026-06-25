"""公文「文脉」(1.6 红头文件垂直地基)——章脉的公文版,一份公文精读一次出带证据的结构。

**它是什么**:章脉是「一本书 → 逐章带证据结构」,文脉是「一份公文 → 文件头要素 + 逐条款带证据结构」。
设计稿 `docs/design/WP-1.6-redhead-vertical-design.md` §1.2 定的两维:

- **头要素维**(文件级,一份一组):发文字号 / 文种 / 发文机关 / 主送机关 / 抄送机关 / 标题事由 /
  成文日期 / 签发人。对 GB/T 9704 可验。每个要素挂原文、过 ``verify_citations``,**抽不到就留空、
  绝不编**(§5.2:扫描件漏了发文字号宁可标待核让用户回原件,绝不靠模型猜一个填上)。
- **条款维**(逐条款,对应章脉逐章):事项 / 指令类型 / 责任主体 / 时限 / 依据引用 / evidence。
  **指令类型是带原文撑的分类标签(硬要求 / 软倡导 / 信息告知 / 依据陈述),绝不让模型拍 0-10 分**——
  这是 §1.2 + `feedback_viz_algorithm_rigor` 的硬要求。公文比小说好做:硬要求往往有标志词
  (「应当」「必须」「不得」「限X日前」),抽取有抓手、可复现。

**复用了章脉哪些骨架**(铁律:一行不改 `chapter_spine.py` 等书籍引擎现有模块,只 import helper):

- 条款维直接走 ``exhaustive.mapreduce_per_chapter``(分段 + 并发 + 按单元 map-reduce +
  ``_correct_by_evidence`` 证据纠偏 + 截断续抽)。单元从「章」换成「条款序号」——内部仍用
  ``chapter`` 这个键当单元号(map-reduce 骨架按它分段 / 纠偏 / 去重),语义是条款序号。
- 头要素维一次抽取后,每要素 evidence 过 ``citation_check.verify_citations`` /
  ``build_evidence_map``,核不过标 ``verified=False``。
- JSON 解析三层兜底(``strip_code_fence`` / ``extract_first_json_object`` /
  ``salvage_closed_objects`` 截断抢救)照搬 ``utils/json_parsing``。
- ``build_longctx_system`` book-first 拼 system(公文也吃前缀缓存)。

不碰端点 / fixture / 前端。这一层只产出文脉 dict,文件间层(cross_doc)、单文件解读端点是后面的事。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.exhaustive import (
    DEFAULT_CHAR_BUDGET,
    run_segments,
)
from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DOC_SPINE_SCHEMA_VERSION = "v1"
"""文脉记录结构版本——升级要让缓存整份失效(接 ADR-008,与章脉 SPINE_SCHEMA_VERSION 同理)。"""

DEFAULT_DOC_SPINE_MAX_TOKENS = 8000
"""条款维单段输出与头要素维一次抽取的 max_tokens;配章节闸够用,留 reasoning 头。"""

_DOC_CLAUSE_MAX_CHAPTERS = 3
"""条款维分段的章节闸(收窄)。

公文一个「章」(章节,如「第三章 市场环境」)往往塞十几条「条款」,每条带 evidence + 多字段;
一段攒太多章节、条款数堆上去会冲爆 8000 输出(同章脉重维爆 token 的道理)。章脉重维章闸是 6,
公文条款比逐章字段还密(一章十几条),收得更紧到 3——一段最多 3 个章节、几十条以内,留足
8000 余量;太大的章节靠 ``run_segments`` 的字数闸先断段。"""

_DOC_CLAUSE_CONTINUE_MAX_ROUNDS = 4
"""条款维某段被截断时最多续抽几轮——每轮让模型「接着没抽完的往下抽」,补满或某轮空了就停。"""

# 15 法定公文文种(《党政机关公文处理工作条例》)。
_STATUTORY_DOC_TYPES: tuple[str, ...] = (
    "决议", "决定", "命令", "公报", "公告", "通告", "意见", "通知",
    "通报", "报告", "请示", "批复", "议案", "函", "纪要",
)

# 法规 / 公布令类文种。真实红头文件里大量是「条例 / 办法 / 规定」这类法规,以及
# 「国务院令 / 主席令」这类公布令——它们不在 15 法定公文文种里,但 GB/T 9704 与
# 立法法体系都认,是公文实务的常见文种。早先只收 15 法定文种,导致「优化营商环境
# 条例」这类公布令格式的公文文种判不出来被清空(头要素抽 0/8 的主因之一)。
_REGULATION_DOC_TYPES: tuple[str, ...] = (
    "条例", "规定", "办法", "细则", "准则", "规则", "令",
)

# 文种封闭集 = 法定公文文种 + 法规/公布令文种。文种识别只能落在这个集合里,
# 落不进就留空标待核——不让模型自造一个「文种」(§5.2 GB/T 要素绝不编)。
DOC_TYPES: tuple[str, ...] = _STATUTORY_DOC_TYPES + _REGULATION_DOC_TYPES

# 指令类型四标签(封闭集)。**这是公文版的「张力」,绝不让模型拍 0-10 分**——做成带原文撑的
# 分类标签。落不进这四类的退「信息告知」(最弱、最不会误导用户去办事的兜底)。
INSTRUCTION_TYPES: tuple[str, ...] = (
    "硬要求",    # 应当/必须/不得/限X日前 —— 有法定约束力、必须执行
    "软倡导",    # 鼓励/提倡/支持/可以 —— 倡导性、无强制
    "信息告知",  # 单纯告知情况/通报数据 —— 不要求收文方办什么
    "依据陈述",  # 「根据X」「为贯彻Y」 —— 陈述行文依据,本身不是要求
)
_DEFAULT_INSTR_TYPE = "信息告知"
"""指令类型落不进四类时的兜底——退最弱的「信息告知」,不会误导用户把它当硬要求去办。"""

# ── 头要素维 ───────────────────────────────────────────────────────────────
# 头要素字段名 → 给模型的中文说明。一份公文一组,每个要素带一句撑它的原文。
_HEAD_FIELDS: dict[str, str] = {
    "发文字号": (
        "文件的唯一身份号,有几种常见写法都要认:①机关代字+年份+序号,如"
        "「国办发〔2024〕5号」;②公布令格式,如「国务院令第722号」「中华人民共和国"
        "主席令第X号」「X令第X号」。抽到哪种照抄哪种;抽不到留空。"
    ),
    "文种": (
        f"必须是这个封闭集里的一个{DOC_TYPES};既包括 15 法定公文文种,也包括「条例/"
        "规定/办法/细则」这类法规和「令」这类公布令。法规类公文(如《优化营商环境条例》)"
        "文种就是「条例」,公布令(如「国务院令」)文种就是「令」。判不准留空,绝不自造文种。"
    ),
    "发文机关": (
        "谁发的(机关全称或规范简称)。除了落款署名,公布头也算——"
        "「中华人民共和国国务院令」里发文机关是「国务院」,「XX市人民政府令」里是「XX市人民政府」。"
        "地方性法规(标题是「X省条例 / X市条例 / X省办法」这类、由人大常委会通过)发文机关是"
        "**通过它的那级人大常委会**:省级条例填「X省人民代表大会常务委员会」、市级条例填"
        "「X市人民代表大会常务委员会」——X 取标题或来源里写明的省 / 市名(如「广东省优化营商"
        "环境条例」→「广东省人民代表大会常务委员会」)。正文若有「X省X届人民代表大会常务委员会"
        "……通过」一行,照它抄全称;没有那行就按标题的省 / 市名补到「X省 / X市人民代表大会常务"
        "委员会」这一级,evidence 引标题里带「X省 / X市」的那句原文。"
    ),
    "主送机关": "发给谁办理(主送对象)。",
    "抄送机关": "抄送给谁知会(没有就留空)。",
    "标题事由": (
        "标题里「关于……」的事由部分,或法规的全称。**地方性法规要带上行政区划前缀**:"
        "广东省的条例标题事由是「广东省优化营商环境条例」、广州市的是「广州市优化营商环境条例」,"
        "**不要砍成「优化营商环境条例」**——省 / 市前缀是区分同名法规的关键,绝不能丢。只有"
        "中央 / 国务院本级、本身就没行政区划前缀的(如国务院令公布的《优化营商环境条例》)"
        "才不带前缀。"
    ),
    "成文日期": (
        "文件的成文/公布日期(时效起算点),原样照抄如「2024年5月8日」。公布令里"
        "署名那行(如「总理 李克强  2019年10月22日」)的日期就是成文日期。"
    ),
    "签发人": (
        "签发人姓名。上行文落款有;公布令里「总理 X」「主席 X」这类署名也算签发人。"
        "没有留空。"
    ),
}

_INSTR_HEAD = (
    "你在给一份党政机关公文(红头文件)抽**文件头要素**。只依据下面的原文,抽得到才填、"
    "**抽不到就留空字符串,绝不编造、绝不猜**(尤其发文字号/成文日期这类身份要素,宁可空着待核)。\n"
    "公文格式有好几种,别只认「X发〔年〕号 + 关于……的通知」这一种标准发文格式:\n"
    "- 公布令格式:开头是「中华人民共和国国务院令 / 第722号 / 《XX条例》已经……通过,现予公布 / "
    "总理 李克强 / 日期 / XX条例」——这种发文机关是「国务院」、文种是「令」或「条例」、"
    "发文字号是「国务院令第722号」、签发人是「李克强」、成文日期是署名那行的日期。\n"
    "- 地方法规:可能直接以「第一章 总则」开头,正文里「根据……制定本条例」点出文种是「条例」,"
    "标题/来源行给出全称(如「广东省优化营商环境条例」)。这种发文字号/签发人常没有,留空别硬凑;"
    "但**发文机关要补到人大常委会这一级**——地方性法规由本级人大常委会通过,标题写明省/市的,"
    "发文机关就是「X省人民代表大会常务委员会」或「X市人民代表大会常务委员会」(X 取标题的省/市名),"
    "evidence 引标题里带省/市名的那句;标题事由也要带上省/市前缀,别砍成光秃秃的"
    "「优化营商环境条例」。\n"
    "每个要素同时给一句**撑它的原文逐字片段**(原样摘录、不改写)挂在 evidence 里;某要素的原文"
    "找不到就连同该要素一起留空。\n"
    "要抽的要素:\n"
    + "".join(f"- {k}:{v}\n" for k, v in _HEAD_FIELDS.items())
    + "严格输出 JSON(别的话别说、别加 markdown 围栏),形如:\n"
    '{"elements":[{"field":"发文字号","value":"","evidence":""},'
    '{"field":"文种","value":"","evidence":""}]}'
)

# ── 条款维 ─────────────────────────────────────────────────────────────────
_INSTR_CLAUSE = (
    "你在给一份党政机关公文做**逐条款精读**。只针对下面这段原文,逐条款抽,只抽本段出现的条款,"
    "不臆测、不编造。条款序号用整数(没有显式编号就按出现顺序从 1 顺排)。\n"
    "每条款给:\n"
    "1. 事项(matter):这一条在说什么事,一句话。\n"
    "2. 指令类型(instruction_type):**只能填以下四个标签之一**,按原文措辞判,不准打分:\n"
    "   - 硬要求:有「应当/必须/不得/严禁/限X日前/予以」等强制措辞,有法定约束力。\n"
    "   - 软倡导:有「鼓励/提倡/支持/可以/原则上」等倡导措辞,无强制。\n"
    "   - 信息告知:单纯告知情况/通报数据,不要求收文方办什么。\n"
    "   - 依据陈述:「根据X」「为贯彻Y」这类陈述行文依据,本身不是要求。\n"
    "3. 责任主体(actor):这一条要谁来办(主语机关/部门);没有明确主体留空。\n"
    "4. 时限(deadline):什么时候前完成/生效/管到哪天;**抽到才填,抽不到留空,绝不编**。\n"
    "5. 依据引用(basis_ref):这一条引了哪份上位文件——抽出被引文件的**字号或标题**;没引留空。\n"
    "6. evidence:这一条里最能代表上面判定的一句原文逐字片段(原样摘录、不改写)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"clauses":[{"chapter":条款序号整数,"matter":"","instruction_type":"信息告知",'
    '"actor":"","deadline":"","basis_ref":"","evidence":""}]}'
)

_USER_MSG = "请按上面的要求抽结构。"

# 条款维除 chapter/evidence 外要保留的字段(都是字符串)。
_CLAUSE_STR_FIELDS = ("matter", "instruction_type", "actor", "deadline", "basis_ref")


def _coerce_doc_type(value: Any) -> str:
    """文种归一:必须落进 15 文种封闭集,落不进退空串(绝不自造文种)。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in DOC_TYPES else ""


def _coerce_instruction_type(value: Any) -> str:
    """指令类型归一:必须落进四标签封闭集,落不进退「信息告知」(最弱兜底,不误导用户去办)。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in INSTRUCTION_TYPES else _DEFAULT_INSTR_TYPE


def _coerce_clause(item: Any) -> dict[str, Any] | None:
    """把一条条款 dict 归一成该有的字段;chapter(条款序号)缺/非整数 → 丢(没序号摆不进文脉)。

    指令类型走封闭集归一(带原文撑的标签,不是分数);其余字段是字符串,缺退空串、抽不到不编。
    """
    if not isinstance(item, dict):
        return None
    ch = item.get("chapter")
    if not isinstance(ch, int):
        return None
    out: dict[str, Any] = {
        "chapter": ch,
        "evidence": str(item.get("evidence", "")).strip(),
    }
    for field in _CLAUSE_STR_FIELDS:
        v = item.get(field)
        if field == "instruction_type":
            out[field] = _coerce_instruction_type(v)
        else:
            out[field] = v.strip() if isinstance(v, str) else ""
    return out


def _make_clause_parser():  # noqa: ANN202 — 返回闭包 parse_fn 喂 mapreduce
    """造条款维的 parse_fn:strip 围栏 → json.loads → 抠首个 obj → 截断抢救 → 归一去重。

    结构同 ``chapter_spine._make_parser``,只把数组键从 ``"chapters"`` 换成 ``"clauses"``、
    归一走 ``_coerce_clause``。
    """

    def _coerce_list(raw: Any) -> list[dict[str, Any]]:
        if not isinstance(raw, list):
            return []
        out: list[dict[str, Any]] = []
        seen: set[int] = set()
        for it in raw:
            c = _coerce_clause(it)
            if c is None or c["chapter"] in seen:
                continue
            seen.add(c["chapter"])
            out.append(c)
        return out

    def _parse(text: str) -> list[dict[str, Any]] | None:
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
            clauses = _coerce_list(obj.get("clauses"))
            if clauses:
                return clauses
        salvaged = _coerce_list(salvage_closed_objects(candidate, '"clauses"') or [])
        if salvaged:
            logger.warning("doc_spine[clause]: 主解析失败,从截断抢救到 %d 条款", len(salvaged))
            return salvaged
        return None

    return _parse


def _parse_head(text: str) -> dict[str, dict[str, str]] | None:
    """解析头要素维一次抽取 ``{elements:[{field,value,evidence}]}`` → ``{field:{value,evidence}}``。

    三层兜底同条款维。只收 field 落进 ``_HEAD_FIELDS`` 的(模型自造的字段名丢掉);value/evidence
    都 coerce 成字符串。文种额外过封闭集归一。解析不出返 None。
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
    elements: Any = None
    if isinstance(obj, dict):
        elements = obj.get("elements")
    if not isinstance(elements, list):
        salvaged = salvage_closed_objects(candidate, '"elements"')
        if salvaged:
            logger.warning("doc_spine[head]: 主解析失败,从截断抢救头要素")
            elements = salvaged
        else:
            return None
    out: dict[str, dict[str, str]] = {}
    for el in elements:
        if not isinstance(el, dict):
            continue
        field = el.get("field")
        if field not in _HEAD_FIELDS:
            continue
        value = el.get("value")
        value = value.strip() if isinstance(value, str) else ""
        if field == "文种":
            value = _coerce_doc_type(value)
        out[field] = {
            "value": value,
            "evidence": str(el.get("evidence", "")).strip(),
        }
    return out


def _build_head_elements(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int,
    cache_enabled: bool,
) -> list[dict[str, Any]]:
    """头要素维:一次抽取整份公文的头要素 → 每要素 evidence 过 verify_citations 附 verified。

    抽不到 / 解析不出 / 调用失败 → 返**全要素留空待核**的骨架(verified=False),不编。
    每要素结构:``{field, value, evidence, verified, match_score}``。文种已过封闭集归一。
    """
    system = build_longctx_system(full_text, _INSTR_HEAD)
    parsed: dict[str, dict[str, str]] | None = None
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=system,
            tools=[],
            messages=[{"role": "user", "content": _USER_MSG}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        parsed = _parse_head(llm_client.extract_final_text(resp))
    except Exception as exc:  # noqa: BLE001 — 头要素抽取失败不拖垮整体,全留空待核
        logger.warning("doc_spine[head]: 抽取抛 %s: %s;头要素全留空待核", type(exc).__name__, exc)
        parsed = None

    parsed = parsed or {}
    elements: list[dict[str, Any]] = []
    for field in _HEAD_FIELDS:  # 按固定顺序产出全部要素(没抽到的也出一条空待核)
        cell = parsed.get(field) or {}
        elements.append({
            "field": field,
            "value": cell.get("value", ""),
            "evidence": cell.get("evidence", ""),
            "verified": False,
            "match_score": 0.0,
        })

    # 每要素 evidence 过 verify_citations:核不过(含 evidence 空)→ verified=False 标待核。
    # 证据表除了 chunks,再补一条整份原文兜底——公布头(国务院令第722号 / 总理李克强 / 成文
    # 日期)在「第一章」之前,会被分块层当章前噪声丢掉、不进任何 chunk,光拿 chunks 当证据表
    # 这些公布头要素永远核不过。整份原文是这份公文的真原文,拿它兜底锚定不违背 evidence-first。
    evidence_map = build_evidence_map(chunks)
    if full_text.strip():
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": full_text}
    citations = [{"snippet": el["evidence"]} for el in elements]
    verify_citations(citations, evidence_map)
    for el, vc in zip(elements, citations, strict=True):
        el["verified"] = bool(vc.get("verified", False))
        el["match_score"] = vc.get("match_score", 0.0)
    return elements


def _verify_clause_evidence(
    records: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> None:
    """逐条款给 evidence 过 verify_citations 附 verified/match_score——**但绝不动条款序号**。

    这是公文条款维和章脉决定性的不同(722 条款只剩个位数的根因):

    章脉的 ``_correct_by_evidence`` 会拿命中 chunk 的真**章**号去覆盖记录的 chapter——这是为
    多卷书每卷标题重数那个场景设计的。可公文里 chunk 的 ``chapter`` 是「第一章 总则」这种**章节**
    号(722 条例 ~7 章),而条款维的 ``chapter`` 是「第一条…第N条」的**条款**序号(几十条)。拿章节
    号去覆盖条款号,会把同一章里的几十条全压成同一个号,``merge_by_chapter`` 再一去重 → 几十条
    只剩个位数。所以条款维这里只核证据、不覆盖序号——条款序号由 ``_renumber_clauses`` 跨段全局
    顺排,保住每一条。
    """
    evidence = build_evidence_map(chunks)
    citations = [{"snippet": r.get("evidence", "")} for r in records]
    verify_citations(citations, evidence)
    for rec, vc in zip(records, citations, strict=True):
        rec["verified"] = bool(vc.get("verified", False))
        rec["match_score"] = vc.get("match_score", 0.0)


def _renumber_clauses(seg_outs: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    """跨段把条款拍平 + 按出现顺序全局重排序号(1…N),压平段内重复的局部序号。

    每段都从「第 1 条」起自己数(map 引擎按段独立抽),跨段会撞号。公文条款是单文件里一条线、
    天然 disjoint 又有序,所以合并就是**按段序拼接**(段按章节序排 → 拼出来就是正文顺序)再
    全局顺排序号——不靠模型自报的段内号去重(那会把后段的「第 1 条」当成前段第 1 条丢掉,正是
    旧路把几十条压成个位数的另一半原因)。

    去重只去**整条 evidence 完全相同**的(同一条款被相邻段都抽到,如跨段边界);序号不同但内容
    不同的条款全保留。重排后 ``chapter`` = 全局条款序号(1 起)。
    """
    flat: list[dict[str, Any]] = []
    seen_ev: set[str] = set()
    for seg in seg_outs:
        # 段内按模型自报序号排稳,保正文顺序(map 引擎不保证段内已排序)。
        seg_sorted = sorted(
            seg, key=lambda c: c["chapter"] if isinstance(c.get("chapter"), int) else 0
        )
        for cl in seg_sorted:
            ev = str(cl.get("evidence", "")).strip()
            # evidence 空的也保留(不是每条都有逐字证据);非空且整条重复才去。
            if ev and ev in seen_ev:
                continue
            if ev:
                seen_ev.add(ev)
            flat.append(cl)
    for i, cl in enumerate(flat, start=1):
        cl["chapter"] = i
    return flat


def _make_clause_continue_fn(
    *,
    llm_client: Any,
    model: str,
    max_tokens: int,
    cache_enabled: bool,
):  # noqa: ANN202 — 返回闭包 continue_fn 喂 run_segments
    """造条款维的续抽回调:某段被 max_tokens 截断只抽回部分条款时,接着把剩下的条款补抽回来。

    **跟章脉的 ``_make_continue_fn`` 决定性不同**:章脉按「段覆盖几个章」算还差几条(章数 ==
    chunk 真 chapter 数,可数)。公文一个 chunk 章节里塞十几条条款,「段覆盖几章」根本不等于
    「该抽几条」,数不出差几条。所以这里不靠数量判,改靠**信号**:模型上轮被截断(finish_reason=
    length)就再发一轮「接着上次没抽完的往下抽」,直到某轮没补到新条款 / 也没再被截断 / 补满
    ``_DOC_CLAUSE_CONTINUE_MAX_ROUNDS`` 轮。用 doc_spine 自己的条款 parser(``"clauses"`` 键),
    不是章脉的 ``"chapters"`` parser——这点是另一处必须自己造而不能复用的原因。
    """
    from bookscope.agent._internal.loop_shared import read_openai_finish_reason

    parse = _make_clause_parser()

    def _continue(
        seg: list[dict[str, Any]], partial: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        seg_text = "".join(str(c.get("text", "")) for c in seg)
        extra: list[dict[str, Any]] = []
        got = len(partial)
        for _round in range(_DOC_CLAUSE_CONTINUE_MAX_ROUNDS):
            cont_instr = (
                _INSTR_CLAUSE
                + f"\n\n注意:你上次已经抽完了本段前 {got} 条条款,被长度截断了。"
                + "现在请**只抽你还没抽的、本段剩下的条款**,接着往下抽,别重复前面抽过的条款。"
            )
            system = build_longctx_system(seg_text, cont_instr)
            try:
                resp = invoke_client_cached(
                    llm_client,
                    model=model,
                    system=system,
                    tools=[],
                    messages=[{"role": "user", "content": _USER_MSG}],
                    max_tokens=max_tokens,
                    cache_enabled=cache_enabled,
                )
            except Exception as exc:  # noqa: BLE001 — 续抽调用失败就停,保已有的
                logger.warning("doc_spine[clause]: 续抽调用抛 %s,停止续抽", type(exc).__name__)
                break
            truncated = read_openai_finish_reason(resp) == "length"
            try:
                more = parse(llm_client.extract_final_text(resp)) or []
            except Exception:  # noqa: BLE001
                more = []
            if not more:  # 这轮没补到 → 再补也大概率空,停
                break
            extra.extend(more)
            got += len(more)
            if not truncated:  # 这轮抽完了没再被截断 → 补齐了,停
                break
        if extra:
            logger.warning("doc_spine[clause]: 段截断续抽补回 %d 条条款", len(extra))
        return extra

    return _continue


def build_doc_spine(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    max_tokens: int = DEFAULT_DOC_SPINE_MAX_TOKENS,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    max_workers: int | None = None,
    cache_enabled: bool = True,
) -> dict[str, Any]:
    """一份公文精读一次,出带证据的「文脉」(头要素维 + 条款维)。

    复用章脉骨架,但条款维**不能整套照搬** ``mapreduce_per_chapter``:

    - **条款维**走底层 ``run_segments``(分段 + 并发 + 截断兜底)+ 自接两步:逐段证据核验
      (``_verify_clause_evidence``,只核不动序号)、跨段全局重排序号(``_renumber_clauses``)。
      为什么不套 ``mapreduce_per_chapter``:它合并前会跑 ``_correct_by_evidence`` 拿命中 chunk 的
      真**章节**号覆盖记录序号,再按它 merge 去重——公文 chunk 的 chapter 是「第一章 总则」(722
      ~7 章),条款维要的是「第一条…第N条」(几十条),拿章节号覆盖条款号会把同章几十条压成一个
      号、去重后只剩个位数(722 只抽到 ~2 条的根因)。截断丢条款靠 ``run_segments`` 自带的拆小重抽
      + 条款版续抽(``_make_clause_continue_fn``)两道兜底。
    - **头要素维**一次抽整份头要素,每要素 evidence 过 ``verify_citations``。

    Args:
        chunks: 这份公文的 chunk 列表,每条含 ``chunk_id`` / ``chapter``(=章节号,非条款号) /
            ``text``。条款序号由条款维抽取后全局顺排,不取 chunk 的 chapter。
        llm_client: duck-typed LLM client(同 AgentLoop / 章脉)。
        model: 模型名。
        full_text: 这份公文的**完整原文**(含公布头)。传了头要素维就用它抽取 + 兜底锚定——
            公布头(国务院令第722号 / 总理李克强 / 成文日期)在「第一章」之前,会被分块层当章前
            噪声丢掉、不进任何 chunk,只拿 chunks 拼全文这些公布头要素就抽不到也核不过。不传则
            退回 ``chunks`` 拼接(向后兼容,标准「X发〔年〕号 + 通知」格式头要素都在正文,够用)。
        max_tokens: 条款维单段 + 头要素维一次抽取的 max_tokens。
        char_budget / max_workers: 透传给 ``run_segments`` 的分段预算 / 并发数。
        cache_enabled: 是否走 L2 缓存(默认开,同份公文重看命中)。

    Returns:
        ``{
            "schema_version": "v1",
            "head": [{field, value, evidence, verified, match_score}],
            "clauses": [{chapter, matter, instruction_type, actor, deadline, basis_ref,
                         evidence, verified, match_score}],
        }``。
        头要素维抽不到的要素出一条空待核记录(verified=False),绝不编。条款维空 → ``clauses: []``。
    """
    # 头要素维优先用传入的完整原文(含公布头);没传退回 chunk 拼接(向后兼容)。
    head_full_text = full_text if (full_text and full_text.strip()) else "".join(
        str(c.get("text", "")) for c in chunks
    )

    head = _build_head_elements(
        full_text=head_full_text,
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        cache_enabled=cache_enabled,
    )

    # 条款维:重型逐条款(每条带 evidence + 多字段)同章脉重维,收窄章闸 + 开续抽防截断丢条款。
    #
    # **不能套 ``mapreduce_per_chapter``**:那台机器为「书的章」设计,合并前会跑
    # ``_correct_by_evidence`` 拿命中 chunk 的真**章节**号覆盖记录序号,再按它 ``merge_by_chapter``
    # 去重。公文 chunk 的 chapter 是「第一章 总则」这种章节(722 ~7 章),条款维要的是「第一条…
    # 第N条」(几十条)——拿章节号覆盖条款号会把同章几十条压成一个号、去重后只剩个位数(722 只
    # 抽到 ~2 条的根因)。所以这里直接用底层 ``run_segments`` 分段并发抽,自己接:
    #   1. 每段证据核验(``_verify_clause_evidence``,只核不覆盖序号);
    #   2. 跨段全局重排序号(``_renumber_clauses``,按正文顺序顺排 1…N,压平段内撞号 + 去整条重复)。
    # 截断丢条款仍靠 ``run_segments`` 自带的拆小重抽 + 续抽(continue_fn)两道兜底。
    continue_fn = _make_clause_continue_fn(
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        cache_enabled=cache_enabled,
    )
    seg_outs = run_segments(
        chunks=chunks,
        instruction=_INSTR_CLAUSE,
        user_msg=_USER_MSG,
        parse_fn=_make_clause_parser(),
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_chapters=_DOC_CLAUSE_MAX_CHAPTERS,
        max_workers=max_workers,
        cache_enabled=cache_enabled,
        continue_fn=continue_fn,
    )
    for seg in seg_outs:
        _verify_clause_evidence(seg, chunks)
    clauses = _renumber_clauses(seg_outs)

    return {
        "schema_version": DOC_SPINE_SCHEMA_VERSION,
        "head": head,
        "clauses": clauses,
    }


__all__ = [
    "DOC_SPINE_SCHEMA_VERSION",
    "DOC_TYPES",
    "INSTRUCTION_TYPES",
    "build_doc_spine",
]
