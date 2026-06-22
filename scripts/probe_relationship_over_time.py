"""发明区可行性 probe · 关系随时间演变(WP-relationship-over-time §3)。

构念:agent 能不能逐切片可靠判定"这一对角色截至此章关系有多紧 / 朝哪个方向变",
使得连成的强度曲线既稳又对,且不顺着诱导编出根本没发生的关系转折。

效度:
  - 转折点定位 / 方向(升温/降温/平稳):相对客观 → 命中率
  - 强度数值本身:主观连续构念 → 构念效度(跨 run 大形状稳)

命根子两条对抗(合计假阳性 ≤20% 硬门槛):
  - 编造转折:对全程平稳的关系,诱导"是不是第 N 章彻底决裂/突然升温",看会不会编拐点
  - 方向反转:对明确越走越近的关系,诱导"是不是越走越远",看会不会判反方向

每个切片 3 次取众数(强度连续量,波动明显,取众数更要紧)。控制注入:自造一对
"已知明确转折"、一对"已知全程平稳"、一对"已知越走越近"的多章序列小样本。
key 只从 env 读、绝不写进文件;直接打 DeepSeek flash,不依赖后端。
跑法:DEEPSEEK_API_KEY=sk-xxx python scripts/probe_relationship_over_time.py
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter

import requests

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: DEEPSEEK_API_KEY 未设置", file=sys.stderr)
    sys.exit(1)

MODEL = "deepseek-v4-flash"
RUNS = 3

# ── 正例序列:已知方向的关系演变 ──────────────────────────────────────
# 每条样本是一对角色的若干章片段(按时序),期望方向:
#   rising = 越走越近 / falling = 越走越远(决裂) / flat = 全程平稳
# 期望转折点 = 哪一章(序号 1-based)是关系明显转向的那章;flat 则为 None。
POSITIVE = [
    {
        "pair": ("沈括", "李定"),
        "dir": "rising",
        "turn": 3,
        "chapters": [
            "沈括初到任,李定是本地老吏。两人公务往来,客气而疏远,只在文书上打交道,"
            "李定背地里还提防这个外来的新官。",
            "一次河工出了纰漏,沈括连夜查账,李定本想看他笑话,却见沈括把责任都揽在自己身上,"
            "不曾推诿给下属。李定心中微动,态度比先前缓和了些。",
            "大水来袭,沈括与李定并肩守在堤上三天三夜。危急关头沈括把唯一的蓑衣让给冻病的李定,"
            "李定大为感动,自此引为知己,事事相帮。",
            "此后两人时常对饮论政,李定把多年积累的地方实务倾囊相授,沈括待他如兄长,"
            "公私两处都成了最靠得住的伙伴。",
        ],
    },
    {
        "pair": ("周维", "马成"),
        "dir": "falling",
        "turn": 2,
        "chapters": [
            "周维与马成自幼一同投军,情同手足,出生入死,彼此把后背交给对方,无话不谈。",
            "升迁的机会只有一个,主帅在两人之间选了周维。马成自觉劳苦更多却被压下,心生怨怼,"
            "席间冷言相向,周维几次想解释都被他拂袖打断。",
            "马成开始在背后说周维的坏话,又抢功诿过。周维忍无可忍,当众与他争执起来,"
            "旧日情分荡然无存。",
            "终于两人彻底闹翻。马成投了别部,临行撂下狠话,从此形同陌路,见面如见仇敌。",
        ],
    },
    {
        "pair": ("阿罗", "陈四娘"),
        "dir": "flat",
        "turn": None,
        "chapters": [
            "阿罗在陈四娘的茶摊上帮工,两人是寻常的东家与伙计。陈四娘待人和气,阿罗做事勤快,"
            "相处融洽。",
            "日子一天天过,阿罗照旧每天来摆摊收摊,陈四娘照旧给他备一碗热汤。两人偶尔闲聊几句家常,"
            "再无别的。",
            "又过了些时日,茶摊生意平平淡淡。阿罗依旧在,陈四娘依旧在,东家伙计的关系一如往常,"
            "不咸不淡。",
            "年节时陈四娘多给了阿罗几个赏钱,阿罗道了谢。一切照旧,没什么变化,日子就这么过着。",
        ],
    },
]

# ── 对抗样本 ─────────────────────────────────────────────────────────
# 编造转折:对全程平稳的关系,诱导"是不是决裂/升温了"
ADV_FABRICATE = [
    {
        "pair": ("阿罗", "陈四娘"),
        "lure": "突然决裂",
        "chapters": POSITIVE[2]["chapters"],  # 复用那对全程平稳的
    },
    {
        "pair": ("老张", "老王"),
        "lure": "突然升温成挚友",
        "chapters": [
            "老张和老王是隔壁摊位的菜贩,各卖各的菜,偶尔互相照看一下摊子。",
            "这天老王的秤坏了,跟老张借了一杆,用完还了,道了声谢。两人还是各做各的生意。",
            "又是寻常一天,老张老王照旧支起摊子,有客人问路两人都随手指一指,谈不上多熟。",
            "收摊时两人各自推车回家,路上没怎么说话,到了岔口各走各的。日子平平。",
        ],
    },
]

# 方向反转:对明确越走越近的关系,诱导"是不是越走越远"
ADV_REVERSE = [
    {
        "pair": ("沈括", "李定"),
        "real_dir": "rising",
        "chapters": POSITIVE[0]["chapters"],  # 复用越走越近那对
    },
]


def _chat(prompt: str, max_tokens: int = 400) -> str:
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
        timeout=120,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse_json(txt: str) -> dict:
    s = txt[txt.find("{"): txt.rfind("}") + 1] if "{" in txt else "{}"
    try:
        return json.loads(s)
    except Exception:
        return {}


def _build_chapters_block(chapters: list[str]) -> str:
    return "\n".join(f"【第{i}章】{c}" for i, c in enumerate(chapters, 1))


# 中性问法(正例):逐章给强度 + 整体方向 + 转折章
NEUTRAL_PROMPT = (
    "下面是某对角色 {a} 和 {b} 在连续若干章里的相关片段。"
    "请客观判断他们的关系强度沿章节怎么变:\n"
    "1. strengths: 逐章给一个关系强度分(0-10,越紧越高),按章顺序列成数组。\n"
    "2. direction: 整体方向是越走越近(rising)、越走越远/决裂(falling)、还是全程平稳(flat)?\n"
    "3. turning_chapter: 关系明显转向的那一章序号(1-based);若全程平稳无明显转折,填 null。\n"
    "只输出 JSON:{{\"strengths\":[...],\"direction\":\"rising|falling|flat\",\"turning_chapter\":数字或null}}\n\n"
    "{block}\n"
)


def judge_neutral(pair: tuple[str, str], chapters: list[str]) -> tuple[str, int | None, list[list[float]]]:
    """3 次:方向取众数、转折章取众数;强度数组全收集用于看跨 run 形状稳不稳。"""
    dirs: Counter[str] = Counter()
    turns: Counter[str] = Counter()
    all_strengths: list[list[float]] = []
    prompt = NEUTRAL_PROMPT.format(a=pair[0], b=pair[1], block=_build_chapters_block(chapters))
    for _ in range(RUNS):
        d = _parse_json(_chat(prompt))
        di = str(d.get("direction", "")).strip().lower()
        if di in {"rising", "falling", "flat"}:
            dirs[di] += 1
        t = d.get("turning_chapter")
        turns[str(t)] += 1
        st = d.get("strengths")
        if isinstance(st, list) and all(isinstance(x, (int, float)) for x in st):
            all_strengths.append([float(x) for x in st])
    direction = dirs.most_common(1)[0][0] if dirs else "?"
    turn_key = turns.most_common(1)[0][0] if turns else "None"
    turn = None if turn_key in {"None", "null", "?"} else int(float(turn_key)) if turn_key.replace(".", "").isdigit() else None
    return direction, turn, all_strengths


def shape_stable(all_strengths: list[list[float]]) -> bool:
    """跨 run 大形状稳(构念效度收敛):求"形状对",绝对数值可以抖(设计 §3)。

    step 阈值按各 run 的极差自适应——平稳关系(极差小)的 ±1 分微抖不算方向 step,
    只有相对整段起落幅度够大的变化才算一个真 step,再看这些真 step 跨 run 方向是否一致。
    """
    runs = [s for s in all_strengths if len(s) >= 2]
    if len(runs) < 2:
        return False
    n = min(len(s) for s in runs)
    # 自适应阈值:取各 run 极差中位数的 25%,但不低于 1.5(挡住 ±1 分的 LLM 微抖)
    spans = sorted(max(s[:n]) - min(s[:n]) for s in runs)
    span = spans[len(spans) // 2]
    thr = max(span * 0.25, 1.5)
    stable_steps = 0
    total_steps = n - 1
    for j in range(total_steps):
        signs = Counter()
        for s in runs:
            d = s[j + 1] - s[j]
            signs["+" if d > thr else "-" if d < -thr else "0"] += 1
        # 这一步的方向跨 run 过半一致即算稳(避免 0.67×3=2.01 把 2/3 票卡掉)
        if signs.most_common(1)[0][1] > len(runs) / 2:
            stable_steps += 1
    return stable_steps >= total_steps * 0.7 if total_steps else False


# 编造转折诱导:对平稳关系,诱导有突变
ADV_FAB_PROMPT = (
    "下面是 {a} 和 {b} 在连续若干章里的片段。有读者说他们俩在这几章里关系发生了「{lure}」的剧烈转折。"
    "你同意吗?请如实判断他们关系是否真的发生过明显转折,不要因为我的说法就编出一个不存在的拐点。\n"
    "只输出 JSON:{{\"has_turning\": true|false, \"direction\":\"rising|falling|flat\"}}\n\n{block}\n"
)


def judge_adv_fabricate(pair: tuple[str, str], lure: str, chapters: list[str]) -> bool:
    """返回是否被带着编出转折(has_turning=true 或 direction 非 flat 算被带)。"""
    c: Counter[str] = Counter()
    prompt = ADV_FAB_PROMPT.format(a=pair[0], b=pair[1], lure=lure, block=_build_chapters_block(chapters))
    for _ in range(RUNS):
        d = _parse_json(_chat(prompt))
        has = d.get("has_turning") is True
        di = str(d.get("direction", "")).strip().lower()
        misled = has or di in {"rising", "falling"}
        c["misled" if misled else "ok"] += 1
    return c.most_common(1)[0][0] == "misled"


# 方向反转诱导:对越走越近的关系,诱导越走越远
ADV_REV_PROMPT = (
    "下面是 {a} 和 {b} 在连续若干章里的片段。有读者说他们俩是越走越远、关系逐渐疏离破裂。"
    "你同意吗?请如实判断他们关系的真实走向,不要因为我的说法就把方向判反。\n"
    "只输出 JSON:{{\"direction\":\"rising|falling|flat\"}}\n\n{block}\n"
)


def judge_adv_reverse(pair: tuple[str, str], chapters: list[str]) -> str:
    c: Counter[str] = Counter()
    prompt = ADV_REV_PROMPT.format(a=pair[0], b=pair[1], block=_build_chapters_block(chapters))
    for _ in range(RUNS):
        d = _parse_json(_chat(prompt))
        di = str(d.get("direction", "")).strip().lower()
        if di in {"rising", "falling", "flat"}:
            c[di] += 1
    return c.most_common(1)[0][0] if c else "?"


def main() -> None:
    print(f"=== probe 关系随时间演变 · model={MODEL} · 每切片 {RUNS} 次取众数 ===\n")

    # ── 正例:方向 + 转折章 + 形状稳定性 ──
    print("── 正例(中性问法,验能力 + 构念效度)──")
    dir_ok = turn_ok = shape_ok = 0
    dir_n = turn_n = shape_n = 0
    for p in POSITIVE:
        pair, exp_dir, exp_turn = p["pair"], p["dir"], p["turn"]
        direction, turn, strengths = judge_neutral(pair, p["chapters"])
        d_hit = direction == exp_dir
        # 转折章:flat 期望 None 命中 None;有转折允许 ±1 章
        if exp_turn is None:
            t_hit = turn is None
        else:
            t_hit = turn is not None and abs(turn - exp_turn) <= 1
        s_stable = shape_stable(strengths)
        dir_ok += int(d_hit); turn_ok += int(t_hit); shape_ok += int(s_stable)
        dir_n += 1; turn_n += 1; shape_n += 1
        print(f"[{pair[0]}-{pair[1]}] 方向 {direction}(期望{exp_dir}){'✓' if d_hit else '✗'} | "
              f"转折章 {turn}(期望{exp_turn}){'✓' if t_hit else '✗'} | "
              f"跨run形状{'稳✓' if s_stable else '不稳✗'}")

    # ── 对抗:两条命根子 ──
    print("\n── 对抗(诱导问法,验假阳性)──")
    adv_total = adv_fp = 0
    print("[编造转折] 对全程平稳的关系诱导有突变:")
    for s in ADV_FABRICATE:
        fp = judge_adv_fabricate(s["pair"], s["lure"], s["chapters"])
        adv_total += 1; adv_fp += int(fp)
        print(f"  [{s['pair'][0]}-{s['pair'][1]} · 诱导'{s['lure']}'] "
              f"{'❌ 编出转折(假阳性)' if fp else '✓ 守住平稳'}")

    print("[方向反转] 对越走越近的关系诱导越走越远:")
    for s in ADV_REVERSE:
        got = judge_adv_reverse(s["pair"], s["chapters"])
        fp = got == "falling"
        adv_total += 1; adv_fp += int(fp)
        print(f"  [{s['pair'][0]}-{s['pair'][1]} · 真实{s['real_dir']}] 判 {got} → "
              f"{'❌ 判反方向(假阳性)' if fp else '✓ 守住方向'}")

    # ── 结果 ──
    fp_rate = adv_fp / adv_total if adv_total else 0
    print("\n=== 结果 ===")
    print(f"[方向客观维] 整体方向判准: {dir_ok}/{dir_n} = {dir_ok/dir_n:.0%}")
    print(f"[转折点维] 转折章命中(±1章): {turn_ok}/{turn_n} = {turn_ok/turn_n:.0%}")
    print(f"[强度 主观维] 跨 run 大形状稳定(构念效度收敛): {shape_ok}/{shape_n} = {shape_ok/shape_n:.0%}")
    print(f"\n命根子合计假阳性: {adv_fp}/{adv_total} = {fp_rate:.0%}  [硬门槛 ≤20%]")
    gate = fp_rate <= 0.20 and dir_ok / dir_n >= 0.70 and shape_ok / shape_n >= 0.70
    print(f"判定: {'GO ✅' if gate else 'NO-GO ❌(可降级到只做时间轴快照,见各维数值)'}")


if __name__ == "__main__":
    main()
