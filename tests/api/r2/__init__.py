"""``tests/api/r2`` —— API 层 r2 路径 mock 测试套。

ADR-007 Migration Plan "测试改造范围"硬要求：Sprint 6 默认从 r1 切到 r2 后，
``tests/api/`` 下原有 22 个 r1 mock 测试由 ``tests/api/conftest.py`` autouse
fixture 锁 r1 兜底；本目录承接 r2 形态的等价测试，autouse 锁 r2。

本目录是范式 / 脚手架——Sprint 6 内只放 1-2 个代表性 r2 mock 测试作为模板，
后续 sprint 按这套 pattern 补齐全套 r2 测试。
"""
