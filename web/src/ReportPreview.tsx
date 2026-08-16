// ---------------------------------------------------------------------------
// ReportPreview —— 书鉴/对照报告预览（产品内交付物，不只是下载文件）
//
// 报告是主轴交付物：点「出报告」不再只下载，而是先在应用内 iframe 预览，
// 可随时下载 / 关闭。解决"HTML 文件打不开/看不到"的断点。
// ---------------------------------------------------------------------------

export interface ReportPreviewState {
  url: string;
  title: string;
  fileName: string;
}

export function ReportPreview({
  preview,
  onClose,
}: {
  preview: ReportPreviewState;
  onClose: () => void;
}) {
  const download = () => {
    const a = document.createElement("a");
    a.href = preview.url;
    a.download = preview.fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  return (
    <div
      className="fixed inset-0 z-[200] flex flex-col bg-[var(--color-paper)]"
      role="dialog"
      aria-modal="true"
      aria-label={`报告预览：${preview.title}`}
    >
      {/* 顶栏：标题 + 下载 + 关闭 */}
      <div
        className="flex items-center gap-3 px-4 py-2.5 border-b border-[var(--color-rule)]"
        style={{ background: "var(--color-paper-raised)" }}
      >
        <span className="text-sm font-bold text-[var(--color-seal)] truncate" style={{ fontFamily: "var(--font-display)" }}>
          📜 {preview.title}
        </span>
        <span className="text-xs text-[var(--color-ink-muted)] hidden sm:inline">
          书鉴报告 · 可下载后分享 / 存档
        </span>
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            onClick={download}
            className="text-xs px-3 py-1.5 rounded-md bg-[var(--color-seal)] text-white hover:brightness-110 transition"
            style={{ fontFamily: "var(--font-display)" }}
          >
            下载 HTML
          </button>
          <button
            type="button"
            onClick={onClose}
            className="text-xs px-3 py-1.5 rounded-md border border-[var(--color-rule)] text-[var(--color-ink-muted)] hover:text-[var(--color-ink)] transition"
          >
            关闭
          </button>
        </div>
      </div>
      {/* 报告本体：iframe 全屏预览 */}
      <iframe
        src={preview.url}
        title={preview.title}
        className="flex-1 w-full border-0"
        style={{ background: "white" }}
      />
    </div>
  );
}
