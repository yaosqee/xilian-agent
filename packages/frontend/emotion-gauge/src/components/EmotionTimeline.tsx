import { type EmotionData, EMOTION_COLORS } from "../types/emotion";

interface Props {
  history: EmotionData[];
}

export default function EmotionTimeline({ history }: Props) {
  if (history.length === 0) return null;

  return (
    <div style={{ marginTop: 20 }}>
      <h4 style={{ fontSize: 14, color: "#999", marginBottom: 8 }}>
        情绪时间线
      </h4>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {history.map((item, i) => (
          <div
            key={i}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              padding: "4px 10px",
              background: "rgba(255,255,255,0.06)",
              borderRadius: 8,
              fontSize: 12,
            }}
            title={new Date(item.timestamp).toLocaleTimeString("zh-CN")}
          >
            <span
              style={{
                width: 8,
                height: 8,
                borderRadius: "50%",
                backgroundColor: EMOTION_COLORS[item.primary_emotion],
                display: "inline-block",
              }}
            />
            {item.primary_emotion}{" "}
            {(item.primary_intensity * 100).toFixed(0)}%
          </div>
        ))}
      </div>
    </div>
  );
}
