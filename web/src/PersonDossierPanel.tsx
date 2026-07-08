// ---------------------------------------------------------------------------
// PersonDossierPanel — 人物志的 live 取数包壳（真 app 用）。
//
// 把 PersonDossier（纯展示）接上真端点，落实两条架构约束：
//   · 全员出来：名册 = /agent/character-graph 的 nodes（章脉派生、几百人全在）;
//     处境 = /agent/character-arc（一次拿主要角色的逐章处境，可缺）。
//   · 按需精确：点名册里的人才现跑 /agent/character-stance（Toulmin 正反取证 + 争议度），
//     结果缓进 stanceMap，不预算全员。立场轴（尊汉/篡逆…）可编辑——每本书换轴，改轴清缓存重跑。
//
// 契约同别的按需视图：BYOK、失败静默/提示、命中缓存秒出。展示逻辑全在 PersonDossier，
// 本壳只管取数 + 状态。
// ---------------------------------------------------------------------------

import { useCallback, useState } from "react";
import {
  PersonDossier,
  type DossierArc,
  type DossierArcPoint,
  type DossierEvid,
  type DossierRosterEntry,
  type DossierStance,
} from "./PersonDossier";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { RunningProcess } from "./runProcess";

interface Props {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export function PersonDossierPanel({ sessionId, provider, apiKey, model, baseUrl }: Props) {
  const [roster, setRoster] = useState<DossierRosterEntry[] | null>(null);
  const [stanceMap, setStanceMap] = useState<Map<string, DossierStance>>(() => new Map());
  const [arc, setArc] = useState<DossierArc[]>([]);
  const [loadingRoster, setLoadingRoster] = useState(false);
  const [loadingName, setLoadingName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [axisPos, setAxisPos] = useState("尊汉扶主");
  const [axisNeg, setAxisNeg] = useState("篡逆自立");

  function reqBody(extra: Record<string, unknown> = {}): Record<string, unknown> {
    const b: Record<string, unknown> = { book_session_id: sessionId, provider, api_key: apiKey, ...extra };
    if (model) b.model = model;
    if (baseUrl) b.base_url = baseUrl;
    return b;
  }

  async function loadRoster() {
    setLoadingRoster(true);
    setError(null);
    try {
      const gRes = await fetch("/api/agent/character-graph", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(reqBody()),
      });
      if (!gRes.ok) {
        const j = (await gRes.json().catch(() => null)) as { detail?: { message?: string } } | null;
        throw new Error(j?.detail?.message ?? `名册请求失败（${gRes.status}）`);
      }
      const g = (await gRes.json()) as { nodes?: string[] };
      const names = g.nodes ?? [];
      if (names.length === 0) {
        setError("没抽出人物名册，稍后重试。");
        return;
      }
      setRoster(names.map((n) => ({ name: n, hasStance: false })));
      // 处境弧线（可选、一次拿主要角色；失败不阻断名册）
      try {
        const aRes = await fetch("/api/agent/character-arc", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody()),
        });
        if (aRes.ok) {
          const a = (await aRes.json()) as {
            characters?: { name: string; points?: DossierArcPoint[] }[];
          };
          setArc(
            (a.characters ?? []).map((c) => ({
              name: c.name,
              points: (c.points ?? []).map((p) => ({
                chapter: p.chapter,
                fortune: p.fortune,
                evidence: p.evidence,
                verified: p.verified,
              })),
            })),
          );
        }
      } catch {
        /* 处境可缺，不阻断 */
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingRoster(false);
    }
  }

  const fetchStance = useCallback(
    async (name: string) => {
      if (stanceMap.has(name) || loadingName === name) return;
      setLoadingName(name);
      try {
        const res = await fetch("/api/agent/character-stance", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody({ character: name, pos_label: axisPos, neg_label: axisNeg })),
        });
        if (res.ok) {
          const d = (await res.json()) as {
            scanned?: boolean;
            net: number;
            dispute: number;
            dispute_reason?: string;
            pro: DossierEvid[];
            con: DossierEvid[];
          };
          if (d.scanned) {
            setStanceMap((m) =>
              new Map(m).set(name, {
                name,
                faction: "",
                net: d.net,
                dispute: d.dispute,
                dispute_reason: d.dispute_reason,
                pro: d.pro,
                con: d.con,
              }),
            );
          }
        }
      } catch {
        /* 单人失败静默，面板继续 */
      } finally {
        setLoadingName((cur) => (cur === name ? null : cur));
      }
    },
    // reqBody 闭包依赖这些；axis 变了重建，配合清缓存重跑
    [stanceMap, loadingName, axisPos, axisNeg, sessionId, provider, apiKey, model, baseUrl],
  );

  function changeAxis(which: "pos" | "neg", val: string) {
    if (which === "pos") setAxisPos(val);
    else setAxisNeg(val);
    setStanceMap(new Map()); // 换轴 → 旧立场作废，重新点人现跑
    setLoadingName(null);
  }

  if (!roster) {
    return (
      <FeatureEntryCard
        title="人物志"
        lead="全书人物一册在手：左边全员名册（可搜），点谁看谁——他的立场（正反证据 + 争议度）、处境转折，都锚原文。点开才现跑他的精确分析。"
        actionLabel="开人物志"
        loadingLabel="读全书出人物名册中…"
        onAction={loadRoster}
        loading={loadingRoster}
        disabled={!apiKey}
        hint="名册来自章脉（整本读一次），点人现跑精确分析；命中缓存秒出"
        error={error}
      >
        {loadingRoster && (
          <RunningProcess label="读全书出人物名册" hint="整本书出章脉、派生全员名册；命中缓存秒出。" />
        )}
      </FeatureEntryCard>
    );
  }

  return (
    <div className="pt-4">
      <h3
        className="text-base font-bold text-[var(--color-ink)] mb-3"
        style={{ fontFamily: "var(--font-display)" }}
      >
        人物志
      </h3>
      {/* 立场轴可配：每本书换（史书=尊汉/篡逆，别的书换别的）；改轴清缓存重跑 */}
      <div className="mb-3 flex items-center gap-2 flex-wrap text-sm">
        <span className="text-[var(--color-ink-muted)]">立场轴：</span>
        <input
          value={axisPos}
          onChange={(e) => changeAxis("pos", e.target.value)}
          className="w-28 px-2 py-1 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] outline-none focus:border-[var(--color-seal)]"
        />
        <span className="text-[var(--color-ink-muted)]">↔</span>
        <input
          value={axisNeg}
          onChange={(e) => changeAxis("neg", e.target.value)}
          className="w-28 px-2 py-1 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] outline-none focus:border-[var(--color-seal)]"
        />
        <span className="text-xs text-[var(--color-ink-muted)]">改轴后点人重新现跑</span>
      </div>
      <PersonDossier
        roster={roster}
        stance={[...stanceMap.values()]}
        arc={arc}
        axisPos={axisPos}
        axisNeg={axisNeg}
        onSelectPerson={fetchStance}
        loadingName={loadingName}
      />
    </div>
  );
}
