import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Loader2, BookOpen } from "lucide-react";
import { fetchShareAnalysis, type SessionAnalysis } from "../lib/api";
import VerdictCard from "../components/VerdictCard";
import EmotionRadar from "../components/EmotionRadar";
import ArcChart from "../components/ArcChart";

export default function SharePage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [analysis, setAnalysis] = useState<SessionAnalysis | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!token) return;
    fetchShareAnalysis(token)
      .then((data) => {
        setAnalysis(data);
        setLoading(false);
      })
      .catch(() => {
        setError("Share link expired or not found.");
        setLoading(false);
      });
  }, [token]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-6 h-6 text-[var(--bs-accent)] animate-spin" />
      </div>
    );
  }

  if (error || !analysis) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <p className="text-[var(--bs-text-muted)]">{error || "No data found."}</p>
          <button onClick={() => navigate("/")} className="text-[var(--bs-accent)] hover:underline">
            Upload a book
          </button>
        </div>
      </div>
    );
  }

  const { reader_verdict, readability, arc_pattern, dominant_emotion, valence_series, emotion_scores } = analysis;

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 bg-[var(--bs-bg)]/95 backdrop-blur border-b border-[var(--bs-border)]">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <BookOpen className="w-5 h-5 text-[var(--bs-accent)]" strokeWidth={1.5} />
            <h1 className="text-lg font-medium truncate">{analysis.title}</h1>
          </div>
          <span className="text-xs text-[var(--bs-text-muted)]">Shared analysis</span>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-6 space-y-6">
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
      </main>
    </div>
  );
}
