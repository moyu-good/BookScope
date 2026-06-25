"""公文大白话翻译(1.6 红头文件垂直·二炮)——把公文体官话逐条翻成人话,每句白话锚回原条款。

**它解决什么**:公文体普通人看不懂(「应当于X日前予以办结」「依据上位文件精神,各相关单位
须严格落实」)。这功能把每条条款的官话改写成大白话,**白话是对原文的忠实转述、不是编造**——
公文比小说好做这一点:条款的事项 + 原文都是定死的,白话只是「换种说法说同一件事」,天然契合
evidence-first(白话背后那句原文核得到、就盖「鉴」印)。

**它跟公文结构解读(doc_structure)的分工**:那个把一份公文拆成头要素 + 逐条款的「结构」;这个
拿同一份文脉的条款,逐条再跑一次 LLM 把官话改写成人话。同一份文脉(``get_or_build_doc_spine``)
建一次,两个功能共用、第二个秒出。

**怎么做(套现成的机器,一行不改 doc_spine / cross_doc)**:

1. **拿文脉**:走 ``get_or_build_doc_spine`` 拿到这份公文的文脉(头要素 + 条款,带证据)。同一份
   公文命中缓存秒出,不重精读。
2. **逐条款并发改写**:对每条 clause 的公文体(事项 + 原文)跑一次 LLM,要求「把这句官话改写成
   普通人能懂的大白话,只转述、不增减、不编」。逐条并发(``ThreadPoolExecutor``,同穷尽化分段
   并发的道理),每条走 ``invoke_client_cached`` 缓存——同一条第二次看秒出、不重付 token。
3. **白话锚回原条款,过核验**:白话写完后,这条的 evidence(**原条款的逐字原文**,不是白话)再
   过一次 ``verify_citations``——核得到就 ``verified=True`` 盖「鉴」印。核的是「这条白话转述的那句
   原文在文中找得到」,不是核白话本身(白话是改写、不该也核不到原文)。改写失败 / 核不过的条款,
   白话退回原事项 + 标 ``verified=False``,绝不假装翻好了。

铁律:**只 import ``doc_spine`` 的缓存入口 + 现有 helper,一行不改 ``doc_spine`` / ``cross_doc``**;
不碰 ``agent.py`` 端点(端点该返的结构写在 ``build_plain_language_response`` 的 docstring 里给主
Claude 接线)。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from bookscope.agent._internal.doc_spine_cache import get_or_build_doc_spine
from bookscope.agent._internal.exhaustive import resolve_workers
from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import build_evidence_map, verify_citations

logger = logging.getLogger(__name__)

PLAIN_SCHEMA_VERSION = "v1"
"""大白话记录结构版本——升级要让从文脉派生的这层重算(文脉缓存不受影响,只是改写层重跑)。"""

DEFAULT_PLAIN_MAX_TOKENS = 1200
"""逐条款改写单条的 max_tokens。一条白话就一两句话,1200 留足 reasoning 头还绰绰有余
(deepseek-v4-flash 把 reasoning_content 算进 max_tokens,
见 reference_reasoning_model_token_budget)。"""

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
    "只输出这一句大白话本身,别加引号、别加「这条的意思是」这类前缀、别加解释、别加 markdown。"
)


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


def plain_language_from_spine(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    max_tokens: int = DEFAULT_PLAIN_MAX_TOKENS,
    max_workers: int | None = None,
    cache_enabled: bool = True,
    **spine_kwargs: Any,
) -> dict[str, Any]:
    """一份公文逐条款翻成大白话——拿文脉 → 逐条并发改写 → 白话锚回原条款过核验。

    复用现成的机器,一行不改 ``doc_spine`` / ``cross_doc``:

    - **文脉**走 ``get_or_build_doc_spine``(同份公文命中缓存秒出,跟公文结构解读共用一份文脉)。
    - **改写**逐条款各跑一次 LLM(``_rewrite_one``,只喂这一条的事项 + 原文、不喂全文),
      ``ThreadPoolExecutor`` 并发(同穷尽化分段并发的道理),每条走 ``invoke_client_cached``
      缓存。改写失败的条款白话退回原事项、标 ``verified=False``,绝不假装翻好了。
    - **核验**白话写完后,这条的 **原文 evidence**(不是白话)再过一次 ``verify_citations``——
      核的是「这条白话转述的那句原文在文中找得到」。核得到 ``verified=True`` 盖「鉴」印;
      核不过(含原文为空)``verified=False`` 标待核。

    Args:
        chunks: 这份公文的 chunk 列表(每条含 ``chunk_id`` / ``chapter`` / ``text``)。
        llm_client: duck-typed LLM client(同 AgentLoop / 文脉)。
        model: 模型名。
        full_text: 这份公文的完整原文(含公布头),透传给文脉构建当头要素抽取 + 兜底锚定。
        max_tokens: 逐条改写单条的 max_tokens(一句白话够用)。
        max_workers: 逐条并发数(透传 ``resolve_workers``,同穷尽化分段并发)。
        cache_enabled: 是否走 L2 缓存(默认开;改写层 + 文脉层都吃)。
        **spine_kwargs: 透传给 ``get_or_build_doc_spine`` 的其余参数(char_budget 等)。

    Returns:
        ``{
            "schema_version": "v1",
            "items": [{chapter, matter(原公文体事项), plain(大白话),
                       evidence(原条款逐字原文), verified, match_score}],
        }``。
        条款空(这份没拆出可逐条的正文)→ ``items: []``。``items`` 按条款序号(1…N)排。
    """
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
        return {"schema_version": PLAIN_SCHEMA_VERSION, "items": []}

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
    evidence_map = build_evidence_map(chunks)
    if full_text and full_text.strip():
        # 同文脉头要素维:公布头在「第一章」之前会被分块层当章前噪声丢掉,整份原文兜底锚定。
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": full_text}
    citations = [{"snippet": it["evidence"]} for it in items]
    verify_citations(citations, evidence_map)
    for it, vc in zip(items, citations, strict=True):
        it["verified"] = bool(vc.get("verified", False))
        it["match_score"] = vc.get("match_score", 0.0)

    return {"schema_version": PLAIN_SCHEMA_VERSION, "items": items}


__all__ = [
    "DEFAULT_PLAIN_MAX_TOKENS",
    "PLAIN_SCHEMA_VERSION",
    "plain_language_from_spine",
]
