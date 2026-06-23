// ---------------------------------------------------------------------------
// ChapterCurves —— 逐章曲线合视图（合并冗余功能：节奏 ⊂ 叙事曲线 + 人物弧线 三合一）
//
// roadmap「合视图不合能力」：把三件逐章曲线收进一个入口、内部切换，不丢任何能力。
//   · 叙事曲线（山水长卷，四维：张力/情感/视角/主支线）—— 默认，最全
//   · 人物弧线（工笔花鸟，角色戏份/处境）
//   · 节奏（轻量张力速览，⊂ 叙事曲线的张力维，留作快看）
// 三个子组件全挂载、只切显隐——切标签不丢已生成的数据、不白白重跑花钱。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { CharacterArc } from "./CharacterArc";
import { NarrativeCurve } from "./NarrativeCurve";
import { PacingCurve } from "./PacingCurve";

interface ChapterCurvesProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

type Tab = "narrative" | "chararc" | "pacing";
const TABS: { id: Tab; label: string }[] = [
  { id: "narrative", label: "叙事曲线" },
  { id: "chararc", label: "人物弧线" },
  { id: "pacing", label: "节奏" },
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
      <div className={tab === "pacing" ? "" : "hidden"}>
        <PacingCurve {...props} />
      </div>
    </div>
  );
}
