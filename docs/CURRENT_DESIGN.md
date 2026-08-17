# BookScope 当前设计（2026-08 · 唯一权威）

> 本文档是 BookScope 当前开发的唯一设计依据。
> 凡是与本文冲突的旧设计文档，一律视为**已废弃**，只作历史参考，不得据此继续开发。

## 一、产品定义

**BookScope 是一个轻量的本地长文本工具/插件/辅助 skill，不是阅读器，不是平台，不是服务器，也不是一个让用户去学 CLI 的产品。**

- 输入：书 / 公文 / 论文 / 任意长文档（epub / txt / pdf / docx / md）
- 输出：可核验、可交互、可追问的 HTML 报告 + 结构化 JSON 数据
- 运行：本地起轻量服务，作为 AI 助手的 tool/skill 被调用；CLI 只是内部调试/脚本的一种调用方式，不是产品形态；不需要 Docker、不需要公网服务器
- 数据：BYOK，key 只留在浏览器/本地，不经过任何服务器

## 二、核心原则（不可违背）

1. **核验优先**：每条引文回原文逐字核对，对得上才盖「鉴」；推断标「研判」。
2. **渐进交付**：先秒出结构版，后台按章构建深度版，进度实时可见；改哪章只重算哪章。
3. **Tool 不是 Reader**：不做“读着读着”的沉浸阅读器，做“点一下就能用”的分析工具。
4. **书/论文/公文都是数据库**：马恩、论文、小说都只是案例，不是方向本身。
5. **轻量、工具化、适配热门工具**：CLI / REST API / OpenAI 兼容 / Feishu / HTML / JSON，拒绝重部署。
6. **别被旧设计带偏**：遇到旧文档与本文冲突，以本文为准。

## 三、当前技术主线

- Python 3.12 + FastAPI + React 19 + Vite + TypeScript + Tailwind v4
- 默认 DeepSeek `deepseek-v4-flash`，兼容任何 OpenAI 兼容接口
- 章脉缓存（按章粒度）+ 跨文本对照 + 簇关系发现 + 报告工作台
- CLI：`report / prewarm / ask / cross / cluster / import / list / doctor / serve`

## 四、文档状态

| 文档 | 状态 |
| --- | --- |
| `docs/CURRENT_DESIGN.md` | ✅ 当前唯一权威 |
| `docs/ARCHITECTURE.md` | ✅ 当前架构（如与本文冲突，以本文为准） |
| `docs/USER_GUIDE.md` | ✅ 当前用户手册 |
| `docs/architecture-decisions/001~010, 012` | ✅ 仍有效的技术决策 |
| `docs/architecture-decisions/011-hosted-account-backend.md` | ⚠️ 已废弃（托管/Docker 方向，不符合轻量本地工具） |
| `docs/internal/case-study/*` | 🗄️ 历史记录（不是设计指令） |
| `docs/internal/ROADMAP.md` | ⚠️ 历史路线图（含已废弃方向，当前以本文为准） |
| `docs/internal/NORTH_STAR.md` / `WORKFLOW.md` / `ASSESSMENT_20260814.md` | 🗄️ 内部历史工作文档，不是当前设计依据 |

## 五、开发时怎么做

- 新功能先对照本文四条核心原则，不符合就不做。
- 旧文档里出现的“论文垂直”“托管版”“Docker”“沉浸阅读器”等方向，除非本文明确支持，否则视为废弃。
- 每轮开发只以本文 + 代码现状为准。
