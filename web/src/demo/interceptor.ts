// 演示模式 fetch 拦截器：VITE_DEMO_MODE=1 时装上，把所有 /api/* 请求改成返回
// 打包好的真实样本数据，不连后端。这样 GitHub Pages 的纯静态 demo 也能展示全部功能。
//
// - 普通 JSON 接口：按 "<METHOD> <pathname>" 查 jsonFixtures，返回捕获的真实响应。
// - SSE 接口（agent/ask/stream 等）：回放录制的原始 SSE 字节，逐事件吐出，保留"实时在跑"的观感。
// 非 /api 请求一律放行到真实 fetch。

import { jsonFixtures, sseFixtures } from "./fixtures";

const SSE_PATHS = new Set(["/api/agent/ask/stream", "/api/books/upload/stream"]);

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function reqInfo(input: RequestInfo | URL, init?: RequestInit): { url: string; method: string } {
  let url: string;
  let method = init?.method;
  if (typeof input === "string") url = input;
  else if (input instanceof URL) url = input.toString();
  else {
    url = input.url;
    method = method ?? input.method;
  }
  return { url, method: (method ?? "GET").toUpperCase() };
}

export function installDemoFetch(): void {
  const realFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const { url, method } = reqInfo(input, init);
    let pathname = url;
    try {
      pathname = new URL(url, window.location.origin).pathname;
    } catch {
      /* 相对/异常 URL 原样当 path */
    }

    if (!pathname.startsWith("/api/")) return realFetch(input, init);

    // 留点延迟，让进度/动画有"在干活"的观感
    await sleep(350 + Math.random() * 450);

    if (SSE_PATHS.has(pathname)) {
      const raw = sseFixtures[`${method} ${pathname}`] ?? "";
      const chunks = raw.split("\n\n").filter((c) => c.trim().length > 0);
      const stream = new ReadableStream<Uint8Array>({
        async start(controller) {
          const enc = new TextEncoder();
          for (const chunk of chunks) {
            controller.enqueue(enc.encode(chunk + "\n\n"));
            await sleep(220);
          }
          controller.close();
        },
      });
      return new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      });
    }

    // 关系编年端点按请求体分支：有 pair → 那对的编年，无 pair → 全员清单。
    // 拦截器本来只认 "METHOD 路径"、不看 body，这里给这一个端点补看 pair_a/pair_b。
    if (pathname === "/api/agent/relationship-timeline") {
      let pairA: unknown;
      let pairB: unknown;
      try {
        const parsed = init?.body ? JSON.parse(init.body as string) : {};
        pairA = (parsed as Record<string, unknown>).pair_a;
        pairB = (parsed as Record<string, unknown>).pair_b;
      } catch {
        /* 无 body / 解析失败 → 当全员清单走 */
      }
      if (typeof pairA === "string" && typeof pairB === "string") {
        const chronicles = (jsonFixtures[`${method} ${pathname}#chronicles`] ??
          {}) as Record<string, unknown>;
        const key = [pairA, pairB].sort().join("|");
        const cp = chronicles[key] ?? {
          relations: [],
          pairs: [],
          scanned: false,
          book_session_id: "demo",
          trace: {},
        };
        return new Response(JSON.stringify(cp), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      // 无 pair → 落到下面通用查找，返全员清单
    }

    const body = jsonFixtures[`${method} ${pathname}`];
    if (body === undefined) {
      return new Response(
        JSON.stringify({ detail: "演示模式下该功能暂无样本数据" }),
        { status: 404, headers: { "Content-Type": "application/json" } },
      );
    }
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
}
