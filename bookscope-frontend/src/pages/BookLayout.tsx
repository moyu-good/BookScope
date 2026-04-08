import { useEffect, useRef, useState, createContext, useContext } from "react";
import {
  Outlet,
  useParams,
  useLocation,
  useNavigate,
} from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Library,
  Plus,
  Save,
  Settings,
  MessageCircle,
} from "lucide-react";
import clsx from "clsx";
import { fetchSessionStatus, fetchOverview, startExtraction, saveToLibrary } from "../lib/api";
import type { SSEEvent, SessionStatus, CharacterBrief } from "../lib/types";
import ChatDrawer from "../components/ChatDrawer";

/* ------------------------------------------------------------------ */
/*  Extraction context — shared with child pages                      */
/* ------------------------------------------------------------------ */

interface ExtractionContextValue {
  sseEvents: SSEEvent[];
  isExtracting: boolean;
  sessionStatus: SessionStatus | undefined;
  characters: CharacterBrief[];
}

const ExtractionContext = createContext<ExtractionContextValue>({
  sseEvents: [],
  isExtracting: false,
  sessionStatus: undefined,
  characters: [],
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
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  // Poll session status
  const { data: sessionStatus } = useQuery({
    queryKey: ["session-status", sessionId],
    queryFn: () => fetchSessionStatus(sessionId!),
    enabled: !!sessionId,
    refetchInterval: isExtracting ? 2000 : false,
  });

  // Fetch overview for character list (used by ChatDrawer)
  const { data: overview } = useQuery({
    queryKey: ["overview", sessionId],
    queryFn: () => fetchOverview(sessionId!),
    enabled: !!sessionId,
    refetchInterval: isExtracting ? 2000 : false,
  });

  const characters: CharacterBrief[] = overview?.characters_brief ?? [];

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

  const title = locationState?.title ?? overview?.title ?? "书籍分析";

  const handleSave = async () => {
    if (!sessionId || saving) return;
    setSaving(true);
    setSaveMsg(null);
    try {
      await saveToLibrary(sessionId);
      setSaveMsg("已保存到书库");
      setTimeout(() => setSaveMsg(null), 2500);
    } catch {
      setSaveMsg("保存失败");
      setTimeout(() => setSaveMsg(null), 2500);
    } finally {
      setSaving(false);
    }
  };

  const contextValue: ExtractionContextValue = {
    sseEvents,
    isExtracting,
    sessionStatus,
    characters,
  };

  return (
    <ExtractionContext.Provider value={contextValue}>
      <div className="min-h-svh flex flex-col">
        {/* Header */}
        <header className="sticky top-0 z-40 bg-[var(--bg)]/80 backdrop-blur-md border-b border-[var(--border)]">
          <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
            {/* Left: branding + title */}
            <div className="flex items-center gap-3 min-w-0">
              <button
                onClick={() => navigate("/")}
                className="text-lg text-[var(--accent)] shrink-0 hover:opacity-80 transition-opacity"
                style={{ fontFamily: "var(--font-display)" }}
              >
                书鉴
              </button>
              <span className="text-xs text-[var(--border)]">|</span>
              <h1
                className="text-base truncate text-[var(--text)]"
                style={{
                  fontFamily: "var(--font-display)",
                  letterSpacing: "0.08em",
                }}
              >
                {title}
              </h1>
              {isExtracting && (
                <span className="shrink-0 ml-2 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider bg-[var(--accent)]/15 text-[var(--accent)] rounded-full">
                  提取中
                </span>
              )}
            </div>

            {/* Right: actions */}
            <div className="flex items-center gap-1.5">
              <button
                onClick={handleSave}
                disabled={saving}
                className="p-2 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all relative"
                title="保存到书库"
              >
                <Save className="w-4 h-4" />
              </button>
              <button
                onClick={() => navigate("/library")}
                className="p-2 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all"
                title="书库"
              >
                <Library className="w-4 h-4" />
              </button>
              <button
                onClick={() => navigate("/settings")}
                className="p-2 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all"
                title="设置"
              >
                <Settings className="w-4 h-4" />
              </button>
              <button
                onClick={() => navigate("/")}
                className="p-2 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all"
                title="新建分析"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>
          </div>

          {/* Save toast */}
          {saveMsg && (
            <div className="absolute top-14 left-1/2 -translate-x-1/2 px-3 py-1.5 rounded-lg bg-[var(--surface)] border border-[var(--border)] text-xs text-[var(--text)] shadow-lg animate-[fadeIn_0.2s_ease-out]">
              {saveMsg}
            </div>
          )}
        </header>

        {/* Content */}
        <main className="flex-1 max-w-6xl mx-auto w-full px-4 py-6 pb-20">
          <Outlet />
        </main>

        {/* Floating chat button */}
        <button
          onClick={() => setChatOpen(true)}
          className={clsx(
            "fixed bottom-6 right-6 z-40 flex items-center gap-2 px-4 py-3 rounded-full shadow-lg transition-all duration-300",
            "bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] hover:scale-105",
            "active:scale-95",
            chatOpen && "opacity-0 pointer-events-none",
          )}
        >
          <MessageCircle className="w-5 h-5" />
          <span className="text-sm font-medium hidden sm:inline">问书</span>
        </button>

        {/* Chat drawer */}
        {sessionId && (
          <ChatDrawer
            open={chatOpen}
            onClose={() => setChatOpen(false)}
            sessionId={sessionId}
            characters={characters}
          />
        )}
      </div>
    </ExtractionContext.Provider>
  );
}
