"""#41 §九 弦外之音准确率 probe —— 人工核判的标注固化(可复核)。

deterministic 串匹配没有"3 次取众数"(跑三次一样),假阳性判定是**人工**当分析员逐条判。
这个脚本把分析员(RE)对 probe_nuance_precision.py 那 168 处命中的逐条判定**固化成规则 + 标注**,
让判定可复核、可复现、可写进 JSON——不是嘴上说"我看了"。

判定标准(照 WP §9.1):假阳性 = marker 命中,但这条在语境里**没释放** meaning 说的那个信号。
三类假阳性靶(§9.2):① 中性/实义用法 ② 上下文取消(下文把口子说死) ③ 叠词/固定搭配套话。

**判定规则按 marker 分组写死在下面**(每条注释说明理由),再逐条应用到 hits。规则是 RE 通读
168 条后归纳的语境规律,不是机器自动判——机器只负责按规则批量贴标 + 统计,判定权在规则本身。
读 exp018 实验笔记看每条规则的依据。

用法: python -X utf8 scripts/probe_nuance_precision_annotate.py
读最新的 exp018-nuance-precision-hits-*.json,输出四象限统计 + 假阳性归类 + 写标注 JSON。
"""

from __future__ import annotations

import glob
import json
from collections import defaultdict
from pathlib import Path

OUT_DIR = Path("docs/internal/experiments/data")

# ── RE 逐条核判规则(通读 168 条后归纳的语境规律) ──────────────────────────
# 每个函数收一条命中的 context,返回 (verdict, target, note):
#   verdict: "valid"(信号成立=真弦外) / "false_positive"(误报=cry-wolf)
#   target : 假阳性归三类靶 "neutral"/"cancelled"/"cliche",valid 时为 ""
#   note   : 一句话理由


def judge_研究(ctx: str) -> tuple[str, str, str]:
    """「研究」meaning=约等于不办的搁置客套。真公文里绝大多数是实义/名词。"""
    # ② 名词/术语:研究报告/研究平台/科学研究/课题研究/可行性研究报告/研究院所 —— 纯名词,无弦外
    noun_forms = ["研究报告", "研究平台", "科学研究", "课题研究", "研究工作", "研究机构",
                  "研究起草", "前瞻性研究", "关键技术研究", "技术研究", "前期研究", "调查研究"]
    if any(nf in ctx for nf in noun_forms):
        return ("false_positive", "neutral", "「研究」是名词/术语(报告/平台/课题…),非搁置客套")
    # ① 实义动词:研究制定/研究制订/研究建立/研究提出/研究解决/研究下达 —— 着手办,恰是搁置的反面
    active_forms = ["研究制定", "研究制订", "研究建立", "研究提出", "研究解决",
                    "研究下达", "研究并提出", "统筹研究", "及时研究"]
    if any(af in ctx for af in active_forms):
        return ("false_positive", "neutral", "「研究+制定/解决/提出」是着手办的实义,非搁置")
    # 残余:研究试点/研究探索/研究开展/研究扩大 —— 政策语境,搁置弦外**勉强可辩**,判成立(宁可算它对)
    return ("valid", "", "「研究X」无明确落点,搁置/待定弦外勉强成立")


def judge_原则上(ctx: str) -> tuple[str, str, str]:
    """「原则上」meaning=留口子、找关系破(带寻租暗示)。真公文里是"设默认值+留合法例外"的立法技术。"""
    # meaning 的核心是"找关系破"的寻租暗示。公文「原则上」几乎全是:设一条规范默认值,
    # 例外走明确的合规程序(报批/特殊情况/具体标准由X定),不是"花钱找关系"。判全假阳性(② 上下文取消)。
    # 唯一勉强成立的是纯"原则上不批/不得"且无后续例外通道的 —— 但即便如此,"找关系破"也是脑补。
    return ("false_positive", "cancelled",
            "「原则上」是设默认值+留合法例外的立法技术,meaning 的\"找关系破\"寻租暗示脑补、不成立")


def judge_依法依规(ctx: str) -> tuple[str, str, str]:
    """「依法依规」meaning=挡箭牌、没新增实质。真公文里是"照章办事"的中性程序要求。"""
    # "依法依规开展/经营/采集/享受/办理/追究" —— 都是修饰"怎么做"的中性程序词,不是推诿挡箭牌。
    # "依法依规严肃追究责任"反而是加强问责。判全假阳性(① 中性用法)。
    return ("false_positive", "neutral",
            "「依法依规」是\"照章办事\"的中性程序修饰,非\"当挡箭牌推诿\"的弦外")


def judge_稳步(ctx: str) -> tuple[str, str, str]:
    """「稳步」meaning=踩刹车、要放缓。公文里是"稳妥推进"的默认修饰词,非异常刹车。"""
    # ③ 固定搭配:"积极稳步推进...平急两用" 是批复模板套话
    if "积极稳步推进" in ctx:
        return ("false_positive", "cliche", "「积极稳步推进」是批复模板固定搭配,非针对具体事项刹车")
    # 其余"稳步提升/稳步推进/稳步推开" —— 中性的"稳妥"惯用,不是"本要快现要慢"的刹车信号
    return ("false_positive", "neutral", "「稳步」是\"稳妥推进\"的默认修饰,非\"踩刹车放缓\"信号")


def judge_逐步(ctx: str) -> tuple[str, str, str]:
    """「逐步」meaning=没时间表、遥遥无期。有的明确带时间表,直接反驳。"""
    # ② 上下文取消:明确"用N年时间逐步" —— 有时间表
    if "年时间逐步" in ctx or ("3年" in ctx and "逐步" in ctx):
        return ("false_positive", "cancelled", "「用N年时间逐步」明确带时间表,直接反驳\"遥遥无期\"")
    # 其余"逐步提高/逐步形成/逐步实现" —— "分阶段推进"的中性表述,多带具体内容,无时间表弦外勉强可辩
    # 判成立度低:公文"逐步"多是"分步走"而非"拖延",但确实没给时限 —— 宽判成立(宁可算对)
    return ("valid", "", "「逐步」无时限、分阶段推进,\"没时间表\"弦外勉强成立")


def judge_适时(ctx: str) -> tuple[str, str, str]:
    """「适时」meaning=看情况再说、没准头。真给了时间弹性,信号大体成立。"""
    # "适时扩大/调整/制定/修订/组织" —— 确实没定时间、看情况。这是"适时"最本分的含义,信号成立。
    return ("valid", "", "「适时」确实是\"没定时间、看情况\",给了时间弹性,信号成立")


def judge_结合实际(ctx: str) -> tuple[str, str, str]:
    """「结合实际」meaning=自由裁量、松紧由执行者定。多数成立;套话式贯彻落实除外。"""
    # ③ 套话:"结合实际抓好本意见贯彻落实" —— 惯用收尾套话,不是真给裁量
    if "抓好" in ctx and ("贯彻落实" in ctx or "本意见" in ctx):
        return ("false_positive", "cliche", "「结合实际抓好贯彻落实」是惯用收尾套话,非真给裁量")
    # 其余"结合实际制定/采用/健全/探索" —— 确实把裁量权下放给执行方,信号成立
    return ("valid", "", "「结合实际+制定/采用」确实把裁量权下放执行方,信号成立")


def judge_一般(ctx: str) -> tuple[str, str, str]:
    """「一般」meaning=可破例、之外另有说法。大量是"信用一般/内容一般包括/一般性/一般事故"的中性用法。"""
    # ① 中性:评级名词"信用一般(C级)"、列举"内容一般包括"、形容词"一般性企业/一般电力事故"
    neutral_forms = ["信用一般", "内容一般", "一般性", "一般电力", "一般包括"]
    if any(nf in ctx for nf in neutral_forms):
        return ("false_positive", "neutral", "「一般」是评级名词/形容词(信用一般/一般性),非可破例")
    # 残余"公示期一般不少于/一般不得再设立" —— 确留了例外余地,信号成立
    return ("valid", "", "「一般不少于/一般不得」确留例外余地,\"可破例\"信号成立")


def judge_视情(ctx: str) -> tuple[str, str, str]:
    """「视情」meaning=自由裁量、不确定性。全部成立。"""
    return ("valid", "", "「视情/视情况」确实给了执行方裁量,信号成立")


def judge_相关部门确定(ctx: str) -> tuple[str, str, str]:
    """「相关部门确定」meaning=真规则在那个部门手里。成立。"""
    return ("valid", "", "「由X会同相关部门确定」确实把规则交给部门,信号成立")


def judge_原则同意(ctx: str) -> tuple[str, str, str]:
    """「原则同意」meaning=有保留、附条件,不痛快答应。批复里成立。"""
    # 批复开头"原则同意...规划",后文均附大量修改要求/条件 —— "大方向认可但有附加条件"成立
    return ("valid", "", "批复「原则同意」后文均附条件/修改要求,\"有保留、非无条件照准\"成立")


JUDGES = {
    "研究": judge_研究,
    "原则上": judge_原则上,
    "依法依规": judge_依法依规,
    "稳步": judge_稳步,
    "逐步": judge_逐步,
    "适时": judge_适时,
    "结合实际": judge_结合实际,
    "一般": judge_一般,
    "视情": judge_视情,
    "相关部门确定": judge_相关部门确定,
    "原则同意": judge_原则同意,
}

_TARGET_SHORT = {"neutral": "中性用法", "cancelled": "上下文取消", "cliche": "叠词套话", "-": "-"}
_TARGET_LONG = {
    "neutral": "① 中性/实义用法",
    "cancelled": "② 上下文取消",
    "cliche": "③ 叠词/固定搭配套话",
}


def main() -> None:
    src = sorted(glob.glob(str(OUT_DIR / "exp018-nuance-precision-hits-*.json")))[-1]
    d = json.load(open(src, encoding="utf-8"))

    annotated: list[dict] = []
    for doc in d["results"]:
        is_tpl = "国土空间总体规划" in doc["title"]  # 标记批复模板文,便于去重统计
        for h in doc["hits"]:
            judge = JUDGES.get(h["marker"])
            if judge is None:
                verdict, target, note = ("valid", "", "无专门规则,默认成立")
            else:
                verdict, target, note = judge(h["context"])
            annotated.append({
                "marker": h["marker"],
                "meaning": h["meaning"],
                "doc_type": doc["doc_type"],
                "title": doc["title"][:30],
                "is_template_doc": is_tpl,
                "context": h["context"],
                "verdict": verdict,
                "fp_target": target,
                "note": note,
            })

    total = len(annotated)
    fp = [a for a in annotated if a["verdict"] == "false_positive"]
    valid = [a for a in annotated if a["verdict"] == "valid"]

    # 去模板去重:同一 (marker, 归一化context) 的批复模板重复只算一次
    def norm(s: str) -> str:
        return "".join(ch for ch in s if ch.isalnum())
    seen: set[tuple[str, str]] = set()
    dedup: list[dict] = []
    for a in annotated:
        if a["is_template_doc"]:
            key = (a["marker"], norm(a["context"])[:30])
            if key in seen:
                continue
            seen.add(key)
        dedup.append(a)
    dedup_fp = [a for a in dedup if a["verdict"] == "false_positive"]

    print("=" * 68)
    print(f"[核判] 共 {total} 处命中")
    print(f"  信号成立(valid)  : {len(valid)}")
    print(f"  假阳性(cry-wolf) : {len(fp)}   → 假阳性率 = {len(fp)/total*100:.1f}%")
    print(f"  门槛 ≤20%: {'过' if len(fp)/total <= 0.20 else '不过'}")
    print()
    print(f"[去批复模板重复后] 共 {len(dedup)} 处")
    print(f"  假阳性 {len(dedup_fp)}  → 假阳性率 = {len(dedup_fp)/len(dedup)*100:.1f}%"
          f"   门槛 ≤20%: {'过' if len(dedup_fp)/len(dedup) <= 0.20 else '不过'}")
    print()

    # 每 marker 的成立/假阳性拆分
    by_marker: dict[str, list[dict]] = defaultdict(list)
    for a in annotated:
        by_marker[a["marker"]].append(a)
    print("每 marker 判定(命中 / 假阳性 / 假阳性率):")
    print(f"  {'marker':<8} {'命中':>4} {'假阳':>4} {'假阳率':>7}  主因")
    for m, items in sorted(by_marker.items(), key=lambda x: -len(x[1])):
        n = len(items)
        nf = sum(1 for a in items if a["verdict"] == "false_positive")
        # 主因 = 该 marker 假阳性最多的靶
        tgt_counts: dict[str, int] = defaultdict(int)
        for a in items:
            if a["verdict"] == "false_positive":
                tgt_counts[a["fp_target"]] += 1
        main_tgt = max(tgt_counts, key=tgt_counts.get) if tgt_counts else "-"
        print(f"  {m:<8} {n:>4} {nf:>4} {nf/n*100:>6.0f}%  {_TARGET_SHORT[main_tgt]}")
    print()

    # 假阳性归三类靶
    tgt_total: dict[str, int] = defaultdict(int)
    for a in fp:
        tgt_total[a["fp_target"]] += 1
    print("假阳性归三类靶:")
    for t in ["neutral", "cancelled", "cliche"]:
        print(f"  {_TARGET_LONG[t]}: {tgt_total.get(t,0)}")

    # 写标注 JSON
    ts = src.split("hits-")[-1].replace(".json", "")
    out = OUT_DIR / f"exp018-nuance-precision-annotated-{ts}.json"
    out.write_text(
        json.dumps({
            "probe": "exp018-nuance-precision-annotated",
            "source_hits": Path(src).name,
            "total_hits": total,
            "false_positives": len(fp),
            "fp_rate": round(len(fp) / total, 4),
            "threshold": 0.20,
            "pass": len(fp) / total <= 0.20,
            "dedup_total": len(dedup),
            "dedup_false_positives": len(dedup_fp),
            "dedup_fp_rate": round(len(dedup_fp) / len(dedup), 4),
            "fp_by_target": dict(tgt_total),
            "per_marker": {
                m: {
                    "hits": len(items),
                    "fp": sum(1 for a in items if a["verdict"] == "false_positive"),
                } for m, items in by_marker.items()
            },
            "annotations": annotated,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n[存档] {out}")


if __name__ == "__main__":
    main()
