"""发明区可行性 probe · 精读注释层锚位(WP-annotated-reading §3)。

构念:一条分析结论的 citation snippet,能不能**可靠锚回原文里正确的那一处**
(对的章 / 段)?锚错位置比不锚更糟——在好句子上贴假批注。

被测主体:``bookscope.agent.citation_check.verify_citations``。
它是**纯确定性字符串定位**(归一化精确子串 → 失败再求最大 3-gram containment),
**不掺 LLM**。所以按 WP §3 的效度类型直接测命中率 / 锚错率,**不取众数**
(没有 LLM 波动可平滑)。章号纠偏走调用方 ``evidence_map[chunk_id]["chapter"]``
覆盖模型自报章号(见 argument_structure.py:204-212 等 8 处端点同一模式),
所以**锚对 chunk_id = 锚对真章号**,probe 直接量 chunk_id 命中。

不打 LLM、不读网络、不需要 key——纯比对算法 probe。
跑法:python scripts/probe_annotation_anchor.py
"""

from __future__ import annotations

import sys

from bookscope.agent.citation_check import verify_citations

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 正例:取一批"已 verify 过、逐字引用"的 citation 当现成 ground truth(WP §3 招①)。
# 每条:snippet 逐字摘自某 chunk(known_cid)。confirm verify_citations 把它锚到
# 那个 chunk(→ 那个真章号)。snippet 都是只在唯一一章出现的特征句,无歧义。
# evidence 仿真实端点形态:{chunk_id: {"chapter": int, "text": str}}。
# 文本用《安史之乱》题材的拟真书写句(自造,非原文逐字,只为造无歧义特征句)。
# ---------------------------------------------------------------------------
EVIDENCE_POSITIVE: dict[str, dict] = {
    "ch3-0": {"chapter": 3, "text": (
        "天宝年间,安禄山身兼平卢、范阳、河东三镇节度使,握重兵于东北。"
        "他屡次入朝,以胡旋舞博玄宗欢心,又厚结杨国忠之外的权贵以自固。")},
    "ch5-0": {"chapter": 5, "text": (
        "潼关失守的消息传到长安,玄宗仓皇出奔,百官多不知所往。"
        "六军行至马嵬驿,将士哗变,先杀杨国忠,再逼缢杨贵妃于佛堂之前。")},
    "ch7-0": {"chapter": 7, "text": (
        "睢阳被围既久,城中粮尽,张巡、许远督军死守,以纸为食,啮齿出血。"
        "外援不至,城终陷,而江淮赖此得以保全,叛军不能尽下东南。")},
    "ch9-0": {"chapter": 9, "text": (
        "史思明再据范阳,复称大燕皇帝,与其子史朝义内相猜忌。"
        "朝义遣人弑父自立,叛军自此离心,部将多怀去就之念。")},
    "ch11-0": {"chapter": 11, "text": (
        "宝应之后,仆固怀恩引回纥兵东讨,洛阳再克,史朝义穷走自缢于林中。"
        "河北诸降将各授节度,藩镇之祸由是萌芽,乱虽平而根未除。")},
    "ch2-0": {"chapter": 2, "text": (
        "玄宗晚年怠于政事,委任李林甫专权十九年,杜绝言路,蔽塞聪明。"
        "林甫死后杨国忠继之,与安禄山争宠交恶,边将离心,祸机已伏。")},
}

# (snippet, 期望 chunk_id, kind) —— kind: "quote" 逐字 / "paraphrase" 转述。
# 逐字引用是 WP §3 招①的现成 ground truth,量命中率;转述类按 WP §35 本就不进行间、
# 退面板,只验它不锚错章(锚对章或退场都对),不计入逐字命中率。
POSITIVE_CASES: list[tuple[str, str, str]] = [
    ("安禄山身兼平卢、范阳、河东三镇节度使", "ch3-0", "quote"),
    ("六军行至马嵬驿,将士哗变,先杀杨国忠", "ch5-0", "quote"),
    ("睢阳被围既久,城中粮尽,张巡、许远督军死守", "ch7-0", "quote"),
    ("朝义遣人弑父自立,叛军自此离心", "ch9-0", "quote"),
    ("史朝义穷走自缢于林中", "ch11-0", "quote"),
    ("委任李林甫专权十九年,杜绝言路", "ch2-0", "quote"),
    # 全半角标点差异版(注释里 snippet 常被改标点)——应仍锚对
    ("安禄山身兼平卢、范阳、河东三镇节度使，握重兵于东北。", "ch3-0", "quote"),
    # 转述类(非逐字,containment 不过阈值)——退场(None)或锚对章都算对,锚到别章才错
    ("张巡和许远死守睢阳,城中粮尽仍不降", "ch7-0", "paraphrase"),
]


# ---------------------------------------------------------------------------
# 命根子伪负例:控制注入(WP §3 招②)。造**文字高度相似、但在不同章/不同语境**
# 的样本,喂给锚位逻辑,看它会不会贴到错的那一章。锚错率 ≤ 20% 是硬门槛。
#
# 消歧验证:snippet 在多个 chunk 都逐字命中时,verify_citations 用调用方传入的
# 自报章号(弱先验)选对的那个(2026-06-18 加的 _disambiguate_by_chapter);
# 本 probe 验它能把锚错率从原先的 60% 压进门槛。
# 每条对抗:(snippet, 正确 chunk_id, 干扰 chunk_id, 注释场景说明)。
# ---------------------------------------------------------------------------
def build_adversarial() -> list[tuple[dict, str, str, str, str]]:
    """造对抗样本。返回 [(evidence_map, snippet, 正确cid, 干扰cid, 场景)]。

    干扰 chunk 与正确 chunk 文字高度相似(同人名/近措辞)但属不同章。
    """
    cases: list[tuple[dict, str, str, str, str]] = []

    # A. 同一句话在两章逐字重复(回环呼应 / 母题复现常见)——
    #    注释要指的是"第 8 章这一处",但同句在第 2 章也原样出现过。
    #    verify_citations 精确子串 break 在第一个命中 chunk → 锚到 ch2(错)。
    snippet_a = "天下大势,合久必分,分久必合"
    ev_a = {
        "ch2-0": {"chapter": 2, "text": "话说" + snippet_a + ",此乃古今常理,叙事由此发端。"},
        "ch8-0": {"chapter": 8, "text": "至此再叹" + snippet_a + ",前番伏笔于此回收,首尾相照。"},
    }
    cases.append((ev_a, snippet_a, "ch8-0", "ch2-0", "同句两章逐字复现(母题回环),注释指第 8 章回收处"))

    # B. 同一人物名 + 近措辞,在两章各出现一次(同名不同事)。
    #    正确指第 6 章"史思明再叛",干扰是第 4 章"史思明初降"。
    snippet_b = "史思明拥兵自重,阳奉阴违,终复称兵作乱"
    ev_b = {
        "ch4-0": {"chapter": 4, "text": "史思明拥兵自重,阳奉阴违,然此时尚未公然反唐,姑且观望。"},
        "ch6-0": {"chapter": 6, "text": "其后" + snippet_b + ",河北复陷,朝廷震动。"},
    }
    cases.append((ev_b, snippet_b, "ch6-0", "ch4-0", "同人近措辞两章(初降 vs 再叛),注释指第 6 章再叛"))

    # C. 近义改写,正确章是逐字、干扰章是高 containment 近写。
    #    snippet 逐字属第 10 章;第 1 章有一句 3-gram 高度重叠的近写。
    snippet_c = "潼关一失,长安门户洞开,叛军长驱直入"
    ev_c = {
        "ch1-0": {"chapter": 1, "text": "若潼关一失,则长安门户洞开,叛军可长驱直入,此乃后话先伏。"},
        "ch10-0": {"chapter": 10, "text": snippet_c + ",玄宗遂决意西幸。"},
    }
    cases.append((ev_c, snippet_c, "ch10-0", "ch1-0", "近写干扰 vs 逐字正确,注释指第 10 章逐字处"))

    # D. 短引用(易撞)——一个短判断句在两章都出现。
    snippet_d = "民不堪命,流离道路"
    ev_d = {
        "ch3-0": {"chapter": 3, "text": "兵祸连年," + snippet_d + ",此其一也。"},
        "ch12-0": {"chapter": 12, "text": "乱后疮痍," + snippet_d + ",户口减半,十不存一。"},
    }
    cases.append((ev_d, snippet_d, "ch12-0", "ch3-0", "短判断句两章复现,注释指第 12 章乱后处"))

    # E. 干扰 chunk 在 evidence 字典里**排在正确 chunk 前面**——
    #    专测 dict 顺序对 break-first 的影响(若锚第一个 → 锚到干扰=错)。
    snippet_e = "回纥兵入洛阳,纵掠三日,民间财货为之一空"
    ev_e = {
        # 干扰(第 5 章一处近似纵掠记述,同句式)放前面
        "ch5-0": {"chapter": 5, "text": "初,回纥兵入洛阳,纵掠三日,民间财货为之一空,后稍戢。"},
        # 正确(第 11 章二次克洛阳同样记述)放后面
        "ch11-0": {"chapter": 11, "text": "再克之日," + snippet_e + ",东都几成废墟。"},
    }
    cases.append((ev_e, snippet_e, "ch11-0", "ch5-0", "同句两章,干扰排字典前位(测 break-first 偏向)"))

    return cases


def run_positive() -> tuple[int, int, int, int, list[str]]:
    """逐字引用量命中率(WP §3 招①现成 ground truth);转述类只验不锚错章。

    Returns: (quote_hit, quote_total, para_ok, para_total, lines)
    """
    quote_hit = quote_total = para_ok = para_total = 0
    lines: list[str] = []
    for snippet, want_cid, kind in POSITIVE_CASES:
        # 真实调用方带 LLM 自报章号;正例单命中、章号不影响结果,带上只为贴近真实用法
        cits = [{"snippet": snippet, "chapter": EVIDENCE_POSITIVE[want_cid]["chapter"]}]
        verify_citations(cits, EVIDENCE_POSITIVE)
        got_cid = cits[0].get("chunk_id")
        mt = cits[0].get("match_type")
        want_ch = EVIDENCE_POSITIVE[want_cid]["chapter"]
        got_ch = EVIDENCE_POSITIVE.get(got_cid, {}).get("chapter") if got_cid else None
        if kind == "quote":
            quote_total += 1
            ok = got_cid == want_cid
            quote_hit += int(ok)
            mark = "✓" if ok else "✗ 锚错"
        else:  # paraphrase:退场(None)或锚对章都算对,锚到别章才错
            para_total += 1
            ok = got_cid in (want_cid, None)
            para_ok += int(ok)
            mark = "✓ 转述正确处理" if ok else "✗ 转述锚错章"
        lines.append(
            f"  [{mark}] kind={kind} 期望 ch{want_ch}({want_cid}) → 实得 "
            f"ch{got_ch}({got_cid}) match_type={mt} 「{snippet[:18]}…」"
        )
    return quote_hit, quote_total, para_ok, para_total, lines


def run_adversarial() -> tuple[int, int, list[str]]:
    """量锚错率:本该锚正确章、却锚到干扰章(或飘到 None)的比例。

    锚到正确 chunk = 对;锚到干扰 chunk = 锚错(命根子失败);锚到 None = 也算错
    (注释挂不上 → 不会浮出,不算"贴错位置",但这里仍记为未锚对供观察)。
    """
    wrong = 0
    total = 0
    lines: list[str] = []
    for ev, snippet, right_cid, distract_cid, scene in build_adversarial():
        # 真实调用方带 LLM 自报章号(注释本就指明"第 N 章")——多命中时消歧拿它做弱先验。
        # 自报章号建模为该结论的目标章;长上下文自报会漂 ±1~2,但干扰章距正确章 5~9 章,
        # 取最近逻辑对这点漂移稳健(漂到的章仍离正确章更近)。
        cits = [{"snippet": snippet, "chapter": ev[right_cid]["chapter"]}]
        verify_citations(cits, ev)
        got = cits[0].get("chunk_id")
        mt = cits[0].get("match_type")
        total += 1
        if got == right_cid:
            verdict, is_wrong = "✓ 锚到正确章", False
        elif got == distract_cid:
            verdict, is_wrong = "❌ 锚到干扰章(贴错位置)", True
        else:
            verdict, is_wrong = f"⚠ 锚到 {got}(未命中正确章)", True
        wrong += int(is_wrong)
        right_ch = ev[right_cid]["chapter"]
        distract_ch = ev[distract_cid]["chapter"]
        lines.append(
            f"  {verdict}  正确=ch{right_ch} 干扰=ch{distract_ch} "
            f"实得={got} match_type={mt}\n      场景:{scene}"
        )
    return wrong, total, lines


def main() -> None:
    print("=== probe 精读注释层锚位 · 被测=verify_citations(纯确定性,不掺 LLM) ===\n")

    print("【正例 · 逐字引用命中率(已 verify 逐字引用当 ground truth)】")
    q_hit, q_total, p_ok, p_total, pos_lines = run_positive()
    for ln in pos_lines:
        print(ln)
    recall = q_hit / q_total if q_total else 0.0
    print(f"  → 逐字引用锚位命中率: {q_hit}/{q_total} = {recall:.0%}")
    print(f"  → 转述类正确处理(锚对章或退场、不锚错章): {p_ok}/{p_total}\n")

    print("【命根子伪负例 · 锚错率(控制注入:相似文本不同章)】")
    adv_wrong, adv_total, adv_lines = run_adversarial()
    for ln in adv_lines:
        print(ln)
    err_rate = adv_wrong / adv_total if adv_total else 0.0
    print(f"  → 锚错率: {adv_wrong}/{adv_total} = {err_rate:.0%}  [命根子门槛 ≤20%]\n")

    print("=== 判定 ===")
    gate_pos = recall >= 0.90
    gate_adv = err_rate <= 0.20
    go = gate_pos and gate_adv
    print(f"  命中率 {recall:.0%} (要 ≥90%): {'达标' if gate_pos else '不达标'}")
    print(f"  锚错率 {err_rate:.0%} (要 ≤20%): {'达标' if gate_adv else '不达标'}")
    print(f"\n  {'GO ✅' if go else 'NO-GO ❌(命根子未过 → 注释层需加消歧)'}")


if __name__ == "__main__":
    main()
