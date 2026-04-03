import { useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { uploadFile, extractSSE } from "../api";

/* ── Font preloading — lock fonts regardless of system language ── */
const FONT_CSS = `
@import url('https://fonts.googleapis.com/css2?family=Zhi+Mang+Xing&family=Poiret+One&family=Noto+Serif+SC:wght@400;700&family=ZCOOL+XiaoWei&display=swap');

/* Force Chinese characters to always use our chosen fonts, never system fallback */
@font-face {
  font-family: 'ShiJuan-Display';
  src: local('Zhi Mang Xing');
  unicode-range: U+4E00-9FFF, U+3400-4DBF, U+F900-FAFF, U+2F800-2FA1F;
}
@font-face {
  font-family: 'ShiJuan-Body';
  src: local('Noto Serif SC');
  unicode-range: U+4E00-9FFF, U+3400-4DBF, U+3000-303F, U+FF00-FFEF;
}
`;

function injectFonts() {
  if (document.getElementById("shijuan-fonts")) return;

  // Preload critical fonts
  const preloads = [
    "https://fonts.gstatic.com/s/zhimangxing/v10/x3d-cl7KZQoQ5W0vBNhxgYGIuQ.woff2",
    "https://fonts.gstatic.com/s/poiretone/v16/UqyVK80NJXN4zfRgbdfbk5k.woff2",
  ];
  preloads.forEach((href) => {
    const link = document.createElement("link");
    link.rel = "preload";
    link.as = "font";
    link.type = "font/woff2";
    link.crossOrigin = "anonymous";
    link.href = href;
    document.head.appendChild(link);
  });

  // Inject stylesheet
  const style = document.createElement("style");
  style.id = "shijuan-fonts";
  style.textContent = FONT_CSS;
  document.head.appendChild(style);

  // Lock html lang to zh so browsers don't substitute CJK system fonts
  document.documentElement.lang = "zh-CN";
}

/* ── Ink wash mountain silhouette (SVG data URI) ─────────────── */
const MOUNTAIN_SVG = `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 320'%3E%3Cpath fill='%23100d08' fill-opacity='0.6' d='M0,288L48,272C96,256,192,224,288,213.3C384,203,480,213,576,229.3C672,245,768,267,864,261.3C960,256,1056,224,1152,208C1248,192,1344,192,1392,192L1440,192L1440,320L1392,320C1344,320,1248,320,1152,320C1056,320,960,320,864,320C768,320,672,320,576,320C480,320,384,320,288,320C192,320,96,320,48,320L0,320Z'/%3E%3Cpath fill='%230c0a06' fill-opacity='0.8' d='M0,256L60,261.3C120,267,240,277,360,272C480,267,600,245,720,240C840,235,960,245,1080,250.7C1200,256,1320,256,1380,256L1440,256L1440,320L1380,320C1320,320,1200,320,1080,320C960,320,840,320,720,320C600,320,480,320,360,320C240,320,120,320,60,320L0,320Z'/%3E%3C/svg%3E")`;

export function UploadPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<string>("");
  const [progress, setProgress] = useState<{ current: number; total: number } | null>(null);
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    injectFonts();
  }, []);

  const handleFile = useCallback(
    async (file: File) => {
      try {
        setStatus("上传中...");
        const res = await uploadFile(file);
        setStatus(`已上传《${res.title}》— ${res.total_chunks} 段落，开始提取...`);

        sessionStorage.setItem("session_id", res.session_id);
        sessionStorage.setItem("book_title", res.title);

        for await (const event of extractSSE(res.session_id)) {
          if (event.type === "progress") {
            setProgress({ current: event.current, total: event.total });
            setStatus(`提取中... ${event.current}/${event.total}`);
          } else if (event.type === "done") {
            sessionStorage.setItem("knowledge_graph", JSON.stringify(event.graph));
            setStatus("提取完成!");
            setTimeout(() => navigate("/characters"), 500);
          }
        }
      } catch (err) {
        setStatus(`错误: ${err instanceof Error ? err.message : String(err)}`);
      }
    },
    [navigate],
  );

  const onDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragging(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const onFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "#0e0c08",
        minHeight: "100vh",
        position: "relative",
        overflow: "hidden",
      }}
    >
      {/* Layer 1: Ink wash radial blurs — 墨渍晕染 */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background: [
            "radial-gradient(ellipse 80% 60% at 25% 20%, rgba(42,32,18,0.7) 0%, transparent 70%)",
            "radial-gradient(ellipse 60% 50% at 75% 70%, rgba(30,22,12,0.5) 0%, transparent 65%)",
            "radial-gradient(ellipse 40% 35% at 50% 45%, rgba(50,38,22,0.3) 0%, transparent 60%)",
          ].join(", "),
          pointerEvents: "none",
        }}
      />

      {/* Layer 2: Warm candle glow — 烛光暖晕 */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "radial-gradient(circle 400px at 50% 40%, rgba(212,165,116,0.04) 0%, transparent 100%)",
          pointerEvents: "none",
        }}
      />

      {/* Layer 3: Rice paper grain texture — 宣纸纹理 */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          opacity: 0.035,
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg viewBox='0 0 512 512' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='g'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.65' numOctaves='5' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23g)'/%3E%3C/svg%3E\")",
          backgroundSize: "256px 256px",
          pointerEvents: "none",
        }}
      />

      {/* Layer 4: Mountain silhouette — 远山剪影 */}
      <div
        style={{
          position: "absolute",
          bottom: 0,
          left: 0,
          right: 0,
          height: "35vh",
          backgroundImage: MOUNTAIN_SVG,
          backgroundSize: "cover",
          backgroundPosition: "bottom center",
          backgroundRepeat: "no-repeat",
          pointerEvents: "none",
        }}
      />

      {/* Layer 5: Top vignette */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          background:
            "linear-gradient(180deg, rgba(14,12,8,0.3) 0%, transparent 30%, transparent 75%, rgba(14,12,8,0.5) 100%)",
          pointerEvents: "none",
        }}
      />

      {/* Content */}
      <div style={{ textAlign: "center", maxWidth: 600, position: "relative", zIndex: 1, padding: "0 1.5rem" }}>
        {/* Decorative top line */}
        <div
          style={{
            width: 1,
            height: 48,
            margin: "0 auto 2rem",
            background: "linear-gradient(180deg, transparent, rgba(212,165,116,0.3), transparent)",
          }}
        />

        {/* ▍Chinese calligraphy — UNLEASHED */}
        <h1
          style={{
            fontFamily: "'Zhi Mang Xing', 'ShiJuan-Display', cursive",
            fontSize: "clamp(7rem, 24vw, 13rem)",
            color: "#d4a574",
            letterSpacing: "0.35em",
            lineHeight: 0.9,
            margin: 0,
            textShadow: [
              "0 0 80px rgba(212,165,116,0.15)",
              "0 2px 4px rgba(0,0,0,0.5)",
            ].join(", "),
            WebkitTextStroke: "0.5px rgba(212,165,116,0.8)",
          }}
        >
          拾卷
        </h1>

        {/* English subtitle */}
        <p
          style={{
            fontFamily: "'Poiret One', sans-serif",
            fontSize: "clamp(1.3rem, 3.5vw, 1.8rem)",
            letterSpacing: "0.8em",
            color: "#8a6a4a",
            margin: "1rem 0 0",
          }}
        >
          SHIJUAN
        </p>

        {/* Tagline */}
        <p
          style={{
            fontFamily: "'Noto Serif SC', 'ShiJuan-Body', serif",
            fontWeight: 400,
            fontSize: "clamp(0.95rem, 2.2vw, 1.15rem)",
            color: "#6a5438",
            letterSpacing: "0.22em",
            margin: "1.5rem 0 0",
          }}
        >
          拾遗补阙，卷中乾坤
        </p>

        {/* Decorative diamond cluster */}
        <div
          style={{
            margin: "2.5rem 0 3rem",
            display: "flex",
            justifyContent: "center",
            alignItems: "center",
            gap: "1rem",
          }}
        >
          <div style={{ width: 40, height: 1, background: "linear-gradient(90deg, transparent, rgba(212,165,116,0.25))" }} />
          <span style={{ color: "#d4a574", opacity: 0.35, fontSize: "0.7rem" }}>◇</span>
          <div style={{ width: 40, height: 1, background: "linear-gradient(90deg, rgba(212,165,116,0.25), transparent)" }} />
        </div>

        {/* Upload drop zone */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          onClick={() => document.getElementById("file-input")?.click()}
          style={{
            border: `1px solid ${dragging ? "rgba(212,165,116,0.5)" : "rgba(212,165,116,0.1)"}`,
            borderRadius: 8,
            padding: "2.5rem 2rem",
            background: dragging
              ? "rgba(212,165,116,0.06)"
              : "rgba(255,255,255,0.015)",
            cursor: "pointer",
            transition: "all 0.4s ease",
            backdropFilter: "blur(8px)",
          }}
        >
          <p
            style={{
              fontFamily: "'ZCOOL XiaoWei', 'ShiJuan-Body', serif",
              fontSize: "1.1rem",
              color: "#b8956a",
              marginBottom: "0.5rem",
            }}
          >
            拖放书籍文件到此处
          </p>
          <p
            style={{
              fontFamily: "'Poiret One', sans-serif",
              color: "#5a4a38",
              fontSize: "0.8rem",
              letterSpacing: "0.08em",
            }}
          >
            .txt / .epub / .pdf
          </p>
          <input
            id="file-input"
            type="file"
            accept=".txt,.epub,.pdf"
            onChange={onFileInput}
            style={{ display: "none" }}
          />
        </div>

        {/* Status */}
        {status && (
          <p
            style={{
              marginTop: "1.5rem",
              fontFamily: "'Noto Serif SC', 'ShiJuan-Body', serif",
              color: "#d4a574",
              fontSize: "0.9rem",
            }}
          >
            {status}
          </p>
        )}

        {/* Progress bar */}
        {progress && (
          <div
            style={{
              marginTop: "1rem",
              background: "rgba(212,165,116,0.08)",
              borderRadius: 2,
              height: 3,
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${(progress.current / progress.total) * 100}%`,
                height: "100%",
                background: "linear-gradient(90deg, #6a5438, #d4a574)",
                transition: "width 0.3s ease",
                boxShadow: "0 0 8px rgba(212,165,116,0.3)",
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
