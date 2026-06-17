import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev server proxies /api/* to the FastAPI app running on :8000 so the
// browser sees a same-origin URL and CORS stays out of the picture.
// Change target if you run uvicorn on a different port.
// 演示模式：构建用 `vite build --mode demo`，base 走子路径 /BookScope/（GitHub Pages）；
// web/.env.demo 把 VITE_DEMO_MODE=1 注入前端（用打包样本、不连后端）。正常构建 base=/。
export default defineConfig(({ mode }) => ({
  base: mode === "demo" ? "/BookScope/" : "/",
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
}));
