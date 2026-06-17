# BookScope Web — 最小前端

R1 代际的前端入口：单页 React 应用，三件事——上传书、问书、看带原文引用的答案。

## 运行

前置条件：

- Node.js ≥ 20
- 后端 FastAPI 已在 `http://localhost:8000` 跑（项目根：`uvicorn bookscope.api.app:app --reload`）

```bash
cd web
npm install
npm run dev
```

然后打开 `http://localhost:5173`。

`vite.config.ts` 里配了 `/api/*` proxy 到 `http://localhost:8000`，所以浏览器看到的是同源请求，无需 CORS 折腾。

## 工作流

1. **LLM 配置**：选 provider（默认 minimax MiniMax-M2.x），填 API key；可选 model 与 base_url
2. **上传书籍**：选 epub/txt/pdf，填书名，点"上传并抽取 KG"——**这一步真跑 `MinimalKGExtractor`，大书可能几分钟**
3. **问书**：session 建好后下方出现问答区；输入问题，agent 会在真书上做多轮 tool use 后给出带 citation 的答案

## BYOK 与隐私

- API key **只存在内存**（React state），刷新页面即丢
- 不写 localStorage / cookie / 后端
- 上传的书存在后端 `data/sessions/<session_id>/`（ADR-005 方案 A）

## 技术栈

- React 19 + TypeScript 5
- Vite 6
- Tailwind v4（用 `@tailwindcss/vite` plugin + CSS-first `@theme` 配置）

## 设计取向

避免 "默认 tailwind 模板" 观感：
- 书页暖白背景 + 朱砂红 accent（章节序号 / 引用边 / 按钮）
- 中文优先字体栈（PingFang / Noto CJK / Source Han），正文与引用用衬线
- 中式段落序号（壹/贰/叁）而非 1/2/3

改造空间：颜色、字体、版式都在 `src/index.css` 的 `@theme` 里，改一行就能换整套视觉。

## 构建

```bash
npm run build
# 产物在 dist/，可用任何静态 server 托管
# 生产环境记得把 /api/* 反向代理到真后端
```

## 关联文档

- `../docs/architecture-decisions/001-r1-agent-tool-interfaces.md`
- `../docs/architecture-decisions/004-upload-endpoint-strategy.md`
- `../docs/architecture-decisions/005-book-session-persistence.md`
- `../docs/architecture-decisions/006-local-ml-api-only.md`
- `../docs/internal/STATE.md`
