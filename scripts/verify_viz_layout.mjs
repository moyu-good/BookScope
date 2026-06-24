// 验证 RelationshipTimeline(关系演变)+ ForeshadowArcs(伏笔回收)富数据下的渲染布局。
// preview_screenshot 因永动动画超时、预览无头环境 rAF 被节流(力导向不跑),都验不了;
// 这脚本用 Playwright 真 chromium(会跑 rAF)+ animations:"disabled" 截到稳定帧。
// 用法:先跑着 web-demo(localhost:5173),再 `node scripts/verify_viz_layout.mjs`。
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
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
    if ((exact ? t === text : t.includes(text)) && (await b.isVisible())) {
      await b.click();
      return true;
    }
  }
  return false;
}

async function openJian(page) {
  await page.goto(BASE, { waitUntil: "load", timeout: 60000 });
  await sleep(1500);
  await clickText(page, "三国", { exact: false });
  await sleep(1200);
  await clickText(page, "鉴");
  await sleep(700);
}

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });

  console.log("关系演变(力导向)…");
  await openJian(page);
  await clickText(page, "关系");
  await sleep(400);
  await clickText(page, "关系演变");
  await sleep(400);
  if (!(await clickText(page, "重新生成"))) await clickText(page, "生成", { exact: false });
  await sleep(2500); // 小多图无动画，渲染即稳
  await page.screenshot({ path: join(OUT, "_verify_rel.png"), animations: "disabled" });
  console.log("  存 _verify_rel.png");
  // 下钻:点第一对关系行 → 单对曲线
  await page.evaluate(() => {
    const sm = [...document.querySelectorAll("svg")].find((s) => (s.textContent || "").includes("—"));
    // 行 <g> 才含 polyline(sparkline);轴刻度 <g> 没有。点行内透明热区 rect。
    const row = [...(sm?.querySelectorAll("g") || [])].find((g) => g.querySelector("polyline"));
    const hit = row?.querySelector("rect") || row;
    if (hit) hit.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await sleep(1200);
  await page.screenshot({ path: join(OUT, "_verify_rel_detail.png"), animations: "disabled" });
  console.log("  存 _verify_rel_detail.png");

  console.log("伏笔回收…");
  await openJian(page);
  await clickText(page, "伏笔回收");
  await sleep(400);
  if (!(await clickText(page, "重新生成"))) await clickText(page, "生成", { exact: false });
  await sleep(4000);
  await page.screenshot({ path: join(OUT, "_verify_foreshadow.png"), animations: "disabled" });
  console.log("  存 _verify_foreshadow.png");

  await browser.close();
  console.log("完成。");
}
main().catch((e) => { console.error(e); process.exit(1); });
