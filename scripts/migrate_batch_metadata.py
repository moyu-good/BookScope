"""B-4 · batch JSON schema 迁移：给 ``docs/internal/experiments/data/*.json`` 顶层
``book`` 节加 ``book_scope`` 字段。

背景：mingchao 当前只跑卷一切片但 metadata 无字段说明，跨卷题跑不了；
anshi 跑整本。给每份 batch JSON 顶层 ``book.book_scope`` 加值后，未来
跨书 / 跨切片对照实验能直接从 metadata 判断同范围内才比。

book_scope 取值集合：

- ``vol-1`` —— mingchao 卷一切片（v2 / v3.x / sprint5-mingchao / exp003-minimax-v2-ablation）
- ``full`` —— anshi 整本（exp002-anshi-* / sprint5-anshi-* / sprint5-sanity*）
- ``chapters-N-to-M`` —— 章节区间（当前没文件命中，留作未来用）
- ``unknown`` —— 不能从文件名前缀判断的兜底
- ``n/a`` —— probe 类（非 batch，跨书）

幂等：脚本可重复跑——已有 book_scope 字段则跳过，不覆盖。

用法（项目根目录）::

    python scripts/migrate_batch_metadata.py
    python scripts/migrate_batch_metadata.py --dry-run  # 只打印不写文件

测试见 ``tests/scripts/test_migrate_batch_metadata.py``。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Literal

BookScopeValue = Literal["vol-1", "full", "unknown", "n/a"]


def classify_batch_file(filename: str) -> BookScopeValue:
    """按 batch JSON 文件名前缀判断 book_scope 取值。

    判别规则来自 ``docs/internal/case-study/test-book-templates.md`` 第五节文件清单：

    - mingchao 切片（卷一）：``v2-*`` / ``v3-*`` / ``v3.1-*`` / ``v3.2-*`` /
      ``v3.3-mingchao-*`` / ``v3.4-mingchao-*`` / ``sprint5-mingchao-*`` /
      ``exp003-minimax-v2-ablation``
    - anshi 整本：``exp002-anshi-*`` / ``sprint5-anshi-*`` / ``sprint5-sanity*``
    - probe（不是 batch）：``exp003-training-contamination-probe``
    - 兜底：``unknown``
    """
    name = filename.lower()

    # probe 类——非 batch，跨书记忆探测
    if "training-contamination" in name or "probe" in name:
        return "n/a"

    # anshi 全本
    if "anshi" in name or "sanity" in name:
        return "full"

    # mingchao 卷一切片
    if (
        name.startswith("v2-")
        or name.startswith("v3-")
        or name.startswith("v3.1-")
        or name.startswith("v3.2-")
        or "mingchao" in name
        or "exp003-minimax-v2-ablation" in name
    ):
        return "vol-1"

    return "unknown"


def migrate_one(path: Path, dry_run: bool = False) -> tuple[bool, str]:
    """处理单份 JSON。

    Returns:
        (changed, message) —— changed=True 表示写了文件；message 是状态摘要。
    """
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"SKIP（无法读取或解析）: {type(exc).__name__}: {exc}"

    # 不是 dict 顶层（罕见）—— 跳过
    if not isinstance(data, dict):
        return False, "SKIP（顶层非 dict）"

    book = data.get("book")
    if not isinstance(book, dict):
        # 题集 / probe 等可能没有 book 节；放过
        return False, "SKIP（无 book 节）"

    if "book_scope" in book:
        return False, f"SKIP（已有 book_scope={book['book_scope']!r}）"

    scope = classify_batch_file(path.name)
    book["book_scope"] = scope

    if dry_run:
        return True, f"DRY → 加 book_scope={scope!r}"

    # 写回——保持原 indent=2 / ensure_ascii=False / 末尾换行
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + ("\n" if raw.endswith("\n") else ""),
        encoding="utf-8",
    )
    return True, f"加 book_scope={scope!r}"


def migrate_all(data_dir: Path, dry_run: bool = False) -> dict[str, int]:
    """遍历目录，返回统计 dict。"""
    stats = {
        "total": 0,
        "changed": 0,
        "skipped": 0,
        "by_scope": {"vol-1": 0, "full": 0, "n/a": 0, "unknown": 0},
    }
    files = sorted(data_dir.glob("*.json"))
    for p in files:
        stats["total"] += 1
        changed, msg = migrate_one(p, dry_run=dry_run)
        if changed:
            stats["changed"] += 1
            scope = classify_batch_file(p.name)
            stats["by_scope"][scope] = stats["by_scope"].get(scope, 0) + 1
        else:
            stats["skipped"] += 1
        print(f"  [{p.name}] {msg}")
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="batch JSON book_scope 字段迁移")
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "docs" / "experiments" / "data",
        help="batch JSON 目录（默认 docs/internal/experiments/data/）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印不写文件",
    )
    args = parser.parse_args()

    if not args.data_dir.is_dir():
        print(f"[migrate] 目录不存在: {args.data_dir}", file=sys.stderr)
        return 1

    print(f"[migrate] 处理目录: {args.data_dir}")
    print(f"[migrate] 模式: {'DRY-RUN' if args.dry_run else 'WRITE'}")
    print("=" * 64)
    stats = migrate_all(args.data_dir, dry_run=args.dry_run)
    print("=" * 64)
    print(
        f"[migrate] 总 {stats['total']} 份 / 改 {stats['changed']} / 跳 {stats['skipped']}"
    )
    print(f"[migrate] 分布: {stats['by_scope']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
