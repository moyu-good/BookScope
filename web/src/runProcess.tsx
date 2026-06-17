// ---------------------------------------------------------------------------
// runProcess — 运行过程可视化（点功能后不再黑盒干等）
//
// 整本书功能（关系图 / 节奏 / 时间线 …）一次要 40-70s 通读全书，过去只有个"…中"按钮，
// 用户盯着干等。这里给两块共享件：
//   RunningProcess —— 跑的时候：四段流水线（取全书 → 通读 → 梳理 → 核验）+ 不确定进度
//     扫光 + 实时计时器。不伪造百分比（一次 LLM 长调用看不到中间态），只诚实显示"跑了多久"。
//   RunStats       —— 跑完：案头小字一行——读了多少字、花了多少 token、用了多久。
//     数据来自后端响应的 trace（input_tokens / output_tokens / chars / duration_ms）。
// ---------------------------------------------------------------------------

import { useEffect, useState } from "react";

export interface RunTrace {
  input_tokens?: number;
  output_tokens?: number;
  chars?: number;
  duration_ms?: number;
}

/** 字数 → "39.5 万字" / "3,210 字"。 */
export function formatChars(n: number | undefined): string {
  if (!n || n <= 0) return "";
  if (n >= 10000) return `${(n / 10000).toFixed(1)} 万字`;
  return `${n.toLocaleString("en-US")} 字`;
}

function fmtNum(n: number | undefined): string {
  if (!n || n <= 0) return "0";
  return n.toLocaleString("en-US");
}

/** ms → "45.9s" / "1m02s"。 */
function fmtDuration(ms: number | undefined): string {
  if (!ms || ms <= 0) return "";
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rest = Math.round(s % 60);
  return `${m}m${String(rest).padStart(2, "0")}s`;
}

const STAGES = ["取出整本书", "喂模型通读", "梳理结构", "核验原文"];

/**
 * 跑的时候显示的流水线 + 计时器。自带计时（从 mount 起算），父组件只在 loading 时挂上即可。
 */
export function RunningProcess({
  label = "读全书分析中",
  hint = "整本书喂进模型通读——大书约 1 分钟，请稍候。",
}: {
  label?: string;
  hint?: string;
}) {
  const [sec, setSec] = useState(0);
  useEffect(() => {
    const t0 = Date.now();
    const id = window.setInterval(() => {
      setSec(Math.floor((Date.now() - t0) / 1000));
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  const mm = String(Math.floor(sec / 60)).padStart(2, "0");
  const ss = String(sec % 60).padStart(2, "0");

  return (
    <div className="mt-3 p-4 rounded border border-[var(--color-rule)] bg-[var(--color-paper-raised)]">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span
            className="inline-block w-2 h-2 rounded-full bg-[var(--color-seal)] animate-pulse"
            aria-hidden
          />
          <span
            className="text-sm font-bold text-[var(--color-ink)]"
            style={{ fontFamily: "var(--font-display)" }}
          >
            {label}
          </span>
        </div>
        <span className="text-xs tabular-nums text-[var(--color-ink-muted)]">
          {mm}:{ss}
        </span>
      </div>

      {/* 不确定进度扫光——不伪造百分比，只表示"在跑" */}
      <div className="mt-3 relative h-1 rounded-full bg-[var(--color-rule)] overflow-hidden">
        <div
          className="absolute inset-y-0 left-0 w-1/4 rounded-full bg-[var(--color-seal)]"
          style={{ animation: "run-sweep 1.5s ease-in-out infinite" }}
          aria-hidden
        />
      </div>

      {/* 四段流水线 */}
      <ol className="mt-3 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-[var(--color-ink-muted)]">
        {STAGES.map((s, i) => (
          <li key={s} className="flex items-center gap-2">
            <span className="text-[var(--color-seal)] tabular-nums">{i + 1}</span>
            <span>{s}</span>
            {i < STAGES.length - 1 && (
              <span className="text-[var(--color-rule)]" aria-hidden>
                →
              </span>
            )}
          </li>
        ))}
      </ol>

      <p className="mt-2 text-xs text-[var(--color-ink-muted)] leading-relaxed">{hint}</p>
    </div>
  );
}

/** 跑完显示的用量小字。trace 缺某字段就跳过那项；全缺则不渲染。 */
export function RunStats({
  trace,
  note,
}: {
  trace?: RunTrace | null;
  note?: string;
}) {
  if (!trace) return null;
  const parts: string[] = [];
  if (trace.chars) parts.push(`通读 ${formatChars(trace.chars)}`);
  const it = trace.input_tokens ?? 0;
  const ot = trace.output_tokens ?? 0;
  if (it || ot) parts.push(`输入 ${fmtNum(it)}、输出 ${fmtNum(ot)} tokens`);
  else parts.push("命中缓存（0 token）");
  if (trace.duration_ms) parts.push(`用时 ${fmtDuration(trace.duration_ms)}`);
  if (note) parts.push(note);
  if (parts.length === 0) return null;
  return (
    <p className="mt-3 pt-2 border-t border-[var(--color-rule)] text-xs text-[var(--color-ink-muted)] flex flex-wrap items-center gap-x-1.5 gap-y-1">
      <span className="text-[var(--color-seal)]" aria-hidden>
        ❡
      </span>
      {parts.map((p, i) => (
        <span key={p} className="flex items-center gap-1.5">
          {i > 0 && (
            <span className="text-[var(--color-rule)]" aria-hidden>
              ·
            </span>
          )}
          <span className="tabular-nums">{p}</span>
        </span>
      ))}
    </p>
  );
}
