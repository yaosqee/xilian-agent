/**
 * AutobiographyPanel — 自传体故事流
 *
 * 阶段 5 新增。展示昔涟的《生命故事》日记。
 * 左侧目录 + 右侧正文，像翻一本厚厚的故事书。
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

  const loadLatest = useCallback(async () => {
    try {
      const res = await fetchAutobiography();
      if (res.entry) setEntry(res.entry);
    } catch { /* silent */ }
  }, []);

  const loadList = useCallback(async () => {
    try {
      const res = await fetchAutobiographyList(30);
      if (res.entries) setList(res.entries);
    } catch { /* silent */ }
  }, []);

  const loadDate = useCallback(async (date: string) => {
    setSelected(date);
    try {
      const res = await fetchAutobiography(date);
      if (res.entry) setEntry(res.entry);
    } catch { /* silent */ }
  }, []);

  useEffect(() => {
    loadLatest();
    loadList();
  }, [loadLatest, loadList]);

  if (list.length === 0) {
    return (
      <div>
        <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>📔 生命故事</h3>
        <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.3)', textAlign: 'center', padding: 40 }}>
          昔涟还没有开始写日记呢<br />每天凌晨 4:00，她会翻开书页~
        </p>
      </div>
    );
  }

  return (
    <div>
      <h3 style={{ fontSize: 16, fontWeight: 600, marginBottom: 4 }}>📔 生命故事</h3>
      <p style={{ fontSize: 12, color: 'rgba(255,255,255,0.3)', marginBottom: 16 }}>
        {list.length} 篇日记
      </p>

      <div style={{ display: 'flex', gap: 12 }}>
        {/* 目录 */}
        <div style={{
          width: 120, flexShrink: 0, maxHeight: 400, overflowY: 'auto',
          borderRight: '1px solid rgba(255,255,255,0.06)', paddingRight: 8,
        }}>
          {list.map((item) => (
            <button
              key={item.date}
              onClick={() => loadDate(item.date)}
              style={{
                display: 'block', width: '100%', textAlign: 'left', padding: '6px 8px',
                border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 12,
                background: selected === item.date || (!selected && item === list[0])
                  ? 'rgba(255,179,179,0.1)' : 'transparent',
                color: (selected === item.date || (!selected && item === list[0]))
                  ? '#FFB3B3' : 'rgba(255,255,255,0.5)',
                marginBottom: 2,
              }}
            >
              {formatDate(item.date)}
            </button>
          ))}
        </div>

        {/* 正文 */}
        <div style={{
          flex: 1, maxHeight: 400, overflowY: 'auto',
          padding: '16px', borderRadius: 12,
          background: 'rgba(255,179,179,0.04)',
        }}>
          {entry ? (
            <>
              {entry.mood_summary && (
                <p style={{ fontSize: 12, color: 'rgba(255,179,179,0.6)', marginBottom: 12 }}>
                  🎵 {entry.mood_summary} · {entry.word_count || 0} 字
                </p>
              )}
              <div style={{
                fontSize: 14, lineHeight: 2, color: 'rgba(255,255,255,0.75)',
                whiteSpace: 'pre-wrap', fontFamily: '"Noto Serif SC", serif',
              }}>
                {entry.content}
              </div>
            </>
          ) : (
            <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.3)' }}>点击左侧日期阅读~</p>
          )}
        </div>
      </div>
    </div>
  );
};
