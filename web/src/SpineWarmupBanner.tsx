// ---------------------------------------------------------------------------
// SpineWarmupBanner —— 章脉后台预建的进度横幅（性能 Lever B 前端）
//
// 超长文第一次打开要在后台把整本读一遍建章脉（可能十几分钟）。一进分析台就后台起
// 预建，这条横幅只是告知"正在通读全书，好了所有分析秒出"，不拦任何操作。
//
// 三态：
//   - building：低调横幅 + 朱砂扫光走动条（后端建到一半不给章数，不伪造百分比）。
//   - done：短暂显示"全书已通读，分析秒出"，几秒后由 App 收起。
//   - 其它（idle / error）：不渲染——预建失败不吓用户，各功能还能按需现建。
//
// 数字善本风：朱砂淡底、克制，不喧宾夺主。
// ---------------------------------------------------------------------------

/** App 侧折叠出来的预建 UI 状态。error / idle 直接不给这个组件（返 null 收起）。 */
export type SpineWarmupPhase = "building" | "done";

export function SpineWarmupBanner({ phase }: { phase: SpineWarmupPhase }) {
  const building = phase === "building";
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
              正在通读全书
            </span>
            <span className="text-[var(--color-ink-muted)]">
              {" "}
              —— 第一次读这本书要把整本读一遍（大书约几分钟），只此一次。现在点整本书功能会等它读完；读完之后再点，就都秒出了。
            </span>
          </>
        ) : (
          <span className="font-bold text-[var(--color-seal)]">
            全书已通读，整本书分析秒出。
          </span>
        )}
      </div>
      {/* 走动条：只在 building 时出现。朱砂扫光从左到右往复，不表示百分比。 */}
      {building && (
        <div
          className="relative h-[3px] w-full overflow-hidden"
          style={{
            background: "color-mix(in oklch, var(--color-seal) 12%, transparent)",
          }}
        >
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
        }
        @media (prefers-reduced-motion: reduce) {
          .spine-warmup-sweep { animation-duration: 3.2s; }
        }
      `}</style>
    </div>
  );
}
