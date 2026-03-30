"""BookScope — PNG share card generator.

Generates a styled 800×480 dark PNG card: book title, dominant emotion,
arc pattern, word count, and an emotion bar chart.

Public API:
    generate_share_card(book_title, arc_pattern, detected_lang,
                        total_words, n_chunks, emotion_scores) -> bytes
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# ── Emotion palette (matches _EMOTION_COLORS in app/ui_constants.py) ─────────
_EMOTION_COLORS: dict[str, str] = {
    "anger": "#ef4444",
    "anticipation": "#f97316",
    "disgust": "#84cc16",
    "fear": "#6b7280",
    "joy": "#eab308",
    "sadness": "#3b82f6",
    "surprise": "#06b6d4",
    "trust": "#22c55e",
}

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)

# ── Arc pattern display names ─────────────────────────────────────────────────
_ARC_SYMBOLS = {
    "Rags to Riches": "↗",
    "Riches to Rags":  "↘",
    "Man in a Hole":   "↘↗",
    "Icarus":          "↗↘",
    "Cinderella":      "↗↘↗",
    "Oedipus":         "↘↗↘",
    "Unknown":         "~",
}

# Card dimensions
_W, _H = 800, 480


def _hex_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    """Convert '#rrggbb' to (r, g, b) floats in [0, 1]."""
    h = hex_color.lstrip("#")
    return tuple(int(h[i: i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def generate_share_card(
    book_title: str,
    arc_pattern: str,
    detected_lang: str,
    total_words: int,
    n_chunks: int,
    emotion_scores: list,
) -> bytes:
    """Render an 800×480 dark PNG share card and return it as raw bytes.

    Falls back to an empty 1×1 transparent PNG if matplotlib is unavailable.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend — safe in Streamlit
        import matplotlib.patches as mpatches
        import matplotlib.pyplot as plt
    except ImportError:
        # Minimal 1×1 transparent PNG fallback
        return (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
            b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )

    # ── Average emotion scores ────────────────────────────────────────────────
    n = len(emotion_scores)
    if n > 0:
        avg = {
            e: sum(getattr(s, e) for s in emotion_scores) / n
            for e in _EMOTION_FIELDS
        }
    else:
        avg = {e: 0.0 for e in _EMOTION_FIELDS}

    # Top emotion
    top_emotion = max(avg, key=lambda e: avg[e])
    top_color = _EMOTION_COLORS.get(top_emotion, "#a78bfa")

    # Arc display
    arc_symbol = _ARC_SYMBOLS.get(arc_pattern, "")
    arc_display = f"{arc_pattern}  {arc_symbol}"

    # ── Figure setup ─────────────────────────────────────────────────────────
    dpi = 100
    fig = plt.figure(figsize=(_W / dpi, _H / dpi), dpi=dpi, facecolor="#0d1117")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, _W)
    ax.set_ylim(0, _H)
    ax.axis("off")
    ax.set_facecolor("#0d1117")

    # ── Background card rectangle ─────────────────────────────────────────────
    card = mpatches.FancyBboxPatch(
        (20, 20), _W - 40, _H - 40,
        boxstyle="round,pad=10",
        facecolor="#161b22", edgecolor="#30363d", linewidth=1.5,
    )
    ax.add_patch(card)

    # ── Top accent line (top-emotion color) ───────────────────────────────────
    accent_rgb = _hex_to_rgb01(top_color)
    accent_bar = mpatches.Rectangle((20, _H - 24), _W - 40, 4, color=accent_rgb)
    ax.add_patch(accent_bar)

    # ── "BookScope" branding (top-left) ──────────────────────────────────────
    ax.text(
        48, _H - 50, "BookScope",
        color="#6b7280", fontsize=11, fontweight="bold",
        va="top", ha="left",
    )

    # ── Book title ────────────────────────────────────────────────────────────
    title_display = book_title[:55] + ("…" if len(book_title) > 55 else "")
    ax.text(
        48, _H - 100, title_display,
        color="#e6edf3", fontsize=22, fontweight="bold",
        va="top", ha="left", wrap=False,
    )

    # ── Top emotion badge ─────────────────────────────────────────────────────
    badge_x, badge_y = 48, _H - 160
    badge_bg = mpatches.FancyBboxPatch(
        (badge_x - 4, badge_y - 22), 160, 32,
        boxstyle="round,pad=4",
        facecolor=(*accent_rgb, 0.2), edgecolor=(*accent_rgb, 0.6), linewidth=1,
    )
    ax.add_patch(badge_bg)
    ax.text(
        badge_x + 76, badge_y - 6,
        top_emotion.capitalize(),
        color=top_color, fontsize=12, fontweight="semibold",
        va="center", ha="center",
    )

    # ── Arc pattern ───────────────────────────────────────────────────────────
    arc_x = badge_x + 185
    arc_bg = mpatches.FancyBboxPatch(
        (arc_x - 4, badge_y - 22), 200, 32,
        boxstyle="round,pad=4",
        facecolor="#7c3aed22", edgecolor="#7c3aed88", linewidth=1,
    )
    ax.add_patch(arc_bg)
    ax.text(
        arc_x + 96, badge_y - 6, arc_display,
        color="#a78bfa", fontsize=12,
        va="center", ha="center",
    )

    # ── Stats row ─────────────────────────────────────────────────────────────
    stats_y = _H - 200
    lang_label = {"en": "English", "zh": "Chinese", "ja": "Japanese"}.get(
        detected_lang, detected_lang.upper()
    )
    stats_text = f"{total_words:,} words · {n_chunks} chunks · {lang_label}"
    ax.text(
        48, stats_y, stats_text,
        color="#6b7280", fontsize=10.5,
        va="top", ha="left",
    )

    # ── Emotion bar chart (bottom half) ──────────────────────────────────────
    chart_left = 48
    chart_right = _W - 48
    chart_bottom = 55
    chart_top = _H - 230
    chart_h = chart_top - chart_bottom

    # Axis label
    ax.text(
        chart_left, chart_top + 8, "Emotion profile",
        color="#4b5563", fontsize=9,
        va="bottom", ha="left",
    )

    bar_w = (chart_right - chart_left) / len(_EMOTION_FIELDS) - 6
    max_val = max(avg.values()) if any(avg.values()) else 1.0

    for i, emotion in enumerate(_EMOTION_FIELDS):
        val = avg[emotion]
        bar_h = max(2, (val / max(max_val, 0.001)) * chart_h)
        bx = chart_left + i * ((chart_right - chart_left) / len(_EMOTION_FIELDS))

        # Bar fill
        bar_color = _hex_to_rgb01(_EMOTION_COLORS[emotion])
        alpha = 0.85 if emotion == top_emotion else 0.45
        rect = mpatches.Rectangle(
            (bx, chart_bottom), bar_w, bar_h,
            color=(*bar_color, alpha),
        )
        ax.add_patch(rect)

        # Label below bar
        ax.text(
            bx + bar_w / 2, chart_bottom - 4,
            emotion[:3].capitalize(),
            color="#4b5563" if emotion != top_emotion else "#94a3b8",
            fontsize=8, va="top", ha="center",
        )

        # Value above bar (only for top emotion)
        if emotion == top_emotion and val > 0:
            ax.text(
                bx + bar_w / 2, chart_bottom + bar_h + 4,
                f"{val:.2f}",
                color=_EMOTION_COLORS[emotion],
                fontsize=8, va="bottom", ha="center",
            )

    # ── Version watermark ─────────────────────────────────────────────────────
    ax.text(
        _W - 48, 30, "bookscope.app",
        color="#374151", fontsize=8,
        va="bottom", ha="right",
    )

    # ── Render to bytes ───────────────────────────────────────────────────────
    import warnings
    buf = io.BytesIO()
    # Suppress CJK/emoji glyph-missing warnings — DejaVu Sans has no CJK coverage;
    # affected characters render as boxes, which is acceptable for title display.
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Glyph .*missing from font")
        fig.savefig(buf, format="png", dpi=dpi, bbox_inches="tight", facecolor="#0d1117")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
