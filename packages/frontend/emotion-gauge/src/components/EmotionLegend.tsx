import {
  EMOTION_DIMENSIONS,
  EMOTION_COLORS,
  type EmotionData,
} from "../types/emotion";

interface Props {
  data: EmotionData;
}

export default function EmotionLegend({ data }: Props) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(80px, 1fr))",
        gap: "6px 10px",
        marginTop: 16,
        padding: "12px 16px",
        background: "rgba(255,255,255,0.04)",
        borderRadius: 12,
      }}
    >
      {EMOTION_DIMENSIONS.map((name) => {
        const val = data.dimensions[name] ?? 0;
        const isPrimary = name === data.primary_emotion;
        return (
          <div
            key={name}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              opacity: isPrimary ? 1 : 0.55,
              fontWeight: isPrimary ? 600 : 400,
            }}
          >
            <span
              style={{
                display: "inline-block",
                width: 10,
                height: 10,
                borderRadius: "50%",
                backgroundColor: EMOTION_COLORS[name],
                flexShrink: 0,
              }}
            />
            <span style={{ fontSize: 13 }}>{name}</span>
            <span style={{ fontSize: 11, color: "#888", marginLeft: "auto" }}>
              {(val * 100).toFixed(0)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}
