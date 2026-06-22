"""发明区可行性 probe · 人物叙事流图(WP-character-narrative-flow §3)。

构念:LLM 能不能从原文可靠判定"某段里哪些人物**同场/有直接互动**",
且不把"只是分别被提到、不在同一场景"的人物硬凑成同场(假阳性)。

方法:控制注入标注样本(已知同场 = 正例;已知分场 = 对抗伪负例),
每段 3 次取众数(某对人物 ≥2/3 次被判同场才算"抽到"),量:
  - 正例 recall:该抽到的同场对,抽到了几成(能力)
  - 对抗 假阳性率:把分场对错判成同场的比例 —— **≤20% 硬门槛(命根子)**

key 只从 env 读、绝不写进文件;直接打 DeepSeek flash,不依赖后端。
跑法:DEEPSEEK_API_KEY=sk-xxx python scripts/probe_character_cooccurrence.py
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
RUNS = 3  # 每段跑 3 次取众数

# 正例:同一场景里照面/对话/交手 —— 期望抽到的同场对
POSITIVE = [
    ("玄德同关羽、张飞来到庄前。玄德下马，亲叩柴门。童子出，玄德拱手问：先生在否？"
     "时孔明昼寝未起，玄德拱立阶下，等了半晌。孔明翻身又朝里壁睡着，玄德不敢惊动。",
     [("刘备", "诸葛亮")]),
    ("操执玄德手，同入小亭，已设樽俎。二人对坐，开怀畅饮。操以手指玄德，"
     "后自指曰：今天下英雄，惟使君与操耳！玄德闻言，吃了一惊，手中匙箸落于地下。",
     [("曹操", "刘备")]),
    ("玄德、关羽、张飞三人于桃园结为兄弟。焚香再拜，誓曰：同心协力，救困扶危。"
     "三人对天盟誓，饮酒大醉。",
     [("刘备", "关羽"), ("刘备", "张飞"), ("关羽", "张飞")]),
    ("云长提刀纵马，于华容道拦住去路。曹操在马上欠身谓云长曰：将军别来无恙？"
     "云长见操军惶惶，又想起旧日恩义，长叹一声，纵马放他过去。",
     [("关羽", "曹操")]),
    ("周瑜请孔明入帐议事。瑜曰：即日将与曹军交战，水路交兵，当以何兵器为先？"
     "孔明笑曰：大江之上，以弓箭为先。瑜暗喜，遂命其十日造十万支箭。",
     [("周瑜", "诸葛亮")]),
    ("吕布潜入凤仪亭，正见貂蝉立于亭下。貂蝉佯作泪眼，对布诉说董卓之逼。"
     "布按戟上前，正欲与语，忽见董卓自后赶来。",
     [("吕布", "貂蝉")]),
]

# 对抗:两人在同段里被**分别**提及、各在各的场景 —— 不该判为同场
ADVERSARIAL = [
    ("却说曹操在许都大宴群臣，商议征伐之事。且说刘备屯兵新野，日夜操练士卒，整顿城防。",
     ("曹操", "刘备")),
    ("孙权坐镇江东，广纳贤才，国势日盛。与此同时，马超在西凉起兵，誓为父报仇。",
     ("孙权", "马超")),
    ("诸葛亮在成都安抚百姓、整理屯田。彼时，司马懿于洛阳称病不出，暗中养望。",
     ("诸葛亮", "司马懿")),
    ("关羽镇守荆州，威震华夏。另一头，张飞在阆中督造军械、操演步卒。",
     ("关羽", "张飞")),
    ("袁绍据河北，地广兵多。荆州刘表则坐拥江汉，观望成败、不轻动兵。",
     ("袁绍", "刘表")),
    ("曹丕在邺城日夜读书、结交文士。同一时间，周瑜于柴桑养病，闲时操琴。",
     ("曹丕", "周瑜")),
]

PROMPT = (
    "下面是一段小说原文。请只列出在这段文字里**同场出现、有直接互动**的人物对"
    "(同一场景里照面、对话、交手才算;只是被分别提到、各在各的场景，不算)。\n"
    "只输出 JSON，格式 {\"pairs\": [[\"人物A\",\"人物B\"], ...]}，没有同场对就 {\"pairs\": []}。\n\n"
    "原文:\n"
)


def extract_pairs(passage: str) -> set[frozenset[str]]:
    body = {
        "model": MODEL,
        "messages": [{"role": "user", "content": PROMPT + passage}],
        "max_tokens": 400,
        "temperature": 0.0,
    }
    r = requests.post(
        "https://api.deepseek.com/chat/completions",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        json=body,
        timeout=120,
    )
    r.raise_for_status()
    txt = r.json()["choices"][0]["message"]["content"]
    # 宽松剥 JSON
    s = txt[txt.find("{"): txt.rfind("}") + 1] if "{" in txt else "{}"
    try:
        pairs = json.loads(s).get("pairs", [])
    except Exception:
        return set()
    out = set()
    for p in pairs:
        if isinstance(p, list) and len(p) == 2:
            out.add(frozenset(str(x).strip() for x in p))
    return out


def majority_pairs(passage: str) -> set[frozenset[str]]:
    cnt: Counter[frozenset[str]] = Counter()
    for _ in range(RUNS):
        for pr in extract_pairs(passage):
            cnt[pr] += 1
    return {pr for pr, c in cnt.items() if c >= 2}  # ≥2/3 取众数


def norm(name: str) -> set[str]:
    """人物别名归并(粗)——同一人多个称呼算命中。"""
    alias = {
        "刘备": {"刘备", "玄德"}, "诸葛亮": {"诸葛亮", "孔明"},
        "关羽": {"关羽", "云长"}, "曹操": {"曹操", "操"},
    }
    return alias.get(name, {name})


def pair_hit(target: tuple[str, str], extracted: set[frozenset[str]]) -> bool:
    a, b = norm(target[0]), norm(target[1])
    for pr in extracted:
        names = list(pr)
        if len(names) != 2:
            continue
        x, y = names
        if (x in a and y in b) or (x in b and y in a):
            return True
    return False


def main() -> None:
    print(f"=== probe 人物同场抽取 · model={MODEL} · 每段 {RUNS} 次取众数 ===\n")

    # 正例:期望对的命中率(recall)
    pos_total = pos_hit = 0
    for i, (passage, expected) in enumerate(POSITIVE, 1):
        ex = majority_pairs(passage)
        hits = [pair_hit(t, ex) for t in expected]
        pos_total += len(expected)
        pos_hit += sum(hits)
        print(f"[正例 {i}] 期望 {expected} → 命中 {sum(hits)}/{len(expected)}  抽到对数={len(ex)}")

    print()
    # 对抗:分场对被错判成同场的比例(假阳性)
    adv_total = adv_fp = 0
    for i, (passage, sep_pair) in enumerate(ADVERSARIAL, 1):
        ex = majority_pairs(passage)
        fp = pair_hit(sep_pair, ex)
        adv_total += 1
        adv_fp += int(fp)
        print(f"[对抗 {i}] 分场对 {sep_pair} → {'❌ 误判同场(假阳性)' if fp else '✓ 正确未判同场'}")

    recall = pos_hit / pos_total if pos_total else 0
    fp_rate = adv_fp / adv_total if adv_total else 0
    print("\n=== 结果 ===")
    print(f"正例 recall(同场对抽到率): {pos_hit}/{pos_total} = {recall:.0%}")
    print(f"对抗 假阳性率(分场误判同场): {adv_fp}/{adv_total} = {fp_rate:.0%}  [命根子门槛 ≤20%]")
    gate = fp_rate <= 0.20 and recall >= 0.70
    print(f"\n判定: {'GO ✅(假阳性达标 + recall 够)' if gate else 'NO-GO ❌'}")


if __name__ == "__main__":
    main()
