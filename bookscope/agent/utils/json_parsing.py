"""LLM 自由文本里剥第一段顶层 JSON object + 一组 autofix 修破 JSON 的纯函数。

历史：

- 第 35 轮第三波（commit b33e985）先抽出 ``extract_first_json_object`` —— 把
  loop.py / question_processor.py / reviewer.py 三处等价的"括号平衡剥 JSON"
  实现归并到这层
- Sprint 7 第一步（本次）再抽 ``_strip_code_fence`` / 4 个 ``_autofix_*`` /
  ``parse_final_answer`` —— reviewer / loop_r2 / fast_path 三处原本从
  ``bookscope.agent.loop`` 里 import 这些 helper，把它们跟 r1 ``loop.py``
  解耦后才能 git rm r1 runtime

本模块只引标准库（``json`` / ``re``），不反向 import 任何 ``bookscope.agent``
子模块——保持纯净避免 import 循环。

Sprint 7（2026-05-15）r1 ``loop.py`` 已 ``git rm``，原本转调到这里的私有别名
（``_strip_code_fence`` / ``_autofix_*`` / ``_extract_first_json_object``）也
一并消失。现在 reviewer / loop_r2 / fast_path 直接 import 本模块公共函数，
不再有 r1 兼容层。
"""

from __future__ import annotations

import json
import re
from typing import Any

from bookscope.agent.errors import LLMFormatError

__all__ = [
    "autofix_control_chars_in_strings",
    "autofix_fullwidth_quote_string_closer",
    "autofix_stray_apostrophe_string_closer",
    "autofix_trailing_commas",
    "autofix_unescaped_answer_quotes",
    "autofix_unescaped_quotes_in_all_string_values",
    "extract_first_json_object",
    "parse_final_answer",
    "salvage_closed_objects",
    "strip_code_fence",
]


_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*(.*?)\s*```$", re.DOTALL)

_AUTOFIX_ANSWER_HEAD_RE = re.compile(r'"answer"\s*:\s*"')
_AUTOFIX_CITATIONS_TAIL_RE = re.compile(r'"\s*,\s*"citations"\s*:')

_JSON_STRUCTURAL_AFTER_QUOTE = frozenset(",}]:")
_JSON_WHITESPACE = frozenset(" \t\n\r")

_STRAY_APOS_CLOSER_RE = re.compile(r"'(\s*[,}]\s*[\n\r])")

_FULLWIDTH_QUOTE_CLOSER_RE = re.compile(r"[“”](\s*[,\]}])")


def extract_first_json_object(text: str) -> str | None:
    """扫第一个 ``{...}`` JSON object 子串；找不到返 ``None``。

    实现要点：

    - 花括号深度计数；字符串内部的 ``{`` / ``}`` 不计入深度（避免被 value 里的
      字面量误导）
    - 反斜杠转义在字符串内逐字符跳过，``\\"`` 不算字符串结束
    - 从第一个 ``{`` 起算深度——前置解释文字会被一并跳过
    - 找到第一段配平的 ``{...}`` 立刻返回，后续多余文本忽略

    Args:
        text: LLM 自由文本，可能在 JSON 前后裹解释 / think 块 / 多余引号。

    Returns:
        从首个 ``{`` 到对应 ``}`` 的子串；未找到配平结构则 ``None``。
    """
    depth = 0
    start_idx: int | None = None
    in_string = False
    escape = False
    for idx, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start_idx = idx
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start_idx is not None:
                    return text[start_idx : idx + 1]
    return None


def strip_code_fence(text: str) -> str:
    """如果 LLM 把 JSON 包在 ```json ... ``` 里，剥掉围栏。

    原从 r1 ``loop.py`` 抽出 · Sprint 7 第一步 · audit §7 推荐方案 A。
    """
    m = _CODE_FENCE_RE.match(text.strip())
    if m:
        return m.group(1).strip()
    return text


def salvage_closed_objects(text: str, key: str) -> list[Any] | None:
    """从 ``text`` 里 ``key`` 指向的数组中抠出已闭合的完整 ``{...}`` 对象（截断抢救通用件）。

    flash 把 reasoning_content 算进 max_tokens，结构化输出一大就可能被截断成半截 JSON，
    整段 ``json.loads`` 必败。这里定位 ``key`` 后的 ``[``，括号匹配逐个抠完整对象（跳过
    字符串内的括号、按 ``\\`` 处理转义），最后那个没闭合的对象丢掉。拼出的部分结果比整段
    丢掉好——人物图 / 时间线 / 伏笔弧等十余处结构化抽取共用这一份抢救逻辑。

    Args:
        text: 可能被截断的 LLM JSON 输出。
        key: 数组字段名，**含引号**，如 ``'"edges"'`` / ``'"chapters"'``。

    Returns:
        已闭合对象的原始 ``list``（未 coerce）；``key`` 找不到 / 没有 ``[`` / 一个完整对象
        都没抠到时返 ``None``。
    """
    idx = text.find(key)
    if idx == -1:
        return None
    start = text.find("[", idx)
    if start == -1:
        return None
    raw_items: list[Any] = []
    i = start + 1
    n = len(text)
    while i < n:
        while i < n and text[i] not in "{]":  # 跳到下一个对象起点；遇 ] 收工
            i += 1
        if i >= n or text[i] == "]":
            break
        depth = 0
        in_str = False
        esc = False
        closed = False
        j = i
        while j < n:  # 括号匹配抠一个完整 {...}，跳过字符串内的括号
            ch = text[j]
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = not in_str
            elif not in_str:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        j += 1
                        closed = True
                        break
            j += 1
        if not closed:
            break  # 最后一个对象被截断 → 停
        try:
            raw_items.append(json.loads(text[i:j]))
        except json.JSONDecodeError:
            pass
        i = j
    return raw_items or None


def autofix_unescaped_quotes_in_all_string_values(json_text: str) -> str | None:
    """通用 autofix —— 状态机扫描，对任意字符串 value 内部的裸 ASCII `"` 转义。

    原从 r1 ``loop.py`` 抽出 · Sprint 7 第一步 · audit §7 推荐方案 A。

    启发式判定：处于 JSON 字符串 value 内部时遇到 `"`，peek 后续非空白
    字符；若是 ``,``/``}``/``]``/``:`` 或 EOF，视为字符串真结束；否则
    视为裸内嵌，插入 `\\` 转义。

    与定向的 :func:`autofix_unescaped_answer_quotes` 的关系：
    - 定向版本专修 loop.py 的 ``{"answer": ..., "citations": ...}`` 顶层
      结构，**快且精准**，位置靠 regex 定位
    - 通用版本不依赖 schema，适用任意嵌套字段（如 reviewer 输出里
      ``per_dimension_comment.*`` / ``overall`` / ``top_issues[*]`` /
      ``single_most_valuable_improvement``）
    - 调用链：先试定向；返回 None 时退到通用

    **已知 limitation**：纯英文文本中 `"word", next` 这样的场景会让通用
    autofix 误判（"word" 后的 `",` 看起来像真结束）。本项目主用场景是
    中文叙事答复（中文有全角标点 `，`/`。`/`）`，误判概率极低），
    所以接受这个 trade-off。未来若要支持英文作家题，需切到真正的
    lenient JSON parser（json5 / demjson3）。

    返回值：
    - 修复后的 JSON 文本（至少有一处转义被插入）
    - ``None`` 表示原文里没有裸引号可修（避免下游二次解析）
    """
    out: list[str] = []
    in_string = False
    fixed = False
    i = 0
    n = len(json_text)
    while i < n:
        ch = json_text[i]
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            i += 1
            continue
        # in_string
        if ch == "\\":
            # 复制转义对（比如 \" / \\ / \n）
            out.append(ch)
            if i + 1 < n:
                out.append(json_text[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch == '"':
            # peek 下一个非空白字符
            j = i + 1
            while j < n and json_text[j] in _JSON_WHITESPACE:
                j += 1
            if j >= n or json_text[j] in _JSON_STRUCTURAL_AFTER_QUOTE:
                # 真结束
                in_string = False
                out.append(ch)
                i += 1
            else:
                # 裸内嵌，转义
                out.append("\\")
                out.append(ch)
                fixed = True
                i += 1
            continue
        out.append(ch)
        i += 1
    if not fixed:
        return None
    return "".join(out)


def autofix_control_chars_in_strings(json_text: str) -> str | None:
    """通用 autofix —— string value 内裸 ASCII control char (\\n / \\r / \\t)
    转成 ``\\n`` / ``\\r`` / ``\\t`` escape。

    原从 r1 ``loop.py`` 抽出 · Sprint 7 第一步 · audit §7 推荐方案 A。

    背景：MiniMax-M2.x 等 reasoning model 在生成多行 JSON 字符串时，常把
    raw newline 直接写进 ``"..."`` 内部，json.loads 报 ``Invalid control
    character at: line N column M``。reviewer 的长 dimension 评语尤其
    多见。

    与 ``autofix_unescaped_quotes_in_all_string_values`` 串联使用：
    quote 修先做 → 仍 parse 失败再试 control-char 修 → 再 parse。

    返回值：
    - 修复后的 JSON 文本（至少有一处 control char 被 escape）
    - ``None`` 表示原文里没 string-内 control char（避免下游二次解析）
    """
    out: list[str] = []
    in_string = False
    fixed = False
    i = 0
    n = len(json_text)
    while i < n:
        ch = json_text[i]
        if not in_string:
            if ch == '"':
                in_string = True
            out.append(ch)
            i += 1
            continue
        # in_string
        if ch == "\\":
            out.append(ch)
            if i + 1 < n:
                out.append(json_text[i + 1])
                i += 2
            else:
                i += 1
            continue
        if ch == '"':
            in_string = False
            out.append(ch)
            i += 1
            continue
        if ch == "\n":
            out.append("\\n")
            fixed = True
        elif ch == "\r":
            out.append("\\r")
            fixed = True
        elif ch == "\t":
            out.append("\\t")
            fixed = True
        else:
            out.append(ch)
        i += 1
    if not fixed:
        return None
    return "".join(out)


def autofix_trailing_commas(json_text: str) -> str | None:
    """通用 autofix —— 删掉 object / array 收尾前的 trailing comma。

    起源：exp004 anshi run3 q1（2026-06-10，docs/internal/experiments/004 §9.3）。
    DeepSeek reviewer 在 ``per_dimension_comment`` 最后一个键值对后多写了
    一个逗号，严格 ``json.loads`` 报 ``Expecting property name enclosed in
    double quotes``，原有 autofix 链（定向引号 / 通用引号 / control char）
    全部不命中。

    实现与 :func:`autofix_control_chars_in_strings` 同款状态机：跳过字符串
    内部（含 ``\\`` 转义对），只在结构层遇到 ``,`` 时 peek 后续非空白字符，
    若是 ``}`` 或 ``]`` 则丢弃这个逗号。字符串 value 里的 ``,}`` 字面量
    不受影响。

    返回值：
    - 修复后的 JSON 文本（至少一个 trailing comma 被删）
    - ``None`` 表示原文里没有 trailing comma（避免下游二次解析）
    """
    out: list[str] = []
    in_string = False
    fixed = False
    i = 0
    n = len(json_text)
    while i < n:
        ch = json_text[i]
        if in_string:
            if ch == "\\":
                out.append(ch)
                if i + 1 < n:
                    out.append(json_text[i + 1])
                    i += 2
                else:
                    i += 1
                continue
            if ch == '"':
                in_string = False
            out.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == ",":
            # peek 下一个非空白字符
            j = i + 1
            while j < n and json_text[j] in _JSON_WHITESPACE:
                j += 1
            if j < n and json_text[j] in "}]":
                # trailing comma——丢弃
                fixed = True
                i += 1
                continue
        out.append(ch)
        i += 1
    if not fixed:
        return None
    return "".join(out)


def autofix_stray_apostrophe_string_closer(json_text: str) -> str | None:
    """通用 autofix —— 模型用 ASCII `'` 误代替 `"` 收束 string value。

    原从 r1 ``loop.py`` 抽出 · Sprint 7 第一步 · audit §7 推荐方案 A。

    背景：MiniMax-M2.x reviewer 偶发把多行 dimension 评语的收束符写成
    bare apostrophe（``"...内容？',\\n``），导致 string 没真正闭合，
    后续 ``extract_first_json_object`` 的 `"`-平衡跑乱、整段定位失败。

    匹配模式刻意收紧到"`'` + 可选空白 + `,` 或 `}` + 可选空白 + 换行"
    —— 这是 JSON 结构上 `"` 必出现的位置；中文叙事里偶发的
    单引号一般不会紧跟 `,\\n` 出现。误伤面极小。

    Returns:
        修复后的 JSON 文本（至少一处替换发生）；原文无此模式时 ``None``。
    """
    if "'" not in json_text:
        return None
    fixed, count = _STRAY_APOS_CLOSER_RE.subn(r'"\1', json_text)
    if count == 0:
        return None
    return fixed


def autofix_fullwidth_quote_string_closer(json_text: str) -> str | None:
    """通用 autofix —— 模型用全角引号 ``”``/``“`` 误代替 ``"`` 收束 string value。

    起源：exp004 zhinei run2 q5（2026-06-10，docs/internal/experiments/004 §9.3）。
    DeepSeek reviewer 把 ``top_issues`` 第二条字符串的收束符写成全角 ``”``，
    string 没真正闭合，``extract_first_json_object`` 的 `"`-平衡跑乱、整段
    定位失败（错误现象是 "no valid JSON object" 而非 parse failed）。

    与 :func:`autofix_stray_apostrophe_string_closer` 同族：都是"错字符
    出现在 JSON 结构上 `"` 必出现的位置"。匹配模式同样收紧——全角引号 +
    可选空白 + ``,``/``]``/``}``。中文叙事里全角引号后面跟的是全角标点或
    继续行文，紧跟 ASCII 结构符的情况只在 JSON 收束位出现；字符串内部
    正常成对的 ``“...”`` 后面是 ASCII `"`（真收束符），不会命中。

    Returns:
        修复后的 JSON 文本（至少一处替换发生）；原文无此模式时 ``None``。
    """
    if "”" not in json_text and "“" not in json_text:
        return None
    fixed, count = _FULLWIDTH_QUOTE_CLOSER_RE.subn(r'"\1', json_text)
    if count == 0:
        return None
    return fixed


def autofix_unescaped_answer_quotes(json_text: str) -> str | None:
    """针对 astron-code 等 code 模型在 answer 字段裸用 ASCII `"` 的破裂修复。

    原从 r1 ``loop.py`` 抽出 · Sprint 7 第一步 · audit §7 推荐方案 A。

    前提：顶层 schema 固定为 ``{"answer": "...", "citations": [...]}``，且字段顺序
    answer 先于 citations（citation_format_v1 明文要求）。本函数用这个位置约束
    定位 answer 字符串值的起止边界，然后把中间所有未经 `\\` 转义的裸 ASCII `"`
    补上转义，返回修复后的 JSON 文本。

    返回 ``None`` 表示"无法定位 answer 值的边界"，调用方据此抛更明确的错误。

    注意：这是针对单一失败模式的定向 autofix，不是通用 JSON 修复器。只处理
    answer 字段内的裸引号；不尝试修 citations 字段内的类似问题（因为 citations
    是 tool 原文 snippet 回传，副管理已要求 LLM "不得改写"，破裂概率极低）。
    """
    head = _AUTOFIX_ANSWER_HEAD_RE.search(json_text)
    if head is None:
        return None
    value_start = head.end()
    tail = _AUTOFIX_CITATIONS_TAIL_RE.search(json_text, value_start)
    if tail is None:
        return None
    value_end = tail.start()  # 指向 answer 值闭合的 `"` 位置
    original_value = json_text[value_start:value_end]
    # 把所有未经 `\` 转义的 ASCII `"` 改为 `\"`
    fixed_value = re.sub(r'(?<!\\)"', r'\\"', original_value)
    if fixed_value == original_value:
        # 没东西可修；避免多此一举
        return None
    return json_text[:value_start] + fixed_value + json_text[value_end:]


def _coerce_chapter(value: object) -> int:
    """把模型自报的 chapter 强转成 int（宽松模式用）。

    flash 偶发把章号写成字符串（``"第5章"`` / ``"5"`` / ``"5-6"``）或省略。
    长上下文路里章号本来就会被 ``run_long_context`` 的 chunk-match 命中后覆盖，
    所以这里只求不报错：能抠出第一个整数就用，抠不出退 0。``bool`` 是 int 子类，
    显式排除免得 ``True`` 被当 1。
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        m = re.search(r"\d+", value)
        return int(m.group(0)) if m else 0
    return 0


def _coerce_citations_lenient(raw: object) -> list[dict]:
    """宽松收编 citations：chapter str→int 强转、坏 citation 单条丢不整条废。

    丢的唯一硬条件是 **snippet 缺失 / 非字符串 / 空**——snippet 是证据本体，
    没它这条 citation 无从核验。chapter 一律 coerce（见 :func:`_coerce_chapter`）。
    """
    if not isinstance(raw, list):
        return []
    out: list[dict] = []
    for cit in raw:
        if not isinstance(cit, dict):
            continue
        snippet = cit.get("snippet")
        if not isinstance(snippet, str) or not snippet:
            continue
        out.append({**cit, "chapter": _coerce_chapter(cit.get("chapter")), "snippet": snippet})
    return out


def parse_final_answer(
    text: str, *, lenient: bool = False
) -> tuple[str, list[dict]]:
    """从 LLM 返回的最后一段文本里抽出 ``answer`` / ``citations``。

    原从 r1 ``loop.py`` 的 ``_R1AgentLoop._parse_final_answer`` instance method
    抽出 · Sprint 7 第一步 · audit §4.4：``loop_r2.py:360`` 原本直接调
    ``_R1AgentLoop._parse_final_answer(self, final_text)`` 让 r2 复用 r1 的
    JSON parse + autofix 链；本函数把它独立成纯函数，r1 / r2 都走这层，
    不再借道 ``_R1AgentLoop`` classmethod。

    method 实现里完全不使用 ``self``——只读 ``text`` 参数、调本模块内的
    autofix 函数——所以提到模块顶层是 zero-behavior 改动。

    允许 LLM 回复被 markdown 代码围栏包裹；也允许回复前后带解释文本，
    此时会尝试定位第一段合法 JSON 对象。

    Raises:
        LLMFormatError: 任何解析或校验失败。
    """
    raw = text.strip()
    if not raw:
        raise LLMFormatError("LLM final message was empty")

    candidate = strip_code_fence(raw)
    # 尝试定位第一个 '{' 到配对 '}' 的 JSON 对象
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        json_slice = extract_first_json_object(candidate)
        if json_slice is None:
            # 全角引号 `”` 误代替 `"` 收束 string 时，`"`-平衡跑乱、
            # 定位必然失败（exp004 zhinei run2 q5 同病）；修后重试一次。
            fw_fixed = autofix_fullwidth_quote_string_closer(candidate)
            if fw_fixed is not None:
                json_slice = extract_first_json_object(fw_fixed)
        if json_slice is None:
            raise LLMFormatError(
                "LLM final message is not valid JSON and contains no JSON object"
            ) from None
        try:
            obj = json.loads(json_slice)
        except json.JSONDecodeError:
            # 兜底：astron-code 等模型在字符串 value 里裸用 ASCII 直引号
            # 引用原文（违反 citation_format_v1 硬约束），导致 JSON 破裂。
            # 先试定向修复（只修 answer 字段，快且精准），再退到通用
            # 状态机扫描（修任意字段内的裸引号）。
            autofixed = autofix_unescaped_answer_quotes(json_slice)
            if autofixed is None:
                autofixed = autofix_unescaped_quotes_in_all_string_values(
                    json_slice,
                )
            if autofixed is None:
                autofixed = autofix_fullwidth_quote_string_closer(json_slice)
            if autofixed is None:
                autofixed = autofix_trailing_commas(json_slice)
            if autofixed is None:
                raise LLMFormatError(
                    "failed to parse JSON and autofix did not apply"
                ) from None
            try:
                obj = json.loads(autofixed)
            except json.JSONDecodeError as exc:
                raise LLMFormatError(
                    f"failed to parse JSON: {exc}"
                ) from exc

    if not isinstance(obj, dict):
        raise LLMFormatError("LLM final JSON is not an object")
    if "answer" not in obj:
        raise LLMFormatError("LLM final JSON missing 'answer' field")

    if lenient:
        # 宽松模式（长上下文路）：answer 必须 str；citations 走 coerce + 坏的单条丢，
        # 章号下面会被 chunk-match 覆盖、无需严格 int。全丢光才算失败（触发重试/回退）。
        answer = obj["answer"]
        if not isinstance(answer, str):
            raise LLMFormatError("'answer' field must be a string")
        citations = _coerce_citations_lenient(obj.get("citations"))
        if not citations:
            raise LLMFormatError("no usable citation after lenient coercion")
        return answer, citations

    if "citations" not in obj:
        raise LLMFormatError("LLM final JSON missing 'citations' field")

    answer = obj["answer"]
    citations = obj["citations"]

    if not isinstance(answer, str):
        raise LLMFormatError("'answer' field must be a string")
    if not isinstance(citations, list):
        raise LLMFormatError("'citations' field must be a list")
    if len(citations) == 0:
        raise LLMFormatError("'citations' list must contain at least one entry")
    for idx, cit in enumerate(citations):
        if not isinstance(cit, dict):
            raise LLMFormatError(f"citation[{idx}] is not an object")
        if "chapter" not in cit:
            raise LLMFormatError(f"citation[{idx}] missing 'chapter'")
        if "snippet" not in cit:
            raise LLMFormatError(f"citation[{idx}] missing 'snippet'")
        if not isinstance(cit["chapter"], int):
            raise LLMFormatError(f"citation[{idx}].chapter must be int")
        if not isinstance(cit["snippet"], str) or not cit["snippet"]:
            raise LLMFormatError(
                f"citation[{idx}].snippet must be a non-empty string"
            )
    return answer, citations
