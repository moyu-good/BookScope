import { useState, useCallback, useRef, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { chatSSE } from "../api";

interface Message {
  role: "user" | "assistant";
  content: string;
}

const FONT = {
  display: "'Zhi Mang Xing', cursive",
  sub: "'ZCOOL XiaoWei', serif",
  body: "'Noto Serif SC', serif",
};

export function ChatPage() {
  const navigate = useNavigate();
  const sessionId = sessionStorage.getItem("session_id");
  const title = sessionStorage.getItem("book_title") ?? "未知书籍";

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    document.documentElement.lang = "zh-CN";
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = useCallback(async () => {
    if (!input.trim() || !sessionId || loading) return;
    const userMsg = input.trim();
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: userMsg }]);
    setLoading(true);

    try {
      let assistantContent = "";
      for await (const event of chatSSE(sessionId, userMsg)) {
        if (event.type === "message") {
          assistantContent += event.content;
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant") {
              last.content = assistantContent;
            } else {
              updated.push({ role: "assistant", content: assistantContent });
            }
            return updated;
          });
        }
      }
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `错误: ${err instanceof Error ? err.message : String(err)}` },
      ]);
    } finally {
      setLoading(false);
    }
  }, [input, sessionId, loading]);

  if (!sessionId) {
    return (
      <div
        style={{
          minHeight: "100vh",
          background: "#0e0c08",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
        }}
      >
        <div style={{ textAlign: "center" }}>
          <p style={{ fontFamily: FONT.body, color: "#8a7a62", marginBottom: "1.5rem" }}>
            请先上传书籍
          </p>
          <button onClick={() => navigate("/")} style={btnPrimary}>
            返回上传
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", background: "#0e0c08" }}>
      {/* Header */}
      <header
        style={{
          padding: "0.8rem 1.5rem",
          borderBottom: "1px solid rgba(212,165,116,0.08)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          background: "rgba(14,12,8,0.95)",
          backdropFilter: "blur(12px)",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.8rem" }}>
          <h2
            style={{
              fontFamily: FONT.display,
              fontSize: "1.8rem",
              color: "#d4a574",
              lineHeight: 1,
            }}
          >
            {title}
          </h2>
          <span style={{ fontFamily: FONT.sub, fontSize: "0.8rem", color: "#5a4a38", letterSpacing: "0.1em" }}>
            对话
          </span>
        </div>
        <div style={{ display: "flex", gap: "0.6rem" }}>
          <button onClick={() => navigate("/characters")} style={btnGhost}>
            人物档案
          </button>
          <button onClick={() => navigate("/")} style={btnGhost}>
            首页
          </button>
        </div>
      </header>

      {/* Messages area */}
      <div
        style={{
          flex: 1,
          overflow: "auto",
          padding: "1.5rem",
          background: "linear-gradient(180deg, #0e0c08, #12100a)",
        }}
      >
        {messages.length === 0 && (
          <div style={{ textAlign: "center", marginTop: "15vh" }}>
            <p
              style={{
                fontFamily: FONT.display,
                fontSize: "2.5rem",
                color: "rgba(212,165,116,0.12)",
                marginBottom: "1rem",
              }}
            >
              拾卷
            </p>
            <p style={{ fontFamily: FONT.body, color: "#5a4a38", fontSize: "0.9rem" }}>
              问任何关于这本书的问题...
            </p>
          </div>
        )}

        <div style={{ maxWidth: 720, margin: "0 auto" }}>
          {messages.map((msg, i) => (
            <div
              key={i}
              style={{
                marginBottom: "1.25rem",
                display: "flex",
                justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
              }}
            >
              <div
                style={{
                  maxWidth: "75%",
                  padding: msg.role === "user" ? "0.7rem 1.1rem" : "1rem 1.3rem",
                  borderRadius: msg.role === "user" ? "12px 12px 2px 12px" : "12px 12px 12px 2px",
                  background:
                    msg.role === "user"
                      ? "rgba(212,165,116,0.12)"
                      : "rgba(26,21,14,0.7)",
                  border:
                    msg.role === "user"
                      ? "1px solid rgba(212,165,116,0.2)"
                      : "1px solid rgba(212,165,116,0.06)",
                  fontFamily: FONT.body,
                  fontSize: "0.9rem",
                  color: msg.role === "user" ? "#d4a574" : "#c0b8a0",
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.7,
                }}
              >
                {msg.content}
              </div>
            </div>
          ))}

          {loading && (
            <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: "1rem" }}>
              <div
                style={{
                  padding: "0.8rem 1.2rem",
                  borderRadius: "12px 12px 12px 2px",
                  background: "rgba(26,21,14,0.7)",
                  border: "1px solid rgba(212,165,116,0.06)",
                }}
              >
                <span style={{ color: "#6a5438", fontSize: "0.85rem", fontFamily: FONT.sub }}>
                  思索中...
                </span>
              </div>
            </div>
          )}
        </div>

        <div ref={bottomRef} />
      </div>

      {/* Input area */}
      <div
        style={{
          padding: "0.8rem 1.5rem",
          borderTop: "1px solid rgba(212,165,116,0.08)",
          display: "flex",
          gap: "0.75rem",
          background: "rgba(14,12,8,0.95)",
          backdropFilter: "blur(12px)",
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          placeholder="输入问题..."
          style={{
            flex: 1,
            fontFamily: FONT.body,
            background: "rgba(26,21,14,0.6)",
            border: "1px solid rgba(212,165,116,0.1)",
            borderRadius: 6,
            padding: "0.65rem 1rem",
            color: "#e0d8c8",
            fontSize: "0.9rem",
            outline: "none",
            transition: "border-color 0.3s",
          }}
          onFocus={(e) => (e.currentTarget.style.borderColor = "rgba(212,165,116,0.3)")}
          onBlur={(e) => (e.currentTarget.style.borderColor = "rgba(212,165,116,0.1)")}
        />
        <button onClick={send} disabled={loading} style={btnPrimary}>
          {loading ? "..." : "发送"}
        </button>
      </div>
    </div>
  );
}

const btnPrimary: React.CSSProperties = {
  fontFamily: "'ZCOOL XiaoWei', serif",
  background: "rgba(212,165,116,0.15)",
  color: "#d4a574",
  border: "1px solid rgba(212,165,116,0.25)",
  borderRadius: 4,
  padding: "0.5rem 1.5rem",
  cursor: "pointer",
  fontSize: "0.9rem",
  letterSpacing: "0.1em",
};

const btnGhost: React.CSSProperties = {
  fontFamily: "'ZCOOL XiaoWei', serif",
  background: "transparent",
  color: "#6a5438",
  border: "1px solid rgba(212,165,116,0.08)",
  borderRadius: 4,
  padding: "0.45rem 1rem",
  cursor: "pointer",
  fontSize: "0.8rem",
};
