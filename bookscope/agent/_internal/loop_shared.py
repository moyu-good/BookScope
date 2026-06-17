"""``bookscope.agent._internal.loop_shared`` —— r1 / r2 loop 共用常量 + helper。

Sprint 7 ③a 把 r1 ``loop.py`` 里 r2 真在用的 13 个常量 + 5 个模块级
helper + 2 个 prompt 加载逻辑（原是 r1 ``AgentLoop`` 的 instance method，
本层改成接 ``instance`` 参数的模块级函数）抽到这里，让 r2 模块的 import
不再指向 r1 ``loop.py``。

姿态仿 commit ``1050367``（autofix 抽 utils）：

- 本层收**真定义**，公共 API 名字不带前导下划线（``elapsed_ms`` 而非
  ``_elapsed_ms``），常量保留原名
- r1 ``loop.py`` 留私有别名转调（``_elapsed_ms = loop_shared.elapsed_ms``
  / ``_load_system_prompt`` instance method 改 delegate）—— Sprint 7 ③b
  删 r1 时这层别名自然消失
- ``_load_system_prompt`` / ``_load_citation_format_hint`` 抽成模块级
  ``load_system_prompt(instance)`` / ``load_citation_format_hint(instance)``
  形式——接 self 形式参数 instance 但不依赖 instance 上任何字段（纯磁盘
  读取），让 r1 / r2 双方都能透明 delegate

本模块严禁 import ``bookscope.agent.loop`` / ``loop_r2`` / ``fast_path``
/ 任何 r2 模块——只允许标准库 + ``bookscope.agent.errors`` /
``bookscope.agent.models`` 等纯数据层。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# 常量（行为冻结、值与 r1 loop.py 完全一致）
# ---------------------------------------------------------------------------

DEFAULT_MODEL: str = "deepseek-v4-flash"
DEFAULT_MAX_ITERATIONS: int = 12
"""每个 query 最大 iter 数。第 32 轮起 8→12——anshi q1 在 minimax+v3.2
上 8 轮跑不收敛挂 MaxIterationsExceeded（dur 290.9s）；agent 多跑几
轮 tool 调用是常态，12 给足空间。timeout_seconds 仍是上限兜底。"""

DEFAULT_TIMEOUT_SECONDS: float = 180.0
"""query 总时长上限。第 35 轮第二波 90→180——dogfood 撞 LoopTimeout：
minimax 单次 LLM 调用 30-50s + 4 轮综合极限 200s 量级；90s 上限让
深度题在第 4 轮 LLM 综合阶段大概率挂 timeout。180s 给足深度题 6-8 轮
LLM 调用的余量，对 fast_path 通识题（3-12s）无影响。"""

DEFAULT_TOOL_RETRY_LIMIT: int = 2
DEFAULT_FORMAT_RETRY_LIMIT: int = 1
DEFAULT_CONTENT_FILTER_RETRY_LIMIT: int = 2
"""内容审核拒绝（``ContentFiltered``）后的重试上限。

第 31 轮 probe 验证：minimax M2.7 对 anshi q3 题面单独 5/5 全过，但
agent loop 累积上下文 + 长答复合成时偶发触发 422 ``output new_sensitive``。
重试同 input 通常能过。设 2 次：第一次直接重试，第二次带中性化提示。
"""


def _read_int_env(env_name: str, default: int) -> int:
    """从环境变量读 int；解析失败 / 未设置 → 返回 default。

    解析失败时静默降级为 default，避免误配置导致整条 import 链炸掉。
    """
    raw = os.environ.get(env_name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


DEFAULT_RATE_LIMIT_RETRY_LIMIT: int = _read_int_env(
    "BOOKSCOPE_RATE_LIMIT_RETRY_LIMIT", 3
)
"""Provider 限流（``RateLimited`` / HTTP 429）后的重试上限（不含原次调用）。

Sprint 2 BE-1：默认 3 次，配指数退避序列 1s → 2s → 4s。
通过 env ``BOOKSCOPE_RATE_LIMIT_RETRY_LIMIT`` 覆盖。
"""

RATE_LIMIT_BACKOFF_BASE_SECONDS: float = 1.0
"""指数退避的初始秒数。第 n 次重试睡 ``BASE * 2 ** (n-1)`` 秒——
即 1, 2, 4, 8...。这是 transport 层兜底，不暴露给用户。"""

DEFAULT_CONTEXT_TRUNCATE_RETRY_LIMIT: int = _read_int_env(
    "BOOKSCOPE_CONTEXT_TRUNCATE_RETRY_LIMIT", 1
)
"""上下文超限（``ContextLimitExceeded``）后的截断重试上限（不含原次调用）。

Sprint 2 BE-2：默认 1 次——保守 MVP 策略。截断后还撑爆说明 system +
最后 user message 加起来本身就超 context window，再截没意义，把原始
``ContextLimitExceeded`` 抛给上层让 API 路由按 ``ProviderError`` 兜底。

通过 env ``BOOKSCOPE_CONTEXT_TRUNCATE_RETRY_LIMIT`` 覆盖。
"""

CONTEXT_TRUNCATE_KEEP_LAST: int = 6
"""截断后保留 messages 列表的最后 K 条上限（含 system 不计入此处的 K）。

策略：从最早的 tool_use / tool_result 对开始**成对**丢弃，直到 messages
长度 ≤ K。配对丢弃避免留下孤儿 tool_use（Anthropic / OpenAI API 直接
422）。最后一条 user message 永远保留。
"""

DEFAULT_MAX_TOKENS: int = 4000

FORCED_SYNTHESIS_REMAINING_SECONDS: float = 30.0
"""剩余时间低于这个秒数时，loop 向对话注入"立即基于已有证据给出
final answer"的提示（WP5 剩时强制综合）。

背景：循环不收敛之前只有"傻跑到 180 秒超时"一条出路，超时硬切是
开环；这里把剩余时间变成反馈量——还来得及让模型自己综合，就别等
硬切。注入后若仍超时，按原超时路径走（partial_evidence 兜底已有）。"""

TOOL_PARALLEL_MAX_WORKERS: int = 5
"""一轮内 N 个 tool_use blocks 并发执行的 worker 上限。"""

CURRENT_PROMPT_VERSION = "v3.5"
"""生产默认 system prompt 版本——单一事实源，改版本只动这一行。

WP0（2026-06-10）：本常量的前身（r1 loop.py 时代）自第 26 轮起冻结在
v3.1，v3.2~v3.5 三轮实验验证的改进从未进过生产，三个月无人发现。
``tests/agent/r2/test_prompt_version.py`` 有哨兵断言守护本值；
重构搬家时若值被静默改动，测试会先叫。
"""

PROMPT_PATH_ENV_VAR = "BOOKSCOPE_LOOP_PROMPT_PATH"
"""实验用 prompt override 环境变量。

WP0 起 override 内建到 ``resolve_system_prompt_path``——旧机制
（run_batch_r1.py patch ``bookscope.agent.loop`` 模块属性）在
Sprint 7 git rm r1 后指向已删除模块，设了直接 ImportError。
"""

SYSTEM_PROMPT_PATH = (
    Path(__file__).parent.parent
    / "prompts"
    / f"loop_system_prompt_{CURRENT_PROMPT_VERSION}.md"
)
CITATION_FORMAT_PATH = (
    Path(__file__).parent.parent / "prompts" / "citation_format_v1.md"
)

QUESTION_PROCESSING_LENGTH_THRESHOLD: int = 30
"""触发问题处理引擎的字数下限——与 ``fast_path.LENGTH_THRESHOLD_FAST``
保持一致。"""

TOOL_NAME_SEARCH = "search_chunks"
TOOL_NAME_CHAPTER_RANGE = "get_chapter_range"
TOOL_NAME_LIST_CHARACTERS = "list_characters_in_chapter"


# ---------------------------------------------------------------------------
# 模块级 helper
# ---------------------------------------------------------------------------


def question_processing_enabled() -> bool:
    """读 env flag ``BOOKSCOPE_QUESTION_PROCESSING_ENABLED``。默认 on。

    设 ``"0"`` 关闭；其他值（含未设）均视为 on。运行时读，便于测试时
    在单条 case 内切换。
    """
    return os.environ.get("BOOKSCOPE_QUESTION_PROCESSING_ENABLED", "1") != "0"


def invoke_client(
    client: Any,
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> Any:
    """把一轮 LLM 调用分发到合适的入口上。

    优先级：
    1. 有 ``messages_create`` 方法 → ``LLMClient`` Protocol 风格（adapter 层）。
    2. 否则退回 ``client.messages.create(...)`` 风格（历史 Fake client /
       直接 ``anthropic.Anthropic`` 实例）。
    """
    if hasattr(client, "messages_create"):
        return client.messages_create(
            model=model,
            system=system,
            tools=tools,
            messages=messages,
            max_tokens=max_tokens,
        )
    return client.messages.create(
        model=model,
        system=system,
        tools=tools,
        messages=messages,
        max_tokens=max_tokens,
    )


def resp_field(resp: Any, field: str) -> Any:
    """对 dict / 对象两种 response 形态统一取字段。"""
    if resp is None:
        return None
    if isinstance(resp, dict):
        return resp.get(field)
    return getattr(resp, field, None)


def read_openai_choice_content(response: Any) -> str:
    """从 OpenAI ``ChatCompletion`` 形态 response 抽 ``choices[0].message.content``。

    Backlog B-1 共用 helper：``AnthropicAdapter`` 反向翻译后吐 OpenAI plain
    dict，``DeepSeekAdapter`` 本来就是 OpenAI 原生形态；两边的
    ``extract_final_text`` 都走这一份实现。

    兼容三种来源——``messages_create`` 返的 plain dict、L2 缓存反序列化
    的 plain dict、单测直接传的 SDK 风格 object——所有字段访问走
    ``resp_field`` 兜底。任一字段缺失返空串，不抛。
    """
    if response is None:
        return ""
    choices = resp_field(response, "choices")
    if not choices:
        return ""
    first = choices[0]
    message = resp_field(first, "message")
    if message is None:
        return ""
    content = resp_field(message, "content")
    if isinstance(content, str):
        return content.strip()
    return ""


def read_openai_usage(response: Any) -> tuple[int, int]:
    """从 OpenAI 形态 response 抽 ``(prompt_tokens, completion_tokens)``。

    缺字段 / usage 本身为 None 时降级 ``(0, 0)``，不抛。
    """
    usage = resp_field(response, "usage")
    if usage is None:
        return 0, 0
    prompt_tokens = resp_field(usage, "prompt_tokens") or 0
    completion_tokens = resp_field(usage, "completion_tokens") or 0
    try:
        return int(prompt_tokens), int(completion_tokens)
    except (TypeError, ValueError):
        return 0, 0


def elapsed_ms(start: float) -> int:
    return int((time.monotonic() - start) * 1000)


def summarise_output(output: Any) -> str:
    """给 trace 用的短 summary；避免整条 chunk 原文进 trace。"""
    if isinstance(output, list):
        return f"list[{len(output)}]"
    if isinstance(output, dict):
        return f"dict[{len(output)} keys]"
    return type(output).__name__


def measure_output_size(output: Any) -> tuple[int, int]:
    """量一次 tool 结果进上下文的体量（WP-agent-token-budget Phase 1）。

    返回 ``(chars, tokens_est)``：

    - ``chars``：序列化后字符数，精确、免分词器。
    - ``tokens_est``：粗估 token，CJK 字 ~0.6 / 其余 ~0.3，仅用于 per-tool
      的 miss 归因排序（search_chunks vs get_chapter_range 谁是肥源）。

    **计费真值看 ``trace.cache_miss_tokens``（API usage），本估算不替代它**；
    这里的用途是把 miss 拆到「哪个 tool 灌进来的新原文」，戴明式先量再砍。
    """
    try:
        text = json.dumps(output, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = str(output)
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    tokens_est = round(cjk * 0.6 + (len(text) - cjk) * 0.3)
    return len(text), tokens_est


# ---------------------------------------------------------------------------
# prompt 加载（原 r1 ``AgentLoop`` 的 instance method；本层抽成模块级
# 接 ``instance`` 形式参数的函数，不依赖 instance 上任何字段，让 r1 /
# r2 双方都能透明 delegate）
# ---------------------------------------------------------------------------


def resolve_system_prompt_path() -> Path:
    """算出本次实例化实际要加载的 prompt 路径。

    优先级：env ``BOOKSCOPE_LOOP_PROMPT_PATH``（实验 override）>
    默认 ``SYSTEM_PROMPT_PATH``。相对路径按当前工作目录解析
    （batch / probe 脚本约定从仓库根运行）。
    """
    override = os.environ.get(PROMPT_PATH_ENV_VAR)
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = Path.cwd() / path
        return path
    return SYSTEM_PROMPT_PATH


def prompt_version_from_path(path: Path) -> str:
    """从 prompt 文件名解析版本号；非标准命名时回退整个 stem。

    ``loop_system_prompt_v3.5.md`` → ``"v3.5"``；``custom.md`` → ``"custom"``。
    供 ``LoopTrace.prompt_version`` 与 batch 元数据使用——版本是
    trace 记录的事实，不是 CLI 参数口头标注。
    """
    stem = path.stem
    prefix = "loop_system_prompt_"
    if stem.startswith(prefix):
        return stem[len(prefix) :]
    return stem


def current_prompt_version() -> str:
    """本次实例化实际生效的 prompt 版本（含 override 解析）。"""
    return prompt_version_from_path(resolve_system_prompt_path())


def load_system_prompt(instance: Any) -> str:  # noqa: ARG001 — 形式参数兼容
    """从磁盘加载 system prompt；文件缺失时抛 ``FileNotFoundError``。"""
    return resolve_system_prompt_path().read_text(encoding="utf-8")


def load_citation_format_hint(instance: Any) -> str:  # noqa: ARG001 — 同上
    """从磁盘加载 citation format hint。"""
    return CITATION_FORMAT_PATH.read_text(encoding="utf-8")
