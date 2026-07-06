// ---------------------------------------------------------------------------
// exportUsageExample — 「存图」这套怎么接进一个 viz 的样板（传播性基座，1.8.x）
//
// ⚠️ 这个文件不接进任何现有 viz，也不被任何地方 import——它只是给下一轮做「接线」的人一份
// 可直接照抄、且已过 tsc 的模板。真正接线时，把这段模式搬进目标 viz（如 CharacterArc /
// CharacterGraph / NarrativeCurve），删掉这个示例文件即可。
//
// 三步：
//   1) 给要导出的 <svg> 挂一个 ref；
//   2) 「存图」按钮的 onExport 里：先 stampSvgForExport 落款（标题=一句话结论、来源=基于第X回原文），
//      再 await exportSvgToPng，最后 finally restore() 把页面上的 SVG 还原（落款只进 PNG、不留界面）；
//   3) 按钮放图页脚（008：导出入口的肌肉记忆位置）。
//
// 关键点（008 + 本项目特有）：
//   • 标题/来源/水印必须画进 SVG 本身（stampSvgForExport 干这事）——在 SVG 外的 Tailwind div 里
//     截 SVG 就截没了，脱离语境传播看不懂。
//   • viz 的 SVG 里若直接写了 CSS 变量（fill="var(--color-seal)"），exportSvgToPng 会就地解析，
//     不用调用方操心。
//   • 当前系统字体栈，不用传 fonts（见 svgExport.ts 文件头字体现状说明）。
// ---------------------------------------------------------------------------

import { useRef } from "react";

import { ExportButton } from "./ExportButton";
import { exportSvgToPng, stampSvgForExport } from "./svgExport";

interface ExampleProps {
  /** 一句话结论，作导出图标题（008：标题即观点，不是「关系图」这种图种名）。 */
  headline: string;
  /** 证据出处，如「基于《三国演义》第 55–60 回原文」。 */
  source: string;
  /** 下载文件名（不带 .png 也行）。 */
  filename: string;
}

export function ExportUsageExample({ headline, source, filename }: ExampleProps) {
  // 1) 给要导出的 SVG 挂 ref
  const svgRef = useRef<SVGSVGElement>(null);

  // 2) 拼导出流程：落款 → 导出 → 复原
  async function handleExport() {
    const svgEl = svgRef.current;
    if (!svgEl) return;
    // 落款：标题+来源画进 SVG 顶部，右下角水印「书鉴 · BookScope」
    const restore = stampSvgForExport(svgEl, {
      title: headline,
      source,
      // watermark 默认「书鉴 · BookScope」，一般不用传
    });
    try {
      await exportSvgToPng(svgEl, filename);
    } finally {
      restore(); // 无论成败都把页面上的 SVG 还原——落款只为导出那一下
    }
  }

  return (
    <div className="pt-4">
      {/* viz 主体：这里用一张最小 SVG 占位，真 viz 换成 CharacterGraph/HuaniaoArc 等的 <svg> */}
      <svg
        ref={svgRef}
        viewBox="0 0 480 240"
        width={480}
        height={240}
        xmlns="http://www.w3.org/2000/svg"
      >
        <rect x={0} y={0} width={480} height={240} fill="var(--color-paper)" />
        <circle cx={240} cy={120} r={40} fill="var(--color-seal)" />
        <text
          x={240}
          y={200}
          textAnchor="middle"
          fontSize={16}
          fill="var(--color-ink)"
          fontFamily="var(--font-display)"
        >
          示例图（中文导出验字体）
        </text>
      </svg>

      {/* 3) 存图按钮放页脚 */}
      <div className="mt-3 flex justify-end">
        <ExportButton onExport={handleExport} />
      </div>
    </div>
  );
}
