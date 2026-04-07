import { useParams, useLocation, useNavigate } from "react-router-dom";
import { useState, lazy, Suspense } from "react";
import {
  BookOpen, Sparkles, MessageCircle, Search, BarChart3,
  Save, Share2, Download, Check, Link, Library,
} from "lucide-react";
import type { AnalysisResult } from "../lib/api";
import {
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

// Lazy-loaded deep analysis charts (Recharts heavy)
const EmotionHeatmap = lazy(() => import("../components/EmotionHeatmap"));
const EmotionTimeline = lazy(() => import("../components/EmotionTimeline"));
const StyleRadarFull = lazy(() => import("../components/StyleRadarFull"));

type Tab = "overview" | "depth" | "insights" | "chat" | "search";

export default function BookPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as {
    analysis?: AnalysisResult;
    title?: string;
    bookType?: string;
    hasKnowledgeGraph?: boolean;
  } | null;
  const analysis = state?.analysis;
  const title = state?.title ?? "Untitled";
  const bookType = state?.bookType ?? "fiction";
  const [hasKG] = useState(state?.hasKnowledgeGraph ?? false);

  const [activeTab, setActiveTab] = useState<Tab>("overview");
  const [saved, setSaved] = useState(false);
  const [shareUrl, setShareUrl] = useState("");

  if (!analysis || !sessionId) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <p className="text-[var(--bs-text-muted)]">No analysis data found.</p>
          <button
            onClick={() => navigate("/")}
            className="text-[var(--bs-accent)] hover:underline"
          >
            Upload a book
          </button>
        </div>
      </div>
    );
  }

  const handleSave = async () => {
    try {
      await saveToLibrary(sessionId);
      setSaved(true);
    } catch {
      // silent
    }
  };

  const handleShare = async () => {
    try {
      const data = await createShareLink(sessionId);
      const url = `${window.location.origin}${data.url}`;
      setShareUrl(url);
      await navigator.clipboard.writeText(url);
    } catch {
      // silent
    }
  };

  const { reader_verdict, readability, arc_pattern, dominant_emotion, valence_series, emotion_scores } = analysis;

  return (
    <div className="min-h-screen">
      {/* ── Identity Bar ────────────────────────────────────── */}
      <header className="sticky top-0 z-10 bg-[var(--bs-bg)]/95 backdrop-blur border-b border-[var(--bs-border)]">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <BookOpen className="w-5 h-5 text-[var(--bs-accent)]" strokeWidth={1.5} />
            <h1 className="text-lg font-medium truncate max-w-md">{title}</h1>
          </div>
          <div className="flex items-center gap-2">
            {/* Save to Library */}
            <button
              onClick={handleSave}
              disabled={saved}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg
                         border border-[var(--bs-border)] text-[var(--bs-text-muted)]
                         hover:border-[var(--bs-accent)] hover:text-[var(--bs-accent)]
                         disabled:opacity-50 transition-colors"
              title="Save to library"
            >
              {saved ? <Check className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
              {saved ? "Saved" : "Save"}
            </button>

            {/* Share */}
            <button
              onClick={handleShare}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg
                         border border-[var(--bs-border)] text-[var(--bs-text-muted)]
                         hover:border-[var(--bs-accent)] hover:text-[var(--bs-accent)]
                         transition-colors"
              title={shareUrl || "Create share link"}
            >
              {shareUrl ? <Link className="w-3.5 h-3.5" /> : <Share2 className="w-3.5 h-3.5" />}
              {shareUrl ? "Copied" : "Share"}
            </button>

            {/* Export dropdown */}
            <div className="relative group">
              <button
                className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg
                           border border-[var(--bs-border)] text-[var(--bs-text-muted)]
                           hover:border-[var(--bs-accent)] hover:text-[var(--bs-accent)]
                           transition-colors"
              >
                <Download className="w-3.5 h-3.5" />
                Export
              </button>
              <div className="absolute right-0 top-full mt-1 bg-[var(--bs-surface)] border border-[var(--bs-border)]
                              rounded-lg shadow-lg py-1 min-w-[140px] opacity-0 invisible
                              group-hover:opacity-100 group-hover:visible transition-all z-20">
                <a
                  href={getExportJsonUrl(sessionId)}
                  download
                  className="block px-3 py-1.5 text-xs text-[var(--bs-text)] hover:bg-[var(--bs-border)]/50"
                >
                  JSON
                </a>
                <a
                  href={getExportMarkdownUrl(sessionId)}
                  download
                  className="block px-3 py-1.5 text-xs text-[var(--bs-text)] hover:bg-[var(--bs-border)]/50"
                >
                  Markdown Report
                </a>
              </div>
            </div>

            {/* Library link */}
            <button
              onClick={() => navigate("/library")}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg
                         border border-[var(--bs-border)] text-[var(--bs-text-muted)]
                         hover:border-[var(--bs-accent)] hover:text-[var(--bs-accent)]
                         transition-colors"
              title="View library"
            >
              <Library className="w-3.5 h-3.5" />
            </button>

            <button
              onClick={() => navigate("/")}
              className="text-sm text-[var(--bs-text-muted)] hover:text-[var(--bs-accent)] transition-colors ml-2"
            >
              New analysis
            </button>
          </div>
        </div>
      </header>

      {/* ── Tab Nav ─────────────────────────────────────────── */}
      <nav className="max-w-5xl mx-auto px-4 pt-4 flex gap-1">
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
              flex items-center gap-2 px-4 py-2 rounded-lg text-sm transition-all
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
            <NarrativeCard sessionId={sessionId} bookType={bookType} uiLang="en" />
            <SoulCards sessionId={sessionId} hasKnowledgeGraph={hasKG} />
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <BookClubCard sessionId={sessionId} bookType={bookType} uiLang="en" />
              <RecommendationsCard sessionId={sessionId} bookType={bookType} uiLang="en" />
            </div>
          </div>
        )}

        {activeTab === "chat" && <ChatPanel sessionId={sessionId} />}
        {activeTab === "search" && <SearchPanel sessionId={sessionId} />}
      </main>
    </div>
  );
}
