import { useParams, useLocation, useNavigate } from "react-router-dom";
import { useState } from "react";
import { BookOpen, BarChart3, MessageCircle, Search } from "lucide-react";
import type { AnalysisResult } from "../lib/api";
import VerdictCard from "../components/VerdictCard";
import EmotionRadar from "../components/EmotionRadar";
import ArcChart from "../components/ArcChart";
import ChatPanel from "../components/ChatPanel";
import SearchPanel from "../components/SearchPanel";

type Tab = "overview" | "depth" | "chat" | "search";

export default function BookPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const location = useLocation();
  const navigate = useNavigate();
  const state = location.state as { analysis?: AnalysisResult; title?: string } | null;
  const analysis = state?.analysis;
  const title = state?.title ?? "Untitled";

  const [activeTab, setActiveTab] = useState<Tab>("overview");

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
          <button
            onClick={() => navigate("/")}
            className="text-sm text-[var(--bs-text-muted)] hover:text-[var(--bs-accent)] transition-colors"
          >
            New analysis
          </button>
        </div>
      </header>

      {/* ── Tab Nav ─────────────────────────────────────────── */}
      <nav className="max-w-5xl mx-auto px-4 pt-4 flex gap-1">
        {([
          { key: "overview", label: "Overview", icon: BookOpen },
          { key: "depth", label: "Deep Analysis", icon: BarChart3 },
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
            {/* L1: What is this book about? (Verdict) */}
            <VerdictCard
              verdict={reader_verdict}
              readability={readability}
              arcPattern={arc_pattern}
              dominantEmotion={dominant_emotion}
            />

            {/* L2: How does it feel? (Emotion + Arc) */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <EmotionRadar emotionScores={emotion_scores} />
              <ArcChart valenceSeries={valence_series} arcPattern={arc_pattern} />
            </div>
          </div>
        )}

        {activeTab === "depth" && (
          <div className="text-center py-20 text-[var(--bs-text-muted)]">
            <BarChart3 className="mx-auto w-12 h-12 mb-4 opacity-30" />
            <p>Deep analysis charts — coming in Phase 2</p>
            <p className="text-sm mt-1">Heatmap, timeline, style radar, and more</p>
          </div>
        )}

        {activeTab === "chat" && (
          <ChatPanel sessionId={sessionId} />
        )}

        {activeTab === "search" && (
          <SearchPanel sessionId={sessionId} />
        )}
      </main>
    </div>
  );
}
