"""公文「利害与风向」研判(1.6.1·机会/风险/信号 + 含金量,按角色)——同一份公文,带上身份
重看一遍,研判出**对这角色的机会、暴露的风险、透出的政策风向**,并评每条的含金量、给一句带立
场的建议。

**它解决什么**:读公文的真正用事(JTBD)不是「读懂字面」(那是大白话翻译干的),而是「这份文件对
我藏着什么机会、什么风险,透出什么风向」。「跟我相关」回答的是「这份公文里哪几条落到你头上、是
义务还是利好」(条款清单);本功能更进一步——研判你**可争取的红利**(不是现成便利,是试点可申请、
扶持方向早卡位这种)、你的**暴露面/代价**(门槛抬高把你挤出、不办的代价、监管收紧),以及这文件
透出的**政策方向**(行业要松还是要紧)。同一份公文,个体户/投资人/某局看到的利害与风向不同——
独有维度 = 带身份的利害研判 + 政策风向。

**两种证据契约(evidence-first 升级,1.6.1 命门)**:

- **机会 / 风险 = 证据层**:每条锚原文逐字片段、过 ``verify_citations``、核得过盖「鉴」印。核不过
  的丢——绝不留编的。
- **信号 = 评估层**:研判出的政策方向是**推断**,直接撞 evidence-first;情报分析那套(证据↔评估
  分离,Heuer/Kent 估计性措辞)正是「如何在不污染事实的前提下负责任地输出推断」。所以信号**绝不
  盖鉴印、不过 verified**,但每条必须列出**引发它的原文基础**(basis)+ **置信度**(高/中/低)。
  死守:**没有原文基础的信号一条都不输出**——连推断都要有据,basis 里的原文片段还要校验确在文里。

**含金量(substance,第二个命门)**:公文条款分轻重缓急——有的真金白银,有的是空头支票(倡导性,
十年二十年甚至永远不兑现)。判据 = 钱学森控制论**开环/闭环**:看这条有没有把控制回路闭上。

- **闭环 = 真金白银**:硬约束词(应当/必须/不得)+ 具体数字(金额/比例/门槛)+ 明确时限(X日前)
  + 明确责任主体(X部门负责)+ 配套(考核/问责/罚则/财政资金)。指令→主体→时限→反馈,不办有代价,
  会兑现。
- **开环 = 空头倡导**:倡导词(鼓励/支持/探索/推动/逐步/适时)+ 无数字 + 无时限或「条件成熟时/
  逐步」+ 无责任主体(有关方面/各地)+ 无罚则无资金。只发号召、无反馈回路,自然衰减、漂没。

含金量分三档(真金白银/有条件兑现/空头倡导),每条机会/风险都要标 + 给 ``substance_reason``
(凭哪些 marker 判的,锚原文)+ ``horizon``(时效:近/远/无期)。机会/风险按含金量排序
(真金白银在前)= 轻重缓急。最后给一句 ``recommendation``——系统的 take,**带立场不中立罗列**
(哪些真金白银值得马上动、哪些空头别当真)。

**怎么做(走整本结构化功能那套,一次扫全份)**:跟 ``redhead_hard_facts`` 同款——机会/风险/信号
是横切全文的研判,不绑定单条条款,所以整份公文 + 角色进长上下文(``build_longctx_system``
book-first 拼,公文也吃前缀缓存),一次出三段 JSON;机会/风险逐条过 ``verify_citations``(核不过
的丢)、信号逐条校 basis 原文确在文里;三守卫焊死(给够 token 防 reasoning 吃光 / cache_enabled
透传 / parse 健壮带截断抢救)。

铁律:**只 import 现有 helper,一行不改任何别的模块**;不碰端点(scanned/book_session_id/trace
由端点层加,本模块只管 ``{role, opportunities, risks, signals, recommendation}`` 四块)。
evidence-first:机会/风险锚原文核不过就丢、信号无 basis 就丢,绝不编原文没有的;role 为空直接返空
结构、不跑 LLM。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.redhead_codebook import (
    SUBSTANCE_LEVELS,
    codebook_block,
    coerce_substance,
    substance_rank,
)
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

STAKES_SCHEMA_VERSION = "v1"
"""利害与风向记录结构版本——升级要让这层重算(不影响别的功能)。"""

DEFAULT_STAKES_MAX_TOKENS = 3000
"""一次扫全份出三段(机会/风险/信号)的 max_tokens。

这功能整份公文进上下文,且要一次吐三段带 substance_reason / basis 的结构化 JSON——比
逐条款功能(``redhead_relevance``/``redhead_plain`` 各 1200)输出长得多。deepseek-v4-flash
把 reasoning_content 算进 max_tokens(见 reference_reasoning_model_token_budget),全文进上下文
后会先吐一大段 reasoning,预算太小会被吃光导致 content 空、``finish_reason=length``、三段全抽空。
3000 装得下三段研判还给 reasoning 留头;真被截断也有 ``extract_first_json_object`` 兜底。"""

# 含金量三档 / 归一 / 排序权重统一取自 redhead_codebook(单一真相源,见 codebook 文档)——
# 本模块不各定一套,免得 codebook 演进时 stakes 漂移(原本地重抄已删)。
# codebook_block() 渲染的措辞刻度判据(约束力阶梯/留口子/搁置/含金量 rubric)拼进 system prompt。

# 时效三档(封闭集)。落不进退「无期」(开环号召的典型时效——不了了之)。
HORIZONS: tuple[str, ...] = ("近", "远", "无期")
_DEFAULT_HORIZON = "无期"

# 信号置信度三档(封闭集)。落不进退「低」(最保守,不替推断拔高可信度)。
CONFIDENCE_LEVELS: tuple[str, ...] = ("高", "中", "低")
_DEFAULT_CONFIDENCE = "低"

# 一次扫全份出三段的指令。死守:机会/风险锚原文 + 评含金量(开环/闭环判据写进 prompt)、
# 信号标研判 + 引原文基础 + 置信度、绝不编原文没有的、荒谬角色老实说判不出。
_INSTR_STAKES = (
    "你在帮一个**带着身份**读党政机关公文(红头文件)的人,研判这份文件**对他这个角色**的"
    "利害与风向。用户身份在「=== 任务要求 ===」之后给出。你要研判三件事:\n"
    "\n"
    "【一、机会(opportunities)】这角色**可以去争取/早布局的红利**——不是现成就有的便利,而是"
    "试点资格可申请、扶持方向可早卡位、政策窗口可抢这类。每条给:\n"
    "  - what:这个机会是什么(短、准)。\n"
    "  - why:对**这个角色**为什么是机会(一句话,直接称呼「你」)。\n"
    "  - action:他可以采取的具体动作(去申请什么/早布局什么)。\n"
    "  - evidence:原文里**撑这条的逐字片段**(原样摘录、不改写)。\n"
    "\n"
    "【二、风险(risks)】这角色的**暴露面/代价**——门槛抬高把他挤出、新增的合规义务、不办的代价、"
    "监管收紧带来的压力。每条给:\n"
    "  - what:这个风险是什么(短、准)。\n"
    "  - cost:对他的代价/后果是什么(一句话)。\n"
    "  - evidence:原文里**撑这条的逐字片段**(原样摘录、不改写)。\n"
    "\n"
    "【含金量(substance)——机会和风险每条都必须评】"
    "公文条款分轻重缓急:有的真金白银会兑现,有的是空头支票。判据(开环/闭环)见下文「公文措辞刻度」"
    "块,按那把尺判,不要自己另定一套。\n"
    "  每条机会/风险再给:\n"
    "  - substance:只能填「真金白银」「有条件兑现」「空头倡导」之一。\n"
    "  - substance_reason:凭原文里**哪些 marker** 判成这档(点出约束词/数字/时限/主体/罚则的"
    "有无,锚原文,别空说)。\n"
    "  - horizon:时效,只能填「近」(短期就见效)「远」(要好几年)「无期」(开环号召、大概率漂没)。\n"
    "\n"
    "【三、信号(signals)】从全文研判这文件透出的**政策方向**(这行业要松还是要紧、往哪走)。"
    "这是你的**推断**,不是文件明说的事实,所以:\n"
    "  - direction:你研判出的政策方向(一句话)。\n"
    "  - basis:引发这个研判的**原文片段列表**(几条逐字原文,原样摘录)——没有原文基础的研判"
    "**一条都别写**,哪怕你觉得很可能。\n"
    "  - confidence:这个研判的把握,只能填「高」「中」「低」。\n"
    "\n"
    "死守铁律:\n"
    "①机会/风险的 evidence、信号的 basis,都必须是原文里**真有**的逐字片段——原文没写的承诺/"
    "数字/方向,一个都别编、别猜、别推。找不到原文撑的那条,宁可不写。\n"
    "②只研判**对这个角色**有意义的;跟这角色八竿子打不着的别硬凑。\n"
    "③如果用户给的身份是**荒谬的/根本读不出利害**的(比如「一块石头」「一阵风」),就老实把三段都"
    "留空(opportunities/risks/signals 都给 []),**别硬编**去附和这个假前提。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏),形如:\n"
    '{"opportunities":[{"what":"","why":"","action":"","substance":"真金白银",'
    '"substance_reason":"","horizon":"近","evidence":""}],'
    '"risks":[{"what":"","cost":"","substance":"空头倡导","substance_reason":"",'
    '"horizon":"无期","evidence":""}],'
    '"signals":[{"direction":"","basis":["",""],"confidence":"中"}]}'
)

_USER_MSG = "请按上面的要求,研判这份公文对该角色的机会、风险、信号,并评含金量,输出 JSON。"


def _coerce_horizon(value: Any) -> str:
    """时效归一:必须落进三档封闭集,落不进退「无期」。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in HORIZONS else _DEFAULT_HORIZON


def _coerce_confidence(value: Any) -> str:
    """置信度归一:必须落进三档封闭集,落不进退「低」(最保守)。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in CONFIDENCE_LEVELS else _DEFAULT_CONFIDENCE


def _coerce_opportunity(item: Any) -> dict[str, Any] | None:
    """归一一条机会;what 或 evidence 空 → 丢(没说法 / 没原文撑的不进证据层)。

    含金量类字段走封闭集兜底;evidence 留着进核验那步(核不过会被丢)。
    """
    if not isinstance(item, dict):
        return None
    what = str(item.get("what", "")).strip()
    evidence = str(item.get("evidence", "")).strip()
    if not what or not evidence:
        return None
    return {
        "what": what,
        "why": str(item.get("why", "")).strip(),
        "action": str(item.get("action", "")).strip(),
        "substance": coerce_substance(item.get("substance")),
        "substance_reason": str(item.get("substance_reason", "")).strip(),
        "horizon": _coerce_horizon(item.get("horizon")),
        "evidence": evidence,
    }


def _coerce_risk(item: Any) -> dict[str, Any] | None:
    """归一一条风险;what 或 evidence 空 → 丢。风险用 ``cost`` 不是 ``why``(代价/后果)。"""
    if not isinstance(item, dict):
        return None
    what = str(item.get("what", "")).strip()
    evidence = str(item.get("evidence", "")).strip()
    if not what or not evidence:
        return None
    return {
        "what": what,
        "cost": str(item.get("cost", "")).strip(),
        "substance": coerce_substance(item.get("substance")),
        "substance_reason": str(item.get("substance_reason", "")).strip(),
        "horizon": _coerce_horizon(item.get("horizon")),
        "evidence": evidence,
    }


def _coerce_signal(item: Any) -> dict[str, Any] | None:
    """归一一条信号;direction 空 或 basis 没一条原文 → 丢(无据的推断不输出)。

    basis 是「引发这个研判的原文片段列表」——评估层,但基础必须可核(原文确在文里这步在上层做)。
    这里只保证结构:basis 收成非空字符串的 list,空了说明无据、丢。
    """
    if not isinstance(item, dict):
        return None
    direction = str(item.get("direction", "")).strip()
    raw_basis = item.get("basis")
    basis: list[str] = []
    if isinstance(raw_basis, list):
        basis = [str(b).strip() for b in raw_basis if str(b).strip()]
    elif isinstance(raw_basis, str) and raw_basis.strip():
        # 模型偶尔把 basis 写成单个字符串而非 list,宽松收一下。
        basis = [raw_basis.strip()]
    if not direction or not basis:
        return None
    return {
        "direction": direction,
        "basis": basis,
        "confidence": _coerce_confidence(item.get("confidence")),
    }


def _parse_stakes(text: str) -> dict[str, list[dict[str, Any]]]:
    """解析 ``{opportunities, risks, signals}`` → 三段归一后的列表。

    两层兜底:strip 围栏 → json.loads → 抠首个 obj。三段各自走对应 coerce(丢残缺条)。
    解析不出 / 不是 dict → 三段全空。
    """
    raw = (text or "").strip()
    empty: dict[str, list[dict[str, Any]]] = {
        "opportunities": [],
        "risks": [],
        "signals": [],
    }
    if not raw:
        return empty
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
    if not isinstance(obj, dict):
        return empty

    def _coerce_list(key: str, coerce) -> list[dict[str, Any]]:  # noqa: ANN001
        raw_list = obj.get(key)
        if not isinstance(raw_list, list):
            return []
        out: list[dict[str, Any]] = []
        for it in raw_list:
            coerced = coerce(it)
            if coerced is not None:
                out.append(coerced)
        return out

    return {
        "opportunities": _coerce_list("opportunities", _coerce_opportunity),
        "risks": _coerce_list("risks", _coerce_risk),
        "signals": _coerce_list("signals", _coerce_signal),
    }


def _verify_evidence_items(
    items: list[dict[str, Any]], evidence_map: dict[str, dict]
) -> list[dict[str, Any]]:
    """机会/风险逐条过 ``verify_citations``,附 ``verified``/``match_score``,**核不过的丢**。

    证据层死守:evidence 在原文里核得到才留(盖鉴印);核不过(含 evidence 空)说明可能是编的,
    直接丢——绝不留编的原文。返只含 verified=True 的条目。
    """
    if not items:
        return []
    citations = [{"snippet": it["evidence"]} for it in items]
    verify_citations(citations, evidence_map)
    kept: list[dict[str, Any]] = []
    for it, vc in zip(items, citations, strict=True):
        if not bool(vc.get("verified", False)):
            continue  # 核不过的丢
        it["verified"] = True
        it["match_score"] = vc.get("match_score", 0.0)
        kept.append(it)
    return kept


def _filter_signals_by_basis(
    signals: list[dict[str, Any]], evidence_map: dict[str, dict]
) -> list[dict[str, Any]]:
    """信号逐条校 basis 原文确在文里——评估层,**不盖 verified**,但基础必须可核。

    信号是推断、不过 verified(评估层不冒充事实);但「没有原文基础的信号一条都不输出」是死守。
    所以这里只用 ``verify_citations`` 校 basis 里的每条原文片段是否真在文里:**一条 basis 都核
    不到的信号丢**(无据);留下的信号 basis 只保留核得到的片段(把编的片段剔掉),结论仍标推断。
    """
    if not signals:
        return []
    kept: list[dict[str, Any]] = []
    for sig in signals:
        basis = sig.get("basis") or []
        citations = [{"snippet": b} for b in basis]
        verify_citations(citations, evidence_map)
        grounded = [
            b for b, vc in zip(basis, citations, strict=True)
            if bool(vc.get("verified", False))
        ]
        if not grounded:
            continue  # 一条原文基础都核不到 → 无据的推断,丢
        sig["basis"] = grounded  # 只留核得到的原文片段(剔掉编的)
        kept.append(sig)
    return kept


def stakes_from_doc(
    *,
    chunks: list[dict[str, Any]],
    role: str,
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    max_tokens: int = DEFAULT_STAKES_MAX_TOKENS,
    max_workers: int | None = None,  # noqa: ARG001 — 一次扫全份不分段,留参对齐兄弟模块签名
    cache_enabled: bool = True,
) -> dict[str, Any]:
    """带角色研判一份公文的利害与风向——一次扫全份出三段 → 机会/风险核验 + 信号校基础。

    走整本结构化功能那套(同 ``redhead_hard_facts`` 一次扫全份,因为机会/风险/信号是横切全文的
    研判、不绑单条条款):整份公文 + 角色进 ``build_longctx_system`` book-first 上下文(吃前缀
    缓存),一次 LLM 出三段 JSON;机会/风险逐条过 ``verify_citations`` 核不过的丢(证据层、盖鉴印),
    信号逐条校 basis 原文确在文里(评估层、不盖 verified、无据丢)。三守卫:给够 token / cache_enabled
    透传 / parse 健壮带兜底。

    Args:
        chunks: 这份公文的 chunk 列表(每条含 ``chunk_id`` / ``chapter`` / ``text``)。
        role: 用户报的身份(自由文本,如「个体工商户」「投资人」「某市市场监管局」)。
            空身份 → 直接返空结构(没身份没法研判利害),不跑 LLM。
        llm_client: duck-typed LLM client(同 AgentLoop / 其它公文功能)。
        model: 模型名。
        full_text: 这份公文的**完整原文**(含公布头)。传了就用它进上下文 + 当核验兜底锚
            (公布头在「第一章」前会被分块层丢掉);没传退回 ``chunks`` 拼接(向后兼容)。
        max_tokens: 一次扫全份出三段的 max_tokens。整份原文进上下文后 reasoning 也吃这预算
            (deepseek-v4-flash),太小会被吃光导致三段抽空——默认 3000,比逐条款功能给得多。
        max_workers: 占位,不生效(一次扫全份不分段),留参对齐兄弟模块签名。
        cache_enabled: 是否走 L2 缓存(默认开)。

    Returns:
        ``{
            "schema_version": "v1",
            "role": 回显用户身份,
            "opportunities": [{what, why, action, substance, substance_reason, horizon,
                               evidence, verified, match_score}],  # 证据层,按 substance 排序
            "risks": [{what, cost, substance, substance_reason, horizon,
                       evidence, verified, match_score}],          # 证据层,按 substance 排序
            "signals": [{direction, basis(原文片段列表), confidence}],  # 评估层,不盖 verified
            "recommendation": 系统一句话建议(带立场),
        }``。
        机会/风险只含核验过的(核不过的丢);按含金量排(真金白银 > 有条件兑现 > 空头倡导)。
        信号只含 basis 有原文基础的。身份空 / 没原文 / 没研判出 → 三段空 + recommendation 空。
        ``scanned`` / ``book_session_id`` / ``trace`` 由端点层加,本模块不管。
    """
    role = (role or "").strip()
    if not role:
        return {
            "schema_version": STAKES_SCHEMA_VERSION,
            "role": "",
            "opportunities": [],
            "risks": [],
            "signals": [],
            "recommendation": "",
        }

    # 一次扫全份:整份原文进上下文(优先完整原文,含公布头;没传退 chunk 拼接)。
    source_text = (
        full_text
        if (full_text and full_text.strip())
        else "".join(str(c.get("text", "")) for c in chunks)
    )
    if not source_text.strip():
        return {
            "schema_version": STAKES_SCHEMA_VERSION,
            "role": role,
            "opportunities": [],
            "risks": [],
            "signals": [],
            "recommendation": "",
        }

    # 角色拼进指令尾段(变化段,落在 book 之后,不破前缀缓存:同份公文不同角色共用前缀)。
    # codebook_block() 是固定判据块,拼在固定指令之后、变化 role 之前——仍是稳定前缀。
    instruction = _INSTR_STAKES + "\n\n" + codebook_block() + f"\n\n用户身份:{role}"
    system = build_longctx_system(source_text, instruction)

    parsed: dict[str, list[dict[str, Any]]] = {
        "opportunities": [],
        "risks": [],
        "signals": [],
    }
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
        parsed = _parse_stakes(llm_client.extract_final_text(resp))
    except Exception as exc:  # noqa: BLE001 — 研判失败不抛,返空结构(前端优雅退场)
        logger.warning(
            "redhead_stakes: 研判抛 %s: %s;返空结构", type(exc).__name__, exc
        )

    # 证据登记表:chunks + 整份原文兜底锚(公布头在「第一章」前会被分块层丢掉,光拿 chunks
    # 当证据表那类原文永远核不过)。机会/风险核验、信号校 basis 都用这同一张表。
    evidence_map = build_evidence_map(chunks)
    if source_text.strip():
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": source_text}

    # 机会 / 风险:证据层,逐条核验,核不过的丢(绝不留编的原文)。
    opportunities = _verify_evidence_items(parsed["opportunities"], evidence_map)
    risks = _verify_evidence_items(parsed["risks"], evidence_map)

    # 按含金量排序(真金白银 > 有条件兑现 > 空头倡导)= 轻重缓急,同档保抽取顺序(stable sort)。
    opportunities.sort(key=lambda it: substance_rank(it["substance"]))
    risks.sort(key=lambda it: substance_rank(it["substance"]))

    # 信号:评估层,不盖 verified,但 basis 必须可核——无原文基础的信号丢。
    signals = _filter_signals_by_basis(parsed["signals"], evidence_map)

    recommendation = _build_recommendation(opportunities, risks)

    return {
        "schema_version": STAKES_SCHEMA_VERSION,
        "role": role,
        "opportunities": opportunities,
        "risks": risks,
        "signals": signals,
        "recommendation": recommendation,
    }


def _build_recommendation(
    opportunities: list[dict[str, Any]], risks: list[dict[str, Any]]
) -> str:
    """系统一句话建议——带立场,按含金量分轻重缓急:真金白银值得马上动、空头别当真。

    不调 LLM(再调一次既费 token 又得二次核验):直接从已核验、已按含金量排好的机会/风险里,
    挑真金白银的点名「值得动」、把空头倡导的点名「别当真」,拼一句带立场的话。没料(三段都空)
    返空串,前端优雅退场。
    """
    if not opportunities and not risks:
        return ""

    def _firsts(items: list[dict[str, Any]], level: str, n: int = 2) -> list[str]:
        return [it["what"] for it in items if it.get("substance") == level][:n]

    parts: list[str] = []

    # 真金白银的机会/风险:点名值得马上动 / 必须当真。
    hard_opps = _firsts(opportunities, "真金白银")
    hard_risks = _firsts(risks, "真金白银")
    if hard_opps:
        parts.append("「" + "、".join(hard_opps) + "」是真金白银的红利,值得马上动")
    if hard_risks:
        parts.append("「" + "、".join(hard_risks) + "」是实打实的风险,得当回事")

    # 空头倡导:点名别当真(开环号召,大概率漂没)。
    hollow = _firsts(opportunities, "空头倡导") + _firsts(risks, "空头倡导")
    if hollow:
        parts.append("「" + "、".join(hollow[:2]) + "」多半是空头倡导,别太当真")

    if not parts:
        # 全是「有条件兑现」档:没有可拍板的强信号,给个温和提示。
        return "这份文件对你这角色多是有条件兑现的内容,得看后续落实,先盯着别急动。"
    return ";".join(parts) + "。"


__all__ = [
    "CONFIDENCE_LEVELS",
    "DEFAULT_STAKES_MAX_TOKENS",
    "HORIZONS",
    "STAKES_SCHEMA_VERSION",
    "SUBSTANCE_LEVELS",
    "stakes_from_doc",
]
