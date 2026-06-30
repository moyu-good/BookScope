"""会议「立场与弦外」研判(1.7 会议垂直·第四炮)——同一份会议记录,读出字面底下的**真实态度**
和**言下之意**:谁真同意、谁附条件、谁嘴上应付实则拖延、谁踢皮球回避、谁口头答应心里没底。

**它解决什么**:前面四块(行动项台账 / 我的行动项 / 悬而未决 / 跨会承诺—兑现)回答「这场会定了
什么、谁要办什么」;立场与弦外回答「大家心里到底怎么想、这些表态有几分真」——这是会议比公文多出
的一维(公文单向下达没有多方角力),也是读者光靠自己读最难读出来的一层。「再研究研究」往往是搁置
不想办,「我理解但是」往往是软反对,「我尽量争取」往往是没底的敷衍。

**整个是评估层(evidence-first 命门,照搬公文「利害与风向」的信号段契约)**:

立场弦外没有一条是「盖鉴印的事实」,全是带原话基础的**推断**——跟会脉的 decisions/action_items
(证据层、核得过盖鉴印)不同,跟公文 ``redhead_stakes`` 的信号段一致。三条死守:

- **每条 stance/subtext 的 ``basis`` 必须过核验,一条都核不到就丢整条**(照搬
  ``redhead_stakes._filter_signals_by_basis``)。模型就算脑补一个立场,没有真原话撑,核验这关
  就拦掉——这是 probe 命根子(假阳性 0/9)能守住的工程保证。
- **schema 里 stance/subtext 都没有 ``verified`` 字段**(评估层、不盖鉴印)。立场「Eng-B 软反对」
  是推断,撑它的逐字稿原话才是事实,前端标「研判」不是钤印核验。
- **抽不到就不输出,绝不脑补**:person 锚不到 → 这条不输出;basis 核不到 → 丢;议题本就没立场
  张力(纯通报 / 真一致同意)→ 老实返空(verdict=确证一致无弦外),绝不为了「分析出点东西」硬编。

**两个维度(复用现成的判据)**:

- **position(方向五态,封闭集)**:支持 / 反对(含软反对)/ 保留(附条件)/ 摇摆(没准主意)/
  回避(不正面表态)。落不进退「摇摆」(最中性,不替用户断成支持或反对)。
- **substance(分量三档,复用钱学森开环/闭环)**:带承诺 + 责任 + 时限的表态=闭环=「真金白银」,
  纯姿态 / 原则性表态=开环=「空头表态」,介于两者=「有条件兑现」。一个人说「支持」但既不接活
  也不给时间,这个「支持」就是空头姿态。**position 和 substance 是两个维度**——position 是方向,
  substance 是分量。

**弦外六类(封闭集)**:表面同意实则保留 / 拖延搁置 / 甩锅推责 / 回避问题 / 留口子 /
口头答应没底。落不进六类**不输出该条**(不设兜底类——弦外最容易脑补,宁可漏一条也不留个说不清的)。

**form 门控(逐字稿主路 / 纪要退场)**:立场弦外靠口语细节(省略号「行吧」、「争取」二字、表态
温差),纪要是编辑过的概括稿、口语弦外被洗掉了。在纪要的概括文本上硬编言下之意,正是 evidence-
first 红线最该防的破法。所以:

- **逐字稿(form==逐字稿)**:正常跑,每条立场/弦外锚原话、过核验。form_note 为空串。
- **纪要(form==纪要)**:直接优雅退场——返 topics 空 + form_note 提示建议传逐字稿。**绝不在概括
  句上硬编**(设计稿 §3.2 的硬降级 B 缓做,要先补一组纪要验证集,本模块不实现 B)。

**verdict 三态(议题层承载「确证无 ≠ 抽不到」)**:

- **有立场张力**:逐字稿里读出了立场/弦外。
- **确证一致无弦外**:确证这议题没张力(纯通报 / 真一致同意)——这是笃定的答案不是抽不到,
  stances/subtexts 空但 verdict 本身是答案,甚至是正面信号(会开得清爽)。
- **读不出（纪要/待核）**:纪要形态读不出语气、或模型这趟没读出。

**怎么做(走整本结构化功能那套,一次扫全份)**:跟 ``stakes_from_doc`` 同款——立场是横切全场的
研判(要看一个人在整场会的前后表态对照才判得准,分段会割裂「他先反对后被压下」这种弧线),所以
整份会议记录进 ``build_longctx_system`` book-first 上下文(吃前缀缓存,同份会议不同功能共用前缀),
一次出 JSON;每条 stance/subtext 的 basis 逐条过 ``verify_citations``(一条都核不到丢整条);
三守卫焊死(给够 token 防 reasoning 吃光 / cache_enabled 透传 / parse 健壮带兜底)。

铁律:**只 import 现有 helper,一行不改 ``redhead_stakes`` / ``meeting_spine`` /
``redhead_codebook`` / ``citation_check`` 本体**;basis 核不到就丢、纪要不硬编、绝不盖鉴印;
``scanned`` / ``book_session_id`` / ``trace`` 由端点层加,本模块只管
``{schema_version, form, form_note, topics, summary}``。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent._internal.longctx_system import build_longctx_system
from bookscope.agent.citation_check import build_evidence_map, verify_citations

# 只 import helper,一行不改 meeting_spine 本体:措辞刻度块(判含金量同一把尺)、含金量归一
# (会议三档 + 公文别名)、form 归一(落不进退纪要)、议程段弱先验消歧(防同人反复短发言锚错轮)。
# MEETING_SUBSTANCE_LEVELS:含金量三档,立场 substance 同一集,re-export。
from bookscope.agent.meeting_spine import (
    MEETING_SUBSTANCE_LEVELS,
    _coerce_form,
    _coerce_meeting_substance,
    _infer_segment_prior,
    _meeting_codebook_block,
)
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

STANCE_SCHEMA_VERSION = "v1"
"""立场与弦外记录结构版本——升级要让这层重算(不影响别的功能)。"""

DEFAULT_STANCE_MAX_TOKENS = 16000
"""一次扫全份出多议题多人立场 + 弦外 + basis 列表的 max_tokens。

deepseek-v4-flash 把 reasoning_content 算进 max_tokens(reference_reasoning_model_token_budget),
整份进上下文后先吐一大段 reasoning,预算太小会被吃光导致 content 截断、``finish_reason=length``。
**live 抽查校准(2026-06-30)**:设计稿 §4.4 估的 5000 不够——一份 2187 字、6 议题的逐字稿在 5000
下被截断,salvage 只捞回前 2 个干净议题,后面 4 个带拖延 / 空头表态的议题全丢,还静默显示成「确证
一致无弦外」(假装没暗流,对红线功能危险)。16000 实测装得下整场多议题研判 + reasoning 头。真被
截断仍有 ``extract_first_json_object`` + ``salvage_closed_objects`` 兜底,但默认就该给够。"""

# ── 封闭集(落不进退最保守档,evidence-first 评估层纪律)─────────────────────────
# 立场方向五态(封闭集)。落不进退「摇摆」——最中性,不替用户断成支持或反对。
STANCE_POSITIONS: tuple[str, ...] = ("支持", "反对", "保留", "摇摆", "回避")
_DEFAULT_POSITION = "摇摆"

# 弦外六类(封闭集)。**落不进不输出该条**(不设兜底类——弦外最容易脑补,宁可漏一条也不留
# 个说不清类别的),所以归一函数返 None 由调用方丢掉,而不是退某个兜底值。
SUBTEXT_KINDS: tuple[str, ...] = (
    "表面同意实则保留",
    "拖延搁置",
    "甩锅推责",
    "回避问题",
    "留口子",
    "口头答应没底",
)

# 置信度三档(封闭集)。落不进退「低」——最保守,不替推断拔高可信度。
CONFIDENCE_LEVELS: tuple[str, ...] = ("高", "中", "低")
_DEFAULT_CONFIDENCE = "低"

# 议题层 verdict 三态(封闭集,承载「确证无 ≠ 抽不到」)。落不进按 form 兜底:
# 逐字稿退「有立场张力」(默认有内容)、纪要退「读不出（纪要/待核）」——见 _default_verdict_for_form。
VERDICT_HAS_TENSION = "有立场张力"
VERDICT_CONFIRMED_NONE = "确证一致无弦外"
VERDICT_UNREADABLE = "读不出（纪要/待核）"
VERDICTS: tuple[str, ...] = (VERDICT_HAS_TENSION, VERDICT_CONFIRMED_NONE, VERDICT_UNREADABLE)

# 纪要退场的提示文案(说人话、无破折号、无真名)。逐字稿分支 form_note 为空串。
_JIYAO_FORM_NOTE = (
    "这份是整理稿,读不出现场语气,立场与弦外要逐字稿才判得了,建议传逐字稿。"
)

# 立场 / 弦外里非封闭集、非 basis 的字符串字段。
_STANCE_STR_FIELDS = ("person", "topic", "reading", "substance_reason")
_SUBTEXT_STR_FIELDS = ("person", "topic", "subtext")


# ── 抽取 prompt(逐字稿主分支,照 meeting_spine 内联体例)─────────────────────────
# 死守:每条立场/弦外锚原话 + 标研判 + 给置信度;封闭集落不进退最保守;真一致同意/纯通报老实
# 返空(verdict=确证一致无弦外);basis 摘长防锚错。措辞刻度块(判含金量同一把尺)拼在末尾。
_INSTR_STANCE = (
    "你在读一份会议记录,替读者挖出字面底下的**真实态度**和**言下之意**。\n"
    "会议里大家心里怎么想,常常不写在脸上:「再研究研究」往往是不想办,「我理解但是」往往是软反对,"
    "「我尽量争取」往往是没底的敷衍。你要读出这些弦外之音——但**只在发言原话里真有支撑时才点,"
    "原话里读不出的,一个都别编**。\n"
    "\n"
    "【你要产出两块,按议题(topic)聚合】\n"
    "\n"
    "一、立场(stances):每个关键与会人,对每个核心议题/决策的**真实态度**。每条给:\n"
    "1. person:谁(用会议记录里出现的称呼/名字)。读不出是谁说的就别写这条。\n"
    "2. topic:对哪个议题或决策(一句话点出,如「v2.0 在 4 月 15 号发版」「社区运营怎么推」)。\n"
    "3. position:他的真实态度,**只能填以下五个之一**:\n"
    "   · 支持——明确赞成、愿意推。\n"
    "   · 反对——明确不赞成(含软反对:嘴上不直接拒绝但一直挑刺、提替代方案、强调风险)。\n"
    "   · 保留——附条件同意 / 同意里打了折(「原则上同意」「可以,但是…」)。\n"
    "   · 摇摆——没拿定主意、模棱两可、前后不一致。\n"
    "   · 回避——不正面表态、岔开话题、被点名却只说别的。\n"
    "   判不准就填「摇摆」。\n"
    "4. reading:用人话说清他的真实态度(一句话,直接说「他其实是…」)。\n"
    "5. substance(这表态有几分真):用下面「会议措辞刻度」的开环/闭环判,**只能填「真金白银」"
    "「有条件兑现」「空头表态」之一**:表态 + 接了活 + 给了时限/验收 → 真金白银(动真格);"
    "纯姿态、没接活没下文(「我支持」但啥也不做)→ 空头表态(场面话);介于两者 → 有条件兑现。\n"
    "6. substance_reason:凭原话里哪些 marker 判这档(他有没有接活/给时限,还是只是表个态,"
    "锚原话);判不出留空。\n"
    "7. basis:引发你这个判断的**发言原话片段列表**(几条逐字原话,连说话人一起原样摘录)——"
    "**没有原话撑的判断,一条都别写**,哪怕你觉得很可能。摘长一点、带上下文,别只摘「同意」两个字。\n"
    "8. confidence:这判断的把握,只能填「高」「中」「低」。\n"
    "\n"
    "二、弦外(subtexts):发言表面意思之外的**言下之意**。每条给:\n"
    "1. kind:哪一类言下之意,**只能填以下六个之一**:\n"
    "   · 表面同意实则保留——「我理解但是」「原则上同意」「嗯可以吧」,同意打了折。\n"
    "   · 拖延搁置——「再研究研究」「回头安排」「后面再细化」「先放放」,把事请出会议室。\n"
    "   · 甩锅推责——「这个不归我们」「得看上面意思」「等 X 部门先动」,责任往外推。\n"
    "   · 回避问题——答非所问、岔开话题、被点名却只说别的,不正面接。\n"
    "   · 留口子——「尽量」「争取」「视情况」「差不多」,给自己留退路、不是硬承诺。\n"
    "   · 口头答应没底——嘴上应了(「我尽量」「下周争取出初稿」),但自己也没把握、可能再落空。\n"
    "   **落不进这六类的弦外别写**(别硬塞一个说不清类别的)。\n"
    "2. person:谁说的(读不出就别写这条)。\n"
    "3. topic:这弦外出现在哪个议题上。\n"
    "4. subtext:他这话真正想说的是什么(一句话)。\n"
    "5. basis:引发这判断的发言原话片段列表(逐字、连说话人、摘长带上下文)——**没原话撑的别写**。\n"
    "6. confidence:把握,「高」「中」「低」。\n"
    "\n"
    "【最重要的红线:没有就说没有,绝不为了分析出点东西而脑补】\n"
    "- 如果一个议题大家是**真心一致同意**(都明确说没意见、没有任何转折犹豫),就把这议题的"
    "verdict 填「确证一致无弦外」、stances 和 subtexts 给空数组——这是好事,不是你没读出来,"
    "verdict 本身就是答案。\n"
    "- 如果某个议题就是**纯通报、纯汇报数据/进度**,没有任何态度可挖,同样填「确证一致无弦外」、"
    "给空数组,**绝不**顺着「他藏着什么立场」硬编一个出来。\n"
    "- 读出了立场/弦外的议题,verdict 填「有立场张力」。\n"
    "- 立场和弦外是**推断**,不是会议明说的事实。你引出的原话才是事实,你的判断要标清是「研判」。\n"
    "- 同一个判断,原话里读不出方向(到底支持还是反对都看不出来)时,position 填「摇摆」、"
    "confidence 填「低」,别硬断。\n"
    "\n"
    "【证据要摘长(违反会让系统锚错地方)】\n"
    "会议里同一个人反复说「同意」「好的」「可以」,这种短句到处都是。basis 只摘「同意」两个字,"
    "系统没法判断是哪一轮说的,会锚错。**每条 basis 必须摘一整句、带前后文、连说话人标记**,"
    "比如不要摘「行吧」,要摘「Eng-B:……行吧,那我尽量。回归计划我两天内列出来」整句。"
    "摘得越长越独特越锚得准。\n"
    "\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏),按议题聚合,形如:\n"
    '{"topics":[{"topic":"","verdict":"有立场张力",'
    '"stances":[{"person":"","topic":"","position":"反对","reading":"",'
    '"substance":"有条件兑现","substance_reason":"","basis":["",""],"confidence":"中"}],'
    '"subtexts":[{"kind":"口头答应没底","person":"","topic":"","subtext":"",'
    '"basis":["",""],"confidence":"中"}]}],'
    '"summary":""}\n'
    "如果整场会就是纯通报 / 全程一致无分歧,topics 里对应议题的 verdict 填「确证一致无弦外」、"
    "stances 和 subtexts 给空数组——verdict 本身就是答案,别硬塞内容。\n"
    "\n"
    + _meeting_codebook_block()
)

_USER_MSG = "请按上面的要求,读出这份会议记录里各议题的立场与弦外,输出 JSON。"


def _coerce_position(value: Any) -> str:
    """立场方向归一:必须落进五态封闭集,落不进退「摇摆」(最中性)。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in STANCE_POSITIONS else _DEFAULT_POSITION


def _coerce_confidence(value: Any) -> str:
    """置信度归一:必须落进三档封闭集,落不进退「低」(最保守)。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in CONFIDENCE_LEVELS else _DEFAULT_CONFIDENCE


def _coerce_kind(value: Any) -> str | None:
    """弦外类别归一:落进六类封闭集才返,**落不进返 None(由调用方丢这条)**。

    弦外最容易脑补,不设兜底类——说不清类别的宁可漏掉,不留个含混的。
    """
    s = value.strip() if isinstance(value, str) else ""
    return s if s in SUBTEXT_KINDS else None


def _coerce_basis(value: Any) -> list[str]:
    """basis 归一成非空字符串 list。模型偶尔写成单字符串而非 list,宽松收(同 ``_coerce_signal``)。"""
    if isinstance(value, list):
        return [str(b).strip() for b in value if str(b).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _coerce_stance(item: Any, topic_fallback: str) -> dict[str, Any] | None:
    """归一一条立场;person 空 或 basis 没一条原文 → 丢(没人 / 没据的不输出)。

    照 ``redhead_stakes._coerce_signal`` 的纪律:结构层只保证「有 person + basis 非空」,
    basis 原文确在文里那步在上层 ``_filter_topics_by_basis`` 做。position/substance/confidence
    走封闭集兜底;topic 缺退到所属议题(冗余存便于扁平消费)。**不收 verified 字段**(评估层)。
    """
    if not isinstance(item, dict):
        return None
    person = str(item.get("person", "")).strip()
    basis = _coerce_basis(item.get("basis"))
    if not person or not basis:
        return None
    out: dict[str, Any] = {
        "person": person,
        "position": _coerce_position(item.get("position")),
        "substance": _coerce_meeting_substance(item.get("substance")),
        "basis": basis,
        "confidence": _coerce_confidence(item.get("confidence")),
    }
    for field in _STANCE_STR_FIELDS:
        if field == "person":
            continue
        v = item.get(field)
        out[field] = v.strip() if isinstance(v, str) else ""
    if not out["topic"]:
        out["topic"] = topic_fallback
    return out


def _coerce_subtext(item: Any, topic_fallback: str) -> dict[str, Any] | None:
    """归一一条弦外;kind 落不进六类 / person 空 / basis 没一条原文 → 丢。

    弦外封闭集落不进**不输出**(``_coerce_kind`` 返 None),同立场的无据丢。**不收 verified**。
    """
    if not isinstance(item, dict):
        return None
    kind = _coerce_kind(item.get("kind"))
    person = str(item.get("person", "")).strip()
    basis = _coerce_basis(item.get("basis"))
    if kind is None or not person or not basis:
        return None
    out: dict[str, Any] = {
        "kind": kind,
        "person": person,
        "basis": basis,
        "confidence": _coerce_confidence(item.get("confidence")),
    }
    for field in _SUBTEXT_STR_FIELDS:
        if field == "person":
            continue
        v = item.get(field)
        out[field] = v.strip() if isinstance(v, str) else ""
    if not out["topic"]:
        out["topic"] = topic_fallback
    return out


def _coerce_verdict(value: Any, *, has_items: bool) -> str:
    """议题 verdict 归一(逐字稿分支):落进三态封闭集才用;落不进按有无内容兜底。

    逐字稿里:抽到了立场/弦外 → 「有立场张力」;模型明说确证一致无 → 尊重;落不进且没内容 →
    退「有立场张力」是错的(没内容怎么有张力),退「确证一致无弦外」更合理(逐字稿读完没读出
    张力)。所以:落不进时,有内容退「有立场张力」、没内容退「确证一致无弦外」。
    """
    s = value.strip() if isinstance(value, str) else ""
    if s in VERDICTS:
        return s
    return VERDICT_HAS_TENSION if has_items else VERDICT_CONFIRMED_NONE


def _parse_stance(text: str) -> dict[str, Any] | None:
    """解析 ``{topics:[{topic, verdict, stances, subtexts}], summary}`` → 归一后结构。

    三层兜底同 ``meeting_spine``:strip 围栏 → loads → 抠首个 obj → 截断抢救(从 ``"topics"``
    抢救已闭合议题)。每个议题的 stances/subtexts 各走 coerce(丢残缺 / 无据 / 封闭集落不进的)。
    解析不出返 None(调用方据此给空结构)。**summary 原样收**(末尾从已核验的拼,这里只透传模型的)。
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

    topics_raw: Any = None
    summary = ""
    if isinstance(obj, dict):
        topics_raw = obj.get("topics")
        summary = str(obj.get("summary", "")).strip()
    if not isinstance(topics_raw, list):
        salvaged = salvage_closed_objects(candidate, '"topics"')
        if salvaged:
            logger.warning("meeting_stance: 主解析失败,从截断抢救到 %d 个议题", len(salvaged))
            topics_raw = salvaged
        else:
            return None

    topics: list[dict[str, Any]] = []
    for t in topics_raw:
        if not isinstance(t, dict):
            continue
        topic = str(t.get("topic", "")).strip()
        stances: list[dict[str, Any]] = []
        for s in t.get("stances") or []:
            coerced = _coerce_stance(s, topic)
            if coerced is not None:
                stances.append(coerced)
        subtexts: list[dict[str, Any]] = []
        for st in t.get("subtexts") or []:
            coerced_st = _coerce_subtext(st, topic)
            if coerced_st is not None:
                subtexts.append(coerced_st)
        verdict = _coerce_verdict(
            t.get("verdict"), has_items=bool(stances or subtexts)
        )
        topics.append({
            "topic": topic,
            "verdict": verdict,
            "stances": stances,
            "subtexts": subtexts,
        })
    return {"topics": topics, "summary": summary}


def _filter_basis_items(
    items: list[dict[str, Any]],
    evidence_map: dict[str, dict],
    norm_chunks: list[tuple[str, Any, str]],
) -> list[dict[str, Any]]:
    """逐条校 basis 原文确在文里——评估层,**不盖 verified**,但基础必须可核。

    照搬 ``redhead_stakes._filter_signals_by_basis``:basis 里每条原文片段过 ``verify_citations``,
    **一条 basis 都核不到的整条丢**(无据的推断不输出);留下的只保留核得到的片段(把模型可能编
    的剔掉),结论仍标推断。

    会议特有的锚错防护(``reference_verify_citations_anchoring_limit``):同一人反复说「同意/好的」
    短引文跨轮复现率极高,多命中时 ``verify_citations`` 会锚到第一个出现的 chunk。这里把每条 basis
    所属议程段当**弱先验**塞进 ``chapter`` 字段触发消歧(复用 ``meeting_spine._infer_segment_prior``
    + ``citation_check._disambiguate_by_chapter``,跟会脉结论项核验同机制)。prompt 层已要求 basis
    摘长治本,这里是核验层的二道防护。
    """
    kept: list[dict[str, Any]] = []
    for it in items:
        basis = it.get("basis") or []
        citations: list[dict[str, Any]] = []
        for b in basis:
            prior = _infer_segment_prior(b, norm_chunks)
            cit: dict[str, Any] = {"snippet": b}
            if prior is not None:
                cit["chapter"] = prior
            citations.append(cit)
        verify_citations(citations, evidence_map)
        grounded = [
            b for b, vc in zip(basis, citations, strict=True)
            if bool(vc.get("verified", False))
        ]
        if not grounded:
            continue  # 一条原文基础都核不到 → 无据的推断,丢整条
        it["basis"] = grounded  # 只留核得到的原文片段(剔掉编的)
        kept.append(it)
    return kept


def _default_verdict_for_form(form: str) -> str:
    """没读出内容时议题 verdict 的形态兜底:纪要退「读不出」,逐字稿退「确证一致无弦外」。

    逐字稿读完一个议题没读出张力 = 确证这议题没暗流(笃定的「无」);纪要本就读不出语气 = 读不出。
    """
    return VERDICT_UNREADABLE if form == "纪要" else VERDICT_CONFIRMED_NONE


def _build_summary(topics: list[dict[str, Any]]) -> str:
    """系统一句话总览——带立场不中立罗列(类比 ``stakes._build_recommendation``)。

    **不调额外 LLM**(再调一次费 token 又得二次核验):直接从已核验、已排好的立场/弦外里挑分量
    重的点出来。挑法:优先点高置信度的软反对 / 拖延 / 口头答应没底这类「读者最该警惕」的弦外,
    再点空头表态的立场。没料(立场弦外全空)返空串。
    """
    # 收所有已核验的弦外 + 立场,挑分量重的。弦外比立场更「弦外之音」,优先。
    notable: list[str] = []
    for t in topics:
        topic = t.get("topic", "")
        for st in t.get("subtexts", []):
            if st.get("confidence") == "高":
                person = st.get("person", "")
                kind = st.get("kind", "")
                notable.append(f"{person}在「{topic}」上{kind}")
    # 空头表态的立场(嘴上一套实则不办)——读者该警惕。
    for t in topics:
        topic = t.get("topic", "")
        for s in t.get("stances", []):
            if s.get("substance") == "空头表态" and s.get("confidence") in ("高", "中"):
                person = s.get("person", "")
                notable.append(f"{person}对「{topic}」是空头表态")
    if not notable:
        # 有内容但都不够「分量重」:给个温和总览,点出有几条立场张力。
        n_stance = sum(len(t.get("stances", [])) for t in topics)
        n_subtext = sum(len(t.get("subtexts", [])) for t in topics)
        if n_stance or n_subtext:
            return f"这场会读出 {n_stance} 处立场、{n_subtext} 处弦外,具体看下面各议题。"
        return ""
    return ";".join(notable[:3]) + "。"


def _empty_result(form: str, form_note: str) -> dict[str, Any]:
    """空结构(纪要退场 / 无原文 / 没研判出):topics 空 + summary 空。"""
    return {
        "schema_version": STANCE_SCHEMA_VERSION,
        "form": form,
        "form_note": form_note,
        "topics": [],
        "summary": "",
    }


def stances_from_meeting(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    form: str | None = None,
    max_tokens: int = DEFAULT_STANCE_MAX_TOKENS,
    cache_enabled: bool = True,
) -> dict[str, Any]:
    """读一份会议记录的立场与弦外——一次扫全份出多议题研判 → 每条 basis 校原文确在文里。

    走整本结构化功能那套(同 ``stakes_from_doc`` 一次扫全份,因为立场是横切全场的研判、要看一个人
    整场前后表态才判得准):整份会议记录进 ``build_longctx_system`` book-first 上下文(吃前缀缓存),
    一次 LLM 出 JSON;每条 stance/subtext 的 basis 逐条过 ``verify_citations``,一条都核不到丢整条
    (评估层、不盖 verified、无据丢)。三守卫:给够 token / cache_enabled 透传 / parse 健壮带兜底。

    **form 门控(逐字稿主路 / 纪要退场)**:form 是纪要 → 直接返 topics 空 + form_note 提示传逐字稿
    (绝不在概括句上硬编弦外,设计稿 §3.2 的硬降级 B 缓做)。form 是逐字稿 → 正常跑,form_note 空串。

    Args:
        chunks: 这份会议记录的 chunk 列表(每条含 ``chunk_id`` / ``chapter``(=议程段号,会议里
            多半无、退 0) / ``text``)。basis 核验 + 议程段弱先验消歧用它。
        llm_client: duck-typed LLM client(同 AgentLoop / 其它会议功能)。
        model: 模型名。
        full_text: 这份会议记录的**完整原文**。传了就用它进上下文 + 当 basis 核验兜底锚;不传则
            退回 ``chunks`` 拼接(向后兼容)。
        form: 形态(``逐字稿`` | ``纪要``)。传了就用它当门控;不传则退「纪要」(更保守,不会误开
            只有逐字稿能跑的立场功能)。**纪要直接退场,绝不硬编**。
        max_tokens: 一次扫全份的 max_tokens(默认 16000,live 校准:reasoning 模型 + 多议题输出,
            5000 会截断把带张力的议题静默丢成「确证一致无弦外」)。
        cache_enabled: 是否走 L2 缓存(默认开,同份会议重看命中)。

    Returns:
        ``{
            "schema_version": "v1",
            "form": "逐字稿" | "纪要",
            "form_note": str,                # 纪要时的退场提示(逐字稿为空串)
            "topics": [{
                "topic": str,
                "verdict": "有立场张力" | "确证一致无弦外" | "读不出（纪要/待核）",
                "stances":  [{person, topic, position, reading, substance, substance_reason,
                              basis(原话列表), confidence}],   # 评估层,**无 verified**
                "subtexts": [{kind, person, topic, subtext, basis(原话列表), confidence}],
            }],
            "summary": str,                  # 系统一句话总览(带立场),没料返空串
        }``。
        stance/subtext 只含 basis 有原文基础的(一条都核不到丢整条);**都没有 verified 字段**
        (评估层、绝不盖鉴印)。form 是纪要 / 没原文 / 没研判出 → topics 空。
        ``scanned`` / ``book_session_id`` / ``trace`` 由端点层加,本模块不管。
    """
    resolved_form = _coerce_form(form)  # 传了用它;没传 / 落不进退「纪要」(更保守)

    # 纪要退场(A 方案):绝不在概括文本上硬编言下之意,直接返空 + 提示传逐字稿。B(硬降级)缓做。
    if resolved_form == "纪要":
        return _empty_result("纪要", _JIYAO_FORM_NOTE)

    # 一次扫全份:整份原文进上下文(优先完整原文;没传退 chunk 拼接)。
    source_text = (
        full_text
        if (full_text and full_text.strip())
        else "".join(str(c.get("text", "")) for c in chunks)
    )
    if not source_text.strip():
        return _empty_result(resolved_form, "")

    system = build_longctx_system(source_text, _INSTR_STANCE)

    parsed: dict[str, Any] | None = None
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
        parsed = _parse_stance(llm_client.extract_final_text(resp))
    except Exception as exc:  # noqa: BLE001 — 研判失败不抛,返空结构(前端优雅退场)
        logger.warning(
            "meeting_stance: 研判抛 %s: %s;返空结构", type(exc).__name__, exc
        )
        parsed = None

    if parsed is None:
        return _empty_result(resolved_form, "")

    # 证据登记表:chunks + 整份原文兜底锚(会议头/开头白可能被分块层切碎;整份原文是真原文,
    # 拿它兜底锚定不违背 evidence-first,同 ``stakes_from_doc`` / ``meeting_spine`` 的整份兜底)。
    evidence_map = build_evidence_map(chunks)
    if source_text.strip():
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": source_text}
    # 议程段弱先验消歧用的归一 chunks(同 ``meeting_spine._verify_conclusion_evidence``)。
    norm_chunks = [
        (str(c.get("chunk_id", "")), c.get("chapter"), str(c.get("text", "")))
        for c in chunks
    ]

    # 逐议题校 basis:stance/subtext 的 basis 一条都核不到 → 丢整条(评估层、不盖 verified)。
    # 校完空了的议题:有 topic 文字就保留(verdict 据是否还剩内容重判),纯空壳丢。
    topics: list[dict[str, Any]] = []
    for t in parsed["topics"]:
        stances = _filter_basis_items(t["stances"], evidence_map, norm_chunks)
        subtexts = _filter_basis_items(t["subtexts"], evidence_map, norm_chunks)
        has_items = bool(stances or subtexts)
        verdict = t["verdict"]
        # 校验把内容全冲掉了:原本「有立场张力」但 basis 全核不过 → 落不进了,按 form 兜底。
        if not has_items and verdict == VERDICT_HAS_TENSION:
            verdict = _default_verdict_for_form(resolved_form)
        # 纯空壳(无 topic 文字 + 无内容 + 不是确证无)丢掉,免得 UI 显一堆空议题。
        if not t["topic"] and not has_items and verdict != VERDICT_CONFIRMED_NONE:
            continue
        topics.append({
            "topic": t["topic"],
            "verdict": verdict,
            "stances": stances,
            "subtexts": subtexts,
        })

    summary = _build_summary(topics)

    return {
        "schema_version": STANCE_SCHEMA_VERSION,
        "form": resolved_form,
        "form_note": "",  # 逐字稿分支:form_note 空串
        "topics": topics,
        "summary": summary,
    }


__all__ = [
    "CONFIDENCE_LEVELS",
    "DEFAULT_STANCE_MAX_TOKENS",
    "MEETING_SUBSTANCE_LEVELS",
    "STANCE_POSITIONS",
    "STANCE_SCHEMA_VERSION",
    "SUBTEXT_KINDS",
    "VERDICTS",
    "stances_from_meeting",
]
