import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./index.css";

// 演示模式（VITE_DEMO_MODE=1）下，先装上 fetch 拦截器再渲染——必须在任何组件发请求前生效。
// 用动态 import，正常构建里这段是死代码，demo 代码不会进正常 bundle。
async function boot(): Promise<void> {
  if (import.meta.env.VITE_DEMO_MODE === "1") {
    const { installDemoFetch } = await import("./demo/interceptor");
    installDemoFetch();
  }
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void boot();
