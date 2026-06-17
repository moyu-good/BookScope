"""``bookscope.agent.adapters.anthropic_r2`` —— r2 下 Anthropic adapter 反向翻译。

ADR-007 D-2 决策：r2 切到 OpenAI function calling 主格式后，AnthropicAdapter
从 r1 时代的 near-passthrough 改为反向翻译——请求方向把 OpenAI 形态翻译
成 Anthropic 形态再喂给 SDK，响应方向把 Anthropic ``Message`` 对象翻译
成 OpenAI ``ChatCompletion`` 形态返回给 loop。

### 翻译表速查

请求方向（OpenAI → Anthropic）：

- ``role=system`` 消息抽出为顶级 ``system`` 字段（多条用 ``\n\n`` 合并）
- 连续 ``role=tool`` 消息合并成一条 ``role=user`` + N 个 ``tool_result`` block
- ``assistant.tool_calls`` → ``content`` 内的 ``tool_use`` block（id 严格保留）
- ``function.arguments``（JSON 字符串）→ ``input``（dict）；解析失败退化
  ``{"_raw": original}``
- tools 嵌套 ``{type, function: {name, description, parameters}}`` →
  扁平 ``{name, description, input_schema}``（兼容 loop_r2 已经传扁平形态的情况）
- ``tool_choice`` 字典映射：``"auto"`` / ``"none"`` / ``"required"`` /
  ``{"type": "function", "function": {"name": X}}`` → 对应 Anthropic 形态

响应方向（Anthropic → OpenAI）：

- ``content`` 内的 ``text`` block 合并为 ``message.content`` 字符串
- ``tool_use`` block → ``tool_calls`` 数组（``input`` dict 转回 JSON 字符串）
- 只有 tool_use 没有 text → ``content`` 为 ``None``
- 只有 text 没有 tool_use → ``tool_calls`` 为 ``None``（不写空 list）
- ``stop_reason`` → ``finish_reason``（``tool_use``→``tool_calls``、
  ``end_turn``→``stop``、``max_tokens``→``length``、``stop_sequence``→``stop``）
- ``usage.input_tokens`` / ``output_tokens`` → ``prompt_tokens`` /
  ``completion_tokens`` + 合计 ``total_tokens``

### 与 r1 ``AnthropicAdapter`` 的关系

不继承 r1 实现——r1 是 near-passthrough，r2 是双向翻译，复用没意义。
错误翻译 helper 从 r1 直接 import 复用（``_translate_error``）。
"""

from __future__ import annotations

import json
from typing import Any, Final, Literal

from bookscope.agent._internal.anthropic_shared import (
    translate_error as _translate_error,
)
from bookscope.agent._internal.loop_shared import (
    read_openai_choice_content as _read_openai_choice_content,
)
from bookscope.agent._internal.loop_shared import (
    read_openai_usage as _read_openai_usage,
)

# ---------------------------------------------------------------------------
# 翻译表常量
# ---------------------------------------------------------------------------

_STOP_REASON_TO_FINISH_REASON: Final[dict[str, str]] = {
    "tool_use": "tool_calls",
    "end_turn": "stop",
    "max_tokens": "length",
    "stop_sequence": "stop",
}

_OBJECT_CHAT_COMPLETION: Final[Literal["chat.completion"]] = "chat.completion"


class AnthropicAdapter:
    """r2 下 Anthropic provider 反向翻译 adapter。

    Args:
        api_key: Anthropic API key。
        anthropic_client: 可选的**已构造好**的 Anthropic client——仅给
            单测注入 mock 用。生产传 ``None`` 时本类会 lazy import
            ``anthropic`` 并自行构造。
    """

    def __init__(
        self,
        api_key: str,
        *,
        anthropic_client: Any | None = None,
    ) -> None:
        self._api_key = api_key
        self._anthropic_client = anthropic_client

    @property
    def _client(self) -> Any:
        """Lazy 构造 SDK client，让测试用 mock 注入路径完全跳过 SDK 依赖检查。"""
        if self._anthropic_client is not None:
            return self._anthropic_client
        self._anthropic_client = self._build_default_client(self._api_key)
        return self._anthropic_client

    @staticmethod
    def _build_default_client(api_key: str) -> Any:
        """Lazy import ``anthropic`` 并构造 client；未装时清晰提示。"""
        try:
            import anthropic  # noqa: PLC0415 — 故意 lazy import
        except ImportError as exc:
            raise ImportError(
                "AnthropicAdapter 需要 anthropic SDK；请先运行："
                "`pip install anthropic`"
            ) from exc
        return anthropic.Anthropic(api_key=api_key)

    # ------------------------------------------------------------------
    # 对外方法
    # ------------------------------------------------------------------

    def messages_create(
        self,
        *,
        model: str,
        system: str,
        tools: list[dict[str, Any]],
        messages: list[dict[str, Any]],
        max_tokens: int,
        temperature: float | None = None,
        tool_choice: Any | None = None,
    ) -> dict[str, Any]:
        """接 OpenAI 形态进来、翻译成 Anthropic 形态喂 SDK、把 SDK 返回翻回 OpenAI 形态。

        loop_r2 的调用约定：
        - ``messages`` 是 OpenAI 形态（role 含 user / assistant / tool；
          assistant 可能带 ``tool_calls``）；可能含 role=system 条目
          （会被抽到顶级 ``system`` 字段；与函数参数 ``system`` 合并）
        - ``tools`` 由 loop_r2._build_tool_schemas 传入 Anthropic 扁平形态
          ``{name, description, input_schema}``；也兼容 OpenAI 嵌套形态
          ``{type: function, function: {...}}``
        - ``tool_choice`` 可选：OpenAI 形态（``"auto"`` / ``"none"`` /
          ``"required"`` / 函数指定字典）
        """
        anth_system, anth_messages = _translate_messages_to_anthropic(system, messages)
        anth_tools = _translate_tools_to_anthropic(tools)
        anth_tool_choice = _translate_tool_choice_to_anthropic(tool_choice)

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": anth_messages,
            "max_tokens": max_tokens,
        }
        if anth_system:
            kwargs["system"] = anth_system
        if anth_tools:
            kwargs["tools"] = anth_tools
        if anth_tool_choice is not None:
            kwargs["tool_choice"] = anth_tool_choice
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            response = self._client.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — 故意拦所有 SDK 异常做翻译
            raise _translate_error(exc) from exc

        return _translate_response_to_openai(response, model=model)

    # ------------------------------------------------------------------
    # LLMClient Protocol：响应解析（Backlog B-1）
    # ------------------------------------------------------------------

    def extract_final_text(self, response: Any) -> str:
        """从 r2 形态响应抽 final 文本。

        ``messages_create`` 已经把 Anthropic ``Message`` 反向翻译成
        OpenAI ``ChatCompletion`` plain dict，所以这里读
        ``choices[0].message.content``——跟 ``DeepSeekAdapter`` 形态
        一致，没有任何 sniffing。

        缓存命中时 response 直接是 dict；首次调用走 ``messages_create``
        也返 dict——两种都被 :func:`_read_openai_choice_content` 兜底。
        """
        return _read_openai_choice_content(response)

    def extract_usage_tokens(self, response: Any) -> tuple[int, int]:
        """抽 ``(input_tokens, output_tokens)``。

        r2 反向翻译已把 Anthropic ``input_tokens`` / ``output_tokens``
        重命名成 OpenAI ``prompt_tokens`` / ``completion_tokens``，
        所以读这两个字段即可。
        """
        return _read_openai_usage(response)


# ---------------------------------------------------------------------------
# 请求方向：OpenAI → Anthropic
# ---------------------------------------------------------------------------


def _translate_messages_to_anthropic(
    system_arg: str,
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI messages → (system 字符串, Anthropic messages list)。

    顶级 ``system_arg`` 与 messages 里所有 role=system 条目合并（用 ``\n\n``
    分隔保结构）。连续的 role=tool 消息合并成一条 role=user + N 个
    tool_result block。
    """
    system_parts: list[str] = []
    if system_arg:
        system_parts.append(system_arg)

    anth: list[dict[str, Any]] = []
    i = 0
    n = len(messages)
    while i < n:
        msg = messages[i]
        role = msg.get("role")
        content = msg.get("content")

        if role == "system":
            text = _coerce_text(content)
            if text:
                system_parts.append(text)
            i += 1
            continue

        if role == "tool":
            # 合并连续 tool 消息成一条 user + N tool_result blocks
            blocks: list[dict[str, Any]] = []
            while i < n and messages[i].get("role") == "tool":
                tmsg = messages[i]
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tmsg.get("tool_call_id", ""),
                        "content": _coerce_text(tmsg.get("content")),
                    }
                )
                i += 1
            anth.append({"role": "user", "content": blocks})
            continue

        if role == "user":
            anth.append({"role": "user", "content": _coerce_text(content)})
            i += 1
            continue

        if role == "assistant":
            anth.append(_translate_assistant_message(msg))
            i += 1
            continue

        # 未知 role:宽容透传字符串内容
        anth.append({"role": str(role or "user"), "content": _coerce_text(content)})
        i += 1

    merged_system = "\n\n".join(s for s in system_parts if s)
    return merged_system, anth


def _translate_assistant_message(msg: dict[str, Any]) -> dict[str, Any]:
    """OpenAI assistant 消息 → Anthropic assistant 消息（content blocks）。

    OpenAI: ``{role: assistant, content: str|None, tool_calls: [...]}``
    Anthropic: ``{role: assistant, content: [text_block?, tool_use_blocks...]}``

    要点：
    - content 非空 → 加 text block（content 为 None / 空串则不加）
    - 每个 tool_call → tool_use block，id 严格保留，arguments JSON 解析
      为 dict；解析失败退化 ``{"_raw": original_str}`` 不 raise
    - Anthropic 要求 content 至少一个 block——若 text 与 tool_use 都没有，
      退化加一个空 text block 保合法
    """
    text = _coerce_text(msg.get("content"))
    tool_calls = msg.get("tool_calls") or []

    blocks: list[dict[str, Any]] = []
    if text:
        blocks.append({"type": "text", "text": text})

    for tc in tool_calls:
        fn = tc.get("function") or {}
        raw_args = fn.get("arguments", "")
        if isinstance(raw_args, dict):
            parsed: Any = raw_args
        else:
            parsed = _parse_arguments_string(raw_args if isinstance(raw_args, str) else "")
        blocks.append(
            {
                "type": "tool_use",
                "id": tc.get("id", ""),
                "name": fn.get("name", ""),
                "input": parsed,
            }
        )

    if not blocks:
        blocks.append({"type": "text", "text": ""})

    return {"role": "assistant", "content": blocks}


def _parse_arguments_string(raw: str) -> dict[str, Any]:
    """OpenAI ``function.arguments`` 字符串 → Anthropic ``input`` dict。

    JSON 解析失败时退化为 ``{"_raw": raw}``（容错，不 raise）。空串退化空 dict。
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"_raw": raw}
    if not isinstance(parsed, dict):
        return {"_raw": raw}
    return parsed


def _translate_tools_to_anthropic(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """OpenAI ``tools`` → Anthropic ``tools``。

    兼容两种入参形态：
    1. OpenAI 嵌套 ``{type: function, function: {name, description, parameters}}``
       → 扁平 ``{name, description, input_schema}``
    2. Anthropic 扁平 ``{name, description, input_schema}``（loop_r2 当前
       直接传这种形态）→ 原样返回
    """
    if not tools:
        return []

    out: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            fn = tool["function"]
            out.append(
                {
                    "name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters", {}),
                }
            )
        else:
            # 已是 Anthropic 扁平形态
            out.append(
                {
                    "name": tool.get("name", ""),
                    "description": tool.get("description", ""),
                    "input_schema": tool.get("input_schema", tool.get("parameters", {})),
                }
            )
    return out


def _translate_tool_choice_to_anthropic(tool_choice: Any) -> dict[str, Any] | None:
    """OpenAI ``tool_choice`` → Anthropic ``tool_choice``。

    映射表：
    - ``"auto"`` / None → ``{"type": "auto"}``（None 时不传字段，由调用方
      决定；这里给 None 表示"不传"）
    - ``"none"`` → ``None``（调用方不传 tool_choice 字段；Anthropic 表达
      "不调工具"的方式是不传或传 ``{"type": "none"}``，后者较新）
    - ``"required"`` → ``{"type": "any"}``
    - ``{"type": "function", "function": {"name": X}}`` →
      ``{"type": "tool", "name": X}``
    """
    if tool_choice is None:
        return None
    if tool_choice == "auto":
        return {"type": "auto"}
    if tool_choice == "none":
        return None
    if tool_choice == "required":
        return {"type": "any"}
    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "function":
            fn = tool_choice.get("function") or {}
            return {"type": "tool", "name": fn.get("name", "")}
    return None


# ---------------------------------------------------------------------------
# 响应方向：Anthropic → OpenAI
# ---------------------------------------------------------------------------


def _translate_response_to_openai(response: Any, *, model: str) -> dict[str, Any]:
    """Anthropic ``Message`` 对象 → OpenAI ``ChatCompletion`` plain dict。

    测试常直接传 dict——本函数对 dict / SDK object 都用 ``_attr`` 兼容访问。
    """
    msg_id = _attr(response, "id") or ""
    msg_model = _attr(response, "model") or model

    content_blocks = _attr(response, "content") or []

    text_parts: list[str] = []
    tool_calls_out: list[dict[str, Any]] = []
    for block in content_blocks:
        btype = _attr(block, "type")
        if btype == "text":
            text_parts.append(_attr(block, "text") or "")
        elif btype == "tool_use":
            input_val = _attr(block, "input") or {}
            tool_calls_out.append(
                {
                    "id": _attr(block, "id") or "",
                    "type": "function",
                    "function": {
                        "name": _attr(block, "name") or "",
                        "arguments": json.dumps(input_val, ensure_ascii=False),
                    },
                }
            )

    # text 拼成单字符串；只 tool_use 没 text → content=None
    content_str: str | None = "".join(text_parts) if text_parts else None
    tool_calls_field: list[dict[str, Any]] | None = (
        tool_calls_out if tool_calls_out else None
    )

    stop_reason = _attr(response, "stop_reason") or "end_turn"
    finish_reason = _STOP_REASON_TO_FINISH_REASON.get(stop_reason, "stop")

    usage_obj = _attr(response, "usage")
    input_tokens = int(_attr(usage_obj, "input_tokens") or 0)
    output_tokens = int(_attr(usage_obj, "output_tokens") or 0)

    message_out: dict[str, Any] = {
        "role": "assistant",
        "content": content_str,
        "tool_calls": tool_calls_field,
    }

    return {
        "id": msg_id,
        "model": msg_model,
        "object": _OBJECT_CHAT_COMPLETION,
        "choices": [
            {
                "index": 0,
                "message": message_out,
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        },
    }


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def _attr(obj: Any, name: str) -> Any:
    """兼容 dict / 具备属性访问 的两种形态。"""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _coerce_text(content: Any) -> str:
    """OpenAI ``content`` 字段宽容降级为字符串。

    - None / 空 → 空串
    - str → 原样
    - list of {type: text, text: ...} block → 拼接 text 字段
    - 其它 → json 序列化（极少见，宽容兜底）
    """
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content)


__all__ = ["AnthropicAdapter"]
