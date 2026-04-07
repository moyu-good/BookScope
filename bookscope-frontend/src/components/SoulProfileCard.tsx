import { Brain, Heart, Target } from "lucide-react";
import type { CharacterProfile } from "../lib/types";

interface SoulProfileCardProps {
  character: CharacterProfile;
}

export default function SoulProfileCard({ character }: SoulProfileCardProps) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5 space-y-5">
      <div className="flex items-center gap-2">
        <Brain className="w-4 h-4 text-[var(--accent)]" />
        <h2 className="text-sm font-semibold uppercase tracking-wider text-[var(--text-secondary)]">
          灵魂档案
        </h2>
      </div>

      {/* Personality type */}
      {character.personality_type && (
        <div className="bg-[var(--bg)] rounded-lg p-4 border border-[var(--border)]">
          <p className="text-xs text-[var(--text-secondary)] mb-1">
            人格类型
          </p>
          <p className="text-lg font-semibold text-[var(--text)]">
            {character.personality_type}
          </p>
        </div>
      )}

      {/* Values */}
      {character.values && character.values.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <Heart className="w-3.5 h-3.5 text-rose-400" />
            <p className="text-xs font-medium text-[var(--text-secondary)]">
              核心价值观
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {character.values.map((v) => (
              <span
                key={v}
                className="px-2.5 py-1 text-xs rounded-full bg-rose-500/10 text-rose-300 border border-rose-500/20"
              >
                {v}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Motivations */}
      {character.motivations.length > 0 && (
        <div>
          <div className="flex items-center gap-1.5 mb-2">
            <Target className="w-3.5 h-3.5 text-amber-400" />
            <p className="text-xs font-medium text-[var(--text-secondary)]">
              内心动机
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {character.motivations.map((m) => (
              <span
                key={m}
                className="px-2.5 py-1 text-xs rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20"
              >
                {m}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Arc summary */}
      {character.arc_summary && (
        <div className="border-t border-[var(--border)] pt-4">
          <p className="text-xs text-[var(--text-secondary)] mb-1">
            人物弧线
          </p>
          <p className="text-sm text-[var(--text)] leading-relaxed italic">
            {character.arc_summary}
          </p>
        </div>
      )}
    </div>
  );
}
