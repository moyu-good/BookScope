import { useState } from "react";
import { useParams } from "react-router-dom";
import { ChevronDown, ChevronRight } from "lucide-react";
import ChatPanel from "../components/ChatPanel";
import SearchPanel from "../components/SearchPanel";

export default function ExplorePage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [showAdvanced, setShowAdvanced] = useState(false);

  if (!sessionId) return null;

  return (
    <div className="space-y-6">
      {/* RAG Chat */}
      <ChatPanel sessionId={sessionId} />

      {/* Full-text search */}
      <SearchPanel sessionId={sessionId} />

      {/* Advanced analysis — collapsible */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl overflow-hidden">
        <button
          onClick={() => setShowAdvanced((v) => !v)}
          className="w-full px-5 py-3 flex items-center justify-between text-left hover:bg-[var(--surface-hover)] transition-colors duration-200"
        >
          <span className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
            高级分析
          </span>
          {showAdvanced ? (
            <ChevronDown className="w-4 h-4 text-[var(--text-secondary)]" />
          ) : (
            <ChevronRight className="w-4 h-4 text-[var(--text-secondary)]" />
          )}
        </button>

        {showAdvanced && (
          <div className="px-5 pb-5 space-y-4 border-t border-[var(--border)] pt-4">
            <p className="text-xs text-[var(--text-secondary)]">
              详细的情绪热力图、文风雷达和叙事分析将在提取完成后可用。
              可在总览页查看图表。
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
