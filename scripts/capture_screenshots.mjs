// 截 demo 真功能图给 README 用。连本地跑着的 demo(vite --mode demo,localhost:5173/BookScope/),
// 走"书→鉴→功能"驱动到各可视化,等渲染稳了截图存 docs/images/。
// 用法:先 `cd web && npm run dev -- --mode demo`(或复用已跑的预览),再 `node scripts/capture_screenshots.mjs`。
// 需 chromium:`npx playwright install chromium`。

import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
// playwright 装在 web/node_modules(--no-save 一次性);以 web/ 为基准解析,脚本留 scripts/。
const require = createRequire(join(ROOT, "web", "package.json"));
const { chromium } = require("playwright");
const OUT = join(ROOT, "docs", "images");
const BASE = "http://localhost:5173/BookScope/";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function clickText(page, text, { exact = true } = {}) {
  const loc = page.locator("button", { hasText: text });
  const n = await loc.count();
  for (let i = 0; i < n; i++) {
    const b = loc.nth(i);
    const t = (await b.innerText()).trim();
    if (exact ? t === text : t.includes(text)) {
      if (await b.isVisible()) {
        await b.click();
        return true;
      }
    }
  }
  return false;
}

async function openJian(page) {
  // 回首页 → 点书卡(进阅读器)→ 点「鉴」开浮层
  await page.goto(BASE, { waitUntil: "load", timeout: 60000 });
  await sleep(1500);
  await clickText(page, "三国", { exact: false });
  await sleep(1200);
  await clickText(page, "鉴");
  await sleep(700);
}

async function shoot(page, name) {
  await page.screenshot({ path: join(OUT, name), animations: "disabled" });
  console.log("  存", name);
}

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 2 });

  // ── 星图关系图 ───────────────────────────────────────────────
  console.log("关系图(星图)…");
  await openJian(page);
  await clickText(page, "关系");
  await sleep(500);
  await clickText(page, "关系网");
  await sleep(500);
  await clickText(page, "人物关系图", { exact: false });
  await sleep(15000); // 等 fixture 加载 + 力导向稳定(348 节点 + 防重叠铺开,settle 慢,多给时间)
  await shoot(page, "graph.png");

  // ── 山水叙事曲线 ─────────────────────────────────────────────
  console.log("叙事曲线(山水)…");
  await openJian(page);
  await clickText(page, "逐章曲线");
  await sleep(500);
  await clickText(page, "叙事曲线");
  await sleep(500);
  if (!(await clickText(page, "重新生成"))) await clickText(page, "生成", { exact: false });
  await sleep(4000);
  await shoot(page, "narrative.png");

  // ── 花鸟人物弧 ───────────────────────────────────────────────
  console.log("人物弧线(花鸟)…");
  await openJian(page);
  await clickText(page, "逐章曲线");
  await sleep(500);
  await clickText(page, "人物弧线");
  await sleep(500);
  if (!(await clickText(page, "重新生成"))) await clickText(page, "生成", { exact: false });
  await sleep(4000);
  await shoot(page, "arc.png");

  // ── 叙事流(验动态高:泳道多不挤)─────────────────────────────
  console.log("叙事流…");
  await openJian(page);
  await clickText(page, "叙事流");
  await sleep(500);
  if (!(await clickText(page, "重新生成"))) await clickText(page, "生成", { exact: false });
  await sleep(6000);
  await shoot(page, "flow.png");

  await browser.close();
  console.log("完成。");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
