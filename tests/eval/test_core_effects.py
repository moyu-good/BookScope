"""核心功能效果测试（eval）——不是只测“能跑”，而是测“效果对不对”。

用小型真实样本验证：
- 结构报告是否覆盖全部章节
- 本地检索是否命中真正相关的章节
- 导入后是否能被 list 看到
这些测试同时用于发现新需求（比如检索漏召回、报告缺章等）。
"""

from __future__ import annotations

from pathlib import Path

from bookscope.local_tools import (
    import_file,
    list_sessions,
    load_chunks,
    local_search,
    structure_report_html,
)


def _sample_book(tmp_path: Path, name: str = "sample.txt") -> Path:
    f = tmp_path / name
    f.write_text(
        "第一章 经济改革\n这里讨论财政激励与地方政府行为。\n"
        "第二章 市场与政府\n这里分析市场机制与政府干预的关系。\n"
        "第三章 土地财政\n这里讲土地财政与地方债务。\n",
        encoding="utf-8",
    )
    return f


def test_structure_report_covers_all_chapters(tmp_path: Path) -> None:
    f = _sample_book(tmp_path)
    html = structure_report_html(f, title="效果测试书")
    assert "第一章" in html
    assert "第二章" in html
    assert "第三章" in html
    assert "经济改革" in html or "市场" in html or "土地" in html


def test_local_search_hits_relevant_chapter(tmp_path: Path) -> None:
    f = _sample_book(tmp_path)
    _name, _book, _results, chunks = load_chunks(f)
    hits = local_search("土地财政", chunks, top_k=3)
    assert hits, "本地检索应至少命中一章"
    # 相关章节应在结果里
    texts = " ".join(h["text"] for h in hits)
    assert "土地" in texts


def test_import_then_list_sees_book(tmp_path: Path, monkeypatch) -> None:
    f = _sample_book(tmp_path, "effect.txt")
    data_dir = tmp_path / "sessions"
    session_id = import_file(f, data_dir, title="效果测试书")
    assert session_id.startswith("api-")
    books = list_sessions(data_dir)
    assert any(b["session_id"] == session_id for b in books)
    assert any("效果测试书" in b["book_title"] for b in books)


def test_local_search_ranks_higher_frequency_first() -> None:
    from bookscope.local_tools import local_search

    chunks = [
        {"chapter": 1, "text": "土地财政、土地财政、土地财政与地方债务。"},
        {"chapter": 2, "text": "这里提到土地财政。"},
    ]
    hits = local_search("土地财政", chunks, top_k=2)
    assert hits[0]["chapter"] == 1


def test_cluster_merge_dedupes_edges() -> None:
    from bookscope.local_tools import _dedupe_edges

    edges = [
        {"from": "a", "to": "b", "relation": "继承", "rationale": "1"},
        {"from": "a", "to": "b", "relation": "继承", "rationale": "2"},
        {"from": "b", "to": "a", "relation": "反驳", "rationale": "3"},
    ]
    out = _dedupe_edges(edges)
    assert len(out) == 2


def test_cluster_merge_groups_concepts() -> None:
    from bookscope.local_tools import _merge_concepts

    items = [
        {"concept": "法治", "stages": [{"paper": "a", "stage": "提出"}]},
        {"concept": "法治", "stages": [{"paper": "b", "stage": "发展"}, {"paper": "a", "stage": "提出"}]},
    ]
    out = _merge_concepts(items)
    assert out[0]["concept"] == "法治"
    assert len(out[0]["stages"]) == 2


def test_spine_progress_effect_reports_built_total(tmp_path: Path) -> None:
    from bookscope.local_tools import spine_progress

    f = tmp_path / "a.txt"
    f.write_text("第一章 开端\n甲。\n第二章 发展\n乙。\n", encoding="utf-8")
    progress = spine_progress(f)
    assert progress["book"] == "a"
    assert progress["total"] >= 1
    assert progress["built"] >= 0
    assert set(progress) >= {"built_chapters", "missing_chapters", "ready", "mode"}


def test_verify_quote_effect_honest_exact_and_missing(tmp_path: Path) -> None:
    from bookscope.local_tools import verify_quote

    f = tmp_path / "a.txt"
    f.write_text("第一章 开端\n这里提到市场与政府的关系。\n", encoding="utf-8")
    hit = verify_quote(f, "市场与政府的关系")
    assert hit["verified"] is True
    assert hit["method"] == "exact"
    miss = verify_quote(f, "完全不存在的句子")
    assert miss["verified"] is False
    assert miss["match_type"] == "none"
    assert "未找到" in miss["hint"]
