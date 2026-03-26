"""BookScope visual theme — centralized colors and font settings."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BookScopeTheme:
    """Immutable theme configuration used by all renderers."""

    # Plutchik 8-emotion color palette
    emotion_colors: dict[str, str] = field(
        default_factory=lambda: {
            "anger": "#e63946",
            "anticipation": "#f4a261",
            "disgust": "#8ecae6",
            "fear": "#6a0572",
            "joy": "#ffb703",
            "sadness": "#457b9d",
            "surprise": "#06d6a0",
            "trust": "#2dc653",
        }
    )

    background_color: str = "#0f1117"
    paper_color: str = "#1a1d27"
    font_color: str = "#e0e0e0"
    grid_color: str = "#2a2d3a"
    font_family: str = "Inter, sans-serif"
    font_size: int = 13


# Module-level default instance
DEFAULT_THEME = BookScopeTheme()
