import { useMemo, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import type { BookKnowledgeGraph } from "../api";

export function CharactersPage() {
  const navigate = useNavigate();

  useEffect(() => {
    document.documentElement.lang = "zh-CN";
  }, []);

  const graph: BookKnowledgeGraph | null = useMemo(() => {
    const raw = sessionStorage.getItem("knowledge_graph");
    return raw ? JSON.parse(raw) : null;
  }, []);

  const title = sessionStorage.getItem("book_title") ?? "未知书籍";

  if (!graph) {
    return (
      <div style={{ ...pageBase, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{ textAlign: "center" }}>
          <p style={{ fontFamily: FONT.body, color: "#8a7a62", fontSize: "1.05rem", marginBottom: "1.5rem" }}>
            尚未提取知识图谱
          </p>
          <button onClick={() => navigate("/")} style={btnPrimary}>
            返回上传
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={pageBase}>
      <div style={{ maxWidth: 1000, margin: "0 auto", padding: "2.5rem 1.5rem" }}>
        {/* Header */}
        <header style={{ marginBottom: "3rem" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
            <div>
              <h1
                style={{
                  fontFamily: FONT.display,
                  fontSize: "clamp(2.2rem, 6vw, 3.5rem)",
                  color: "#d4a574",
                  lineHeight: 1,
                  marginBottom: "0.6rem",
                }}
              >
                {title}
              </h1>
              <p style={{ fontFamily: FONT.body, color: "#6a5438", fontSize: "0.9rem", letterSpacing: "0.1em" }}>
                {graph.characters.length} 位人物 · {graph.chapter_summaries.length} 段落
              </p>
            </div>
            <div style={{ display: "flex", gap: "0.75rem" }}>
              <button onClick={() => navigate("/")} style={btnGhost}>
                首页
              </button>
              <button onClick={() => navigate("/chat")} style={btnPrimary}>
                对话
              </button>
            </div>
          </div>
          <div
            style={{
              marginTop: "1.5rem",
              height: 1,
              background: "linear-gradient(90deg, rgba(212,165,116,0.3), transparent 70%)",
            }}
          />
        </header>

        {/* Chapter summaries */}
        <section style={{ marginBottom: "3rem" }}>
          <h2 style={sectionTitle}>卷 览</h2>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.6rem" }}>
            {graph.chapter_summaries.map((ch) => (
              <div key={ch.chunk_index} style={cardStyle}>
                <div style={{ display: "flex", gap: "0.6rem", alignItems: "baseline", marginBottom: "0.4rem" }}>
                  <span
                    style={{
                      fontFamily: FONT.display,
                      color: "#d4a574",
                      fontSize: "1.3rem",
                      opacity: 0.6,
                      minWidth: "2rem",
                    }}
                  >
                    {String(ch.chunk_index + 1).padStart(2, "0")}
                  </span>
                  {ch.title && (
                    <span style={{ fontFamily: FONT.sub, fontWeight: 700, color: "#e0d8c8", fontSize: "0.95rem" }}>
                      {ch.title}
                    </span>
                  )}
                </div>
                {ch.summary && (
                  <p style={{ fontFamily: FONT.body, fontSize: "0.88rem", color: "#b0a890", lineHeight: 1.7, marginLeft: "2.6rem" }}>
                    {ch.summary}
                  </p>
                )}
                {ch.key_events.length > 0 && (
                  <p style={{ fontSize: "0.78rem", color: "#6a5a42", marginTop: "0.3rem", marginLeft: "2.6rem" }}>
                    {ch.key_events.join(" · ")}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>

        {/* Character cards */}
        <section>
          <h2 style={sectionTitle}>人 物</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "1rem" }}>
            {graph.characters.map((c, i) => (
              <div
                key={c.name}
                style={{
                  ...cardStyle,
                  padding: "1.5rem",
                  borderLeft: "2px solid rgba(212,165,116,0.2)",
                  position: "relative",
                }}
              >
                {/* Subtle index */}
                <span
                  style={{
                    position: "absolute",
                    top: "0.75rem",
                    right: "1rem",
                    fontFamily: "'Poiret One', sans-serif",
                    fontSize: "0.7rem",
                    color: "#4a3a28",
                    letterSpacing: "0.1em",
                  }}
                >
                  NO.{String(i + 1).padStart(2, "0")}
                </span>

                <h3
                  style={{
                    fontFamily: FONT.display,
                    fontSize: "1.6rem",
                    color: "#d4a574",
                    marginBottom: "0.5rem",
                    lineHeight: 1.2,
                  }}
                >
                  {c.name}
                </h3>

                {c.aliases.length > 0 && (
                  <p style={{ fontSize: "0.78rem", color: "#6a5438", marginBottom: "0.6rem", letterSpacing: "0.05em" }}>
                    {c.aliases.join(" / ")}
                  </p>
                )}

                {c.description && (
                  <p style={{ fontFamily: FONT.body, fontSize: "0.9rem", color: "#c0b8a0", lineHeight: 1.6, marginBottom: "0.5rem" }}>
                    {c.description}
                  </p>
                )}

                {c.voice_style && (
                  <p style={{ fontSize: "0.82rem", color: "#8a7a5a", fontStyle: "italic" }}>
                    「{c.voice_style}」
                  </p>
                )}

                {c.arc_summary && (
                  <p
                    style={{
                      fontSize: "0.82rem",
                      color: "#b8956a",
                      marginTop: "0.6rem",
                      paddingTop: "0.6rem",
                      borderTop: "1px solid rgba(212,165,116,0.08)",
                    }}
                  >
                    {c.arc_summary}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

/* ── Design tokens ───────────────────────────────────────────── */

const FONT = {
  display: "'Zhi Mang Xing', cursive",
  sub: "'ZCOOL XiaoWei', serif",
  body: "'Noto Serif SC', serif",
};

const pageBase: React.CSSProperties = {
  minHeight: "100vh",
  background: "linear-gradient(180deg, #0e0c08 0%, #14100a 100%)",
};

const sectionTitle: React.CSSProperties = {
  fontFamily: FONT.display,
  fontSize: "2rem",
  color: "#d4a574",
  letterSpacing: "0.3em",
  marginBottom: "1.2rem",
  opacity: 0.8,
};

const cardStyle: React.CSSProperties = {
  background: "rgba(26,21,14,0.6)",
  border: "1px solid rgba(212,165,116,0.08)",
  borderRadius: 6,
  padding: "1rem 1.2rem",
  transition: "border-color 0.3s ease",
};

const btnPrimary: React.CSSProperties = {
  fontFamily: FONT.sub,
  background: "rgba(212,165,116,0.15)",
  color: "#d4a574",
  border: "1px solid rgba(212,165,116,0.25)",
  borderRadius: 4,
  padding: "0.5rem 1.5rem",
  cursor: "pointer",
  fontSize: "0.9rem",
  letterSpacing: "0.1em",
  transition: "all 0.3s ease",
};

const btnGhost: React.CSSProperties = {
  fontFamily: FONT.sub,
  background: "transparent",
  color: "#6a5438",
  border: "1px solid rgba(212,165,116,0.1)",
  borderRadius: 4,
  padding: "0.5rem 1.25rem",
  cursor: "pointer",
  fontSize: "0.85rem",
  letterSpacing: "0.1em",
};
