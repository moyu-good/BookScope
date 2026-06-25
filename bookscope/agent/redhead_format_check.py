"""公文「规范性自检」(1.6 红头文件垂直·发明区一炮)——对照 GB/T 9704《党政机关公文
格式》看一份公文该有的要素齐不齐、文种对不对。

**它解决什么**:一份红头文件该有哪些要素是有国标管的——GB/T 9704 把发文字号、标题、成文
日期、印发机关这些「版头 / 主体 / 版记」要素一项项写死了。普通人拿到一份公文,不知道它格式
规不规范、缺没缺要素、文种用得对不对。这功能逐项对照国标判:**齐 / 缺 / 存疑**,文种是否落在
15 法定文种 + 法规/公布令的封闭集里。

**它跟另外三个红头功能决定性的不同——这是唯一有「标准答案」的**:公文结构解读拆结构、大白话
翻译换说法、跟我相关带身份筛,这三个的判断或多或少要 LLM 临场判(指令类型、白话、相关度)。
规范性自检不一样:**要素齐不齐是对着 GB/T 9704 这本国标比对出来的,不是 LLM 拍脑袋**。所以这
一层**一行 LLM 都不再跑**——judge 纯靠文脉已经抽好的头要素结果(value 抽到没、verified 核过没)
做规则比对。差异化 = 有 ground truth(国标),不是主观判断(feedback_viz_algorithm_rigor:别让
模型拍 0-10 分,有抓手就用抓手)。

**诚实是这功能的命根子——「公文真没有」和「我们没抽到」必须分开**(§5.2):

某个要素 value 空,有两种可能——①这份公文里**真的没有**这一项(扫描件本就没印发文字号 /
法规体本就没签发人),那是「缺」;②文脉**抽取本身漏了**(扫描糊了、格式特殊没认出来),那不是
公文的错、是我们没抽到,该标「存疑·可能抽取漏」让用户回原件自己看。武断把所有空都判「缺」会
冤枉一份其实规范、只是我们没抽好的公文。区分靠一个信号:**整份头要素抽取整体可信吗**——大部分
要素都抽到了(说明抽取机制这次工作正常),某项还空,更可能是真没有 → 判「缺」;抽到的极少(抽取
这次大概率失败/糊了),某项空更可能是没抽到 → 判「存疑·可能抽取漏」。

**怎么做(套现成的文脉,一行不改 doc_spine / cross_doc / agent / schemas)**:

1. **拿文脉**:走 ``get_or_build_doc_spine`` 拿这份公文的文脉(头要素已含 发文字号 / 文种 /
   发文机关 / 主送机关 / 成文日期 / 签发人 等的抽取结果 + verified)。同份公文命中缓存秒出,
   不重精读、不再调 LLM。
2. **逐项对照 GB/T 9704 判齐/缺/存疑**:对每条国标要素规则,看文脉里对应头要素 value 抽到没、
   verified 核过没,结合「整份抽取可信度」判三态。文种额外查是否落在封闭集(``DOC_TYPES``)。
3. **evidence 锚原文**:每条 check 把对应头要素的 evidence(逐字原文)带出来,核过的盖「鉴」印。
   judge 本身是规则比对、不需要再核(verified 是文脉已经核过的结果),这里只是把证据透出去给
   前端展示「凭什么判齐」。

铁律:**只 import ``doc_spine_cache`` 的缓存入口 + ``doc_spine`` 的封闭集常量,一行不改
``doc_spine`` / ``cross_doc`` / ``agent`` / ``schemas`` / ``App.tsx``**;不碰端点(端点该返的
结构写在 ``format_check_from_spine`` 的 docstring 里给主 Claude 接线)。
"""

from __future__ import annotations

import logging
from typing import Any

from bookscope.agent._internal.doc_spine_cache import get_or_build_doc_spine
from bookscope.agent.doc_spine import DOC_TYPES

logger = logging.getLogger(__name__)

FORMAT_CHECK_SCHEMA_VERSION = "v1"
"""规范性自检记录结构版本——升级要让从文脉派生的这层重算(文脉缓存不受影响,只是 judge 层重跑)。"""

# 三态(封闭集)。不打分、不画进度条——是分类不是程度(feedback_viz_algorithm_rigor)。
STATUS_OK = "齐"
STATUS_MISSING = "缺"
STATUS_UNSURE = "存疑"

# 整份头要素抽取「这次大概率失败/糊了」的判定阈值:8 个要素里抽到的占比。
# 抽到比例 ≥ 这个数 → 抽取这次工作正常,某项空更可能是「公文真没有」→ 判「缺」;
# 低于这个数 → 抽取这次大概率没成(扫描糊 / 格式怪),某项空更可能是「没抽到」→ 判「存疑」。
# 取 1/3:8 项里至少抽到 3 项才算「抽取这次是好的」。定保守——宁可多标几个存疑让用户回原件,
# 也不武断判一份其实规范的公文「缺」。
_EXTRACTION_TRUSTWORTHY_RATIO = 1.0 / 3.0


# ── GB/T 9704 要素规则 ───────────────────────────────────────────────────────
# 每条规则对照国标里一个该有的要素,绑到文脉头要素的某个 field。
#   field:文脉头要素名(必须是 doc_spine._HEAD_FIELDS 里的);特殊规则「文种合法性」field=文种
#         但走单独的封闭集判定。
#   item:这条规则在自检表里显示的名(国标要素名,可能跟 field 不完全同字)。
#   required:GB/T 9704 里这要素是不是「该有」的——
#       True  = 规范公文普遍该有(发文字号 / 标题 / 成文日期 / 发文机关),空了倾向判「缺」。
#       False = 有条件要素(抄送 / 签发人):没有不算不规范(下行文无签发人、无抄送机关很正常),
#               空了不判「缺」,只标「未见(此类公文可不设)」式的中性结论,不冤枉它。
#   rule_note:这条对照的国标点,一句话(给前端展示「按什么规矩判的」)。
_FORMAT_RULES: tuple[dict[str, Any], ...] = (
    {
        "field": "发文字号",
        "item": "发文字号",
        "required": True,
        "rule_note": (
            "GB/T 9704:发文字号是版头要素,由机关代字、年份、序号组成"
            "(如「国办发〔2024〕5号」),公布令格式为「X令第N号」。"
        ),
    },
    {
        "field": "文种",
        "item": "文种(是否合法)",
        "required": True,
        "rule_note": (
            "《党政机关公文处理工作条例》定 15 法定文种,GB/T 9704 与立法法体系"
            "另认条例/规定/办法等法规及「令」类公布令;文种须落在这个封闭集。"
        ),
        "is_doc_type_rule": True,  # 这条走文种封闭集判定,不是单纯看 value 空不空
    },
    {
        "field": "发文机关",
        "item": "发文机关署名",
        "required": True,
        "rule_note": (
            "GB/T 9704:成文日期之上应有发文机关署名(谁发的);"
            "法规由通过它的人大常委会署名。"
        ),
    },
    {
        "field": "标题事由",
        "item": "标题",
        "required": True,
        "rule_note": (
            "GB/T 9704:公文标题由发文机关名称、事由、文种组成"
            "(「关于……的通知」),法规为全称(带行政区划)。"
        ),
    },
    {
        "field": "成文日期",
        "item": "成文日期",
        "required": True,
        "rule_note": "GB/T 9704:成文日期是公文生效/时效起算的版记要素,须用阿拉伯数字标全(年月日)。",
    },
    {
        "field": "主送机关",
        "item": "主送机关",
        "required": True,
        "rule_note": (
            "GB/T 9704:主送机关是公文主要受理对象,标于正文之前;"
            "公布令、普发性公告可不设主送。"
        ),
        # 多数公文该有,但公布令/法规/公告无主送很正常 → 空了判「存疑」而非「缺」
        "soft_required": True,
    },
    {
        "field": "抄送机关",
        "item": "抄送机关",
        "required": False,
        "rule_note": "GB/T 9704:抄送机关是需知晓公文的其他机关,属版记要素;无须抄送时可不设。",
    },
    {
        "field": "签发人",
        "item": "签发人",
        "required": False,
        "rule_note": (
            "GB/T 9704:上行文(请示/报告)版头标签发人;"
            "下行文、平行文、法规公布令通常不标签发人。"
        ),
    },
)


def _head_by_field(head: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """把文脉头要素列表按 field 索引成 dict,方便规则逐条取对应要素。"""
    out: dict[str, dict[str, Any]] = {}
    for el in head:
        if isinstance(el, dict):
            field = el.get("field")
            if isinstance(field, str):
                out[field] = el
    return out


def _has_value(el: dict[str, Any] | None) -> bool:
    """这条头要素是不是真抽到了(value 非空白才算)。"""
    if not el:
        return False
    return bool(str(el.get("value", "")).strip())


def _extraction_trustworthy(head: list[dict[str, Any]]) -> bool:
    """这次头要素抽取整体可不可信——抽到的要素占比是否达阈值。

    这是区分「公文真没有」vs「我们没抽到」的全局信号:大部分要素都抽到了说明抽取机制这次工作
    正常,某项还空更可能是真没有(→「缺」);抽到的极少说明这次大概率没抽成(扫描糊/格式怪),
    某项空更可能是没抽到(→「存疑·可能抽取漏」)。
    """
    if not head:
        return False
    filled = sum(1 for el in head if _has_value(el))
    return (filled / len(head)) >= _EXTRACTION_TRUSTWORTHY_RATIO


def _doc_type_value(head_index: dict[str, dict[str, Any]]) -> str:
    """取文种 value(已被文脉过封闭集归一:落不进封闭集的文脉里已清成空串)。"""
    return str((head_index.get("文种") or {}).get("value", "")).strip()


def _judge_doc_type(*, value: str, extraction_ok: bool) -> tuple[str, str]:
    """文种合法性判定(走封闭集,不是单纯看空不空)→ (status, note)。

    文脉抽取时文种已过封闭集归一(``doc_spine._coerce_doc_type``):落进 ``DOC_TYPES`` 才留、
    落不进清成空串。所以这里:
    - value 非空 → 它必然已落在封闭集(归一保证)→ 合法 → 齐。
    - value 空 → 有两种可能:①这份真没认出合法文种(扫描件没文种 / 真用了非法定文种被清空);
      ②抽取这次没抽到。按整份抽取可信度区分,绝不武断判这份「文种不合法」。
    """
    if value:
        return STATUS_OK, f"文种「{value}」落在法定文种 + 法规/公布令的封闭集内,合法。"
    # value 空(含「抽到了但不在封闭集被清空」与「没抽到」两种,文脉这层已合并成空)
    if extraction_ok:
        return (
            STATUS_UNSURE,
            "未识别出合法文种——可能这份用了非法定文种(被按封闭集滤掉),也可能文种这项没抽到;建议回原件确认标题里的文种。",
        )
    return (
        STATUS_UNSURE,
        "文种未抽到——这次头要素整体抽取偏少(可能扫描件糊了/格式特殊),不武断判文种缺失,请回原件核对。",
    )


def _judge_element(
    rule: dict[str, Any], el: dict[str, Any] | None, *, extraction_ok: bool
) -> tuple[str, str]:
    """普通头要素(非文种)的齐/缺/存疑判定 → (status, note)。

    判定优先级:
    1. value 非空 + verified → 齐(抽到了且原文核过)。
    2. value 非空 + 未 verified → 存疑(抽到了但没在原文核上,可能锚错/抽取有偏,不敢盖章判齐)。
    3. value 空 + 这要素 GB/T 该有(required):
       - 整份抽取可信(extraction_ok)→ 缺(抽取这次是好的,还空 → 更可能这份真没这一项)。
       - 整份抽取不可信 → 存疑·可能抽取漏(这次抽取大概率没成,空不该算这份的错)。
    4. value 空 + soft_required(多数该有但公布令/法规可不设,如主送机关)→ 一律存疑,不判缺
       (无主送的公布令/公告/法规是规范的,武断判缺会冤枉它)。
    5. value 空 + 非 required(有条件要素,如抄送/签发人)→ 中性「未见」,不算不规范。
    """
    item = rule["item"]
    if _has_value(el):
        verified = bool((el or {}).get("verified", False))
        if verified:
            return STATUS_OK, f"{item}已抽到并在原文核验通过。"
        return (
            STATUS_UNSURE,
            f"{item}抽到了,但没在原文比对命中——可能锚错位置或抽取有偏,暂不判定为齐,建议看原文出处确认。",
        )

    # value 空
    if rule.get("soft_required"):
        return (
            STATUS_UNSURE,
            f"未见{item}——公布令、普发性公告、法规这类公文本就可不设主送对象;若这份属此类则属正常,否则建议回原件确认。",
        )
    if rule.get("required"):
        if extraction_ok:
            return (
                STATUS_MISSING,
                f"未见{item}——这次头要素整体抽到较全,此项仍空,"
                "GB/T 9704 要求的该要素这份大概率确实缺失。",
            )
        return (
            STATUS_UNSURE,
            f"{item}未抽到,但这次头要素整体抽取偏少(可能扫描件糊了/格式特殊),不武断判缺;请回原件核对此项有无。",
        )
    # 非 required 的有条件要素(抄送/签发人):没有不算不规范
    return (
        STATUS_UNSURE,
        f"未见{item}——下行文、平行文、法规公布令通常不设此项,无此项不影响规范性;如属上行文则建议确认。",
    )


def format_check_from_spine(
    *,
    chunks: list[dict[str, Any]],
    llm_client: Any,
    model: str,
    full_text: str | None = None,
    cache_enabled: bool = True,
    **spine_kwargs: Any,
) -> dict[str, Any]:
    """一份公文对照 GB/T 9704 做规范性自检——拿文脉头要素 → 逐项规则比对判齐/缺/存疑。

    **这层一行 LLM 都不跑**(跟另外三个红头功能决定性的不同):judge 纯靠文脉已经抽好的头要素
    结果(value 抽到没、verified 核过没)做规则比对——要素齐不齐是对着 GB/T 9704 这本国标比出来
    的,有 ground truth,不是 LLM 临场判。``llm_client`` / ``model`` 只透传给
    ``get_or_build_doc_spine`` 用来建文脉(同份公文命中缓存就连这一步的 LLM 都不跑)。

    诚实区分「公文真没有」vs「我们没抽到」:某要素 value 空时,按整份头要素抽取的可信度
    (``_extraction_trustworthy``:抽到占比够不够)区分——抽取整体可信、某项还空 → 判「缺」;
    抽取这次大概率没成 → 判「存疑·可能抽取漏」,让用户回原件,绝不武断判一份其实规范的公文「缺」。

    Args:
        chunks: 这份公文的 chunk 列表(每条含 ``chunk_id`` / ``chapter`` / ``text``)。
        llm_client: duck-typed LLM client(只透传给文脉构建,本层不直接调)。
        model: 模型名(同上,只透传给文脉构建)。
        full_text: 这份公文的完整原文(含公布头),透传给文脉构建当头要素抽取 + 兜底锚定。
        cache_enabled: 是否走文脉缓存(默认开;同份公文命中秒出、连文脉的 LLM 都不跑)。
        **spine_kwargs: 透传给 ``get_or_build_doc_spine`` 的其余参数(char_budget 等)。

    Returns:
        ``{
            "schema_version": "v1",
            "checks": [{
                "item": "发文字号",        # 国标要素名
                "status": "齐"/"缺"/"存疑",
                "note": "一句话判定理由",
                "evidence": "对应头要素的逐字原文(可能空)",
                "verified": bool,          # 这条原文文脉核过没(给前端盖「鉴」印)
                "rule_note": "对照的 GB/T 9704 国标点",
            }],
            "summary": {
                "ok": N,        # 判「齐」的条数
                "missing": M,   # 判「缺」的条数
                "unsure": K,    # 判「存疑」的条数
                "total": T,     # 规则总条数
                "text": "齐 N/T",  # 给前端一行展示
                "extraction_trustworthy": bool,  # 这次头要素抽取整体可不可信(影响空项判缺还是存疑)
            },
        }``。
        头要素全空(一次抽取失败)→ 所有 required 项判「存疑·可能抽取漏」(不会全判缺冤枉公文)。
    """
    spine = get_or_build_doc_spine(
        chunks=chunks,
        llm_client=llm_client,
        model=model,
        full_text=full_text,
        cache_enabled=cache_enabled,
        **spine_kwargs,
    )
    head: list[dict[str, Any]] = spine.get("head") or []
    head_index = _head_by_field(head)
    extraction_ok = _extraction_trustworthy(head)

    checks: list[dict[str, Any]] = []
    for rule in _FORMAT_RULES:
        field = rule["field"]
        el = head_index.get(field)

        if rule.get("is_doc_type_rule"):
            value = _doc_type_value(head_index)
            status, note = _judge_doc_type(value=value, extraction_ok=extraction_ok)
        else:
            status, note = _judge_element(rule, el, extraction_ok=extraction_ok)

        # 文种封闭集是「合规」依据,DOC_TYPES 仅供日志/将来扩展提示用,这里不展开列。
        _ = DOC_TYPES  # noqa: F841 — 显式标明本层依赖封闭集常量(判定逻辑已落在 doc_spine 归一里)

        checks.append({
            "item": rule["item"],
            "status": status,
            "note": note,
            # evidence / verified 直接透文脉头要素的——judge 是规则比对、不再核;verified 是
            # 文脉已经核过的结果,带出来给前端盖「鉴」印,绝不在这层假装重核一遍。
            "evidence": str((el or {}).get("evidence", "")).strip(),
            "verified": bool((el or {}).get("verified", False)),
            "rule_note": rule["rule_note"],
        })

    ok = sum(1 for c in checks if c["status"] == STATUS_OK)
    missing = sum(1 for c in checks if c["status"] == STATUS_MISSING)
    unsure = sum(1 for c in checks if c["status"] == STATUS_UNSURE)
    total = len(checks)

    return {
        "schema_version": FORMAT_CHECK_SCHEMA_VERSION,
        "checks": checks,
        "summary": {
            "ok": ok,
            "missing": missing,
            "unsure": unsure,
            "total": total,
            "text": f"齐 {ok}/{total}",
            "extraction_trustworthy": extraction_ok,
        },
    }


__all__ = [
    "FORMAT_CHECK_SCHEMA_VERSION",
    "STATUS_MISSING",
    "STATUS_OK",
    "STATUS_UNSURE",
    "format_check_from_spine",
]
