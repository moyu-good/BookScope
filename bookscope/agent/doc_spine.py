"""公文「文脉」(1.6 红头文件垂直地基)——章脉的公文版,一份公文精读一次出带证据的结构。

**它是什么**:章脉是「一本书 → 逐章带证据结构」,文脉是「一份公文 → 文件头要素 + 逐条款带证据结构」。
设计稿 `docs/design/WP-1.6-redhead-vertical-design.md` §1.2 定的两维:

- **头要素维**(文件级,一份一组):发文字号 / 密级 / 紧急程度 / 文种 / 发文机关 / 主送机关 /
  抄送机关 / 标题事由 / 成文日期 / 签发人。对 GB/T 9704 可验。每个要素挂原文、过
  ``verify_citations``,**抽不到就留空、绝不编**(§5.2:扫描件漏了发文字号宁可标待核让用户回
  原件,绝不靠模型猜一个填上)。
  其中**密级是产品级安全信号**(GB/T 9704 版头要素):抽到「绝密/机密/秘密」说明是涉密件,
  将来前端该据此提醒用户别把内容往云端 LLM 传(研究笔记 004 §3.1)。本层只负责把字段抽出来,
  提醒动作前端以后做。份号/印章/页码这类纯排版要素对「读懂文件说了什么」没用,不抽,省 token。
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
from bookscope.agent.redhead_codebook import (
    SUBSTANCE_LEVELS,
    codebook_block,
    coerce_substance,
)
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DOC_SPINE_SCHEMA_VERSION = "v3"
"""文脉记录结构版本——升级要让缓存整份失效(接 ADR-008,与章脉 SPINE_SCHEMA_VERSION 同理)。

v2(task #29):头要素加空值三态 + 机关层级。
v3:条款维支持叙述体公文(公报/意见把每个原则/部署各抽一条,不再压成一条)+ 新增「方针部署」
指令类型。prompt 结构变了,必须 bump 让旧缓存失效。"""

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

# 法规本体文种(去掉「令」——令是公布令,有发文字号/签发人/成文日期,属"发文"不是立法本体)。
# 这些是立法文本(地方性法规 / 部门规章),结构上压根没有发文字号/密级/紧急程度/主送/抄送/
# 签发人这些"发文"要素。给它们标 not_applicable(本文种无此项),区别于"待核"(该有却没抽到),
# 否则一份条例显"头要素 3/10、全待核"会让用户以为抽坏了,其实是文件本就没有那 6 项。
_REGULATION_PROPER_TYPES: frozenset[str] = frozenset(
    {"条例", "规定", "办法", "细则", "准则", "规则"}
)
# 法规本体天生没有的"发文"类头要素 → 空着时标 N/A,不标待核、不计入"抽到 X/Y"分母。
_REGULATION_NA_HEAD_FIELDS: frozenset[str] = frozenset(
    {"发文字号", "密级", "紧急程度", "主送机关", "抄送机关", "签发人"}
)

# ── 头要素空值三态(task #29 根一)──────────────────────────────────────────────
# evidence-first 的"空"分三态,别一律落"待核"(WP-evidence-empty-semantics §根一):
#   present          抽到了(+ 核过)——现状不变。
#   absent_confirmed 确证为无 / 本文种不适用——笃定答案,带 reason(公开件无密级、此文种无
#                    签发人栏、平件未标紧急、法规本体无发文要素…)。前端显笃定的"公开 / 无 /
#                    不适用",不显"待核"。
#   unverified       真没抽到 / 没核到——才显"待核"。
HEAD_STATUS_PRESENT = "present"
HEAD_STATUS_ABSENT_CONFIRMED = "absent_confirmed"
HEAD_STATUS_UNVERIFIED = "unverified"
HEAD_STATUSES: tuple[str, ...] = (
    HEAD_STATUS_PRESENT,
    HEAD_STATUS_ABSENT_CONFIRMED,
    HEAD_STATUS_UNVERIFIED,
)

# 文种封闭集 = 法定公文文种 + 法规/公布令文种。文种识别只能落在这个集合里,
# 落不进就留空标待核——不让模型自造一个「文种」(§5.2 GB/T 要素绝不编)。
DOC_TYPES: tuple[str, ...] = _STATUTORY_DOC_TYPES + _REGULATION_DOC_TYPES

# 指令类型五标签(封闭集)。**这是公文版的「张力」,绝不让模型拍 0-10 分**——做成带原文撑的
# 分类标签。落不进这五类的退「信息告知」(最弱、最不会误导用户去办事的兜底)。
#
# 前四类按**约束力**分,适配分条式公文(条例/规定:逐条有责任主体 + 时限 + 罚则)。
# 第五类「方针部署」是为**叙述体公文**(公报/意见/讲话/通知里的方针段)加的:这类文件讲的是
# 原则 / 方向 / 部署 / 工作安排,既不是「应当/必须」式的硬要求(往往没有逐条的责任主体和时限)、
# 又比「单纯告知数据」的信息告知重——它是号令全局怎么干的方向性要求。比如公报里「必须遵循以下
# 原则,坚持党的全面领导……」「全会提出,建设现代化产业体系」,每一条都是一个方针 / 部署点,
# 该各自成一条钉到原文,不能压成一条空泛的「遵循以下原则」。这一类专门收叙述体的原则 / 方向 /
# 部署 / 要求,不影响分条式公文(它们的条款仍落硬要求 / 软倡导 / 依据陈述)。
INSTRUCTION_TYPES: tuple[str, ...] = (
    "硬要求",    # 应当/必须/不得/限X日前 —— 有法定约束力、必须执行
    "软倡导",    # 鼓励/提倡/支持/可以 —— 倡导性、无强制
    "方针部署",  # 坚持X/建设X/推进X —— 叙述体公文的原则/方向/部署点(方向性要求,无逐条主体时限)
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
    "密级": (
        "文件的保密等级,只认这三档:「绝密」「机密」「秘密」(GB/T 9704 版头要素)。"
        "常写在版头左上角,如「机密★1年」「秘密」。抽到照填(只填密级词,「★X年」保密期限别带进来);"
        "**抽不到留空**——绝大多数公开红头文件不标密级,留空是常态,绝不硬凑。"
    ),
    "紧急程度": (
        "文件的紧急等级,只认这两档:「特急」「加急」(GB/T 9704 版头要素;电报类用「特提」"
        "「特急」「加急」「平急」,纸质件常见「特急」「加急」)。常写在版头,如「特急」。"
        "抽到照填,**抽不到留空**——多数文件不标紧急程度,留空是常态,绝不硬凑。"
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
        "**地方性法规没有署名行**:成文日期取标题下括注的通过日期——如"
        "「(2020年10月28日广州市……人大常委会……通过 2020年11月27日……批准)」"
        "取通过日「2020年10月28日」(有上级批准日时,通过日即成文日)。别因为没有署名行就留空。"
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
    "**成文日期取标题下「(X年X月X日……通过)」括注里的通过日期**——地方性法规没有署名行,"
    "别因为找不到署名行就把成文日期留空;"
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

# ── 看结构(结构即信号)维:doc 级 structure_read ────────────────────────────────
# WP-redhead-deep-reading-lenses §二「看结构」那一层落到产品的判断层。这是**评估层**:
# 权威刻度的"分量"研判 + 结构信号都是推断(标研判、绝不盖鉴印),但层级 / 缺席 / 排序是从
# **已核的 head / clauses 事实**推的,每条引到具体要素——不另发 LLM,纯计算(deterministic),
# 既省 token 又天然 evidence-first(算的都是已核事实,无脑补空间)。
#
# 效力层级刻度(WP §二:令 > 部委规章 > 地方性法规 > 通知/意见 > 函)。键是层级标签(封闭集),
# 值是 (rank 排序权重越小越高, 一句"这层级什么分量"的研判模板)。判层级只看**已抽的文种 + 发文
# 机关**两个已核事实,落不进就退「一般公文」(中性,不替用户拔高)。
_AUTHORITY_LEVELS: tuple[str, ...] = (
    "公布令/法规",   # 国务院令 / 主席令 / X令 + 条例/规定/办法等法规本体
    "地方性法规",     # 人大常委会通过的地方条例
    "部门规章/规范性文件",  # 部委发的规定/办法/细则(规章)
    "指令性公文",     # 决定/命令/批复等下行硬指令
    "一般公文",       # 通知/意见/通报等(中性兜底)
    "商洽函",         # 函(平行,商洽询问,约束力最弱)
)
_AUTHORITY_RANK = {lv: i for i, lv in enumerate(_AUTHORITY_LEVELS)}

# 层级 → "这层级多大分量、能管到谁、会否被上位覆盖"的一句研判(WP §二的产品落点)。
# 这是**推断**——前端标研判口径,绝不盖鉴印;但它锚在已核的文种/机关上(由调用处引具体要素)。
_AUTHORITY_APPRAISAL: dict[str, str] = {
    "公布令/法规": "效力高、稳定性强——公布令 / 法规是上位规范，下位文件须服从它，"
                   "一般不会被普通通知意见覆盖；改它要走立法 / 修订程序。",
    "地方性法规": "在本行政区划内有法律效力，稳定性强——管得到本地各方，"
                  "但要服从国家法律 / 行政法规这些上位规范，可能被上位法覆盖。",
    "部门规章/规范性文件": "在本部门 / 本系统职权范围内有约束力——管得到本系统对象，"
                          "但效力低于法律法规，可能被上位法或更高层级文件调整。",
    "指令性公文": "下行硬指令、有明确约束力——直接管到收文的下级机关；"
                  "但属一份具体公文，稳定性弱于法规，后续文件可调整或废止。",
    "一般公文": "属常规行文(通知 / 意见 / 通报这类)，约束力看正文措辞而非文种本身——"
                "能管到主送机关，但容易被后续同类或上位文件覆盖、更新。",
    "商洽函": "平行商洽 / 询问，没有上下级强制力——是协商性质，对方可办可不办。",
}
_DEFAULT_AUTHORITY_LEVEL = "一般公文"

# ── 发文机关行政层级(task #29 根二)──────────────────────────────────────────────
# 效力研判除文种外要吃**发文机关的行政层级**(WP-evidence-empty-semantics §根二):同样一个
# 「意见」,国务院办公厅发的跟县政府发的分量天差地别。光按文种一刀切,会把国办《意见》判成
# "一般公文、容易被上位覆盖"——错。层级从已抽的「发文机关」头要素判,deterministic、引原文。
AGENCY_LEVEL_TOP = "最高"      # 国务院 / 国办 / 中共中央 / 中办——全国约束、上位极少
AGENCY_LEVEL_HIGH = "高"      # 部委 / 省级党委政府——本系统 / 本省权威
AGENCY_LEVEL_MID = "中低"     # 市 / 县——地方层级
_AGENCY_LEVELS: tuple[str, ...] = (AGENCY_LEVEL_TOP, AGENCY_LEVEL_HIGH, AGENCY_LEVEL_MID)

# 最高层级机关名标志(出现即判最高)。国务院办公厅 / 中共中央办公厅都含"国务院"/"中共中央",
# 单列"国办""中办"简称兜底。全国人大及其常委会是最高国家权力机关,也归最高。
_TOP_AGENCY_MARKERS: tuple[str, ...] = (
    "国务院", "国办", "中共中央", "中央办公厅", "中办",
    "全国人民代表大会", "全国人大",
)
# 高层级:部委(以"部""委员会""总局""总署""署""局"结尾的国家级)、省级党委政府。市/县在更下,
# 用"省/自治区/直辖市 + 人民政府/党委"判;命中省级关键词且不含市/县 → 高。
_PROVINCE_MARKERS: tuple[str, ...] = ("省", "自治区", "直辖市")
_MINISTRY_MARKERS: tuple[str, ...] = ("部", "国家", "总局", "总署")
_MID_AGENCY_MARKERS: tuple[str, ...] = ("市", "县", "区", "乡", "镇")

# 普通公文的"身份要素"——缺了就存疑/非正式(WP §二缺席信号)。只对**非法规、非 N/A** 的公文报:
# 法规本体天生没有发文字号/成文日期这些"发文"要素(已被 not_applicable 标过),报它们=误报。
_IDENTITY_HEAD_FIELDS: tuple[str, str] = ("发文字号", "成文日期")

# 文种 → 行文方向(上行/下行/平行)的先验。判 instruction_type 要先看这份公文是上行还是下行——
# 同一句「请……」在「请示」(下级求上级批)和「命令」(上级号令下级)里约束力天差地别,光看措辞
# 容易把上行文的请求误判成对下级的硬要求(研究笔记 004 §3.2 排第一的系统性误判)。
# 「意见/通知/纪要」可上可下、语境定方向,不在这三张表里 → 当方向不定处理。
_UPWARD_DOC_TYPES: tuple[str, ...] = ("请示", "报告", "议案")
"""上行文(下级报上级):本质是请求/汇报,不是对收文方下命令。"""
_DOWNWARD_DOC_TYPES: tuple[str, ...] = (
    "命令", "决定", "决议", "公报", "公告", "通告", "通报", "批复",
)
"""下行文(上级对下级):才谈得上对下级的硬要求/软倡导。"""
_PARALLEL_DOC_TYPES: tuple[str, ...] = ("函",)
"""平行文(平级):商洽/询问,多是软倡导/信息告知。"""

# ── 条款维 ─────────────────────────────────────────────────────────────────
_INSTR_CLAUSE = (
    "你在给一份党政机关公文做**逐条款精读**。只针对下面这段原文,逐条款抽,只抽本段出现的条款,"
    "不臆测、不编造。条款序号用整数(没有显式编号就按出现顺序从 1 顺排)。\n"
    "**公文有两类写法,抽法不同,先认准是哪类:**\n"
    "(A) **分条式**(条例 / 规定 / 办法这类法规,有「第X条」逐条编号):一个「第X条」就是一条,"
    "照编号逐条抽。\n"
    "(B) **叙述体**(公报 / 意见 / 讲话 / 通知这类,讲方针 / 原则 / 部署 / 要求,**没有逐条编号、"
    "也常没有逐条的责任主体和时限**):这类**绝不能因为没有「第X条」就只抽出一两条**,要把每个"
    "**独立的要点 / 原则 / 部署 / 工作安排 / 要求**都抽成单独一条。具体怎么切:\n"
    "   - 一句话里**排比列出**的多个原则 / 方向(如「必须遵循以下原则,坚持A,坚持B,坚持C,"
    "坚持D」),**每一个「坚持X」就是一条**,六个原则抽成六条,各自钉到对应那半句原文,"
    "**绝不压成一条空泛的「遵循以下原则」**。\n"
    "   - 每个「全会提出,……」「要……」「坚持……」「加快……」「建设……」「推进……」领起的"
    "独立部署 / 工作安排,各自成一条。\n"
    "   - 同一段里讲了好几件不同的事,就拆成好几条;别把一整段几百字囫囵当一条。\n"
    "   叙述体抽不到「第X条」编号是正常的,序号按出现顺序从 1 顺排即可;**没有责任主体 / 时限也"
    "照样抽这一条**(留空那两个字段),绝不因为「缺主体缺时限」就跳过一个真实的部署 / 原则。\n"
    "**死守:无论哪类,抽出的每一条都必须是原文里真有的要点 / 部署 / 原则,evidence 能在本段找到"
    "对应原句。绝不为了多抽就把一句话硬拆成几条注水、绝不编原文没有的条款。**\n"
    "判指令类型前先看这份公文的**文种 + 行文方向**(在版头/标题里):\n"
    f"   - 上行文({'/'.join(_UPWARD_DOC_TYPES)}):下级报上级,内容是**请求/汇报**——"
    "里头的「请……」「拟……」「恳请批准」是向上求批,**别判成对下级的硬要求**,"
    "多是依据陈述/信息告知;真正的硬要求只在上级回的批复里才有。\n"
    f"   - 下行文({'/'.join(_DOWNWARD_DOC_TYPES)}):上级对下级号令,"
    "**才有对下级的硬要求/软倡导**。\n"
    f"   - 平行文({'/'.join(_PARALLEL_DOC_TYPES)}):平级商洽/询问,多是软倡导/信息告知。\n"
    "   - 通知/意见/纪要可上可下,看正文是号令下级还是汇报上级定方向。\n"
    "每条款给:\n"
    "1. 事项(matter):这一条在说什么事,一句话。\n"
    "2. 指令类型(instruction_type):**只能填以下五个标签之一**,按原文措辞 + 上面的行文方向判,"
    "不准打分:\n"
    "   - 硬要求:有「应当/必须/不得/严禁/限X日前/予以」等强制措辞,有法定约束力——"
    "**前提是下行文**;上行文里同样的措辞是向上请求,不算对下级的硬要求。\n"
    "   - 软倡导:有「鼓励/提倡/支持/可以/原则上」等倡导措辞,无强制。\n"
    "   - 方针部署:叙述体公文里的**原则 / 方向 / 部署 / 工作安排**——「坚持X」「建设X」「推进X」"
    "「加快X」这类号令全局怎么干的方向性要求。它比「信息告知」重(是要去干的方向)、又不像「硬要求」"
    "那样有逐条主体 + 时限 + 罚则。公报 / 意见里的原则和部署点大多落这一类。\n"
    "   - 信息告知:单纯告知情况/通报数据/人事任免,不要求收文方办什么。\n"
    "   - 依据陈述:「根据X」「为贯彻Y」这类陈述行文依据,本身不是要求;上行文的请求事项也归这里。\n"
    "3. 责任主体(actor):这一条要谁来办(主语机关/部门);**没有明确主体就留空**,叙述体公文的"
    "原则 / 部署常常没点名具体哪个部门,留空是常态,绝不硬塞一个。\n"
    "4. 时限(deadline):什么时候前完成/生效/管到哪天;**抽到才填,抽不到留空,绝不编**——"
    "叙述体的方针部署多没有时限,留空是常态。\n"
    "5. 依据引用(basis_ref):这一条引了哪份上位文件——抽出被引文件的**字号或标题**;没引留空。\n"
    "6. evidence:这一条里最能代表上面判定的一句原文逐字片段(原样摘录、不改写)。\n"
    "7. 含金量(substance):这条是真要办还是做做样子——用下面措辞刻度里的开环/闭环判,"
    "**只能填「真金白银」「有条件兑现」「空头倡导」之一**:有硬约束词 + 数字 / 时限 / 责任主体 / "
    "罚则齐全的闭环条款 → 真金白银;纯倡导词(鼓励/支持/探索)、无数字无时限无主体无罚则的开环号召 "
    "→ 空头倡导;介于两者(有指令有主体但缺数字/时限/罚则之一)→ 有条件兑现。信息告知 / 依据陈述"
    "这类本不要求办事的,也退「有条件兑现」(中性)。叙述体的方针部署 / 原则**绝大多数没有数字 / "
    "时限 / 责任主体 / 罚则**(是方向性号召),按开环判 → 多落「空头倡导」或「有条件兑现」,"
    "别只因为口气坚定(坚持 / 必须)就判「真金白银」:真金白银要的是配套兑现回路,不是语气。\n"
    "8. 含金量理由(substance_reason):凭原文里**哪些 marker** 判成这档(点出约束词/数字/时限/"
    "主体/罚则的有无,锚原文,别空说);判不出留空。\n"
    "9. 不办的代价(penalty):这条**不办会怎样**——原文里写了罚则/问责/考核/通报/追责的,"
    "摘出那个后果(如「予以通报问责」「纳入年度考核」「逾期不予受理」);**原文没写代价就留空**,"
    "绝不替它编一个后果(没罚则=空,正好印证它是空头/软倡导)。\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"clauses":[{"chapter":条款序号整数,"matter":"","instruction_type":"信息告知",'
    '"actor":"","deadline":"","basis_ref":"","evidence":"","substance":"有条件兑现",'
    '"substance_reason":"","penalty":""}]}'
    "\n\n" + codebook_block()
)

_USER_MSG = "请按上面的要求抽结构。"

# 条款维除 chapter/evidence/substance 外要保留的字段(都是字符串)。substance 走封闭集归一,
# 单列出来不混进字符串组。substance_reason / penalty 是 1.6.1 加的含金量层字段(向后兼容,
# 抽不到留空)——penalty 留空正好印证这条没罚则(空头/软倡导)。
_CLAUSE_STR_FIELDS = (
    "matter", "instruction_type", "actor", "deadline", "basis_ref",
    "substance_reason", "penalty",
)


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

    指令类型 + 含金量走封闭集归一(带原文撑的标签,不是分数);其余字段是字符串,缺退空串、抽不到
    不编。``substance`` / ``substance_reason`` / ``penalty`` 是 1.6.1 含金量层(向后兼容):老缓存
    没这几个字段时,substance 退「有条件兑现」(中性)、reason/penalty 退空串,绝不替它编代价。
    """
    if not isinstance(item, dict):
        return None
    ch = item.get("chapter")
    if not isinstance(ch, int):
        return None
    out: dict[str, Any] = {
        "chapter": ch,
        "evidence": str(item.get("evidence", "")).strip(),
        "substance": coerce_substance(item.get("substance")),
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


def _confirmed_absent_reason(field: str, doc_type: str) -> str | None:
    """某个**空着**的头要素,是不是"确证为无 / 本文种不适用"?是就返一句站得住的 reason。

    evidence-first 死守(WP-evidence-empty-semantics §根一铁律):reason 必须基于文种 / GB/T
    9704 公文格式规则,不是瞎判"无"。拿不准的(可能该有却没抽到)一律返 None → 退 ``unverified``
    标"待核",绝不硬判"确证无"。判据只看**已抽的文种**(已核事实),deterministic、无脑补。

    三类确证为无(都基于公文格式规则):

    - **密级**:GB/T 9704 版头要素,只有涉密件才标(绝密/机密/秘密);绝大多数公开红头文件
      本就没有密级 → 空 = 公开件无密级(确证,不是没抽到)。
    - **紧急程度**:版头要素,只有特急/加急件才标;多数文件是平件不标 → 空 = 平件(未标紧急)。
    - **签发人**:GB/T 9704 只要求**上行文**(请示/报告/议案,下级报上级)标签发人;下行文
      (意见/通知/命令…)与平行文(函)本就没有签发人栏 → 这些文种空 = 此文种无签发人栏。
      上行文该有签发人却空,是真没抽到 → 返 None 退待核。
    - **法规本体**(条例/规定/办法…):立法文本不是"发文",结构上没有发文字号/密级/紧急程度/
      主送/抄送/签发人这些发文要素 → 空 = 法规本体无此发文要素。

    Args:
        field: 头要素字段名。
        doc_type: 已抽到的文种(已过封闭集归一);空串表示文种没抽到。

    Returns:
        确证为无时返 reason(一句话依据);可能该有却没抽到 → 返 ``None``(退待核)。
    """
    dt = (doc_type or "").strip()
    # 法规本体:发文类要素天生没有(立法文本不是发文)。最优先——条例的密级/签发人都归这条。
    if dt in _REGULATION_PROPER_TYPES and field in _REGULATION_NA_HEAD_FIELDS:
        return "法规本体无此发文要素"
    if field == "密级":
        return "公开件无密级"
    if field == "紧急程度":
        return "平件(未标紧急)"
    if field == "签发人":
        # 上行文该有签发人,空着是真没抽到 → 退待核;下行 / 平行 / 方向不定的文种本就没有。
        if dt in _UPWARD_DOC_TYPES:
            return None
        return "此文种无签发人栏"
    return None


def _classify_head_status(field: str, value: str, doc_type: str) -> tuple[str, str]:
    """给一个头要素定三态(present / absent_confirmed / unverified)+ reason。

    - value 非空 → ``present``(reason 空)。
    - value 空 + :func:`_confirmed_absent_reason` 给得出依据 → ``absent_confirmed`` + reason。
    - value 空 + 给不出依据 → ``unverified``(reason 空,前端显"待核")。
    """
    if value.strip():
        return HEAD_STATUS_PRESENT, ""
    reason = _confirmed_absent_reason(field, doc_type)
    if reason is not None:
        return HEAD_STATUS_ABSENT_CONFIRMED, reason
    return HEAD_STATUS_UNVERIFIED, ""


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
    每要素结构:``{field, value, evidence, verified, match_score, status, reason
    [, not_applicable]}``。文种已过封闭集归一。``status``(task #29 根一)是空值三态
    (present / absent_confirmed / unverified):据已抽文种把"确证为无"(公开件无密级、下行文
    无签发人栏、平件未标紧急、法规本体无发文要素)标 ``absent_confirmed`` + ``reason``、并对齐旧
    ``not_applicable=True``;真没抽到才退 ``unverified``(前端显"待核")。
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

    # 空值三态(task #29 根一):每个要素的"空"分 present / absent_confirmed / unverified。
    # 据**已抽的文种**(已核事实)判:密级空=公开件无密级、签发人空+下行文=此文种无签发人栏、
    # 紧急空=平件、法规本体的发文要素空=本文种无此项……这些是 absent_confirmed(确证无,带
    # reason、前端显笃定的"公开/无/不适用");真没抽到的退 unverified(前端才显"待核")。
    # absent_confirmed ⟺ not_applicable=True(向后兼容旧字段):前端据 not_applicable 不计入
    # "抽到 X/Y"分母、看结构层的缺席信号也跳过它(确证无不是"缺失存疑")。
    doc_type = next(
        (str(el["value"]).strip() for el in elements if el["field"] == "文种"), ""
    )
    for el in elements:
        status, reason = _classify_head_status(el["field"], str(el["value"]), doc_type)
        el["status"] = status
        el["reason"] = reason
        # 旧字段 not_applicable 保留并对齐新三态:确证无 = 不适用(不计分母 / 不报缺席)。
        if status == HEAD_STATUS_ABSENT_CONFIRMED:
            el["not_applicable"] = True
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


def _head_value(head: list[dict[str, Any]], field: str) -> dict[str, Any]:
    """取某头要素整条(value/evidence/verified/not_applicable);没有返空骨架。看结构维用。"""
    for el in head:
        if el.get("field") == field:
            return el
    return {"value": "", "evidence": "", "verified": False, "not_applicable": False}


def _classify_agency_level(issuer: str) -> str:
    """据**已抽的发文机关**判行政层级(最高 / 高 / 中低),判不出返空串。task #29 根二。

    deterministic 串匹配已核机关名,无脑补:

    - **最高**:国务院 / 国办 / 中共中央 / 中办 / 全国人大(及其常委会)——全国约束、上位极少。
    - **高**:部委(国家级"部 / 委 / 总局 / 总署")、省级党委政府(省 / 自治区 / 直辖市 + 政府/
      党委,且不含市 / 县)。
    - **中低**:市 / 县 / 区 / 乡 / 镇这类地方层级。
    - 判不出(机关空 / 认不出)→ 空串,效力研判退回只按文种(向后兼容)。

    优先级:最高 > 中低标志(市/县出现即拉到中低,免得"XX市国务院派出机构"误判) > 省级/部委。
    其实更稳的序是先扣最高,再看有没有市/县(中低),再省级(高),最后部委(高)。
    """
    iss = (issuer or "").strip()
    if not iss:
        return ""
    if any(m in iss for m in _TOP_AGENCY_MARKERS):
        return AGENCY_LEVEL_TOP
    # 市 / 县 / 区 / 乡 / 镇出现 → 中低(地方)。先于省级判:"XX省XX市"这种以更低的市为准。
    if any(m in iss for m in _MID_AGENCY_MARKERS):
        return AGENCY_LEVEL_MID
    # 省 / 自治区 / 直辖市级党委政府 → 高。
    if any(m in iss for m in _PROVINCE_MARKERS):
        return AGENCY_LEVEL_HIGH
    # 国家级部委 / 总局 / 总署 → 高。
    if any(m in iss for m in _MINISTRY_MARKERS):
        return AGENCY_LEVEL_HIGH
    return ""


def _high_authority_appraisal(agency_level: str, issuer: str) -> str | None:
    """高层级发文机关(最高 / 高)的效力研判覆盖句——点出权威范围,**绝不说"容易被覆盖"**。

    WP-evidence-empty-semantics §根二死规矩:国务院 / 国办这类最高层级文件,哪怕文种是「意见」
    (文种维度归"一般公文"),也不准用"一般公文、容易被上位覆盖"那套话术研判它——要点出它的
    全国约束力、上位极少。中低层级不覆盖(返 None,仍用文种维度的研判)。
    """
    iss = (issuer or "").strip()
    who = f"「{iss}」" if iss else "该机关"
    if agency_level == AGENCY_LEVEL_TOP:
        return (
            f"{who}是最高层级发文机关——这份文件有全国范围的约束力，下位文件都得服从它，"
            "其上几乎没有更高的行政规范能覆盖它。哪怕文种是意见 / 通知，也是顶格权威，"
            "绝不是可有可无的一般公文。"
        )
    if agency_level == AGENCY_LEVEL_HIGH:
        return (
            f"{who}是高层级发文机关(部委 / 省级)——在本系统 / 本行政区划内是权威规范，"
            "管得到下面各方，一般只服从国家法律法规和更高层级文件，同级或下位文件覆盖不了它。"
        )
    return None


def _classify_authority(doc_type: str, issuer: str) -> str:
    """据**已抽的文种 + 发文机关**判效力层级,落进 :data:`_AUTHORITY_LEVELS` 封闭集。

    只看两个已核事实(文种 / 机关),deterministic、无脑补:

    - 「令」(公布令) → 公布令/法规;法规本体(条例/规定/办法…)默认归法规,机关是人大常委会的
      细分到「地方性法规」、是部委的细分到「部门规章」。
    - 下行硬指令文种(命令/决定/批复…)→ 指令性公文。
    - 「函」→ 商洽函(平行,最弱)。
    - 其余(通知/意见/通报…)或判不出 → 「一般公文」中性兜底,不替用户拔高也不打死。
    """
    dt = (doc_type or "").strip()
    iss = (issuer or "").strip()
    is_npc = "人民代表大会常务委员会" in iss or "人大常委会" in iss
    if dt == "令":
        return "公布令/法规"
    if dt in _REGULATION_PROPER_TYPES:  # 条例/规定/办法/细则/准则/规则
        if is_npc:
            return "地方性法规"
        # 国务院/中央本级公布的条例(无地方人大、无行政区划前缀)归公布令/法规;
        # 部委发的规定/办法/细则按规章处理。条例本身多由立法机关定,默认法规。
        if dt == "条例":
            return "地方性法规" if is_npc else "公布令/法规"
        return "部门规章/规范性文件"
    if dt in _DOWNWARD_DOC_TYPES:  # 命令/决定/决议/批复…
        return "指令性公文"
    if dt in _PARALLEL_DOC_TYPES:  # 函
        return "商洽函"
    return _DEFAULT_AUTHORITY_LEVEL


def _build_structure_read(
    head: list[dict[str, Any]], clauses: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """看结构(结构即信号)维:从**已核的 head / clauses 事实**推 doc 级 structure_read。

    WP-redhead-deep-reading-lenses §二落到产品的判断层。**评估层**——权威刻度的"分量"研判 +
    结构信号都是推断(前端标研判口径、绝不盖鉴印),但全部锚在已抽要素上:层级引文种 / 机关、
    缺席信号引具体缺的要素、排序信号引具体条款。不另发 LLM(纯计算),既省 token 又无脑补空间。

    死守:

    - **法规 N/A 的不报缺席信号**——法规本体天生没有发文字号 / 成文日期(已被 ``not_applicable``
      标过),只对非 N/A 且真空的身份要素报"存疑/非正式"。这是不误报的命门。
    - **层级只看已抽文种 / 机关**两个事实,落不进退「一般公文」(中性),不替用户断成高效力。
    - 文种都没抽到(空)→ 返 None(没有可判层级的事实根基,不硬造一个 structure_read)。

    Returns:
        ``{
            "authority": {level, rank, doc_type, doc_type_evidence, issuer,
                          issuer_evidence, agency_level, appraisal, verified_basis},
            "signals": [{kind: "missing"|"ordering"|"weight", element, note}],
        }``;文种空(判不了层级)返 None。``agency_level``(最高/高/中低/空,task #29 根二)是
        据发文机关判的行政层级;最高 / 高层级时 ``appraisal`` 已被覆盖成点权威范围的研判,
        不再说"容易被上位覆盖"。
    """
    wenzhong = _head_value(head, "文种")
    doc_type = str(wenzhong.get("value", "")).strip()
    if not doc_type:  # 连文种都没抽到 → 没根基判层级,不硬造
        return None

    issuer_el = _head_value(head, "发文机关")
    issuer = str(issuer_el.get("value", "")).strip()

    level = _classify_authority(doc_type, issuer)
    # 根二:效力研判除文种外吃发文机关行政层级。最高 / 高层级机关(国务院/国办/部委/省级)的
    # 文件,哪怕文种归"一般公文",也要点出全国 / 本系统约束力,绝不说"容易被上位覆盖"。
    agency_level = _classify_agency_level(issuer)
    appraisal = _AUTHORITY_APPRAISAL.get(
        level, _AUTHORITY_APPRAISAL[_DEFAULT_AUTHORITY_LEVEL]
    )
    high_appraisal = _high_authority_appraisal(agency_level, issuer)
    if high_appraisal is not None:
        appraisal = high_appraisal
    # verified_basis:层级研判的两个事实(文种 + 机关)是否都来自已核 head。
    # 机关空时只凭文种判,verified_basis 看文种这一条核没核过(机关缺不算造假,只是依据更薄)。
    basis_verified = bool(wenzhong.get("verified")) and (
        not issuer or bool(issuer_el.get("verified"))
    )
    authority = {
        "level": level,
        "rank": _AUTHORITY_RANK.get(level, len(_AUTHORITY_LEVELS)),
        "doc_type": doc_type,
        "doc_type_evidence": str(wenzhong.get("evidence", "")).strip(),
        "issuer": issuer,
        "issuer_evidence": str(issuer_el.get("evidence", "")).strip(),
        "agency_level": agency_level,  # 最高 / 高 / 中低 / 空(判不出);引发文机关 evidence
        "appraisal": appraisal,
        "verified_basis": basis_verified,
    }

    signals: list[dict[str, str]] = []

    # ① 缺席信号:普通公文缺身份要素(发文字号/成文日期)=存疑/非正式。
    #    死守不误报:法规 N/A 标过的不算(法规本就没这些发文要素),只报非 N/A 且真空的。
    for field in _IDENTITY_HEAD_FIELDS:
        el = _head_value(head, field)
        if el.get("not_applicable"):
            continue  # 法规本体无此项 → 不是缺席信号
        if not str(el.get("value", "")).strip():
            signals.append({
                "kind": "missing",
                "element": field,
                "note": f"缺「{field}」——正式红头文件该有这项，没有可能是非正式件 / 草稿 / "
                        "扫描漏抽，这份文件的正式性存疑（建议回原件核对）。",
            })

    # ② 排序信号:第一条款的责任主体 = 牵头(WP §二"署名/排序谁在前=牵头")。
    #    引到具体条款(第几条 + 谁),不空说;只在确有带 actor 的条款时报。
    actor_clauses = [c for c in clauses if str(c.get("actor", "")).strip()]
    if len(actor_clauses) >= 2:
        first = actor_clauses[0]
        signals.append({
            "kind": "ordering",
            "element": f"第 {first.get('chapter')} 条",
            "note": f"排在最前、最先点名的责任主体是「{str(first.get('actor')).strip()}」——"
                    "公文里排序常含主次，排第一的多为牵头方，后面的偏配合（仅供参考）。",
        })

    # ③ 篇幅/构成信号:指令类型构成暴露文件性质。全是软倡导=倡导性文件(没硬约束)、
    #    硬要求占多数=动真格的指令件。引条款占比,不空说;只在有条款时报。
    if clauses:
        types = [str(c.get("instruction_type", "")).strip() for c in clauses]
        hard = types.count("硬要求")
        soft = types.count("软倡导")
        total = len(clauses)
        if hard == 0 and soft > 0:
            signals.append({
                "kind": "weight",
                "element": f"{soft}/{total} 条软倡导、0 条硬要求",
                "note": "全文没有一条「应当/必须/不得」式硬要求——这是一份倡导性文件，"
                        "落实与否主要靠自觉，约束力弱。",
            })
        elif hard >= 1 and hard >= total - hard:
            signals.append({
                "kind": "weight",
                "element": f"{hard}/{total} 条硬要求",
                "note": "硬要求占了多数——这份文件动真格的成分高，多数条款有法定约束力、要执行。",
            })

    return {"authority": authority, "signals": signals}


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
            "schema_version": "v3",
            "head": [{field, value, evidence, verified, match_score, status, reason
                      [, not_applicable]}],  # status=空值三态(task #29 根一)
            "clauses": [{chapter, matter, instruction_type, actor, deadline, basis_ref,
                         evidence, verified, match_score,
                         substance(真金白银/有条件兑现/空头倡导),  # 1.6.1 含金量层
                         substance_reason,                          # 凭哪些 marker 判的(锚原文)
                         penalty}],                                  # 不办的代价(无罚则=空)
        }``。
        头要素维抽不到的要素出一条空记录,绝不编。条款维空 → ``clauses: []``。

        **空值三态层**(task #29 根一,向后兼容、纯增字段):每个头要素带 ``status``
        (present / absent_confirmed / unverified)+ ``reason``。"空"不再一律落"待核"——据已抽
        文种把"确证为无"(公开件无密级、下行文无签发人栏、平件未标紧急、法规本体无发文要素)标
        ``absent_confirmed`` + reason(前端显笃定的"公开 / 无 / 不适用"),真没抽到的才 ``unverified``
        (前端显"待核")。``absent_confirmed`` 同时对齐旧 ``not_applicable=True``
        (不计分母 / 不报缺席)。

        **1.6.1 给「办事清单」加的含金量层**(向后兼容,纯增字段):每条条款多带 ``substance``
        (办事清单据此分「真要办 vs 做做样子」+ 按含金量排轻重缓急)、``substance_reason``、
        ``penalty``(不办的代价,无罚则留空——正好印证它是空头/软倡导)。这层只增不改原有字段,
        公文结构解读端点拿同一份 clauses、忽略新字段也照常工作。

        **看结构(结构即信号)层**(向后兼容,新增可选 doc 级字段):返回多带一个
        ``structure_read`` dict(与 head/clauses 并列),含 ``authority``(权威刻度:据已抽文种 +
        发文机关判效力层级 + 一句"多大分量/能管到谁/会否被上位覆盖"的研判)+ ``signals``
        (0~N 条结构信号:缺身份要素=存疑、排序=牵头、篇幅构成=文件性质)。这是**评估层**——
        分量研判 + 信号是推断(前端标研判口径、绝不盖鉴印),但锚在已核要素上(引文种/机关/具体
        缺的要素/具体条款),纯计算不另发 LLM。**法规 N/A 标过的要素不报缺席信号**(不误报)。
        文种空(判不了层级)时不挂这个字段。head/clauses 一字不动。
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

    # 看结构(结构即信号)维:从已核的 head / clauses 推 doc 级 structure_read(权威刻度 + 结构
    # 信号)。纯计算、不另发 LLM;文种空(判不了层级)返 None,此时不挂 structure_read(向后兼容)。
    structure_read = _build_structure_read(head, clauses)

    out: dict[str, Any] = {
        "schema_version": DOC_SPINE_SCHEMA_VERSION,
        "head": head,
        "clauses": clauses,
    }
    if structure_read is not None:
        out["structure_read"] = structure_read
    return out


def build_doc_head_only(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    max_tokens: int = DEFAULT_DOC_SPINE_MAX_TOKENS,
    cache_enabled: bool = True,
) -> dict[str, Any]:
    """只建**头要素维 + 看结构维**的轻文脉——给「公文结构」骨架鸟瞰秒出用,跳过贵的条款维。

    公文结构视图(1.8.0 收窄成骨架鸟瞰)只显头要素 + structure_read(权威刻度 + 结构信号),
    不显逐条款(那是「逐条精读」的活)。但整套 ``build_doc_spine`` 的耗时大头是条款维
    ``run_segments`` 分段并发 map-reduce(那两分多钟);头要素维只是一次抽取(秒级)。所以公文
    结构若第一个被点、还没人建过完整文脉,没必要陪跑条款 map-reduce——只建 head 骨架即可,
    那两分钟留给用户真点「逐条精读」时(要深读本就愿意等)。

    **不写全文脉缓存**(调用方负责):本函数返的是 ``clauses: []`` 的轻文脉,绝不能落进
    ``doc_spines`` 缓存的全文脉 key——否则「逐条精读」命中它会拿到空条款。调用侧的规矩是:
    先 ``peek_doc_spine_cache`` 看有没有完整文脉,有就用完整的,没有才调本函数出骨架、且不缓存。

    ``structure_read`` 用空 clauses 推:authority(权威刻度)纯从 head 的文种 + 发文机关算、
    不依赖条款;条款相关信号(排序牵头 / 指令构成)在空 clauses 下自动跳过(``_build_structure_read``
    对空 clauses 安全)。所以骨架的 structure_read 是「权威 + 缺席信号」齐、条款级信号缺——
    正是骨架鸟瞰要的粒度。

    Returns:
        ``{"schema_version", "head", "clauses": [], "structure_read"?}``——与 ``build_doc_spine``
        同形,只是 ``clauses`` 恒空。文种没抽到时无 ``structure_read``(同 build_doc_spine)。
    """
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
    structure_read = _build_structure_read(head, [])
    out: dict[str, Any] = {
        "schema_version": DOC_SPINE_SCHEMA_VERSION,
        "head": head,
        "clauses": [],
        "head_only": True,  # 标记:这是轻文脉(没条款),前端 / 调用方可据此提示「深读点逐条精读」
    }
    if structure_read is not None:
        out["structure_read"] = structure_read
    return out


__all__ = [
    "AGENCY_LEVEL_HIGH",
    "AGENCY_LEVEL_MID",
    "AGENCY_LEVEL_TOP",
    "DOC_SPINE_SCHEMA_VERSION",
    "DOC_TYPES",
    "HEAD_STATUSES",
    "HEAD_STATUS_ABSENT_CONFIRMED",
    "HEAD_STATUS_PRESENT",
    "HEAD_STATUS_UNVERIFIED",
    "INSTRUCTION_TYPES",
    "SUBSTANCE_LEVELS",
    "build_doc_head_only",
    "build_doc_spine",
]
