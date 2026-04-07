import { useNavigate } from "react-router-dom";
import { Users, Sparkles } from "lucide-react";
import type { CharacterBrief } from "../lib/types";

interface CharacterGalleryProps {
  characters: CharacterBrief[];
  sessionId?: string;
  readOnly?: boolean;
}

export default function CharacterGallery({
  characters,
  sessionId,
  readOnly = false,
}: CharacterGalleryProps) {
  const navigate = useNavigate();

  const handleClick = (name: string) => {
    if (readOnly || !sessionId) return;
    navigate(`/book/${sessionId}/character/${encodeURIComponent(name)}`);
  };

  return (
    <div className="ink-card bg-[var(--surface)] border border-[var(--border)] rounded-xl p-5">
      <div className="flex items-center gap-2 mb-4">
        <Users className="w-4 h-4 text-[var(--accent)]" />
        <h2 className="text-xl text-[var(--accent)]">
          人物群像
        </h2>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {characters.map((ch) => {
          const isClickable = !readOnly && !!sessionId;
          const Tag = isClickable ? "button" : "div";

          return (
            <Tag
              key={ch.name}
              onClick={isClickable ? () => handleClick(ch.name) : undefined}
              className={`text-left bg-[var(--bg)] border border-[var(--border)] rounded-lg p-4 transition-all duration-200 group ${
                isClickable
                  ? "hover:border-[var(--accent)]/40 hover:bg-[var(--surface-hover)] cursor-pointer"
                  : ""
              }`}
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3
                  className={`text-sm font-medium text-[var(--text)] transition-colors duration-200 ${
                    isClickable ? "group-hover:text-[var(--accent)]" : ""
                  }`}
                >
                  {ch.name}
                </h3>
                {ch.has_soul && (
                  <span
                    className="shrink-0 flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-medium rounded-full bg-[var(--accent)]/10 text-[var(--accent)]"
                    title="灵魂档案已生成"
                  >
                    <Sparkles className="w-3 h-3" />
                    灵魂
                  </span>
                )}
              </div>

              <p className="text-xs text-[var(--text-secondary)] leading-relaxed line-clamp-2 mb-2">
                {ch.description}
              </p>

              {ch.arc_summary && (
                <p className="text-[10px] text-[var(--text-secondary)] italic line-clamp-1">
                  弧线: {ch.arc_summary}
                </p>
              )}
            </Tag>
          );
        })}
      </div>
    </div>
  );
}
