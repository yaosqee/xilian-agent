/**
 * MemoryTimeline — 情景记忆时间线
 *
 * 阶段 5 新增。纵向时间线布局，展示昔涟记住的片段。
 * 轮询 GET /api/memories/recent
 */
import React, { useState, useEffect, useCallback } from 'react';
import { fetchMemoriesRecent } from '../../services/api';

interface Memory {
  id: number;
  summary: string;
  timestamp: number;
  importance: number;
  emotion_tags: string | null;
  access_count: number;
}

const timeAgo = (ts: number): string => {
  const diff = (Date.now() / 1000) - ts;
  if (diff < 3600) return `${Math.round(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.round(diff / 3600)} 小时前`;
  if (diff < 604800) return `${Math.round(diff / 86400)} 天前`;
  return new Date(ts * 1000).toLocaleDateString('zh-CN');
};

const starLevel = (imp: number): string => {
  if (imp > 0.8) return '⭐⭐⭐⭐';
  if (imp > 0.6) return '⭐⭐⭐';
  if (imp > 0.4) return '⭐⭐';
  return '⭐';
};

export const MemoryTimeline: React.FC = () => {
  const [memories, setMemories] = useState<Memory[]>([]);

  const refresh = useCallback(async () => {
    try {
      const res = await fetchMemoriesRecent(25);
      if (res.memories) setMemories(res.memories);
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 10000);
    return () => clearInterval(t);
  }, [refresh]);

  if (memories.length === 0) {
    return (
      <div>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>📖 记忆碎片</h3>
        <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.3)', textAlign: 'center', padding: 40 }}>
          还没有记忆呢<br />多聊几句，昔涟就会记住啦~
        </p>
      </div>
    );
  }

  return (
    <div>
      <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>📖 记忆碎片</h3>
      <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.3)', marginBottom: 16 }}>
        {memories.length} 段记忆
      </p>

      <div style={{ maxHeight: 500, overflowY: 'auto', paddingRight: 4 }}>
        {memories.map((m, i) => (
          <div
            key={m.id}
            style={{
              position: 'relative',
              padding: '12px 12px 12px 20px',
              marginBottom: 6,
              borderRadius: 10,
              background: 'rgba(255,179,179,0.04)',
              borderLeft: i === 0 ? '2px solid #FFB3B3' : '1px solid rgba(255,255,255,0.06)',
              transition: 'all 0.2s',
            }}
          >
            <p style={{ fontSize: 13, margin: '0 0 4px', lineHeight: 1.5, color: 'rgba(255,255,255,0.8)' }}>
              {m.summary.length > 100 ? m.summary.slice(0, 100) + '...' : m.summary}
            </p>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ fontSize: 11, color: 'rgba(255,255,255,0.35)' }}>
                {timeAgo(m.timestamp)}
              </span>
              <span style={{ fontSize: 11 }}>
                {starLevel(m.importance)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
