"""1.2.1 验:book-first 让整本书前缀跨功能共享 DeepSeek 前缀缓存。

机制:每个「整本进上下文」功能原本按 ``功能指令 + 书`` 拼 system,指令在前→前缀
在指令处就分叉→书(占输入 95%+)进不了公共前缀→每个功能都把整本书当 cache-miss
重付。修法 book-first(:func:`build_longctx_system`):前导 + 书在前(byte 一致),功能
指令挪到书后。

本 probe 背靠背跑 3 个**不同功能指令**(长上下文答题 / 人物关系图 / 节奏曲线),
同一本书,直调 adapter(绕开 L2,measure 真·DeepSeek 服务端前缀缓存):

- call 1(冷):书是新前缀,基本全 miss。
- call 2 / 3(不同功能指令):书前缀应命中→hit ≈ 书 token 数→命中率冲 ≥90%。

key + 书路径只走运行时 env(DEEPSEEK_API_KEY / BOOKSCOPE_SMOKE_EPUB),不硬编、不入库。
"""

from __future__ import annotations

import os
import sys
import time

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass


def main() -> int:
    from bookscope.agent._internal.longctx_system import (
        BOOK_DELIMITER,
        LONGCTX_PREAMBLE,
        build_longctx_system,
    )
    from bookscope.agent.backends.r0_assembler import R0BookAssembler
    from bookscope.agent.character_graph import _PERSON_SYSTEM_INSTRUCTION
    from bookscope.agent.long_context import _LONGCTX_SYSTEM_INSTRUCTION
    from scripts.smoke_test_r1 import (  # type: ignore[import-not-found]
        _build_adapter_and_model,
        _load_book_session,
    )

    if not os.environ.get("DEEPSEEK_API_KEY", "").strip():
        print("ERROR: 没有 DEEPSEEK_API_KEY(.env)")
        return 1

    adapter, model = _build_adapter_and_model("deepseek")
    print(f"[cache] provider=deepseek model={model}")
    book, chunks, kg, vector_store = _load_book_session()
    assembler = R0BookAssembler(
        book_text=book, chunks=chunks, knowledge_graph=kg, session_vector_store=vector_store
    )
    full_text = assembler._book_text.raw_text  # noqa: SLF001
    print(f"[cache] 全书 {len(full_text)} 字符")

    # 节奏曲线指令(就地写个有别于上两个的功能指令,够触发"不同功能"即可)。
    _PACING_INSTRUCTION = (
        "请按章节梳理全书叙事节奏的张弛起伏,只依据原文。严格输出 JSON:"
        '{"points": [{"chapter": 章节号整数, "tension": 紧张度1到5整数, '
        '"note": "该章节奏的一句话说明", "evidence": "原文逐字片段"}]}'
    )

    features = [
        ("长上下文答题", _LONGCTX_SYSTEM_INSTRUCTION),
        ("人物关系图", _PERSON_SYSTEM_INSTRUCTION),
        ("节奏曲线", _PACING_INSTRUCTION),
    ]

    # 结构自检:三个 system 的「前导 + 书」段必须 byte 一致(公共前缀起点)。
    common_prefix = LONGCTX_PREAMBLE + BOOK_DELIMITER + full_text
    for name, instr in features:
        sysmsg = build_longctx_system(full_text, instr)
        if not sysmsg.startswith(common_prefix):
            print(f"[cache] 结构自检失败:{name} 的 system 不以「前导+书」公共前缀开头")
            return 2
    print(f"[cache] 结构自检通过:3 功能共享 {len(common_prefix)} 字符公共前缀(前导+书)")

    print("\n[cache] 背靠背跑 3 个不同功能(直调 adapter,绕 L2)...\n")
    rows: list[tuple[str, int, int, float]] = []
    for i, (name, instr) in enumerate(features, start=1):
        system = build_longctx_system(full_text, instr)
        t0 = time.monotonic()
        resp = adapter.messages_create(
            model=model,
            system=system,
            tools=[],
            messages=[{"role": "user", "content": "请开始。"}],
            max_tokens=256,
            temperature=0.0,
        )
        dt = time.monotonic() - t0
        usage = resp.get("usage", {})
        hit = int(usage.get("prompt_cache_hit_tokens", 0) or 0)
        miss = int(usage.get("prompt_cache_miss_tokens", 0) or 0)
        denom = hit + miss
        rate = hit / denom * 100 if denom else 0.0
        rows.append((name, hit, miss, rate))
        print(
            f"[cache] call{i} {name:8s} {dt:5.0f}s  hit={hit:>8d} miss={miss:>8d} "
            f"命中率={rate:5.1f}%"
        )

    print("\n=== 结论 ===")
    # call 1 冷写缓存;判据看 call 2 起的稳态命中率(目标 ≥90%)。
    steady = [r for r in rows[1:]]
    if steady:
        avg = sum(r[3] for r in steady) / len(steady)
        ok = all(r[3] >= 90.0 for r in steady)
        print(f"call 2 起(不同功能)稳态命中率均值 = {avg:.1f}%  目标 ≥90% → {'达标 ✅' if ok else '未达标 ❌'}")
        print("说明:call 2/3 用的是和 call 1 不同的功能指令,书前缀仍命中 → 跨功能共享成立。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
