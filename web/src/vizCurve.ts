// ---------------------------------------------------------------------------
// vizCurve — 品读视图共用的平滑曲线工具
//
// 山水长卷的山脊（ShanshuiCurve）和工笔花鸟的枝条（HuaniaoArc）都要把一串点连成柔和
// 的曲线，原本各写了一份逐字相同的 Catmull-Rom 转贝塞尔。收口到这里一份，两边 import。
// ---------------------------------------------------------------------------

// 一串点连成平滑曲线（Catmull-Rom 转三次贝塞尔）——线要流动，不要折线的硬棱角。
// 给定一串 [x, y] 点，返回 SVG path 的 d 串。
export function smoothLine(pts: [number, number][]): string {
  if (pts.length < 2) return pts.length ? `M${pts[0][0]},${pts[0][1]}` : "";
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] ?? pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] ?? pts[i + 1];
    const c1x = p1[0] + (p2[0] - p0[0]) / 6;
    const c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6;
    const c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}
