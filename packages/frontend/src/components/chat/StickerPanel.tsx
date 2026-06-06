import React, { useState, useEffect } from 'react';
import { fetchStickers } from '../../services/api';

interface StickerData {
  id: string;
  category: string;
  emotion_tags: string[];
  description: string;
  file: string;
}

interface Props {
  onSelect: (sticker: { id: string; file: string }) => void;
  onClose: () => void;
}

export const StickerPanel: React.FC<Props> = ({ onSelect, onClose }) => {
  const [stickers, setStickers] = useState<StickerData[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchStickers()
      .then((data) => {
        setStickers(data.stickers || []);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  // 按分类分组
  const grouped: Record<string, StickerData[]> = {};
  for (const s of stickers) {
    if (!grouped[s.category]) grouped[s.category] = [];
    grouped[s.category].push(s);
  }

  return (
    <div style={{
      position: 'absolute',
      bottom: 60,
      left: 8,
      right: 8,
      background: 'rgba(255,255,255,0.95)',
      backdropFilter: 'blur(12px)',
      border: '1px solid rgba(216, 180, 226, 0.4)',
      borderRadius: 16,
      padding: 12,
      maxHeight: 300,
      overflowY: 'auto',
      zIndex: 100,
      boxShadow: '0 -4px 20px rgba(216, 180, 226, 0.2)',
    }}>
      {/* 关闭按钮 */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
        <span style={{ fontSize: 13, color: 'var(--color-text-dim)', fontWeight: 500 }}>
          表情包
        </span>
        <button
          onClick={onClose}
          style={{
            border: 'none', background: 'transparent',
            fontSize: 18, color: 'var(--color-text-dim)',
            cursor: 'pointer', padding: '2px 6px',
          }}
        >
          ✕
        </button>
      </div>

      {loading ? (
        <div style={{ textAlign: 'center', padding: 20, color: 'var(--color-text-dim)' }}>
          加载中…
        </div>
      ) : stickers.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 20, color: 'var(--color-text-dim)' }}>
          暂时还没有表情包呢
        </div>
      ) : (
        Object.entries(grouped).map(([category, items]) => (
          <div key={category} style={{ marginBottom: 8 }}>
            <div style={{
              fontSize: 11, color: 'var(--color-text-dim)',
              marginBottom: 4, textTransform: 'uppercase',
            }}>
              {category}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {items.map((s) => (
                <button
                  key={s.id}
                  onClick={() => onSelect({ id: s.id, file: s.file })}
                  title={s.description}
                  style={{
                    width: 56, height: 56,
                    borderRadius: 10,
                    border: '1px solid rgba(216, 180, 226, 0.2)',
                    overflow: 'hidden',
                    cursor: 'pointer',
                    padding: 2,
                    background: 'transparent',
                    transition: 'transform 0.2s, box-shadow 0.2s',
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.transform = 'scale(1.1)';
                    e.currentTarget.style.boxShadow = '0 2px 8px rgba(255, 183, 197, 0.3)';
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.transform = 'scale(1)';
                    e.currentTarget.style.boxShadow = 'none';
                  }}
                >
                  <img
                    src={`/api/stickers/${s.file}`}
                    alt={s.id}
                    style={{ width: '100%', height: '100%', objectFit: 'contain' }}
                    onError={(e) => {
                      (e.target as HTMLImageElement).style.display = 'none';
                    }}
                  />
                </button>
              ))}
            </div>
          </div>
        ))
      )}
    </div>
  );
};
