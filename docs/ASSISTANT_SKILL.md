# 把 BookScope 当作 AI 助手的 Tool / Skill 使用

BookScope 的定位是**工具/插件/辅助 skill**，不是让用户去敲 CLI 的产品。
AI 助手（如 Claude / GPT / 本地 agent）可以通过统一的工具调用入口，把
“读长文档、核验引用、跨文本对照”变成自己的一项能力。

## 工具清单

机器可读清单（OpenAI function calling 风格）在：

- `bookscope/tools_manifest.json`
- 或运行时 `GET /api/tools/manifest`

当前工具：

| 工具名 | 作用 |
| --- | --- |
| `bookscope_import` | 导入本地文件/文件夹，返回 session_id |
| `bookscope_report` | 生成结构版 HTML 书鉴报告 |
| `bookscope_ask` | 对书提问（无 key 自动本地检索） |
| `bookscope_search` | 文件夹跨书本地检索 |
| `bookscope_stats` | 统计书库规模 |
| `bookscope_catalog` | 生成 HTML 书库目录 |
| `bookscope_cross` | 两个文件直接出跨文本对照 HTML 报告（需要 LLM key） |

## 调用方式

AI 助手只需调用一个端点：

```bash
POST /api/tools/invoke
Content-Type: application/json

{
  "tool": "bookscope_search",
  "arguments": {
    "path": "/path/to/books",
    "query": "市场与政府"
  }
}
```

也可以直接调用具体端点：

```bash
POST /api/tools/import    {"path": "/path/to/book.epub"}
POST /api/tools/report    {"path": "/path/to/book.epub"}
POST /api/tools/ask-local {"session_id": "...", "question": "..."}
POST /api/tools/search    {"path": "/path/to/books", "query": "..."}
POST /api/tools/stats     {"path": "/path/to/books"}
POST /api/tools/catalog   {"path": "/path/to/books", "out": "/tmp/catalog"}
```

## 接入 AI 助手的建议

1. 把 `bookscope/tools_manifest.json` 作为 function/tool schema 注入助手。
2. 助手根据用户意图选择工具，把参数通过 `/api/tools/invoke` 发给本地 BookScope。
3. 返回结果可以是 HTML、JSON 或原文片段，助手再组织成自然语言回复。

这样 BookScope 就变成了助手的一项“辅助 skill”，而不是一个需要用户学习的 CLI。
