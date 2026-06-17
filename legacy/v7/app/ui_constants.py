"""BookScope — shared UI constants (emotion colors, icons, fields)."""

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

_EMOTION_ICONS: dict[str, str] = {
    "anger": "😠", "anticipation": "🤩", "disgust": "🤢",
    "fear": "😨", "joy": "😊", "sadness": "😢",
    "surprise": "😲", "trust": "🤝",
}

_EMOTION_FIELDS = (
    "anger", "anticipation", "disgust", "fear",
    "joy", "sadness", "surprise", "trust",
)
