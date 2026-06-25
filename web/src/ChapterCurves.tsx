// ---------------------------------------------------------------------------
// ChapterCurves —— 逐章曲线合视图（叙事曲线 + 人物弧线 二合一）
//
// roadmap「合视图不合能力」：把逐章曲线收进一个入口、内部切换，不丢任何能力。
//   · 叙事曲线（事件密度长卷：每章高度=事件数+转折数，朱砂点标转折，点章看发生的事）—— 默认
//   · 人物弧线（工笔花鸟，角色戏份/处境）
// 1.5.x「砍三为二」：原来的独立「节奏」(画 tension 标量) 跟叙事曲线画的是同一个东西、重复，
// 已撤——新版叙事曲线纵轴换成能数的事，节奏维已并进去。子组件全挂载、只切显隐，切标签不丢数据。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { CharacterArc } from "./CharacterArc";
import { NarrativeCurve } from "./NarrativeCurve";

interface ChapterCurvesProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

type Tab = "narrative" | "chararc";
const TABS: { id: Tab; label: string }[] = [
  { id: "narrative", label: "叙事曲线" },
  { id: "chararc", label: "人物弧线" },
];

export function ChapterCurves(props: ChapterCurvesProps) {
  const [tab, setTab] = useState<Tab>("narrative");
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-1">
        {TABS.map((t) => {
          const on = t.id === tab;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className="text-xs px-2.5 py-1 rounded border transition-colors"
              style={
                on
                  ? { borderColor: "var(--color-seal)", color: "var(--color-seal)" }
                  : { borderColor: "var(--color-rule)", color: "var(--color-ink-muted)" }
              }
            >
              {t.label}
            </button>
          );
        })}
      </div>
      <div className={tab === "narrative" ? "" : "hidden"}>
        <NarrativeCurve {...props} />
      </div>
      <div className={tab === "chararc" ? "" : "hidden"}>
        <CharacterArc {...props} />
      </div>
    </div>
  );
}
