// ---------------------------------------------------------------------------
// NarrativeCurve — 多维叙事曲线（WP-multidim-narrative-curve，probe GO）
//
// 点生成 → 调 /api/agent/narrative-curve（整本进上下文逐章抽四维）→ 画成「山水长卷」品读视图
// （见 ShanshuiCurve）：山势=张力起落、平缓处留白成江水、朱砂点=核验过的高潮章，点任一章看
// 那章原文。张力诚实呈现——只给相对档（平缓/起伏/紧张/高潮），不印"9/10"那种假精确：probe
// 实测张力相对形状跨次稳（σ≈0.5），但绝对分会抖 ±1，所以画形状、不当测量值显示。
// 情感/视角维度噪声较大（probe：情感会翻号、视角在某人/群像间晃），只在选中章的明细里附带列出，
// 标"模型判读"，不画进主图。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { ShanshuiCurve, tensionBand, type CurveChapter } from "./ShanshuiCurve";

interface NarrativeCurveProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export function NarrativeCurve({
  sessionId,
  provider,
  apiKey,
  model,
  baseUrl,
}: NarrativeCurveProps) {
  const [chapters, setChapters] = useState<CurveChapter[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [trace, setTrace] = useState<RunTrace | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    setSelected(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/narrative-curve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        const j = (await resp.json().catch(() => null)) as
          | { detail?: { message?: string } }
          | null;
        throw new Error(j?.detail?.message ?? `请求失败（${resp.status}）`);
      }
      const data = (await resp.json()) as {
        chapters: CurveChapter[];
        scanned?: boolean;
        trace?: RunTrace;
      };
      setTrace(data.trace ?? null);
      if (!data.chapters || data.chapters.length === 0) {
        setError("没抽出叙事曲线，稍后重试。");
      } else {
        setChapters([...data.chapters].sort((p, q) => p.chapter - q.chapter));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  if (!chapters) {
    return (
      <div className="pt-4">
        <h3
          className="text-base font-bold text-[var(--color-ink)] mb-1"
          style={{ fontFamily: "var(--font-display)" }}
        >
          叙事曲线
        </h3>
        <p className="text-sm text-[var(--color-ink-muted)] mb-3">
          把全书逐章张力画成一幅水墨山水长卷——山势起落就是剧情松紧，一眼看出整本书是个什么"形状"，点任一章看那章原文。
        </p>
        <button
          type="button"
          onClick={load}
          disabled={loading || !apiKey}
          className="text-sm px-4 py-2 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] hover:text-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "读全书出曲线中（约 1 分钟）…" : "生成叙事曲线"}
        </button>
        {error && (
          <p className="mt-2 text-sm" style={{ color: "var(--color-seal)" }}>
            {error}
          </p>
        )}
        {!apiKey && (
          <p className="mt-3 text-xs text-[var(--color-ink-muted)]">
            填了 API key 才能生成。
          </p>
        )}
        {loading && (
          <RunningProcess
            label="读全书出叙事曲线"
            hint="整本书喂进模型逐章判张力——每章判定都回原文核验，约 1 分钟。"
          />
        )}
      </div>
    );
  }

  const n = chapters.length;
  const verifiedN = chapters.filter((c) => c.verified).length;
  const sel = selected != null ? chapters.find((c) => c.chapter === selected) : null;

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-base font-bold text-[var(--color-ink)]"
          style={{ fontFamily: "var(--font-display)" }}
        >
          叙事曲线
        </h3>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="text-xs px-2 py-1 rounded border border-[var(--color-rule)] bg-white hover:border-[var(--color-seal)] disabled:opacity-50 transition-colors"
        >
          {loading ? "重出中…" : "重新生成"}
        </button>
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        {n} 章（原文核验 {verifiedN}/{n} 章）。一幅画把四维同收:山势=张力、天色暖冷=情感(暖往上走/冷往下沉)、底部色带=主导视角(换色=换视角、实笔=主线·淡笔=支线)、朱砂点=核验过的高潮章。鼠标移过去吸附最近章、点看那章原文。都是模型判读的相对趋势,不报精确分数。
      </p>

      <ShanshuiCurve chapters={chapters} selected={selected} onSelect={setSelected} />

      {sel && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          <p className="text-sm font-bold text-[var(--color-ink)]">
            第 {sel.chapter} 章 · {tensionBand(sel.tension)}
            <span className="font-normal text-[var(--color-ink-muted)]">
              {" "}
              · 情感{" "}
              {sel.sentiment > 0 ? "偏暖" : sel.sentiment < 0 ? "偏沉" : "平"} · 视角「
              {sel.pov}」· {sel.mainline ? "主线" : "支线"}（模型判读）
            </span>
          </p>
          <p className="mt-1 text-sm text-[var(--color-ink)] leading-relaxed">
            {sel.evidence || "（这章没给出原文依据）"}
          </p>
          <p className="mt-1 text-xs text-[var(--color-ink-muted)]">
            {sel.verified
              ? "原文已核验"
              : "原文未在书中比对命中——这章判读仅供参考"}
          </p>
        </div>
      )}

      {loading ? (
        <RunningProcess label="重出叙事曲线" />
      ) : (
        <RunStats trace={trace} note={`${n} 章`} />
      )}
    </div>
  );
}
