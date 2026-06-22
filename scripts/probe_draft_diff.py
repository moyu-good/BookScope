"""发明区可行性 probe · 草稿版本对比(WP-draft-diff §3)。

命根子是死穴:叙事 diff 报出的"v1→v2 变化",必须是稿子真改了引起的,
不是 LLM 诊断在同一份稿上跑两次的固有抖动。

方法(照 WP-draft-diff §3 的抗抖动设计):
  - 把每个版本跑成结构化叙事产物(这里取最客观的两类:设定/事实点集 + 伏笔埋收点集),
    每版各跑 3 次,只取"3 次里 ≥2 次稳定出现"的稳定集,先把分析噪声压掉。
  - diff = 两版稳定集之间的对称差。
  - 死穴门槛(v1-vs-v1' 自比):构造一个和 v1 完全相同的 v1',
    它们的 diff 必须近空——报出的"变化"占比 = 噪声,≤20% 才 GO;
    否则报的全是 LLM 抖动冒充改动 → NO-GO。
  - recall(v1-vs-v2):v2 在 v1 上做一处已知叙事改动(删掉一处伏笔回收 + 改一处设定),
    diff 必须抓到这处注入改动。

教训(probe_relationship_over_time):判定函数 bug 会造成假 NO-GO。
  - 稳定集用"出现 ≥2/3 次"取,过半即可,不要求 3/3。
  - "变化占比"分母用两版稳定集并集大小,自适应规模,不写死绝对条数阈值。

key 只从 env 读、绝不写进文件;直接打 DeepSeek flash,不依赖后端。
跑法:DEEPSEEK_API_KEY=sk-xxx python scripts/probe_draft_diff.py
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
RUNS = 3  # 每版各跑 3 次取稳定集

# ── v1:一段自造的小说原文(含若干可抽取的设定点 + 一处伏笔埋—收) ──────────
V1 = """\
第一章。镇北侯之子萧决,自幼习剑,十六岁那年随父出征雁门关,亲手斩了北狄先锋拓跋烈。
临行前,老侯爷把祖传的玄铁断剑交给他,只说了一句:此剑认主,断剑重铸之日,便是萧家血仇得报之时。
萧决佩着这柄缺了一角的断剑,从此再未离身。军中都说他冷面寡言,唯独对副将陈五例外——
当年雁门关一役,是陈五替他挡了北狄人射来的一箭,两人自此过命。

第八章。三年后,萧决已是镇北军主将。这夜他独坐帐中,借着烛火又摩挲那柄玄铁断剑。
帐外陈五来报:北狄王庭内乱,正是出兵良机。萧决却摇头,说时机未到,断剑未重铸,他不动。
陈五不解,萧决只道:父亲临终的话,我一日不敢忘。

第十五章。决战之日,萧决在阵前将玄铁断剑高举过顶。当年那个为他挡箭的陈五,如今已是他最信任的左膀右臂。
两军相接,萧决一剑挑落北狄王旗。战后,他终于命人将那柄缺角的断剑送入军中铁匠铺,
亲眼看着它在炉火里重铸成一柄完整的长剑——萧家三代血仇,至此得报。老侯爷当年那句话,应验了。
"""

# ── v1':和 v1 一字不差(死穴自比对照) ──────────────────────────────────
V1_PRIME = V1

# ── v2:在 v1 上做两处已知叙事改动 ─────────────────────────────────────
#   改动 A(断伏笔回收):删掉第十五章"断剑重铸"那一整段回收——埋点(第一章老侯爷的话)还在,回收没了。
#   改动 B(改设定):把"陈五替萧决挡箭"改成"萧决替陈五挡箭"(救命方向反转,人物关系设定变了)。
V2 = """\
第一章。镇北侯之子萧决,自幼习剑,十六岁那年随父出征雁门关,亲手斩了北狄先锋拓跋烈。
临行前,老侯爷把祖传的玄铁断剑交给他,只说了一句:此剑认主,断剑重铸之日,便是萧家血仇得报之时。
萧决佩着这柄缺了一角的断剑,从此再未离身。军中都说他冷面寡言,唯独对副将陈五例外——
当年雁门关一役,是萧决替陈五挡了北狄人射来的一箭,两人自此过命。

第八章。三年后,萧决已是镇北军主将。这夜他独坐帐中,借着烛火又摩挲那柄玄铁断剑。
帐外陈五来报:北狄王庭内乱,正是出兵良机。萧决却摇头,说时机未到,断剑未重铸,他不动。
陈五不解,萧决只道:父亲临终的话,我一日不敢忘。

第十五章。决战之日,萧决在阵前将玄铁断剑高举过顶。当年那个被他挡箭救下的陈五,如今已是他最信任的左膀右臂。
两军相接,萧决一剑挑落北狄王旗。战后,他望着满地尸骸,只觉父亲的遗愿仍遥遥无期。
"""

# 预期 v1→v2 应抓到的两处改动(用关键词宽松判命中)
EXPECTED_CHANGES = [
    {"name": "断伏笔回收(断剑重铸未交代)", "keywords": ["断剑", "重铸", "血仇", "伏笔", "遗愿", "未", "没", "回收"]},
    {"name": "设定反转(挡箭救命方向)", "keywords": ["挡箭", "挡了", "救", "陈五", "萧决", "方向", "反", "谁救谁"]},
]


# ── 结构化叙事产物抽取:取最客观的两类(设定/事实点 + 伏笔埋收) ──────────
EXTRACT_PROMPT = (
    "下面是一段小说原文。请把它的**结构化叙事要素**抽出来,只抽两类,要客观、贴原文,不要脑补:\n"
    "1. facts: 关键设定/事实点列表(谁做了什么、谁救了谁、什么物件有什么设定、人物关系)。"
    "每条是一句不超过 20 字的陈述句。\n"
    "2. foreshadow: 伏笔的埋点和回收点。每条 {\"setup\":\"埋点一句话\",\"payoff\":\"回收点一句话或\\\"未回收\\\"\"}。\n"
    "只输出 JSON:{\"facts\":[\"...\"],\"foreshadow\":[{\"setup\":\"...\",\"payoff\":\"...\"}]}\n\n原文:\n"
)


def _chat(prompt: str, max_tokens: int = 800) -> str:
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


# 把一条结构化要素归一成一个粗粒度"语义键",抗逐字抖动:
#   facts → 取去标点后的字符 bag(集合),两条 fact 字符重合度高 = 同一条
#   这样"萧决斩拓跋烈" 和 "萧决亲手斩了拓跋烈" 会被认作同一条,不算"变化"。
def _norm_text(s: str) -> frozenset[str]:
    drop = set("。,，、:：;；!！?？\"'「」《》()（） \n\t的了是在和与对把被将就都也还又只")
    return frozenset(ch for ch in str(s) if ch not in drop)


def _similar(a: frozenset[str], b: frozenset[str]) -> bool:
    """两条要素是否"同一条"(Jaccard ≥ 0.6,抗措辞抖动)。"""
    if not a or not b:
        return False
    inter = len(a & b)
    union = len(a | b)
    return union > 0 and inter / union >= 0.6


def stable_set(passage: str) -> list[frozenset[str]]:
    """每版跑 RUNS 次,返回稳定集:在 ≥2/RUNS 次里出现的要素(过半即可)。

    要素 = facts 每条 + foreshadow 每条(setup||payoff 拼起来)统一成语义键。
    """
    # 收集每次跑出的要素键
    per_run: list[list[frozenset[str]]] = []
    for _ in range(RUNS):
        d = _parse_json(_chat(EXTRACT_PROMPT + passage))
        keys: list[frozenset[str]] = []
        for f in d.get("facts", []):
            k = _norm_text(f)
            if k:
                keys.append(k)
        for fs in d.get("foreshadow", []):
            if isinstance(fs, dict):
                k = _norm_text(str(fs.get("setup", "")) + str(fs.get("payoff", "")))
                if k:
                    keys.append(k)
        per_run.append(keys)

    # 跨 run 聚类计票:把语义相近的要素归为一簇,统计它在几次 run 里出现
    clusters: list[frozenset[str]] = []
    cluster_runs: list[set[int]] = []
    for ri, keys in enumerate(per_run):
        for k in keys:
            placed = False
            for ci, c in enumerate(clusters):
                if _similar(k, c):
                    cluster_runs[ci].add(ri)
                    placed = True
                    break
            if not placed:
                clusters.append(k)
                cluster_runs.append({ri})

    threshold = 2  # 过半(3 次里 ≥2 次),不要求 3/3
    return [clusters[i] for i in range(len(clusters)) if len(cluster_runs[i]) >= threshold]


def diff_sets(a: list[frozenset[str]], b: list[frozenset[str]]) -> tuple[list, list]:
    """返回 (只在 a 有的, 只在 b 有的) —— 对称差,按语义相近匹配。"""
    only_a = [x for x in a if not any(_similar(x, y) for y in b)]
    only_b = [x for x in b if not any(_similar(y, x) for y in a)]
    return only_a, only_b


def change_ratio(a: list[frozenset[str]], b: list[frozenset[str]]) -> float:
    """变化占比 = 对称差条数 / 两版稳定集并集条数(自适应规模)。"""
    only_a, only_b = diff_sets(a, b)
    # 并集大小:a 的全部 + b 中不与 a 相似的(避免重复计)
    union = len(a) + len(only_b)
    if union == 0:
        return 0.0
    return (len(only_a) + len(only_b)) / union


def hit_expected(only_a: list, only_b: list, change: dict) -> bool:
    """注入改动是否被 diff 抓到:对称差里任一条命中该改动的关键词(≥2 个关键词)。"""
    kws = change["keywords"]
    for item in list(only_a) + list(only_b):
        chars = set("".join(item))
        if sum(1 for kw in kws if any(c in chars for c in kw)) >= 2:
            return True
    return False


def main() -> None:
    print(f"=== probe 草稿版本对比 · model={MODEL} · 每版 {RUNS} 次取稳定集 ===\n")

    print("抽取 v1 稳定集 ...")
    s_v1 = stable_set(V1)
    print(f"  v1 稳定集条数 = {len(s_v1)}")

    print("抽取 v1'(与 v1 一字不差)稳定集 ...")
    s_v1p = stable_set(V1_PRIME)
    print(f"  v1' 稳定集条数 = {len(s_v1p)}")

    print("抽取 v2(注入两处改动)稳定集 ...")
    s_v2 = stable_set(V2)
    print(f"  v2 稳定集条数 = {len(s_v2)}\n")

    # ── 死穴:v1-vs-v1' 自比噪声 ──
    noise_ratio = change_ratio(s_v1, s_v1p)
    print("── 死穴:v1-vs-v1' 自比(同一份稿,应近空)──")
    only_a, only_b = diff_sets(s_v1, s_v1p)
    print(f"  对称差 = {len(only_a)}(只在v1) + {len(only_b)}(只在v1') ")
    print(f"  噪声占比 = {noise_ratio:.0%}  [死穴门槛 ≤20%]")

    # ── recall:v1-vs-v2 抓注入改动 ──
    print("\n── recall:v1-vs-v2(应抓到注入的两处改动)──")
    only_a2, only_b2 = diff_sets(s_v1, s_v2)
    print(f"  对称差 = {len(only_a2)}(只在v1,即被删/改掉的) + {len(only_b2)}(只在v2,即新引入的)")
    hits = []
    for ch in EXPECTED_CHANGES:
        h = hit_expected(only_a2, only_b2, ch)
        hits.append(h)
        print(f"  注入改动「{ch['name']}」 → {'✓ 抓到' if h else '✗ 漏抓'}")
    recall = sum(hits) / len(hits)

    # ── 判定 ──
    print("\n=== 结果 ===")
    print(f"死穴 v1-vs-v1' 噪声占比: {noise_ratio:.0%}  [门槛 ≤20%]")
    print(f"注入改动 recall: {sum(hits)}/{len(hits)} = {recall:.0%}")
    gate = noise_ratio <= 0.20 and recall >= 0.70
    print(f"\n判定: {'GO ✅(噪声压得住 + 抓得到真改动)' if gate else 'NO-GO ❌'}")
    if noise_ratio > 0.20:
        print("  → 死穴未过:v1-vs-v1' 噪声超门槛,报的'变化'是 LLM 抖动冒充改动,整本叙事 diff 不上。")


if __name__ == "__main__":
    main()
