"""`bookscope.agent.adapters` — provider adapter 层。

``AgentLoop`` 主循环只和 ``LLMClient`` Protocol 打交道，不依赖任何具体
SDK。本子包把各家 LLM 厂商的原生 API 统一包装成符合 Protocol 的 adapter：

- :class:`DeepSeekAdapter` —— ADR-002 v2 选定的**默认** provider，走 OpenAI
  兼容 endpoint。
- :class:`AnthropicAdapter` —— 备选 provider。

### r2 升级历史

Sprint 7（2026-05-15）r1 ``adapters/deepseek.py`` / ``adapters/anthropic.py``
已 ``git rm``。两个 adapter 实际指向 r2 实现（``deepseek_r2.py`` /
``anthropic_r2.py``）——为了 user-facing API 名稳定，对外仍叫
``DeepSeekAdapter`` / ``AnthropicAdapter``，不带 ``_r2`` 后缀。
"""

from bookscope.agent.adapters.anthropic_r2 import AnthropicAdapter
from bookscope.agent.adapters.base import LLMClient
from bookscope.agent.adapters.deepseek_r2 import DeepSeekAdapter

__all__ = [
    "AnthropicAdapter",
    "DeepSeekAdapter",
    "LLMClient",
]
