// ---------------------------------------------------------------------------
// RelationshipView —— 关系合视图（合并冗余功能：关系图 + 关系演变 合一个入口）
//
// roadmap「合视图不合能力」+「静态图 = 末章快照」：两个本是同族的关系视图（都已是星图皮）
// 收进一个入口、内部切换：
//   · 关系网（全书静态星图，CharacterGraph）—— 默认
//   · 关系演变（带时间轴的星图快照 + 单对强度曲线，RelationshipTimeline）
// 两个子组件全挂载、只切显隐——切标签不丢已生成的数据、不白白重跑花钱。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { CharacterGraph } from "./CharacterGraph";
import { RelationshipTimeline } from "./RelationshipTimeline";

interface RelationshipViewProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

type Tab = "graph" | "reltime";
const TABS: { id: Tab; label: string }[] = [
  { id: "graph", label: "关系网" },
  { id: "reltime", label: "关系演变" },
];

export function RelationshipView(props: RelationshipViewProps) {
  const [tab, setTab] = useState<Tab>("graph");
  // 在关系网里点一个人 → 切到关系演变、聚焦这个人。每次点都换一个新对象引用，
  // 让关系演变那边的 effect 重新触发（同名连点也能重新聚焦）。
  const [focusPerson, setFocusPerson] = useState<{ name: string } | null>(null);
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
      <div className={tab === "graph" ? "" : "hidden"}>
        <CharacterGraph
          {...props}
          onSelectPerson={(name) => {
            setFocusPerson({ name });
            setTab("reltime");
          }}
        />
      </div>
      <div className={tab === "reltime" ? "" : "hidden"}>
        <RelationshipTimeline {...props} focusPerson={focusPerson} />
      </div>
    </div>
  );
}
