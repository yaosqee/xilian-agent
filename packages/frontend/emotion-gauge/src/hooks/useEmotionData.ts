import { useState, useEffect, useCallback } from "react";
import type { EmotionData } from "../types/emotion";
import { generateMockData } from "../utils/mockData";

/**
 * 情绪数据 Hook。
 * 阶段 2：定时生成模拟数据。
 * 阶段 3：改为 fetch GET /api/emotion。
 */
export function useEmotionData(refreshMs = 4000) {
  const [data, setData] = useState<EmotionData>(generateMockData);
  const [paused, setPaused] = useState(false);

  const refresh = useCallback(() => {
    setData(generateMockData());
  }, []);

  useEffect(() => {
    if (paused) return;
    const timer = setInterval(refresh, refreshMs);
    return () => clearInterval(timer);
  }, [refreshMs, paused, refresh]);

  return { data, paused, setPaused, refresh };
}
