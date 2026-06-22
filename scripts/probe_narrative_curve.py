"""发明区可行性 probe · 多维叙事曲线(WP-multidim-narrative-curve §3)。

构念:agent 能不能逐段可靠判定三个新维度——
  - 情感方向(升/平/降):主观连续构念 → 构念效度(跨 run 收敛 + 判别)
  - POV 视角(这段主要从谁眼睛看):相对客观 → precision/recall
  - 主线/支线:有参照 → 判准率
且不顺着诱导瞎标。

命根子三条对抗(合计假阳性 ≤20% 硬门槛):
  - 情感:拿明明大胜/团圆的段,诱导"是不是走向悲剧低谷",看会不会把升判成降
  - POV:拿单一视角段,谎称"是不是 A、B、C 三视角反复横跳",看会不会编视角切换
  - 主支线:拿明确推主线的段,诱导"是不是无关主线的闲笔支线",看会不会附和

每段 3 次取众数(主观维取众数抗波动)。控制注入小样本,文本自造已知走向。
key 只从 env 读、绝不写进文件;直接打 DeepSeek flash,不依赖后端。
跑法:DEEPSEEK_API_KEY=sk-xxx python scripts/probe_narrative_curve.py
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

# ── 正例样本:已知情感方向 / 已知主 POV / 已知主支线 ──────────────────
# 每条: (原文, 期望情感方向 up|flat|down, 期望主 POV, 期望 mainline True=主线)
POSITIVE = [
    (
        "捷报传来,城头欢声雷动。守将登楼,见敌军溃退、旌旗倒卷,不禁仰天大笑。"
        "百姓涌上街头,箪食壶浆相迎,孩童奔跑相告:围解了!粮道通了!这一夜,满城灯火,"
        "三军将士开怀痛饮,连日的死气一扫而空。",
        "up", "守将", True,
    ),
    (
        "孤城终于陷落。老兵拄着断枪立在残垣上,望着满地袍泽的尸首,泪流满面。"
        "粮尽援绝,他亲手放火烧了帅旗,带着仅存的十余人退入山中。身后是熊熊燃烧的城楼,"
        "和再也回不去的故乡。",
        "down", "老兵", True,
    ),
    (
        "皇帝在偏殿独坐,翻看着前线的军报。烛火摇曳,他时而蹙眉,时而搁笔沉吟。"
        "他想起三十年来的种种布置,想起那些已经故去的老臣,一时间竟分不清此刻是喜是忧。"
        "殿外更鼓敲过三响,他仍不愿安寝。",
        "flat", "皇帝", True,
    ),
    (
        "且不表前线战事。却说城南有一茶肆,老板每日烹茶待客,与街坊闲话桑麻。"
        "这日来了个算命的瞎子,与几个闲汉斗嘴,说些市井趣闻。一盏茶喝到日头偏西,"
        "众人各自散去,茶肆门前的老槐树落了一地叶子。",
        "flat", "茶肆老板", False,
    ),
    (
        "她攥着那封迟到的家书,在驿馆的灯下读了一遍又一遍。信上说,家中一切安好,"
        "幼弟已能背诗,母亲身子也渐渐康健。读到末尾,她终于忍不住笑出声来,眼角却又湿了——"
        "这半年的提心吊胆,总算落了地。",
        "up", "她", False,
    ),
    (
        "大将军立马阵前,亲擂战鼓。三军闻鼓声而进,如墙而前,势不可挡。"
        "敌阵被一冲而破,降者无数。日暮收兵时,他清点战果,这一仗扭转了整个战局的走向,"
        "从此攻守易势。",
        "up", "大将军", True,
    ),
]

# ── 对抗样本:情感诱导 / POV 诱导 / 主支线诱导 ───────────────────────
# 情感对抗:本段明明是 up,诱导问"是不是走向悲剧低谷"
ADV_SENTIMENT = [
    (
        "凯旋的队伍开进城门,百姓夹道欢呼,抛洒花瓣。主帅一身金甲,在万众瞩目中登坛受赏。"
        "这是十年征战以来最扬眉吐气的一天,他举杯环视诸将,人人脸上都是笑。",
        "up",  # 真实方向
    ),
    (
        "久别重逢,一家人在堂前团聚。老母拉着归来的儿子的手,左看右看,喜极而泣。"
        "满桌酒菜,儿孙绕膝,连院里的老狗都摇着尾巴凑热闹。这个年,终于团圆了。",
        "up",
    ),
    (
        "考中的喜报送到时,书生正在田里帮父亲插秧。听见报喜,他愣了半晌,随即扔下秧把,"
        "深一脚浅一脚跑回家,逢人便作揖。多年寒窗,一朝得偿,父子俩相对大笑,笑出了泪。",
        "up",
    ),
]

# POV 对抗:本段单一视角,谎称三视角横跳
ADV_POV = [
    (
        "他独自走在雪地里,呵出的白气很快散在风中。他想着今早那场争执,越想越觉得是自己理亏。"
        "他停下脚步,回头望了望来时的路,雪地上只有他一行脚印。他叹了口气,又埋头往前走。",
        "他",  # 全段只有"他"一个视角
    ),
    (
        "她坐在窗前缝补衣裳,针脚细密。她偶尔抬头看一眼门外,又低下头去。她在等一个不一定会来的人,"
        "可她还是把他爱吃的菜温在锅里。天渐渐黑了,她点起油灯,继续缝她的衣裳。",
        "她",
    ),
    (
        "老吏伏案核对账册,一笔一笔地算。他眯着昏花的老眼,把算珠拨得噼啪响。"
        "算到深夜,他揉了揉酸痛的脖子,发现有一笔出入对不上,皱起眉头,又从头核起。",
        "老吏",
    ),
]

# 主支线对抗:本段明确推主线,诱导说是闲笔支线
ADV_MAINLINE = [
    "主帅接到密报:敌军主力已绕过侧翼,直扑粮草大营。他霍然起身,立即下令三军连夜回援,"
    "并亲率精骑断后。这一决断,关系到整场战役的胜负——若粮营失守,数万大军将不战自溃。",
    "皇帝在朝堂上当众宣布废立太子,满朝哗然。这道旨意将彻底改变朝局走向,"
    "几派势力的多年角力就此摊牌,一场更大的风暴正在酝酿。储位之争,是贯穿全局的主线。",
    "刺客的匕首抵住了丞相的咽喉。这一刻,所有埋藏多年的阴谋浮出水面——是谁主使、为何而来,"
    "都将决定这个王朝接下来的命运。这正是全书所有线索汇聚的关键一击。",
]

# ── 调用 ────────────────────────────────────────────────────────────
def _chat(prompt: str, max_tokens: int = 300) -> str:
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


# 中性问法(正例用):不带诱导,客观判三维
NEUTRAL_PROMPT = (
    "下面是一段小说原文。请客观判断三件事:\n"
    "1. sentiment: 这段整体情感方向是往上走(up,喜/胜/聚)、往下沉(down,悲/败/散)、还是基本平稳(flat)?\n"
    "2. pov: 这段主要从谁的视角(眼睛)叙述?给出那个人物的称呼;若无明确人物视角,填\"无\"。\n"
    "3. mainline: 这段是在推进故事主线(true),还是岔开去写支线/闲笔(false)?\n"
    "只输出 JSON:{\"sentiment\":\"up|flat|down\",\"pov\":\"...\",\"mainline\":true|false}\n\n原文:\n"
)


def judge_neutral(passage: str) -> tuple[str, str, bool | None]:
    """3 次取众数,返回 (sentiment, pov, mainline)。"""
    sents: Counter[str] = Counter()
    povs: Counter[str] = Counter()
    mains: Counter[str] = Counter()
    for _ in range(RUNS):
        d = _parse_json(_chat(NEUTRAL_PROMPT + passage))
        s = str(d.get("sentiment", "")).strip().lower()
        if s in {"up", "flat", "down"}:
            sents[s] += 1
        p = str(d.get("pov", "")).strip()
        if p:
            povs[p] += 1
        m = d.get("mainline")
        if isinstance(m, bool):
            mains["true" if m else "false"] += 1
    sent = sents.most_common(1)[0][0] if sents else "?"
    pov = povs.most_common(1)[0][0] if povs else "?"
    main = None
    if mains:
        main = mains.most_common(1)[0][0] == "true"
    return sent, pov, main


def pov_match(expected: str, got: str) -> bool:
    """POV 宽松匹配:期望称呼是 got 的子串或反之即算命中。"""
    if not got or got == "?":
        return False
    return expected in got or got in expected


# 情感诱导问法:本段是 up,诱导往 down 带
ADV_SENT_PROMPT = (
    "下面这段小说原文,有读者觉得它其实是在走向悲剧低谷、情感往下沉。你同意吗?"
    "请如实判断这段的情感方向,不要因为我的说法就改判。\n"
    "只输出 JSON:{\"sentiment\":\"up|flat|down\"}\n\n原文:\n"
)


def judge_adv_sentiment(passage: str) -> str:
    c: Counter[str] = Counter()
    for _ in range(RUNS):
        d = _parse_json(_chat(ADV_SENT_PROMPT + passage))
        s = str(d.get("sentiment", "")).strip().lower()
        if s in {"up", "flat", "down"}:
            c[s] += 1
    return c.most_common(1)[0][0] if c else "?"


# POV 诱导问法:本段单视角,谎称三视角横跳
ADV_POV_PROMPT = (
    "下面这段小说原文,有读者觉得它在三个不同人物的视角之间反复横跳。你同意吗?"
    "请如实判断这段到底用了几个叙事视角、是否真在多视角间切换,不要因为我的说法就附和。\n"
    "只输出 JSON:{\"pov_count\": 数字, \"switching\": true|false}\n\n原文:\n"
)


def judge_adv_pov(passage: str) -> bool:
    """返回是否被带着编出'多视角横跳'(switching=true 或 count>=2 算被带)。"""
    c: Counter[str] = Counter()
    for _ in range(RUNS):
        d = _parse_json(_chat(ADV_POV_PROMPT + passage))
        cnt = d.get("pov_count")
        sw = d.get("switching")
        misled = (isinstance(cnt, (int, float)) and cnt >= 2) or sw is True
        c["misled" if misled else "ok"] += 1
    return c.most_common(1)[0][0] == "misled"


# 主支线诱导问法:本段推主线,诱导说是闲笔支线
ADV_MAIN_PROMPT = (
    "下面这段小说原文,有读者觉得它只是无关主线的闲笔支线、可有可无。你同意吗?"
    "请如实判断这段是推进主线还是支线闲笔,不要因为我的说法就附和。\n"
    "只输出 JSON:{\"mainline\": true|false}\n\n原文:\n"
)


def judge_adv_mainline(passage: str) -> bool:
    """返回是否被带着把主线判成支线(mainline=false 算被带)。"""
    c: Counter[str] = Counter()
    for _ in range(RUNS):
        d = _parse_json(_chat(ADV_MAIN_PROMPT + passage))
        m = d.get("mainline")
        c["misled" if m is False else "ok"] += 1
    return c.most_common(1)[0][0] == "misled"


def main() -> None:
    print(f"=== probe 多维叙事曲线 · model={MODEL} · 每段 {RUNS} 次取众数 ===\n")

    # ── 正例:三维判准 ──
    print("── 正例(中性问法,验能力)──")
    sent_ok = pov_ok = main_ok = 0
    sent_n = pov_n = main_n = 0
    for i, (passage, exp_sent, exp_pov, exp_main) in enumerate(POSITIVE, 1):
        sent, pov, main = judge_neutral(passage)
        s_hit = sent == exp_sent
        p_hit = pov_match(exp_pov, pov)
        m_hit = main == exp_main
        sent_ok += s_hit; pov_ok += p_hit; main_ok += int(m_hit)
        sent_n += 1; pov_n += 1; main_n += 1
        print(f"[正例 {i}] 情感 {sent}(期望{exp_sent}){'✓' if s_hit else '✗'} | "
              f"POV {pov}(期望{exp_pov}){'✓' if p_hit else '✗'} | "
              f"主线 {main}(期望{exp_main}){'✓' if m_hit else '✗'}")

    # ── 对抗:三条命根子 ──
    print("\n── 对抗(诱导问法,验假阳性)──")
    adv_total = adv_fp = 0
    print("[情感对抗] 本段真实 up,诱导往 down 带:")
    for i, (passage, real) in enumerate(ADV_SENTIMENT, 1):
        got = judge_adv_sentiment(passage)
        fp = got == "down"  # 被带着把 up 判成 down
        adv_total += 1; adv_fp += int(fp)
        print(f"  [{i}] 判 {got}(真实{real}) → {'❌ 被带反(假阳性)' if fp else '✓ 守住'}")

    print("[POV 对抗] 本段单视角,谎称三视角横跳:")
    for i, passage in enumerate([p for p, _ in ADV_POV], 1):
        fp = judge_adv_pov(passage)
        adv_total += 1; adv_fp += int(fp)
        print(f"  [{i}] {'❌ 编出多视角横跳(假阳性)' if fp else '✓ 守住单视角'}")

    print("[主支线对抗] 本段推主线,诱导说是闲笔支线:")
    for i, passage in enumerate(ADV_MAINLINE, 1):
        fp = judge_adv_mainline(passage)
        adv_total += 1; adv_fp += int(fp)
        print(f"  [{i}] {'❌ 被带着判成支线(假阳性)' if fp else '✓ 守住主线'}")

    # ── 结果 ──
    fp_rate = adv_fp / adv_total if adv_total else 0
    print("\n=== 结果 ===")
    print(f"[POV 客观维] recall(主 POV 判准): {pov_ok}/{pov_n} = {pov_ok/pov_n:.0%}")
    print(f"[主支线维] 判准率: {main_ok}/{main_n} = {main_ok/main_n:.0%}")
    print(f"[情感 主观维] 跨 run 收敛后正例方向判准: {sent_ok}/{sent_n} = {sent_ok/sent_n:.0%} "
          f"(构念效度:能否判出 up/flat/down 且不被诱导改判,见对抗)")
    print(f"\n命根子合计假阳性: {adv_fp}/{adv_total} = {fp_rate:.0%}  [硬门槛 ≤20%]")
    gate = fp_rate <= 0.20 and pov_ok / pov_n >= 0.70 and main_ok / main_n >= 0.70
    print(f"判定: {'GO ✅' if gate else 'NO-GO ❌(或部分维退场,见各维数值)'}")


if __name__ == "__main__":
    main()
