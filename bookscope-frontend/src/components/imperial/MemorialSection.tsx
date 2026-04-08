import { useState, useRef, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";
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
      className={clsx(
        "text-xs px-3 py-1.5 rounded border transition-colors cursor-pointer",
        "border-[var(--vermillion-border)] text-[var(--vermillion)]",
        "hover:bg-[var(--vermillion-light)] hover:border-[var(--vermillion)]",
        disabled && "opacity-40 cursor-not-allowed",
      )}
    >
      朱批 ✏️
    </button>
  );
}
