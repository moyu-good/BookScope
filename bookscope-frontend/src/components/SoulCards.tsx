import { useState, useEffect, useRef } from "react";
import { Users, Brain, Quote, Heart, ChevronDown, ChevronUp, Sparkles, Loader2 } from "lucide-react";
import { soulEnrichSSE, kgExtractSSE, type SoulCharacter } from "../lib/api";

interface SoulCardsProps {
  sessionId: string;
  hasKnowledgeGraph: boolean;
  onKGReady?: () => void;
}

export default function SoulCards({ sessionId, hasKnowledgeGraph, onKGReady }: SoulCardsProps) {
  const [characters, setCharacters] = useState<SoulCharacter[]>([]);
  const [loading, setLoading] = useState(false);
  const [extracting, setExtracting] = useState(false);
  const [extractProgress, setExtractProgress] = useState({ current: 0, total: 0 });
  const [progress, setProgress] = useState({ current: 0, total: 0, name: "" });
  const [error, setError] = useState("");
  const controllerRef = useRef<AbortController | null>(null);

  // Auto-trigger soul enrichment when KG becomes available
  useEffect(() => {
    if (!hasKnowledgeGraph) return;
    setLoading(true);
    setError("");

    controllerRef.current = soulEnrichSSE(
      sessionId,
      (data) => setProgress({
        current: data.current ?? 0,
        total: data.total ?? 0,
        name: data.character ?? "",
      }),
      (chars) => {
        setCharacters(chars);
        setLoading(false);
      },
      (err) => {
        setLoading(false);
        setError(err.message);
      },
    );

    return () => controllerRef.current?.abort();
  }, [sessionId, hasKnowledgeGraph]);

  const handleExtract = () => {
    setExtracting(true);
    setError("");
    controllerRef.current = kgExtractSSE(
      sessionId,
      (current, total) => setExtractProgress({ current, total }),
      () => {
        setExtracting(false);
        onKGReady?.();
      },
      (err) => {
        setExtracting(false);
        setError(err.message);
      },
    );
  };

  if (extracting) {
    return (
      <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6">
        <div className="flex items-center gap-2 mb-3">
          <Users className="w-4 h-4 text-violet-500" strokeWidth={1.5} />
          <h3 className="text-sm font-semibold tracking-wide uppercase text-[var(--bs-text-muted)]">
            Knowledge Graph
          </h3>
        </div>
        <div className="flex items-center gap-3 text-sm text-[var(--bs-text-muted)]">
          <Loader2 className="w-4 h-4 text-violet-500 animate-spin" />
          Extracting knowledge graph... ({extractProgress.current}/{extractProgress.total})
        </div>
      </div>
    );
  }

  if (!hasKnowledgeGraph) {
    return (
      <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6 text-center">
        <Users className="mx-auto w-8 h-8 mb-3 text-[var(--bs-text-muted)] opacity-40" />
        <p className="text-sm text-[var(--bs-text-muted)] mb-4">
          Extract knowledge graph to unlock character soul profiles
        </p>
        <button
          onClick={handleExtract}
          className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm
                     bg-violet-500/10 text-violet-400 hover:bg-violet-500/20 transition-colors"
        >
          <Sparkles className="w-4 h-4" />
          Extract Knowledge Graph
        </button>
        {error && <p className="mt-3 text-xs text-red-400">{error}</p>}
      </div>
    );
  }

  if (loading) {
    return (
      <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6">
        <div className="flex items-center gap-2 mb-3">
          <Users className="w-4 h-4 text-violet-500" strokeWidth={1.5} />
          <h3 className="text-sm font-semibold tracking-wide uppercase text-[var(--bs-text-muted)]">
            Character Souls
          </h3>
        </div>
        <div className="flex items-center gap-3 text-sm text-[var(--bs-text-muted)]">
          <div className="w-4 h-4 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
          Enriching {progress.name}... ({progress.current}/{progress.total})
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-6">
        <p className="text-sm text-red-400">{error}</p>
      </div>
    );
  }

  if (characters.length === 0) return null;

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Users className="w-4 h-4 text-violet-500" strokeWidth={1.5} />
        <h3 className="text-sm font-semibold tracking-wide uppercase text-[var(--bs-text-muted)]">
          Character Souls
        </h3>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {characters.map((char) => (
          <CharacterCard key={char.name} character={char} />
        ))}
      </div>
    </div>
  );
}

function CharacterCard({ character }: { character: SoulCharacter }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="bg-[var(--bs-surface)] border border-[var(--bs-border)] rounded-2xl p-5 space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h4 className="font-semibold text-[var(--bs-text)]">{character.name}</h4>
          {character.description && (
            <p className="text-xs text-[var(--bs-text-muted)] mt-0.5">{character.description}</p>
          )}
        </div>
        {character.personality_type && (
          <span className="text-xs font-mono px-2 py-1 rounded-lg bg-violet-500/10 text-violet-400 whitespace-nowrap">
            {character.personality_type.split("—")[0]?.trim()}
          </span>
        )}
      </div>

      {/* MBTI label */}
      {character.personality_type && character.personality_type.includes("—") && (
        <div className="flex items-center gap-1.5 text-xs text-[var(--bs-text-muted)]">
          <Brain className="w-3 h-3" />
          {character.personality_type}
        </div>
      )}

      {/* Values */}
      {character.values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {character.values.map((v) => (
            <span
              key={v}
              className="text-xs px-2 py-0.5 rounded-full bg-[var(--bs-border)] text-[var(--bs-text-muted)]"
            >
              {v}
            </span>
          ))}
        </div>
      )}

      {/* Top quote */}
      {character.key_quotes.length > 0 && (
        <div className="flex gap-2 text-sm text-[var(--bs-text)] italic">
          <Quote className="w-3.5 h-3.5 text-amber-500 flex-shrink-0 mt-0.5" />
          <span className="line-clamp-2">{character.key_quotes[0]}</span>
        </div>
      )}

      {/* Expand toggle */}
      {(character.emotional_stages.length > 0 || character.key_quotes.length > 1) && (
        <>
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 text-xs text-[var(--bs-accent)] hover:underline"
          >
            {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            {expanded ? "Less" : "More"}
          </button>

          {expanded && (
            <div className="space-y-3 pt-1">
              {/* Emotional arc */}
              {character.emotional_stages.length > 0 && (
                <div className="space-y-1.5">
                  <div className="flex items-center gap-1.5 text-xs font-medium text-[var(--bs-text-muted)]">
                    <Heart className="w-3 h-3" />
                    Emotional Arc
                  </div>
                  <div className="flex gap-2">
                    {character.emotional_stages.map((stage, i) => (
                      <div
                        key={i}
                        className="flex-1 text-xs bg-[var(--bs-bg)] rounded-lg p-2"
                      >
                        <div className="font-medium text-[var(--bs-text)] capitalize">
                          {stage.stage}
                        </div>
                        <div className="text-[var(--bs-text-muted)]">{stage.emotion}</div>
                        <div className="text-[var(--bs-text-muted)] mt-0.5 line-clamp-2">
                          {stage.event}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* More quotes */}
              {character.key_quotes.length > 1 && (
                <div className="space-y-1">
                  {character.key_quotes.slice(1).map((q, i) => (
                    <div key={i} className="flex gap-2 text-xs text-[var(--bs-text-muted)] italic">
                      <Quote className="w-3 h-3 text-amber-500/50 flex-shrink-0 mt-0.5" />
                      <span>{q}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
