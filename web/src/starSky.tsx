// ---------------------------------------------------------------------------
// starSky —— 关系类视图的星图皮共享件
//
// 人物关系图（CharacterGraph）和关系演变（RelationshipTimeline）是同族同皮：夜空底 +
// 人物画成会闪烁的星（glow 圈 + 四芒线 + 白芯核）+ 星座连线。两边原本各写一份夜空底色、
// 一份星节点、一份 twinkle keyframe（cg-twinkle / rt-twinkle，定义逐字相同）。这里收口成
// 一份：夜空常量 + StarNode 子组件 + StarTwinkleStyle keyframe，两边 import。
// ---------------------------------------------------------------------------

// 夜空底色：星图视图的 svg 背景。
export const NIGHT_SKY = "#0f1730";

// twinkle keyframe（纯 CSS，不靠 rAF——headless / 后台标签会暂停 rAF）。两个视图共用一个
// 动画名 star-twinkle，在星图 svg 里渲染一次即可。
export function StarTwinkleStyle() {
  return <style>{`@keyframes star-twinkle{0%,100%{opacity:.6}50%{opacity:1}}`}</style>;
}

// 一颗星：glow 圈 + 四芒线（横竖各一）+ 白芯闪烁核。大小/亮度由调用方按戏份给 r，
// 阵营色给 color，闪烁周期给 twinkleDur（错开免得齐刷刷）。
export function StarNode({
  cx,
  cy,
  r,
  color,
  twinkleDur,
}: {
  cx: number;
  cy: number;
  r: number;
  color: string;
  twinkleDur: number;
}) {
  return (
    <>
      <circle cx={cx} cy={cy} r={r * 2.3} fill={color} opacity={0.13} />
      <line x1={cx - r * 1.8} y1={cy} x2={cx + r * 1.8} y2={cy} stroke={color} strokeWidth={0.8} opacity={0.45} />
      <line x1={cx} y1={cy - r * 1.8} x2={cx} y2={cy + r * 1.8} stroke={color} strokeWidth={0.8} opacity={0.45} />
      <circle
        cx={cx}
        cy={cy}
        r={r}
        fill={color}
        stroke="#fdf6e3"
        strokeWidth={0.9}
        style={{ animation: `star-twinkle ${twinkleDur}s ease-in-out infinite` }}
      />
    </>
  );
}
