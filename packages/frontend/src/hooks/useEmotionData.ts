import { useEffect, useCallback } from 'react';
import { useEmotionStore } from '../stores/emotionStore';
import { fetchEmotion, fetchEmotionHistory } from '../services/api';

export function useEmotionData(pollInterval = 5000) {
  const { current, history, setCurrent, setHistory } = useEmotionStore();

  const refresh = useCallback(async () => {
    try {
      const [emotionRes, historyRes] = await Promise.all([
        fetchEmotion(),
        fetchEmotionHistory(50),
      ]);
      if (emotionRes.emotion) setCurrent(emotionRes.emotion);
      if (historyRes.history) setHistory(historyRes.history);
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
