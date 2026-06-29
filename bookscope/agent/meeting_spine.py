"""会议「会脉」(1.7 会议垂直地基)——文脉的会议版,一份会议记录精读一次出带证据的结构。

**它是什么**:章脉是「一本书 → 逐章带证据结构」,文脉是「一份公文 → 头要素 + 逐条款」,
会脉是「一份会议记录 → 会议头要素 + 决议 + 行动项」。
设计稿 ``WP-1.7-action-ledger-schema-prompt.md`` 定的三维(+ 一个门控开关):

- **head(会议头要素维)**(会议级,一份一组):会议主题 / 会议时间 / 主持人 / 参会人 /
  缺席列席 / 记录范围。还判一个 ``form``(逐字稿 | 纪要)挂在顶层当门控。每个要素挂原文、
  过 ``verify_citations``,**抽不到留空、绝不编**(照搬 ``doc_spine._build_head_elements`` 的纪律)。
- **decisions(决议维)**:这场会真定下来的事——decision / decided_by / background /
  含金量(开环闭环) / evidence。
- **action_items(行动项维,首炮主角)**:谁要去做什么——task / owner / due / from_decision /
  source / 含金量 / loose_end / evidence。``loose_end``(owner 空或 due 空)**由 BE 纯计算**,
  不让模型打分。
- **open_issues(议而未决维)**:**首炮恒空 ``[]``**,schema 先占位,第二炮再填。

**跟公文最大的不同就一句**:公文逐条抽条款(条款本身就是要读的内容),会议要先从发言流水里
淘出结论项(发言轮是证据来源不是抽取单元)。同一台 map-reduce 引擎,prompt 让模型抽的东西
从「这段有哪些条款」换成「这段定了什么、谁要做什么」。

**复用了哪些骨架**(铁律:一行不改 ``doc_spine`` / ``chapter_spine`` / ``redhead_codebook`` /
``redhead_relevance`` 等现有模块,只 import helper):

- 结论项维走底层 ``exhaustive.run_segments``(分段 + 并发 + 截断兜底)+ 自接两步:逐段证据
  核验(只核不覆盖序号)+ 跨段全局重排序号——照 ``doc_spine`` 的做法(不能套
  ``mapreduce_per_chapter``,理由同公文条款维:那台机器会拿命中 chunk 的真章号覆盖记录序号,
  把同议程段的多条结论项压成一个号)。决议、行动项各自重排,行动项的 ``from_decision`` 跟着改。
- 头要素维一次抽取整份,每要素 evidence 过 ``verify_citations``,
  照搬 ``doc_spine._build_head_elements``。
- 含金量开环/闭环判直接 import ``redhead_codebook``(``coerce_substance``),**叶子档名换会议版
  「空头表态」**(公文是「空头倡导」)——开环/闭环框架复用,只换会议适配的措辞刻度块。
- JSON 解析三层兜底照搬 ``utils/json_parsing``;``build_longctx_system`` book-first 拼 system
  (会议记录吃前缀缓存:同一份会议不同功能共用前缀)。
- 截断续抽照搬 ``doc_spine._make_clause_continue_fn`` 的「靠信号不靠数量判」。
- 会议特有的证据锚错防护:同一人反复说「同意/好的」短引文跨轮复现率极高,evidence 必须摘长
  (prompt 层治本);核验层把结论项的**议程段序号**当弱先验传进 ``verify_citations`` 触发消歧
  (复用 ``citation_check`` 的 ``_disambiguate_by_chapter``,跟公文传自报章号同机制)。

不碰端点 / fixture / 前端——这一层只产出会脉的行动项台账 dict;端点该返的结构写在
``action_ledger_from_meeting`` 的 docstring 里给主 Claude 接线。
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

MEETING_SPINE_SCHEMA_VERSION = "v1"
"""会脉记录结构版本——升级要让这层重算(与文脉 / 章脉 SCHEMA_VERSION 同理)。"""

# 含金量三档(会议版,封闭集)。**开环/闭环判断框架复用公文 ``redhead_codebook``**(见
# ``_meeting_codebook_block``),但**叶子档名换成会议版「空头表态」**(公文是「空头倡导」——
# 公文拍板的对应物是倡导,会议是表态)。顺序就是轻重缓急排序权重(真金白银 > 有条件兑现 >
# 空头表态)。作者拍板叶子档名用「空头表态」(WP-1.7 §六 第 1 点)。
MEETING_SUBSTANCE_LEVELS: tuple[str, ...] = ("真金白银", "有条件兑现", "空头表态")
_DEFAULT_MEETING_SUBSTANCE = "有条件兑现"
"""含金量落不进三档的兜底——退「有条件兑现」(最中性,不替用户断成真金白银 / 空头)。"""

# 公文叶子档名 → 会议叶子档名的别名映射。模型偶尔会输出公文版「空头倡导」(prompt 虽要求会议
# 版,但训练里公文/会议措辞接近),或老缓存里存的是公文档名——都归一到会议版,免得被当未知值
# 退兜底。键是「会被误输出的别名」,值是会议版正名。
_MEETING_SUBSTANCE_ALIASES: dict[str, str] = {"空头倡导": "空头表态"}

DEFAULT_MEETING_SPINE_MAX_TOKENS = 8000
"""结论项维单段输出与头要素维一次抽取的 max_tokens。

对齐 ``doc_spine.DEFAULT_DOC_SPINE_MAX_TOKENS``:一段几百轮发言可能抽出十几条
decision + action_item,每条带 evidence(摘长更费 token)+ 多字段;deepseek-v4-flash 把
reasoning_content 也算进 max_tokens(reference_reasoning_model_token_budget),给 8000
留足 reasoning 头。真被截断有 ``salvage_closed_objects`` 抢救 + ``continue_fn`` 续抽兜底。"""

_MEETING_SEG_MAX_CHAPTERS = 3
"""结论项维分段的议程段闸(收窄)。

会议一个议程段塞的结论项 + 摘长 evidence 比公文条款还占输出,所以收得跟公文条款维一样紧
(``doc_spine._DOC_CLAUSE_MAX_CHAPTERS=3``)。会议记录的 chunk 多半不带「章号」(议程不是章),
此时章闸不触发,靠 ``run_segments`` 的字数闸断段(向后兼容)。"""

_MEETING_CONTINUE_MAX_ROUNDS = 4
"""结论项维某段被截断时最多续抽几轮——每轮让模型「接着没抽完的结论项往下抽」,补满或某轮空了就停。"""

# 形态封闭集(= 顶层 form)。判不准默认「纪要」——纪要是更保守的下游期望(不会误开只有逐字稿
# 能跑的功能,如第四炮的立场弦外)。
MEETING_FORMS: tuple[str, ...] = ("逐字稿", "纪要")
_DEFAULT_FORM = "纪要"

# 纪要天生没有的 head 字段 → 空着时标 not_applicable,不标待核、不进「抽到 X/Y」分母。
# 纪要是编辑稿,很少逐字记「谁没来」——「缺席/列席」纪要常没有(同公文法规本体 N/A 区分的纪律)。
# 逐字稿是流水,没有编辑过的议题概述——「记录范围」逐字稿常没有。
_FORM_NA_HEAD_FIELDS: dict[str, frozenset[str]] = {
    "纪要": frozenset({"缺席/列席"}),
    "逐字稿": frozenset({"记录范围"}),
}

# ── 头要素维 ───────────────────────────────────────────────────────────────
# 头要素字段名 → 给模型的中文说明。一份会议记录一组,每个要素带一句撑它的原文。
_HEAD_FIELDS: dict[str, str] = {
    "会议主题": (
        "这场会的主题 / 名称。会议记录开头常有标题或一句「今天开 X 会」「X 第 N 次周会」;"
        "抽不到留空。"
    ),
    "会议时间": (
        "开会日期,原样照抄(如「2026年3月3日」「3月3日上午」)。这是跨会议追踪的排序锚,"
        "尽量抽准;逐字稿可能散在开头的寒暄白里。抽不到留空。"
    ),
    "主持人": (
        "谁主持这场会(影响「谁拍板算数」)。逐字稿里反复说「下面我们……」「这个就这么定」"
        "「咱进正题」的多半是主持人;纪要常直接写「主持人:X」「主持:X」。抽不到留空。"
    ),
    "参会人": (
        "到会的人,列出名字 + 角色(如「张三(PM)、李四(后端)」)。逐字稿从说话人标记里"
        "聚合(出现过「X:」的都是参会人);纪要常有规整名单(「参会人员:……」)。抽不到留空。"
    ),
    "缺席/列席": (
        "谁该来没来 / 谁只是列席旁听。多数记录没有(尤其纪要),抽不到留空,别硬凑。"
    ),
    "记录范围": (
        "这次会涵盖哪些议题,一句话概述(纪要常有「记录范围:……」;逐字稿是流水,"
        "没有就留空)。"
    ),
}

_INSTR_HEAD = (
    "你在给一份会议记录抽**会议头要素**。只依据下面的原文,抽得到才填、"
    "**抽不到就留空字符串,绝不编造、绝不猜**(尤其会议时间、参会人这类身份要素,宁可空着待核)。\n"
    "会议记录有两种形态,先判清这份是哪种(填 form 字段):\n"
    "- 逐字稿:带说话人标记(如「张三:……」「主持人:……」)、有口语、有寒暄跑题。"
    "这种能追到「谁原话怎么说的」。\n"
    "- 纪要:已整理过、按议题归并、写成「会议决定:……」「相关组负责……」这种,噪声少但常"
    "没有具体说话人。\n"
    "判不准时填「纪要」(更保守,不会误开只有逐字稿能跑的功能)。\n"
    "每个要素同时给一句**撑它的原文逐字片段**(原样摘录、不改写)挂在 evidence 里;某要素的原文"
    "找不到就连同该要素一起留空。\n"
    "要抽的要素:\n"
    + "".join(f"- {k}:{v}\n" for k, v in _HEAD_FIELDS.items())
    + "严格输出 JSON(别的话别说、别加 markdown 围栏),形如:\n"
    '{"form":"逐字稿","elements":[{"field":"会议主题","value":"","evidence":""},'
    '{"field":"会议时间","value":"","evidence":""}]}'
)

# ── 结论项维(决议 + 行动项)─────────────────────────────────────────────────
def _meeting_codebook_block() -> str:
    """会议版措辞刻度块(判含金量套这把尺)——注进结论项 prompt。

    复用 ``redhead_codebook`` 的开环/闭环框架,但**换成会议适配的拍板语/推诿语/表态温差刻度**
    (公文那套「应当/不得」式标志词会议不灵),叶子档名用会议版「空头表态」(公文是「空头倡导」)。
    """
    return (
        "【会议措辞刻度(判含金量套这把尺,别只看字面)】\n"
        "- 真拍板语(定了的信号):「就这么定」「同意」「通过」「OK,按这个来」"
        "+ 有人接了带时间的任务。\n"
        "- 软搁置语(听着像定了、实则没定):「再研究研究」「会后再议」「原则上同意」「下次会上定」"
        "「我考虑考虑」——这些不算决议。\n"
        "- 推诿/踢皮球语(责任没落地的信号):「这个不归我们」「得看上面意思」「等 X 部门先动」"
        "「回头安排个人」——owner 多半落空。\n"
        "- 表态温差(同样是同意,分量差很远):「完全支持,明天就排期」是真金白银;"
        "「嗯,可以吧」「先这样吧」偏空头表态。\n"
        "- 含金量(开环/闭环判,真金白银/有条件兑现/空头表态):\n"
        "    · 真金白银:闭环——明确拍板 + 有 owner + 有 due + 有验收/复盘安排。"
        "有问责回路、不办有人追 → 会兑现。\n"
        "    · 空头表态:开环——纯表态(「大家重视」)/「回头弄」、无 owner、无 due、无下文。"
        "纯号召、无反馈回路 → 漂没。\n"
        "    · 有条件兑现:半闭环——有方向有人接但缺一环(如有 owner 无 due、有 due 无验收)。"
        "落不进两端时退这档(中性)。\n"
        "把判断锚在原文这些 marker 上(引哪句话/有无 owner/due/验收),别凭空给结论。"
    )


_INSTR_CONCLUSIONS = (
    "你在给一份会议记录做**结论项精读**。只针对下面这段原文,抽出这段里**真正定下来的事**和"
    "**谁要去做的事**。\n"
    "【最重要:抽的是结果,不是过程】\n"
    "会议记录大部分是发言流水——谁说了什么、寒暄、跑题、重复、口水话。"
    "**这些发言本身不是要抽的单元,它们是证据来源。** 你要从一段发言里淘出三五条干货:\n"
    "- 定了什么(decision)——这段会议**拍板下来**的事。\n"
    "- 谁要去做什么(action_item)——这段会议派下去 / 有人认领的**具体任务**。\n"
    "**绝不要**把「某某说了某某」逐条列成流水账。一段几百轮发言可能只对应两三条决议、"
    "三五个行动项,这是正常的——宁可少而准,别把讨论过程当成结论凑数。\n"
    "【会议结论埋着、不写明,靠上下文判,别只看字面】\n"
    "会议里一个决定常常没有标志词,是「那就这么定吧」「行,先这样」「我看可以,下周执行」这种。\n"
    "更要小心的是**很多事根本没拍板**:议而不决、和稀泥、「这个再议」「下次会上定」——"
    "这些是「悬着的事」,**不是决议、不是行动项**,这一炮先不抽它们(别抽出来就好),"
    "但**绝不能把没定的说成定了**。\n"
    "判断一件事到底定没定,看有没有:明确的拍板语(「就这么定」「同意」「通过」)、或有人接了"
    "具体任务带了时间。只是「大家讨论了一下」「有人提议」但没人拍板的,不算决议。\n"
    "【抽 decisions(决议),每条给】:\n"
    "1. 序号(chapter):整数,本段内从 1 顺排(跨段全局序号由系统重排,你只管本段)。\n"
    "2. decision:定了什么,一句话中性陈述。**只写真定下来的**,别把「提议」「讨论」写成「决定」。\n"
    "3. decided_by:谁拍的板(主持人 / 某人 / 集体表决)。锚到参会的人;纪要里只能到「会议」"
    "这一级也行;抽不到留空。\n"
    "4. background:为什么定 / 依据 / 背景,一句话;抽不到留空。\n"
    "5. substance(含金量):用下面措辞刻度里的开环/闭环判,**只能填「真金白银」「有条件兑现」"
    "「空头表态」之一**:有明确拍板语 + 具体安排(谁、何时、怎么验收)→ 真金白银;纯表态"
    "(「这事很重要,大家重视」)、无具体安排无时限无责任人 → 空头表态;介于两者 → 有条件兑现。\n"
    "6. substance_reason:凭原文里**哪些 marker** 判成这档(有无拍板语 / 有无具体安排 / 有无后续"
    "验收,锚原文,别空说);判不出留空。\n"
    "7. evidence:拍板那句**逐字原文**。**务必摘足够长、带上下文的整句**(见下方「证据要摘长」)。\n"
    "【抽 action_items(行动项),每条给】:\n"
    "1. 序号(chapter):整数,本段内从 1 顺排(与 decisions 各自独立编号,系统会分别重排)。\n"
    "2. task:要做的事,一句话。\n"
    "3. owner:谁负责。锚到参会的人。"
    "**没人接 / 没点名谁做的,留空——这是关键信号(说明这个任务没落实到人),"
    "绝不替它编一个负责人。**\n"
    "4. due:什么时候前完成(「下周一前」「3月10日」「这周内」)。"
    "**抽到才填,抽不到留空,绝不编一个时间。**\n"
    "5. from_decision:这个行动项是落实哪条决议的,填那条决议的**本段序号**;"
    "不是从某条决议来的就填 null。\n"
    "6. source:谁交代的 / 谁认领的(「张三让李四去办」里 source 是张三、owner 是李四;"
    "「我来跟进」里 source 和 owner 是同一人)。抽不到留空。\n"
    "7. substance:同决议的三档判。有 owner + 有 due + 有验收安排=真金白银;无 owner 无 due 的"
    "「回头弄一下」=空头表态;介于两者=有条件兑现。\n"
    "8. substance_reason:凭哪些 marker 判(点出 owner/due/验收的有无,锚原文);判不出留空。\n"
    "9. evidence:交代这个任务那句**逐字原文**,**务必摘足够长、带上下文的整句**。\n"
    "【证据要摘长(这一条最重要,违反会让系统锚错地方)】\n"
    "会议里同一个人会反复说话,「同意」「好的」「可以」这种短句在一份记录里到处都是。"
    "如果 evidence 只摘「同意」两个字,系统没法判断这是哪一轮说的,会锚到最先出现的那个"
    "「同意」——锚错地方。\n"
    "**所以每条 evidence 必须摘一整句、带前后文的完整发言**,比如不要摘「下周一前」,要摘"
    "「Eng-B:接口我来写,下周一前给你们出个初版,你们先接着调」整句。"
    "摘得越长越独特,系统越锚得准。逐字稿就连说话人标记一起摘(「张三:……」)。\n"
    "【抽不到就留空,绝不编】\n"
    "owner 没人接→留空;due 没说→留空;background 没讲→留空。空着是诚实,编一个是错误。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏),形如:\n"
    '{"decisions":[{"chapter":1,"decision":"","decided_by":"","background":"",'
    '"substance":"有条件兑现","substance_reason":"","evidence":""}],'
    '"action_items":[{"chapter":1,"task":"","owner":"","due":"","from_decision":null,'
    '"source":"","substance":"有条件兑现","substance_reason":"","evidence":""}]}'
    "\n\n" + _meeting_codebook_block()
)

_USER_MSG = "请按上面的要求抽结构。"

# 决议维除 chapter/evidence/substance 外要保留的字符串字段。
_DECISION_STR_FIELDS = ("decision", "decided_by", "background", "substance_reason")
# 行动项维除 chapter/evidence/substance/from_decision/loose_end 外要保留的字符串字段。
_ACTION_STR_FIELDS = ("task", "owner", "due", "source", "substance_reason")


def _coerce_form(value: Any) -> str:
    """形态归一:必须落进封闭集,落不进退「纪要」(更保守的下游期望)。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in MEETING_FORMS else _DEFAULT_FORM


def _coerce_meeting_substance(value: Any) -> str:
    """含金量归一(会议版):落进会议三档,公文档名「空头倡导」先归一到会议版「空头表态」,
    都落不进退「有条件兑现」(中性兜底)。

    **不直接复用 ``redhead_codebook.coerce_substance``**:那个的封闭集是公文版(叶子=「空头倡导」),
    会把会议版「空头表态」当未知值退兜底。这里复用它的开环/闭环判据框架(在 codebook block 里),
    但封闭集换成会议三档(叶子=「空头表态」),并把公文档名当别名收一下(模型偶尔吐公文版 / 老缓存)。
    """
    s = value.strip() if isinstance(value, str) else ""
    s = _MEETING_SUBSTANCE_ALIASES.get(s, s)
    return s if s in MEETING_SUBSTANCE_LEVELS else _DEFAULT_MEETING_SUBSTANCE


def _coerce_decision(item: Any) -> dict[str, Any] | None:
    """把一条决议 dict 归一;chapter(本段序号)缺/非整数 → 丢(没序号摆不进会脉)。

    含金量走封闭集归一(带原文撑的标签,不是分数);其余字段是字符串,缺退空串、抽不到不编。
    """
    if not isinstance(item, dict):
        return None
    ch = item.get("chapter")
    if not isinstance(ch, int):
        return None
    out: dict[str, Any] = {
        "chapter": ch,
        "evidence": str(item.get("evidence", "")).strip(),
        "substance": _coerce_meeting_substance(item.get("substance")),
    }
    for field in _DECISION_STR_FIELDS:
        v = item.get(field)
        out[field] = v.strip() if isinstance(v, str) else ""
    return out


def _coerce_action(item: Any) -> dict[str, Any] | None:
    """把一条行动项 dict 归一;chapter 缺/非整数 → 丢。

    含金量走封闭集归一;``from_decision`` 收成 int 或 None(非整数一律 None);``loose_end``
    这里**不收模型的值**——它由 BE 在重排后纯计算(owner 空 or due 空),prompt 也没让模型填。
    其余字段是字符串,缺退空串、抽不到不编(owner/due 空是信号不是缺陷)。
    """
    if not isinstance(item, dict):
        return None
    ch = item.get("chapter")
    if not isinstance(ch, int):
        return None
    from_decision = item.get("from_decision")
    out: dict[str, Any] = {
        "chapter": ch,
        "from_decision": from_decision if isinstance(from_decision, int) else None,
        "evidence": str(item.get("evidence", "")).strip(),
        "substance": _coerce_meeting_substance(item.get("substance")),
    }
    for field in _ACTION_STR_FIELDS:
        v = item.get(field)
        out[field] = v.strip() if isinstance(v, str) else ""
    return out


def _make_conclusions_parser():  # noqa: ANN202 — 返回闭包 parse_fn 喂 run_segments
    """造结论项维的 parse_fn:strip 围栏 → loads → 抠首个 obj → 截断抢救 → 归一去重。

    一次抽两类(decisions + action_items),所以解析出的「一条」是一个 ``{"_kind", ...}`` 标了
    类别的 dict——``run_segments`` 只认 ``list[dict]``,这里把两类塞进一个 list、各带 ``_kind``
    标记,合并时再按 ``_kind`` 分桶。两类各自的本段序号(chapter)互不干扰(分别去重)。
    """

    def _coerce_list(obj: Any) -> list[dict[str, Any]]:
        if not isinstance(obj, dict):
            return []
        out: list[dict[str, Any]] = []
        seen_dec: set[int] = set()
        for it in obj.get("decisions") or []:
            d = _coerce_decision(it)
            if d is None or d["chapter"] in seen_dec:
                continue
            seen_dec.add(d["chapter"])
            out.append({"_kind": "decision", **d})
        seen_act: set[int] = set()
        for it in obj.get("action_items") or []:
            a = _coerce_action(it)
            if a is None or a["chapter"] in seen_act:
                continue
            seen_act.add(a["chapter"])
            out.append({"_kind": "action", **a})
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
            items = _coerce_list(obj)
            if items:
                return items
        # 截断抢救:decisions / action_items 任一抢救到就拼起来。
        salvaged_dec = salvage_closed_objects(candidate, '"decisions"') or []
        salvaged_act = salvage_closed_objects(candidate, '"action_items"') or []
        if salvaged_dec or salvaged_act:
            items = _coerce_list(
                {"decisions": salvaged_dec, "action_items": salvaged_act}
            )
            if items:
                logger.warning(
                    "meeting_spine[conclusions]: 主解析失败,从截断抢救到 %d 条", len(items)
                )
                return items
        return None

    return _parse


def _parse_head(text: str) -> dict[str, Any] | None:
    """解析头要素维一次抽取 ``{form, elements:[{field,value,evidence}]}``。

    三层兜底同结论项维。返 ``{"form": 归一后的形态, "elements": {field:{value,evidence}}}``;
    只收 field 落进 ``_HEAD_FIELDS`` 的(模型自造的字段名丢掉)。解析不出返 None。
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
    form = _DEFAULT_FORM
    elements: Any = None
    if isinstance(obj, dict):
        form = _coerce_form(obj.get("form"))
        elements = obj.get("elements")
    if not isinstance(elements, list):
        salvaged = salvage_closed_objects(candidate, '"elements"')
        if salvaged:
            logger.warning("meeting_spine[head]: 主解析失败,从截断抢救头要素")
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
        out[field] = {
            "value": value,
            "evidence": str(el.get("evidence", "")).strip(),
        }
    return {"form": form, "elements": out}


def _build_head_elements(
    *,
    full_text: str,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    max_tokens: int,
    cache_enabled: bool,
    form_override: str | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """头要素维:一次抽取整份会议记录的头要素 + 判 form → 每要素 evidence 过 verify_citations。

    抽不到 / 解析不出 / 调用失败 → 返**全要素留空待核**的骨架(verified=False),不编。
    每要素结构:``{field, value, evidence, verified, match_score[, not_applicable]}``。
    返回 ``(elements, form)``——form 是判出的形态(``form_override`` 传了就用它,不再让模型判)。
    """
    parsed: dict[str, Any] | None = None
    try:
        system = build_longctx_system(full_text, _INSTR_HEAD)
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
        logger.warning(
            "meeting_spine[head]: 抽取抛 %s: %s;头要素全留空待核", type(exc).__name__, exc
        )
        parsed = None

    parsed = parsed or {}
    form = _coerce_form(form_override) if form_override else parsed.get("form", _DEFAULT_FORM)
    cells: dict[str, dict[str, str]] = parsed.get("elements") or {}

    elements: list[dict[str, Any]] = []
    for field in _HEAD_FIELDS:  # 按固定顺序产出全部要素(没抽到的也出一条空待核)
        cell = cells.get(field) or {}
        elements.append({
            "field": field,
            "value": cell.get("value", ""),
            "evidence": cell.get("evidence", ""),
            "verified": False,
            "match_score": 0.0,
        })

    # 每要素 evidence 过 verify_citations:核不过(含 evidence 空)→ verified=False 标待核。
    # 整份原文兜底——会议头(主题/时间/参会人)常在「正文」之前的开头白里,可能被分块层切碎,
    # 整份原文是真原文,拿它兜底锚定不违背 evidence-first(同 doc_spine 的整份兜底)。
    evidence_map = build_evidence_map(chunks)
    if full_text.strip():
        evidence_map["__doc_full_text__"] = {"chapter": 0, "text": full_text}
    citations = [{"snippet": el["evidence"]} for el in elements]
    verify_citations(citations, evidence_map)
    for el, vc in zip(elements, citations, strict=True):
        el["verified"] = bool(vc.get("verified", False))
        el["match_score"] = vc.get("match_score", 0.0)

    # N/A 区分:按 form 标这种形态天生没有的字段(纪要常没「缺席/列席」、逐字稿常没「记录范围」)。
    # 空着时标 not_applicable=True,前端显「本形态无此项」而非「待核」,且不计入「抽到 X/Y」分母。
    na_fields = _FORM_NA_HEAD_FIELDS.get(form, frozenset())
    for el in elements:
        if el["field"] in na_fields and not str(el["value"]).strip():
            el["not_applicable"] = True

    return elements, form


def _verify_conclusion_evidence(
    records: list[dict[str, Any]], chunks: list[dict[str, Any]]
) -> None:
    """逐条结论项给 evidence 过 verify_citations 附 verified/match_score——**但绝不动本段序号**。

    同 ``doc_spine._verify_clause_evidence`` 的纪律:只核证据、不覆盖序号(序号由
    ``_renumber`` 跨段全局顺排,保住每一条)。

    会议特有的锚错防护(``reference_verify_citations_anchoring_limit``):同一人反复说「同意/好的」
    短引文跨轮复现率极高,多命中时 ``verify_citations`` 会锚到第一个出现的 chunk。这里把这条
    结论项所属 chunk 的「议程段序号」(chunk 的 ``chapter``,会议里语义是议程段)当**弱先验**
    塞进 ``snippet`` 的 ``chapter`` 字段触发消歧——多命中时优先选本议程段内的 chunk。prompt 层
    已要求 evidence 摘长治本,这里是核验层的二道防护。
    """
    evidence = build_evidence_map(chunks)
    # 弱先验:这条结论项来自哪个议程段?用它所属 chunk 的 chapter(议程段序号)。结论项 dict
    # 自己不带议程段号(map 阶段没记),但 evidence 摘长 + 议程段弱先验都是为消歧——这里退而
    # 取「整份里这条 evidence 首次出现在哪个 chunk」作弱先验:对短引文(易锚错)给个所属段的
    # 倾向。拿不到就不传(_disambiguate_by_chapter 无先验时退回确定性首个,向后兼容)。
    norm_chunks = [
        (str(c.get("chunk_id", "")), c.get("chapter"), str(c.get("text", "")))
        for c in chunks
    ]
    citations: list[dict[str, Any]] = []
    for r in records:
        ev = str(r.get("evidence", "")).strip()
        prior = _infer_segment_prior(ev, norm_chunks)
        cit: dict[str, Any] = {"snippet": ev}
        if prior is not None:
            cit["chapter"] = prior
        citations.append(cit)
    verify_citations(citations, evidence)
    for rec, vc in zip(records, citations, strict=True):
        rec["verified"] = bool(vc.get("verified", False))
        rec["match_score"] = vc.get("match_score", 0.0)


def _infer_segment_prior(
    evidence: str, norm_chunks: list[tuple[str, Any, str]]
) -> Any:
    """给一条 evidence 推它所属议程段序号当弱先验(取它首次作为子串出现的 chunk 的 chapter)。

    用归一化子串(去空白 + 全半角)判命中,跟 ``verify_citations`` 同口径。拿不到(evidence 空 /
    没命中 / chunk 不带 chapter)返 None——此时不传先验,消歧退回确定性首个(向后兼容)。
    这只是给「同人反复短发言」一个本段倾向,最终命中 chunk 仍由 verify_citations 定。
    """
    from bookscope.agent.citation_check import normalize_text

    if not evidence:
        return None
    needle = normalize_text(evidence)
    if not needle:
        return None
    for _cid, chapter, text in norm_chunks:
        if not isinstance(chapter, int):
            continue
        if needle in normalize_text(text):
            return chapter
    return None


def _renumber(seg_outs: list[list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    """跨段把结论项拍平 + 分两类各自全局重排序号,行动项的 from_decision 跟着改。

    同 ``doc_spine._renumber_clauses`` 的纪律:每段都从「第 1 条」起自己数(map 引擎按段独立抽),
    跨段会撞号。会议结论项是单文件里一条线、天然有序,合并就是**按段序拼接**(段按议程顺序排 →
    拼出来就是会议进程顺序)再全局顺排序号——不靠模型自报的段内号去重。

    决议、行动项**各自独立编号**(decisions 1…M、action_items 1…N)。行动项的 ``from_decision``
    在段内指的是**本段决议序号**,全局重排后要映射成全局决议序号——这里逐段建「本段决议序号 →
    全局决议序号」映射,改 action 的 from_decision(跨段对不上 / null 的置 None,绝不瞎指)。

    去重只去**整条 evidence 完全相同**的(同一结论项被相邻段都抽到);序号不同但内容不同的全保留。
    """
    decisions_flat: list[dict[str, Any]] = []
    actions_flat: list[dict[str, Any]] = []
    seen_dec_ev: set[str] = set()
    seen_act_ev: set[str] = set()

    for seg in seg_outs:
        # 段内分两类,各按模型自报序号排稳(map 引擎不保证段内已排序)。
        seg_dec = sorted(
            (r for r in seg if r.get("_kind") == "decision"),
            key=lambda c: c["chapter"] if isinstance(c.get("chapter"), int) else 0,
        )
        seg_act = sorted(
            (r for r in seg if r.get("_kind") == "action"),
            key=lambda c: c["chapter"] if isinstance(c.get("chapter"), int) else 0,
        )
        # 本段决议:边收边记「本段序号 → 这条决议在 decisions_flat 里的全局序号」。
        local_to_global: dict[int, int] = {}
        for dec in seg_dec:
            ev = str(dec.get("evidence", "")).strip()
            if ev and ev in seen_dec_ev:
                continue
            if ev:
                seen_dec_ev.add(ev)
            local_chapter = dec["chapter"]
            decisions_flat.append(dec)
            local_to_global[local_chapter] = len(decisions_flat)  # 1 起的全局序号
        # 本段行动项:from_decision 用本段映射改成全局决议序号(对不上 / null → None)。
        for act in seg_act:
            ev = str(act.get("evidence", "")).strip()
            if ev and ev in seen_act_ev:
                continue
            if ev:
                seen_act_ev.add(ev)
            fd = act.get("from_decision")
            act["from_decision"] = local_to_global.get(fd) if isinstance(fd, int) else None
            actions_flat.append(act)

    # 全局顺排序号(各自 1 起),去掉 _kind 内部标记,行动项纯计算 loose_end。
    decisions: list[dict[str, Any]] = []
    for i, dec in enumerate(decisions_flat, start=1):
        dec.pop("_kind", None)
        dec["chapter"] = i
        decisions.append(dec)
    actions: list[dict[str, Any]] = []
    for i, act in enumerate(actions_flat, start=1):
        act.pop("_kind", None)
        act["chapter"] = i
        # loose_end 由 BE 纯计算:owner 空 或 due 空 = 悬而未办(信号不是缺陷)。
        act["loose_end"] = not str(act.get("owner", "")).strip() or not str(
            act.get("due", "")
        ).strip()
        actions.append(act)

    return {"decisions": decisions, "action_items": actions}


def _make_conclusions_continue_fn(
    *,
    llm_client: Any,
    model: str,
    max_tokens: int,
    cache_enabled: bool,
):  # noqa: ANN202 — 返回闭包 continue_fn 喂 run_segments
    """造结论项维的续抽回调:某段被 max_tokens 截断只抽回部分结论项时,接着把剩下的补抽回来。

    照搬 ``doc_spine._make_clause_continue_fn`` 的「靠信号不靠数量判」:一段抽了多少结论项数不
    出来,模型上轮 ``finish_reason=length`` 就再发一轮「接着没抽完的结论项往下抽」,直到某轮没补到
    新结论项 / 也没再被截断 / 补满 ``_MEETING_CONTINUE_MAX_ROUNDS`` 轮。用本模块的结论项 parser。
    """
    from bookscope.agent._internal.loop_shared import read_openai_finish_reason

    parse = _make_conclusions_parser()

    def _continue(
        seg: list[dict[str, Any]], partial: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        seg_text = "".join(str(c.get("text", "")) for c in seg)
        extra: list[dict[str, Any]] = []
        got = len(partial)
        for _round in range(_MEETING_CONTINUE_MAX_ROUNDS):
            cont_instr = (
                _INSTR_CONCLUSIONS
                + f"\n\n注意:你上次已经抽完了本段前 {got} 条结论项,被长度截断了。"
                + "现在请**只抽你还没抽的、本段剩下的决议和行动项**,接着往下抽,"
                + "别重复前面抽过的。"
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
                logger.warning(
                    "meeting_spine[conclusions]: 续抽调用抛 %s,停止续抽", type(exc).__name__
                )
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
            logger.warning(
                "meeting_spine[conclusions]: 段截断续抽补回 %d 条结论项", len(extra)
            )
        return extra

    return _continue


def action_ledger_from_meeting(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    form: str | None = None,
    owner: str | None = None,
    max_tokens: int = DEFAULT_MEETING_SPINE_MAX_TOKENS,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    max_workers: int | None = None,
    cache_enabled: bool = True,
) -> dict[str, Any]:
    """一份会议记录精读一次,出带证据的「会脉」行动项台账(head + decisions + action_items)。

    照 ``doc_spine.build_doc_spine`` 的套路,结论项维**不能整套照搬** ``mapreduce_per_chapter``:

    - **结论项维**走底层 ``run_segments``(分段 + 并发 + 截断兜底)+ 自接两步:逐段证据核验
      (``_verify_conclusion_evidence``,只核不动序号 + 会议议程段弱先验消歧)、跨段全局重排序号
      (``_renumber``,决议/行动项各自 1…N、行动项 from_decision 跟着改)。为什么不套
      ``mapreduce_per_chapter``:同公文条款维——它合并前会拿命中 chunk 的真章号覆盖记录序号,把
      同议程段的多条结论项压成一个号、去重后塌成个位数。截断丢条款靠 ``run_segments`` 自带的
      拆小重抽 + 结论项版续抽(``_make_conclusions_continue_fn``)两道兜底。
    - **头要素维**一次抽整份头要素 + 判 form,每要素 evidence 过 ``verify_citations``。

    三可靠性守卫焊死(``project_wholebook_feature_pattern``):① 给够 max_tokens 留 reasoning 头
    (8000 + 议程段闸收窄 + 续抽);② ``cache_enabled`` 透传(坏 JSON 在解析层就被三层兜底挡掉、
    不进缓存);③ 解析失败重试 + 截断抢救(``salvage_closed_objects`` + continue_fn)。

    Args:
        chunks: 这份会议记录的 chunk 列表,每条含 ``chunk_id`` / ``chapter``(=议程段号,会议里
            多半无、退 0) / ``text``。结论项序号由抽取后全局顺排,不取 chunk 的 chapter。
        llm_client: duck-typed LLM client(同 AgentLoop / 文脉)。
        model: 模型名。
        full_text: 这份会议记录的**完整原文**。传了头要素维就用它抽取 + 兜底锚定;不传则退回
            ``chunks`` 拼接(向后兼容)。
        form: 形态(``逐字稿`` | ``纪要``)。传了就用它当门控,不再让模型判;不传则头要素抽取里
            让模型判(判不准默认「纪要」)。
        owner: 「我的行动项」用——传了就只返 owner 字段命中这个身份的行动项(纯字符串包含匹配,
            大小写敏感按原样)。不传则返全部行动项(行动项台账)。
        max_tokens: 结论项维单段 + 头要素维一次抽取的 max_tokens。
        char_budget / max_workers: 透传给 ``run_segments`` 的分段预算 / 并发数。
        cache_enabled: 是否走 L2 缓存(默认开,同份会议重看命中)。

    Returns:
        ``{
            "schema_version": "v1",
            "form": "逐字稿" | "纪要",
            "owner": 回显请求的 owner(我的行动项时) / None(台账模式),
            "head": [{field, value, evidence, verified, match_score[, not_applicable]}],
            "decisions": [{chapter, decision, decided_by, background, substance,
                           substance_reason, evidence, verified, match_score}],
            "action_items": [{chapter, task, owner, due, from_decision, source, substance,
                              substance_reason, loose_end, evidence, verified, match_score}],
            "open_issues": [],   # 首炮恒空,schema 占位(第二炮再填)
        }``。
        头要素抽不到的要素出一条空待核记录(verified=False),绝不编。结论项空 → 对应列 ``[]``。
        ``action_items`` 按「先 loose_end 置顶、再按含金量(真金白银→空头表态)、再按序号」排——
        台账把没人接/没时限的黑洞捞到最前。传了 ``owner`` 时只含命中该身份的行动项(我的行动项)。

        **loose_end 由 BE 纯计算**(owner 空 or due 空),不让模型打分(``feedback_viz_algorithm_rigor``
        不许拍分的纪律)。**含金量复用公文开环/闭环三档**,叶子档名是会议版「空头表态」。
    """
    # 头要素维优先用传入的完整原文;没传退回 chunk 拼接(向后兼容)。
    head_full_text = full_text if (full_text and full_text.strip()) else "".join(
        str(c.get("text", "")) for c in chunks
    )

    head, resolved_form = _build_head_elements(
        full_text=head_full_text,
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        cache_enabled=cache_enabled,
        form_override=form,
    )

    # 结论项维:重型逐结论项(每条带 evidence + 多字段),收窄议程段闸 + 开续抽防截断丢结论项。
    # 不能套 mapreduce_per_chapter(理由同公文条款维),直接用底层 run_segments 自接核验 + 重排。
    continue_fn = _make_conclusions_continue_fn(
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        cache_enabled=cache_enabled,
    )
    seg_outs = run_segments(
        chunks=chunks,
        instruction=_INSTR_CONCLUSIONS,
        user_msg=_USER_MSG,
        parse_fn=_make_conclusions_parser(),
        llm_client=llm_client,
        model=model,
        max_tokens=max_tokens,
        char_budget=char_budget,
        max_chapters=_MEETING_SEG_MAX_CHAPTERS,
        max_workers=max_workers,
        cache_enabled=cache_enabled,
        continue_fn=continue_fn,
    )
    for seg in seg_outs:
        _verify_conclusion_evidence(seg, chunks)
    renumbered = _renumber(seg_outs)
    decisions = renumbered["decisions"]
    action_items = renumbered["action_items"]

    # 台账排序:① loose_end 置顶(黑洞捞取)② 含金量轻重缓急 ③ 序号。
    action_items.sort(key=lambda a: (
        0 if a.get("loose_end") else 1,
        _substance_rank(a.get("substance")),
        a["chapter"] if isinstance(a.get("chapter"), int) else 1_000_000,
    ))

    # 「我的行动项」:传了 owner 就只留 owner 命中这个身份的(纯字符串包含,任一方向都算)。
    if owner and owner.strip():
        needle = owner.strip()
        action_items = [
            a for a in action_items
            if needle in str(a.get("owner", "")) or str(a.get("owner", "")).strip() == needle
        ]

    return {
        "schema_version": MEETING_SPINE_SCHEMA_VERSION,
        "form": resolved_form,
        "owner": owner.strip() if (owner and owner.strip()) else None,
        "head": head,
        "decisions": decisions,
        "action_items": action_items,
        "open_issues": [],  # 首炮恒空,schema 占位
    }


def _substance_rank(level: Any) -> int:
    """含金量排序权重:真金白银=0 < 有条件兑现=1 < 空头表态=2,未知排最后。给台账排轻重缓急。"""
    s = level if isinstance(level, str) else ""
    return (
        MEETING_SUBSTANCE_LEVELS.index(s)
        if s in MEETING_SUBSTANCE_LEVELS
        else len(MEETING_SUBSTANCE_LEVELS)
    )


__all__ = [
    "MEETING_FORMS",
    "MEETING_SPINE_SCHEMA_VERSION",
    "MEETING_SUBSTANCE_LEVELS",
    "action_ledger_from_meeting",
]
