import { useState, useRef, useEffect, type ReactNode } from "react";
import { ChevronRight, X } from "lucide-react";
import clsx from "clsx";

interface MemorialSectionProps {
  /** Section title shown in collapsed and expanded state */
  title: string;
  /** Brief preview shown when collapsed */
  preview?: string;
  /** Full content rendered when expanded */
  children: ReactNode;
  /** Initially expanded? First section defaults to true */
  defaultOpen?: boolean;
  /** Slot for 朱批 annotations rendered below main content */
  annotations?: ReactNode;
  /** Slot for action buttons (朱批, 已阅) at the bottom */
  actions?: ReactNode;
  /** Show the read-stamp indicator on collapsed state */
  isRead?: boolean;
  /** Callback when expand/collapse state changes */
  onToggle?: (open: boolean) => void;
}

export default function MemorialSection({
  title,
  preview,
  children,
  defaultOpen = false,
  annotations,
  actions,
  isRead = false,
  onToggle,
}: MemorialSectionProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [stampVisible, setStampVisible] = useState(isRead);
  const contentRef = useRef<HTMLDivElement>(null);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    onToggle?.(next);
  };

  return (
    <div className="memorial-section">
      {/* ── Header — always visible ──────────────────── */}
      <button
        onClick={toggle}
        className={clsx(
          "w-full text-left px-6 py-5 flex items-start gap-4 cursor-pointer",
          "transition-colors duration-200",
          open ? "pb-2" : "hover:bg-[var(--parchment-dark)]/40",
        )}
      >
        {/* Chevron */}
        <ChevronRight
          className={clsx(
            "w-4 h-4 mt-1.5 shrink-0 text-[var(--parchment-text-secondary)] transition-transform duration-300",
            open && "rotate-90",
          )}
        />

        {/* Title + preview */}
        <div className="flex-1 min-w-0">
          <h2
            className="text-lg font-medium tracking-wide"
            style={{
              fontFamily: "var(--font-display)",
              color: "var(--parchment-text)",
              letterSpacing: "0.08em",
            }}
          >
            {title}
          </h2>
          {!open && preview && (
            <p className="text-xs mt-1 text-[var(--parchment-text-secondary)] line-clamp-1">
              {preview}
            </p>
          )}
        </div>

        {/* 已阅 stamp indicator (collapsed only) */}
        {!open && stampVisible && (
          <span className="seal-stamp shrink-0 mt-0.5">已阅</span>
        )}
      </button>

      {/* ── Expanded content ────────────────────────── */}
      {open && (
        <div
          ref={contentRef}
          className="animate-[memorialUnfold_0.4s_ease-out_both] overflow-hidden"
        >
          {/* Main content */}
          <div className="memorial-body px-6 pb-4">{children}</div>

          {/* Annotations (朱批 thread) */}
          {annotations && (
            <div className="px-6 pb-4 space-y-3">{annotations}</div>
          )}

          {/* Actions bar */}
          {actions && (
            <div className="px-6 pb-5 flex items-center justify-end gap-3">
              {actions}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Fold Crease separator ────────────────────────── */

export function FoldCrease() {
  return (
    <div className="fold-crease my-1 px-4">
      <span className="fold-crease-text">折</span>
    </div>
  );
}

/* ── Read Stamp button ────────────────────────────── */

interface ReadStampProps {
  isRead: boolean;
  onMark: () => void;
}

export function ReadStamp({ isRead, onMark }: ReadStampProps) {
  const [justStamped, setJustStamped] = useState(false);

  const handleClick = () => {
    if (isRead) return;
    setJustStamped(true);
    onMark();
  };

  if (isRead) {
    return (
      <span
        className={clsx("seal-stamp", justStamped && "seal-stamp-animated")}
      >
        已阅
      </span>
    );
  }

  return (
    <button
      onClick={handleClick}
      className="text-xs px-3 py-1.5 rounded border border-[var(--fold-line)] text-[var(--parchment-text-secondary)] hover:border-[var(--vermillion)] hover:text-[var(--vermillion)] transition-colors cursor-pointer"
    >
      标为已阅
    </button>
  );
}

/* ── Feature Guide Card (首次引导) ───────────────── */

const GUIDE_SEEN_KEY = "bookscope-feature-guide-seen";

export function FeatureGuide() {
  const [visible, setVisible] = useState(
    () => !localStorage.getItem(GUIDE_SEEN_KEY),
  );

  const dismiss = () => {
    setVisible(false);
    localStorage.setItem(GUIDE_SEEN_KEY, "1");
  };

  if (!visible) return null;

  return (
    <div className="w-full mb-3 animate-[fadeSlideIn_0.3s_ease-out_both]">
      <div
        className="relative rounded-lg border px-4 py-3"
        style={{
          borderColor: "var(--vermillion-border)",
          background: "var(--vermillion-light)",
        }}
      >
        <button
          onClick={dismiss}
          className="absolute top-2 right-2 text-[var(--parchment-text-secondary)] hover:text-[var(--parchment-text)] cursor-pointer"
        >
          <X className="w-3.5 h-3.5" />
        </button>
        <p className="text-xs font-medium text-[var(--vermillion)] mb-1.5">
          使用指南
        </p>
        <ul className="text-[11px] text-[var(--parchment-text)] space-y-1 leading-relaxed">
          <li>
            <span className="text-[var(--vermillion)] font-medium">顶部判断</span>
            {" —— 这本书值不值得你读，一句话答案在最上方「御览」印章处"}
          </li>
          <li>
            <span className="text-[var(--vermillion)] font-medium">御问</span>
            {" —— 展开任一证据段落，底部点击「御问」，就此段向 AI 发问"}
          </li>
          <li>
            <span className="text-[var(--vermillion)] font-medium">传召对话</span>
            {" —— 底部对话框点击人物标签，与书中角色直接问答"}
          </li>
          <li>
            <span className="text-[var(--vermillion)] font-medium">已阅标记</span>
            {" —— 读完的段落标「已阅」，进度自动保留"}
          </li>
        </ul>
      </div>
    </div>
  );
}

/* ── 朱批 trigger button ──────────────────────────── */

interface AnnotateButtonProps {
  onClick: () => void;
  disabled?: boolean;
}

export function AnnotateButton({ onClick, disabled }: AnnotateButtonProps) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title="就此段向 AI 御问——内容作为上下文送入下方对话"
      className={clsx(
        "text-xs px-3 py-1.5 rounded border transition-colors cursor-pointer",
        "border-[var(--fold-line)] text-[var(--parchment-text-secondary)]",
        "hover:border-[var(--vermillion)] hover:text-[var(--vermillion)]",
        disabled && "opacity-40 cursor-not-allowed",
      )}
    >
      御问
    </button>
  );
}
