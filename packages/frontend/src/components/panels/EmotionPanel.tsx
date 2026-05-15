import React, { useState, useCallback, useEffect } from 'react';
import { useEmotionData } from '../../hooks/useEmotionData';
import { EmotionGauge } from '../EmotionGauge/EmotionGauge';
import { EmotionLegend } from '../EmotionGauge/EmotionLegend';
import { PADTrajectory } from './PADTrajectory';
import { AffectionBar } from '../AffectionBar';
import { fetchPADHistory } from '../../services/api';
import type { PADSnapshot, PADPoint } from '../../types/emotion';

type TabKey = 'radar' | 'pad';

const tabStyle = (active: boolean): React.CSSProperties => ({
  flex: 1,
  padding: '8px 0',
  border: 'none',
  borderRadius: 8,
  cursor: 'pointer',
  fontSize: 13,
  fontWeight: active ? 600 : 400,
  background: active ? 'rgba(255,179,179,0.15)' : 'transparent',
  color: active ? '#FFB3B3' : 'rgba(255,255,255,0.4)',
  transition: 'all 0.2s',
});

export const EmotionPanel: React.FC = () => {
  const { current, history } = useEmotionData(5000);
  const [activeTab, setActiveTab] = useState<TabKey>('radar');
  const [padSnapshots, setPadSnapshots] = useState<PADSnapshot[]>([]);
  const [padCurrent, setPadCurrent] = useState<PADPoint | null>(null);

  // PAD 数据独立轮询（只在切换到 PAD tab 时激活）
  const refreshPAD = useCallback(async () => {
    try {
      const res = await fetchPADHistory(100);
      if (res.snapshots) {
        setPadSnapshots(res.snapshots);
      }
      // 从当前 emotion API 获取 live PAD 坐标
      const { fetchEmotion } = await import('../../services/api');
      const emo = await fetchEmotion();
      if (emo?.pad) {
        setPadCurrent(emo.pad);
      }
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    if (activeTab === 'pad') {
      refreshPAD();
      const interval = setInterval(refreshPAD, 5000);
      return () => clearInterval(interval);
    }
  }, [activeTab, refreshPAD]);

  return (
    <div>
      <AffectionBar />
      <h3 style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>📊 情绪感知</h3>
      <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.4)', marginBottom: 16 }}>
        昔涟感受到的情绪涟漪
      </p>

      {/* Tab 切换 */}
      <div style={{
        display: 'flex',
        gap: 6,
        marginBottom: 20,
        background: 'rgba(255,255,255,0.03)',
        borderRadius: 10,
        padding: 3,
      }}>
        <button style={tabStyle(activeTab === 'radar')} onClick={() => setActiveTab('radar')}>
          🎯 雷达图
        </button>
        <button style={tabStyle(activeTab === 'pad')} onClick={() => setActiveTab('pad')}>
          🌊 PAD 轨迹
        </button>
      </div>

      {/* 雷达图 Tab */}
      {activeTab === 'radar' && (
        current ? (
          <>
            <div style={{
              textAlign: 'center', marginBottom: 16,
              padding: '12px', borderRadius: 12,
              background: 'rgba(255,255,255,0.04)',
            }}>
              <span style={{ fontSize: 32 }}>
                {current.primary_intensity > 0.7 ? '🔥' : current.primary_intensity > 0.4 ? '💫' : '🍃'}
              </span>
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
        )
      )}

      {/* PAD 轨迹 Tab */}
      {activeTab === 'pad' && (
        <>
          {padCurrent && (
            <div style={{
              textAlign: 'center', marginBottom: 16,
              padding: '10px', borderRadius: 12,
              background: 'rgba(255,255,255,0.04)',
            }}>
              <span style={{ fontSize: 14, color: 'rgba(255,255,255,0.5)' }}>当前 PAD</span>
              <p style={{ fontSize: 14, fontWeight: 600, margin: '4px 0 0', fontFamily: 'monospace' }}>
                P={padCurrent.P.toFixed(2)} A={padCurrent.A.toFixed(2)} D={padCurrent.D.toFixed(2)}
              </p>
            </div>
          )}
          <PADTrajectory
            snapshots={padSnapshots}
            current={padCurrent}
            width={580}
            height={400}
          />
        </>
      )}

      {/* 情绪历史（仅雷达图 Tab 显示） */}
      {activeTab === 'radar' && history.length > 0 && (
        <div style={{ marginTop: 24 }}>
          <h4 style={{ fontSize: 14, fontWeight: 600, marginBottom: 12, color: 'rgba(255,255,255,0.6)' }}>
            📈 情绪历史
          </h4>
        </div>
      )}
    </div>
  );
};
