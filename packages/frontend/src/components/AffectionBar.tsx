import React, { useEffect, useCallback } from 'react';
import { useAffectionStore } from '../stores/affectionStore';

const LEVEL_ICONS: Record<number, string> = {
  1: '❤️',
  2: '💕',
  3: '💖',
  4: '💝',
};

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
  const level = data?.level ?? 1;
  const label = data?.level_label ?? '昔涟喜欢你';
  const icon = LEVEL_ICONS[level] || '❤️';

  return (
    <div style={{
      padding: '8px 12px', borderRadius: 10,
      background: 'rgba(255, 183, 197, 0.06)', marginBottom: 12,
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
        <span style={{ fontSize: 12, color: 'var(--color-text-dim)' }}>
          {icon} {label}
        </span>
        <span style={{ fontSize: 12, color: 'var(--color-pink-dark)', fontWeight: 600 }}>
          好感度 {score.toFixed(1)}
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
