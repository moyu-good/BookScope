"""发明区可行性 probe · 角色 voice 一致性(WP-character-voice §3)。

构念:agent 能不能(a)归拢某角色对白、刻画其语言特征,(b)判出"这句不像他说的",
且**不把合理的口吻变化、不把样本不足、不把别人的话误判成 drift**。

主观构念 → 不用 precision/recall,用构念效度三件套 + 三类对抗伪负例:
  - 收敛:声口分明的角色,核心语言特征跨 3 次 run 稳不稳(能力)。
  - 判别:同一角色喂"真 drift 段"和"一致段",能不能分开。
  - 三类伪负例(各假阳性 ≤20% 硬门槛,命门):
      1. 合理变化——剧情驱动的口吻转变,诱导问"是不是 drift",理想=识别为合理、不报。
      2. 样本不足——角色只有三两句,看会不会硬刻画再倒打一耙,理想=明说样本不足、不判 drift。
      3. 张冠李戴——把 B 的话问"这是不是 A 说的、像不像 A",理想=指出不是 A 说的。

3 次取众数抗波动。教训(probe_relationship_over_time):判定按多数票过半即可,别要 3/3。

key 只从 env 读、绝不写进文件;直接打 DeepSeek flash,不依赖后端。
跑法:DEEPSEEK_API_KEY=sk-xxx python scripts/probe_character_voice.py
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

from dotenv import load_dotenv  # 从 gitignored .env 读 key（不进命令行/transcript）

load_dotenv()
API_KEY = os.environ.get("DEEPSEEK_API_KEY", "").strip()
if not API_KEY:
    print("ERROR: DEEPSEEK_API_KEY 未设置", file=sys.stderr)
    sys.exit(1)

MODEL = "deepseek-v4-flash"
RUNS = 3


def _chat(prompt: str, max_tokens: int = 600) -> str:
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


def _parse_json(txt: str) -> dict:
    s = txt[txt.find("{"): txt.rfind("}") + 1] if "{" in txt else "{}"
    try:
        return json.loads(s)
    except Exception:
        return {}


# ── 角色对白语料:两个声口分明的角色 ──────────────────────────────────
# 张铁牛:粗豪武夫,大白话、短句、爱骂、爱用"老子/娘的/砍/揍"
ZHANG_LINES = [
    "娘的,这帮孙子又来抢粮!老子跟他们拼了!",
    "怕个鸟!脑袋掉了碗大个疤,十八年后又是一条好汉!",
    "少废话,谁不服老子一刀劈了他!",
    "饿了就吃,困了就睡,想那么多干啥,脑子又不是用来打仗的。",
    "兄弟们抄家伙,跟老子上!",
]
# 沈砚之:文人谋士,文白、长句、爱引典、说话绕、爱用"窃以为/恐/不妨/未尝不可"
SHEN_LINES = [
    "窃以为此役不宜速进,敌据坚城而我悬师在外,粮道一断,恐有覆军之危。",
    "兵者诡道,虚则实之,实则虚之,将军不妨示弱以骄其志,再图后举,未尝不可。",
    "古人云,小不忍则乱大谋。眼下隐忍数日,他日方能一击而定,何必争此朝夕。",
    "在下观天时人事,皆不在彼而在我,将军但能持重,胜算自归。",
]

# 真 drift 段:把张铁牛(粗人)的嘴里塞一句沈砚之式的文绉绉排比(明显出戏)
ZHANG_DRIFT_LINE = "窃以为此事当从长计议,夫兵者国之大事,死生之地,存亡之道,不可不察也。"
# 一致段:还是张铁牛本色的话(用于判别对照)
ZHANG_CONSISTENT_LINE = "管他娘的什么计议,老子带人冲过去砍了他不就完了!"

# 对抗 1·合理变化:张铁牛的兄弟战死,他在坟前少见地沉默低声——口吻变了但有剧情理由
ZHANG_REASONABLE_SHIFT = (
    "张铁牛跪在新坟前,半晌没说话。他粗糙的大手按在土堆上,声音低得几乎听不见:"
    "\"二娃,哥没护住你……你放心走,这仇,哥替你报。\" 这个平日里嗓门震天的汉子,这一刻没骂一句脏话。"
)

# 对抗 2·样本不足:全书只露过两句的小角色(刻意给极少样本)
MINOR_CHAR = "李四"
MINOR_LINES = ["是。", "小人遵命。"]
MINOR_QUESTION_LINE = "回大人,此事另有隐情,容小人细禀。"  # 问这句"像不像李四说的"

# 对抗 3·张冠李戴:把沈砚之的一句很有特色的文人话,问"这是不是张铁牛说的、像不像他腔调"
CROSS_ATTR_LINE = "古人云,小不忍则乱大谋,将军何必争此朝夕。"  # 实为沈砚之口吻


# ── 收敛:刻画语言特征,跨 run 看核心特征稳不稳 ────────────────────────
def profile_voice(name: str, lines: list[str]) -> list[Counter]:
    prompt_head = (
        f"下面是小说人物「{name}」的全部对白。请客观刻画他说话的语言特征,只抽最核心的几条"
        "(用词偏好、句长长短、文白程度、语气、口头禅),每条不超过 12 字。\n"
        "只输出 JSON:{\"traits\":[\"...\",\"...\"]}\n\n对白:\n"
        + "\n".join(f"- {ln}" for ln in lines)
    )
    runs: list[Counter] = []
    for _ in range(RUNS):
        d = _parse_json(_chat(prompt_head))
        c: Counter = Counter()
        for t in d.get("traits", []):
            # 归一到几个语义桶,看核心特征是否稳定复现
            s = str(t)
            for bucket, kws in {
                "粗俗/脏话": ["脏", "粗", "骂", "俗", "老子", "娘"],
                "短句/直白": ["短", "直", "白", "简"],
                "文白/引典": ["文", "雅", "典", "古", "书"],
                "长句/绕": ["长", "绕", "复杂", "委婉"],
                "语气冲/豪": ["冲", "豪", "横", "硬", "狠"],
                "谨慎/委婉": ["谨", "婉", "恐", "慎", "稳"],
            }.items():
                if any(kw in s for kw in kws):
                    c[bucket] += 1
        runs.append(c)
    return runs


def convergence(runs: list[Counter]) -> tuple[set, float]:
    """核心特征桶:在 ≥2/RUNS 次里出现的桶 = 稳定特征。返回(稳定桶, 稳定占比)。"""
    bucket_runs: Counter = Counter()
    for c in runs:
        for b in c:
            bucket_runs[b] += 1
    stable = {b for b, n in bucket_runs.items() if n >= 2}
    all_buckets = set(bucket_runs)
    ratio = len(stable) / len(all_buckets) if all_buckets else 0.0
    return stable, ratio


# ── 判别:真 drift 段 vs 一致段,agent 能不能分开 ──────────────────────
DISCRIM_PROMPT = (
    "小说人物「{name}」平日说话的腔调是:{style}。\n"
    "现在有一句据称是他说的话:「{line}」\n"
    "请判断这句话像不像「{name}」平日的腔调。只输出 JSON:"
    "{{\"like\": true|false, \"reason\":\"一句话\"}}(like=true 表示像他、口吻一致;false 表示不像、疑似 drift)"
)


def judge_like(name: str, style: str, line: str) -> bool | None:
    """3 次取众数,返回 like(True=像/一致, False=不像/drift, None=无定论)。"""
    c: Counter = Counter()
    for _ in range(RUNS):
        d = _parse_json(_chat(DISCRIM_PROMPT.format(name=name, style=style, line=line)))
        v = d.get("like")
        if isinstance(v, bool):
            c["like" if v else "drift"] += 1
    if not c:
        return None
    return c.most_common(1)[0][0] == "like"


# ── 对抗 1·合理变化:诱导问"是不是 drift",理想=识别为合理、不报 ────────
ADV_REASONABLE_PROMPT = (
    "小说人物「张铁牛」平时是个嗓门大、爱骂脏话、说话很冲的粗豪武夫。\n"
    "下面这段里他的说话方式和平时很不一样,有读者觉得这是作者写崩了的 voice drift。你同意吗?\n"
    "请如实判断:这是作者笔误式的口吻失控(drift),还是剧情情境驱动的合理口吻变化?"
    "不要因为我的说法就附和。只输出 JSON:{\"drift\": true|false, \"reason\":\"一句话\"}\n\n段落:\n"
)


def judge_adv_reasonable() -> bool:
    """返回是否被带着把合理变化判成 drift(drift=true 算假阳性)。"""
    c: Counter = Counter()
    for _ in range(RUNS):
        d = _parse_json(_chat(ADV_REASONABLE_PROMPT + ZHANG_REASONABLE_SHIFT))
        v = d.get("drift")
        c["fp" if v is True else "ok"] += 1
    return c.most_common(1)[0][0] == "fp"


# ── 对抗 2·样本不足:看会不会硬刻画再判 drift,理想=明说样本不足 ─────────
ADV_FEWSHOT_PROMPT = (
    f"小说人物「{MINOR_CHAR}」全书只出现过这两句话:\n"
    + "\n".join(f"- {ln}" for ln in MINOR_LINES)
    + f"\n\n现在有一句据称是他说的:「{MINOR_QUESTION_LINE}」\n"
    "请判断这句是不是「不像他说的」(voice drift)。\n"
    "注意:如果样本太少、不足以刻画一个人的说话腔调,请如实说样本不足、无法判定,不要硬下 drift 结论。\n"
    "只输出 JSON:{\"verdict\":\"drift|consistent|insufficient_sample\", \"reason\":\"一句话\"}"
)


def judge_adv_fewshot() -> bool:
    """返回是否在样本不足时硬下了 drift/consistent 判定(没说 insufficient 算假阳性)。"""
    c: Counter = Counter()
    for _ in range(RUNS):
        d = _parse_json(_chat(ADV_FEWSHOT_PROMPT))
        v = str(d.get("verdict", "")).strip().lower()
        # 理想是 insufficient_sample;硬判 drift 或 consistent 都算"没守住样本不足"
        c["fp" if v in {"drift", "consistent"} else "ok"] += 1
    return c.most_common(1)[0][0] == "fp"


# ── 对抗 3·张冠李戴:把沈砚之的话问"是不是张铁牛说的",理想=指出不是他说的 ──
ADV_CROSS_PROMPT = (
    "小说人物「张铁牛」是个嗓门大、爱骂脏话、说话很冲、满嘴大白话的粗豪武夫。\n"
    f"下面这句话据说是他说的:「{CROSS_ATTR_LINE}」\n"
    "请判断:这句话像不像张铁牛的腔调?是不是真出自他口?\n"
    "只输出 JSON:{\"is_his\": true|false, \"reason\":\"一句话\"}"
    "(is_his=true 表示像他/认为是他说的;false 表示不像他/不是他的腔调)"
)


def judge_adv_cross() -> bool:
    """返回是否被带着附和"这是张铁牛说的/像他"(is_his=true 算假阳性)。"""
    c: Counter = Counter()
    for _ in range(RUNS):
        d = _parse_json(_chat(ADV_CROSS_PROMPT))
        v = d.get("is_his")
        c["fp" if v is True else "ok"] += 1
    return c.most_common(1)[0][0] == "fp"


def main() -> None:
    print(f"=== probe 角色 voice 一致性 · model={MODEL} · 每项 {RUNS} 次取众数 ===\n")

    # ── 收敛 ──
    print("── 收敛(声口分明角色,核心特征跨 run 稳不稳)──")
    zhang_runs = profile_voice("张铁牛", ZHANG_LINES)
    z_stable, z_ratio = convergence(zhang_runs)
    print(f"  张铁牛 稳定特征桶: {z_stable}  稳定占比={z_ratio:.0%}")
    shen_runs = profile_voice("沈砚之", SHEN_LINES)
    s_stable, s_ratio = convergence(shen_runs)
    print(f"  沈砚之 稳定特征桶: {s_stable}  稳定占比={s_ratio:.0%}")
    # 收敛判准:粗人应抓到粗俗/冲,文人应抓到文白/谨慎
    zhang_ok = bool(z_stable & {"粗俗/脏话", "短句/直白", "语气冲/豪"})
    shen_ok = bool(s_stable & {"文白/引典", "长句/绕", "谨慎/委婉"})
    print(f"  张铁牛特征抓对(粗/冲/直)= {zhang_ok} | 沈砚之特征抓对(文/绕/慎)= {shen_ok}")

    # ── 判别 ──
    print("\n── 判别(真 drift 段 vs 一致段,能不能分开)──")
    zhang_style = "嗓门大、爱骂脏话、说话很冲、满嘴大白话的粗豪武夫"
    like_drift = judge_like("张铁牛", zhang_style, ZHANG_DRIFT_LINE)
    like_cons = judge_like("张铁牛", zhang_style, ZHANG_CONSISTENT_LINE)
    print(f"  真 drift 段(塞了文绉绉排比)→ judge like={like_drift} (理想 False=判出 drift)")
    print(f"  一致段(本色粗话)→ judge like={like_cons} (理想 True=判为一致)")
    discrim_ok = (like_drift is False) and (like_cons is True)
    print(f"  判别成立(drift 判 drift、一致判一致)= {discrim_ok}")

    # ── 三类对抗伪负例 ──
    print("\n── 三类对抗伪负例(各假阳性 ≤20% 硬门槛)──")
    fp_reasonable = judge_adv_reasonable()
    print(f"  [1 合理变化] {'❌ 把合理变化判成 drift(假阳性)' if fp_reasonable else '✓ 识别为合理、未报'}")
    fp_fewshot = judge_adv_fewshot()
    print(f"  [2 样本不足] {'❌ 样本不足仍硬下判定(假阳性)' if fp_fewshot else '✓ 守住、说样本不足'}")
    fp_cross = judge_adv_cross()
    print(f"  [3 张冠李戴] {'❌ 附和这是张铁牛说的(假阳性)' if fp_cross else '✓ 指出不是他的腔调'}")

    # 每类 1 个样本,假阳性率 = 命中/1(0% 或 100%);三类合计也给
    adv_results = [fp_reasonable, fp_fewshot, fp_cross]
    fp_rate_each = [1.0 if x else 0.0 for x in adv_results]
    fp_rate_total = sum(adv_results) / len(adv_results)

    print("\n=== 结果 ===")
    print(f"收敛: 张铁牛特征抓对={zhang_ok} 稳定占比={z_ratio:.0%} | 沈砚之特征抓对={shen_ok} 稳定占比={s_ratio:.0%}")
    print(f"判别: {'成立' if discrim_ok else '不成立'}(真 drift→{like_drift} / 一致→{like_cons})")
    print(f"三类对抗假阳性: 合理变化={fp_rate_each[0]:.0%} 样本不足={fp_rate_each[1]:.0%} 张冠李戴={fp_rate_each[2]:.0%}  [各≤20%]")
    print(f"三类合计假阳性: {sum(adv_results)}/3 = {fp_rate_total:.0%}")

    # 门槛:三类假阳性各 ≤20%(每类 1 样本意味着该类必须 0 假阳性)+ 收敛 + 判别
    adv_gate = all(r <= 0.20 for r in fp_rate_each)
    gate = adv_gate and zhang_ok and shen_ok and discrim_ok
    print(f"\n判定: {'GO ✅(假阳性达标 + 收敛 + 判别成立)' if gate else 'NO-GO ❌(看上面哪条没过)'}")


if __name__ == "__main__":
    main()
