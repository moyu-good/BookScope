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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  PersonDossier,
  type DossierArc,
  type DossierArcPoint,
  type DossierEvid,
  type DossierRosterEntry,
  type DossierStance,
} from "./PersonDossier";
import type { QuadPoint } from "./StanceQuadrant";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { RunningProcess } from "./runProcess";

interface Props {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

// 关系图边的最小形态：只取算戏份（连接度）用得上的字段。
interface GraphEdgeLite {
  source: string;
  target: string;
  strength?: number;
}
// 批量粗定位一项（/agent/batch-stance 的 positions[i]）。
interface BatchPos {
  name: string;
  net: number;
  dispute: number;
  brief?: string;
}

export function PersonDossierPanel({ sessionId, provider, apiKey, model, baseUrl }: Props) {
  const [roster, setRoster] = useState<DossierRosterEntry[] | null>(null);
  const [stanceMap, setStanceMap] = useState<Map<string, DossierStance>>(() => new Map());
  const [arc, setArc] = useState<DossierArc[]>([]);
  const [loadingRoster, setLoadingRoster] = useState(false);
  const [loadingName, setLoadingName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [axisPos, setAxisPos] = useState("");
  const [axisNeg, setAxisNeg] = useState("");
  // 立场格局批量粗定位：关系图边（算戏份）+ 一次批量定位结果 + loading。
  const [edges, setEdges] = useState<GraphEdgeLite[]>([]);
  const [positions, setPositions] = useState<BatchPos[] | null>(null);
  const [batchLoading, setBatchLoading] = useState(false);
  const batchStartedRef = useRef(false); // 单次触发去重：只跑一次批量，换轴时重置

  function reqBody(extra: Record<string, unknown> = {}): Record<string, unknown> {
    const b: Record<string, unknown> = { book_session_id: sessionId, provider, api_key: apiKey, ...extra };
    if (model) b.model = model;
    if (baseUrl) b.base_url = baseUrl;
    return b;
  }

  // 按书自动建议立场轴：换书 / key 到位时，若两端都还空（没被用户改过），就问后端这本书
  // 围绕的核心立场对立，填进去当默认（用户仍可改）。判不出（工具书 / 诗集）或失败就保持空，
  // 让用户自己填；只在空时填，绝不覆盖用户已输入的。
  useEffect(() => {
    if (!sessionId || !apiKey) return;
    if (axisPos !== "" || axisNeg !== "") return;
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/agent/suggest-stance-axis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(reqBody()),
        });
        if (!res.ok) return;
        const d = (await res.json()) as { pos?: string; neg?: string; scanned?: boolean };
        if (cancelled) return;
        if (d.scanned && d.pos && d.neg) {
          setAxisPos(d.pos);
          setAxisNeg(d.neg);
        }
      } catch {
        /* 建议失败静默，保持空让用户自己填 */
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, apiKey]);

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
      const g = (await gRes.json()) as { nodes?: string[]; edges?: GraphEdgeLite[] };
      const names = g.nodes ?? [];
      if (names.length === 0) {
        setError("没抽出人物名册，稍后重试。");
        return;
      }
      setRoster(names.map((n) => ({ name: n, hasStance: false })));
      // 边留着算戏份（连接度）：定象限里谁进前 20、谁的点大 / 靠右（主角）——都是可数事实，不靠 LLM 猜。
      setEdges(g.edges ?? []);
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
      if (!axisPos || !axisNeg) return; // 没立场轴不跑单人 Toulmin（后端 pos/neg 必填，避免 422）
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

  // 戏份 = 该人所有关系边 strength 之和（连接度）。定象限的 x（主角靠右）+ 点大小，也用来挑前 20。
  const degreeByName = useMemo(() => {
    const d = new Map<string, number>();
    for (const e of edges) {
      d.set(e.source, (d.get(e.source) ?? 0) + (e.strength ?? 1));
      d.set(e.target, (d.get(e.target) ?? 0) + (e.strength ?? 1));
    }
    return d;
  }, [edges]);

  // 名册按戏份降序取前 20 主要人物喂批量定位（配角在下面名册搜，不挤进象限）。
  const topNames = useMemo(() => {
    if (!roster) return [];
    return [...roster]
      .map((r) => r.name)
      .sort((a, b) => (degreeByName.get(b) ?? 0) - (degreeByName.get(a) ?? 0))
      .slice(0, 20);
  }, [roster, degreeByName]);

  // 进视图 + 有立场轴（自动建议或用户填）后，一次批量把前 20 人粗定位到立场轴上。
  // 失败 / 判不出 → positions 置空，前端不画象限、退回按需点人（优雅退）。ref 去重只跑一次。
  useEffect(() => {
    if (!roster || !axisPos || !axisNeg || topNames.length === 0) return;
    if (batchStartedRef.current) return;
    batchStartedRef.current = true;
    setBatchLoading(true);
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/agent/batch-stance", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(
            reqBody({ characters: topNames, pos_label: axisPos, neg_label: axisNeg }),
          ),
        });
        if (!res.ok) {
          if (!cancelled) setPositions([]);
          return;
        }
        const d = (await res.json()) as { positions?: BatchPos[]; scanned?: boolean };
        if (cancelled) return;
        setPositions(d.scanned ? (d.positions ?? []) : []);
      } catch {
        if (!cancelled) setPositions([]);
      } finally {
        if (!cancelled) setBatchLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roster, axisPos, axisNeg, topNames]);

  // 象限点：net/dispute 先用批量粗定位；某人点开跑过单人 Toulmin 后，用它更准的 net/dispute 覆盖（渐进精修）。
  const quadPoints = useMemo<QuadPoint[]>(() => {
    if (!positions || positions.length === 0) return [];
    return positions.map((p) => {
      const refined = stanceMap.get(p.name);
      const deg = degreeByName.get(p.name) ?? 1;
      return {
        name: p.name,
        x: deg,
        y: refined ? refined.net : p.net,
        group: "人物",
        size: deg,
        dispute: refined ? refined.dispute : p.dispute,
        disputeReason: refined?.dispute_reason || p.brief || "",
        pro: [],
        con: [],
      };
    });
  }, [positions, stanceMap, degreeByName]);

  function changeAxis(which: "pos" | "neg", val: string) {
    if (which === "pos") setAxisPos(val);
    else setAxisNeg(val);
    setStanceMap(new Map()); // 换轴 → 旧立场作废，重新点人现跑
    setLoadingName(null);
    // 换轴也要重新批量定位：清结果 + 复位去重 ref，触发上面的 effect 再跑一次。
    setPositions(null);
    setBatchLoading(false);
    batchStartedRef.current = false;
  }

  if (!roster) {
    return (
      <FeatureEntryCard
        title="立场格局"
        lead="把书里的主要人物一口气打在一张立场图上：横看戏份，纵看立场倾向，谁站哪边、谁有争议一眼看清。想看细的点开谁，正反两面的证据、处境起落，每条都能翻回原文。"
        actionLabel="翻开立场格局"
        loadingLabel="正在通读全书，整理人物…"
        onAction={loadRoster}
        loading={loadingRoster}
        disabled={!apiKey}
        hint="先通读全书列出人物、把主要人物一次定位到立场图上；点开某个人才细看他的正反取证。读过一次后再看就快。"
        error={error}
      >
        {loadingRoster && (
          <RunningProcess label="正在通读全书，整理人物" hint="先把整本书读一遍列出人物；读过一次后再看就快。" />
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
        立场格局
      </h3>
      {/* 立场轴可配：每本书换（史书=尊汉/篡逆，别的书换别的）；改轴清缓存重跑 */}
      <div className="mb-3 flex items-center gap-2 flex-wrap text-sm">
        <span className="text-[var(--color-ink-muted)]">立场轴：</span>
        <input
          value={axisPos}
          onChange={(e) => changeAxis("pos", e.target.value)}
          placeholder="正端（如 尊汉扶主 / 忠唐）"
          className="w-28 px-2 py-1 rounded border border-[var(--color-rule)] bg-[var(--color-paper)] text-[var(--color-ink)] outline-none focus:border-[var(--color-seal)]"
        />
        <span className="text-[var(--color-ink-muted)]">↔</span>
        <input
          value={axisNeg}
          onChange={(e) => changeAxis("neg", e.target.value)}
          placeholder="负端（如 篡逆自立 / 附燕）"
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
        quadPoints={quadPoints}
        quadLoading={batchLoading}
      />
    </div>
  );
}
