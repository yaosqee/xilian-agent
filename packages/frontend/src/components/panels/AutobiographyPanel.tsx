/**
 * AutobiographyPanel — 自传体故事流 (light theme)
 */
import React, { useState, useEffect, useCallback } from 'react';
import { fetchAutobiography, fetchAutobiographyList } from '../../services/api';

interface AutoEntry {
  date: string;
  content: string;
  mood_summary?: string;
  word_count?: number;
}

interface AutoListItem {
  date: string;
  mood_summary?: string;
  word_count?: number;
}

const formatDate = (d: string): string => {
  const [y, m, day] = d.split('-');
  return `${y}年${parseInt(m)}月${parseInt(day)}日`;
};

export const AutobiographyPanel: React.FC = () => {
  const [entry, setEntry] = useState<AutoEntry | null>(null);
  const [list, setList] = useState<AutoListItem[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);

  const loadLatest = useCallback(async () => {
    try {
      const res = await fetchAutobiography();
      if (res.entry) setEntry(res.entry);
    } catch {}
  }, []);

  const loadList = useCallback(async () => {
    try {
      const res = await fetchAutobiographyList(30);
      if (res.entries) setList(res.entries);
    } catch {}
  }, []);

  const loadDate = useCallback(async (date: string) => {
    setSelected(date);
    try {
      const res = await fetchAutobiography(date);
      if (res.entry) setEntry(res.entry);
    } catch {}
  }, []);

  useEffect(() => {
    loadLatest();
    loadList();
  }, [loadLatest, loadList]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await fetch('/api/autobiography/generate', { method: 'POST' });
      await loadList();
      await loadLatest();
    } catch {} finally { setGenerating(false); }
  };

  if (list.length === 0) {
    return (
      <div>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4, color: 'var(--color-text)' }}>
          生命故事
        </h3>
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', textAlign: 'center', padding: '20px 40px' }}>
          昔涟还没有开始写日记呢<br />每天凌晨 4:00，她会翻开书页~
        </p>
        <div style={{ textAlign: 'center' }}>
          <button
            onClick={handleGenerate}
            disabled={generating}
            style={{
              padding: '8px 24px',
              borderRadius: 10,
              border: '1px solid var(--color-pink)',
              background: generating ? 'rgba(255, 183, 197, 0.1)' : 'rgba(255, 183, 197, 0.15)',
              color: 'var(--color-pink-dark)',
              fontSize: 13,
              cursor: generating ? 'not-allowed' : 'pointer',
              transition: 'all 0.3s var(--ease-spring)',
            }}
          >
            {generating ? '正在生成……' : '✨ 立即生成第一篇日记'}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4, color: 'var(--color-text)' }}>
        生命故事
      </h3>
      <p style={{ fontSize: 12, color: 'var(--color-text-dim)', marginBottom: 16 }}>
        {list.length} 篇日记
      </p>

      <div style={{ display: 'flex', gap: 12 }}>
        {/* 目录 */}
        <div style={{
          width: 110, flexShrink: 0, maxHeight: 400, overflowY: 'auto',
          borderRight: '1px solid rgba(200, 180, 210, 0.15)', paddingRight: 8,
        }}>
          {list.map((item, i) => {
            const isActive = selected === item.date || (!selected && i === 0);
            return (
              <button
                key={item.date}
                onClick={() => loadDate(item.date)}
                style={{
                  display: 'block', width: '100%', textAlign: 'left', padding: '6px 8px',
                  border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12,
                  background: isActive ? 'rgba(255, 183, 197, 0.12)' : 'transparent',
                  color: isActive ? 'var(--color-pink-dark)' : 'var(--color-text-dim)',
                  marginBottom: 2, fontWeight: isActive ? 500 : 400,
                }}
              >
                {formatDate(item.date)}
              </button>
            );
          })}
        </div>

        {/* 正文 */}
        <div style={{
          flex: 1, maxHeight: 400, overflowY: 'auto',
          padding: '16px', borderRadius: 12,
          background: 'rgba(255, 183, 197, 0.05)',
        }}>
          {entry ? (
            <>
              {entry.mood_summary && (
                <p style={{ fontSize: 12, color: 'var(--color-text-dim)', marginBottom: 12 }}>
                  {entry.mood_summary} · {entry.word_count || 0} 字
                </p>
              )}
              <div style={{
                fontSize: 14, lineHeight: 2, color: 'var(--color-text)',
                whiteSpace: 'pre-wrap', fontFamily: '"Noto Serif SC", serif',
              }}>
                {entry.content}
              </div>
            </>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>点击左侧日期阅读~</p>
          )}
        </div>
      </div>
    </div>
  );
};
