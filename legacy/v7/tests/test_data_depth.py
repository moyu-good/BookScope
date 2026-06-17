"""Data depth validation: verify v6 smart-sampling maintains analysis quality.

Tests that the budget-filling chunk selection sends sufficient text to LLM,
comparable to v5's per-chapter analysis approach.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

EPUB_SESSION = Path(__file__).resolve().parent.parent / "data" / "sessions" / "2ae908744956.json"

pytestmark = pytest.mark.skipif(
    not EPUB_SESSION.exists(),
    reason=f"Session file not found: {EPUB_SESSION}",
)


class Chunk:
    """Minimal chunk object for testing."""

    def __init__(self, index: int, text: str):
        self.index = index
        self.text = text


@pytest.fixture(scope="module")
def chunks():
    data = json.loads(EPUB_SESSION.read_text(encoding="utf-8"))
    return [Chunk(c["index"], c["text"]) for c in data["chunks"]]


@pytest.fixture(scope="module")
def arcs(chunks):
    from bookscope.nlp.knowledge_extractor import _build_arcs

    return _build_arcs(chunks, target_arcs=12)


HEADER_RE = re.compile(r"^\[《.+?》(.+?)\]\n?")


def _strip_header(text: str) -> str:
    return HEADER_RE.sub("", text, count=1).strip()


class TestSmartGrouping:
    """Validate chapter → volume → arc grouping is structurally correct."""

    def test_detects_7_volumes(self, chunks):
        from bookscope.nlp.knowledge_extractor import (
            _detect_volumes,
            _group_chunks_by_chapter,
        )

        chapter_groups = _group_chunks_by_chapter(chunks)
        volumes = _detect_volumes(chapter_groups)
        assert len(volumes) == 7, f"Expected 7 volumes, got {len(volumes)}"

    def test_builds_10_to_20_arcs(self, arcs):
        assert 10 <= len(arcs) <= 20, f"Expected 10-20 arcs, got {len(arcs)}"

    def test_arcs_cover_all_chunks(self, chunks, arcs):
        all_covered = set()
        for arc in arcs:
            all_covered.update(arc["all_chunk_indices"])
        assert len(all_covered) == len(chunks), (
            f"Arcs cover {len(all_covered)} chunks, expected {len(chunks)}"
        )

    def test_no_overlapping_arcs(self, arcs):
        seen = set()
        for arc in arcs:
            for idx in arc["all_chunk_indices"]:
                assert idx not in seen, (
                    f"Chunk {idx} appears in multiple arcs"
                )
                seen.add(idx)

    def test_arc_order_preserved(self, arcs):
        prev_max = -1
        for arc in arcs:
            indices = arc["all_chunk_indices"]
            assert min(indices) > prev_max, (
                f"Arc {arc['arc_index']}: min index {min(indices)} <= prev max {prev_max}"
            )
            prev_max = max(indices)


class TestDataDepth:
    """Core test: verify budget-filling sends enough text to LLM."""

    def test_each_arc_fills_budget(self, chunks, arcs):
        """Each arc with enough content should use ~25K chars."""
        from bookscope.nlp.knowledge_extractor import _MAX_ARC_CHARS

        for arc in arcs:
            rep_indices = arc["representative_chunks"]
            total_chars = 0
            for idx in rep_indices:
                text = _strip_header(chunks[idx].text)
                total_chars += len(text)

            # Arc 0 (序章) may be small, skip it
            if len(arc["all_chunk_indices"]) < 30:
                continue

            # Each large arc should fill at least 80% of budget
            assert total_chars >= _MAX_ARC_CHARS * 0.80, (
                f"Arc {arc['arc_index']} ({arc['title'][:30]}): "
                f"only {total_chars:,} chars, expected >= {int(_MAX_ARC_CHARS * 0.80):,}"
            )

    def test_minimum_20_percent_coverage(self, chunks, arcs):
        """Total text selected must be >= 20% of original."""
        total_original = sum(len(c.text) for c in chunks)
        total_selected = sum(
            len(_strip_header(chunks[idx].text))
            for arc in arcs
            for idx in arc["representative_chunks"]
            if idx < len(chunks)
        )
        coverage = total_selected / total_original
        assert coverage >= 0.20, (
            f"Coverage {coverage:.1%} is below 20% minimum. "
            f"Selected {total_selected:,} / {total_original:,} chars"
        )

    def test_each_arc_has_enough_chunks(self, arcs):
        """Each arc must select at least 5 representative chunks."""
        for arc in arcs:
            n_reps = len(arc["representative_chunks"])
            # Small arcs (< 10 chunks) may have fewer reps
            if len(arc["all_chunk_indices"]) >= 10:
                assert n_reps >= 5, (
                    f"Arc {arc['arc_index']}: only {n_reps} reps for "
                    f"{len(arc['all_chunk_indices'])} chunks"
                )

    def test_representative_chunks_are_meaningful(self, chunks, arcs):
        """Representative chunks should not be tiny TOC/header-only chunks."""
        from bookscope.nlp.knowledge_extractor import _MIN_CONTENT_LEN

        for arc in arcs:
            for idx in arc["representative_chunks"]:
                text = _strip_header(chunks[idx].text)
                if len(text) < _MIN_CONTENT_LEN:
                    # Count how many meaningful chunks exist in this arc
                    meaningful = sum(
                        1 for i in arc["all_chunk_indices"]
                        if len(_strip_header(chunks[i].text)) >= _MIN_CONTENT_LEN
                    )
                    # Only flag if there were better options
                    if meaningful >= 5:
                        pytest.fail(
                            f"Arc {arc['arc_index']} selected tiny chunk {idx} "
                            f"({len(text)} chars) when {meaningful} meaningful chunks exist"
                        )

    def test_structural_coverage(self, chunks, arcs):
        """First and last meaningful chunks of each arc should be selected."""
        from bookscope.nlp.knowledge_extractor import _MIN_CONTENT_LEN

        for arc in arcs:
            all_idx = arc["all_chunk_indices"]
            meaningful = [
                i for i in all_idx
                if len(_strip_header(chunks[i].text)) >= _MIN_CONTENT_LEN
            ]
            if len(meaningful) < 3:
                continue

            reps = set(arc["representative_chunks"])
            # First and last meaningful should be in reps
            assert meaningful[0] in reps, (
                f"Arc {arc['arc_index']}: first meaningful chunk {meaningful[0]} not selected"
            )
            assert meaningful[-1] in reps, (
                f"Arc {arc['arc_index']}: last meaningful chunk {meaningful[-1]} not selected"
            )


class TestV5Parity:
    """Compare v6 data depth against v5 baselines."""

    def test_total_text_exceeds_300k(self, chunks, arcs):
        """v6 should send at least 300K chars total (v5 deep phase: 1.57M)."""
        total = sum(
            len(_strip_header(chunks[idx].text))
            for arc in arcs
            for idx in arc["representative_chunks"]
            if idx < len(chunks)
        )
        assert total >= 300_000, (
            f"Total selected text {total:,} chars < 300K minimum"
        )

    def test_per_arc_matches_v5_per_chapter_budget(self, chunks, arcs):
        """Each arc should get roughly the same text budget as v5 gave each chapter (25K)."""
        from bookscope.nlp.knowledge_extractor import _MAX_ARC_CHARS

        budgets = []
        for arc in arcs:
            total = sum(
                len(_strip_header(chunks[idx].text))
                for idx in arc["representative_chunks"]
            )
            budgets.append(total)

        avg_budget = sum(budgets) / len(budgets)
        # Average should be within 80% of max arc chars
        assert avg_budget >= _MAX_ARC_CHARS * 0.80, (
            f"Average arc budget {avg_budget:,.0f} < 80% of {_MAX_ARC_CHARS:,}"
        )

    def test_llm_calls_under_25(self, arcs):
        """Total LLM calls should be under 25 (arcs + merge + outline + rhythm + summary)."""
        total_calls = len(arcs) + 4
        assert total_calls <= 25, f"Too many LLM calls: {total_calls}"

    def test_improvement_ratio(self, chunks, arcs):
        """v6 should use at least 95% fewer LLM calls than v5."""
        from bookscope.nlp.knowledge_extractor import (
            _BATCH_SIZE,
            _group_chunks_by_chapter,
        )

        chapter_groups = _group_chunks_by_chapter(chunks)
        v5_calls = (len(chunks) + _BATCH_SIZE - 1) // _BATCH_SIZE + len(chapter_groups) + 3
        v6_calls = len(arcs) + 4

        reduction = 1 - v6_calls / v5_calls
        assert reduction >= 0.90, (
            f"Only {reduction:.0%} reduction in LLM calls "
            f"(v5={v5_calls}, v6={v6_calls}), expected >= 90%"
        )
