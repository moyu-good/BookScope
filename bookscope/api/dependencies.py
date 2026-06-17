"""FastAPI 依赖注入工具。

本模块集中存放路由用到的 Depends 工厂，避免路由文件重复实现同一段
样板代码。当前有三个依赖：

  - :func:`get_book_session_store`  统一入口：默认注入
    :class:`JSONFileSessionStorage` 让 session 进程重启后仍可用
    （ADR-005 方案 A）。测试可通过 ``app.dependency_overrides``
    覆盖为 tmp_path 或纯内存替身。
  - :func:`build_llm_client`        根据 request.provider 构造 adapter。
  - :func:`build_llm_client_from_params` 基于 provider + api_key 的
    低层构造入口，供 upload 端点等非 AgentAskRequest 场景使用。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Literal

from bookscope.agent.adapters import AnthropicAdapter, DeepSeekAdapter, LLMClient
from bookscope.api.book_sessions import (
    BookSessionStore,
)
from bookscope.api.book_sessions import (
    get_book_session_store as _get_memory_only_store,
)
from bookscope.api.conversation_store import JSONFileConversationStore
from bookscope.api.schemas import AgentAskRequest
from bookscope.api.session_storage import JSONFileSessionStorage

DEFAULT_MODEL_BY_PROVIDER: dict[str, str] = {
    "deepseek": "deepseek-v4-flash",
    "anthropic": "claude-sonnet-4-6",
}
"""默认模型名（ADR-002 v2 + 第 30 轮）。请求不传 model 时使用。"""


DEFAULT_SESSIONS_ROOT: Path = Path("data/sessions")
"""本地 session 数据默认根目录（ADR-005 方案 A）。

相对路径，以进程工作目录为根——符合 "作者从仓库根跑 uvicorn" 的典型
部署形态。测试时 FastAPI dependency override 会把这个路径替换为
``tmp_path``。
"""


def default_model_for(provider: Literal["deepseek", "anthropic"]) -> str:
    """按 provider 返回默认模型名。

    未知 provider 直接落 deepseek-v4-flash 作为最低保底——这条分支实际
    走不到（Pydantic 的 Literal 已在 schema 层把 provider 值域收死），
    仅为后续扩展时留 graceful fallback。
    """
    return DEFAULT_MODEL_BY_PROVIDER.get(provider, "deepseek-v4-flash")


def build_llm_client(request: AgentAskRequest) -> LLMClient:
    """根据 :class:`AgentAskRequest` 选择并构造对应 adapter。

    adapter 的错误全部向上冒泡；路由层再把 ``ImportError``（SDK 未装）
    与 ``ProviderError`` 家族翻译成合适的 HTTP 状态码。
    """
    return build_llm_client_from_params(
        provider=request.provider,
        api_key=request.api_key,
        base_url=request.base_url,
    )


def build_llm_client_from_params(
    *,
    provider: str,
    api_key: str,
    base_url: str | None = None,
) -> LLMClient:
    """低层 adapter 构造入口。

    upload 端点的 multipart form 没法直接塞进 ``AgentAskRequest``，
    因此本函数只吃最小必要参数，行为与 :func:`build_llm_client` 一致。

    ``base_url`` 的语义：
    - ``deepseek``：仅在用户显式传递时覆盖默认端点（代理 / OpenRouter /
      私有部署 / 其他 OpenAI 兼容 endpoint）
    - ``anthropic``：忽略 base_url（当前 ``AnthropicAdapter`` 不支持）
    """
    if provider == "deepseek":
        if base_url:
            return DeepSeekAdapter(api_key=api_key, base_url=base_url)
        return DeepSeekAdapter(api_key=api_key)
    if provider == "anthropic":
        return AnthropicAdapter(api_key=api_key)
    raise ValueError(f"unsupported provider: {provider!r}")


# ---------------------------------------------------------------------------
# 带持久化后端的 BookSessionStore 单例
# ---------------------------------------------------------------------------


_storage_attach_lock = threading.Lock()


def get_book_session_store() -> BookSessionStore:
    """返回带 :class:`JSONFileSessionStorage` 的 :class:`BookSessionStore` 单例。

    实现细节：本函数返回的是 :mod:`book_sessions` 模块级**同一个** store
    单例——这样 ``from bookscope.api.book_sessions import
    get_book_session_store`` 与 ``from bookscope.api.dependencies import
    get_book_session_store`` 两种写法都能拿到同一实例，单测与路由代码
    不会因 import 路径不同而各自持有各自的 cache。

    首次调用时，会**懒**地为这个共享单例附上 :class:`JSONFileSessionStorage`
    后端（数据根目录见 :data:`DEFAULT_SESSIONS_ROOT`）。重复调用幂等。

    测试可通过 ``app.dependency_overrides`` 覆盖本依赖替换为 tmp_path
    版本，或调 :func:`reset_book_session_store_for_tests` 清空 storage 挂载。
    """
    store = _get_memory_only_store()
    # 只在首次进入时（storage 还没挂）动手；保证并发下只挂一次。
    if store._storage is None:  # noqa: SLF001 — 内部协作字段
        with _storage_attach_lock:
            if store._storage is None:  # noqa: SLF001
                store._storage = JSONFileSessionStorage(  # noqa: SLF001
                    root=DEFAULT_SESSIONS_ROOT,
                )
    return store


_conversation_store_singleton: JSONFileConversationStore | None = None
_conversation_store_lock = threading.Lock()


def get_conversation_store() -> JSONFileConversationStore:
    """返回 :class:`JSONFileConversationStore` 单例（ADR-009 Phase 1a）。

    对话文件落在 book session 同一根目录下（:data:`DEFAULT_SESSIONS_ROOT`）
    ——对话从属于书，删书即删对话。懒初始化，重复调用幂等。

    测试可通过 ``app.dependency_overrides`` 覆盖为 tmp_path 版本，或调
    :func:`reset_conversation_store_for_tests` 清空单例。
    """
    global _conversation_store_singleton
    if _conversation_store_singleton is None:
        with _conversation_store_lock:
            if _conversation_store_singleton is None:
                _conversation_store_singleton = JSONFileConversationStore(
                    root=DEFAULT_SESSIONS_ROOT,
                )
    return _conversation_store_singleton


def reset_conversation_store_for_tests() -> None:
    """清空对话存储单例（仅测试用）。下次 ``get_conversation_store`` 重建。"""
    global _conversation_store_singleton
    with _conversation_store_lock:
        _conversation_store_singleton = None


def reset_book_session_store_for_tests() -> None:
    """解绑持久化后端（仅测试用）。

    把共享 store 的 ``_storage`` 置回 None，让下一次
    :func:`get_book_session_store` 重新挂载。通常配合
    :func:`book_sessions.reset_book_session_store` 一起使用。
    """
    store = _get_memory_only_store()
    with _storage_attach_lock:
        store._storage = None  # noqa: SLF001
    store.clear()


__all__ = [
    "DEFAULT_MODEL_BY_PROVIDER",
    "DEFAULT_SESSIONS_ROOT",
    "BookSessionStore",
    "build_llm_client",
    "build_llm_client_from_params",
    "default_model_for",
    "get_book_session_store",
    "get_conversation_store",
    "reset_book_session_store_for_tests",
    "reset_conversation_store_for_tests",
]
