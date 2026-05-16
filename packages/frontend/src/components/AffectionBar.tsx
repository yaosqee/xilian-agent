import React, { useState, useEffect, useCallback } from 'react';
import { fetchEmotionStats } from '../services/api';

interface AffectionData {
  score: number; level: number; label: string; emoji: string;
}

const LEVELS: AffectionData[] = [
  { score: 25, level: 1, label: '初遇', emoji: '🌱' },
  { score: 50, level: 2, label: '相识', emoji: '🌿' },
  { score: 75, level: 3, label: '老友', emoji: '🌳' },
  { score: 100, level: 4, label: '羁绊', emoji: '💎' },
];

function getLevel(score: number): AffectionData {
  for (let i = LEVELS.length - 1; i >= 0; i--) {
    if (score >= LEVELS[i].score) return LEVELS[i];
  }
  return LEVELS[0];
}

export const AffectionBar: React.FC = () => {
  const [affection, setAffection] = useState(50);
  const level = getLevel(affection);

  const refresh = useCallback(async () => {
    try {
      const res = await fetchEmotionStats(30);
      if (res) {
        let score = 50;
        score += Math.min(30, (res.snapshot_count || 0) * 0.5);
        if (res.emotion_distribution) {
          const pos = (res.emotion_distribution['快乐'] || 0) + (res.emotion_distribution['平静'] || 0) * 0.5;
          score += pos * 30;
        }
        if (res.emotional_volatility) score -= Math.min(15, res.emotional_volatility * 20);
        setAffection(Math.max(5, Math.min(100, Math.round(score))));
      }
    } catch {}
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <div style={{
      padding: '8px 12px', borderRadius: 10,
      background: 'rgba(255, 183, 197, 0.06)', marginBottom: 12,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-dim)' }}>
          {level.emoji} {level.label}
        </span>
        <span style={{ fontSize: 12, color: 'var(--color-pink-dark)', fontWeight: 600 }}>
          羁绊值 {affection}
        </span>
      </div>
      <div style={{ height: 4, borderRadius: 2, background: 'rgba(200, 180, 210, 0.15)', overflow: 'hidden' }}>
        <div style={{
          height: '100%', borderRadius: 2, width: `${affection}%`,
          background: 'linear-gradient(90deg, var(--color-pink), var(--color-pink-dark))',
          transition: 'width 0.5s var(--ease-spring)',
        }} />
      </div>
    </div>
  );
};
