// ---------------------------------------------------------------------------
// ScholarStancePanel — 学者立场谱的 live 取数包壳（真 app 用）
//
// 把 ScholarStanceSpectrum（纯展示）接上 /agent/scholar-stance：一次通读全书，让模型
// 定出本书自己的核心争论轴，再把书里对话的学者摆到轴上（有立场的给原文引证、只提名的
// 归到"没表态"）。契约同别的按需视图：BYOK、失败提示、命中缓存秒出。
//
// 优雅退场：这是理论书专属镜头。非理论书（小说 / 公文 / 诗集）后端会 scanned=false
// 或返空学者集，前端不画谱、只说明这本书没在跟学者做立场对话，不硬凑一张空图。
// 换书由 App 传 key 重挂，本壳不管重置。
// ---------------------------------------------------------------------------

import { useState } from "react";
import {
  ScholarStanceSpectrum,
  type SpectrumAxis,
  type SpectrumScholar,
} from "./ScholarStanceSpectrum";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";
import { RunningProcess } from "./runProcess";

interface Props {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

interface StanceResult {
  scanned: boolean;
  axis: SpectrumAxis | null;
  scholars: SpectrumScholar[];
}

const LEAD =
  "看这本书在跟哪些思想家对话：先理出它自己的核心争论，再把书里引到的学者按原文摆到争论的某一极，谁偏哪头一眼看清。点开谁，看书里怎么刻画他，每句都能核回原文。";

export function ScholarStancePanel({ sessionId, provider, apiKey, model, baseUrl }: Props) {
  const [result, setResult] = useState<StanceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        book_session_id: sessionId,
        provider,
        api_key: apiKey,
      };
      if (model) body.model = model;
      if (baseUrl) body.base_url = baseUrl;
      const resp = await fetch("/api/agent/scholar-stance", {
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
        scanned?: boolean;
        axis?: SpectrumAxis | null;
        scholars?: SpectrumScholar[];
      };
      setResult({
        scanned: Boolean(data.scanned),
        axis: data.axis ?? null,
        scholars: data.scholars ?? [],
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  // 空态（还没生成）：统一入口卡
  if (!result) {
    return (
      <FeatureEntryCard
        title="学者立场谱"
        lead={LEAD}
        actionLabel="翻开学者立场谱"
        loadingLabel="通读全书中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书理出核心争论、把学者摆上轴，约 1 分钟；命中缓存秒出"
        error={error}
      >
        {loading && (
          <RunningProcess
            label="正在通读全书，理出书里对话的学者"
            hint="先把整本书读一遍，定出它自己的核心争论，再把学者按原文摆到某一极；读过一次后再看就快。"
          />
        )}
      </FeatureEntryCard>
    );
  }

  // 生成过了：理论书专属镜头，非理论书优雅退场（不硬画空图）。
  const empty = !result.scanned || !result.axis || result.scholars.length === 0;

  return (
    <div className="pt-4">
      <div className="flex items-center justify-between mb-3 gap-3">
        <p className="text-sm text-[var(--color-ink-muted)] leading-relaxed pr-2">{LEAD}</p>
        <SealButton
          size="sm"
          label="重新生成"
          loadingLabel="通读中…"
          loading={loading}
          onClick={load}
          className="shrink-0"
        />
      </div>

      {error && (
        <p className="text-sm mb-3" style={{ color: "var(--color-seal)" }}>
          {error}
        </p>
      )}

      {loading && <RunningProcess label="正在通读全书，理出书里对话的学者" />}

      {!loading && empty && (
        <div className="rounded border border-dashed border-[var(--color-rule)] bg-[var(--color-paper-raised)] p-5 text-sm text-[var(--color-ink-muted)] leading-relaxed">
          这本书没有在跟学者做立场层面的对话，就不画学者立场谱了。这个镜头是给理论 / 论述类书准备的：看它引了哪些思想家、各自站在书里核心争论的哪一极。想看别的维度，去左栏其它功能。
        </div>
      )}

      {!loading && !empty && result.axis && (
        <ScholarStanceSpectrum axis={result.axis} scholars={result.scholars} />
      )}
    </div>
  );
}
