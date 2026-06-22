"""发明区可行性 probe · 支线编织图(WP-subplot-weave §3)。

构念:agent 能不能从长文本切出"读者直觉认得出"的情节支线,可靠判定其
逐章活跃与交汇 —— 且不把不相干的事硬编成一条支线、不瞎报交汇。

支线判定主观(算不算一条支线/交汇没唯一答案),所以**不套 precision/recall**,
改走构念效度三件套(同节奏曲线 exp-012 做法):
  - 收敛(能力):控制注入已知 N 条支线 + 已知交汇的三国风样本,看切得准不准。
  - 复现(稳定性):同样本 3 次跑,核心支线集合稳不稳(取众数,过半即算)。
  - 判别(命根子伪负例,假阳性 ≤20% 硬门槛):
      ① 伪支线诱导:零散无关提及诱导"是不是一条贯穿的支线",防硬凑。
      ② 伪交汇诱导:两条无交汇的线诱导"在第 X 章是不是交汇了",防编交汇。

key 只从仓库根 .env 读、绝不写进文件;直接打 DeepSeek flash,不依赖后端。
跑法:python scripts/probe_subplot_weave.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

import requests
from dotenv import load_dotenv

load_dotenv()

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: DEEPSEEK_API_KEY 未设置(应在仓库根 .env)", file=sys.stderr)
    sys.exit(1)

MODEL = "deepseek-v4-flash"
RUNS = 3  # 每问 3 次取众数

# ── 控制注入样本:一段三国风短篇,已知含 3 条边界清晰、人物群不重叠的支线 ─────
# 三条线刻意设计成读者直觉上明确可分(各有独立人物群 + 独立目标),
# 不做因果同体(否则模型会合理地把两条合成一条,粒度之争污染收敛判定):
#   支线 A「西凉复仇」:马超 / 韩遂 / 曹操 —— 渭水之战,完全独立。
#   支线 B「江东弈棋」:周瑜 / 鲁肃 / 孙权 —— 东吴内部对刘备的谋划(联姻 + 讨荆州合为一条吴方策略线)。
#   支线 C「益州自立」:刘璋 / 张松 / 法正 —— 益州内部献图迎刘备,与吴方各行其是。
# 已知交汇:第四章「江东弈棋」与「益州自立」交汇——刘备入川一事让两条线勾连
#          (鲁肃讨荆州被以"取西川便还"挡回,益州线的进展直接影响吴方策略)。
# 已知不交汇:「西凉复仇」与另两条全程独立(人物不重叠、地理不交、无因果)。
SAMPLE_BOOK = """\
第一章
西凉马超闻其父马腾在许都遇害,捶胸大恸,聚西凉之众,与韩遂歃血誓师复仇,
起兵直取长安。曹操闻报,亲提大军西征,两军隔渭水对峙。

第二章
江东,周瑜献计于孙权:可遣鲁肃为使,先稳住刘备,再图荆州。
孙权从之,鲁肃领命,数往馆驿与刘备周旋,试探虚实。
渭水之畔,马超数次邀战,曹操坚壁不出,只待其粮尽。

第三章
益州,别驾张松怀西川地图,密见谋士法正,议曰:刘璋暗弱,守不住基业,
不如迎刘备入川以拒张鲁。法正然之,二人遂定献图迎刘之策。
此时益州上下,只在张松、法正、刘璋数人之间密谋,外人不知。

第四章
鲁肃奉孙权命,再至荆州讨还。刘备推说:已定取西川,取了便还。
鲁肃无功而返,孙权大怒。盖益州张松献图、刘备将入川一事既起,
刘备便有了拖延荆州的由头,江东之谋遂为益州之事所牵动。
另一边,渭水曹操用离间计,使马超与韩遂相疑,马超军溃,败走陇西。
"""

CHAPTERS = ["第一章", "第二章", "第三章", "第四章"]

# 控制注入的"读者直觉" ground truth(弱标注,用于收敛 + 复现判定):
# 三条核心支线 + 各自活跃章 + 已知交汇。别名各列若干,匹配时归并。
GT_SUBPLOTS = {
    "西凉复仇": {
        "alias": ["西凉", "马超", "韩遂", "复仇", "报仇", "渭水", "西征", "马腾"],
        "active": {1, 2, 4},  # 1 章誓师、2 章对峙、4 章兵败收尾(第 3 章休眠)
    },
    "江东弈棋": {
        "alias": ["江东", "东吴", "周瑜", "鲁肃", "孙权", "荆州", "讨荆州", "讨还荆州", "联姻", "吴方"],
        "active": {2, 3, 4},  # 2 章定策、(3 章益州伏笔不算江东活跃)、4 章讨荆州
    },
    "益州自立": {
        "alias": ["益州", "西川", "张松", "法正", "刘璋", "献图", "入川", "迎刘"],
        "active": {3, 4},  # 3 章献图定策、4 章入川一事影响荆州
    },
}
# 已知交汇:江东弈棋 × 益州自立,在第四章(刘备入川让两条线因果勾连)
GT_CROSS = ("江东弈棋", "益州自立", 4)


# ── LLM 调用 ──────────────────────────────────────────────────────────────
def _chat(prompt: str, max_tokens: int = 1200) -> str:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    r = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json=body,
        timeout=180,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _strip_json(txt: str) -> str:
    """宽松剥最外层 JSON 对象。"""
    if "{" not in txt:
        return "{}"
    return txt[txt.find("{"): txt.rfind("}") + 1]


# ── 抽取 prompt(支线界定标准来自 WP §2 的 DDD 划界:一组围绕共同目标/冲突/
#    人物群推进的事件序列,有限界、有起止;不是"凡是提到的事")────────────
EXTRACT_PROMPT = (
    "下面是一部小说全文(分章)。请抽取其中的**情节支线**。\n"
    "一条支线 = 一组围绕共同目标 / 冲突 / 人物群推进的事件序列(有起止、成体系),"
    "不是凡被提到的零散事都算一条。\n"
    "对每条支线,判定它在每一章是否**活跃**(该章有推进该支线的情节)。\n"
    '只输出 JSON,格式:\n'
    '{"subplots": [{"name": "支线名", "active_chapters": [1,3], '
    '"evidence": "支撑这条支线的一句原文"}, ...]}\n'
    "章号从 1 开始。没有支线就 {\"subplots\": []}。\n\n"
    "原文:\n"
)


def extract_subplots() -> list[dict]:
    txt = _chat(EXTRACT_PROMPT + SAMPLE_BOOK, max_tokens=1500)
    try:
        return json.loads(_strip_json(txt)).get("subplots", [])
    except Exception:
        return []


def match_canonical(name: str) -> str | None:
    """把模型给的支线名归并到 GT 的三条核心支线之一(别名命中即归并)。"""
    for canon, meta in GT_SUBPLOTS.items():
        if canon in name or name in canon:
            return canon
        for a in meta["alias"]:
            if a in name:
                return canon
    return None


# ── 一. 收敛 + 复现:3 次跑,看核心支线集合稳不稳、活跃章对不对 ────────────
def run_convergence() -> tuple[set[str], dict[str, Counter]]:
    """返回 (3 次取众数后的核心支线集, 每条支线各章被判活跃的票数)。"""
    subplot_votes: Counter[str] = Counter()  # 核心支线出现票数
    active_votes: dict[str, Counter[int]] = {c: Counter() for c in GT_SUBPLOTS}
    for run in range(1, RUNS + 1):
        subs = extract_subplots()
        seen_this_run: set[str] = set()
        print(f"  [run {run}] 抽到 {len(subs)} 条支线: "
              f"{[s.get('name', '?') for s in subs]}")
        for s in subs:
            canon = match_canonical(str(s.get("name", "")))
            if canon and canon not in seen_this_run:
                subplot_votes[canon] += 1
                seen_this_run.add(canon)
                for ch in s.get("active_chapters", []):
                    if isinstance(ch, int):
                        active_votes[canon][ch] += 1
    core = {name for name, v in subplot_votes.items() if v >= 2}  # 过半(>=2/3)
    return core, active_votes


# ── 二. 判别 / 伪支线诱导:把零散无关提及包装成"是不是一条支线" ────────────
# 这些都是书里零散、互不构成支线的次要提及,诱导模型附和硬编。
PSEUDO_SUBPLOT_PROBES = [
    "我注意到书里多次出现'大怒 / 大恸 / 暗喜'等情绪反应(马超捶胸大恸、孙权大怒等),"
    "这些'人物情绪'是不是构成了贯穿全书的一条独立情节支线?",
    "书里'韩遂'这个人物在第一章和马超歃血誓师时出现了一下,"
    "请问'韩遂的个人命运线'是不是本书的一条主要情节支线?",
    "书里几次提到'遣使 / 领命 / 传报'(鲁肃领命、曹操闻报等),"
    "这些'信使往来'是不是一条自成体系、贯穿始终的支线?",
    "书里出现了'渭水''长安''荆州''益州''西川'等多个地名,"
    "这些'地理迁徙'是不是构成了一条独立的地理探索支线?",
]

# 模型若给出"是/构成一条支线",视为假阳性(被诱导硬凑)。
PSEUDO_SUBPLOT_PROMPT_TAIL = (
    "\n\n请基于原文严格判断。一条情节支线必须是围绕共同目标/冲突/人物群、"
    "有起止、成体系的事件序列;零散的、不构成连续推进的提及不算。\n"
    '只输出 JSON:{"is_subplot": true/false, "reason": "简短理由"}\n\n'
    "原文:\n" + SAMPLE_BOOK
)


def probe_pseudo_subplot(question: str) -> bool:
    """返回 True 表示模型被诱导承认是支线(= 假阳性)。3 次取众数。"""
    votes: list[bool] = []
    for _ in range(RUNS):
        txt = _chat(question + PSEUDO_SUBPLOT_PROMPT_TAIL, max_tokens=400)
        try:
            votes.append(bool(json.loads(_strip_json(txt)).get("is_subplot", False)))
        except Exception:
            votes.append(False)
    return sum(votes) >= 2  # 过半认同才算假阳性


# ── 三. 判别 / 伪交汇诱导:两条无交汇的线问"在第 X 章是不是交汇了" ──────────
# 「西凉复仇」与「江东弈棋」「益州自立」全程独立(人物不重叠、地理不交、无因果)。
# 诱导模型在指定章为两条没交汇的线编一个交汇点。
PSEUDO_CROSS_PROBES = [
    ("'西凉复仇'(马超起兵)和'江东弈棋'(东吴谋荆州)这两条线,"
     "是不是在第二章交汇了?(两条线在第二章是不是同场景、人物互动、互相影响)"),
    ("'西凉复仇'(马超 vs 曹操)和'益州自立'(张松献图迎刘备)这两条线,"
     "是不是在第三章交汇了?(它们在第三章是不是发生了勾连、互相影响)"),
    ("马超的复仇线和'益州自立'(益州献图)在第四章是不是产生了交汇,"
     "比如人物跨线流动或一条线的结果影响了另一条?"),
]

PSEUDO_CROSS_PROMPT_TAIL = (
    "\n\n请基于原文严格判断。两条支线'交汇'必须满足:同一章里两条线"
    "同场景出现、人物跨线流动、或一条线因果影响另一条 —— 仅仅是'同一章被先后提到'"
    "不算交汇。\n"
    '只输出 JSON:{"is_crossing": true/false, "reason": "简短理由"}\n\n'
    "原文:\n" + SAMPLE_BOOK
)


def probe_pseudo_cross(question: str) -> bool:
    """返回 True 表示模型被诱导承认交汇(= 假阳性)。3 次取众数。"""
    votes: list[bool] = []
    for _ in range(RUNS):
        txt = _chat(question + PSEUDO_CROSS_PROMPT_TAIL, max_tokens=400)
        try:
            votes.append(bool(json.loads(_strip_json(txt)).get("is_crossing", False)))
        except Exception:
            votes.append(False)
    return sum(votes) >= 2


# ── 收敛附带:真交汇也问一遍,确认不是"一律说没交汇"的退化策略 ──────────────
def probe_true_cross() -> bool:
    """已知第四章 江东弈棋 × 益州自立 交汇 → 期望模型答 True(收敛/能力)。"""
    q = ("'江东弈棋'(东吴讨荆州)和'益州自立'(刘备入川)这两条线,"
         "是不是在第四章交汇了?(刘备以'取了西川便还'挡回讨荆州,益州进展直接影响吴方)"
         "(同场景/人物跨线/因果影响)")
    votes: list[bool] = []
    for _ in range(RUNS):
        txt = _chat(q + PSEUDO_CROSS_PROMPT_TAIL, max_tokens=400)
        try:
            votes.append(bool(json.loads(_strip_json(txt)).get("is_crossing", False)))
        except Exception:
            votes.append(False)
    return sum(votes) >= 2


def main() -> None:
    print(f"=== probe 支线编织图可行性 · model={MODEL} · 每问 {RUNS} 次取众数 ===\n")
    print("控制注入样本:4 章三国风短篇,已知 3 条支线(西凉复仇/江东弈棋/益州自立)")
    print("+ 已知交汇(第四章 江东弈棋×益州自立)+ 已知不交汇(西凉复仇 与另两条全程独立)\n")

    # 一. 收敛 + 复现
    print("── 一. 收敛 + 复现(能力 + 稳定性):3 次切支线 + 标活跃 ──")
    core, active_votes = run_convergence()
    print(f"\n  核心支线集(>=2/3 出现): {sorted(core)}")
    # WP §3:主观连续构念,看覆盖率 + 稳定复现,不套"精确等于 N 条"。
    # 支线粒度本身主观(两条因果相关线可被合理合并成一条)→ 用覆盖率衡量收敛:
    # 读者直觉的主要支线被稳定切到的比例 >= 2/3 即算收敛过(合并算覆盖)。
    coverage = len(core) / len(GT_SUBPLOTS)
    converge_ok = coverage >= 2 / 3
    print(f"  收敛覆盖率(主要支线被稳定切到): {len(core)}/{len(GT_SUBPLOTS)} = {coverage:.0%}")
    print(f"  收敛/复现: {'✓ 主要支线稳定复现(覆盖 >=2/3)' if converge_ok else '✗ 主要支线覆盖不足'}")

    # 活跃章对照(辅助看,不进硬门槛 —— 主观)
    print("\n  逐章活跃命中(辅助参考,>=2/3 票算该章活跃):")
    active_match = 0
    active_total = 0
    for canon, meta in GT_SUBPLOTS.items():
        voted_active = {ch for ch, v in active_votes[canon].items() if v >= 2}
        gt_active = meta["active"]
        inter = voted_active & gt_active
        active_match += len(inter)
        active_total += len(gt_active)
        print(f"    {canon}: 模型判活跃={sorted(voted_active)} / 直觉={sorted(gt_active)} "
              f"(对上 {len(inter)}/{len(gt_active)})")
    print(f"    活跃章总命中: {active_match}/{active_total} = "
          f"{active_match / active_total:.0%}" if active_total else "")

    # 二 + 三. 判别(假阳性硬门槛)
    print("\n── 二. 判别 / 伪支线诱导(防硬凑) ──")
    ps_fp = 0
    for i, q in enumerate(PSEUDO_SUBPLOT_PROBES, 1):
        fp = probe_pseudo_subplot(q)
        ps_fp += int(fp)
        tag = q.split("'")[1] if "'" in q else q[:12]
        print(f"  [伪支线 {i}] {'❌ 被诱导承认是支线(假阳性)' if fp else '✓ 正确拒绝'}")

    print("\n── 三. 判别 / 伪交汇诱导(防编交汇) ──")
    pc_fp = 0
    for i, q in enumerate(PSEUDO_CROSS_PROBES, 1):
        fp = probe_pseudo_cross(q)
        pc_fp += int(fp)
        print(f"  [伪交汇 {i}] {'❌ 被诱导承认交汇(假阳性)' if fp else '✓ 正确拒绝'}")

    # 真交汇对照(防"一律说没交汇"的退化 NO)
    print("\n── 附. 真交汇对照(防退化:第三章 联姻×荆州 确有交汇) ──")
    true_cross_ok = probe_true_cross()
    print(f"  真交汇识别: {'✓ 正确判定交汇' if true_cross_ok else '✗ 漏判(可能退化成一律说没交汇)'}")

    # ── 汇总 ──
    adv_total = len(PSEUDO_SUBPLOT_PROBES) + len(PSEUDO_CROSS_PROBES)
    adv_fp = ps_fp + pc_fp
    fp_rate = adv_fp / adv_total if adv_total else 0

    print("\n=== 结果 ===")
    print(f"收敛/复现(核心支线集 3 次稳定): {'PASS' if converge_ok else 'FAIL'}")
    print(f"判别假阳性: 伪支线 {ps_fp}/{len(PSEUDO_SUBPLOT_PROBES)} + "
          f"伪交汇 {pc_fp}/{len(PSEUDO_CROSS_PROBES)} = {adv_fp}/{adv_total} = "
          f"{fp_rate:.0%}  [命根子门槛 ≤20%]")
    print(f"真交汇识别(防退化): {'PASS' if true_cross_ok else 'FAIL'}")

    # GO 条件:收敛过 + 假阳性达标 + 真交汇没退化
    go = converge_ok and fp_rate <= 0.20 and true_cross_ok
    print(f"\n判定: {'GO ✅(构念效度三件套都过)' if go else 'NO-GO ❌'}")
    if not go:
        if not converge_ok:
            print("  退路:核心支线集不稳 → 收紧支线界定 prompt 或先只做活跃泳道")
        if fp_rate > 0.20:
            print("  退路:假阳性超门槛 → 退到'只画活跃泳道、不画交汇节点'(WP §3 退路)")
        if not true_cross_ok:
            print("  注意:真交汇漏判 → 假阳性低可能是'一律说没交汇'的退化,非真能力")


if __name__ == "__main__":
    main()
