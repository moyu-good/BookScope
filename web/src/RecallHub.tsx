// 全书回溯（整合 round2 B）——把「实体回溯 / 概念演进 / 母题追踪」三个长得一样的入口合成一个。
//
// 三者是同一个交互（输一个词 → 全书回溯它 → 竖向带原文的轨迹），只是追的对象不同（具体实体 /
// 抽象概念 / 母题符号）。以前用户得先想清「它算实体还是概念还是母题」再挑对功能——让用户当裁缝。
// 这里合成一个入口，进来选（或 drill-into 自动切）追什么。
//
// **合入口不合引擎**（WP-consolidation-round2 §B.3）：三个后端端点保留（entity-recall /
// concept-evolution / motif-tracking 各有各的 prompt 侧重，实体重「在哪出现干嘛」、概念重「怎么
// 发展」、母题重「怎么体现」，合引擎会稀释质量）。这里只是把前端三个入口收成一个带切换的壳，
// 底下仍挂原来那三个组件、各打各的后端。

import { useEffect, useState } from "react";
import { ConceptEvolution } from "./ConceptEvolution";
import { EntityRecall } from "./EntityRecall";
import { MotifTracking } from "./MotifTracking";

type RecallKind = "entity" | "concept" | "motif";
type Prefill = { value: string; token: number } | null;

const KINDS: { id: RecallKind; label: string; hint: string }[] = [
  { id: "entity", label: "实体", hint: "追一个人 / 物 / 地点：全书每次出现，在哪章、在做什么。" },
  { id: "concept", label: "概念", hint: "追一个概念：全书怎么一步步发展，每阶段被怎么用 / 深化。" },
  { id: "motif", label: "母题", hint: "追一个主题 / 母题：全书哪些地方复现、各处怎么体现。" },
];

interface RecallHubProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  // drill-into 从 agent 编排进来的预填（哪个 token 变了就切到那类、自动跑）。
  entityPrefill?: Prefill;
  conceptPrefill?: Prefill;
  motifPrefill?: Prefill;
}

export function RecallHub({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
  entityPrefill,
  conceptPrefill,
  motifPrefill,
}: RecallHubProps) {
  const [kind, setKind] = useState<RecallKind>("entity");

  // drill-into：某类 prefill 令牌一变，就切到那类（子组件自己的 prefill effect 会自动跑一次）。
  // 一次 drill 只动一个 prefill，所以对应的 effect 触发、切到它。
  useEffect(() => {
    if (entityPrefill?.token) setKind("entity");
  }, [entityPrefill?.token]);
  useEffect(() => {
    if (conceptPrefill?.token) setKind("concept");
  }, [conceptPrefill?.token]);
  useEffect(() => {
    if (motifPrefill?.token) setKind("motif");
  }, [motifPrefill?.token]);

  const common = { sessionId, provider, apiKey, model, baseUrl };
  const activeHint = KINDS.find((k) => k.id === kind)?.hint ?? "";

  return (
    <div>
      {/* 追什么：三档切换。善本风分段（纸底 + 朱砂选中），不露原生控件。 */}
      <div
        className="inline-flex rounded-md p-0.5 mb-2"
        style={{ background: "var(--color-paper-sunken)" }}
      >
        {KINDS.map((k) => (
          <button
            key={k.id}
            type="button"
            onClick={() => setKind(k.id)}
            className="px-3 py-1.5 text-sm rounded transition-colors"
            style={
              kind === k.id
                ? { background: "var(--color-seal)", color: "#fff", fontFamily: "var(--font-display)" }
                : { color: "var(--color-ink-muted)" }
            }
          >
            追{k.label}
          </button>
        ))}
      </div>
      <p className="mb-3 text-xs text-[var(--color-ink-muted)] leading-relaxed">{activeHint}</p>

      {/* 底下挂原来那三个组件之一——各打各的后端，能力不动 */}
      {kind === "entity" && <EntityRecall {...common} prefill={entityPrefill} />}
      {kind === "concept" && <ConceptEvolution {...common} prefill={conceptPrefill} />}
      {kind === "motif" && <MotifTracking {...common} prefill={motifPrefill} />}
    </div>
  );
}
