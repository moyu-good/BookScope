// ---------------------------------------------------------------------------
// vizTokens — 自写 SVG 图的默认外观值(可视化 Phase 0 地基之③,
// 依托 docs/design/WP-viz-phase0-foundation.md §方案概要③)。
//
// 干一件事:把每张图各调各的配色 / 字号 / 轴线 / 留白 / 动画时长收成一处,
// 各镜头引用同一套默认值,不再手抄。研究笔记 008 的判断是"设计感在线、
// 只是 fleet 内不一致",所以这里不是发明新审美,是把善本那套默认值 codify 下来
// (008 §一维度① + §五 nivo theme / Observable Plot 默认克制美学那条)。
//
// 配色跟着主题走:能引 CSS 变量的都写成 var(--x) 字符串,暗色主题一切换,
// 图自动跟着变(index.css 里 [data-theme="dark"] 已备好那套暖炭墨的值)。
// 纯几何量(px / 时长)没有主题概念,直接给数。
//
// ⚠️ 分类配色 vs 数据色 —— 两回事,别混:
//   · 分类配色(categoricalPalette,这里给):给"不同系列 / 不同分类"随手分色用的
//     默认盘。颜色本身不承载含义,只求彼此分得开、跟善本调性搭。多系列折线、
//     多组柱、图例分色这类场景取它。
//   · 数据色(不在这里,各镜头自己留):按数值 / 语义映射出来的颜色,含义就在颜色里。
//     比如 CharacterGraph 的 EDGE_COLOR(敌红 / 亲青 / 中灰)、RelationshipTimeline
//     的敌友色温(WARM 暖=盟 / COOL 冷=敌)。这些是"红就代表敌",不能拿分类盘随机盖,
//     必须保持独立、不进这个文件。
// ---------------------------------------------------------------------------

/**
 * 分类配色序列——给多系列 / 多分类图随手分色。
 *
 * 排布:朱砂(唯一 accent,给最该突出的那一系列)打头,墨与暖灰墨压场当中性主力,
 * 再跟几个克制的辅色(青绿 / 靛 / 赭 / 藤),都往善本那种低饱和暖调收,不要糖果色。
 * 前四个已经足够拉开;系列多到 5-7 才动用后面的辅色。超过 8 个系列本就不该硬堆颜色
 * (008 说的"别逼读者拿颜色去图例对号"),那时该换直接标注或分面,不是再加色。
 *
 * 注:朱砂 / 墨 / 分隔线走 CSS 变量跟主题;辅色是固定 hex——它们不属于善本三主色,
 * 没有对应的 CSS 变量,且分类色求的是"稳定可区分"而非"跟主题浮动",定死更稳。
 */
export const categoricalPalette = [
  "var(--color-seal)", // 朱砂——留给最该突出的一条
  "var(--color-ink)", // 墨——中性主力
  "#2E8B6E", // 青绿(与关系图同盟色同源,和谐)
  "#C08A2E", // 赭黄
  "#3E6E9A", // 靛蓝(克制,不刺眼)
  "#8A6BA6", // 藤紫
  "#B5623A", // 砖赭
  "var(--color-ink-muted)", // 暖灰墨——收尾兜底
] as const;

/**
 * 字号层级——四档,px。
 * 对齐 index.css 的语义字号:脚注≈--text-caption(11px)、数据标签≈--text-body-sm(13px)。
 * SVG <text> 用数值比 CSS 变量稳(不同浏览器对 SVG 里 rem/var 支持参差),
 * 所以这里给算好的 px,数值本身跟 index.css 那套对齐、别另立一套。
 */
export const fontSize = {
  title: 15, // 图标题(说结论那句,008 要求标题即观点)
  axis: 12, // 轴标签 / 刻度
  dataLabel: 13, // 贴在数据点上的标签(节点名 / 数值),对齐 --text-body-sm
  footnote: 11, // 来源 / 水印 / 脚注,对齐 --text-caption
} as const;

/** 标题字体——跟 index.css 的 --font-display 走(善本衬线)。 */
export const fontFamily = {
  display: "var(--font-display)",
} as const;

/**
 * 轴线——粗细 + 颜色。颜色用 --color-rule(善本那条细墨分隔线),
 * 暗色主题自动转成暗中间调。现在 RelationshipTimeline 等处硬写着 #c9c2b6,
 * 以后统一收到这里、跟主题走。
 */
export const axis = {
  color: "var(--color-rule)",
  width: 1, // 主轴线
  tickWidth: 1, // 刻度线,与主轴同粗,克制
  gridColor: "var(--color-rule)", // 网格线同色,更淡靠 opacity 压
  gridOpacity: 0.5,
} as const;

/**
 * 留白——图表默认 margin 基准(px)。
 * 左侧留宽给 Y 轴标签,底部留给 X 轴 + 脚注,上方留给标题。
 * 具体镜头可按需覆盖,这里给一套克制的默认(Observable Plot 那种"够用就好")。
 */
export const margin = {
  top: 24, // 容标题
  right: 16,
  bottom: 36, // 容 X 轴标签 + 脚注
  left: 44, // 容 Y 轴标签
} as const;

/** 图内元素间距基准(px),排图例 / 标注留缝用。 */
export const padding = {
  base: 8,
  tight: 4,
  loose: 16,
} as const;

/**
 * 动画时长(ms)——有节制的过渡,不是永动。
 * 008 明确要求 200–300ms 的克制过渡(维度④"有节制的更新动画,不是永动")。
 * 力导向那种持续 rAF 模拟不归这里管(它不是"过渡",是实时布局)。
 */
export const motion = {
  fast: 200, // hover 高亮 / 淡化这类即时反馈
  base: 260, // 系列进出 / 数值变化的默认过渡
  slow: 300, // 稍大的布局位移
  easing: "cubic-bezier(0.2, 0.7, 0.2, 1)", // 与 index.css 的 reveal-up 缓动同源
} as const;

/** 描边宽默认基准(px)——线图主线 / 一般边。数据边的粗细各镜头另按数值算。 */
export const strokeWidth = {
  hairline: 1, // 细线 / 辅助线
  base: 1.6, // 一般描边(与现有图标描边同宽)
  emphasis: 2.4, // 强调 / 选中态
} as const;

/** 数据点半径基准(px)。 */
export const pointRadius = {
  small: 3,
  base: 5,
  large: 7,
} as const;

/**
 * 一处导出的图表 token 总集。各镜头 `import { vizTokens } from "./viz/vizTokens"`
 * 后统一引用,如 vizTokens.axis.color / vizTokens.fontSize.axis。
 * as const:字面量类型 + 只读,防止某个镜头顺手改了污染别处。
 */
export const vizTokens = {
  categoricalPalette,
  fontSize,
  fontFamily,
  axis,
  margin,
  padding,
  motion,
  strokeWidth,
  pointRadius,
} as const;

export type VizTokens = typeof vizTokens;
