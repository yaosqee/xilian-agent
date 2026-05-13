import React from 'react';
import { useEmotionData } from '../../hooks/useEmotionData';
import { EmotionGauge } from '../EmotionGauge/EmotionGauge';
import { EmotionLegend } from '../EmotionGauge/EmotionLegend';
import { EmotionTimeline } from '../EmotionGauge/EmotionTimeline';

export const EmotionPanel: React.FC = () => {
  const { current, history } = useEmotionData(5000);

  return (
    <div>
      <h3 style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>📊 情绪感知</h3>
      <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.4)', marginBottom: 20 }}>
        昔涟感受到的情绪涟漪
      </p>

      {current ? (
        <>
          <div
            style={{
              textAlign: 'center',
              marginBottom: 16,
              padding: '12px',
              borderRadius: 12,
              background: 'rgba(255,255,255,0.04)',
            }}
          >
            <span style={{ fontSize: 32 }}>{current.primary_intensity > 0.7 ? '🔥' : current.primary_intensity > 0.4 ? '💫' : '🍃'}</span>
            <p style={{ fontSize: 16, fontWeight: 600, margin: '8px 0 4px' }}>
              主要情绪：{current.primary_emotion}
            </p>
            <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.5)', margin: 0 }}>
              强度 {Math.round(current.primary_intensity * 100)}%
              {current.possible_cause && ` · ${current.possible_cause}`}
            </p>
          </div>

          <div style={{ marginBottom: 20 }}>
            <EmotionGauge data={current} width={300} height={300} />
          </div>
          <EmotionLegend />
        </>
      ) : (
        <p style={{ color: 'rgba(255,255,255,0.3)', fontSize: 14, textAlign: 'center', marginTop: 60 }}>
          还没有情绪数据呢…<br />多说几句话，昔涟就能感受到啦~
        </p>
      )}

      {history.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <h4 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: 'rgba(255,255,255,0.6)' }}>
            📈 情绪历史
          </h4>
          <EmotionTimeline data={history} width={300} height={100} />
        </div>
      )}
    </div>
  );
};
