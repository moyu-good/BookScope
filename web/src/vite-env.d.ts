/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 演示模式：=1 时（GitHub Pages 静态 demo）前端用打包样本数据、不连后端。 */
  readonly VITE_DEMO_MODE?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
