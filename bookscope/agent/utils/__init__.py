"""AgentLoop / question_processor / reviewer 三家共用的小工具集。

跨模块复用的纯函数都进这里。能在这层共享是为了让 r1 / r2 / 未来的 r3 不
重复写一遍同样的 JSON 剥皮、think 块剥离、autofix 等惯例处理。
"""

from bookscope.agent.utils.json_parsing import (
    autofix_control_chars_in_strings,
    autofix_stray_apostrophe_string_closer,
    autofix_unescaped_answer_quotes,
    autofix_unescaped_quotes_in_all_string_values,
    extract_first_json_object,
    parse_final_answer,
    strip_code_fence,
)

__all__ = [
    "autofix_control_chars_in_strings",
    "autofix_stray_apostrophe_string_closer",
    "autofix_unescaped_answer_quotes",
    "autofix_unescaped_quotes_in_all_string_values",
    "extract_first_json_object",
    "parse_final_answer",
    "strip_code_fence",
]
