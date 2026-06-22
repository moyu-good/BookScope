// ---------------------------------------------------------------------------
// AnalysisOverlay —— 阅读界面里的「鉴」：就地跑分析，不跳走（WP-reading-experience §2.5）
//
// 读着读着点「鉴」→ 这个大浮层盖在阅读器之上（书页留在底下、变暗但不卸载），挑一项分析
// 就在这里跑出结果。收起即回到刚才读的位置。绝不跳回主页 —— 分析就在阅读界面里搞完。
//
// 复用现有 22 个分析组件（props 形态一致：sessionId/provider/apiKey/model/baseUrl）。
// 功能按「读着用得上」重排（§point 4）：读中常用 → 人物 → 情节 → 查证/学习。
// 多数分析是整本口径,结论里点章号能回到原文那一章(目录跳)。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { AgentOrchestrate } from "./AgentOrchestrate";
import { AnnotatedReader } from "./AnnotatedReader";
import { ArgumentStructure } from "./ArgumentStructure";
import { CharacterArc } from "./CharacterArc";
import { CharacterFlow } from "./CharacterFlow";
import { CharacterGraph } from "./CharacterGraph";
import { CharacterVoice } from "./CharacterVoice";
import { ConceptEvolution } from "./ConceptEvolution";
import { ConsistencyScan } from "./ConsistencyScan";
import { EntityRecall } from "./EntityRecall";
import { ForeshadowArcs } from "./ForeshadowArcs";
import { MotifTracking } from "./MotifTracking";
import { NarrativeCurve } from "./NarrativeCurve";
import { PacingCurve } from "./PacingCurve";
import { Recap } from "./Recap";
import { RelationshipTimeline } from "./RelationshipTimeline";
import { RevisionList } from "./RevisionList";
import { StudyCards } from "./StudyCards";
import { StyleIssues } from "./StyleIssues";
import { SubplotWeave } from "./SubplotWeave";
import { Timeline } from "./Timeline";

interface AnalysisOverlayProps {
  sessionId: string;
  bookTitle: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
  /** 你正读到第几章——带进来让能按章的功能（前情回顾）对准在读处。 */
  currentChapter?: number | null;
  onClose: () => void;
}

type Feat = {
  id: string;
  label: string;
  hint: string;
};

// 读着用得上的排序：读中常用 → 人物 → 情节 → 查证 / 学习。
const GROUPS: { title: string; feats: Feat[] }[] = [
  {
    title: "读着用",
    feats: [
      { id: "orchestrate", label: "给目标", hint: "说一句你想搞清的事，它编排几个分析、综合带证据回答" },
      { id: "recap", label: "前情回顾", hint: "无剧透地回顾到某一章为止发生了什么" },
      { id: "annotate", label: "行间批注", hint: "原文行间浮出带证据的朱砂批注（伏笔/矛盾/母题/人物）" },
    ],
  },
  {
    title: "人物",
    feats: [
      { id: "graph", label: "关系图", hint: "谁和谁、什么关系，每条边点得到原文" },
      { id: "reltime", label: "关系演变", hint: "两人关系逐章升降，转折钉原文" },
      { id: "flow", label: "叙事流", hint: "谁何时入场、哪几章群戏" },
      { id: "chararc", label: "人物弧线", hint: "角色逐章的戏份与处境起落" },
      { id: "charvoice", label: "声口一致", hint: "标出「这句不像他说的」" },
    ],
  },
  {
    title: "情节",
    feats: [
      { id: "foreshadow", label: "伏笔回收", hint: "哪个伏笔埋了、收没收" },
      { id: "subplot", label: "支线编织", hint: "每条支线何时活跃、在哪交汇" },
      { id: "timeline", label: "时间线", hint: "多线倒叙也理清真实时序" },
      { id: "pacing", label: "节奏曲线", hint: "逐章张力起伏" },
      { id: "narrative", label: "叙事曲线", hint: "逐章张力/情感/视角/主支线" },
    ],
  },
  {
    title: "查证 / 学习",
    feats: [
      { id: "entity", label: "实体回溯", hint: "一个人/物/地点全书每次出现" },
      { id: "motif", label: "母题追踪", hint: "一个主题全书每次复现" },
      { id: "concept", label: "概念演进", hint: "一个概念全书怎么发展" },
      { id: "consistency", label: "一致性", hint: "前后设定矛盾" },
      { id: "style", label: "文体体检", hint: "用词重复/视角越界等毛病" },
      { id: "argument", label: "论点结构", hint: "论证骨架 + 证据" },
      { id: "cards", label: "知识卡片", hint: "知识点卡 + 自测" },
      { id: "revision", label: "改稿清单", hint: "诊断聚成可勾选的改稿清单" },
    ],
  },
];

const ALL_FEATS: Record<string, Feat> = Object.fromEntries(
  GROUPS.flatMap((g) => g.feats).map((f) => [f.id, f]),
);

export function AnalysisOverlay({
  sessionId,
  bookTitle,
  provider,
  apiKey,
  model,
  baseUrl,
  currentChapter,
  onClose,
}: AnalysisOverlayProps) {
  const [active, setActive] = useState<string | null>(null);
  const shared = { sessionId, provider, apiKey, model, baseUrl };

  function renderActive() {
    switch (active) {
      case "orchestrate":
        return <AgentOrchestrate {...shared} onDrill={() => {}} />;
      case "recap":
        return <Recap {...shared} prefillChapter={currentChapter ?? undefined} />;
      case "annotate":
        return <AnnotatedReader {...shared} />;
      case "graph":
        return <CharacterGraph {...shared} />;
      case "reltime":
        return <RelationshipTimeline {...shared} />;
      case "flow":
        return <CharacterFlow {...shared} />;
      case "chararc":
        return <CharacterArc {...shared} />;
      case "charvoice":
        return <CharacterVoice {...shared} />;
      case "foreshadow":
        return <ForeshadowArcs {...shared} />;
      case "subplot":
        return <SubplotWeave {...shared} />;
      case "timeline":
        return <Timeline {...shared} />;
      case "pacing":
        return <PacingCurve {...shared} />;
      case "narrative":
        return <NarrativeCurve {...shared} />;
      case "entity":
        return <EntityRecall {...shared} />;
      case "motif":
        return <MotifTracking {...shared} />;
      case "concept":
        return <ConceptEvolution {...shared} />;
      case "consistency":
        return <ConsistencyScan {...shared} />;
      case "style":
        return <StyleIssues {...shared} />;
      case "argument":
        return <ArgumentStructure {...shared} />;
      case "cards":
        return <StudyCards {...shared} />;
      case "revision":
        return <RevisionList {...shared} bookTitle={bookTitle} />;
      default:
        return null;
    }
  }

  return (
    <div className="fixed inset-0 z-50">
      {/* 背景:让书页留在底下、变暗（不卸载，收起即回原处） */}
      <button
        type="button"
        aria-label="收起，回到阅读"
        onClick={onClose}
        className="absolute inset-0"
        style={{ background: "color-mix(in oklch, var(--color-ink) 45%, transparent)" }}
      />
      <div className="absolute inset-2 sm:inset-6 rounded-lg bg-[var(--color-paper)] border border-[var(--color-rule)] overflow-hidden flex flex-col">
        {/* 头 */}
        <div className="flex items-center justify-between px-4 py-2.5 border-b border-[var(--color-rule)]">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className="text-sm font-bold text-[var(--color-seal)]"
              style={{ fontFamily: "var(--font-display)" }}
            >
              鉴
            </span>
            <span className="text-sm text-[var(--color-ink)] truncate">
              {active ? ALL_FEATS[active]?.label : "分析这本书"}
            </span>
            <span className="text-xs text-[var(--color-ink-muted)] truncate hidden sm:inline">
              · {bookTitle}
              {currentChapter ? ` · 你读到第 ${currentChapter} 章` : ""}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-sm text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] shrink-0"
          >
            收起，回到阅读 ✕
          </button>
        </div>

        {/* 体:左功能栏 + 右结果区 */}
        <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-[12rem_1fr]">
          <nav className="border-b md:border-b-0 md:border-r border-[var(--color-rule)] overflow-y-auto p-2 bg-[var(--color-paper-sunken)]">
            {GROUPS.map((g) => (
              <div key={g.title} className="mb-2">
                <div className="text-xs text-[var(--color-ink-muted)] px-2 py-1">{g.title}</div>
                <div className="flex flex-wrap md:flex-col gap-1">
                  {g.feats.map((f) => {
                    const on = f.id === active;
                    return (
                      <button
                        key={f.id}
                        type="button"
                        onClick={() => setActive(f.id)}
                        title={f.hint}
                        className="text-left text-xs px-2.5 py-1.5 rounded transition-colors"
                        style={
                          on
                            ? { background: "var(--color-seal-soft)", color: "var(--color-seal)" }
                            : { color: "var(--color-ink)" }
                        }
                      >
                        {f.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>

          <div className="overflow-y-auto p-4 sm:p-6">
            {active ? (
              <>
                <p className="text-xs text-[var(--color-ink-muted)] mb-3 leading-relaxed">
                  {ALL_FEATS[active]?.hint}
                </p>
                {renderActive()}
              </>
            ) : (
              <div className="h-full flex items-center justify-center text-center">
                <div className="max-w-sm">
                  <p className="text-sm text-[var(--color-ink)] mb-2" style={{ fontFamily: "var(--font-display)" }}>
                    读着读着，挑一项分析
                  </p>
                  <p className="text-xs text-[var(--color-ink-muted)] leading-relaxed">
                    左边挑一项，就在这儿跑、就在这儿看——结论都带原文证据，收起就回到你刚读的地方。
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
