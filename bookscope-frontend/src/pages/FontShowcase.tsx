/**
 * Brand name + font showcase — 6 naming × visual design options.
 * Chinese calligraphy title on top, English subtitle below.
 * Navigate to /fonts to preview.
 */

import { useEffect } from "react";

/* ── Google Fonts ─────────────────────────────────────────────────── */
const GOOGLE_FONTS = [
  // Chinese calligraphy / display
  "Ma+Shan+Zheng",                              // 行书
  "Liu+Jian+Mao+Cao",                           // 草书
  "Zhi+Mang+Xing",                              // 草书
  "Long+Cang",                                   // 行书
  "ZCOOL+XiaoWei",                               // 文艺宋体
  "Noto+Serif+SC:wght@400;700;900",             // 宋体
  // English display
  "Cormorant+Garamond:wght@300;400;600;700",
  "Bodoni+Moda:ital,wght@0,400;0,700;1,400",
  "Cinzel:wght@400;700;900",
  "Playfair+Display:wght@400;700;900",
  "Cormorant:wght@300;400;600;700",
  "Poiret+One",
  // English body
  "Jost:wght@300;400;500",
  "Josefin+Sans:wght@300;400",
];

function injectFonts() {
  if (document.getElementById("brand-fonts")) return;
  const link = document.createElement("link");
  link.id = "brand-fonts";
  link.rel = "stylesheet";
  link.href = `https://fonts.googleapis.com/css2?${GOOGLE_FONTS.map((f) => `family=${f}`).join("&")}&display=swap`;
  document.head.appendChild(link);
}

/* ── Scheme definitions ──────────────────────────────────────────── */
interface Scheme {
  id: string;
  zhName: string;
  enName: string;
  tagline: string;
  description: string;
  bg: string;
  zhStyle: React.CSSProperties;
  enStyle: React.CSSProperties;
  taglineStyle: React.CSSProperties;
  decorBefore?: React.ReactNode;
  decorAfter?: React.ReactNode;
}

const schemes: Scheme[] = [
  /* ── A: 墨知 ─────────────────────────────────────────────────── */
  {
    id: "A",
    zhName: "墨 知",
    enName: "MÒZHI",
    tagline: "以墨为镜，以文知心",
    description:
      "Ma Shan Zheng 行书 + Cinzel 罗马碑文体。暗金配色，" +
      "墨=文学载体，知=深度理解。古典庄重。",
    bg: "radial-gradient(ellipse at 50% 30%, #1a1710 0%, #0c0a08 100%)",
    zhStyle: {
      fontFamily: "'Ma Shan Zheng', cursive",
      fontSize: "5.5rem",
      color: "#d4af37",
      letterSpacing: "0.25em",
      lineHeight: 1.1,
      textShadow: "0 0 60px rgba(212,175,55,0.15)",
    },
    enStyle: {
      fontFamily: "'Cinzel', serif",
      fontWeight: 400,
      fontSize: "1.1rem",
      letterSpacing: "0.5em",
      color: "#8a7a5a",
      marginTop: "1rem",
    },
    taglineStyle: {
      fontFamily: "'ZCOOL XiaoWei', serif",
      fontSize: "0.95rem",
      color: "#6b5c3e",
      letterSpacing: "0.2em",
      marginTop: "1.2rem",
    },
    decorBefore: (
      <div style={{
        width: 80, height: 1, margin: "0 auto 1.5rem",
        background: "linear-gradient(90deg, transparent, #d4af37, transparent)",
      }} />
    ),
    decorAfter: (
      <div style={{
        width: 80, height: 1, margin: "1.5rem auto 0",
        background: "linear-gradient(90deg, transparent, #d4af37, transparent)",
      }} />
    ),
  },

  /* ── B: 解语 ─────────────────────────────────────────────────── */
  {
    id: "B",
    zhName: "解 语",
    enName: "JIĚYǓ",
    tagline: "一花解语，一书解心",
    description:
      "Liu Jian Mao Cao 草书 + Cormorant Garamond 斜体。" +
      "玫瑰雾色，源自《解语花》——能读懂人心的花。飘逸浪漫。",
    bg: "radial-gradient(ellipse at 40% 40%, #1a1218 0%, #0d0a0e 100%)",
    zhStyle: {
      fontFamily: "'Liu Jian Mao Cao', cursive",
      fontSize: "6rem",
      color: "#e8b4b8",
      letterSpacing: "0.2em",
      lineHeight: 1.05,
      textShadow: "0 0 50px rgba(232,180,184,0.12)",
    },
    enStyle: {
      fontFamily: "'Cormorant Garamond', serif",
      fontWeight: 300,
      fontStyle: "italic",
      fontSize: "1.15rem",
      letterSpacing: "0.45em",
      color: "#9a7a7e",
      marginTop: "0.9rem",
    },
    taglineStyle: {
      fontFamily: "'Noto Serif SC', serif",
      fontSize: "0.9rem",
      color: "#7a5a5e",
      letterSpacing: "0.15em",
      marginTop: "1.3rem",
    },
    decorBefore: (
      <div style={{ margin: "0 auto 1.2rem", color: "#e8b4b8", opacity: 0.35, fontSize: "1.5rem" }}>
        ✦
      </div>
    ),
  },

  /* ── C: 灵犀 ─────────────────────────────────────────────────── */
  {
    id: "C",
    zhName: "灵 犀",
    enName: "LÍNGXĪ",
    tagline: "心有灵犀，书中自现",
    description:
      "Zhi Mang Xing 狂草 + Bodoni Moda 高对比衬线。" +
      "青白配色，源自《心有灵犀一点通》——人与书的深层共鸣。气韵生动。",
    bg: "linear-gradient(165deg, #080c12 0%, #0a1018 50%, #060a10 100%)",
    zhStyle: {
      fontFamily: "'Zhi Mang Xing', cursive",
      fontSize: "6.5rem",
      color: "#c8dce8",
      letterSpacing: "0.15em",
      lineHeight: 1.0,
      textShadow: "0 0 80px rgba(160,200,230,0.1)",
    },
    enStyle: {
      fontFamily: "'Bodoni Moda', serif",
      fontWeight: 400,
      fontStyle: "italic",
      fontSize: "1.05rem",
      letterSpacing: "0.55em",
      color: "#5a7a8a",
      marginTop: "1rem",
    },
    taglineStyle: {
      fontFamily: "'ZCOOL XiaoWei', serif",
      fontSize: "0.9rem",
      color: "#4a6a78",
      letterSpacing: "0.18em",
      marginTop: "1.3rem",
    },
    decorAfter: (
      <div style={{
        width: 120, height: 1, margin: "1.5rem auto 0",
        background: "linear-gradient(90deg, transparent, #5a8aa0, transparent)",
        boxShadow: "0 0 12px rgba(90,138,160,0.3)",
      }} />
    ),
  },

  /* ── D: 观止 ─────────────────────────────────────────────────── */
  {
    id: "D",
    zhName: "观 止",
    enName: "GUĀNZHǏ",
    tagline: "阅尽千卷，叹为观止",
    description:
      "Long Cang 行楷 + Playfair Display 900。纯白+朱红，" +
      "源自《叹为观止》——阅读的终极体验。大气磅礴。",
    bg: "#0a0a0a",
    zhStyle: {
      fontFamily: "'Long Cang', cursive",
      fontSize: "6rem",
      color: "#f0ece4",
      letterSpacing: "0.3em",
      lineHeight: 1.05,
    },
    enStyle: {
      fontFamily: "'Playfair Display', serif",
      fontWeight: 900,
      fontSize: "0.95rem",
      letterSpacing: "0.6em",
      color: "#c23b22",
      marginTop: "1rem",
      textTransform: "uppercase" as const,
    },
    taglineStyle: {
      fontFamily: "'Noto Serif SC', serif",
      fontWeight: 400,
      fontSize: "0.9rem",
      color: "#5a5550",
      letterSpacing: "0.12em",
      marginTop: "1.4rem",
    },
    decorBefore: (
      <div style={{
        width: 3, height: 40, margin: "0 auto 1.2rem",
        background: "linear-gradient(180deg, transparent, #c23b22, transparent)",
      }} />
    ),
    decorAfter: (
      <div style={{
        width: 3, height: 40, margin: "1.2rem auto 0",
        background: "linear-gradient(180deg, transparent, #c23b22, transparent)",
      }} />
    ),
  },

  /* ── E: 阅微 ─────────────────────────────────────────────────── */
  {
    id: "E",
    zhName: "阅 微",
    enName: "YUÈWĒI",
    tagline: "微言大义，字里行间",
    description:
      "Ma Shan Zheng 行书 + Cormorant 细衬线。翡翠绿+墨色，" +
      "源自纪晓岚《阅微草堂笔记》——洞察文字间的幽微之处。文人雅趣。",
    bg: "radial-gradient(ellipse at 60% 35%, #0f1a14 0%, #080e0a 100%)",
    zhStyle: {
      fontFamily: "'Ma Shan Zheng', cursive",
      fontSize: "5.5rem",
      color: "#7ab89a",
      letterSpacing: "0.25em",
      lineHeight: 1.1,
      textShadow: "0 0 50px rgba(122,184,154,0.1)",
    },
    enStyle: {
      fontFamily: "'Cormorant', serif",
      fontWeight: 300,
      fontSize: "1.1rem",
      letterSpacing: "0.5em",
      color: "#4a7a62",
      marginTop: "1rem",
    },
    taglineStyle: {
      fontFamily: "'ZCOOL XiaoWei', serif",
      fontSize: "0.9rem",
      color: "#3a5a48",
      letterSpacing: "0.2em",
      marginTop: "1.3rem",
    },
    decorBefore: (
      <div style={{ display: "flex", justifyContent: "center", gap: 8, marginBottom: "1.2rem" }}>
        {[...Array(3)].map((_, i) => (
          <div key={i} style={{
            width: 4, height: 4, borderRadius: "50%",
            background: "#7ab89a", opacity: 0.3 + i * 0.2,
          }} />
        ))}
      </div>
    ),
  },

  /* ── F: 拾卷 ─────────────────────────────────────────────────── */
  {
    id: "F",
    zhName: "拾 卷",
    enName: "SHÍJUÀN",
    tagline: "拾遗补阙，卷中乾坤",
    description:
      "Zhi Mang Xing 狂草 + Poiret One Art Deco 细线体。" +
      "琥珀暖光，拾=拾取精华，卷=书卷。Art Deco 与东方书法碰撞。",
    bg: "linear-gradient(155deg, #14100a 0%, #1a150e 50%, #0e0c08 100%)",
    zhStyle: {
      fontFamily: "'Zhi Mang Xing', cursive",
      fontSize: "6rem",
      color: "#d4a574",
      letterSpacing: "0.2em",
      lineHeight: 1.05,
      textShadow: "0 0 40px rgba(212,165,116,0.12)",
    },
    enStyle: {
      fontFamily: "'Poiret One', sans-serif",
      fontSize: "1.2rem",
      letterSpacing: "0.6em",
      color: "#8a6a4a",
      marginTop: "1rem",
    },
    taglineStyle: {
      fontFamily: "'Noto Serif SC', serif",
      fontWeight: 400,
      fontSize: "0.85rem",
      color: "#6a5438",
      letterSpacing: "0.18em",
      marginTop: "1.4rem",
    },
    decorBefore: (
      <div style={{ margin: "0 auto 1rem", fontSize: "1.2rem", color: "#d4a574", opacity: 0.3 }}>
        ◇
      </div>
    ),
    decorAfter: (
      <div style={{ margin: "1rem auto 0", fontSize: "1.2rem", color: "#d4a574", opacity: 0.3 }}>
        ◇
      </div>
    ),
  },
];

/* ── Component ───────────────────────────────────────────────────── */
export function FontShowcase() {
  useEffect(() => {
    injectFonts();
  }, []);

  return (
    <div style={{ padding: "2.5rem 1.5rem", maxWidth: 900, margin: "0 auto" }}>
      <h1 style={{ fontSize: "1.1rem", color: "#888", fontWeight: 400, marginBottom: "0.3rem" }}>
        BookScope v3 — 品牌命名 × 视觉方案
      </h1>
      <p style={{ color: "#555", fontSize: "0.8rem", marginBottom: "3rem" }}>
        中文书法在上，英文在下。选择你喜欢的（A-F），或混搭组合。
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: "2.5rem" }}>
        {schemes.map((s) => (
          <div key={s.id}>
            {/* Label bar */}
            <div style={{
              display: "flex", justifyContent: "space-between", alignItems: "baseline",
              marginBottom: "0.6rem", gap: "1rem",
            }}>
              <span style={{ fontWeight: 700, fontSize: "0.9rem", color: "#ccc", whiteSpace: "nowrap" }}>
                {s.id} — {s.zhName.replace(/ /g, "")} / {s.enName}
              </span>
              <span style={{
                fontSize: "0.72rem", color: "#666", textAlign: "right", lineHeight: 1.4,
              }}>
                {s.description}
              </span>
            </div>

            {/* Preview card */}
            <div style={{
              background: s.bg,
              borderRadius: 14,
              padding: "4rem 2rem",
              textAlign: "center",
              border: "1px solid rgba(255,255,255,0.06)",
              overflow: "hidden",
            }}>
              {s.decorBefore}
              <h2 style={{ margin: 0, ...s.zhStyle }}>{s.zhName}</h2>
              <p style={{ margin: 0, ...s.enStyle }}>{s.enName}</p>
              <p style={{ margin: 0, ...s.taglineStyle }}>{s.tagline}</p>
              {s.decorAfter}
            </div>
          </div>
        ))}
      </div>

      <p style={{
        marginTop: "3rem", color: "#666", fontSize: "0.85rem", textAlign: "center",
        lineHeight: 1.8,
      }}>
        告诉我你喜欢哪个（A-F），或者混搭：比如「D 的名字 + A 的配色」
      </p>
    </div>
  );
}
