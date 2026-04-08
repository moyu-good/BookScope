import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Sparkles, Loader2, User, ChevronLeft, ChevronRight } from "lucide-react";
import clsx from "clsx";
import { fetchCharacter, enrichCharacter } from "../lib/api";
import { useExtraction } from "./BookLayout";
import type { CharacterProfile, SSEEvent } from "../lib/types";
import SoulProfileCard from "../components/SoulProfileCard";
import CharacterQuotes from "../components/CharacterQuotes";
import EmotionalArcTimeline from "../components/EmotionalArcTimeline";
import CharacterChat from "../components/CharacterChat";

export default function CharacterPage() {
  const { sessionId, name } = useParams<{
    sessionId: string;
    name: string;
  }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const decodedName = name ? decodeURIComponent(name) : "";

  const { characters } = useExtraction();

  const [enriching, setEnriching] = useState(false);
  const [enrichError, setEnrichError] = useState<string | null>(null);
  const enrichStartedRef = useRef(false);
  const stripRef = useRef<HTMLDivElement>(null);

  const {
    data: character,
    isLoading,
    error,
  } = useQuery<CharacterProfile>({
    queryKey: ["character", sessionId, decodedName],
    queryFn: () => fetchCharacter(sessionId!, decodedName),
    enabled: !!sessionId && !!decodedName,
  });

  // Reset enrichment state when character changes
  useEffect(() => {
    enrichStartedRef.current = false;
    setEnriching(false);
    setEnrichError(null);
  }, [decodedName]);

  // Auto-trigger enrichment if character exists but has no soul
  useEffect(() => {
    if (!character || character.has_soul) return;
    if (enrichStartedRef.current) return;
    if (!sessionId) return;

    enrichStartedRef.current = true;
    setEnriching(true);
    setEnrichError(null);

    const sse = enrichCharacter(sessionId, decodedName);
    sse.onEvent((event: SSEEvent) => {
      if (event.type === "done") {
        setEnriching(false);
        queryClient.invalidateQueries({
          queryKey: ["character", sessionId, decodedName],
        });
      } else if (event.type === "error") {
        setEnriching(false);
        setEnrichError(
          (event as { message?: string }).message ?? "Enrichment failed",
        );
      }
    });
    sse.onError((err) => {
      setEnriching(false);
      setEnrichError(err);
    });
    sse.onDone(() => {
      setEnriching(false);
    });
    sse.start();

    return () => sse.abort();
  }, [character, sessionId, decodedName, queryClient]);

  // Current character index for prev/next
  const currentIndex = characters.findIndex((c) => c.name === decodedName);

  const goToCharacter = (charName: string) => {
    navigate(`/book/${sessionId}/character/${encodeURIComponent(charName)}`);
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-6 h-6 animate-spin text-[var(--accent)]" />
      </div>
    );
  }

  if (error || !character) {
    return (
      <div className="text-center py-16">
        <p className="text-[var(--text-secondary)] mb-4">
          {error instanceof Error ? error.message : "未找到该人物"}
        </p>
        <button
          onClick={() => navigate(`/book/${sessionId}`)}
          className="text-[var(--accent)] hover:underline text-sm"
        >
          返回总览
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Character navigation strip */}
      {characters.length > 1 && (
        <div className="flex items-center gap-2">
          <button
            onClick={() => navigate(`/book/${sessionId}`)}
            className="shrink-0 p-1.5 rounded-lg text-[var(--text-secondary)] hover:text-[var(--accent)] hover:bg-[var(--surface)] transition-all"
            title="返回总览"
          >
            <ArrowLeft className="w-4 h-4" />
          </button>

          {/* Prev button */}
          {currentIndex > 0 && (
            <button
              onClick={() => goToCharacter(characters[currentIndex - 1].name)}
              className="shrink-0 p-1.5 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
          )}

          {/* Horizontal strip */}
          <div
            ref={stripRef}
            className="flex-1 flex items-center gap-1.5 overflow-x-auto py-1 scrollbar-none"
          >
            {characters.map((ch) => (
              <button
                key={ch.name}
                onClick={() => goToCharacter(ch.name)}
                className={clsx(
                  "shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-all",
                  ch.name === decodedName
                    ? "bg-[var(--accent)]/15 text-[var(--accent)] border border-[var(--accent)]/30"
                    : "text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] border border-transparent",
                )}
              >
                <User className="w-3 h-3" />
                {ch.name}
                {ch.has_soul && (
                  <Sparkles className="w-2.5 h-2.5 text-[var(--accent)]" />
                )}
              </button>
            ))}
          </div>

          {/* Next button */}
          {currentIndex >= 0 && currentIndex < characters.length - 1 && (
            <button
              onClick={() => goToCharacter(characters[currentIndex + 1].name)}
              className="shrink-0 p-1.5 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text)] hover:bg-[var(--surface)] transition-all"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          )}
        </div>
      )}

      {/* Back link (fallback if no character list) */}
      {characters.length <= 1 && (
        <button
          onClick={() => navigate(`/book/${sessionId}`)}
          className="inline-flex items-center gap-1.5 text-xs text-[var(--text-secondary)] hover:text-[var(--accent)] transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          返回总览
        </button>
      )}

      {/* Character header */}
      <div className="ink-card bg-[var(--surface)] border border-[var(--border)] rounded-xl p-6 animate-[fadeSlideIn_0.3s_ease-out_both]">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-3xl text-[var(--text)] mb-1">
              {character.name}
            </h1>
            {character.aliases.length > 0 && (
              <p className="text-xs text-[var(--text-secondary)] mb-3">
                又名: {character.aliases.join("、")}
              </p>
            )}
            <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
              {character.description}
            </p>
          </div>
          <div className="shrink-0 flex flex-col items-end gap-2">
            {character.has_soul ? (
              <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-[var(--accent)]/15 text-[var(--accent)]">
                <Sparkles className="w-3.5 h-3.5" />
                灵魂已丰富
              </span>
            ) : enriching ? (
              <span className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium rounded-full bg-amber-500/15 text-amber-400">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                丰富中...
              </span>
            ) : null}
            {character.personality_type && (
              <span className="px-2.5 py-1 text-xs font-mono font-medium rounded-full bg-[var(--surface-hover)] text-[var(--text)]">
                {character.personality_type}
              </span>
            )}
          </div>
        </div>
        {enrichError && (
          <p className="mt-3 text-xs text-red-400">
            灵魂丰富失败: {enrichError}
          </p>
        )}
      </div>

      {/* Soul profile + quotes row */}
      {character.has_soul && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <SoulProfileCard character={character} />
          <CharacterQuotes quotes={character.key_quotes ?? []} />
        </div>
      )}

      {/* Emotional arc timeline */}
      {character.emotional_stages && character.emotional_stages.length > 0 && (
        <EmotionalArcTimeline stages={character.emotional_stages} />
      )}

      {/* Character chat */}
      {character.has_soul && sessionId && (
        <CharacterChat sessionId={sessionId} characterName={decodedName} />
      )}
    </div>
  );
}
