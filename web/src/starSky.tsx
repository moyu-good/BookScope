// ---------------------------------------------------------------------------
// starSky —— 关系图（CharacterGraph）的底皮共享件
//
// 早先这套是「夜空底 + 闪烁星（辉光圈 + 四芒线 + 白芯核）+ 星座连线」，久看杂乱、也难受。
// 现在照 CBDB / Network of Thrones 那种干净的浅底网络图重做：浅底、静止、克制的实心圆点。
// 一份浅底常量 + 一个 StarNode 圆点子组件，CharacterGraph 引用。名字沿用 starSky / StarNode，
// 不重命名组件（少动引用面），但视觉已从「星」改成「点」。
// ---------------------------------------------------------------------------

// 图底色：浅、干净的凹陷画布色，跟数字善本一套，暗色主题也自动跟着变。
export const GRAPH_BG = "var(--color-paper-sunken)";

// 一个节点：干净的实心圆点。填色按阵营给 color，大小按戏份给 r。
// 一圈很细的浅色描边把挨在一起的点分开，不带辉光、不带四芒、不闪。
export function StarNode({
  cx,
  cy,
  r,
  color,
}: {
  cx: number;
  cy: number;
  r: number;
  color: string;
}) {
  return (
    <circle cx={cx} cy={cy} r={r} fill={color} stroke="var(--color-paper)" strokeWidth={1} />
  );
}
