"""L2 LLM 调用结果缓存 —— Sprint 8 W2。

ADR-008 D-1 第二层：把 ``invoke_client`` 的 LLM 调用结果按 ``(model,
system, tools, messages, max_tokens)`` 作 key 持久化到 SQLite。命中时
跳过一次 LLM API 调用（5-60 秒不等的延迟与 BYOK token 成本）。

### 设计要点

- **存储后端 SQLite**：ADR-008 D-2 决策——重启不丢是产品级要求（用户
  付的 token 钱不能因为进程重启就再付一次）；stdlib 零外部依赖。
- **key 算法（D-3 算法 c 实施版）**：把 messages / tools / system / model
  / max_tokens 合一个 dict，``sort_keys`` JSON dump 后 sha256 取前 24
  字符。assistant 消息里的 ``tool_calls[].id`` 按出现顺序归一化为
  ``call_0`` / ``call_1`` 抹掉 provider 端 random id 抖动；对应的 tool
  消息的 ``tool_call_id`` 用同一映射回填。tools 列表按 ``function.name``
  或顶层 ``name`` 排序，避免 schema 顺序差异虚假 miss。
- **响应序列化**：response 可能是 dict / SDK 对象（Anthropic SDK 或 OpenAI
  SDK 的 pydantic 模型）。SDK 对象先 ``model_dump()`` 转 dict 再 JSON
  序列化；dict 直接 JSON。反序列化只产 dict——调用方（loop_r2 / fast_path）
  已经走 ``_resp_field`` / ``_msg_field`` 兼容 dict / 对象两种形态，命中
  缓存返 dict 不影响下游路径。
- **不缓存失败**：``invoke_client`` 抛 ``ContentFiltered`` / ``RateLimited``
  / ``ContextLimitExceeded`` 时直接传播，不写缓存——失败响应不可复用。
- **schema_version**：本模块定义 ``LLM_CACHE_SCHEMA_VERSION = "v1"``。
  日后改 key 算法 / 序列化格式时升版本，``SQLiteCache`` 自动按 version
  miss 旧条目。
- **prompt_version 整版本失效**：``invalidate_by_prompt_version(old)``
  暴露给上层——prompt 升级时显式调，DB 内对应 row 全部清掉。

### 环境变量

- ``BOOKSCOPE_LLM_CACHE_DISABLED=1``：跑测试或对比 baseline 时关掉缓存
- ``BOOKSCOPE_LLM_CACHE_DB_PATH``：自定义 DB 路径；未设走默认
  ``<repo_root>/.bookscope_cache/llm_cache.db``
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from bookscope.agent._internal.loop_shared import invoke_client as _invoke_client
from bookscope.agent._internal.sqlite_cache import SQLiteCache

logger = logging.getLogger(__name__)

LLM_CACHE_SCHEMA_VERSION = "v1"
"""key 算法 / 序列化格式版本号。改算法时升 → 旧 row 自动 miss。"""

ENV_DISABLED = "BOOKSCOPE_LLM_CACHE_DISABLED"
ENV_DB_PATH = "BOOKSCOPE_LLM_CACHE_DB_PATH"

_DEFAULT_DB_REL_PATH = ".bookscope_cache/llm_cache.db"


def _default_db_path() -> Path:
    """默认 DB 路径：repo root 下 ``.bookscope_cache/llm_cache.db``。

    repo root 通过本文件位置反推（``_internal/llm_cache.py`` 上溯 3 级）。
    env ``BOOKSCOPE_LLM_CACHE_DB_PATH`` 覆盖。
    """
    env_override = os.environ.get(ENV_DB_PATH)
    if env_override:
        return Path(env_override)
    # bookscope/agent/_internal/llm_cache.py → repo root 是 parents[3]
    repo_root = Path(__file__).resolve().parents[3]
    return repo_root / _DEFAULT_DB_REL_PATH


# 模块级单例 + lazy init 锁——避免 import 期就建 DB 文件（让测试 / fixture
# 能先设 env 再 import）
_CACHE_LOCK = threading.Lock()
_CACHE_INSTANCE: SQLiteCache | None = None


def _get_cache() -> SQLiteCache:
    """惰性拿 module-level SQLiteCache 单例。"""
    global _CACHE_INSTANCE
    if _CACHE_INSTANCE is not None:
        return _CACHE_INSTANCE
    with _CACHE_LOCK:
        if _CACHE_INSTANCE is None:
            _CACHE_INSTANCE = SQLiteCache(
                db_path=_default_db_path(),
                table_name="llm_calls",
                schema_version=LLM_CACHE_SCHEMA_VERSION,
            )
        return _CACHE_INSTANCE


def _is_cache_disabled() -> bool:
    """env flag 检查。设 ``"1"`` 关闭；其他值（含未设）视为 on。"""
    return os.environ.get(ENV_DISABLED, "").strip() == "1"


# ---------------------------------------------------------------------------
# key 算法（ADR-008 D-3 算法 c 实施版）
# ---------------------------------------------------------------------------


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """归一化 messages 列表——主要是 ``tool_calls[].id`` 重编号。

    OpenAI provider 端给 tool_calls 生成的 ``id`` 是 random 字符串
    （形如 ``call_abc123``），同样的 input 第二次调用会生成不同 id。
    不归一化的话同 input 算出的 key 不一样，缓存永远 miss。

    本函数按 assistant 消息中 tool_calls 出现的顺序把 id 重编号为
    ``call_0`` / ``call_1`` / ...，对应的 ``role=tool`` 消息的
    ``tool_call_id`` 用同一映射回填。

    其他字段（content / role / name 等）保留原样。
    """
    id_map: dict[str, str] = {}
    counter = 0
    normalized: list[dict[str, Any]] = []
    for msg in messages:
        # 浅拷贝够用——内层 tool_calls 才需要深拷
        new_msg: dict[str, Any] = dict(msg)
        if new_msg.get("role") == "assistant":
            tool_calls = new_msg.get("tool_calls")
            if isinstance(tool_calls, list) and tool_calls:
                new_tcs: list[dict[str, Any]] = []
                for tc in tool_calls:
                    if not isinstance(tc, dict):
                        new_tcs.append(tc)
                        continue
                    old_id = tc.get("id")
                    new_id = f"call_{counter}"
                    counter += 1
                    if isinstance(old_id, str):
                        id_map[old_id] = new_id
                    new_tc = dict(tc)
                    new_tc["id"] = new_id
                    # function 字段嵌套——浅拷再原样塞回（不需要改）
                    if "function" in new_tc and isinstance(
                        new_tc["function"], dict
                    ):
                        new_tc["function"] = dict(new_tc["function"])
                    new_tcs.append(new_tc)
                new_msg["tool_calls"] = new_tcs
        elif new_msg.get("role") == "tool":
            old_tool_call_id = new_msg.get("tool_call_id")
            if isinstance(old_tool_call_id, str) and old_tool_call_id in id_map:
                new_msg["tool_call_id"] = id_map[old_tool_call_id]
        normalized.append(new_msg)
    return normalized


def _normalize_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """按 name 排序 tools 列表——schema 顺序差异不该影响 key。

    name 字段在 r2 形态下嵌在 ``function.name``；在 r1 / Anthropic 形态
    下是顶层 ``name``。两种都接。
    """
    if not tools:
        return []

    def _name_of(tool: dict[str, Any]) -> str:
        # r2 / OpenAI: {"type": "function", "function": {"name": "..."}}
        fn = tool.get("function")
        if isinstance(fn, dict) and isinstance(fn.get("name"), str):
            return fn["name"]
        # r1 / Anthropic: {"name": "...", "input_schema": {...}}
        if isinstance(tool.get("name"), str):
            return tool["name"]
        return ""

    return sorted(tools, key=_name_of)


def _compute_llm_cache_key(
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]] | None,
    messages: list[dict[str, Any]],
    max_tokens: int,
) -> str:
    """按 ADR-008 D-3 算法 c 实施版算 cache key。

    payload = {model, system, tools(sorted by name), messages(id-normalized),
               max_tokens}，sort_keys JSON dump 后 sha256 取前 24 字符。

    Returns:
        24 字符 hex 串。
    """
    payload = {
        "model": model,
        "system": system,
        "tools": _normalize_tools(tools),
        "messages": _normalize_messages(messages),
        "max_tokens": max_tokens,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


# ---------------------------------------------------------------------------
# 序列化 / 反序列化
# ---------------------------------------------------------------------------


def _serialize_response(response: Any) -> bytes:
    """把 response 转 bytes 存进 SQLite。

    response 可能是：

    - dict：直接 JSON
    - pydantic model（Anthropic SDK / OpenAI SDK 的响应对象）：先
      ``model_dump()`` 转 dict 再 JSON
    - 其他：尝试 ``__dict__`` 拷出
    """
    if isinstance(response, dict):
        payload = response
    elif hasattr(response, "model_dump"):
        try:
            payload = response.model_dump()
        except Exception:  # noqa: BLE001
            payload = dict(getattr(response, "__dict__", {}))
    else:
        payload = dict(getattr(response, "__dict__", {}))
    return json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")


def _deserialize_response(blob: bytes) -> dict[str, Any]:
    """从 bytes 反序列化回 dict。

    返 dict 而非 SDK 对象——loop_r2 / fast_path 路径都走 ``_resp_field``
    / ``_msg_field`` 兼容 dict / 对象访问，dict 形态完全兼容。
    """
    return json.loads(blob.decode("utf-8"))


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


def invoke_client_cached(
    client: Any,
    *,
    model: str,
    system: str,
    tools: list[dict[str, Any]],
    messages: list[dict[str, Any]],
    max_tokens: int,
    cache_enabled: bool = True,
) -> Any:
    """带 L2 缓存的 ``invoke_client`` wrapper。

    Args:
        client / model / system / tools / messages / max_tokens: 同
            ``invoke_client``。
        cache_enabled: 调用方显式关缓存（如 reviewer 路径）。env
            ``BOOKSCOPE_LLM_CACHE_DISABLED=1`` 是全局开关，本参数与 env
            **任一**为 False 都视为关。

    Returns:
        命中缓存时返反序列化的 dict；miss 时调原 ``invoke_client`` 后写
        缓存再返原 response（保留 SDK 对象形态，让首次调用的下游兼容性
        100% 跟无缓存路径一致）。

    Raises:
        与 ``invoke_client`` 同——不捕获、不缓存失败响应。
    """
    if not cache_enabled or _is_cache_disabled():
        return _invoke_client(
            client,
            model=model,
            system=system,
            tools=tools,
            messages=messages,
            max_tokens=max_tokens,
        )

    try:
        cache = _get_cache()
        key = _compute_llm_cache_key(
            model=model,
            system=system,
            tools=tools,
            messages=messages,
            max_tokens=max_tokens,
        )
        cached_bytes = cache.get(key)
        if cached_bytes is not None:
            try:
                return _deserialize_response(cached_bytes)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                logger.warning(
                    "llm_cache: deserialize failed (%s); ignoring cached row",
                    exc,
                )
    except Exception as exc:  # noqa: BLE001
        # 缓存层任何意外（DB 锁、磁盘满、key 计算异常）都不能 break LLM 调用
        logger.warning(
            "llm_cache: cache lookup raised %s: %s; bypassing cache",
            type(exc).__name__,
            exc,
        )
        return _invoke_client(
            client,
            model=model,
            system=system,
            tools=tools,
            messages=messages,
            max_tokens=max_tokens,
        )

    response = _invoke_client(
        client,
        model=model,
        system=system,
        tools=tools,
        messages=messages,
        max_tokens=max_tokens,
    )

    # 写缓存——序列化 / DB 写入都包死异常，不能让缓存写失败 break 调用
    try:
        cache.set(key, _serialize_response(response))
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "llm_cache: cache set raised %s: %s; cache miss persists",
            type(exc).__name__,
            exc,
        )

    return response


def invalidate_by_prompt_version(old_prompt_version: str) -> int:
    """整版本失效 —— prompt 升级时显式调用。

    Args:
        old_prompt_version: 旧 prompt 版本号字符串。本层用 SQLiteCache 的
            ``schema_version`` 字段做版本失效——传入的 prompt version 会
            匹配 row 的 ``schema_version`` 字段。

    Returns:
        实际删除的行数。

    Note:
        当前实施中 ``schema_version = LLM_CACHE_SCHEMA_VERSION = "v1"``
        是 key 算法版本，不直接含 prompt version。Sprint 8 W3 / W4 接入
        prompt version 到 schema_version 时，本函数会按"v1:prompt_v3.4"
        这样的复合 version 失效。当前先暴露 API hook，调用本函数 = 显式
        清掉指定 schema_version 的所有 row。
    """
    return _get_cache().invalidate_by_version(old_prompt_version)


def clear_llm_cache() -> None:
    """清空整张 LLM 缓存表 + 重置 stats。给 CLI 工具 / 测试用。"""
    _get_cache().clear_all()


def get_llm_cache_stats() -> dict[str, int]:
    """返 L2 缓存的 hit / miss / size 快照。给 OPS dashboard 用。"""
    return _get_cache().stats()


def reset_llm_cache_singleton_for_test() -> None:
    """把模块级单例重置为 None——给测试用，让下次 ``_get_cache`` 重新建。

    主要用途：测试 fixture 改 env ``BOOKSCOPE_LLM_CACHE_DB_PATH`` 后强制
    重建 SQLiteCache 指向新路径。
    """
    global _CACHE_INSTANCE
    with _CACHE_LOCK:
        _CACHE_INSTANCE = None


__all__ = [
    "ENV_DB_PATH",
    "ENV_DISABLED",
    "LLM_CACHE_SCHEMA_VERSION",
    "clear_llm_cache",
    "get_llm_cache_stats",
    "invalidate_by_prompt_version",
    "invoke_client_cached",
    "reset_llm_cache_singleton_for_test",
]
