// 演示模式的样本数据 —— 全部来自把 BookScope 真跑一遍公有领域《三国演义》后捕获的真实响应。
// 🛑 绝不手编引用：这里每一条引用都是真实核验过的（verified=true，带章节 + 原文 snippet）。
// 由 scripts/capture_demo_fixtures.py 跑书后生成 captured-fixtures.json，这里只做装载。
//
// 键格式："<METHOD> <pathname>"，对应前端各组件的 fetch 调用。

import captured from "./captured-fixtures.json";

const data = captured as {
  json: Record<string, unknown>;
  sse: Record<string, string>;
  meta?: Record<string, unknown>;
};

/** 普通 JSON 接口的捕获响应。 */
export const jsonFixtures: Record<string, unknown> = data.json ?? {};

/** SSE 接口录制的原始响应体（保留 event:/data: ...\n\n 框架），逐事件回放。 */
export const sseFixtures: Record<string, string> = data.sse ?? {};
