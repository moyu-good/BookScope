"""B-4 · migrate_batch_metadata 脚本测试。

覆盖：
- classify_batch_file 按文件名前缀正确判别 book_scope
- migrate_one 幂等（重跑不覆盖已有字段）
- migrate_one 在 tmp 目录构造的样本上正确 inject
- 不动 batch JSON 其他字段（事实记录原则）
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.migrate_batch_metadata import (
    classify_batch_file,
    migrate_all,
    migrate_one,
)


class TestClassify:
    """文件名前缀 → book_scope 判别。"""

    @pytest.mark.parametrize(
        "filename,expected",
        [
            # mingchao 卷一切片
            ("v2-batch-01.json", "vol-1"),
            ("v3-minimax-batch-pilot-no-enforcement.json", "vol-1"),
            ("v3-minimax-pilot-2.json", "vol-1"),
            ("v3.1-minimax-batch-01.json", "vol-1"),
            ("v3.1-minimax-pilot.json", "vol-1"),
            ("v3.2-minimax-batch-01.json", "vol-1"),
            ("v3.2-mingchao-minimax-batch-02.json", "vol-1"),
            ("v3.3-mingchao-minimax-batch-01.json", "vol-1"),
            ("v3.4-mingchao-minimax-batch-01.json", "vol-1"),
            ("sprint5-mingchao-r1-batch-01.json", "vol-1"),
            ("sprint5-mingchao-r2-batch-03.json", "vol-1"),
            ("exp003-minimax-v2-ablation.json", "vol-1"),
            # anshi 整本
            ("exp002-anshi-questions.json", "full"),
            ("exp002-anshi-minimax-v3.2.json", "full"),
            ("exp002-anshi-minimax-v3.2-rerun-01.json", "full"),
            ("exp002-anshi-minimax-v3.4-batch-01.json", "full"),
            ("sprint5-anshi-r1-batch-02.json", "full"),
            ("sprint5-sanity-anshi-r1-q1.json", "full"),
            ("sprint5-sanity2-q1.json", "full"),
            # probe
            ("exp003-training-contamination-probe.json", "n/a"),
            # 兜底
            ("totally-unknown-file.json", "unknown"),
        ],
    )
    def test_classify(self, filename: str, expected: str) -> None:
        assert classify_batch_file(filename) == expected


class TestMigrateOne:
    """单文件迁移：inject + 幂等 + 不动其他字段。"""

    def _write_json(self, path: Path, data: dict) -> None:
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_inject_vol1_for_mingchao(self, tmp_path: Path) -> None:
        f = tmp_path / "v2-batch-01.json"
        self._write_json(
            f,
            {
                "batch_id": "v2-batch-01",
                "book": {"title": "明朝那些事儿", "word_count": 32164, "chunk_count": 1069},
                "questions": [],
            },
        )
        changed, _ = migrate_one(f, dry_run=False)
        assert changed
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["book"]["book_scope"] == "vol-1"
        # 不动原字段
        assert data["book"]["title"] == "明朝那些事儿"
        assert data["book"]["word_count"] == 32164
        assert data["batch_id"] == "v2-batch-01"
        assert data["questions"] == []

    def test_inject_full_for_anshi(self, tmp_path: Path) -> None:
        f = tmp_path / "sprint5-anshi-r1-batch-01.json"
        self._write_json(
            f,
            {
                "batch_id": "sprint5-anshi-r1-batch-01",
                "book": {"title": "安史之乱：历史、宣传与神话"},
                "questions": [{"id": "q1"}],
            },
        )
        changed, _ = migrate_one(f, dry_run=False)
        assert changed
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["book"]["book_scope"] == "full"
        # 题集内容不动
        assert data["questions"] == [{"id": "q1"}]

    def test_idempotent_does_not_overwrite(self, tmp_path: Path) -> None:
        """已经有 book_scope 字段时不动它（即使值是兜底 unknown）。"""
        f = tmp_path / "v2-batch-01.json"
        self._write_json(
            f,
            {
                "batch_id": "v2-batch-01",
                "book": {"title": "明朝那些事儿", "book_scope": "custom-value"},
            },
        )
        changed, msg = migrate_one(f, dry_run=False)
        assert not changed
        assert "已有" in msg
        data = json.loads(f.read_text(encoding="utf-8"))
        assert data["book"]["book_scope"] == "custom-value"

    def test_skip_no_book_section(self, tmp_path: Path) -> None:
        """没有 book 节的 JSON（如部分 probe）跳过不报错。"""
        f = tmp_path / "exp003-training-contamination-probe.json"
        self._write_json(
            f,
            {
                "probe_id": "exp003-training-contamination-probe",
                "model": "MiniMax-M2.7",
                "probes": [],
            },
        )
        changed, msg = migrate_one(f, dry_run=False)
        assert not changed
        assert "无 book 节" in msg

    def test_dry_run_does_not_write(self, tmp_path: Path) -> None:
        f = tmp_path / "v2-batch-01.json"
        original = {"batch_id": "v2-batch-01", "book": {"title": "明朝那些事儿"}}
        self._write_json(f, original)
        before = f.read_text(encoding="utf-8")
        changed, _ = migrate_one(f, dry_run=True)
        assert changed  # 报告会改
        after = f.read_text(encoding="utf-8")
        assert before == after  # 文件没动


class TestMigrateAll:
    """目录批处理 + 统计。"""

    def test_full_run_on_tmp_dir(self, tmp_path: Path) -> None:
        # 构造迷你 fixture：三种 scope 各一份
        (tmp_path / "v2-batch-01.json").write_text(
            json.dumps({"book": {"title": "明朝"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (tmp_path / "sprint5-anshi-r1-batch-01.json").write_text(
            json.dumps({"book": {"title": "安史"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        (tmp_path / "exp003-training-contamination-probe.json").write_text(
            json.dumps({"probes": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        stats = migrate_all(tmp_path, dry_run=False)
        assert stats["total"] == 3
        assert stats["changed"] == 2  # probe 跳过
        assert stats["by_scope"]["vol-1"] == 1
        assert stats["by_scope"]["full"] == 1

    def test_real_data_dir_dry_run(self) -> None:
        """在真 data 目录跑 dry-run——不写文件，验证脚本能跑通。"""
        project_root = Path(__file__).resolve().parent.parent.parent
        data_dir = project_root / "docs" / "experiments" / "data"
        if not data_dir.is_dir():
            pytest.skip(f"data 目录不存在: {data_dir}")
        stats = migrate_all(data_dir, dry_run=True)
        # 至少要有 30+ 份文件
        assert stats["total"] >= 30
