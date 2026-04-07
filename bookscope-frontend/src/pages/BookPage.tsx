import { useParams, useLocation, useNavigate } from "react-router-dom";
import { useState, useEffect, useRef, lazy, Suspense } from "react";
import {
  BookOpen, Sparkles, MessageCircle, Search, BarChart3,
  Save, Share2, Download, Check, Link, Library, Loader2,
} from "lucide-react";
import type { AnalysisResult } from "../lib/api";
import {
  fetchSessionAnalysis, fetchLibraryAnalysis,
  saveToLibrary, createShareLink,
  getExportJsonUrl, getExportMarkdownUrl,
} from "../lib/api";
import VerdictCard from "../components/VerdictCard";
import EmotionRadar from "../components/EmotionRadar";
import ArcChart from "../components/ArcChart";
import NarrativeCard from "../components/NarrativeCard";
import SoulCards from "../components/SoulCards";
import BookClubCard from "../components/BookClubCard";
import RecommendationsCard from "../components/RecommendationsCard";
import ChatPanel from "../components/ChatPanel";
import SearchPanel from "../components/SearchPanel";

const EmotionHeatmap = lazy(() => import("../components/EmotionHeatmap"));
const EmotionTimeline = lazy(() => import("../components/EmotionTimeline"));
const StyleRadarFull = lazy(() => import("../components/StyleRadarFull"));

type Tab = "overview" | "depth" | "insights" | "chat" | "search";

interface ChatMsg {
  role: "user" | "assistant";
  content: string;
}

export default function BookPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as {
    analysis?: AnalysisResult;
    title?: string;
    bookType?: string;
    language?: string;
    hasKnowledgeGraph?: boolean;
  } | null;

  // Core state — populated from location.state OR fetched from API
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(state?.analysis ?? null);
  const [title, setTitle] = useState(state?.title ?? "");
  const [bookType, setBookType] = useState(state?.bookType ?? "fiction");
  const [uiLang, setUiLang] = useState(state?.language ?? "en");
  const [hasKG, setHasKG] = useState(state?.hasKnowledgeGraph ?? false);
  const [loading, setLoading] = useState(!state?.analysis);
  const [error, setError] = useState("");

  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [saved, setSaved] = useState(false);
  const [shareUrl, setShareUrl] = useState("");
  const [chatHistory, setChatHistory] = useState<ChatMsg[]>([]);
  const [exportOpen, setExportOpen] = useState(false);
  const exportRef = useRef<HTMLDivElement>(null);

  // Is this a library view? (lib:<filename> prefix from LibraryPage)
  const isLibraryView = sessionId?.startsWith("lib:") ?? false;
  const libraryFilename = isLibraryView ? sessionId!.slice(4) : null;

  // #1: Recover analysis from API on refresh (location.state is gone)
  useEffect(() => {
    if (analysis || !sessionId) return;
    setLoading(true);
    const fetchFn = libraryFilename
      ? fetchLibraryAnalysis(libraryFilename)
      : fetchSessionAnalysis(sessionId);
    fetchFn
      .then((data) => {
        setAnalysis(data);
        setTitle(data.title);
        setBookType(data.book_type);
        setUiLang(data.language);
        setHasKG(data.has_knowledge_graph);
        setLoading(false);
      })
      .catch(() => {
        setError("Session expired or analysis not found.");
        setLoading(false);
      });
  }, [sessionId, analysis]);

  // Close export dropdown on outside click
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (exportRef.current && !exportRef.current.contains(e.target as Node)) {
        setExportOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-[var(--bs-accent)] animate-spin" />
      </div>
    );
  }

  if (error || !analysis || !sessionId) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <p className="text-[var(--bs-text-muted)]">{error || "No analysis data found."}</p>
          <button onClick={() => navigate("/")} className="text-[var(--bs-accent)] hover:underline">
            Upload a book
          </button>
        </div>
      </div>
    );
  }

  const handleSave = async () => {
    try { await saveToLibrary(sessionId); setSaved(true); } catch { /* silent */ }
  };

  const handleShare = async () => {
    try {
      const data = await createShareLink(sessionId);
      const url = `${window.location.origin}${data.url}`;
      setShareUrl(url);
      await navigator.clipboard.writeText(url);
    } catch { /* silent */ }
  };

  const { reader_verdict, readability, arc_pattern, dominant_emotion, valence_series, emotion_scores } = analysis;

  return (
    <div className="min-h-screen">
      {/* ── Identity Bar (responsive: #10) ─────────────────── */}
      <header className="sticky top-0 z-10 bg-[var(--bs-bg)]/95 backdrop-blur border-b border-[var(--bs-border)]">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between gap-2">
          <div className="flex items-center gap-3 min-w-0">
            <BookOpen className="w-5 h-5 text-[var(--bs-accent)] flex-shrink-0" strokeWidth={1.5} />
            <h1 className="text-lg font-medium truncate">{title}</h1>
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <button
              onClick={handleSave}
              disabled={saved}
              className="hidden sm:flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg
                         border border-[var(--bs-border)] text-[var(--bs-text-muted)]
                         hover:border-[var(--bs-accent)] hover:text-[var(--bs-accent)]
                         disabled:opacity-50 transition-colors"
              title="Save to library"
            >
              {saved ? <Check className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
              <span className="hidden md:inline">{saved ? "Saved" : "Save"}</span>
            </button>

            <button
              onClick={handleShare}
              className="hidden sm:flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg
                         border border-[var(--bs-border)] text-[var(--bs-text-muted)]
                         hover:border-[var(--bs-accent)] hover:text-[var(--bs-accent)]
                         transition-colors"
              title={shareUrl || "Create share link"}
            >
              {shareUrl ? <Link className="w-3.5 h-3.5" /> : <Share2 className="w-3.5 h-3.5" />}
              <span className="hidden md:inline">{shareUrl ? "Copied" : "Share"}</span>
            </button>

            {/* Export (click toggle, not hover — works on mobile) */}
            <div className="relative" ref={exportRef}>
              <button
                onClick={() => setExportOpen(!exportOpen)}
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg
                           border border-[var(--bs-border)] text-[var(--bs-text-muted)]
                           hover:border-[var(--bs-accent)] hover:text-[var(--bs-accent)]
                           transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                <span className="hidden md:inline">Export</span>
              </button>
              {exportOpen && (
                <div className="absolute right-0 top-full mt-1 bg-[var(--bs-surface)] border border-[var(--bs-border)]
                                rounded-lg shadow-lg py-1 min-w-[160px] z-20">
                  <a href={getExportJsonUrl(sessionId)} download
                     className="block px-3 py-2 text-xs text-[var(--bs-text)] hover:bg-[var(--bs-border)]/50">
                    Export JSON
                  </a>
                  <a href={getExportMarkdownUrl(sessionId)} download
                     className="block px-3 py-2 text-xs text-[var(--bs-text)] hover:bg-[var(--bs-border)]/50">
                    Export Markdown
                  </a>
                  {/* Mobile-only: Save & Share */}
                  <button onClick={handleSave} disabled={saved}
                          className="sm:hidden block w-full text-left px-3 py-2 text-xs text-[var(--bs-text)] hover:bg-[var(--bs-border)]/50 disabled:opacity-50">
                    {saved ? "Saved to Library" : "Save to Library"}
                  </button>
                  <button onClick={handleShare}
                          className="sm:hidden block w-full text-left px-3 py-2 text-xs text-[var(--bs-text)] hover:bg-[var(--bs-border)]/50">
                    {shareUrl ? "Link Copied" : "Share Link"}
                  </button>
                </div>
              )}
            </div>

            <button
              onClick={() => navigate("/library")}
              className="flex items-center text-xs px-2 py-1.5 rounded-lg
                         border border-[var(--bs-border)] text-[var(--bs-text-muted)]
                         hover:border-[var(--bs-accent)] hover:text-[var(--bs-accent)]
                         transition-colors"
              title="Library"
            >
              <Library className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={() => navigate("/")}
              className="text-xs text-[var(--bs-text-muted)] hover:text-[var(--bs-accent)] transition-colors px-2"
            >
              New
            </button>
          </div>
        </div>
      </header>

      {/* ── Tab Nav (scrollable on mobile: #10) ─────────────── */}
      <nav className="max-w-5xl mx-auto px-4 pt-4 flex gap-1 overflow-x-auto">
        {([
          { key: "overview", label: "Overview", icon: BookOpen },
          { key: "depth", label: "Deep Analysis", icon: BarChart3 },
          { key: "insights", label: "Insights", icon: Sparkles },
          { key: "chat", label: "Chat", icon: MessageCircle },
          { key: "search", label: "Search", icon: Search },
        ] as const).map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            className={`
              flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all whitespace-nowrap
              ${activeTab === key
                ? "bg-[var(--bs-accent)]/10 text-[var(--bs-accent)] font-medium"
                : "text-[var(--bs-text-muted)] hover:bg-[var(--bs-border)]/50"
              }
            `}
          >
            <Icon className="w-4 h-4" strokeWidth={1.5} />
            {label}
          </button>
        ))}
      </nav>

      {/* ── Content ─────────────────────────────────────────── */}
      <main className="max-w-5xl mx-auto px-4 py-6">
        {activeTab === "overview" && (
          <div className="space-y-6">
            <VerdictCard
              verdict={reader_verdict}
              readability={readability}
              arcPattern={arc_pattern}
              dominantEmotion={dominant_emotion}
            />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <EmotionRadar emotionScores={emotion_scores} />
              <ArcChart valenceSeries={valence_series} arcPattern={arc_pattern} />
            </div>
          </div>
        )}

        {activeTab === "depth" && (
          <Suspense fallback={
            <div className="text-center py-10 text-sm text-[var(--bs-text-muted)]">Loading charts...</div>
          }>
            <div className="space-y-6">
              <EmotionHeatmap sessionId={sessionId} />
              <EmotionTimeline sessionId={sessionId} />
              <StyleRadarFull sessionId={sessionId} />
            </div>
          </Suspense>
        )}

        {activeTab === "insights" && (
          <div className="space-y-6">
            {/* #6: Use session language, not hardcoded "en" */}
            <NarrativeCard sessionId={sessionId} bookType={bookType} uiLang={uiLang} />
            {/* #2: SoulCards with KG trigger */}
            <SoulCards sessionId={sessionId} hasKnowledgeGraph={hasKG} onKGReady={() => setHasKG(true)} />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <BookClubCard sessionId={sessionId} bookType={bookType} uiLang={uiLang} />
              <RecommendationsCard sessionId={sessionId} bookType={bookType} uiLang={uiLang} />
            </div>
          </div>
        )}

        {/* #9: Chat with persistent history across tab switches */}
        {activeTab === "chat" && (
          <ChatPanel sessionId={sessionId} uiLang={uiLang} history={chatHistory} onHistoryChange={setChatHistory} />
        )}
        {activeTab === "search" && <SearchPanel sessionId={sessionId} />}
      </main>
    </div>
  );
}
