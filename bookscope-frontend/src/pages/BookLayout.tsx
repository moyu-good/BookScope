import { useEffect, useRef, useState, createContext, useContext } from "react";
import {
  Outlet,
  useParams,
  useLocation,
  useNavigate,
  NavLink,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  BookOpen,
  Compass,
  Library,
  Plus,
  Save,
  Download,
} from "lucide-react";
import clsx from "clsx";
import { fetchSessionStatus, startExtraction, saveToLibrary } from "../lib/api";
import type { SSEEvent, SessionStatus } from "../lib/types";

/* ------------------------------------------------------------------ */
/*  Extraction context — shared with child pages                      */
/* ------------------------------------------------------------------ */

interface ExtractionContextValue {
  sseEvents: SSEEvent[];
  isExtracting: boolean;
  sessionStatus: SessionStatus | undefined;
}

const ExtractionContext = createContext<ExtractionContextValue>({
  sseEvents: [],
  isExtracting: false,
  sessionStatus: undefined,
});

export function useExtraction(): ExtractionContextValue {
  return useContext(ExtractionContext);
}

/* ------------------------------------------------------------------ */
/*  BookLayout component                                              */
/* ------------------------------------------------------------------ */

export default function BookLayout() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const locationState = location.state as
    | { bookType?: string; uiLang?: string; title?: string }
    | undefined;

  const [sseEvents, setSSEEvents] = useState<SSEEvent[]>([]);
  const [isExtracting, setIsExtracting] = useState(false);
  const extractionStartedRef = useRef(false);
  const [saving, setSaving] = useState(false);

  // Poll session status
  const { data: sessionStatus } = useQuery({
    queryKey: ["session-status", sessionId],
    queryFn: () => fetchSessionStatus(sessionId!),
    enabled: !!sessionId,
    refetchInterval: isExtracting ? 2000 : false,
  });

  // Auto-start extraction when status is "idle"
  useEffect(() => {
    if (!sessionId) return;
    if (extractionStartedRef.current) return;
    if (!sessionStatus) return;
    if (sessionStatus.extraction_status !== "idle") return;

    extractionStartedRef.current = true;
    setIsExtracting(true);

    const sse = startExtraction(sessionId);
    sse.onEvent((event) => {
      setSSEEvents((prev) => [...prev, event]);
    });
    sse.onError((err) => {
      setSSEEvents((prev) => [
        ...prev,
        { type: "error", message: err } as SSEEvent,
      ]);
      setIsExtracting(false);
    });
    sse.onDone(() => {
      setIsExtracting(false);
    });
    sse.start();

    return () => {
      sse.abort();
    };
  }, [sessionId, sessionStatus]);

  // Detect done from status polling
  useEffect(() => {
    if (
      sessionStatus?.extraction_status === "done" ||
      sessionStatus?.extraction_status === "error"
    ) {
      setIsExtracting(false);
    }
  }, [sessionStatus]);

  const title = locationState?.title ?? "书籍分析";

  const handleSave = async () => {
    if (!sessionId || saving) return;
    setSaving(true);
    try {
      await saveToLibrary(sessionId);
    } finally {
      setSaving(false);
    }
  };

  const contextValue: ExtractionContextValue = {
    sseEvents,
    isExtracting,
    sessionStatus,
  };

  return (
    <ExtractionContext.Provider value={contextValue}>
      <div className="min-h-svh flex flex-col">
        {/* Header */}
        <header className="sticky top-0 z-40 bg-[var(--bg)]/80 backdrop-blur-md border-b border-[var(--border)]">
          <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
            {/* Left: branding + title */}
            <div className="flex items-center gap-3 min-w-0">
              <span className="text-lg text-[var(--accent)] shrink-0" style={{ fontFamily: "var(--font-display)" }}>书鉴</span>
              <span className="text-xs text-[var(--border)]">|</span>
              <h1 className="text-base truncate text-[var(--text)]" style={{ fontFamily: "var(--font-display)", letterSpacing: "0.08em" }}>{title}</h1>
              {isExtracting && (
                <span className="shrink-0 ml-2 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-[var(--accent)]/15 text-[var(--accent)] rounded-full">
                  提取中
                </span>
              )}
            </div>

            {/* Center: nav */}
            <nav className="hidden sm:flex items-center gap-1">
              <NavLink
                to={`/book/${sessionId}`}
                end
                className={({ isActive }) =>
                  clsx(
                    "px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200",
                    isActive
                      ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                      : "text-[var(--text-secondary)] hover:text-[var(--text)]",
                  )
                }
              >
                <span className="flex items-center gap-1.5">
                  <BookOpen className="w-3.5 h-3.5" />
                  总览
                </span>
              </NavLink>
              <NavLink
                to={`/book/${sessionId}/explore`}
                className={({ isActive }) =>
                  clsx(
                    "px-3 py-1.5 rounded-lg text-xs font-medium transition-all duration-200",
                    isActive
                      ? "bg-[var(--accent)]/15 text-[var(--accent)]"
                      : "text-[var(--text-secondary)] hover:text-[var(--text)]",
                  )
                }
              >
                <span className="flex items-center gap-1.5">
                  <Compass className="w-3.5 h-3.5" />
                  探索
                </span>
              </NavLink>
            </nav>

            {/* Right: actions */}
            <div className="flex items-center gap-2">
              <button
                onClick={handleSave}
                disabled={saving}
                className="p-2 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all duration-200"
                title="保存到书库"
              >
                <Save className="w-4 h-4" />
              </button>
              <button
                className="p-2 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all duration-200"
                title="导出"
              >
                <Download className="w-4 h-4" />
              </button>
              <button
                onClick={() => navigate("/library")}
                className="p-2 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all duration-200"
                title="书库"
              >
                <Library className="w-4 h-4" />
              </button>
              <button
                onClick={() => navigate("/")}
                className="p-2 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all duration-200"
                title="新建分析"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 max-w-6xl mx-auto w-full px-4 py-6">
          <Outlet />
        </main>
      </div>
    </ExtractionContext.Provider>
  );
}
