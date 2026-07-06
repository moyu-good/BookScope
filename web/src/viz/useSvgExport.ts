// ---------------------------------------------------------------------------
// useSvgExport — 把「存图」的接线姿势固化成一个 hook(传播性地基 Phase 0，§⑤ 存图接线)
//
// exportUsageExample.tsx 里那套「落款 → 导出 → finally 复原」每个镜头都要抄一遍 try/finally，
// 容易抄漏(比如忘了 restore()、忘了管 exporting 态)。这个 hook 把那套流程收进来，各镜头一行接入。
//
// 分工(别重复造):
//   • svgExport.ts —— 真正干活的两个函数。stampSvgForExport 把标题/来源/水印画进 SVG，
//     exportSvgToPng 把 SVG 转 PNG 触发下载。
//   • useSvgExport(本文件) —— 只编排流程:取 ref → 落款 → 导出 → finally 复原，顺带管 exporting 态。
//     不碰按钮 UI，不碰导出细节。
//   • ExportButton.tsx —— 只管按钮长相 + 自己内部的 busy/failed 态 + 出错兜底文案。
//     它内部也有一份 busy 态(点下去到 onExport resolve 之间)，跟本 hook 的 exporting 各管各的:
//     ExportButton.busy 管按钮那一下的禁用+扫光，hook.exporting 是给镜头「除了按钮之外还想禁用别的
//     东西」时用的(比如导出中把整块图压暗)。只用 ExportButton 的话，exporting 可以不接。
//
// 出错兜底:onExport 内部不 throw——真出错也吞在这，让 ExportButton 自己的 catch 去显兜底文案。
// 但即便走 ExportButton，这里 finally 也必须把 exporting 复位 + restore() 把页面 SVG 还原，
// 不能因为出错就把落款留在界面上、或把 exporting 卡在 true。
// ---------------------------------------------------------------------------

import { useCallback, useRef, useState } from "react";
import type { RefObject } from "react";

import { exportSvgToPng, stampSvgForExport } from "../svgExport";

/** 导出那一刻现取的落款信息。用函数形式拿(见 useSvgExport 注释)——因为标题/来源随选中变。 */
export interface SvgExportMeta {
  /** 标题 = 一句话结论(008:标题即观点，不是「关系图」这种图种名)。空则不画标题。 */
  title?: string;
  /** 来源 = evidence-first 的证据出处，如「基于《三国演义》第 55–60 回原文」。空则不画来源。 */
  source?: string;
  /** 下载文件名(不带 .png 也行)。 */
  filename: string;
}

export interface UseSvgExportResult {
  /** 导出进行中。想在按钮之外再禁用/压暗别的东西时读它;只用 ExportButton 可不接。 */
  exporting: boolean;
  /** 传给 <ExportButton onExport={onExport} />。内部:落款 → 导出 → finally 复原。 */
  onExport: () => Promise<void>;
}

/**
 * 存图接线 hook。镜头用法:
 *   const svgRef = useRef<SVGSVGElement>(null);
 *   const { exporting, onExport } = useSvgExport(svgRef, () => ({
 *     title: headline,          // 现取:结论可能随选中变
 *     source: `基于《${bookName}》第 ${from}–${to} 回原文`,
 *     filename: `${bookName}-关系图`,
 *   }));
 *   // …
 *   <svg ref={svgRef} …>…</svg>
 *   <ExportButton onExport={onExport} disabled={!hasData} />
 *
 * getMeta 用函数形式:导出那一刻才调它现取标题/来源——因为结论、聚焦对象、来源章节都可能随
 * 用户选中变，写死会导出成旧标题。
 *
 * @param svgRef  指向要导出的 <svg>(用 useRef<SVGSVGElement>(null) 建，故类型带 | null)。
 * @param getMeta 导出时现取落款+文件名的函数。
 */
export function useSvgExport(
  svgRef: RefObject<SVGSVGElement | null>,
  getMeta: () => SvgExportMeta,
): UseSvgExportResult {
  const [exporting, setExporting] = useState(false);

  // 把 getMeta 存进 ref，让 onExport 的依赖数组不随每次渲染传进来的新函数变——
  // 镜头通常内联写 () => ({...})，每渲染都是新引用;不这样 onExport 会每帧换新的。
  const getMetaRef = useRef(getMeta);
  getMetaRef.current = getMeta;

  const onExport = useCallback(async () => {
    const svg = svgRef.current;
    if (!svg) return; // 图还没渲染出来，静默不做(按钮那边也该 disabled)。

    const { title, source, filename } = getMetaRef.current();

    // 落款:标题+来源画进 SVG 顶部，右下角水印「书鉴 · BookScope」。返回复原函数。
    const restore = stampSvgForExport(svg, { title, source });
    setExporting(true);
    try {
      await exportSvgToPng(svg, filename);
    } catch {
      // 不往外抛:让配套的 ExportButton 用它自己的 catch 去显兜底文案，
      // 避免同一次出错既被这里抛、又被那边抓，重复处理。这里只保证 finally 收好尾。
    } finally {
      restore(); // 无论成败都还原页面上的 SVG——落款只为导出那一下，不留在界面里。
      setExporting(false);
    }
  }, [svgRef]);

  return { exporting, onExport };
}
