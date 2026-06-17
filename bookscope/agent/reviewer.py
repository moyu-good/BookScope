"""Reviewer agent —— 独立的 AI 审稿人，评估 BookScope 的 answer 作为
"作家第一读者反馈"的质量。

**设计原则**（作者 2026-04-24 session 内指示："首先配置一个 AI agent
审稿人来分析，而不是让我来"）：

- 审稿人**不审事实对错**（事实由 citation 原文佐证）
- 审稿人审的是：**这份答复作为"作家第一读者反馈"对作家真有用吗**——
  有没有判断、敢不敢说薄、可操作吗、跨章节视野够吗
- 走 `LLMClient` Protocol，provider-agnostic——和 AgentLoop 一致
- 输出严格 JSON（5 维打分 + per-维点评 + total/overall_comment + top
  issues + single_most_valuable_improvement），字段和当前 rubric
  （默认 `reviewer_rubric_v2.md`，见 `CURRENT_RUBRIC_VERSION`）1:1 对应

本模块刻意**极简**：一个 `review_answer` 函数，不做类、不做 Pydantic
模型。第一版让作者先看产出有没有用，再决定工程化程度。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from bookscope.agent._internal.loop_shared import read_openai_choice_content
from bookscope.agent.adapters import LLMClient
from bookscope.agent.errors import ContentFiltered, LLMFormatError
from bookscope.agent.utils.json_parsing import (
    autofix_control_chars_in_strings as _autofix_control_chars_in_strings,
)
from bookscope.agent.utils.json_parsing import (
    autofix_fullwidth_quote_string_closer as _autofix_fullwidth_quote_string_closer,
)
from bookscope.agent.utils.json_parsing import (
    autofix_stray_apostrophe_string_closer as _autofix_stray_apostrophe_string_closer,
)
from bookscope.agent.utils.json_parsing import (
    autofix_trailing_commas as _autofix_trailing_commas,
)
from bookscope.agent.utils.json_parsing import (
    autofix_unescaped_answer_quotes as _autofix_unescaped_answer_quotes,
)
from bookscope.agent.utils.json_parsing import (
    autofix_unescaped_quotes_in_all_string_values as _autofix_unescaped_quotes_in_all_string_values,
)
from bookscope.agent.utils.json_parsing import (
    extract_first_json_object as _extract_first_json_object,
)
from bookscope.agent.utils.json_parsing import (
    strip_code_fence as _strip_code_fence,
)

CURRENT_RUBRIC_VERSION = "v2"
"""生产默认 rubric 版本——单一事实源，改版本只动这一行。

WP8a（2026-06-10）：reviewer 自第一版起硬编码加载 ``reviewer_rubric_v1.md``，
PE 交付的 v2（``total`` / ``overall_comment`` 字段语义钉死 + 题型感知）一直是
零引用死文件。本常量是 WP0 ``CURRENT_PROMPT_VERSION`` 的镜像——版本指针 +
路径拼接 + env override + 哨兵测试同一套机制。
``tests/agent/r2/test_rubric_version.py`` 有哨兵断言守护本值。
"""

RUBRIC_PATH_ENV_VAR = "BOOKSCOPE_REVIEWER_RUBRIC_PATH"
"""实验用 rubric override 环境变量（仿 ``BOOKSCOPE_LOOP_PROMPT_PATH``）。

设了就直接加载该路径的 rubric 文件，绕过版本拼接——A/B 对照或回归历史
版本时用。相对路径按当前工作目录解析（batch / probe 脚本约定从仓库根运行）。
"""

_PROMPTS_DIR = Path(__file__).parent / "prompts"

_THINKING_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
"""minimax M2.7 等 reasoning model 会在 reviewer 输出里裹 ``<think>...</think>``
块（commit aa8d8d0 batch-03 q1 因此挂掉 reviewer JSON parse）。
``_parse_review_json`` 入口剥掉。"""

DEFAULT_MAX_TOKENS: int = 4000
"""reviewer 响应 token 上限。第 28 轮 minimax 跑 anshi 时 2000 不够——
长 dimension 评语 + per_dimension_comment + top_issues + single_most_
valuable_improvement 经常超 2000，截断后整段 JSON 无法闭合，autofix
也救不回。第 29 轮起默认 4000；可经 ``BOOKSCOPE_REVIEW_MAX_TOKENS``
环境变量再调。"""

DEFAULT_CONTENT_FILTER_RETRY_LIMIT: int = 2
"""reviewer 端 ``ContentFiltered`` 重试上限（第 31 轮加）。

reviewer 拿 generator 输出 + 题面一起送回 minimax 评分时偶发 422
``output new_sensitive``——比 generator 单独跑更易触发，因为 input
含敏感词排列组合。重试同 input 通常能过；超限则视为可恢复降级，
返回 placeholder review dict 而不是抛异常炸 batch。"""

DEFAULT_EMPTY_TEXT_RETRY_LIMIT: int = 2
"""reviewer 返空 text 重试上限（第十六波加）。

minimax 拒答有两种表现——一种是 422 ``output new_sensitive``（走
ContentFiltered 重试），另一种是 200 但 response 里 text 为空（静默拒答 /
间歇性）。后一种之前直接抛 LLMFormatError，第十六波 dogfood 两本作者亲选书
答题验证都挂在这条——亏成首富 + 制内市场 reviewer 都返空 text。按 memory
`feedback_global_not_single_case.md` 通用兜底姿态——空 text 跟 422 是同一类
间歇性问题，重试常能过。"""

_NEUTRALIZE_HINT: str = (
    "\n\n[内部重试提示] 上一次评分输出被 provider 内容审核拦截或静默拒答。"
    "请用中性、学术化的措辞展开同一评分——避免直接重复"
    "题面 / answer 里的敏感词，改用'传播''叙事建构''史料还原'"
    "等中性术语。评分 rubric / JSON 结构不变。"
)
"""中性化提示——ContentFiltered 和空 text 两条重试链共用。

ContentFiltered 第 2 次起 append；空 text 第 1 次起 append（空 text 救回
窗口更窄——只 2 次机会，第一次失败就该改 prompt）。"""


def review_answer(
    *,
    client: LLMClient,
    model: str,
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
    book_title: str,
    language: str = "zh",
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """跑一次 reviewer，返回解析后的评分 dict。

    Args:
        client: ``LLMClient`` Protocol 实现（由调用方选 adapter 注入）
        model: 模型名。建议和生成端**不同**以降低自我偏袒；只有一个 key
            时使用同模型也可以，调用方需在展示层明示 limitation
        question: 作家原问题
        answer: BookScope 生成的 answer 文本
        citations: ``[{"chapter": int, "snippet": str}, ...]``
        book_title: 书名
        language: 语种；默认 zh
        max_tokens: LLM 响应 token 上限

    Returns:
        评分 dict，字段与 reviewer_rubric_v1.md 规定一致：
        ``scores`` / ``per_dimension_comment`` / ``overall`` /
        ``top_issues`` / ``single_most_valuable_improvement``。

    Raises:
        LLMFormatError: reviewer 返回非 JSON、JSON 缺字段、字段类型错等。
        ProviderError 子类: LLM 调用失败时从 adapter 透传。
    """
    system_prompt = _load_rubric()
    user_content = _format_user_input(
        question=question,
        answer=answer,
        citations=citations,
        book_title=book_title,
        language=language,
    )

    effective_max = max_tokens
    if effective_max is None:
        env_val = os.environ.get("BOOKSCOPE_REVIEW_MAX_TOKENS")
        if env_val:
            try:
                effective_max = int(env_val)
            except ValueError:
                effective_max = DEFAULT_MAX_TOKENS
        else:
            effective_max = DEFAULT_MAX_TOKENS

    # 第十六波加——空 text 重试 + 中性化提示。minimax 间歇性会返 200 +
    # 空 content（静默拒答），跟 422 ContentFiltered 是同一类问题不同表现。
    # 重试窗口窄（默认 2 次），所以第 1 次失败就加中性化提示，给 LLM 一次
    # 改用学术化措辞的机会再降级。
    empty_attempts = 0
    while True:
        active_system = system_prompt
        if empty_attempts >= 1:
            active_system = system_prompt + _NEUTRALIZE_HINT
        response = _call_with_content_filter_retry(
            client=client,
            model=model,
            system_prompt=active_system,
            user_content=user_content,
            max_tokens=effective_max,
        )
        text = _extract_text(response)
        if text:
            return _parse_review_json(text)
        empty_attempts += 1
        if empty_attempts > DEFAULT_EMPTY_TEXT_RETRY_LIMIT:
            raise LLMFormatError(
                f"reviewer returned empty text after {empty_attempts} attempts"
            )


# ---------------------------------------------------------------------------
# 内部工具
# ---------------------------------------------------------------------------


def resolve_rubric_path() -> Path:
    """算出本次实际要加载的 rubric 路径。

    优先级：env ``BOOKSCOPE_REVIEWER_RUBRIC_PATH``（实验 override）>
    默认 ``reviewer_rubric_{CURRENT_RUBRIC_VERSION}.md``。相对路径按当前
    工作目录解析（batch / probe 脚本约定从仓库根运行）。仿
    ``loop_shared.resolve_system_prompt_path``。
    """
    override = os.environ.get(RUBRIC_PATH_ENV_VAR)
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    return _PROMPTS_DIR / f"reviewer_rubric_{CURRENT_RUBRIC_VERSION}.md"


def rubric_version_from_path(path: Path) -> str:
    """从 rubric 文件名解析版本号；非标准命名时回退整个 stem。

    ``reviewer_rubric_v2.md`` → ``"v2"``；``custom.md`` → ``"custom"``。
    仿 ``loop_shared.prompt_version_from_path``。
    """
    stem = path.stem
    prefix = "reviewer_rubric_"
    if stem.startswith(prefix):
        return stem[len(prefix) :]
    return stem


def current_rubric_version() -> str:
    """本次实际生效的 rubric 版本（含 override 解析）。"""
    return rubric_version_from_path(resolve_rubric_path())


def _load_rubric() -> str:
    """从磁盘读当前版本 rubric；缺失直接 FileNotFoundError。"""
    return resolve_rubric_path().read_text(encoding="utf-8")


def _call_with_content_filter_retry(
    *,
    client: LLMClient,
    model: str,
    system_prompt: str,
    user_content: str,
    max_tokens: int,
) -> dict[str, Any]:
    """带内容审核重试的 reviewer LLM 调用。

    第 31 轮加。背景：minimax M2.7 reviewer 拿 generator 输出 + 题面
    一起送回审核时偶发 422 ``output new_sensitive``，比 generator 单跑
    更易触发——重试同 input 通常能过。

    重试策略：第 1 次重试同 input；第 2 次在 system 后追加中性化措辞
    提示。超过 ``DEFAULT_CONTENT_FILTER_RETRY_LIMIT`` 后把最后一次异常
    冒上去——本函数只保证"重试到位"，让 ``review_answer`` 决定是否兜底。
    """
    attempts = 0
    while True:
        active_system = system_prompt
        if attempts >= 2:
            active_system = system_prompt + _NEUTRALIZE_HINT
        try:
            return client.messages_create(
                model=model,
                system=active_system,
                tools=[],
                messages=[{"role": "user", "content": user_content}],
                max_tokens=max_tokens,
            )
        except ContentFiltered:
            attempts += 1
            if attempts > DEFAULT_CONTENT_FILTER_RETRY_LIMIT:
                raise
            continue


def _format_user_input(
    *,
    question: str,
    answer: str,
    citations: list[dict[str, Any]],
    book_title: str,
    language: str,
) -> str:
    """把四样东西拼成一段 user message。"""
    citations_json = json.dumps(citations, ensure_ascii=False, indent=2)
    return (
        f"# 书名\n{book_title}\n\n"
        f"# 语种\n{language}\n\n"
        f"# 作家的问题\n{question}\n\n"
        f"# BookScope 给出的 answer\n{answer}\n\n"
        f"# 给出的 citations\n```json\n{citations_json}\n```\n\n"
        f"请按 reviewer_rubric_{current_rubric_version()} 规范出评分报告。"
    )


def _extract_text(response: dict[str, Any]) -> str:
    """把 adapter 返回的 response 抽成纯文本——兼容 OpenAI / Anthropic 两种形态。

    2026-06-10 修：Sprint 7（ADR-007）后 adapter 返回 OpenAI 形态
    （``choices[0].message.content``），本函数原来只认 Anthropic block list
    （``content``）——导致 r2 切换起 reviewer 对所有 provider 一律
    "returned empty text"。exp006 记录的"minimax reviewer 60/60 全空"
    根因是这里，不是 minimax 拒答。两种形态都认，先 OpenAI（现行）
    后 Anthropic（兼容历史 mock / 可能的反向翻译 adapter）。
    """
    # OpenAI 形态（r2 现行）：choices[0].message.content
    openai_text = read_openai_choice_content(response)
    if openai_text:
        return openai_text

    # Anthropic block list 形态（r1 历史 / Anthropic 原生 mock）
    content = response.get("content") or []
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "\n".join(parts).strip()


def _parse_review_json(text: str) -> dict[str, Any]:
    """复用 AgentLoop 的 JSON 解析三连：strip fence → first object →
    autofix unescaped quotes。astron 类 code 模型在 reviewer 场景下
    仍可能用裸 ASCII `"` 引用，复用同一套兜底才稳。

    parse 失败时把原始文本挂在异常的 ``raw_text`` 属性上便于诊断。
    """
    if not text:
        raise LLMFormatError("reviewer returned empty text")

    candidate = _strip_code_fence(text)
    # reasoning model（minimax M2.7 等）会裹 <think>...</think>，先剥
    # 再走 _extract_first_json_object，否则 think 里的 `{` 会扰乱括号配对
    candidate = _THINKING_BLOCK_RE.sub("", candidate).strip()
    if not candidate:
        raise LLMFormatError("reviewer returned only thinking block")
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        json_slice = _extract_first_json_object(candidate)
        if json_slice is None:
            # `'`-as-string-closer 会让 `"`-balance 跑乱、定位失败；
            # 先尝试 stray-apostrophe autofix 再重试一次定位。
            apos_fixed = _autofix_stray_apostrophe_string_closer(candidate)
            if apos_fixed is not None:
                json_slice = _extract_first_json_object(apos_fixed)
        if json_slice is None:
            # 全角引号 `”` 误代替 `"` 收束同样让 `"`-balance 跑乱
            # （exp004 zhinei run2 q5）；同样修后重试定位。
            fw_fixed = _autofix_fullwidth_quote_string_closer(candidate)
            if fw_fixed is not None:
                json_slice = _extract_first_json_object(fw_fixed)
        if json_slice is None:
            exc = LLMFormatError("reviewer output has no valid JSON object")
            exc.raw_text = text  # type: ignore[attr-defined]
            raise exc from None
        try:
            obj = json.loads(json_slice)
        except json.JSONDecodeError:
            # reviewer JSON 结构是嵌套对象（scores / per_dimension_comment /
            # overall / top_issues / single_most_valuable_improvement），
            # loop 里的定向 autofix（只修 `answer` 字段）大概率命中不到。
            # 先试一次定向，再退到通用状态机扫描。
            # autofix 链：定向引号 → 通用引号 → control char → trailing
            # comma。任一命中即试 parse；都不命中或 parse 仍失败时附
            # raw_text 抛出。
            autofixed = _autofix_unescaped_answer_quotes(json_slice)
            if autofixed is None:
                autofixed = _autofix_unescaped_quotes_in_all_string_values(
                    json_slice,
                )
            if autofixed is None:
                autofixed = _autofix_control_chars_in_strings(json_slice)
            else:
                # 引号修过的版本里仍可能有 string-内 control char
                ctrl_fixed = _autofix_control_chars_in_strings(autofixed)
                if ctrl_fixed is not None:
                    autofixed = ctrl_fixed
            if autofixed is None:
                autofixed = _autofix_trailing_commas(json_slice)
            else:
                # 前面修过的版本里仍可能有 trailing comma
                # （exp004 anshi run3 q1 是纯 trailing comma 单发）
                tc_fixed = _autofix_trailing_commas(autofixed)
                if tc_fixed is not None:
                    autofixed = tc_fixed
            if autofixed is None:
                exc = LLMFormatError(
                    "reviewer JSON parse failed and autofix did not apply"
                )
                exc.raw_text = text  # type: ignore[attr-defined]
                raise exc from None
            try:
                obj = json.loads(autofixed)
            except json.JSONDecodeError as jexc:
                # 第二轮：在 quote-fixed 之后再试 control-char autofix
                ctrl_only = _autofix_control_chars_in_strings(autofixed)
                if ctrl_only is not None and ctrl_only != autofixed:
                    try:
                        obj = json.loads(ctrl_only)
                    except json.JSONDecodeError as jexc2:
                        exc = LLMFormatError(
                            f"reviewer JSON parse failed: {jexc2}"
                        )
                        exc.raw_text = text  # type: ignore[attr-defined]
                        raise exc from jexc2
                else:
                    exc = LLMFormatError(f"reviewer JSON parse failed: {jexc}")
                    exc.raw_text = text  # type: ignore[attr-defined]
                    raise exc from jexc

    if not isinstance(obj, dict):
        raise LLMFormatError("reviewer output is not a JSON object")

    # schema 最小校验——总分字段 v1（``overall``）/ v2（``total``）二选一即可，
    # 其余 4 个结构字段照旧必填。WP8a 起 rubric_v2 用 ``total`` + ``overall_comment``
    # 取代 v1 的 ``overall``，所以不能再硬要求 ``overall``。
    structural_required = {
        "scores",
        "per_dimension_comment",
        "top_issues",
        "single_most_valuable_improvement",
    }
    missing = structural_required - set(obj.keys())
    if missing:
        raise LLMFormatError(
            f"reviewer output missing required fields: {sorted(missing)}"
        )
    if "total" not in obj and "overall" not in obj:
        raise LLMFormatError(
            "reviewer output missing total score field "
            "(expected 'total' or 'overall')"
        )

    scores = obj["scores"]
    if not isinstance(scores, dict):
        raise LLMFormatError("reviewer 'scores' must be an object")
    expected_dims = {
        "structural_judgment",
        "evidence_density",
        "honesty",
        "actionability",
        "cross_chapter_coherence",
    }
    missing_dims = expected_dims - set(scores.keys())
    if missing_dims:
        raise LLMFormatError(
            f"reviewer 'scores' missing dimensions: {sorted(missing_dims)}"
        )

    _normalize_review_fields(obj)
    return obj


def _coerce_number(value: Any) -> int | float | None:
    """把 value 转成数字——int / float 原样，数字字符串 parse，其余返 None。

    跨 provider 漂移兜底：DeepSeek 偶尔把分数写成字符串 ``"22"``，minimax
    写裸 int。不抛——拿不到数字就返 None，由调用方决定怎么兜。
    """
    if isinstance(value, bool):  # bool 是 int 子类，先挡掉
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        s = value.strip()
        try:
            return int(s)
        except ValueError:
            try:
                return float(s)
            except ValueError:
                return None
    return None


def _normalize_review_fields(obj: dict[str, Any]) -> None:
    """就地标准化跨版本 / 跨 provider 漂移的字段，方便下游统一消费。

    钉死三件事（WP8a）：

    1. ``total``——总分唯一出口。优先取 v2 的 ``total``（数字）；若缺 ``total``
       但 ``overall`` 是数字（v1 / minimax 把分数写在 ``overall`` 里），用它
       回填 ``total``。两者都不是数字时不写 ``total``（schema 已保证至少有
       一个字段名在，但值可能是文字总评——DeepSeek 把 ``overall`` 当文字用，
       此时分数只能靠五维求和兜，留给下游处理）。
    2. ``question_type_detected``——v2 题型字段透传；缺省补 None 不炸（v1
       rubric 不产此字段）。
    3. ``rubric_version``——记录本次实际用的 rubric 版本，写进解析结果。
    """
    # 1. total 标准化
    total_num = _coerce_number(obj.get("total"))
    if total_num is not None:
        # total 在但可能是数字字符串（DeepSeek 偶发）——就地转成数字
        obj["total"] = total_num
    else:
        # v1 / minimax 兼容：分数写在 overall 里
        overall_num = _coerce_number(obj.get("overall"))
        if overall_num is not None:
            obj["total"] = overall_num

    # 2. question_type_detected 透传（缺省 None）
    obj.setdefault("question_type_detected", None)

    # 3. rubric_version 进解析结果
    obj["rubric_version"] = current_rubric_version()


__all__ = [
    "review_answer",
    "DEFAULT_MAX_TOKENS",
    "CURRENT_RUBRIC_VERSION",
    "RUBRIC_PATH_ENV_VAR",
    "resolve_rubric_path",
    "rubric_version_from_path",
    "current_rubric_version",
]
