// ---------------------------------------------------------------------------
// svgExport — 把自写 SVG 视图导成 PNG「存图」（传播性基座，1.8.x）
//
// 依托：research-notes/008-viz-prior-art.md 第三节「传播性工程落地路径」。
// 那条走通的路是纯浏览器、零后端、CPU 跑（符合禁 GPU）：
//   拿到 <svg> DOM 节点 → 序列化成字符串 → 转 dataURL → new Image() → 画到 canvas
//   （pixelRatio 2 防高分屏糊）→ canvas.toBlob('image/png') → 触发下载。
//
// 为什么不用 html2canvas / html-to-image：外部 CSS（含 @font-face、CSS 变量）不作用在
// <img> 里加载的 SVG 上，中文 <text> 直接渲成方框——这正是「中文导出乱码」的根因。
// 008 明确 html2canvas 对「中文自定义字体 + SVG <text>」是死穴。这条自己写 ~30 行更可控、
// 也不引依赖。
//
// 本项目字体现状（2026-07-06 调研，见文件末尾说明与交付报告）：--font-display / --font-body
// 都是系统字体栈（PingFang SC / Noto Serif CJK / 宋体…），仓库里没有任何 webfont 文件、
// 没有 @font-face。所以走 008 的情况 (b)：导出用系统字体即可，字体内嵌那步（base64 @font-face）
// 目前是 no-op（fontFaces 传空）。跨设备不保证字体完全一致（各机装的中文字体不同），将来要
// 逐像素一致再引子集化 webfont（见 embedFontFaces 注释 + 报告的 FLAG）。
//
// 另一个真实的坑（本项目特有）：viz 的 SVG 里直接写了 CSS 变量（fill="var(--color-seal)"、
// fill="var(--color-paper)"…），它们靠页面的 CSS 级联解析。SVG 一旦脱离页面塞进 <img>，
// var() 无从解析、颜色全丢。所以序列化前必须把用到的 CSS 变量在克隆节点上就地解析成计算值
// （inlineCssVariables）。
// ---------------------------------------------------------------------------

/** 一份要内嵌进 SVG 的字体（将来引子集化 webfont 时用；当前系统字体栈下不需要）。 */
export interface EmbeddedFont {
  /** font-family 名，要跟 SVG 里 text 的 font-family 对上 */
  family: string;
  /** 字体二进制的 base64（不含 data: 前缀） */
  base64: string;
  /** woff2 / woff / truetype / opentype，写进 @font-face src 的 format() */
  format: "woff2" | "woff" | "truetype" | "opentype";
  weight?: string;
  style?: string;
}

export interface ExportSvgOptions {
  /** 导出分辨率倍率，默认 2（防高分屏糊，008 要求）。 */
  pixelRatio?: number;
  /**
   * 背景色。SVG 默认透明，PNG 直接看透明会是黑/花，所以默认铺一层纸色。
   * 传 "transparent" 保留透明。默认解析 --color-paper 的计算值。
   */
  background?: string;
  /**
   * 要内嵌的字体。当前系统字体栈下传空即可（默认空）。将来引子集化 webfont 时，
   * 把子集后的 base64 传进来，会写进 SVG 内部 <defs><style> 的 @font-face，字体随 SVG 走。
   */
  fonts?: EmbeddedFont[];
  /**
   * 额外要就地解析的 CSS 变量名（含 -- 前缀）。默认把善本设计语言那套全解析
   * （见 DEFAULT_CSS_VARS）。viz 若用了别的变量，追加进来。
   */
  cssVars?: string[];
}

// 善本设计语言里 viz 会直接写进 SVG 的 CSS 变量——序列化前要就地解析成计算值。
// 与 index.css @theme 对齐；随主题（浅/暗）走的是「解析当下计算值」，导出即所见。
const DEFAULT_CSS_VARS = [
  "--color-paper",
  "--color-paper-raised",
  "--color-paper-sunken",
  "--color-ink",
  "--color-ink-muted",
  "--color-seal",
  "--color-seal-soft",
  "--color-rule",
  "--color-desk",
  "--color-case",
  "--color-folio-edge",
];

const SVG_NS = "http://www.w3.org/2000/svg";
const XHTML_NS = "http://www.w3.org/1999/xhtml";

/**
 * 把某元素及其后代里，指向 CSS 变量（var(--x)）的呈现属性/内联样式，就地解析成计算值。
 * 只处理 SVG 里真会用到的一小撮属性（fill/stroke/stop-color/color…）+ style 属性里的 var()。
 * 解析源是「原始节点」的 getComputedStyle——因为克隆节点还没进 DOM、算不出级联值。
 */
function inlineCssVariables(
  original: SVGSVGElement,
  clone: SVGSVGElement,
  cssVars: string[],
): void {
  // 先从原始 SVG 的计算样式里读出每个变量的当下值（浅/暗主题即所见）。
  const rootStyle = getComputedStyle(original);
  const varValue = new Map<string, string>();
  for (const name of cssVars) {
    const v = rootStyle.getPropertyValue(name).trim();
    if (v) varValue.set(name, v);
  }

  // 把 var(--x[, fallback]) 里的 --x 换成解析值；解析不到就留 fallback / 原样。
  const resolveVarExpr = (expr: string): string =>
    expr.replace(/var\(\s*(--[\w-]+)\s*(?:,\s*([^)]*))?\)/g, (_m, name: string, fb?: string) => {
      const v = varValue.get(name);
      if (v) return v;
      return (fb ?? "").trim() || _m;
    });

  const originalNodes = original.querySelectorAll<Element>("*");
  const cloneNodes = clone.querySelectorAll<Element>("*");
  // 原始与克隆是同构的（cloneNode(true)），按下标一一对应；根节点单独处理。
  const pairs: Array<[Element, Element]> = [[original, clone]];
  for (let i = 0; i < originalNodes.length && i < cloneNodes.length; i++) {
    pairs.push([originalNodes[i], cloneNodes[i]]);
  }

  // 这些 SVG 呈现属性可能写成 var()；用原始节点的 computed 值回填到克隆节点。
  const PAINT_ATTRS = ["fill", "stroke", "stop-color", "color", "flood-color", "lighting-color"];

  for (const [orig, cl] of pairs) {
    const cs = getComputedStyle(orig);
    for (const attr of PAINT_ATTRS) {
      const attrVal = cl.getAttribute(attr);
      if (attrVal && attrVal.includes("var(")) {
        // 优先用浏览器已算好的 computed 值（最准），算不出再用我们自己的 var 解析。
        const computed = cs.getPropertyValue(attr).trim();
        cl.setAttribute(attr, computed || resolveVarExpr(attrVal));
      }
    }
    // style="fill:var(--x)" 这类内联样式里的 var()
    const styleAttr = cl.getAttribute("style");
    if (styleAttr && styleAttr.includes("var(")) {
      cl.setAttribute("style", resolveVarExpr(styleAttr));
    }
  }
}

/** 把内嵌字体拼成 <style> 里的一组 @font-face 规则（当前系统字体栈下 fonts 为空 → 返回空串）。 */
function buildFontFaceCss(fonts: EmbeddedFont[]): string {
  return fonts
    .map(
      (f) => `@font-face{font-family:'${f.family}';font-style:${f.style ?? "normal"};` +
        `font-weight:${f.weight ?? "normal"};` +
        `src:url(data:font/${f.format};base64,${f.base64}) format('${f.format}');}`,
    )
    .join("\n");
}

/**
 * 克隆 SVG、就地解析 CSS 变量、（有则）内嵌字体、补齐命名空间与显式宽高，
 * 返回一个可安全序列化、脱离页面也能自洽渲染的 <svg>。不改动传入的原始节点。
 */
function prepareSvgForExport(
  svg: SVGSVGElement,
  fonts: EmbeddedFont[],
  cssVars: string[],
): { clone: SVGSVGElement; width: number; height: number } {
  const clone = svg.cloneNode(true) as SVGSVGElement;

  // 命名空间——序列化成独立文件时必须显式带上，否则 <img> 不认。
  clone.setAttribute("xmlns", SVG_NS);
  clone.setAttribute("xmlns:xlink", "http://www.w3.org/1999/xlink");

  // 定尺寸：本项目 viz 多是 viewBox + `w-full`（宽由容器定、无显式 width/height 属性），
  // 所以宽取页面真实渲染宽，高按 viewBox 的纵横比从宽推——这样即使刚 stampSvgForExport 加高了
  // viewBox、CSS 重排还没跟上，导出比例也准（不依赖 rect.height 是否已刷新）。
  const rect = svg.getBoundingClientRect();
  const vb = svg.viewBox?.baseVal;
  let width = Math.round(rect.width);
  let height = Math.round(rect.height);
  if (vb && vb.width && vb.height) {
    if (!width) width = Math.round(vb.width);
    // 有 viewBox 就以它的比例为准（导出比例 = viewBox 比例，落款加高后同样对）。
    height = Math.round((width / vb.width) * vb.height);
  }
  if (!width) width = 800;
  if (!height) height = 600;
  clone.setAttribute("width", String(width));
  clone.setAttribute("height", String(height));

  // 就地把 var(--x) 解析成计算值（本项目特有的坑，见文件头注释）。
  inlineCssVariables(svg, clone, cssVars);

  // 有内嵌字体则写进 <defs><style>，字体随 SVG 走、脱离页面不丢（008 的正确路）。
  const fontCss = buildFontFaceCss(fonts);
  if (fontCss) {
    const defs = document.createElementNS(SVG_NS, "defs");
    const style = document.createElementNS(SVG_NS, "style");
    style.setAttribute("type", "text/css");
    style.textContent = fontCss;
    defs.appendChild(style);
    clone.insertBefore(defs, clone.firstChild);
  }

  return { clone, width, height };
}

/** 解析 --color-paper 的当下计算值当默认背景（导出即所见的纸色，浅/暗主题各自对）。 */
function resolvePaperBackground(svg: SVGSVGElement): string {
  const v = getComputedStyle(svg).getPropertyValue("--color-paper").trim();
  return v || "#ffffff";
}

/** 触发浏览器下载一个 Blob。 */
function triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename.endsWith(".png") ? filename : `${filename}.png`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // 稍后回收，给下载留出发起时间。
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * 把一个 <svg> DOM 节点导成 PNG 并触发下载。
 *
 * 用法（各 viz 拿到自己 SVG 的 ref 后）：
 *   await exportSvgToPng(svgEl, "三国-关系图");
 *
 * @param svgEl   要导出的 SVG 节点（页面上真实渲染中的那个）
 * @param filename 下载文件名（可不带 .png）
 * @param options  分辨率 / 背景 / 内嵌字体 / 额外 CSS 变量
 */
export async function exportSvgToPng(
  svgEl: SVGSVGElement,
  filename: string,
  options: ExportSvgOptions = {},
): Promise<void> {
  const pixelRatio = options.pixelRatio ?? 2;
  const fonts = options.fonts ?? [];
  const cssVars = options.cssVars ?? DEFAULT_CSS_VARS;
  const background =
    options.background === "transparent"
      ? null
      : (options.background ?? resolvePaperBackground(svgEl));

  const { clone, width, height } = prepareSvgForExport(svgEl, fonts, cssVars);

  // 序列化 → dataURL。用 encodeURIComponent + unescape 走 UTF-8，中文 <text> 不乱码。
  const svgString = new XMLSerializer().serializeToString(clone);
  const svgDataUrl =
    "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svgString);

  const img = new Image();
  img.decoding = "async";

  await new Promise<void>((resolve, reject) => {
    img.onload = () => resolve();
    img.onerror = () => reject(new Error("SVG 转图失败：图片加载出错（可能含跨域资源或字体过大）"));
    img.src = svgDataUrl;
  });

  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(width * pixelRatio));
  canvas.height = Math.max(1, Math.round(height * pixelRatio));
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("导出失败：拿不到 canvas 2d 上下文");

  ctx.scale(pixelRatio, pixelRatio);
  if (background) {
    ctx.fillStyle = background;
    ctx.fillRect(0, 0, width, height);
  }
  ctx.drawImage(img, 0, 0, width, height);

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob((b) => resolve(b), "image/png"),
  );
  if (!blob) throw new Error("导出失败：canvas.toBlob 返回空");

  triggerDownload(blob, filename);
}

// ---------------------------------------------------------------------------
// 落款 helper —— 把「标题（一句话结论）/ 来源 / 右下角水印」画进 SVG 本身。
//
// 008 明确：标题/图例/来源若在 SVG 外的 Tailwind <div> 里，截 SVG 就截没了；要脱离语境传播，
// 这几样必须画进 SVG 本身。这个 helper 就干这件事：在导出前，往 SVG 顶部塞标题+来源、
// 右下角塞低透明度水印「书鉴 · BookScope」，并把 viz 主体整体下移给标题让位、把画布加高。
//
// 典型调用（各 viz「存图」时，先落款再导出）：
//   const svgEl = svgRef.current;
//   if (!svgEl) return;
//   const restore = stampSvgForExport(svgEl, {
//     title: "宋江晁盖第 60 回彻底反转",           // 一句话结论，不是「关系图」
//     source: "基于《水浒传》第 55–60 回原文",       // evidence-first：来源印上图
//   });
//   try {
//     await exportSvgToPng(svgEl, "水浒-关系演变");
//   } finally {
//     restore();  // 复原页面上的 SVG（落款只为导出那一下，不留在界面里）
//   }
//
// 说明：stampSvgForExport 直接改传入的 SVG（因为标题要参与真实布局、被 exportSvgToPng 的
// getBoundingClientRect 量到），并返回一个 restore()——导出完调它把 SVG 还原。这样界面上不留
// 落款、只在导出的 PNG 里有。若不想动页面节点，也可先自己 clone 一份 append 到隐藏容器再落款导出。
// ---------------------------------------------------------------------------

export interface StampOptions {
  /** 标题 = 一句话结论（传播的记忆点，008：标题即观点，不是图种名）。 */
  title?: string;
  /** 来源 = evidence-first 的证据出处，如「基于《书名》第 X 回原文」。 */
  source?: string;
  /** 右下角水印文字，默认「书鉴 · BookScope」。传 "" 关掉水印。 */
  watermark?: string;
  /** 标题区顶部留白 + 行距的基准，默认按善本字号来。 */
  titleFontSize?: number;
  sourceFontSize?: number;
}

/**
 * 往 SVG 里画进标题 / 来源 / 水印，返回复原函数。
 * 做法：把原有内容整体下移 headerH，把 viewBox / height 相应加高，在顶部空出的带里写标题+来源，
 * 右下角写低透明度水印。全部用善本设计语言的颜色（就地取计算值，导出时再由 inlineCssVariables 处理，
 * 但这里直接写计算值更稳，免得落款文字也被 var 解析漏掉）。
 */
export function stampSvgForExport(svg: SVGSVGElement, opts: StampOptions): () => void {
  const title = opts.title?.trim();
  const source = opts.source?.trim();
  const watermark = opts.watermark ?? "书鉴 · BookScope";
  const titleSize = opts.titleFontSize ?? 20;
  const sourceSize = opts.sourceFontSize ?? 12;

  const cs = getComputedStyle(svg);
  const ink = cs.getPropertyValue("--color-ink").trim() || "#2a2018";
  const inkMuted = cs.getPropertyValue("--color-ink-muted").trim() || "#6b6259";
  const seal = cs.getPropertyValue("--color-seal").trim() || "#9a3b34";
  const displayFont =
    cs.getPropertyValue("--font-display").trim() ||
    '"PingFang SC","Noto Serif CJK SC",serif';

  // 记录原始 viewBox / width / height，restore 时还原。
  const prevViewBox = svg.getAttribute("viewBox");
  const vb = svg.viewBox?.baseVal;
  const rect = svg.getBoundingClientRect();
  const vbW = vb && vb.width ? vb.width : Math.round(rect.width) || 800;
  const vbH = vb && vb.height ? vb.height : Math.round(rect.height) || 600;
  const vbX = vb ? vb.x : 0;
  const vbY = vb ? vb.y : 0;

  // 顶部标题带高度：有标题给两行位（标题+来源），只有其一给一行。
  const padX = 16;
  const headerH = title ? (source ? titleSize + sourceSize + 26 : titleSize + 20) : source ? sourceSize + 18 : 0;

  // 把 viz 原有内容整体下移 headerH：包一层 <g transform=translate(0,headerH)>。
  const wrapper = document.createElementNS(SVG_NS, "g");
  wrapper.setAttribute("data-export-shift", "1");
  wrapper.setAttribute("transform", `translate(0 ${headerH})`);
  // 把当前所有子节点搬进 wrapper。
  const moved: ChildNode[] = [];
  while (svg.firstChild) {
    moved.push(svg.firstChild);
    wrapper.appendChild(svg.firstChild);
  }
  svg.appendChild(wrapper);

  // 加高画布：viewBox 高 + headerH，width/height 属性同步（若原来有）。
  svg.setAttribute("viewBox", `${vbX} ${vbY} ${vbW} ${vbH + headerH}`);
  const hadWidth = svg.getAttribute("width");
  const hadHeight = svg.getAttribute("height");
  if (hadHeight) svg.setAttribute("height", String((parseFloat(hadHeight) || vbH) + headerH));

  const added: Element[] = [];
  const addText = (
    x: number,
    y: number,
    text: string,
    size: number,
    color: string,
    opacity = 1,
    anchor: "start" | "end" | "middle" = "start",
    bold = false,
  ) => {
    const t = document.createElementNS(SVG_NS, "text");
    t.setAttribute("x", String(x));
    t.setAttribute("y", String(y));
    t.setAttribute("font-size", String(size));
    t.setAttribute("fill", color);
    t.setAttribute("font-family", displayFont);
    t.setAttribute("text-anchor", anchor);
    if (opacity !== 1) t.setAttribute("opacity", String(opacity));
    if (bold) t.setAttribute("font-weight", "700");
    t.textContent = text;
    svg.appendChild(t);
    added.push(t);
    return t;
  };

  // 标题（一句话结论，墨色加粗）+ 来源（朱砂灰、小字）。坐标在原 viewBox 系里（vbX/vbY 起）。
  if (title) {
    addText(vbX + padX, vbY + titleSize + 6, title, titleSize, ink, 1, "start", true);
    if (source) addText(vbX + padX, vbY + titleSize + sourceSize + 14, source, sourceSize, seal, 1, "start");
  } else if (source) {
    addText(vbX + padX, vbY + sourceSize + 10, source, sourceSize, seal, 1, "start");
  }

  // 右下角低透明度水印（裁不掉、脱离页面也在）。画在加高后的画布右下。
  if (watermark) {
    addText(
      vbX + vbW - padX,
      vbY + vbH + headerH - 10,
      watermark,
      12,
      inkMuted,
      0.5,
      "end",
    );
  }

  // restore：拆掉落款文字、把内容从 wrapper 搬回、还原 viewBox / height。
  return () => {
    for (const el of added) el.remove();
    // 把 moved 的节点搬回 svg 顶层（顺序保持），再删掉空 wrapper。
    for (const node of moved) svg.appendChild(node);
    wrapper.remove();
    if (prevViewBox === null) svg.removeAttribute("viewBox");
    else svg.setAttribute("viewBox", prevViewBox);
    if (hadWidth === null) svg.removeAttribute("width");
    else svg.setAttribute("width", hadWidth);
    if (hadHeight === null) svg.removeAttribute("height");
    else svg.setAttribute("height", hadHeight);
  };
}

// 供将来引子集化 webfont 时参考的占位：把 woff/ttf 的 ArrayBuffer 转 base64。
// 当前系统字体栈下用不到（fonts 传空）。真要引：先子集化（只打包图里真出现的字，见 008——
// 中文全字库 base64 会让包爆炸），再走这里转 base64 塞进 exportSvgToPng 的 options.fonts。
// 注意 008 的坑：satori 那类不支持 woff2，但本文件走的是纯 canvas 序列化，woff2 也吃得下。
export function arrayBufferToBase64(buf: ArrayBuffer): string {
  const bytes = new Uint8Array(buf);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

// XHTML_NS 保留给将来若需在 foreignObject 里放 HTML 落款时用（Safari 有 foreignObject 坑，
// 见 008，届时优先仍用纯 SVG <text> 路避开）。当前未用到，标注避免 lint 报未使用。
void XHTML_NS;
