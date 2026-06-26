"""公文大白话翻译(1.6 红头文件垂直·二炮)——把公文体官话翻成人话,每句白话锚回原文 + 点弦外之意。

**它解决什么**:公文体普通人看不懂(「应当于X日前予以办结」「依据上位文件精神,各相关单位
须严格落实」)。这功能把官话改写成大白话,**白话是对原文的忠实转述、不是编造**——公文比小说
好做这一点:事项 + 原文都是定死的,白话只是「换种说法说同一件事」,天然契合 evidence-first
(白话背后那句原文核得到、就盖「鉴」印)。

**两种模式**(``mode`` 参数,默认 ``clauses`` 不破坏老行为):

- ``clauses``(默认):走文脉的**条款**,逐条摘译——一条条款一句白话。要对照公文的分条结构、
  看哪条管啥时用。
- ``fulltext``(全文逐句,作者点名要的 #22):把整份公文**按句顺下来**,每句给「官话 → 白话」
  对照,不漏句。要通篇读懂、一句不落地跟着原文走时用。全文模式按字符预算分段并发顺译
  (同穷尽化分段并发的道理),别一次吃爆 token。

**懂刻度(深度,两种模式都加)**:翻译不止字面通顺——命中措辞刻度 codebook 的 marker 就点
**真实含义**(弦外之意):「原则上」→(有口子)、「研究」→(约等于不办)、「由X认定/另行规定」
→(真规则在别处/某人手里)、「逐步/适时」→(没时间表)。每条白话可带一个可选 ``nuance`` 字段
(命中 marker 才有,见 ``redhead_codebook.detect_nuances``);没命中就不加。死守 evidence-first:
nuance 只在原文里**确有**这个 marker 时才出(deterministic 串匹配,不靠 LLM 脑补隐含义)。

**它跟公文结构解读(doc_structure)的分工**:那个把一份公文拆成头要素 + 逐条款的「结构」;这个
拿同一份文脉,把官话改写成人话。同一份文脉(``get_or_build_doc_spine``)建一次,共用、秒出。

**怎么做(套现成的机器,一行不改 doc_spine / cross_doc)**:

- **clauses**:走 ``get_or_build_doc_spine`` 拿条款 → 逐条并发改写(``_rewrite_one``,只喂这一条
  的事项 + 原文)→ 白话锚回**原条款逐字原文**过 ``verify_citations`` → 命中 marker 挂 nuance。
- **fulltext**:触发/复用文脉缓存(同份秒出)→ 整份原文按句切段、并发逐段顺译(每段吐一串
  ``{原文, 白话}`` 句对)→ 每句的**原文**过 ``verify_citations`` 核得到盖鉴印 → 命中 marker
  挂 nuance。三守卫焊死(给够 token 防 reasoning 吃光 / cache_enabled 透传 / parse 健壮带截断
  抢救)。

铁律:**只 import 现有 helper + codebook 公共件,一行不改 ``doc_spine`` / ``cross_doc``**;不碰
``agent.py`` 端点(端点该返的结构写在 ``plain_language_from_spine`` 的 docstring 里给主 Claude
接线)。
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from bookscope.agent._internal.doc_spine_cache import get_or_build_doc_spine
from bookscope.agent._internal.exhaustive import resolve_workers
from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent._internal.loop_shared import read_openai_finish_reason
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.redhead_codebook import codebook_block, detect_nuances
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

PlainMode = Literal["clauses", "fulltext"]
"""大白话两种模式:``clauses`` 逐条款摘译(默认,向后兼容);``fulltext`` 全文逐句顺译。"""

PLAIN_SCHEMA_VERSION = "v2"
"""大白话记录结构版本。v2 = 每条可带 ``nuance``(命中措辞刻度才有,点弦外之意)+ 新增全文
逐句模式(fulltext)。升级让从文脉派生的这层重算(文脉缓存不受影响,只是这层重跑)。"""

DEFAULT_PLAIN_MAX_TOKENS = 1200
"""逐条款改写单条的 max_tokens。一条白话就一两句话,1200 留足 reasoning 头还绰绰有余
(deepseek-v4-flash 把 reasoning_content 算进 max_tokens,
见 reference_reasoning_model_token_budget)。"""

DEFAULT_FULLTEXT_MAX_TOKENS = 8000
"""全文逐句模式单段的 max_tokens。

全文模式一段要吐**一串** ``{原文, 白话}`` 句对(输出 ∝ 段里句数),比逐条款单条(一句白话)
长得多;且整段进上下文后 deepseek-v4-flash 先吐一大段 reasoning、也算进 max_tokens(见
reference_reasoning_model_token_budget)。对齐 ``redhead_hard_facts`` / ``doc_spine`` 同样
"输出长 + 全文进上下文"那档的 8000——装得下一段几十句的对照,还给 reasoning 留头;真被截断有
``salvage_closed_objects`` 抢救兜底。"""

DEFAULT_FULLTEXT_CHAR_BUDGET = 12000
"""全文逐句分段的每段字符预算。

分段是为了"别一次吃爆 token":每段原文越短,这段要顺译的句数越少、输出越不容易顶爆
``DEFAULT_FULLTEXT_MAX_TOKENS``。12000 字一段约几十句,对照输出(每句原文 + 白话约 2x)
塞进 8000 token 还有 reasoning 余量。比穷尽化的 40000 小——那个一段只抽每章一条(输出轻),
这个一段每句都要翻(输出重),所以段要切得更碎。"""

# 全文逐句:中文句末标点(含右引号/书名号收尾的情形),按句切段用。
_SENTENCE_END_RE = re.compile(r"(?<=[。!?；…」』】）\n])")

# 逐条改写的指令——不进上下文喂全文,只把这一条的「事项 + 原文」给模型,要它改写成大白话。
# 死守三条:只转述不增减、不编原文没有的承诺/数字、口语化但别失真。
_INSTR_PLAIN = (
    "你是帮普通人读懂党政机关公文(红头文件)的助手。下面给你公文里的**一条**条款——"
    "它的「事项」是这条在说什么事,「原文」是这条的逐字原文(公文体官话)。\n"
    "请把这条的官话**改写成普通人一看就懂的大白话**,死守三条:\n"
    "1. 只**转述**原文已经说的,不增不减——原文没写的承诺/数字/期限/对象,一个字都别加。\n"
    "2. 别编。原文说「应当于30日内办结」就说「得在30天内办完」,别擅自改成「尽快」或加个"
    "没有的「否则处罚」。\n"
    "3. 口语化、短句、说人话,但意思必须跟原文一致;像在跟一个没读过公文的朋友解释这条在要求"
    "什么。\n"
    "4. **照原文的力度翻,别拉平**:原文「原则上不批」别翻成死的「不批」(它留了口子)、"
    "「鼓励」别翻成「必须」(它是倡导不是命令)、「逐步推进」别翻成「马上推进」(它没给时间表)。"
    "白话要把这层软硬分寸如实带出来。\n"
    "只输出这一句大白话本身,别加引号、别加「这条的意思是」这类前缀、别加解释、别加 markdown。\n"
    + codebook_block()
)

# 全文逐句模式的指令。喂的是公文的**一段连续原文**,要它按句顺译成「原文 → 白话」对照、不漏句。
# 死守:original 逐字照抄原文(给核验当锚)、plain 只转述这一句、照力度翻别拉平、不漏句不增句。
_INSTR_FULLTEXT = (
    "你是帮普通人读懂党政机关公文(红头文件)的助手。下面 === 全书原文 === 之后是这份公文的"
    "**一段连续原文**(可能是其中一部分,不一定从头)。\n"
    "请把这段**按句顺着翻成大白话**,一句一句来、**一句都不能漏**:每遇到一个句子,输出一对"
    "「原文 → 白话」。死守:\n"
    "1. ``original``:把这句原文**逐字照抄**(原样摘录、标点都别动)——它要拿去跟原文比对核验,"
    "改一个字就核不上了。\n"
    "2. ``plain``:把这句官话改写成普通人一看就懂的大白话,只**转述**这句说的、不增不减,原文"
    "没写的承诺/数字/期限/对象一个字都别加。\n"
    "3. **照原文的力度翻,别拉平**:「原则上不批」别翻成死的「不批」、「鼓励」别翻成「必须」、"
    "「逐步推进」别翻成「马上推进」——软硬分寸如实带出来。\n"
    "4. **顺序、句数跟原文一致**:别合并几句成一句、别拆一句成几句、别跳过任何一句(哪怕是"
    "套话、过渡句也照翻)、别自己加原文没有的句子。\n"
    "5. 标题 / 落款 / 发文字号这类不成句的,也各当一句照翻(``plain`` 简单说明它是什么即可)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏),形如:\n"
    '{"pairs":[{"original":"逐字原文句","plain":"这句的大白话"}]}\n'
    + codebook_block()
)

_FULLTEXT_USER_MSG = "请按上面的要求,把这段公文按句顺译成「原文 → 白话」对照,一句都别漏,输出 JSON。"


def _coerce_plain_text(raw: str) -> str:
    """把模型回的白话清洗成一行:去 markdown 围栏、去包裹引号、压多余空白。

    模型偶尔不听话加「这条的意思是:」前缀或裹一对引号,这里做轻清洗——只去明显的包裹噪声,
    不改写内容(内容真伪靠 verify 那道闸,不靠这里猜)。
    """
    s = (raw or "").strip()
    if not s:
        return ""
    # 去 ```...``` 围栏(模型偶发当代码块输出)
    if s.startswith("```"):
        lines = [ln for ln in s.splitlines() if not ln.strip().startswith("```")]
        s = "\n".join(lines).strip()
    # 去一对包裹的中/英文引号
    for lq, rq in (('"', '"'), ("「", "」"), ("“", "”"), ("'", "'")):
        if len(s) >= 2 and s.startswith(lq) and s.endswith(rq):
            s = s[1:-1].strip()
            break
    return s


def _rewrite_one(
    clause: dict[str, Any],
    *,
    llm_client: Any,
    model: str,
    max_tokens: int,
    cache_enabled: bool,
) -> str:
    """把一条条款的官话改写成大白话——单条 LLM 调用,失败返空串(由上层退回原事项)。

    只把这一条的「事项 + 原文」喂进去(不喂全文),走 ``invoke_client_cached`` 缓存。
    用 ``build_longctx_system`` 拼(同站内其它功能,book-first 前缀也让这层吃缓存:同一条
    第二次改写命中)——这里「书」位置放的是这一条的事项 + 原文(很短)。
    """
    matter = str(clause.get("matter", "")).strip()
    evidence = str(clause.get("evidence", "")).strip()
    # 改写素材:有原文优先拿原文(逐字),没原文退事项——总得有东西给模型改。
    source = evidence or matter
    if not source:
        return ""
    payload = f"事项:{matter or '(未给)'}\n\n原文:{evidence or '(未给逐字原文)'}"
    system = build_longctx_system(payload, _INSTR_PLAIN)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=system,
            tools=[],
            messages=[{"role": "user", "content": "请按上面的要求改写成大白话。"}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
        return _coerce_plain_text(llm_client.extract_final_text(resp))
    except Exception as exc:  # noqa: BLE001 — 单条改写失败不拖垮整体,退回原事项
        logger.warning(
            "redhead_plain: 第 %s 条改写抛 %s: %s;退回原事项",
            clause.get("chapter"),
            type(exc).__name__,
            exc,
        )
        return ""


# ── 全文逐句模式 ─────────────────────────────────────────────────────────────

def _split_into_sentences(text: str) -> list[str]:
    """把一段公文原文按句末标点切成句子列表(保序、保标点,空句丢)。

    中文公文以「。!?;…」收句,右引号 / 书名号 / 右括号收尾的也算句末
    (见 ``_SENTENCE_END_RE``)。换行也当切点(标题/落款常独占一行、不带句末标点)。
    切完去掉纯空白的碎片——只保有实义的句子,顺序不变。
    """
    if not text or not text.strip():
        return []
    parts = _SENTENCE_END_RE.split(text)
    return [s.strip() for s in parts if s and s.strip()]


def _segment_fulltext(text: str, char_budget: int) -> list[str]:
    """把整份原文按句切好后,再按字符预算攒成若干段(每段是若干完整句拼回的一块文字)。

    分段是为了**别一次吃爆 token**:每段越短,要顺译的句数越少、输出越不容易顶爆 max_tokens。
    不在句子中间切(整句跟着段走),所以一段是「攒到快超预算的若干完整句」。单句若本身就超预算
    (极罕见,公文句一般不长)也单独成段——总得有东西给模型,不丢。
    """
    sentences = _split_into_sentences(text)
    if not sentences:
        return []
    segments: list[str] = []
    cur: list[str] = []
    cur_len = 0
    for s in sentences:
        if cur and cur_len + len(s) > char_budget:
            segments.append("".join(cur))
            cur = []
            cur_len = 0
        cur.append(s)
        cur_len += len(s)
    if cur:
        segments.append("".join(cur))
    return segments


def _parse_pairs(text: str) -> list[dict[str, str]]:
    """解析 ``{pairs:[{original, plain}]}`` → 句对列表。三层兜底同兄弟模块。

    strip 围栏 → json.loads → 抠首个 obj → ``salvage_closed_objects`` 截断抢救(全文模式输出长、
    最容易被 max_tokens 截断,这层兜底最关键)。每对要 ``original`` 非空(没原文当不了核验锚);
    ``plain`` 缺退空串(上层会退回原文摆着)。解析不出 → 空列表。
    """
    raw = (text or "").strip()
    if not raw:
        return []
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

    pairs_raw: Any = None
    if isinstance(obj, dict):
        pairs_raw = obj.get("pairs")
    if not isinstance(pairs_raw, list):
        salvaged = salvage_closed_objects(candidate, '"pairs"')
        if salvaged:
            logger.warning("redhead_plain: fulltext 主解析失败,从截断抢救句对")
            pairs_raw = salvaged
        else:
            return []

    out: list[dict[str, str]] = []
    for it in pairs_raw:
        if not isinstance(it, dict):
            continue
        original = str(it.get("original", "")).strip()
        if not original:
            continue  # 没原文 → 当不了核验锚,丢
        out.append({"original": original, "plain": str(it.get("plain", "")).strip()})
    return out


def _translate_segment(
    seg_text: str,
    *,
    llm_client: Any,
    model: str,
    max_tokens: int,
    cache_enabled: bool,
) -> list[dict[str, str]]:
    """把一段连续原文顺译成句对列表——单段 LLM 调用,失败/截断空返空(由上层兜)。

    整段原文进 ``build_longctx_system`` book-first 上下文(吃前缀缓存),要模型吐 ``{pairs}``。
    先读 ``finish_reason`` 把截断变可观测(``salvage_closed_objects`` 仍会抢救已闭合的句对),
    再解析。单段抛异常 → 返空(不拖垮其它段)。
    """
    system = build_longctx_system(seg_text, _INSTR_FULLTEXT)
    try:
        resp = invoke_client_cached(
            llm_client,
            model=model,
            system=system,
            tools=[],
            messages=[{"role": "user", "content": _FULLTEXT_USER_MSG}],
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )
    except Exception as exc:  # noqa: BLE001 — 单段失败不拖垮整体
        logger.warning(
            "redhead_plain: fulltext 段调用抛 %s: %s;跳过该段", type(exc).__name__, exc
        )
        return []
    if read_openai_finish_reason(resp) == "length":
        # 截断了:_parse_pairs 的 salvage 仍会抢回已闭合的句对(可能丢段尾几句),记一笔。
        logger.warning("redhead_plain: fulltext 段被 max_tokens 截断,抢救已闭合句对")
    return _parse_pairs(llm_client.extract_final_text(resp))


def _fulltext_mode(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None,
    max_tokens: int,
    max_workers: int | None,
    cache_enabled: bool,
    char_budget: int,
    spine_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """全文逐句顺译——触发文脉缓存 → 整份原文按句切段并发顺译 → 每句锚原文过核验 + 挂 nuance。

    跟 ``redhead_hard_facts`` 同走「触发文脉缓存复用整份精读」那条:文脉本身这里不拆字段
    (全文逐句要的是按句顺下来,不是条款),但走 ``get_or_build_doc_spine`` 入口能复用那份已精读
    的上下文缓存、跟结构解读 / 大白话 clauses 共用。顺译素材优先用完整原文(含公布头),没传退
    chunk 拼接。
    """
    # 触发/复用文脉缓存(同份秒出,跟别的公文功能共用整份精读)。文脉不在这拆字段。
    get_or_build_doc_spine(
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        full_text=full_text,
        cache_enabled=cache_enabled,
        **spine_kwargs,
    )

    source_text = (
        full_text
        if (full_text and full_text.strip())
        else "".join(str(c.get("text", "")) for c in chunks)
    )
    segments = _segment_fulltext(source_text, char_budget)
    if not segments:
        return {"schema_version": PLAIN_SCHEMA_VERSION, "mode": "fulltext", "items": []}

    workers = resolve_workers(max_workers)

    def _do(seg: str) -> list[dict[str, str]]:
        return _translate_segment(
            seg,
            llm_client=llm_client,
            model=model,
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )

    if workers <= 1 or len(segments) <= 1:
        seg_results = [_do(s) for s in segments]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            seg_results = list(ex.map(_do, segments))

    # 段序==输入序(ThreadPoolExecutor.map 按输入序返回),段按原文顺序切——所以 concat 后
    # 句子顺序就是原文顺序。seq 从 1 连续编号。
    items: list[dict[str, Any]] = []
    seq = 0
    for pairs in seg_results:
        for pair in pairs:
            seq += 1
            original = pair["original"]
            items.append({
                "seq": seq,
                "original": original,
                # 顺译失败(plain 空)→ 退回原文摆着,不假装翻好了。
                "plain": pair["plain"] or original,
                "evidence": original,  # 全文模式 evidence 就是这句逐字原文(核验锚)
                "verified": False,
                "match_score": 0.0,
            })

    if not items:
        return {"schema_version": PLAIN_SCHEMA_VERSION, "mode": "fulltext", "items": []}

    # 核验:每句的**原文**过 verify_citations(核的是「这句原文在文里找得到」)。
    evidence_map = _build_doc_evidence_map(chunks, source_text)
    citations = [{"snippet": it["evidence"]} for it in items]
    verify_citations(citations, evidence_map)
    for it, vc in zip(items, citations, strict=True):
        it["verified"] = bool(vc.get("verified", False))
        it["match_score"] = vc.get("match_score", 0.0)
        # 弦外之意:命中措辞刻度就挂 nuance(原文确有 marker 才有)。
        _attach_nuance(it)

    return {"schema_version": PLAIN_SCHEMA_VERSION, "mode": "fulltext", "items": items}


def _build_doc_evidence_map(
    chunks: list[dict[str, Any]], full_text: str | None
) -> dict[str, dict]:
    """证据登记表:chunks + 整份原文兜底锚。两种模式共用。

    公布头(成文日期 / 发文字号常在公布头)在「第一章」之前会被分块层当章前噪声丢掉、不进任何
    chunk,光拿 chunks 当证据表那类原文永远核不过——所以补一条整份原文兜底(同文脉头要素维)。
    """
    evidence_map = build_evidence_map(chunks)
    if full_text and full_text.strip():
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": full_text}
    return evidence_map


def _attach_nuance(item: dict[str, Any]) -> None:
    """命中措辞刻度就给这条挂 ``nuance``(原地改);没命中不挂——nuance 是可选字段。

    死守 evidence-first:nuance 只在这条**原文**(``evidence``)里**确有** marker 时才出
    (``detect_nuances`` deterministic 串匹配),原文没这词就不加,绝不硬塞。核不过原文的条
    (``verified=False`` 且原文是编的)按理 evidence 已被上层处理;这里只对留下的原文判 nuance。
    """
    evidence = str(item.get("evidence", "")).strip()
    nuances = detect_nuances(evidence)
    if nuances:
        item["nuance"] = nuances


def _clauses_mode(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None,
    max_tokens: int,
    max_workers: int | None,
    cache_enabled: bool,
    spine_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """逐条款摘译(默认模式)——拿文脉 → 逐条并发改写 → 白话锚回原条款过核验 + 挂 nuance。"""
    spine = get_or_build_doc_spine(
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        full_text=full_text,
        cache_enabled=cache_enabled,
        **spine_kwargs,
    )
    clauses: list[dict[str, Any]] = spine.get("clauses") or []
    if not clauses:
        return {"schema_version": PLAIN_SCHEMA_VERSION, "mode": "clauses", "items": []}

    workers = resolve_workers(max_workers)

    def _do(clause: dict[str, Any]) -> str:
        return _rewrite_one(
            clause,
            llm_client=llm_client,
            model=model,
            max_tokens=max_tokens,
            cache_enabled=cache_enabled,
        )

    if workers <= 1 or len(clauses) <= 1:
        plains = [_do(c) for c in clauses]
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            plains = list(ex.map(_do, clauses))

    items: list[dict[str, Any]] = []
    for clause, plain in zip(clauses, plains, strict=True):
        matter = str(clause.get("matter", "")).strip()
        evidence = str(clause.get("evidence", "")).strip()
        items.append({
            "chapter": clause.get("chapter"),
            "matter": matter,
            # 改写失败(空)→ 退回原事项,老实把官话原样摆出来,不假装翻好了。
            "plain": plain or matter,
            "evidence": evidence,
            "verified": False,
            "match_score": 0.0,
        })

    # 核验:每条白话背后的**原文 evidence**(不是白话)过 verify_citations。核的是「这条白话
    # 转述的那句原文在文中找得到」——白话是改写、不该也核不到原文,所以锚的是原 evidence。
    evidence_map = _build_doc_evidence_map(chunks, full_text)
    citations = [{"snippet": it["evidence"]} for it in items]
    verify_citations(citations, evidence_map)
    for it, vc in zip(items, citations, strict=True):
        it["verified"] = bool(vc.get("verified", False))
        it["match_score"] = vc.get("match_score", 0.0)
        # 弦外之意:命中措辞刻度就挂 nuance(原文确有 marker 才有,不靠 LLM 脑补)。
        _attach_nuance(it)

    return {"schema_version": PLAIN_SCHEMA_VERSION, "mode": "clauses", "items": items}


def plain_language_from_spine(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    mode: PlainMode = "clauses",
    full_text: str | None = None,
    max_tokens: int | None = None,
    max_workers: int | None = None,
    cache_enabled: bool = True,
    char_budget: int = DEFAULT_FULLTEXT_CHAR_BUDGET,
    **spine_kwargs: Any,
) -> dict[str, Any]:
    """一份公文翻成大白话——两种模式 + 弦外之意注解。复用现成的机器,一行不改 ``doc_spine``。

    - ``mode="clauses"``(默认,向后兼容):走文脉**条款**,逐条并发摘译(``_rewrite_one`` 只喂
      这一条的事项 + 原文)→ 白话锚回**原条款逐字原文**过 ``verify_citations`` → 命中 marker
      挂 nuance。改写失败退回原事项、标 ``verified=False``。
    - ``mode="fulltext"``(全文逐句,#22):触发/复用文脉缓存 → 整份原文**按句切段**、并发逐段
      顺译(每段吐一串 ``{原文, 白话}`` 句对、不漏句)→ 每句**原文**过 ``verify_citations`` →
      命中 marker 挂 nuance。三守卫:给够 token / cache_enabled 透传 / parse 健壮带截断抢救。

    **nuance(弦外之意,两种模式都有)**:命中措辞刻度 codebook 的 marker 才挂一个 ``nuance``
    字段(``[{marker, meaning}]``),点这词的真实含义(「原则上」→有口子、「研究」→约等于不办)。
    死守 evidence-first:只在原文里**确有** marker 时才出(``detect_nuances`` deterministic 串
    匹配,不靠 LLM 脑补隐含义);没命中就不挂这字段。

    Args:
        chunks: 这份公文的 chunk 列表(每条含 ``chunk_id`` / ``chapter`` / ``text``)。
        llm_client: duck-typed LLM client(同 AgentLoop / 文脉)。
        model: 模型名。
        mode: ``"clauses"``(默认,逐条款)或 ``"fulltext"``(全文逐句)。
        full_text: 这份公文的完整原文(含公布头)。clauses 模式透传给文脉构建当头要素抽取 +
            兜底锚;fulltext 模式直接拿它按句切段(没传退回 ``chunks`` 拼接)。
        max_tokens: 单次调用的 max_tokens。``None`` 按模式取默认——clauses 单条
            ``DEFAULT_PLAIN_MAX_TOKENS=1200``(一句白话够),fulltext 单段
            ``DEFAULT_FULLTEXT_MAX_TOKENS=8000``(一段多句对照,输出长)。
        max_workers: 并发数(透传 ``resolve_workers``):clauses 逐条并发、fulltext 逐段并发。
        cache_enabled: 是否走 L2 缓存(默认开;改写/顺译层 + 文脉层都吃)。
        char_budget: **仅 fulltext** 的每段字符预算(默认 ``DEFAULT_FULLTEXT_CHAR_BUDGET``);
            clauses 模式不用它(但仍会被 ``**spine_kwargs`` 捞走透传给文脉,见下)。
        **spine_kwargs: 透传给 ``get_or_build_doc_spine`` 的其余参数(clauses 模式用)。

    Returns:
        clauses 模式::

            {"schema_version": "v2", "mode": "clauses",
             "items": [{chapter, matter, plain, evidence, verified, match_score,
                        nuance?:[{marker, meaning}]}]}

        fulltext 模式::

            {"schema_version": "v2", "mode": "fulltext",
             "items": [{seq, original, plain, evidence, verified, match_score,
                        nuance?:[{marker, meaning}]}]}

        ``nuance`` 是**可选**字段(命中措辞刻度才有)。两种模式都:没料(条款空 / 全文空)→
        ``items: []``,前端优雅退场。``scanned`` / ``book_session_id`` / ``trace`` 由端点层加,
        本模块不管。
    """
    if mode == "fulltext":
        return _fulltext_mode(
            chunks=chunks,
            llm_client=llm_client,
            model=model,
            full_text=full_text,
            max_tokens=max_tokens if max_tokens is not None else DEFAULT_FULLTEXT_MAX_TOKENS,
            max_workers=max_workers,
            cache_enabled=cache_enabled,
            char_budget=char_budget,
            spine_kwargs=spine_kwargs,
        )
    return _clauses_mode(
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        full_text=full_text,
        max_tokens=max_tokens if max_tokens is not None else DEFAULT_PLAIN_MAX_TOKENS,
        max_workers=max_workers,
        cache_enabled=cache_enabled,
        spine_kwargs=spine_kwargs,
    )


__all__ = [
    "DEFAULT_FULLTEXT_CHAR_BUDGET",
    "DEFAULT_FULLTEXT_MAX_TOKENS",
    "DEFAULT_PLAIN_MAX_TOKENS",
    "PLAIN_SCHEMA_VERSION",
    "PlainMode",
    "plain_language_from_spine",
]
