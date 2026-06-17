"""DeepSeek 缓存适配测试（2026-06-11）：固定前缀稳定 + 命中观测.

守护两件事——缓存命中靠"请求固定前缀逐 token 相同"，再被静默破坏就叫：

1. citation_hint 在 system 固定段、不在每题变化的 user message
   （之前和 question 绑一条 user 里，把 17KB 固定块拖成全价新内容）
2. DeepSeek 返回的 prompt_cache_hit/miss_tokens 被累计进 trace
   （之前 adapter 直接丢弃，命中率不可观测）

设计：commit 见 git log `perf(agent): DeepSeek 缓存适配`
"""

from __future__ import annotations

import json
from typing import Any

from bookscope.agent.models import LoopTrace


def _final_json_text(answer: str, citations: list[dict[str, Any]]) -> str:
    return json.dumps({"answer": answer, "citations": citations}, ensure_ascii=False)


class TestCachePrefixStable:
    def test_citation_hint_in_system_not_user(
        self, r2_response_factory, r2_fake_client, make_r2_loop
    ):
        """citation_hint 进 system 固定段；user message 只剩纯问题。"""
        client = r2_fake_client(
            [
                r2_response_factory(
                    content=_final_json_text(
                        "答案", [{"chapter": 1, "snippet": "原文"}]
                    )
                )
            ]
        )
        loop = make_r2_loop(client)
        # 短问题（< 30 字）不触发问题处理引擎，system 即纯固定段
        loop.query("第一章讲了什么")

        system_sent = client.last_kwargs["system"]
        messages_sent = client.last_kwargs["messages"]
        # 引用格式说明在 system（固定前缀），不在 user
        assert loop._citation_format_hint in system_sent
        assert messages_sent[0]["content"] == "第一章讲了什么"
        assert loop._citation_format_hint not in messages_sent[0]["content"]

    def test_fixed_system_identical_across_queries(
        self, r2_response_factory, r2_fake_client, make_r2_loop
    ):
        """两次不同短问题，发出的 system 固定段逐字相同（缓存命中前提）。"""
        sent_systems = []
        for q in ("第一章讲了什么", "第二章讲了什么"):
            client = r2_fake_client(
                [
                    r2_response_factory(
                        content=_final_json_text(
                            "答案", [{"chapter": 1, "snippet": "原文"}]
                        )
                    )
                ]
            )
            loop = make_r2_loop(client)
            loop.query(q)
            sent_systems.append(client.last_kwargs["system"])
        assert sent_systems[0] == sent_systems[1]


class TestCacheObservability:
    def test_accumulate_cache_tokens_from_usage(
        self, r2_fake_client, make_r2_loop
    ):
        """_accumulate_tokens 把 usage 的缓存命中/未命中累计进 trace。"""
        loop = make_r2_loop(r2_fake_client([]))
        trace = LoopTrace(protocol_version="r2")
        resp = {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 50,
                "prompt_cache_hit_tokens": 80,
                "prompt_cache_miss_tokens": 20,
            }
        }
        loop._accumulate_tokens(trace, resp)
        assert trace.cache_hit_tokens == 80
        assert trace.cache_miss_tokens == 20

    def test_cache_tokens_default_zero_without_field(
        self, r2_fake_client, make_r2_loop
    ):
        """非 DeepSeek / 无缓存字段的 usage 不炸，缓存计数保持 0。"""
        loop = make_r2_loop(r2_fake_client([]))
        trace = LoopTrace(protocol_version="r2")
        loop._accumulate_tokens(
            trace, {"usage": {"prompt_tokens": 10, "completion_tokens": 5}}
        )
        assert trace.cache_hit_tokens == 0
        assert trace.cache_miss_tokens == 0
