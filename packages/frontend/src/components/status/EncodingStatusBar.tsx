import React, { useEffect, useState } from 'react';
import { fetchEncodingStatus } from '../../services/api';

type EncodingState = 'idle' | 'waiting' | 'encoding' | 'done';

const STATE_CONFIG: Record<EncodingState, { text: string; emoji: string; show: boolean }> = {
  idle: { text: '', emoji: '', show: false },
  waiting: { text: '昔涟在等着整理记忆…', emoji: '📝', show: true },
  encoding: { text: '昔涟正在整理记忆…', emoji: '📝', show: true },
  done: { text: '昔涟好好记下了~♪', emoji: '✨', show: true },
};

export const EncodingStatusBar: React.FC = () => {
  const [state, setState] = useState<EncodingState>('idle');

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetchEncodingStatus();
        const s = res.state as EncodingState;
        if (STATE_CONFIG[s]) setState(s);
      } catch {
        // ignore
      }
    };
    poll();
    const interval = setInterval(poll, 2000);
    return () => clearInterval(interval);
  }, []);

  // "done" auto-hides after 5s
  useEffect(() => {
    if (state === 'done') {
      const timer = setTimeout(() => setState('idle'), 5000);
      return () => clearTimeout(timer);
    }
  }, [state]);

  const config = STATE_CONFIG[state];
  if (!config.show) return null;

  const isDone = state === 'done';
  const isActive = state === 'encoding' || state === 'waiting';

  return (
    <div
      style={{
        position: 'absolute',
        bottom: 80,
        left: 16,
        padding: '6px 16px',
        borderRadius: 12,
        background: isDone
          ? 'rgba(100, 200, 100, 0.12)'
          : 'rgba(255, 255, 255, 0.06)',
        fontSize: 12,
        color: isDone ? '#a0d0a0' : 'rgba(255,255,255,0.5)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        transition: 'opacity 500ms',
        opacity: isDone ? 0.9 : 1,
      }}
    >
      {isActive && (
        <span
          style={{
            display: 'inline-block',
            width: 8,
            height: 8,
            borderRadius: '50%',
            background: 'rgba(255,255,255,0.4)',
            animation: 'pulse 1.5s ease infinite',
          }}
        />
      )}
      <span>
        {config.emoji} {config.text}
      </span>
    </div>
  );
};
