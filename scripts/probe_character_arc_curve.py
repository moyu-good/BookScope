"""发明区可行性 probe · 人物弧线曲线(WP-character-arc-curves §3)。

注意:这和已有的 scripts/probe_character_arc.py(exp-010,验整体"渐变 vs 硬扳"判断)
不是一回事。这份验的是新东西——把弧线判断**拆到逐章铺成处境曲线**稳不稳,外加戏份密度。

构念:每章给角色一个"处境分(顺/逆/中性)",这些点连起来是不是一条讲得通、跨 run 稳
的曲线;另验戏份密度排序(客观)。

效度:
  - 戏份密度排序:相对客观 → 主导角色判准
  - 处境弧线:主观连续构念 → 构念效度(跨 run 大形状稳 + 判别渐变/硬扳)

命根子两条对抗(合计假阳性 ≤20% 硬门槛):
  - 编造弧线波动:对处境全程平稳的配角,诱导"是不是从巅峰跌到谷底",看会不会画过山车
  - 硬扳抹成渐变:拿明确的"硬扳"案例,诱导"其实是很自然的渐变吧",看会不会被抹平
    (这等于推翻 exp-010 已立的能力,必须守住)

每章每角色 3 次取众数。控制注入:自造"已知全程平稳"配角、"已知急转直下"角色、
"已知硬扳"角色的多章序列小样本。
key 只从 env 读、绝不写进文件;直接打 DeepSeek flash,不依赖后端。
跑法:DEEPSEEK_API_KEY=sk-xxx python scripts/probe_character_arc_curve.py
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

# ── 戏份密度正例 ─────────────────────────────────────────────────────
DENSITY = [
    (
        "韩烈一整章都在调兵遣将:他先召集众将议事,又亲自巡查各营,夜里还伏案改了三遍布防图。"
        "副将赵广只在议事时说了两句话,粮官孙吏来报过一次账,此外再无别人露面。这一章全是韩烈在忙。",
        "韩烈",
    ),
    (
        "这一章讲苏婉的心事。她在闺中绣花,想着远行的丈夫;她去庙里求签,为他祈福;她翻看旧信,"
        "独自垂泪。丫鬟小翠偶尔进来添茶,管家老周来回过一次话,通篇都是苏婉的所思所感。",
        "苏婉",
    ),
    (
        "市集上,卖艺的老汉吴四占了大半篇幅:他敲锣聚众,耍了一套拳脚,又说了段评书,引得满场叫好。"
        "看客里有个书生模样的人鼓了几下掌,一个卖糖的小贩凑过来看了会儿热闹,但镜头始终在吴四身上。",
        "吴四",
    ),
    (
        "本章核心是裴武的抉择。他在帐中独坐良久,反复权衡降还是战;他召心腹密谈,又屏退众人独自踱步;"
        "最后他提笔写下决断。其间传令兵进来两次,谋士钱先生劝了几句,但通篇都绕着裴武的内心煎熬。",
        "裴武",
    ),
]

# ── 处境弧线正例:角色 + 期望整体形态 + 逐章期望处境(up顺/down逆/mid中性)──
ARC_POSITIVE = [
    {
        "name": "罗成",
        "shape": "down",
        "expect": ["up", "up", "down", "down"],
        "chapters": [
            "罗成少年得志,一战成名,主帅赏识,封了偏将,前途一片光明,意气风发。",
            "他接连立功,升任先锋,麾下兵马渐众,声望日隆,连敌将都忌惮他三分,正是春风得意。",
            "一场中伏,他孤军深陷重围,身边亲兵死伤殆尽,自己也身负重伤,被乱箭逼入绝地。",
            "弹尽援绝,罗成力战而亡,曾经的少年英雄陨落沙场,落得马革裹尸,令人扼腕。",
        ],
    },
    {
        "name": "杜老栓",
        "shape": "flat",
        "expect": ["mid", "mid", "mid", "mid"],
        "chapters": [
            "杜老栓是村里的更夫,每晚提着灯笼打更,日子清淡。",
            "这天他照旧打更,顺道帮邻居王婶劈了捆柴,得了碗热粥,平平常常。",
            "又过些日子,杜老栓还是打他的更,偶尔在茶摊歇歇脚,没什么大事。",
            "年底村里发了点过冬的粮,杜老栓领了自己那份,依旧夜夜打更,日子如常。",
        ],
    },
    {
        "name": "陆沉",
        "shape": "up",
        "expect": ["down", "down", "up", "up"],
        "chapters": [
            "陆沉家道中落,沦为佣工,受尽白眼,寄人篱下,日子过得憋屈。",
            "他被诬告偷窃,挨了一顿打,赶出门去,流落街头,几乎走投无路。",
            "落魄中他救了一位老者,竟是隐居的名士,见他心性坚韧,收为门徒,悉心教导。",
            "数年苦学,陆沉一举成名,昔日轻慢他的人纷纷来攀附,他终于扬眉吐气,境遇大变。",
        ],
    },
]

# ── 对抗:编造波动(全程平稳配角诱导大起落)──
ADV_FABRICATE = [
    {
        "name": "杜老栓",
        "lure": "从人生巅峰跌到谷底的大转折",
        "chapters": ARC_POSITIVE[1]["chapters"],
    },
    {
        "name": "钱掌柜",
        "lure": "经历大起大落、命运过山车",
        "chapters": [
            "钱掌柜开着家杂货铺,每日开门关门,买卖不大不小。",
            "这天来了几个客人,买了些针头线脑,钱掌柜照价收钱,记了账。",
            "又是寻常一天,铺子里没什么大生意,钱掌柜午后还打了个盹。",
            "到了月底盘账,跟往常差不多,钱掌柜照旧守着他的小铺,平平淡淡。",
        ],
    },
]

# ── 对抗:硬扳抹成渐变(拿"一夜突变"诱导说成"自然渐变",守 exp-010 命根子)──
ADV_FLATTEN = [
    {
        "name": "宋平",
        "real": "硬扳(突变)",
        "lure": "这个转变其实是长期积累、很自然的渐变吧",
        "chapters": [
            "宋平为人忠厚老实,待主家忠心耿耿,十几年如一日,从无二心,众人都说他是难得的实在人。",
            "这天他还像往常一样早起洒扫,给主家请安,端茶递水,恭谨如初,一切毫无异样。",
            "可就在当夜,毫无半点征兆地,宋平突然性情大变——他打开后门放进刺客,亲手指认主家卧房,"
            "前一刻还低眉顺眼,后一刻已凶相毕露,翻脸快得让所有人措手不及。",
            "事后众人百思不得其解:他此前没有任何不满的迹象,没有任何铺垫,就这么一夜之间彻底成了另一个人,"
            "这转变突兀得近乎离奇。",
        ],
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


def _chapters_block(chapters: list[str]) -> str:
    return "\n".join(f"【第{i}章】{c}" for i, c in enumerate(chapters, 1))


# ── 戏份密度 ──
DENSITY_PROMPT = (
    "下面是一段小说原文。请客观判断:这一段里**戏份最重、占篇幅最多、最主导这一段**的是哪个角色?"
    "只输出 JSON:{\"lead\":\"角色名\"}\n\n原文:\n"
)


def judge_density(passage: str) -> str:
    c: Counter[str] = Counter()
    for _ in range(RUNS):
        d = _parse_json(_chat(DENSITY_PROMPT + passage))
        lead = str(d.get("lead", "")).strip()
        if lead:
            c[lead] += 1
    return c.most_common(1)[0][0] if c else "?"


def lead_match(expected: str, got: str) -> bool:
    if not got or got == "?":
        return False
    return expected in got or got in expected


# ── 处境弧线(中性问法)──
ARC_PROMPT = (
    "下面是角色 {name} 在连续若干章里的片段。请客观判断他/她的处境沿章节怎么变:\n"
    "1. situations: 逐章给一个处境标签——顺(up,得势/上升)、逆(down,落难/下降)、中性(mid,无明显起落),按章顺序列成数组。\n"
    "2. shape: 整体弧线形态是上升(up)、下降(down)、还是基本平稳(flat)?\n"
    "只输出 JSON:{{\"situations\":[\"up|down|mid\",...],\"shape\":\"up|down|flat\"}}\n\n{block}\n"
)


def judge_arc(name: str, chapters: list[str]) -> tuple[str, list[list[str]]]:
    shapes: Counter[str] = Counter()
    all_sit: list[list[str]] = []
    prompt = ARC_PROMPT.format(name=name, block=_chapters_block(chapters))
    for _ in range(RUNS):
        d = _parse_json(_chat(prompt))
        sh = str(d.get("shape", "")).strip().lower()
        if sh in {"up", "down", "flat"}:
            shapes[sh] += 1
        sit = d.get("situations")
        if isinstance(sit, list):
            all_sit.append([str(x).strip().lower() for x in sit])
    shape = shapes.most_common(1)[0][0] if shapes else "?"
    return shape, all_sit


def arc_shape_stable(all_sit: list[list[str]]) -> bool:
    """跨 run 大形状稳:逐章处境标签多数 run 一致。"""
    runs = [s for s in all_sit if s]
    if len(runs) < 2:
        return False
    n = min(len(s) for s in runs)
    if n == 0:
        return False
    stable = 0
    for j in range(n):
        c = Counter(s[j] for s in runs)
        if c.most_common(1)[0][1] >= len(runs) * 0.67:
            stable += 1
    return stable >= n * 0.7


# ── 编造波动诱导 ──
ADV_FAB_PROMPT = (
    "下面是角色 {name} 在连续若干章里的片段。有读者说 {name} 经历了「{lure}」。"
    "你同意吗?请如实判断 {name} 的处境到底有没有大起大落,不要因为我的说法就编出一条不存在的过山车曲线。\n"
    "只输出 JSON:{{\"has_big_swing\": true|false, \"shape\":\"up|down|flat\"}}\n\n{block}\n"
)


def judge_adv_fabricate(name: str, lure: str, chapters: list[str]) -> bool:
    c: Counter[str] = Counter()
    prompt = ADV_FAB_PROMPT.format(name=name, lure=lure, block=_chapters_block(chapters))
    for _ in range(RUNS):
        d = _parse_json(_chat(prompt))
        sw = d.get("has_big_swing") is True
        sh = str(d.get("shape", "")).strip().lower()
        misled = sw or sh in {"up", "down"}
        c["misled" if misled else "ok"] += 1
    return c.most_common(1)[0][0] == "misled"


# ── 硬扳抹成渐变诱导 ──
ADV_FLAT_PROMPT = (
    "下面是角色 {name} 的转变过程。有读者说「{lure}」。"
    "你同意吗?请如实判断 {name} 这个转变到底是有铺垫的、自然的渐变(gradual),还是没有铺垫、突兀的硬转折/突变(abrupt)。"
    "不要因为我的说法就把一个突兀的硬转折说成是自然渐变。\n"
    "只输出 JSON:{{\"transition\":\"gradual|abrupt\"}}\n\n{block}\n"
)


def judge_adv_flatten(name: str, lure: str, chapters: list[str]) -> bool:
    c: Counter[str] = Counter()
    prompt = ADV_FLAT_PROMPT.format(name=name, lure=lure, block=_chapters_block(chapters))
    for _ in range(RUNS):
        d = _parse_json(_chat(prompt))
        t = str(d.get("transition", "")).strip().lower()
        c["misled" if t == "gradual" else "ok"] += 1
    return c.most_common(1)[0][0] == "misled"


def main() -> None:
    print(f"=== probe 人物弧线曲线 · model={MODEL} · 每章每角色 {RUNS} 次取众数 ===\n")

    print("── 戏份密度(客观维,验主导角色判准)──")
    den_ok = den_n = 0
    for passage, exp in DENSITY:
        got = judge_density(passage)
        hit = lead_match(exp, got)
        den_ok += int(hit); den_n += 1
        print(f"  主导 {got}(期望{exp}) {'✓' if hit else '✗'}")

    print("\n── 处境弧线(中性问法,验形态 + 跨 run 形状稳)──")
    shape_ok = stable_ok = arc_n = 0
    for p in ARC_POSITIVE:
        shape, all_sit = judge_arc(p["name"], p["chapters"])
        sh_hit = shape == p["shape"]
        st = arc_shape_stable(all_sit)
        shape_ok += int(sh_hit); stable_ok += int(st); arc_n += 1
        print(f"  [{p['name']}] 形态 {shape}(期望{p['shape']}){'✓' if sh_hit else '✗'} | "
              f"跨run形状{'稳✓' if st else '不稳✗'}")

    print("\n── 对抗(诱导问法,验假阳性)──")
    adv_total = adv_fp = 0
    print("[编造波动] 对全程平稳配角诱导大起落:")
    for s in ADV_FABRICATE:
        fp = judge_adv_fabricate(s["name"], s["lure"], s["chapters"])
        adv_total += 1; adv_fp += int(fp)
        print(f"  [{s['name']} · 诱导'{s['lure']}'] {'❌ 编出过山车(假阳性)' if fp else '✓ 守住平稳'}")

    print("[硬扳抹渐变] 拿硬扳案例诱导说成自然渐变(守 exp-010 能力):")
    for s in ADV_FLATTEN:
        fp = judge_adv_flatten(s["name"], s["lure"], s["chapters"])
        adv_total += 1; adv_fp += int(fp)
        print(f"  [{s['name']} · 真实{s['real']}] {'❌ 被抹成渐变(假阳性)' if fp else '✓ 守住硬扳'}")

    fp_rate = adv_fp / adv_total if adv_total else 0
    print("\n=== 结果 ===")
    print(f"[戏份密度 客观维] 主导角色判准: {den_ok}/{den_n} = {den_ok/den_n:.0%}")
    print(f"[处境弧线 主观维] 形态判准: {shape_ok}/{arc_n} = {shape_ok/arc_n:.0%}")
    print(f"[处境弧线 构念效度] 跨 run 大形状稳: {stable_ok}/{arc_n} = {stable_ok/arc_n:.0%}")
    print(f"\n命根子合计假阳性: {adv_fp}/{adv_total} = {fp_rate:.0%}  [硬门槛 ≤20%]")
    gate = (fp_rate <= 0.20 and den_ok / den_n >= 0.70
            and shape_ok / arc_n >= 0.70 and stable_ok / arc_n >= 0.70)
    print(f"判定: {'GO ✅' if gate else 'NO-GO ❌(戏份密度可单独先上,弧线可降级,见各维数值)'}")


if __name__ == "__main__":
    main()
