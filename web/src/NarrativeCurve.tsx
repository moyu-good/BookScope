// ---------------------------------------------------------------------------
// NarrativeCurve — 叙事曲线（重设计:转折落点，作者拍板）
//
// 这个功能只答一个问题:全书的转折 / 伏笔回收砸在哪几章。名字沿用"叙事曲线"(别破坏导航),
// 但重心从"数量密度"挪到"转折在哪"。图里朱砂大点 = 转折章(伏笔在这章收掉),章号直接标在点边上,
// 一眼看清转折落在哪几章、密还是疏;事件密度退成一层淡墨山形垫底,只给节奏感(见 ShanshuiCurve)。
//
// 点一个转折章 → 明细先列这章的转折(伏笔回收)每条 + 原文(核验过盖钤印、没命中标待核),再列这章
// 发生的事;普通章至少列这章 events + 原文。每次点击都落到原文。张力只在明细里附带标"模型判读",
// 绝不当纵轴(模型眼估的标量不可信)。
//
// 点生成 → 调 /api/agent/narrative-curve(从共享章脉派生,命中缓存秒出)。evidence-first:这章
// 没事件就标"平铺过渡"。
// ---------------------------------------------------------------------------

import { useState } from "react";
import { RunningProcess, RunStats, type RunTrace } from "./runProcess";
import { ShanshuiCurve, type CurveChapter } from "./ShanshuiCurve";
import { FeatureEntryCard } from "./FeatureEntryCard";
import { SealButton } from "./SealButton";
import { SealMark } from "./SealMark";

interface NarrativeCurveProps {
  sessionId: string;
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

function sentLabel(s: number): string {
  if (s > 0) return "偏暖";
  if (s < 0) return "偏沉";
  return "平";
}

// 张力粗档：exp-016 n=8 实测张力分档内 ±1 档抖、绝对整数不可当真，只有相对高低稳。
// 所以这里跟 CharacterArc / HuaniaoArc 一样报粗档，不印"7/10"那种假精确（虽标了仅供参考）。
function tensionLabel(t: number): string {
  if (t >= 7) return "偏紧";
  if (t <= 3) return "偏松";
  return "居中";
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
      <FeatureEntryCard
        title="叙事曲线"
        lead="看全书的转折、伏笔回收落在哪几章、每处收了几条。朱砂竖得越高，这章收的伏笔越多；章号印在点边上，一眼看清高潮压在哪几章。点一个转折章，看它收了哪几条、每条翻回原文。史书这类没有伏笔的，如实留白。"
        actionLabel="生成叙事曲线"
        loadingLabel="读全书出曲线中（约 1 分钟）…"
        onAction={load}
        loading={loading}
        disabled={!apiKey}
        hint="读全书理出脉络，约一分钟；读过一次再看就快"
        error={error}
      >
        {loading && (
          <RunningProcess
            label="读全书出叙事曲线"
            hint="把整本书逐章读一遍，找出每章的关键事件和回收的伏笔，约一分钟。"
          />
        )}
      </FeatureEntryCard>
    );
  }

  const n = chapters.length;
  const turningN = chapters.filter((c) => c.is_turning).length;
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
        <SealButton
          size="sm"
          label="重新生成"
          loadingLabel="重出中…"
          loading={loading}
          onClick={load}
        />
      </div>

      <p className="text-xs text-[var(--color-ink-muted)] mb-2">
        全书 {n} 章，转折落在其中 <span style={{ color: "var(--color-seal)" }}>{turningN}</span> 章。朱砂竖线越高＝这章收的伏笔 / 转折越多，章号标在点边。鼠标移过去看是哪章，点一下看这章收了哪几条、翻回原文。
      </p>

      <ShanshuiCurve chapters={chapters} selected={selected} onSelect={setSelected} />

      {sel && (
        <div className="mt-3 p-3 rounded border border-[var(--color-rule)] bg-white">
          {/* 标题：转折章朱砂标出来，先报转折处数（主角），事件数退成附注 */}
          <p className="text-sm font-bold text-[var(--color-ink)] flex items-center gap-2">
            <span>第 {sel.chapter} 章</span>
            {sel.is_turning ? (
              <span
                className="inline-flex items-center rounded px-1.5 py-0.5 text-xs font-bold"
                style={{ color: "var(--color-seal)", background: "var(--color-seal-soft)" }}
              >
                转折章 · 收 {sel.turning_count} 条伏笔
              </span>
            ) : (
              <span className="text-xs font-normal text-[var(--color-ink-muted)]">
                过渡章 · {sel.event_count} 件事
              </span>
            )}
          </p>

          {/* 转折章：转折（伏笔回收）领衔——治"点了没料"，每条钉原文 */}
          {sel.turning_points.length > 0 && (
            <div className="mt-2">
              <p className="text-xs font-bold" style={{ color: "var(--color-seal)" }}>
                这章收掉的伏笔 / 转折
              </p>
              <ul className="mt-1.5 space-y-2.5">
                {sel.turning_points.map((tp, i) => (
                  <li key={`tp-${i}`} className="text-sm">
                    <p className="text-[var(--color-ink)] font-medium">· {tp.hook}</p>
                    {tp.evidence ? (
                      <div className="mt-1 ml-3 flex items-start gap-1.5">
                        <p className="flex-1 text-xs text-[var(--color-ink-muted)] border-l-2 pl-2 leading-relaxed" style={{ borderColor: "var(--color-seal)" }}>
                          {tp.evidence}
                        </p>
                        <SealMark size={22} title="原文已逐字核验" className="mt-0.5" />
                      </div>
                    ) : (
                      <p className="mt-1 ml-3 text-xs text-[var(--color-ink-muted)] italic">
                        原文未在书中比对命中，待核
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* 这章发生的事：转折章里退为次级列表，普通章里就是主要内容 */}
          {sel.events.length > 0 ? (
            <div className={sel.turning_points.length > 0 ? "mt-3 pt-2 border-t border-[var(--color-rule)]" : "mt-2"}>
              {sel.turning_points.length > 0 && (
                <p className="text-xs font-bold text-[var(--color-ink-muted)]">这章发生的事</p>
              )}
              <ul className={sel.turning_points.length > 0 ? "mt-1.5 space-y-2" : "space-y-2"}>
                {sel.events.map((ev, i) => (
                  <li key={`ev-${i}`} className="text-sm">
                    <p className="text-[var(--color-ink)]">· {ev.text}</p>
                    {ev.evidence ? (
                      <div className="mt-0.5 ml-3 flex items-start gap-1.5">
                        <p className="flex-1 text-xs text-[var(--color-ink-muted)] border-l-2 border-[var(--color-rule)] pl-2 leading-relaxed">
                          {ev.evidence}
                        </p>
                        <SealMark size={20} title="原文已逐字核验" className="mt-0.5" />
                      </div>
                    ) : (
                      <p className="mt-0.5 ml-3 text-xs text-[var(--color-ink-muted)] italic">
                        原文未在书中比对命中，待核
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            sel.turning_points.length === 0 && (
              <p className="mt-2 text-sm text-[var(--color-ink-muted)]">
                这章没数出关键事件，平铺过渡 / 待核。
              </p>
            )
          )}

          {/* 张力等四维：只附带，标"模型判读"，不当纵轴 */}
          <p className="mt-3 pt-2 border-t border-[var(--color-rule)] text-xs text-[var(--color-ink-muted)]">
            模型判读（仅供参考，不当数据）：张力{tensionLabel(sel.tension)} · 情感{sentLabel(sel.sentiment)} · 视角「{sel.pov}」· {sel.mainline ? "主线" : "支线"}
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
