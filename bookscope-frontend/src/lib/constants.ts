export const EMOTION_COLORS: Record<string, string> = {
  joy: "var(--bs-joy)",
  sadness: "var(--bs-sadness)",
  anger: "var(--bs-anger)",
  fear: "var(--bs-fear)",
  trust: "var(--bs-trust)",
  anticipation: "var(--bs-anticipation)",
  surprise: "var(--bs-surprise)",
  disgust: "var(--bs-disgust)",
};

export const EMOTION_HEX: Record<string, string> = {
  joy: "#f59e0b",
  sadness: "#3b82f6",
  anger: "#ef4444",
  fear: "#8b5cf6",
  trust: "#10b981",
  anticipation: "#f97316",
  surprise: "#ec4899",
  disgust: "#84cc16",
};

export const EMOTION_LABELS: Record<string, string> = {
  joy: "Joy",
  sadness: "Sadness",
  anger: "Anger",
  fear: "Fear",
  trust: "Trust",
  anticipation: "Anticipation",
  surprise: "Surprise",
  disgust: "Disgust",
};

export const EMOTION_FIELDS = [
  "joy",
  "sadness",
  "anger",
  "fear",
  "trust",
  "anticipation",
  "surprise",
  "disgust",
] as const;
