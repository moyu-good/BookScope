/**
 * SVG pan / zoom + 双指 pinch hook（移动端适配用）。
 *
 * 从 CharacterGraph 提炼：视角 {k, tx, ty}，内容画进
 * `<g transform={`translate(${tx} ${ty}) scale(${k})`}>`，整图能拖能缩。
 *
 * 触屏支持：单指拖平移、双指捏合缩放（以两指中点为锚，沿用滚轮的光标锚点公式）。
 * 桌面：滚轮朝光标缩、单指拖平移。
 *
 * 与节点拖拽的隔离：调用方在节点上 onPointerDown 调 e.stopPropagation()，
 * 节点指不冒泡到本 hook，pointersRef 只收背景指。语义：
 *   两指都在背景 → pinch 整图；一指在节点 → 拖节点（由调用方自行处理）。
 *
 * 调用方负责：SVG 加 `touch-none` className、内容包进 transform 的 <g>、
 * defs/marker/style 留在 <g> 外。
 */
import { useCallback, useEffect, useRef, useState } from "react";

export interface View {
  k: number;
  tx: number;
  ty: number;
}

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

interface UsePanZoomOptions {
  width: number;
  height: number;
  minK?: number;
  maxK?: number;
}

interface PointerXY {
  x: number;
  y: number;
}

export function usePanZoom(
  svgRef: React.RefObject<SVGSVGElement | null>,
  { width, height, minK = 0.3, maxK = 4 }: UsePanZoomOptions,
) {
  const [view, setView] = useState<View>({ k: 1, tx: 0, ty: 0 });
  // ref 镜像：pinch/pan 计算要拿最新 view，避免闭包过期
  const viewRef = useRef(view);
  viewRef.current = view;
  // 当前活跃背景指针数（调用方可读，用于在有 hover 吸附的图里 gate：pinch/pan 中不吸附）
  const [pointersCount, setPointersCount] = useState(0);

  // 收背景指针（client 坐标），用于多指 pinch
  const pointersRef = useRef<Map<number, PointerXY>>(new Map());
  // 单指平移起点快照（SVG 坐标 + 当时的 tx/ty）
  const panStartRef = useRef<{ sx: number; sy: number; tx: number; ty: number } | null>(null);
  // 双指 pinch 起点快照（两指距离 + 中点 SVG 坐标 + 当时的 view）
  const pinchStartRef = useRef<{
    dist: number;
    midX: number;
    midY: number;
    k: number;
    tx: number;
    ty: number;
  } | null>(null);

  // client 坐标 → SVG viewBox 坐标
  const toSvg = useCallback((clientX: number, clientY: number): PointerXY => {
    const svg = svgRef.current;
    if (!svg || !svg.getScreenCTM) return { x: 0, y: 0 };
    const pt = svg.createSVGPoint();
    pt.x = clientX;
    pt.y = clientY;
    const loc = pt.matrixTransform(svg.getScreenCTM()!.inverse());
    return { x: loc.x, y: loc.y };
  }, [svgRef]);

  const syncCount = useCallback(() => {
    const n = pointersRef.current.size;
    setPointersCount((prev) => (prev === n ? prev : n));
  }, []);

  // SVG viewBox 坐标 → 逻辑坐标（调用方节点画在 transform 的 <g> 里时用）
  const svgToLogical = useCallback(
    (sx: number, sy: number, v: View): PointerXY => ({ x: (sx - v.tx) / v.k, y: (sy - v.ty) / v.k }),
    [],
  );

  const clampK = useCallback((k: number) => Math.max(minK, Math.min(maxK, k)), [minK, maxK]);

  // 朝 (cx, cy) 锚点缩放：缩放后该点不动。newT = cx - (cx - t) * ratio
  const zoomAt = useCallback((cx: number, cy: number, factor: number) => {
    setView((v) => {
      const newK = Math.max(minK, Math.min(maxK, v.k * factor));
      const ratio = newK / v.k;
      return { k: newK, tx: cx - (cx - v.tx) * ratio, ty: cy - (cy - v.ty) * ratio };
    });
  }, [minK, maxK]);

  // 滚轮缩放:必须原生非 passive 才能 preventDefault 拦住页面滚动(React 合成 onWheel 默认 passive、
  // preventDefault 被忽略 → 缩放图时页面跟着滚)。但不能只在 mount 挂一次——很多图是"空态(无 SVG)
  // → 生成后才出 SVG",mount 时 svgRef.current 还是 null,只挂一次会永远漏掉、滚轮就死了(作者反馈)。
  // 所以:handler 存 ref 取最新闭包 + 一个无依赖 effect 每次 render 后检查,svg 元素变了就重挂监听。
  const wheelHandlerRef = useRef<(e: WheelEvent) => void>(() => {});
  wheelHandlerRef.current = (e: WheelEvent) => {
    e.preventDefault(); // 只缩放图、不带动页面
    const { x: cx, y: cy } = toSvg(e.clientX, e.clientY);
    zoomAt(cx, cy, Math.exp(-e.deltaY * 0.0015)); // 上滚放大、下滚缩小,指数让手感均匀
  };
  // 稳定的分发函数(只建一次),add/remove 用同一个引用才配得上对
  const wheelDispatchRef = useRef((e: WheelEvent) => wheelHandlerRef.current(e));
  const wheelElRef = useRef<SVGSVGElement | null>(null);
  useEffect(() => {
    // 无依赖数组:每次 render 后跑,才能捕捉到 svgRef.current 从 null→SVG(空态→生成)或元素重挂。
    const svg = svgRef.current;
    if (svg === wheelElRef.current) return; // 元素没变,不重复挂
    wheelElRef.current?.removeEventListener("wheel", wheelDispatchRef.current);
    wheelElRef.current = svg;
    svg?.addEventListener("wheel", wheelDispatchRef.current, { passive: false });
  });
  useEffect(
    () => () => {
      wheelElRef.current?.removeEventListener("wheel", wheelDispatchRef.current);
    },
    [],
  );

  // 给调用方 onWheel 属性留个 no-op:缩放已走上面的原生监听,这里再缩一次就成双重缩放了。
  const onWheel = useCallback((_e: React.WheelEvent) => {}, []);

  const onPointerDown = useCallback((e: React.PointerEvent) => {
    const svg = svgRef.current;
    if (!svg) return;
    pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    svg.setPointerCapture?.(e.pointerId);
    syncCount();
    const n = pointersRef.current.size;
    if (n === 1) {
      const { x: sx, y: sy } = toSvg(e.clientX, e.clientY);
      const v = viewRef.current;
      panStartRef.current = { sx, sy, tx: v.tx, ty: v.ty };
      pinchStartRef.current = null;
    } else if (n === 2) {
      const [a, b] = [...pointersRef.current.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      const midClientX = (a.x + b.x) / 2;
      const midClientY = (a.y + b.y) / 2;
      const { x: midX, y: midY } = toSvg(midClientX, midClientY);
      const v = viewRef.current;
      pinchStartRef.current = { dist, midX, midY, k: v.k, tx: v.tx, ty: v.ty };
      panStartRef.current = null; // 双指接管，取消单指平移
    }
  }, [svgRef, toSvg]);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!pointersRef.current.has(e.pointerId)) return;
    pointersRef.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const n = pointersRef.current.size;

    if (n >= 2 && pinchStartRef.current) {
      const ps = pinchStartRef.current;
      const [a, b] = [...pointersRef.current.values()];
      const newDist = Math.hypot(a.x - b.x, a.y - b.y);
      if (ps.dist <= 0) return;
      const ratio = newDist / ps.dist;
      const newK = Math.max(minK, Math.min(maxK, ps.k * ratio));
      const kRatio = newK / ps.k;
      // 锚点 = 起点两指中点（SVG 坐标），缩放后该点不动
      let tx = ps.midX - (ps.midX - ps.tx) * kRatio;
      let ty = ps.midY - (ps.midY - ps.ty) * kRatio;
      // 再叠加两指中点的平移分量（两指整体挪了，整图跟着挪）
      const newMid = toSvg((a.x + b.x) / 2, (a.y + b.y) / 2);
      tx += newMid.x - ps.midX;
      ty += newMid.y - ps.midY;
      setView({ k: newK, tx, ty });
      return;
    }

    if (n === 1 && panStartRef.current) {
      const ps = panStartRef.current;
      const { x: sx, y: sy } = toSvg(e.clientX, e.clientY);
      setView((v) => ({ ...v, tx: ps.tx + (sx - ps.sx), ty: ps.ty + (sy - ps.sy) }));
    }
  }, [toSvg, minK, maxK]);

  const endPointer = useCallback((e: React.PointerEvent) => {
    const svg = svgRef.current;
    svg?.releasePointerCapture?.(e.pointerId);
    pointersRef.current.delete(e.pointerId);
    syncCount();
    const n = pointersRef.current.size;
    if (n === 1) {
      // 从双指掉到单指：用剩余指重设平移起点，避免跳变
      const [remain] = [...pointersRef.current.values()];
      const { x: sx, y: sy } = toSvg(remain.x, remain.y);
      const v = viewRef.current;
      panStartRef.current = { sx, sy, tx: v.tx, ty: v.ty };
      pinchStartRef.current = null;
    } else if (n === 0) {
      panStartRef.current = null;
      pinchStartRef.current = null;
    }
  }, [svgRef, toSvg]);

  const onPointerUp = endPointer;
  const onPointerCancel = endPointer;

  // 围绕视口中心按钮缩放（+/-）
  const zoomBy = useCallback((factor: number) => {
    zoomAt(width / 2, height / 2, factor);
  }, [zoomAt, width, height]);

  // 重置/铺满。传 bounds 则按包围盒 fit（带 10% 余量居中），否则复位 k=1 居中。
  const fitToBounds = useCallback((bounds?: Bounds) => {
    if (bounds) {
      const bw = Math.max(1, bounds.maxX - bounds.minX);
      const bh = Math.max(1, bounds.maxY - bounds.minY);
      let k = Math.min(width / bw, height / bh) * 0.9;
      k = Math.max(minK, Math.min(maxK, k));
      const cx = (bounds.minX + bounds.maxX) / 2;
      const cy = (bounds.minY + bounds.maxY) / 2;
      setView({ k, tx: width / 2 - k * cx, ty: height / 2 - k * cy });
    } else {
      setView({ k: 1, tx: 0, ty: 0 });
    }
  }, [width, height, minK, maxK]);

  const resetView = useCallback(() => fitToBounds(undefined), [fitToBounds]);

  // 组件卸载时清指针状态，防泄漏
  useEffect(() => {
    return () => {
      pointersRef.current.clear();
      panStartRef.current = null;
      pinchStartRef.current = null;
    };
  }, []);

  return {
    view,
    setView,
    pointersCount,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    onPointerCancel,
    onWheel,
    zoomBy,
    zoomAt,
    resetView,
    fitToBounds,
    toSvg,
    svgToLogical,
    clampK,
  };
}
