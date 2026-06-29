"""跨会议层(1.7 会议垂直杀手价值)——多场会摆一起,追「谁承诺了、兑现没」。

**它是什么**:单场会的行动项台账(``meeting_spine.action_ledger_from_meeting``)只看一场会派了
什么活;这一层把好几场会摆一起,沿着时间线追一条承诺的下落——张三在 6 月周会说「下周交鉴权」,
到 7 月的会还没影,这条就该被标成「逾期 / 未兑现」捞出来。这是会议分析真正比「记纪要」强的地方,
跟公文跨文件的依据链网一个道理:价值不在单份,在跨单元的连线。

设计稿 ``WP-1.7-meeting-vertical.md`` §6.1 定的就是这条(杀手·发明区):公文跨文件连的是
「文件引文件」(依据 / 落实 / 废止),会议跨会连的是「人对人的承诺—兑现」——这不是换皮,是会议
独有的跨单元关系。

**怎么建(套现成的机器)**:走 ``cross_doc.py`` 反复验证的「脊 + 一次全局推理 + 锚回真实单元」
范式(``project_chapter_spine_turn``),单元从「文件」换成「会议」、关系从「依据」换成「承诺—兑现」:

1. **每场会先出会脉**(复用 ``action_ledger_from_meeting``):承诺 = 这场会的 action_items(谁、
   做什么、due);会议身份 = 会议时间 + 会议主题(从会脉 head 抽,没字号这一说)。
2. **收承诺清单 + 每场会的「兑现线索」**:把所有承诺按会议时间排成一条线(每条带 owner / task /
   due / 来自哪场会);同时把每场会的 decisions + action_items + open_issues 摘成「这场会提到了
   什么」当兑现信号的搜索池(在更晚的会里,这件事被说成做完了 / 又被当未决重提 / 压根没再提)。
3. **一次 LLM 全局推理**(走 ``invoke_client_cached``):对每条承诺,只在**它之后**的会里找兑现
   信号,判一个状态(兑现 / 未兑现 / 进行中 / 未知;逾期由 BE 据 due 纯算,不靠模型)。
4. **锚回真实单元 + 证据**:承诺锚到「哪场会第几条行动项」(锚不到丢);兑现证据锚到「哪场更晚的
   会、哪句原话」(那场会脉里已核验过的 evidence,锚不到退空——状态降格,绝不假装有据)。

**铁律(evidence-first,最重要,比公文更硬)**:
- **判不出兑现没就标「进行中 / 未知」,绝不猜「兑现」**。假阳性 = 最坏——等于骗用户「放心吧做完
  了」,他就不去追了。所以「兑现」这一档只在**更晚的会里有原话**说这事办成了、且那句原话锚得回
  真实会议时才给;锚不到证据的「兑现 / 未兑现」一律降格成「未知」(``_coerce_commitment``)。
- **逾期(overdue)由 BE 纯计算**,不让模型打这个标:只在「due 真过了(对到某场更晚的会的日期
  之前)+ 没有兑现证据」时才标——这是客观事实判断,不是模型研判(``feedback_viz_algorithm_rigor``
  不许拍分的纪律,逾期同理:能算就别让模型猜)。
- 承诺的 owner / due 抽不到就空(单场会脉已经守了这条),跨会这层不补、不编。

**复用了哪些骨架**(铁律:一行不改 ``cross_doc`` / ``meeting_spine`` / ``cross_doc_views`` 等现有
模块,只 import helper):
- 每场会脉走 ``action_ledger_from_meeting``(它自己焊死了三可靠性守卫:给够 token / 关缓存防
  poison / 重试截断;evidence 过 ``verify_citations``)。
- 一次全局推理走 ``invoke_client_cached``(吃 L2 缓存);JSON 三层兜底照搬 ``utils/json_parsing``。
- 状态封闭集纪律照搬 ``cross_doc.RELATION_KINDS``(模型推的 status 落不进封闭集就丢这条)。
- 参会人别名归一是 owner 聚合 / 跨会承诺匹配的命门(同一个人「张三」「张部长」「老张」要并成一个),
  但 Phase 1 先靠 prompt 提示模型把明显同人的归一,别名机器(``build_spine_name_map``)留到规模化
  (理由:跨会 owner 池小,先验证价值;过早上别名归一是 ``feedback_right_sized_method`` 说的复杂
  方法没有独有理由)。

不碰端点 / fixture / 前端——这一层只产出跨会承诺台账 dict;端点该返的结构写在
``commitments_across_meetings`` 的 docstring 里给主 Claude 接线。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from bookscope.agent._internal.exhaustive import DEFAULT_CHAR_BUDGET
from bookscope.agent._internal.llm_cache import invoke_client_cached
from bookscope.agent.citation_check import build_evidence_map, verify_citations
from bookscope.agent.meeting_spine import (
    DEFAULT_MEETING_SPINE_MAX_TOKENS,
    action_ledger_from_meeting,
)
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object,
    salvage_closed_objects,
    strip_code_fence,
)

logger = logging.getLogger(__name__)

DEFAULT_COMMITMENTS_MAX_TOKENS = 16000
"""一次全局推理把所有承诺的兑现状态全吐出来的 max_tokens。

deepseek-v4-flash 把 reasoning_content 算进 max_tokens(见
[[reference_reasoning_model_token_budget]])。状态条数 = 承诺数(每场会几条行动项 × 几场会),
加 reasoning 头;Phase 1 限几场会、几十条承诺,16000 够吐完;真撑爆靠 ``_parse_commitments``
截断抢救兜底。"""

# 兑现状态封闭集。LLM 推出的 status 必须落进这五类,落不进就丢这条(同 cross_doc 的
# RELATION_KINDS 纪律——不让模型自造状态)。**「兑现」要更晚的会里有原话坐实**才给,否则降级。
COMMITMENT_STATUSES: tuple[str, ...] = (
    "兑现",    # 更晚的会里有原话说这事办成了(锚得回真实会议才算数)
    "未兑现",  # 更晚的会里有原话说这事没做 / 又被当未决重提(同样要原话坐实)
    "逾期",    # due 真过了(到某场更晚的会之前)+ 没兑现证据——**由 BE 纯算,不收模型的**
    "进行中",  # 更晚的会里提到在做 / 部分做了,但没说做完
    "未知",    # 更晚的会里没再提这事,判不出下落——**判不准的默认归这档,绝不猜「兑现」**
)
_DEFAULT_STATUS = "未知"
"""状态落不进封闭集 / 兑现没原话坐实时的兜底——退「未知」(最诚实,不替用户断成兑现 / 未兑现)。"""

# 模型可能吐的近义说法 → 归一到封闭集正名(同 meeting_spine 别名的纪律)。模型不一定用 prompt 给
# 的词,把常见同义说法收一下,免得当未知值退兜底。注意:不收「逾期」的别名——逾期一律由 BE 算,
# 模型就算说「逾期」也当「未兑现」收(再由 BE 据 due 决定要不要升成逾期)。
_STATUS_ALIASES: dict[str, str] = {
    "已兑现": "兑现",
    "完成": "兑现",
    "已完成": "兑现",
    "做完了": "兑现",
    "落实了": "兑现",
    "未完成": "未兑现",
    "没做": "未兑现",
    "没兑现": "未兑现",
    "没落实": "未兑现",
    "推进中": "进行中",
    "在做": "进行中",
    "部分完成": "进行中",
    "部分兑现": "进行中",
    "没下文": "未知",
    "不清楚": "未知",
    "无法判断": "未知",
    "逾期": "未兑现",  # 模型说逾期先当未兑现收,逾期由 BE 据 due 算
}

# 会脉 head 里这两个要素是会议身份(没有公文那种发文字号)+ 跨会排序锚。
_HEAD_TITLE_FIELD = "会议主题"
_HEAD_DATE_FIELD = "会议时间"

# 一条承诺摘给 LLM 的「这件事后来怎样了」搜索池,每场会摘前几条够找兑现信号又不撑爆 input。
_MAX_SIGNALS_PER_MEETING = 12


_INSTR = (
    "下面给你一组**同一条线上的多场会议**,按开会时间从早到晚排好了(meetings)。每场会有:\n"
    "- mid:这场会的编号(整数,照抄)。\n"
    "- 会议主题 / 会议时间:这场会是哪场。\n"
    "- 这场会后来提到的事(signals):这场会的决议 / 行动项 / 还悬着的议题,每条是一句话——"
    "**用来判前面几场会的承诺后来兑现没**。\n"
    "另外给你一张**承诺清单**(commitments),每条是某场会上谁答应要做的一件事:\n"
    "- cid:这条承诺的编号(整数,照抄)。\n"
    "- from_mid:这条承诺是哪场会上提的(对应上面某场会的 mid)。\n"
    "- owner:谁承诺的 / 这活归谁(可能空——没点名谁做的)。\n"
    "- task:答应要做的事。\n"
    "- due:什么时候前做完(可能空——没说时限)。\n"
    "你的任务:**对每一条承诺,只在它之后(开会时间更晚)的会里找这件事后来怎么样了**,判一个"
    "状态。会议分析真正有用的就是这一步——把「谁承诺了、后来兑现没」跨会追出来。\n"
    "【怎么判状态(死守:判不出就标未知,绝不猜兑现)】\n"
    "看**更晚那几场会的 signals 里**有没有提到这条承诺这件事:\n"
    "- 兑现:更晚的会里明说这事**办成了 / 做完了 / 已上线**(如下一场会提「鉴权接口已经接好了」)。"
    "**必须是更晚的会里真有这句话**,不能因为时间到了就默认做完了。\n"
    "- 未兑现:更晚的会里明说这事**没做 / 还没动 / 又被当成没解决重新提**(如下一场会又把同一件事"
    "当待办重新派一遍、或有人说「上次说的那个还没弄」)。\n"
    "- 进行中:更晚的会里提到**在做 / 做了一部分**,但没说做完(如「鉴权写了一半,还在调」)。\n"
    "- 未知:**更晚的会里压根没再提这件事**,看不出下落。**判不准、没把握就归这档——这是最常见"
    "的,也是最诚实的。宁可标未知,绝不替它猜成兑现(猜错等于骗人说做完了)。**\n"
    "不要判「逾期」——时限过没过由系统按日期算,你只管从原话看做没做。\n"
    "【证据(这条最重要,违反会让系统把状态降级)】\n"
    "判成「兑现」「未兑现」「进行中」时,**必须**给出支撑这个判断的那句原话:\n"
    "- evidence_mid:支撑这个状态的那句话来自哪场更晚的会(填那场会的 mid,必须晚于 from_mid)。\n"
    "- evidence:那场会里**逐字**说这件事后来怎样了的原话(原样摘录、别改写、摘整句带上下文)。\n"
    "判成「未知」时不用给证据(本来就是没再提)。\n"
    "**没有更晚的会的原话支撑,就别判兑现 / 未兑现 / 进行中——归未知。** 系统会逐字核这句原话,"
    "对不上的会把状态降成未知。\n"
    "每条承诺输出一条记录:\n"
    "- cid:对应上面那条承诺的编号(照抄)。\n"
    "- status:**只能填「兑现」「未兑现」「进行中」「未知」之一**(别填逾期),落不进就填未知。\n"
    "- evidence_mid:支撑状态的更晚会议 mid(未知时填 null)。\n"
    "- evidence:那句逐字原话(未知时填空串)。\n"
    "- note:一句话说清你凭什么这么判(如「下一场会说接口已接好」);未知时可留空。\n"
    "**只判得出的才下结论,判不出一律未知。宁缺毋滥,绝不为了好看猜成兑现。**\n"
    "严格输出 JSON(别的话别说、别加 markdown 围栏):\n"
    '{"commitments":[{"cid":整数,"status":"未知","evidence_mid":null,"evidence":"","note":""}]}'
)

_USER_MSG = "请按上面的要求,逐条判每个承诺后来兑现没。"


def _head_value(spine: dict[str, Any], field: str) -> str:
    """从一份会脉的 head 里取某要素的 value(抽不到 / 没核到都返空串)。口径同 cross_doc。

    head 是 ``[{field, value, evidence, verified, match_score}]``,按 field 找那条取 value。
    """
    head = spine.get("head")
    if not isinstance(head, list):
        return ""
    for el in head:
        if isinstance(el, dict) and el.get("field") == field:
            return str(el.get("value", "")).strip()
    return ""


def _meeting_label(spine: dict[str, Any], fallback_idx: int) -> str:
    """一场会的展示标签 = 会议主题(没抽到退「第 N 场会」)。给前端分组标题用。"""
    title = _head_value(spine, _HEAD_TITLE_FIELD)
    return title if title else f"第 {fallback_idx + 1} 场会"


def _meeting_signals(spine: dict[str, Any]) -> list[str]:
    """把一场会脉摘成「这场会提到了什么」的一句话清单——给跨会判兑现当搜索池。

    决议(定了什么)+ 行动项(谁要做什么)+ 议而未决(还悬着什么)各摘一句,够让模型在更晚的会里
    认出「上次那件事这次被提了」。只摘文本不摘 evidence(省 input;真要原话时模型从证据池现摘,
    证据核验在 ``_attach_evidence`` 那步对回这场会脉的已核 evidence)。
    """
    out: list[str] = []
    for d in spine.get("decisions") or []:
        if not isinstance(d, dict):
            continue
        txt = str(d.get("decision", "")).strip()
        if txt:
            out.append(f"定了:{txt}")
        if len(out) >= _MAX_SIGNALS_PER_MEETING:
            return out
    for a in spine.get("action_items") or []:
        if not isinstance(a, dict):
            continue
        txt = str(a.get("task", "")).strip()
        if txt:
            who = str(a.get("owner", "")).strip()
            out.append(f"要做:{txt}" + (f"(归 {who})" if who else ""))
        if len(out) >= _MAX_SIGNALS_PER_MEETING:
            return out
    for o in spine.get("open_issues") or []:
        if not isinstance(o, dict):
            continue
        txt = str(o.get("issue", "")).strip()
        if txt:
            out.append(f"还悬着:{txt}")
        if len(out) >= _MAX_SIGNALS_PER_MEETING:
            return out
    return out


def _spine_evidence_pool(spine: dict[str, Any]) -> list[str]:
    """一场会脉里所有已核验过的 evidence 原话——给跨会兑现证据锚回用(只认核过的)。

    决议 / 行动项 / 议而未决三类里 ``verified=True`` 且 evidence 非空的那些。会脉建构时这些
    evidence 已过 ``verify_citations`` 锚到这场会的真原文,所以拿它们当「这场会真有的原话池」可靠。
    """
    pool: list[str] = []
    for key in ("decisions", "action_items", "open_issues"):
        for r in spine.get(key) or []:
            if not isinstance(r, dict):
                continue
            if r.get("verified") and str(r.get("evidence", "")).strip():
                pool.append(str(r["evidence"]).strip())
    return pool


def _collect_commitments(
    ledgers: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],   # 给 LLM 的 meetings 清单(mid + 主题 / 时间 + signals)
    list[dict[str, Any]],   # 给 LLM 的 commitments 清单(cid + from_mid + owner/task/due)
    dict[int, dict[str, Any]],  # cid → 这条承诺的全量信息(锚回 + 逾期算 + 输出用)
    dict[int, dict[str, Any]],  # mid → 这场会的元信息(label / 日期 / 证据池)
]:
    """从一摞会脉收 meetings 清单 + commitments 清单 + cid/mid 索引表。

    每场会脉已带 ``__order`` / ``__sort_key``(调用方按会议时间排过序后塞的)。承诺 = 这场会的
    action_items;每条承诺给个全局 cid,记住它来自哪场会(from_mid)、第几条行动项(item_chapter),
    锚回 / 逾期算都靠这俩。owner / due 照搬会脉里的(空就空,不补)。
    """
    meetings: list[dict[str, Any]] = []
    commitments: list[dict[str, Any]] = []
    by_cid: dict[int, dict[str, Any]] = {}
    by_mid: dict[int, dict[str, Any]] = {}

    cid = 0
    for mid, spine in enumerate(ledgers):
        if not isinstance(spine, dict):
            continue
        label = _meeting_label(spine, mid)
        date = _head_value(spine, _HEAD_DATE_FIELD)
        sort_key = str(spine.get("__sort_key", ""))
        by_mid[mid] = {
            "label": label,
            "date": date,
            "sort_key": sort_key,
            "evidence_pool": _spine_evidence_pool(spine),
        }
        meetings.append({
            "mid": mid,
            "会议主题": label,
            "会议时间": date,
            "signals": _meeting_signals(spine),
        })
        for act in spine.get("action_items") or []:
            if not isinstance(act, dict):
                continue
            task = str(act.get("task", "")).strip()
            if not task:
                continue  # 没说清要做什么的不当承诺追(锚不住)
            owner = str(act.get("owner", "")).strip()
            due = str(act.get("due", "")).strip()
            by_cid[cid] = {
                "cid": cid,
                "from_mid": mid,
                "item_chapter": act.get("chapter"),
                "owner": owner,
                "task": task,
                "due": due,
                "substance": act.get("substance", ""),
                "from_evidence": str(act.get("evidence", "")).strip(),
                "from_verified": bool(act.get("verified", False)),
            }
            commitments.append({
                "cid": cid,
                "from_mid": mid,
                "owner": owner,
                "task": task,
                "due": due,
            })
            cid += 1

    return meetings, commitments, by_cid, by_mid


# 模型能给的状态(逾期不在内——逾期一律 BE 据 due 算)。
_MODEL_STATUSES: frozenset[str] = frozenset({"兑现", "未兑现", "进行中", "未知"})


def _coerce_status(value: Any) -> str:
    """状态归一:落进模型四档(兑现 / 未兑现 / 进行中 / 未知),近义说法先归一,落不进退「未知」。

    「逾期」别名也先收成「未兑现」(模型不该自己判逾期);最终逾期由 ``_apply_overdue`` 据 due 升级。
    """
    s = value.strip() if isinstance(value, str) else ""
    s = _STATUS_ALIASES.get(s, s)
    if s == "逾期":  # 模型直接吐「逾期」也当未兑现收(逾期是 BE 的活)
        s = "未兑现"
    return s if s in _MODEL_STATUSES else _DEFAULT_STATUS


def _parse_commitments(text: str) -> list[dict[str, Any]] | None:
    """解析 ``{"commitments":[...]}``;三层兜底(直解析 / 切首个对象 / 截断抢救)。

    空数组是合法结果返 ``[]``;彻底解析不出返 ``None``。结构同 ``cross_doc._parse_relations``,
    数组键换成 ``"commitments"``。
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
    if isinstance(obj, dict) and isinstance(obj.get("commitments"), list):
        return obj["commitments"]
    salvaged = salvage_closed_objects(candidate, '"commitments"')
    if salvaged:
        logger.warning(
            "meeting_commitments: 主解析失败,从截断抢救到 %d 条", len(salvaged)
        )
        return salvaged
    return None


def _coerce_tracked(
    item: Any,
    by_cid: dict[int, dict[str, Any]],
    by_mid: dict[int, dict[str, Any]],
) -> dict[int, dict[str, Any]] | None:
    """把 LLM 推的一条状态归一 + 锚回真实单元 + 核兑现证据;锚不到 / 兑现没据 → 降级或丢。

    返 ``{cid: {status, evidence_mid, evidence, note, ...}}`` 单键 dict(给调用方按 cid 合并),
    cid 锚不到真实承诺 → 返 None(丢,不编不存在的承诺)。

    死守 evidence-first:
    - status 走封闭集归一(逾期剔出,由 BE 算)。
    - 兑现 / 未兑现 / 进行中**必须**有更晚会议的原话坐实:evidence_mid 要晚于 from_mid + evidence
      逐字锚得回那场会脉的已核证据池;**锚不到就把状态降成「未知」**(``_attach_evidence`` 在调用
      方做核验;这里先做 mid 合法性 + 时序检查)。
    - 未知不需要证据(本就是没再提)。
    """
    if not isinstance(item, dict):
        return None
    cid = item.get("cid")
    if not isinstance(cid, int) or isinstance(cid, bool) or cid not in by_cid:
        return None  # 锚不到真实承诺:丢

    status = _coerce_status(item.get("status"))
    ev_mid = item.get("evidence_mid")
    ev_mid_int = ev_mid if isinstance(ev_mid, int) and not isinstance(ev_mid, bool) else None
    evidence = str(item.get("evidence", "")).strip()
    note = str(item.get("note", "")).strip()
    from_mid = by_cid[cid]["from_mid"]

    # 时序闸:兑现证据必须来自**更晚**的会(mid 存在 + 时间晚于 from_mid)。不满足就清掉证据 mid,
    # 让后面核验那步因「没有效证据」把非未知状态降成未知。
    if ev_mid_int is not None:
        later = ev_mid_int in by_mid and _is_later(by_mid, ev_mid_int, from_mid)
        if not later:
            ev_mid_int = None

    return {cid: {
        "status": status,
        "evidence_mid": ev_mid_int,
        "evidence": evidence,
        "note": note,
    }}


def _is_later(by_mid: dict[int, dict[str, Any]], mid: int, base_mid: int) -> bool:
    """会议 mid 是否晚于 base_mid。先按会议日期 sort_key 比,日期相同 / 无日期退按 mid 序。

    跨会判兑现「只在更晚的会里找证据」靠这个把关。日期(sort_key)是排序锚;两场会同日期(或都没
    抽到日期)时,退按 mid——mid 是调用方排过序后的下标,本身就是时间序的近似。
    """
    a = by_mid.get(mid, {})
    b = by_mid.get(base_mid, {})
    ka, kb = a.get("sort_key", ""), b.get("sort_key", "")
    if ka and kb and ka != kb:
        return ka > kb
    return mid > base_mid


def _attach_evidence(
    tracked: dict[int, dict[str, Any]],
    by_mid: dict[int, dict[str, Any]],
) -> None:
    """逐条给兑现证据过核验:evidence 必须逐字锚得回 evidence_mid 那场会的已核证据池。

    核不过(含 evidence 空 / evidence_mid 空)→ ``evidence_verified=False`` + **状态降成「未知」**
    (非未知状态没有效原话支撑就不能立——立身之本,假阳性最坏)。核过的留 evidence + 标
    verified,前端点开看「是哪场会的这句话」。

    用 ``verify_citations`` 逐字比对(同会脉 / 公文那套),证据池 = evidence_mid 那场会脉里所有
    ``verified=True`` 的 evidence(``_spine_evidence_pool``)——只认这场会真有、且已核过的原话,
    防模型把别场会的话 / 编的话栽到这场会上。
    """
    for rec in tracked.values():
        status = rec["status"]
        ev_mid = rec.get("evidence_mid")
        evidence = str(rec.get("evidence", "")).strip()
        rec["evidence_verified"] = False
        if status == "未知":
            # 未知本就不需要证据:清空证据字段,保持干净。
            rec["evidence"] = ""
            rec["evidence_mid"] = None
            continue
        if ev_mid is None or not evidence:
            _downgrade_to_unknown(rec)
            continue
        pool = by_mid.get(ev_mid, {}).get("evidence_pool", [])
        if not pool:
            _downgrade_to_unknown(rec)
            continue
        # 拿这场会的已核 evidence 当「chunk」喂 verify_citations,逐字比对模型给的 evidence。
        evidence_map = build_evidence_map([
            {"chunk_id": f"ev{i}", "chapter": 0, "text": t}
            for i, t in enumerate(pool)
        ])
        citations = [{"snippet": evidence}]
        verify_citations(citations, evidence_map)
        if citations[0].get("verified"):
            rec["evidence_verified"] = True
        else:
            _downgrade_to_unknown(rec)


def _downgrade_to_unknown(rec: dict[str, Any]) -> None:
    """兑现证据坐实不了 → 状态降成「未知」、清掉证据(绝不留对不上原文的兑现判断)。

    保住 note(模型的判断理由)当线索,但状态本身降级——读者看到的是「未知」,不会被误导成
    「兑现了」。这是 evidence-first 在跨会层最关键的一道闸。
    """
    rec["status"] = "未知"
    rec["evidence"] = ""
    rec["evidence_mid"] = None
    rec["evidence_verified"] = False


def _apply_overdue(
    cid: int,
    rec: dict[str, Any],
    by_cid: dict[int, dict[str, Any]],
    by_mid: dict[int, dict[str, Any]],
) -> None:
    """逾期由 BE 纯算:due 真过了(到某场更晚的会之前)+ 没兑现证据 → 状态升成「逾期」。

    只在两条都满足时标逾期(``feedback_viz_algorithm_rigor`` 能算就别让模型猜):
    1. 这条承诺有 due(没 due 谈不上逾期)。
    2. 有一场**更晚的会**,它的会议日期已经晚过 due —— 也就是「到了这场会,这事早该做完了」。
    3. 当前状态不是「兑现」(已兑现的不算逾期)、也没有有效兑现证据。

    判 due 过没过用最克制的字符串比较(due 形如「下周一前」「3月10日」难精确解析),所以**只在能
    把 due 跟会议日期都归一成可比的日期串、且明显晚过时才升级**;比不出来就不动(宁可不标逾期,
    也不误标——逾期是会咬人的判断,假阳性代价大)。Phase 1 用粗判,精确日期解析留到规模化。
    """
    if rec["status"] == "兑现" or rec.get("evidence_verified"):
        return  # 已兑现 / 有兑现证据:不是逾期
    info = by_cid.get(cid, {})
    due = str(info.get("due", "")).strip()
    if not due:
        return  # 没时限:谈不上逾期
    due_norm = _normalize_date(due)
    if not due_norm:
        return  # due 解析不出可比日期:不强判
    from_mid = info["from_mid"]
    # 找有没有一场更晚的会,其日期晚过 due。
    for mid, m in by_mid.items():
        if not _is_later(by_mid, mid, from_mid):
            continue
        meeting_norm = _normalize_date(str(m.get("date", "")))
        if meeting_norm and meeting_norm > due_norm:
            rec["status"] = "逾期"
            return


def _normalize_date(s: str) -> str:
    """把会议日期 / due 粗归一成可字符串比较的「YYYYMMDD」式;解析不出返空串(不强判)。

    认两种好认的形态:① 「2026年3月10日」「2026-03-10」「2026/3/10」这种带年的;② 没年只有
    「3月10日」的补不出年,返空(不跨年瞎比)。相对期(「下周一前」「这周内」)解析不出,返空——
    宁可不标逾期也不误标。只取数字、按年月日补零拼,够做「明显晚过」的粗比。
    """
    import re

    t = (s or "").strip()
    if not t:
        return ""
    # 带年:YYYY 年/− /. 月 日
    m = re.search(r"(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})", t)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        return f"{int(y):04d}{int(mo):02d}{int(d):02d}"
    return ""  # 没年 / 相对期:不强判逾期


def _status_rank(status: str) -> int:
    """台账排序权重:逾期 / 未兑现(最该追的)排前,进行中次之,兑现 / 未知排后。

    顺序锚住「把咬人的、要追的捞到最前」(同 action_ledger loose_end 置顶的逻辑):逾期 0 < 未兑现 1
    < 进行中 2 < 未知 3 < 兑现 4。兑现的(已落地)和未知的(没下落、不一定是坏事)都靠后。
    """
    order = {"逾期": 0, "未兑现": 1, "进行中": 2, "未知": 3, "兑现": 4}
    return order.get(status, 3)


def commitments_across_meetings(
    *,
    meeting_chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    meeting_full_texts: list[str] | None = None,
    owner: str | None = None,
    max_tokens: int = DEFAULT_COMMITMENTS_MAX_TOKENS,
    spine_max_tokens: int = DEFAULT_MEETING_SPINE_MAX_TOKENS,
    char_budget: int = DEFAULT_CHAR_BUDGET,
    max_workers: int | None = None,
    cache_enabled: bool = True,
) -> dict[str, Any] | None:
    """多场会摆一起,跨会追「谁承诺了、兑现没」→ ``{commitments, meetings, owners}``;失败返 None。

    套「脊 + 一次全局推理 + 锚回真实单元」范式(同 ``cross_doc_relations_from_spines``),单元从
    「文件」换成「会议」、关系从「依据」换成「承诺—兑现」:

    1. 每场会先出会脉(``action_ledger_from_meeting``,焊死三可靠性守卫),承诺 = action_items。
    2. 按会议日期排序(``_sort_ledgers``);收承诺清单 + 每场会的兑现信号池(``_collect_commitments``)。
    3. 一次 LLM 全局推理判每条承诺的状态(``invoke_client_cached``,只在更晚的会里找)。
    4. 锚回真实承诺(cid)+ 核兑现证据(``_attach_evidence``:更晚会议的已核原话,锚不到降「未知」)
       + 逾期 BE 纯算(``_apply_overdue``:due 真过 + 没兑现证据)。

    Args:
        meeting_chunks: **多场会**的 chunk,每场一个 ``list[dict]``(每个 chunk 含 chunk_id /
            chapter / text)。外层 list 一个元素 = 一场会。
        llm_client: duck-typed LLM client(同 AgentLoop / 会脉)。已被 ``_UsageRecorder`` 包过时
            token 用量累加进 trace。
        model: 模型名。
        meeting_full_texts: 各场会的完整原文(跟 meeting_chunks 同序、同长)。传了头要素维就用它
            抽会议主题 / 时间;不传退回 chunk 拼接(向后兼容)。
        owner: 「我的承诺」用——传了就只返 owner 命中这个身份的承诺(纯字符串包含)。不传返全部。
        max_tokens: 一次全局推理的 max_tokens(默认 16000)。
        spine_max_tokens / char_budget / max_workers: 透传给每场会脉构建。
        cache_enabled: 是否走 L2 缓存(默认开,同一组会重开命中)。

    Returns:
        ``{
            "commitments": [{
                cid, from_mid, from_meeting, from_date, owner, task, due, substance,
                status(兑现/未兑现/逾期/进行中/未知), status_note,
                evidence_mid, evidence_meeting, evidence, evidence_verified,
                from_evidence, from_verified,
            }],
            "meetings": [{mid, label, date}],   # 给前端按会标注 / 时间线
            "owners": [按承诺数排的 owner 列表],  # 给前端按人分组
        }``。
        commitments 按「逾期 / 未兑现置顶 → 进行中 → 未知 → 兑现」+ 会议序 + 承诺序排
        (把要追的捞到最前)。传了 owner 时只含命中该身份的。

        少于 2 场能凑成会脉的会议(跨会追本就要 ≥2 场)/ 一场承诺都没有 / 一次推理失败且没有任何
        可锚承诺 → ``None``(端点返空态)。LLM 那一路失败**不直接返 None**:只要有承诺,照样出台账,
        状态全归「未知」(承诺还是真实抽到的,只是没判出下落——比假装判出强)。

        **逾期由 BE 纯算**(due 真过 + 没兑现证据),不让模型打这个标。**「兑现」必须更晚会议有原话
        坐实**(过 ``verify_citations``),锚不到一律降「未知」——判不出兑现没就标未知 / 进行中,
        绝不猜兑现(假阳性 = 骗用户说做完了,最坏)。
    """
    if not isinstance(meeting_chunks, list) or len(meeting_chunks) < 2:
        return None  # 跨会追本就要 ≥2 场

    # 第一步:每场会出会脉(复用 action_ledger_from_meeting,三可靠性守卫已焊死在里头)。
    # 注意:这里**不传 owner**给会脉——owner 筛是跨会层最后做(先把所有人的承诺都收齐,
    # 才能跨会匹配兑现;过早按 owner 砍会丢掉判兑现要用的别人发言信号)。
    full_texts = meeting_full_texts or []
    ledgers: list[dict[str, Any]] = []
    for idx, chunks in enumerate(meeting_chunks):
        if not isinstance(chunks, list):
            continue
        ft = full_texts[idx] if idx < len(full_texts) else None
        ledger = action_ledger_from_meeting(
            chunks=chunks,
            llm_client=llm_client,
            model=model,
            full_text=ft,
            max_tokens=spine_max_tokens,
            char_budget=char_budget,
            max_workers=max_workers,
            cache_enabled=cache_enabled,
        )
        ledgers.append(ledger)

    ledgers = _sort_ledgers(ledgers)
    if len(ledgers) < 2:
        return None

    meetings_digest, commitments_digest, by_cid, by_mid = _collect_commitments(ledgers)
    if not by_cid:
        return None  # 一条承诺都没抽到:跨会追无从谈起

    # 第二步:一次 LLM 全局推理判兑现状态(失败只 warning,承诺还在 → 全归未知出台账)。
    tracked: dict[int, dict[str, Any]] = {}
    user_content = json.dumps(
        {"meetings": meetings_digest, "commitments": commitments_digest},
        ensure_ascii=False,
    )
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
        parsed = _parse_commitments(llm_client.extract_final_text(resp))
    except Exception as exc:  # noqa: BLE001 — 调用失败:承诺还在,全归未知出台账
        logger.warning(
            "meeting_commitments: 全局推理抛 %s: %s;承诺状态全归未知",
            type(exc).__name__, exc,
        )
        parsed = None
    if parsed:
        for item in parsed:
            one = _coerce_tracked(item, by_cid, by_mid)
            if one:
                tracked.update(one)

    # 第三步:核兑现证据(锚不到降未知)+ 逾期 BE 纯算。没被模型判到的承诺补一条「未知」。
    for cid in by_cid:
        tracked.setdefault(cid, {
            "status": "未知", "evidence_mid": None, "evidence": "",
            "note": "", "evidence_verified": False,
        })
    _attach_evidence(tracked, by_mid)
    for cid, rec in tracked.items():
        _apply_overdue(cid, rec, by_cid, by_mid)

    # 组装输出:每条承诺把锚回信息 + 状态 + 证据拼全。
    out_commitments: list[dict[str, Any]] = []
    for cid, info in by_cid.items():
        rec = tracked[cid]
        ev_mid = rec.get("evidence_mid")
        out_commitments.append({
            "cid": cid,
            "from_mid": info["from_mid"],
            "from_meeting": by_mid.get(info["from_mid"], {}).get("label", ""),
            "from_date": by_mid.get(info["from_mid"], {}).get("date", ""),
            "owner": info["owner"],
            "task": info["task"],
            "due": info["due"],
            "substance": info.get("substance", ""),
            "status": rec["status"],
            "status_note": rec.get("note", ""),
            "evidence_mid": ev_mid,
            "evidence_meeting": (
                by_mid.get(ev_mid, {}).get("label", "") if ev_mid is not None else ""
            ),
            "evidence": rec.get("evidence", ""),
            "evidence_verified": bool(rec.get("evidence_verified", False)),
            "from_evidence": info.get("from_evidence", ""),
            "from_verified": info.get("from_verified", False),
        })

    # 「我的承诺」:传了 owner 就只留 owner 命中的(纯字符串包含,任一方向都算)。
    if owner and owner.strip():
        needle = owner.strip()
        out_commitments = [
            c for c in out_commitments
            if needle in str(c.get("owner", "")) or str(c.get("owner", "")).strip() == needle
        ]

    # 排序:把要追的捞到最前——逾期 / 未兑现置顶 → 进行中 → 未知 → 兑现;同档按会议序 + 承诺序。
    out_commitments.sort(key=lambda c: (
        _status_rank(c["status"]),
        c["from_mid"] if isinstance(c.get("from_mid"), int) else 1_000_000,
        c["cid"] if isinstance(c.get("cid"), int) else 1_000_000,
    ))

    # owner 列表(按承诺数多到少,给前端「按人分组」)。空 owner 归一个「未指派」桶不进列表。
    owner_counts: dict[str, int] = {}
    for c in out_commitments:
        o = str(c.get("owner", "")).strip()
        if o:
            owner_counts[o] = owner_counts.get(o, 0) + 1
    owners = sorted(owner_counts, key=lambda o: (-owner_counts[o], o))

    meetings_out = [
        {"mid": mid, "label": m["label"], "date": m["date"]}
        for mid, m in sorted(by_mid.items())
    ]

    return {
        "commitments": out_commitments,
        "meetings": meetings_out,
        "owners": owners,
    }


def _sort_ledgers(ledgers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按会议日期把会脉从早到晚排,给每份塞 ``__order`` / ``__sort_key``;只保是 dict 的。

    会议日期(``会议时间`` 头要素)是跨会判兑现「只看更晚的会」的时间锚。日期归一成可比串
    (``_normalize_date``)排;没抽到日期 / 解析不出的排末尾(但保留——它的承诺仍要追,只是
    时序上当最新)。同日期按原始下标稳定。``__sort_key`` 留给 ``_is_later`` 复用同口径。
    """
    items: list[tuple[str, int, dict[str, Any]]] = []
    for i, spine in enumerate(ledgers):
        if not isinstance(spine, dict):
            continue
        date = _head_value(spine, _HEAD_DATE_FIELD)
        key = _normalize_date(date)
        # 没可比日期的排末尾:用大值占位(￿ 比任何数字串大)。
        items.append((key or "￿", i, spine))
    items.sort(key=lambda t: (t[0], t[1]))
    out: list[dict[str, Any]] = []
    for order, (key, _orig, spine) in enumerate(items):
        spine["__order"] = order
        # sort_key 给 _is_later 用:有可比日期用日期,没日期退 order 的零填串(保时序近似)。
        spine["__sort_key"] = key if key != "￿" else f"zzz{order:06d}"
        out.append(spine)
    return out


__all__ = [
    "COMMITMENT_STATUSES",
    "DEFAULT_COMMITMENTS_MAX_TOKENS",
    "commitments_across_meetings",
]
