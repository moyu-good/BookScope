"""公文措辞刻度 codebook —— 公共件(WP-redhead-deep-reading-lenses「懂刻度」那一层)。

老练读公文的核心:公文用词高度校准,小词差别=大信号。这把 codebook 把"约束力阶梯/留口子/
搁置婉拒/真priority/自由裁量/含金量(开环闭环)"成文,供多个功能 prompt 共用——建一次,
利害与风向 / 大白话翻译 / 办事清单 / 硬信息 / 时间轴 都 import :func:`codebook_block` 注进 prompt,
不各写一套、不漂移。

死守 evidence-first:codebook 只是"怎么判"的判据,判出来的结论照样要锚原文、过核验
(机会/风险/含金量是证据层);弦外之音类(信号)走评估层标研判。codebook 本身不放宽证据要求。
"""

from __future__ import annotations

# 约束力阶梯(从软到硬)——同一件事用哪个词,约束力天差地别。
CONSTRAINT_LADDER: tuple[str, ...] = (
    "鼓励", "支持", "推动", "推进", "引导",  # 倡导性(软,可不办)
    "应当", "必须", "不得", "严禁",          # 强制性(硬,有约束)
)

# 留口子词——表面规定,实际留了例外/可破的余地。
LOOPHOLE_WORDS: tuple[str, ...] = (
    "原则上",  # 有例外:"原则上不批"≈大概率能找关系破
    "一般",    # 可破例
    "依法依规",  # 按现有规矩、常作挡箭牌(没新增实质)
    "等", "等等",  # 开放清单,可扩
)

# 搁置/婉拒词——听着像同意/推进,实则拖或拒。
SHELVING_WORDS: tuple[str, ...] = (
    "研究", "研究研究",  # ≈不办
    "积极稳妥", "稳妥有序", "稳步",  # 放缓信号
    "原则同意",  # 同意但有保留/附条件
    "逐步", "适时", "条件成熟时",  # 无时间表=空头倾向
)

# 真 priority 词——这条是动真格、出事追责的底线。
PRIORITY_WORDS: tuple[str, ...] = (
    "坚决", "切实", "务必", "确保", "严格落实",
)

# 自由裁量词——真规则不在这份文件里,在别处/以后/某人手里(口子 + 寻租点 + 不确定性)。
DISCRETION_WORDS: tuple[str, ...] = (
    "由", "另行规定", "结合实际", "相关部门确定", "视情", "酌情",
)

# 含金量(substance)三档(封闭集)——钱学森控制论开环/闭环判出来的轻重缓急。
# 顺序就是轻重缓急的排序权重(真金白银 > 有条件兑现 > 空头倡导)。这是**公共件的单一真相源**:
# 利害与风向 / 办事清单 / 硬信息 / 时间轴 都从这里取三档,别各定一套(漂移之源)。
SUBSTANCE_LEVELS: tuple[str, ...] = ("真金白银", "有条件兑现", "空头倡导")
DEFAULT_SUBSTANCE = "有条件兑现"
"""落不进三档的兜底——退「有条件兑现」(最中性,不替用户断成真金白银/空头)。"""
_SUBSTANCE_RANK = {lv: i for i, lv in enumerate(SUBSTANCE_LEVELS)}

# 含金量(substance)判据 —— 钱学森控制论开环/闭环。键与 SUBSTANCE_LEVELS 一致。
SUBSTANCE_RUBRIC: dict[str, str] = {
    "真金白银": "闭环——硬约束词 + 具体数字(金额/比例/门槛)+ 明确时限 + 明确责任主体 + "
                "配套(考核/问责/罚则/财政资金)。有问责回路、不办有代价 → 会兑现。",
    "有条件兑现": "半闭环——有方向有抓手但缺一环(如有主体无时限、有目标无罚则、设了门槛)。"
                  "落不进真金白银也非纯号召时退这一档(中性,不替用户拔高也不打死)。",
    "空头倡导": "开环——倡导词(鼓励/支持/探索)+ 无数字 + 无时限或'逐步/条件成熟时' + "
                "无责任主体(有关方面/各地)+ 无罚则无资金。纯号召、无反馈回路 → 自然衰减、漂没。",
}


def coerce_substance(value: object) -> str:
    """含金量归一:必须落进三档封闭集,落不进退「有条件兑现」(中性兜底)。公共件,各功能共用。"""
    s = value.strip() if isinstance(value, str) else ""
    return s if s in SUBSTANCE_LEVELS else DEFAULT_SUBSTANCE


def substance_rank(level: str) -> int:
    """含金量排序权重:真金白银=0 < 有条件兑现=1 < 空头倡导=2,未知排最后。轻重缓急的排序键。"""
    return _SUBSTANCE_RANK.get(level, len(SUBSTANCE_LEVELS))


# 条款四态(封闭集,WP-redhead-substance-vs-slogan §八)——「方针类 + 三空」大桶再劈三态 +
# 桶外的实质态。全 deterministic,不加 LLM、不加阈值:建在现成 grounded 信号上(instruction_type
# + 三空 + detect_nuances + substance)。三功能(逐条精读 / 办事清单 / 大白话)一处定义、分路消费。
POLICY_CLAUSE_KINDS: tuple[str, ...] = (
    "substantive",       # 有可执行内核(非方针部署,或有主体/时限/罚则其一)→ 该解释
    "policy_signal",     # 方针类+三空 且 命中弦外 marker → 有信号,点破口子/没时间表
    "policy_direction",  # 方针类+三空 无 marker 有条件兑现 → 半信号,简述方向
    "policy_slogan",     # 方针类+三空 无 marker 空头倡导 → 纯口号废话,老实标 + 折叠
)


def _is_policy_three_empty(clause: dict[str, object]) -> bool:
    """「方针类」大桶的门:方针部署 + 责任主体/时限/罚则三空。

    不看 substance(比旧 clause_is_pure_statement 宽——空头倡导、有条件兑现都进桶,再按下面分态)。
    三空是硬门槛:抽到 actor/deadline/penalty 任一 = 有可执行内核 = 出桶算实质(宁放口号进实质区
    被解释,也别把真要办的事误标成方针,见 §6.3 保守向实质)。
    """
    return (
        str(clause.get("instruction_type", "")).strip() == "方针部署"
        and not str(clause.get("actor", "")).strip()
        and not str(clause.get("deadline", "")).strip()
        and not str(clause.get("penalty", "")).strip()
    )


def classify_policy_clause(clause: dict[str, object]) -> str:
    """把一条条款分四态(:data:`POLICY_CLAUSE_KINDS`,WP-redhead-substance-vs-slogan §八)。

    1.8.0 的 #5 把「纯表态」拍成一个开关(命中就一律 canned),上线后 canned 又滑成新一轮复读
    (五连显刷屏),还把「有弦外之音的方针」和「纯口号」压成同一档。这里在「方针类 + 三空」大桶
    内部再劈三态,让有信号的点破、有方向的简述、纯口号的才折叠:

    - **substantive**:出桶(有可执行内核)→ 逐条精读走 LLM 解释、办事清单当真待办。
    - **policy_signal**:桶内 + ``detect_nuances(evidence)`` 命中 ≥1 marker → 把弦外之意点破。
    - **policy_direction**:桶内 + 无 marker + 有条件兑现 → 半信号,简述方向(半模板、不调 LLM)。
    - **policy_slogan**:桶内 + 无 marker + 空头倡导 → 纯口号,老实标 + 同类合并折叠、不 N 连显。

    全 deterministic(串匹配 + 封闭集字段),不调 LLM、不加新阈值——判据全建在现成 grounded 信号上。
    真金白银 + 三空是矛盾组合(真金白银本需主体+时限+罚则),``coerce_substance`` 兜底退有条件兑现,
    落进 policy_direction(中性),不误判成废话。弦外之音映射本身的准确率靠 §九 probe 验(假阳性≤20%)。
    """
    if not _is_policy_three_empty(clause):
        return "substantive"
    if detect_nuances(str(clause.get("evidence", ""))):
        return "policy_signal"
    if coerce_substance(clause.get("substance")) == "空头倡导":
        return "policy_slogan"
    return "policy_direction"


def clause_is_pure_statement(clause: dict[str, object]) -> bool:
    """判一条条款是不是「纯口号废话」(= :func:`classify_policy_clause` 的 ``policy_slogan``)。

    保留此薄包装向后兼容(旧调用方判「要不要给 canned / 要不要剔出待办」)。**注意语义收窄**:
    现在它只对应四态里的 slogan 那一档;「方针类非待办」的完整集合(signal + direction + slogan)
    请用 ``classify_policy_clause(clause) != "substantive"`` 判,别再拿这个函数当「所有方针」。
    """
    return classify_policy_clause(clause) == "policy_slogan"

# 措辞 → 弦外之意(注解层)。键是原文里**真出现**才点的 marker,值是这词的真实含义——
# 大白话翻译命中 marker 时点这句"弦外之音",不只字面通顺。死守 evidence-first:nuance 只在
# 原文里**确有**这个 marker 时才出(deterministic 串匹配,不靠 LLM 脑补隐含义),原文没这词就
# 不加。措辞表大体随 LOOPHOLE / SHELVING / DISCRETION 三类走(强制/真priority 是字面变硬、不算
# "弦外",不进这表)。
#
# 顺序 = 检出优先级:长且独特的 marker 在前,短而泛的(如"由")在后——同一句命中多个时,
# :func:`detect_nuances` 按这个序收、按含义去重,避免"逐步"既报搁置又被别的词盖掉。
NUANCE_MARKERS: tuple[tuple[str, str], ...] = (
    # 搁置 / 婉拒(听着像推进,实则拖或拒)
    ("研究研究", "约等于不办——'研究'是搁置的客套"),
    ("条件成熟时", "没给时间表,'条件成熟'谁说了算没准——大概率拖着"),
    ("原则同意", "同意但留了保留/附了条件,不是痛快答应"),
    ("积极稳妥", "踩刹车的信号——要放缓、别冒进"),
    ("稳妥有序", "踩刹车的信号——要放缓、别冒进"),
    ("研究", "约等于不办——'研究'是搁置的客套"),
    ("逐步", "没给时间表——'逐步'='慢慢来',可能遥遥无期"),
    ("适时", "没给时间表——'适时'='看情况再说',没准头"),
    ("稳步", "踩刹车的信号——要放缓、别冒进"),
    # 留口子(表面规定、实留例外)
    ("原则上", "留了口子——'原则上'就有例外,'原则上不批'多半能找关系破"),
    ("依法依规", "按现有规矩、没新增实质,常当挡箭牌"),
    ("等等", "开放清单,'等'后面还能往里塞,口子没封死"),
    ("一般", "可破例——'一般'之外另有说法"),
    # 自由裁量(真规则在别处/以后/某人手里)
    ("另行规定", "真规则不在这份文件里,要等另一份——现在悬着"),
    ("结合实际", "给了自由裁量空间,具体松紧由执行的人定"),
    ("相关部门确定", "真规则在那个部门手里,这份文件没拍死"),
    ("视情", "由办事的人看着办——给了自由裁量,也是不确定性"),
    ("酌情", "由办事的人看着办——给了自由裁量,也是不确定性"),
)
# "等"单字太泛(容易误伤"等待/相等"),只在"等等"形式收;"由X认定/由X负责"的"由"也太泛,
# 不进 marker 表(交给含金量判据,不在字面注解里硬点)——宁可漏不可错报。


def codebook_block() -> str:
    """渲染成可嵌进 prompt 的措辞刻度判据块。各公文功能在自己的指令里拼上它,统一判读口径。

    用法::

        from bookscope.agent.redhead_codebook import codebook_block
        system = build_longctx_system(payload, MY_INSTR + "\\n" + codebook_block())
    """
    ladder = " < ".join(CONSTRAINT_LADDER)
    return (
        "【公文措辞刻度(判读时套这把尺,别只看字面)】\n"
        f"- 约束力阶梯(软→硬):{ladder}。倡导词=可不办,强制词=有约束。\n"
        f"- 留口子词({' / '.join(LOOPHOLE_WORDS)}):表面规定、实留例外,'原则上禁'≈能破。\n"
        f"- 搁置/婉拒({' / '.join(SHELVING_WORDS)}):'研究'≈不办、'积极稳妥'=放缓、"
        "'逐步/适时/条件成熟时'=无时间表=空头倾向。\n"
        f"- 真 priority({' / '.join(PRIORITY_WORDS)}):动真格、出事追责的底线。\n"
        f"- 自由裁量({' / '.join(DISCRETION_WORDS)}…):真规则在别处/以后/某人手里——口子+不确定性。\n"
        "- 含金量(开环/闭环判,真金白银/有条件兑现/空头倡导):\n"
        + "".join(f"    · {k}:{v}\n" for k, v in SUBSTANCE_RUBRIC.items())
        + "把判断锚在原文这些 marker 上(引哪个词/有无数字时限主体罚则),别凭空给结论。"
    )


def detect_nuances(text: str) -> list[dict[str, str]]:
    """扫一段原文,命中 :data:`NUANCE_MARKERS` 的就点出它的弦外之意(deterministic 串匹配)。

    这是大白话翻译"懂刻度"那层的件:翻译时除了字面通顺,命中措辞 marker 还点真实含义
    ("原则上"→有口子、"研究"→约等于不办)。死守 evidence-first——只在原文里**真有**这个
    marker 时才出注解,绝不靠 LLM 脑补隐含义。

    按 :data:`NUANCE_MARKERS` 的序扫(长且独特的在前),**按含义去重**:同一句里"逐步""适时"
    都命中、含义同属"没给时间表"的,只留先命中那条,免得堆一串近义注解。一个 marker 也没命中
    返空 list(调用方据此不挂 nuance 字段)。

    Args:
        text: 一条条款 / 一句公文的原文(逐字)。

    Returns:
        ``[{"marker": 命中的词, "meaning": 它的弦外之意}]``,按原文出现的检出序、含义去重。
    """
    if not text or not text.strip():
        return []
    out: list[dict[str, str]] = []
    seen_meanings: set[str] = set()
    for marker, meaning in NUANCE_MARKERS:
        if marker in text and meaning not in seen_meanings:
            seen_meanings.add(meaning)
            out.append({"marker": marker, "meaning": meaning})
    return out


__all__ = [
    "CONSTRAINT_LADDER",
    "DEFAULT_SUBSTANCE",
    "DISCRETION_WORDS",
    "LOOPHOLE_WORDS",
    "NUANCE_MARKERS",
    "POLICY_CLAUSE_KINDS",
    "PRIORITY_WORDS",
    "SHELVING_WORDS",
    "SUBSTANCE_LEVELS",
    "SUBSTANCE_RUBRIC",
    "classify_policy_clause",
    "clause_is_pure_statement",
    "codebook_block",
    "coerce_substance",
    "detect_nuances",
    "substance_rank",
]
