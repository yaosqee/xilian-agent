import { useEffect, useCallback } from 'react';
import { useEmotionStore } from '../stores/emotionStore';
import { fetchEmotion, fetchEmotionHistory } from '../services/api';

/**
 * PAD 引擎维度名 → 前端显示名映射
 * 将后端 PAD 的 11 个 Mehrabian 标准情绪名映射到前端 EMOTION_DIMENSIONS
 */
const PAD_TO_DISPLAY: Record<string, string> = {
  快乐: '喜悦',
  悲伤: '悲伤',
  愤怒: '愤怒',
  恐惧: '恐惧',
  惊讶: '好奇',
  厌恶: '疲惫',
  信任: '感激',
  期待: '期待',
  焦虑: '焦虑',
  平静: '平静',
  兴奋: '喜悦',
};

/** 将 PAD 格式的 dimensions 键名映射到前端显示名 */
function mapDimensions(dims: Record<string, number>): Record<string, number> {
  const mapped: Record<string, number> = {};
  for (const [key, val] of Object.entries(dims)) {
    const displayName = PAD_TO_DISPLAY[key] || key;
    mapped[displayName] = val;
  }
  return mapped;
}

export function useEmotionData(pollInterval = 5000) {
  const { current, history, setCurrent, setHistory } = useEmotionStore();

  const refresh = useCallback(async () => {
    try {
      const [emotionRes, historyRes] = await Promise.all([
        fetchEmotion(),
        fetchEmotionHistory(50),
      ]);

      // 旧 API 返回 {emotion: {...}}，新 PAD API 直接返回 {...pad, dimensions...}
      let emotionData = emotionRes.emotion || emotionRes;

      // 如果响应有 pad 字段 → PAD 格式，做维度映射
      if (emotionData?.pad && emotionData?.dimensions) {
        emotionData = {
          ...emotionData,
          dimensions: mapDimensions(emotionData.dimensions),
          possible_cause: emotionData.primary_emotion || '',
          need: '',
        };
      }

      if (emotionData?.primary_emotion) {
        setCurrent(emotionData);
      }

      if (historyRes.history) {
        setHistory(historyRes.history);
      }
    } catch {
      // Silently ignore polling errors
    }
  }, [setCurrent, setHistory]);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, pollInterval);
    return () => clearInterval(interval);
  }, [refresh, pollInterval]);

  return { current, history, refresh };
}
