// ---------------------------------------------------------------------------
// vizFocus — 联动总线(可视化 Phase 0 地基,依托 docs/design/WP-viz-phase0-foundation.md)
//
// 干一件事:让多个镜头(关系图 / 关系演变 / 依据链网 …)互相说话。
// 一个镜头 select 一个对象 → 广播;别的镜头订阅到、认得就聚焦/高亮,不认得就忽略。
// 收编原来散落在 App 的几套跨视图机制(onSelectPerson 点人跳关系演变、drillInto / goalPrefill
// 钻取预填、CrossDimRelay / relayToGoal 互相递)——从根上统一成一根总线,不再各做各的。
//
// "选中对象" = 一个跨题材通用的原子实体引用 EntityRef(卢曼原子节点):人 / 概念 / 条款 /
// 事件… 一套结构,任何题材任何镜头都说同一种话。
//
// 接入是 opt-in、可逆:镜头不订阅就对总线无感,行为跟没有总线时完全一致;
// 脱离分析台(没 Provider)时 useVizFocus 返回安全空实现,镜头照常单独工作。
// ---------------------------------------------------------------------------

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

// 跨题材的原子实体种类。新镜头有新种类就往这加(如将来的地图 place 已在内)。
export type EntityKind =
  | "person"
  | "concept"
  | "event"
  | "clause"
  | "policy"
  | "argument"
  | "place"
  | "chapter"
  | "motif"
  | "foreshadow";

// 一个被选中/被聚焦的对象。id 是稳定标识(人名 / 条款号 / 概念名…),
// label 给展示,bookSessionId 定位哪本书/哪份卷宗,source 可选带上锚原文。
export interface EntityRef {
  kind: EntityKind;
  id: string;
  label: string;
  bookSessionId: string;
  source?: { chapter?: number; quote?: string };
}

export interface SetFocusOptions {
  // 把某个镜头顶到前面看(对应 App 的 mode 值,如 "graph" / "reltime" / "redheadDeps")。
  // 不传 = 只广播 focus、不换视图(同屏/当前镜头内联动)。
  switchTo?: string;
}

interface VizFocusValue {
  focus: EntityRef | null;
  setFocus: (ref: EntityRef | null, opts?: SetFocusOptions) => void;
}

const VizFocusContext = createContext<VizFocusValue | null>(null);

// 没有 Provider 时的安全空实现:focus 恒 null、setFocus 无操作。
// 镜头 opt-in 用了 useVizFocus 但被单独渲染(如脱离分析台/单测)也不炸,行为等同没接总线。
const NOOP: VizFocusValue = { focus: null, setFocus: () => {} };

/**
 * 包在分析台外层。onSwitchMode 由 App 传入(把 switchTo 落到 App 的 mode 状态),
 * 不传则 switchTo 静默忽略(只广播 focus)。
 */
export function VizFocusProvider({
  children,
  onSwitchMode,
}: {
  children: ReactNode;
  onSwitchMode?: (mode: string) => void;
}) {
  const [focus, setFocusState] = useState<EntityRef | null>(null);

  const setFocus = useCallback(
    (ref: EntityRef | null, opts?: SetFocusOptions) => {
      setFocusState(ref);
      if (opts?.switchTo && onSwitchMode) onSwitchMode(opts.switchTo);
    },
    [onSwitchMode],
  );

  const value = useMemo(() => ({ focus, setFocus }), [focus, setFocus]);
  return <VizFocusContext.Provider value={value}>{children}</VizFocusContext.Provider>;
}

/** 镜头读/写当前焦点。没 Provider 返回空实现(可逆:不接总线不受影响)。 */
export function useVizFocus(): VizFocusValue {
  return useContext(VizFocusContext) ?? NOOP;
}

/**
 * 便捷判断:某个 entity 是不是当前焦点(镜头拿来决定高不高亮)。
 * kind + id 必须都对上;传了 bookSessionId 且两边都有值就一并核(跨书不误亮)。
 */
export function isFocused(
  focus: EntityRef | null,
  kind: EntityKind,
  id: string,
  bookSessionId?: string,
): boolean {
  if (!focus) return false;
  if (focus.kind !== kind || focus.id !== id) return false;
  if (bookSessionId && focus.bookSessionId && focus.bookSessionId !== bookSessionId) {
    return false;
  }
  return true;
}
