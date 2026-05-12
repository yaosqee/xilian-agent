import { useState } from "react";
import { useEmotionData } from "./hooks/useEmotionData";
import EmotionGauge from "./components/EmotionGauge";
import EmotionLegend from "./components/EmotionLegend";
import EmotionTimeline from "./components/EmotionTimeline";
import type { EmotionData } from "./types/emotion";

const MAX_HISTORY = 12;

export default function App() {
  const { data, paused, setPaused, refresh } = useEmotionData(4000);
  const [history, setHistory] = useState<EmotionData[]>([]);

  const handleRefresh = () => {
    setHistory((prev) => [data, ...prev].slice(0, MAX_HISTORY));
    refresh();
  };

  return (
    <div>
      <h1
        style={{
          textAlign: "center",
          fontSize: 24,
          fontWeight: 600,
          marginBottom: 4,
          color: "#f0e6d3",
        }}
      >
        昔涟 · 心之涟漪
      </h1>
      <p
        style={{
          textAlign: "center",
          fontSize: 14,
          color: "#777",
          marginBottom: 20,
        }}
      >
        EmotionGauge 原型 · 11 维情绪雷达图
      </p>

      <EmotionGauge data={data} />

      <div
        style={{
          textAlign: "center",
          marginTop: 12,
          color: "#aaa",
          fontSize: 14,
        }}
      >
        主情绪：<strong style={{ color: "#f0e6d3" }}>{data.primary_emotion}</strong>
        {" · "}
        可能原因：{data.possible_cause}
        {" · "}
        需求：{data.need}
      </div>

      <div style={{ display: "flex", justifyContent: "center", gap: 12, marginTop: 16 }}>
        <button onClick={handleRefresh} style={btnStyle}>
          🔄 随机刷新
        </button>
        <button onClick={() => setPaused(!paused)} style={btnStyle}>
          {paused ? "▶ 继续" : "⏸ 暂停"}
        </button>
      </div>

      <EmotionLegend data={data} />
      <EmotionTimeline history={history} />
    </div>
  );
}

const btnStyle: React.CSSProperties = {
  padding: "8px 20px",
  border: "1px solid rgba(255,255,255,0.2)",
  borderRadius: 8,
  background: "rgba(255,255,255,0.08)",
  color: "#ddd",
  fontSize: 14,
  cursor: "pointer",
};
