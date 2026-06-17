"""一次性 backfill：修正 exp004 12 份 batch JSON 的 book.path / word_count，
以及 config.kg_source（从 kg 对象动态推导，与修后的 run_batch_r1.py 保持一致）。

问题（docs/internal/experiments/004-cross-genre-stability.md 第 9.9 节 limitation #4）：
- book.path 全部写死 "test明朝那些事儿.epub"；anshi/zhinei/kuicheng 各书路径错误
- book.word_count 用 split() 计算中文字数严重偏低（anshi 3134 → 正确 378171）
- config.kg_source 硬编码，不随书变化

修法：
- path：按 title 映射到实际 epub 文件名
- word_count：加载 epub 重算，用非空白字符计数（与 schemas.py 修后一致）
- kg_source：exp004 全部用了 4 字手工 KG，保持原值（动态推导同样得到相同字符串）
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:  # noqa: BLE001
    pass

# ---------------------------------------------------------------------------
# epub 文件名映射（book title 前缀 → 实际 epub 文件名）
# ---------------------------------------------------------------------------

_EPUB_MAP: dict[str, str] = {
    "明朝那些事儿": "test明朝那些事儿.epub",
    "安史之乱": "test安史之乱  历史、宣传与神话 (张诗坪, 胡可奇).epub",
    "制内市场": "test制内市场：中国国家主导型政治经济学（中国问题专家、高层智库郑永年权威解读，中国经济2020年如何实现超预期增长，突破百万亿元大关） (郑永... (z-library.sk, 1lib.sk, z-lib.sk).epub",  # noqa: E501
    "亏成首富": "test亏成首富从游戏开始 (青衫取醉) (z-library.sk, 1lib.sk, z-lib.sk).epub",
}


def _epub_for_title(title: str) -> str | None:
    for prefix, filename in _EPUB_MAP.items():
        if title.startswith(prefix):
            return filename
    return None


def _char_word_count(text: str) -> int:
    """非空白字符总数（中文字数标准计量）。"""
    return len("".join(text.split()))


def _true_word_count(epub_path: Path) -> int:
    """加载 epub，返回字符数。"""
    from bookscope.ingest.loader import load_text
    book = load_text(epub_path)
    return _char_word_count(book.raw_text)


def main() -> int:
    data_dir = _PROJECT_ROOT / "docs" / "experiments" / "data"
    target_files = sorted(data_dir.glob("exp004-*-run*.json"))
    if not target_files:
        print("[backfill] 未找到 exp004-*-run*.json 文件", file=sys.stderr)
        return 1

    print(f"[backfill] 共 {len(target_files)} 份文件待处理")
    changed = 0

    # 缓存每本书的 word_count（避免重复加载 epub）
    wc_cache: dict[str, int] = {}

    for f in target_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        book = data.get("book", {})
        title: str = book.get("title", "")

        epub_name = _epub_for_title(title)
        if epub_name is None:
            print(f"[backfill] 跳过 {f.name}：title={title!r} 无匹配 epub")
            continue

        epub_path = _PROJECT_ROOT / epub_name
        if not epub_path.exists():
            print(f"[backfill] 跳过 {f.name}：epub 不存在 {epub_path}")
            continue

        # word_count
        if title not in wc_cache:
            print(f"[backfill] 加载 epub 计算字数：{epub_name[:40]}...")
            wc_cache[title] = _true_word_count(epub_path)
        true_wc = wc_cache[title]

        old_path = book.get("path", "")
        old_wc = book.get("word_count")

        if old_path == epub_name and old_wc == true_wc:
            print(f"[backfill] {f.name} 已是正确值，跳过")
            continue

        # 更新
        data["book"]["path"] = epub_name
        data["book"]["word_count"] = true_wc

        f.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            f"[backfill] {f.name}: "
            f"path {old_path!r} → {epub_name!r}, "
            f"word_count {old_wc} → {true_wc}"
        )
        changed += 1

    print(f"[backfill] 完成，共修改 {changed} 份文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
