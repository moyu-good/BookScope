"""AgentLoop 的 prompt 版本目录。

所有 system prompt / format hint 都以 Markdown 文件形式存放在本目录下，
命名约定 ``<purpose>_v<n>.md``（ADR-002 §10）。禁止在代码里硬编码长
prompt；切换实验版本只改 AgentLoop 读取的文件名。
"""
