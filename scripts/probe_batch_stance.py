"""立场"批量定位"前置 probe(exp032):一次调用把多个人物同时定位到立场轴上,准不准。
接 exp024(单人 Toulmin GO)。redesign 要把人物志改成"全员一口气打上立场格局图"——那得靠**一次
批量调用**给每人一个 net,而不是一个个点(那是当前懒加载的毛病)。但批量一次判一二十人可能变浅
(跟 exp028 合并分维一个道理),所以先验:批量 net 跟已知立场 / exp024 单人 net 对不对得上。

方法(三国公版,整本进长上下文):一次调用给这几个人各一个 net(-5..5)+ dispute(0-5)+ 一句依据。
拿三个尺子判:
1. 方向对:诸葛亮 / 关羽 net>0(尊汉)、董卓 net<0(篡逆)。
2. 争议校准:曹操 dispute 高(≥3)且明显高于诸葛亮 / 董卓。
3. 批量 vs 单人:若有 exp024 单人数据(data/exp024-*.json),比每人 batch net 跟单人 net 差多少
   (|Δ|≤2 算稳、方向不反)。

go/no-go:方向对 + 曹操争议高 + 跟单人不明显背离 → GO 把立场格局图接成人物志主视图(批量粗定位 +
点人看详细 Toulmin)。批量方向错 / 全压 0 / 跟单人大背离 → 别一次批太多,分小批或退回按需。
flash,key .env,L2 关。不 commit、不动生产。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
import bookscope  # noqa: E402,F401 — 触发 .env

_MODEL = os.environ.get("BOOKSCOPE_SMOKE_MODEL", "deepseek-v4-flash")
_DS_BASE = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
_BOOK_PAT = "test三国演义*.epub"
_MAX_TOKENS = 4000  # 批量输出比单人大;给够留 flash reasoning 头

_FIGURES = ["曹操", "诸葛亮", "董卓", "孙权", "关羽", "司马懿", "刘备", "吕布"]
_EXPECT = {  # 人工预期(不喂模型,只作对照):net 方向 + 争议
    "曹操": "net~0 / dispute 高(尊汉vs篡逆千年争议)",
    "诸葛亮": "net>0 尊汉 / dispute 低",
    "董卓": "net<0 篡逆 / dispute 低",
    "孙权": "net~0 中(割据自立)",
    "关羽": "net>0 尊汉 / dispute 低",
    "司马懿": "net<0 或 ~0(专权奠基) / dispute 中高",
    "刘备": "net>0 尊汉(汉室宗亲) / dispute 低",
    "吕布": "net<0 或 ~0(反复无主) / dispute 中",
}

_PREAMBLE = (
    "你是严谨的史书人物立场判定助手。下面给你《三国演义》全书原文。\n"
    "任务:判定**下面列出的每一个人物**在「尊汉扶主 ↔ 篡逆自立」这条轴上的立场,一次性全给。\n"
    "铁律:\n"
    "1. 只据原文判,不臆测。身份本身不代表立场(汉臣身份 ≠ 一定尊汉,权臣 ≠ 一定篡逆),"
    "看原文里的行为。\n"
    "2. net = 综合倾向整数(-5 篡逆自立 .. 0 中立 .. +5 尊汉扶主)。\n"
    "3. dispute = 争议度整数(0-5):正反两方原文都有硬证据、真两难才高;一边倒就低。\n"
    "4. brief = 一句话依据(据原文,别编)。\n\n"
    "=== 《三国演义》全书原文 ===\n"
)


def _parse(raw: str):
    from bookscope.agent.utils.json_parsing import strip_code_fence
    txt = strip_code_fence(raw or "")
    # 批量输出是数组;extract_first_json_object 抠对象不抠数组,先直接试 loads,再兜底找 [
    try:
        obj = json.loads(txt)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict) and isinstance(obj.get("people"), list):
            return obj["people"]
    except Exception:  # noqa: BLE001
        pass
    # 兜底:切出首个 [...] 数组
    i, j = txt.find("["), txt.rfind("]")
    if 0 <= i < j:
        try:
            return json.loads(txt[i : j + 1])
        except Exception:  # noqa: BLE001
            return None
    return None


def _load_perperson_ref():
    """读 exp024 单人 net 当对照(有就比 batch vs 单人;没有就跳这项)。"""
    p = _ROOT / "docs" / "internal" / "experiments" / "data" / "exp024-toulmin-stance-sanguo.json"
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    ref = {}
    for r in data.get("records", []):
        if isinstance(r, dict) and r.get("name") and isinstance(r.get("net"), int):
            ref[r["name"]] = r["net"]
    return ref


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("[probe] DEEPSEEK_API_KEY 未设", file=sys.stderr)
        return 1
    found = sorted((_ROOT / "tests" / "file").glob(_BOOK_PAT))
    if not found:
        print("[probe] 三国 epub 没找到", file=sys.stderr)
        return 1
    os.environ["BOOKSCOPE_LLM_CACHE_DISABLED"] = "1"

    from openai import OpenAI

    from bookscope.ingest.book_chunker import chunk_book
    from bookscope.ingest.loader import load_text

    book = load_text(str(found[0]))
    full_text = book.raw_text
    n_chunks = len(chunk_book(book))
    ref = _load_perperson_ref()
    print(f"[probe] 三国 {len(full_text)} 字符 {n_chunks} chunk;批量 {len(_FIGURES)} 人一次定位;"
          f"单人对照 {'有 exp024' if ref else '无(跳过 batch-vs-单人)'};L2 关\n")

    client = OpenAI(api_key=os.environ["DEEPSEEK_API_KEY"], base_url=_DS_BASE)
    names_line = "、".join(_FIGURES)
    user = (
        f"给这些人物一次性全部定位:{names_line}。\n"
        "严格输出 JSON 数组(不要别的话、不要围栏),每人一项:\n"
        '[{"name":"","net":整数-5到5,"dispute":整数0到5,"brief":"一句依据"}]'
    )
    t0 = time.monotonic()
    resp = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "system", "content": _PREAMBLE + full_text},
                  {"role": "user", "content": user}],
        temperature=1.0,
        max_tokens=_MAX_TOKENS,
    )
    arr = _parse(resp.choices[0].message.content or "")
    dt = time.monotonic() - t0
    if not isinstance(arr, list):
        head = (resp.choices[0].message.content or "")[:200]
        print(f"[probe] 批量解析不出数组(用时{dt:.0f}s),原文头:\n{head}", file=sys.stderr)
        return 1

    by_name = {str(d.get("name", "")).strip(): d for d in arr if isinstance(d, dict)}
    print(f"[probe] 批量一次调用 {dt:.0f}s,拿到 {len(by_name)}/{len(_FIGURES)} 人\n")
    print("=" * 74)
    print(f"{'人物':<6} {'batch_net':>9} {'dispute':>7} {'单人net':>7} {'Δ':>4}  预期 / 依据")
    print("-" * 74)
    records = []
    for name in _FIGURES:
        d = by_name.get(name) or {}
        net = d.get("net")
        disp = d.get("dispute")
        pp = ref.get(name)
        delta = (abs(net - pp) if isinstance(net, int) and isinstance(pp, int) else None)
        records.append({"name": name, "net": net, "dispute": disp, "perperson_net": pp,
                        "delta": delta, "brief": d.get("brief", "")})
        pp_s = str(pp) if pp is not None else "—"
        d_s = str(delta) if delta is not None else "—"
        print(f"{name:<6} {str(net):>9} {str(disp):>7} {pp_s:>7} {d_s:>4}  {_EXPECT[name]}")
        if d.get("brief"):
            print(f"        └ {d['brief']}")
    print("=" * 74)
    print("尺子:①方向 诸葛亮/关羽/刘备 net>0、董卓 net<0 ②曹操 dispute≥3 且 > 诸葛亮/董卓 "
          "③|Δ(batch vs 单人)|≤2、方向不反")

    out = _ROOT / "docs" / "internal" / "experiments" / "data" / "exp032-batch-stance-sanguo.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "probe": "exp032-batch-stance", "book": "三国演义(公版)", "model": _MODEL,
        "figures": _FIGURES, "expect_ref": _EXPECT, "n_chunks": n_chunks,
        "batch_seconds": round(dt, 1), "records": records,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[probe] 写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
