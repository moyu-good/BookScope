"""WP8a rubric 版本链 + 题型感知解析哨兵测试（2026-06-10）.

镜像 WP0 ``test_prompt_version.py`` 的模子，守护四件事——任何一件再被
静默破坏，本套测试先叫：

1. 生产默认 rubric 版本 = ``CURRENT_RUBRIC_VERSION``（防 reviewer 又退回
   硬编码 v1——PE 交付的 v2 当死文件三个月无人发现是直接起因）
2. rubric 路径由版本常量拼出且文件真实存在
3. env override ``BOOKSCOPE_REVIEWER_RUBRIC_PATH`` 在加载层真生效
4. 三种返回形态都能正确标准化出分——v2 形态（``total`` 数字 +
   ``overall_comment`` 文字 + ``question_type_detected``）/ v1 形态
   （``overall`` 是数字）/ DeepSeek 漂移形态（``overall`` 文字 +
   ``total`` 数字），且解析结果都带 ``rubric_version`` 字段

设计稿：``docs/internal/design/WP8a-rubric-v2.md``
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bookscope.agent import reviewer


def _parse(obj: dict[str, Any]) -> dict[str, Any]:
    """把一个 review dict 序列化成 JSON 文本，过一遍 reviewer 的解析+标准化。

    ``_parse_review_json`` 是 reviewer 标准化的唯一入口，直接喂文本测它
    （仿 WP0 测试直接调 ``loop_shared`` 的纯函数）。
    """
    return reviewer._parse_review_json(json.dumps(obj, ensure_ascii=False))


def _scores_5() -> dict[str, int]:
    return {
        "structural_judgment": 5,
        "evidence_density": 4,
        "honesty": 5,
        "actionability": 4,
        "cross_chapter_coherence": 4,
    }


def _comments_5() -> dict[str, str]:
    return {
        "structural_judgment": "判断明确",
        "evidence_density": "证据够",
        "honesty": "敢说薄",
        "actionability": "给了 TODO",
        "cross_chapter_coherence": "跨了五章",
    }


# ---------------------------------------------------------------------------
# 1. 单一事实源哨兵
# ---------------------------------------------------------------------------


class TestRubricVersionSentinel:
    def test_current_version_is_v2(self):
        """生产默认 rubric 版本断言——改版本必须有意识地改这条测试。"""
        assert reviewer.CURRENT_RUBRIC_VERSION == "v2"

    def test_default_path_derived_from_current_version(self):
        """路径由版本常量拼出（单一事实源），且文件真实存在。"""
        path = reviewer.resolve_rubric_path()
        expected_name = f"reviewer_rubric_{reviewer.CURRENT_RUBRIC_VERSION}.md"
        assert path.name == expected_name
        assert path.is_file()


# ---------------------------------------------------------------------------
# 2. 版本解析 + env override
# ---------------------------------------------------------------------------


class TestRubricPathResolution:
    def test_version_from_standard_filename(self):
        path = Path("reviewer_rubric_v2.md")
        assert reviewer.rubric_version_from_path(path) == "v2"

    def test_version_from_nonstandard_filename_falls_back_to_stem(self):
        assert reviewer.rubric_version_from_path(Path("custom.md")) == "custom"

    def test_no_override_resolves_default(self, monkeypatch):
        monkeypatch.delenv(reviewer.RUBRIC_PATH_ENV_VAR, raising=False)
        assert (
            reviewer.current_rubric_version() == reviewer.CURRENT_RUBRIC_VERSION
        )

    def test_env_override_takes_effect(self, tmp_path, monkeypatch):
        """override 直接读 env，绕过版本拼接——A/B 对照 / 回归历史版本用。"""
        override = tmp_path / "reviewer_rubric_vtest.md"
        override.write_text("# override rubric vtest", encoding="utf-8")
        monkeypatch.setenv(reviewer.RUBRIC_PATH_ENV_VAR, str(override))

        assert reviewer.resolve_rubric_path() == override
        assert reviewer.current_rubric_version() == "vtest"
        assert reviewer._load_rubric() == "# override rubric vtest"


# ---------------------------------------------------------------------------
# 3. 三种返回形态都正确标准化出分 + rubric_version 进结果
# ---------------------------------------------------------------------------


class TestReviewFormNormalization:
    def test_v2_form(self, monkeypatch):
        """v2 形态：total 数字 + overall_comment 文字 + question_type_detected。"""
        monkeypatch.delenv(reviewer.RUBRIC_PATH_ENV_VAR, raising=False)
        result = _parse(
            {
                "question_type_detected": "diagnostic",
                "scores": _scores_5(),
                "per_dimension_comment": _comments_5(),
                "total": 22,
                "overall_comment": "答复有判断、敢说薄，作为第一读者反馈站得住。",
                "top_issues": ["第 20 章那条线索没原文撑"],
                "single_most_valuable_improvement": "给支线补两处出场定位",
            }
        )
        assert result["total"] == 22
        assert result["question_type_detected"] == "diagnostic"
        assert result["overall_comment"].startswith("答复有判断")
        assert result["rubric_version"] == reviewer.CURRENT_RUBRIC_VERSION

    def test_v1_form_overall_is_number(self, monkeypatch):
        """v1 / minimax 形态：分数写在 overall（数字），缺 total——回填 total。"""
        monkeypatch.delenv(reviewer.RUBRIC_PATH_ENV_VAR, raising=False)
        result = _parse(
            {
                "scores": _scores_5(),
                "per_dimension_comment": _comments_5(),
                "overall": 22,
                "top_issues": [],
                "single_most_valuable_improvement": "n/a",
            }
        )
        # overall 数字回填进 total
        assert result["total"] == 22
        assert result["overall"] == 22
        # v1 rubric 不产题型字段，缺省补 None 不炸
        assert result["question_type_detected"] is None
        assert result["rubric_version"] == reviewer.CURRENT_RUBRIC_VERSION

    def test_deepseek_drift_form(self, monkeypatch):
        """DeepSeek 漂移形态：overall 是文字总评、total 是分数——total 优先取。"""
        monkeypatch.delenv(reviewer.RUBRIC_PATH_ENV_VAR, raising=False)
        result = _parse(
            {
                "scores": _scores_5(),
                "per_dimension_comment": _comments_5(),
                "overall": "整体答复有判断，证据链能跟着走。",
                "total": 22,
                "top_issues": [],
                "single_most_valuable_improvement": "n/a",
            }
        )
        # total 不被 overall 文字污染，优先取数字 total
        assert result["total"] == 22
        # overall 文字原样透传，不被改写成数字
        assert result["overall"] == "整体答复有判断，证据链能跟着走。"
        assert result["rubric_version"] == reviewer.CURRENT_RUBRIC_VERSION

    def test_total_as_numeric_string_coerced(self, monkeypatch):
        """跨 provider 兜底：total 写成数字字符串 "22" 也认。"""
        monkeypatch.delenv(reviewer.RUBRIC_PATH_ENV_VAR, raising=False)
        result = _parse(
            {
                "scores": _scores_5(),
                "per_dimension_comment": _comments_5(),
                "total": "22",
                "overall_comment": "文字总评",
                "top_issues": [],
                "single_most_valuable_improvement": "n/a",
            }
        )
        assert result["total"] == 22

    def test_rubric_version_reflects_override(self, tmp_path, monkeypatch):
        """override 生效时解析结果的 rubric_version 如实反映 override 版本。"""
        override = tmp_path / "reviewer_rubric_vtest.md"
        override.write_text("# vtest", encoding="utf-8")
        monkeypatch.setenv(reviewer.RUBRIC_PATH_ENV_VAR, str(override))
        result = _parse(
            {
                "scores": _scores_5(),
                "per_dimension_comment": _comments_5(),
                "total": 22,
                "overall_comment": "文字总评",
                "top_issues": [],
                "single_most_valuable_improvement": "n/a",
            }
        )
        assert result["rubric_version"] == "vtest"
