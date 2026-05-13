import React from 'react';
import { EMOTION_DIMENSIONS, EMOTION_COLORS } from '../../types/emotion';

export const EmotionLegend: React.FC = () => {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 14px', justifyContent: 'center' }}>
      {EMOTION_DIMENSIONS.map((name) => (
        <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: EMOTION_COLORS[name],
            }}
          />
          <span style={{ fontSize: 12, color: 'rgba(255,255,255,0.6)' }}>{name}</span>
        </div>
      ))}
    </div>
  );
};
