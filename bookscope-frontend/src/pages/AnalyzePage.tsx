import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { analyzeSSE, type AnalysisProgress, type AnalysisResult } from "../lib/api";

const STAGE_LABELS: Record<string, string> = {
  emotion: "Analyzing emotions",
  style: "Analyzing writing style",
  arc: "Classifying narrative arc",
};

export default function AnalyzePage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const meta = location.state as { title?: string; total_chunks?: number } | null;

  const [stage, setStage] = useState("emotion");
  const [current, setCurrent] = useState(0);
  const [total, setTotal] = useState(meta?.total_chunks ?? 0);
  const [error, setError] = useState<string | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!sessionId) return;

    controllerRef.current = analyzeSSE(
      sessionId,
      "fiction", // default; can be extended later
      "en",
      (progress: AnalysisProgress) => {
        setStage(progress.stage);
        setCurrent(progress.current);
        setTotal(progress.total);
      },
      (_result: AnalysisResult) => {
        // Navigate to results with the analysis data
        navigate(`/book/${sessionId}`, { state: { analysis: _result, title: meta?.title } });
      },
      (err: Error) => setError(err.message)
    );

    return () => {
      controllerRef.current?.abort();
    };
  }, [sessionId, navigate, meta?.title]);

  const pct = total > 0 ? Math.round((current / total) * 100) : 0;
  const stageLabel = STAGE_LABELS[stage] || stage;

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="w-full max-w-md text-center">
        {meta?.title && (
          <h2 className="text-xl font-light mb-8 text-[var(--bs-text)]">
            {meta.title}
          </h2>
        )}

        {error ? (
          <div className="space-y-4">
            <p className="text-red-600">{error}</p>
            <button
              onClick={() => navigate("/")}
              className="text-[var(--bs-accent)] hover:underline"
            >
              Back to upload
            </button>
          </div>
        ) : (
          <div className="space-y-6">
            <Loader2 className="mx-auto w-8 h-8 text-[var(--bs-accent)] animate-spin" />

            <div>
              <p className="text-[var(--bs-text)] font-medium mb-2">
                {stageLabel}...
              </p>
              {/* Progress bar */}
              <div className="w-full bg-[var(--bs-border)] rounded-full h-2 overflow-hidden">
                <div
                  className="bg-[var(--bs-accent)] h-full rounded-full transition-all duration-300"
                  style={{ width: `${pct}%` }}
                />
              </div>
              <p className="text-sm text-[var(--bs-text-muted)] mt-2">
                {current} / {total} chunks · {pct}%
              </p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
