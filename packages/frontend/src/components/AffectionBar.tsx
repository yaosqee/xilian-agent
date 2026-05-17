import React, { useEffect, useCallback } from 'react';
import { useAffectionStore } from '../stores/affectionStore';

interface LevelInfo {
  threshold: number;
  level: number;
  label: string;
  icon: string;
}

const LEVELS: LevelInfo[] = [
  { threshold: 25,  level: 1, label: '昔涟喜欢你',     icon: '❤️' },
  { threshold: 50,  level: 2, label: '昔涟非常喜欢你', icon: '💕' },
  { threshold: 75,  level: 3, label: '昔涟特别喜欢你', icon: '💖' },
  { threshold: 100, level: 4, label: '你永远喜欢昔涟', icon: '💝' },
];

function getLevelInfo(score: number): LevelInfo {
  for (let i = LEVELS.length - 1; i >= 0; i--) {
    if (score >= LEVELS[i].threshold) return LEVELS[i];
  }
  return LEVELS[0];
}

export const AffectionBar: React.FC = () => {
  const { data, refresh } = useAffectionStore();

  const doRefresh = useCallback(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    refresh();
    const interval = setInterval(doRefresh, 15000);
    return () => clearInterval(interval);
  }, [doRefresh]);

  const score = data?.score ?? 0;
  const info = getLevelInfo(score);

  return (
    <div style={{
      padding: '8px 12px', borderRadius: 10,
      background: 'rgba(255, 183, 197, 0.06)', marginBottom: 12,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-dim)' }}>
          {info.icon} {info.label}
        </span>
        <span style={{ fontSize: 12, color: 'var(--color-pink-dark)', fontWeight: 600 }}>
          好感度 {Math.round(score)}
        </span>
      </div>
      <div style={{ height: 4, borderRadius: 2, background: 'rgba(200, 180, 210, 0.15)', overflow: 'hidden' }}>
        <div style={{
          height: '100%', borderRadius: 2, width: `${Math.min(100, score)}%`,
          background: score >= 100
            ? 'linear-gradient(90deg, #ff6b9d, #ff3366)'
            : 'linear-gradient(90deg, var(--color-pink), var(--color-pink-dark))',
          transition: 'width 0.5s var(--ease-spring)',
        }} />
      </div>
    </div>
  );
};
