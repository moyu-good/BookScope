// ---------------------------------------------------------------------------
// SpineWarmupBanner —— 章脉后台预建的进度横幅（性能 Lever B 前端）
//
// 超长文第一次打开要在后台把整本读一遍建章脉（可能十几分钟）。一进分析台就后台起
// 预建，这条横幅告知进度——按章渐进：建到哪算哪，已建章节的分析/报告随时可用。
//
// 形态：
//   - building：低调横幅 + 真实进度（已建 N/M 章）+ 朱砂扫光走动条
//   - done：短暂显示"全书已通读，分析秒出"，几秒后由 App 收起。
//   - 其它（idle / error）：不渲染——预建失败不吓用户，各功能还能按需现建。
//
// 数字善本风：朱砂淡底、克制，不喧宾夺主。
// ---------------------------------------------------------------------------

/** App 侧折叠出来的预建 UI 状态。error / idle 直接不给这个组件（返 null 收起）。 */
export type SpineWarmupPhase =
  | { status: "building"; built: number; total: number }
  | { status: "done" };

export function SpineWarmupBanner({ phase }: { phase: SpineWarmupPhase }) {
  const building = phase.status === "building";
  const pct =
    building && phase.total > 0
      ? Math.min(100, Math.round((phase.built / phase.total) * 100))
      : 0;
  return (
    <div
      className="mb-4 overflow-hidden rounded-md border text-xs leading-relaxed"
      style={{
        background: "var(--color-seal-soft)",
        borderColor: "color-mix(in oklch, var(--color-seal) 30%, transparent)",
      }}
    >
      <div className="px-3.5 py-2.5">
        {building ? (
          <>
            <span className="font-bold text-[var(--color-seal)]">
              正在通读全书 · {phase.built}/{phase.total} 章（{pct}%）
            </span>
            <span className="text-[var(--color-ink-muted)]">
              {" "}
              —— 按章渐进：已读过的章节分析/报告现在就能用；改稿只重算改动章，不用全书重跑。
            </span>
          </>
        ) : (
          <span className="font-bold text-[var(--color-seal)]">
            全书已通读，整本书分析秒出。
          </span>
        )}
      </div>
      {/* 走动条：只在 building 时出现。朱砂扫光从左到右往复；宽度按真实进度。 */}
      {building && (
        <div
          className="relative h-[3px] w-full overflow-hidden"
          style={{
            background: "color-mix(in oklch, var(--color-seal) 12%, transparent)",
          }}
        >
          <div
            className="absolute inset-y-0 rounded-full transition-all duration-500"
            style={{
              width: `${Math.max(pct, 4)}%`,
              background: "var(--color-seal)",
            }}
          />
          <div
            className="spine-warmup-sweep absolute inset-y-0 w-1/3 rounded-full"
            style={{ background: "var(--color-seal)" }}
          />
        </div>
      )}
      <style>{`
        @keyframes spine-warmup-sweep {
          0%   { left: -35%; }
          100% { left: 100%; }
        }
        .spine-warmup-sweep {
          animation: spine-warmup-sweep 1.6s ease-in-out infinite;
          opacity: 0.35;
        }
        @media (prefers-reduced-motion: reduce) {
          .spine-warmup-sweep { animation-duration: 3.2s; }
        }
      `}</style>
    </div>
  );
}
