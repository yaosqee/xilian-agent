/* FILE: src/components/panels/PortraitPanel.tsx */
import React, { useEffect, useState, useCallback } from 'react';
import { fetchUserPortrait } from '../../services/api';

export const PortraitPanel: React.FC = () => {
  const [portrait, setPortrait] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const [changes, setChanges] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await fetchUserPortrait();
      if (data.error) {
        setError(data.error);
      } else {
        setPortrait(data.portrait);
        setVersion(data.version);
        setUpdatedAt(data.updated_at);
        setChanges(data.changes);
      }
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // 空状态时自动轮询（印象可能在当前会话中刚生成）
  useEffect(() => {
    if (portrait !== null || loading) return;
    const timer = setInterval(load, 5000);
    // 30 秒后停止轮询
    const stop = setTimeout(() => clearInterval(timer), 30000);
    return () => { clearInterval(timer); clearTimeout(stop); };
  }, [portrait, loading, load]);

  const formatDate = (ts: number | null) => {
    if (!ts) return '';
    return new Date(ts * 1000).toLocaleString('zh-CN', {
      month: 'numeric', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    });
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 12 }}>
      {/* 状态栏 */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        fontSize: 12, color: 'var(--color-text-dim)',
        padding: '8px 12px', borderRadius: 8,
        background: 'rgba(255, 183, 197, 0.06)',
      }}>
        <span>
          {version > 0 ? `第 ${version} 版` : '尚未生成'}
          {updatedAt ? ` · ${formatDate(updatedAt)} 更新` : ''}
        </span>
        <button
          onClick={load}
          disabled={loading}
          style={{
            padding: '2px 10px', borderRadius: 'var(--radius-full)',
            border: '1px solid rgba(200, 175, 220, 0.3)',
            background: 'rgba(255, 255, 255, 0.4)',
            color: 'var(--color-text-dim)', fontSize: 11,
            cursor: loading ? 'default' : 'pointer',
            opacity: loading ? 0.5 : 1,
          }}
        >
          {loading ? '刷新中...' : '刷新'}
        </button>
      </div>

      {/* 加载状态 */}
      {loading && (
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          <span style={{
            display: 'inline-block', width: 20, height: 20,
            border: '2px solid rgba(200, 175, 220, 0.3)',
            borderTopColor: 'var(--color-pink)',
            borderRadius: '50%',
            animation: 'spin 0.6s linear infinite',
          }} />
        </div>
      )}

      {/* 错误状态 */}
      {!loading && error && (
        <div style={{ textAlign: 'center', padding: 24, color: 'var(--color-text-muted)', fontSize: 13 }}>
          加载失败：{error}
        </div>
      )}

      {/* 空状态 */}
      {!loading && !error && !portrait && (
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column',
          alignItems: 'center', justifyContent: 'center', gap: 8,
        }}>
          <span style={{ fontSize: 36, opacity: 0.6 }}>📖</span>
          <span style={{ fontSize: 14, color: 'var(--color-text)' }}>
            昔涟还没有写下对你的印象呢
          </span>
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            聊一会儿天之后，她会在这里轻轻记下对你的理解
          </span>
        </div>
      )}

      {/* 印象内容 */}
      {!loading && !error && portrait && (
        <>
          <div style={{
            flex: 1, overflowY: 'auto',
            padding: '16px 20px',
            borderRadius: 'var(--radius-card)',
            background: 'rgba(255, 255, 255, 0.35)',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
            border: '1px solid rgba(255, 183, 197, 0.15)',
            fontSize: 14,
            lineHeight: 2,
            color: 'var(--color-text)',
            whiteSpace: 'pre-wrap',
            fontFamily: 'var(--font-serif)',
            letterSpacing: '0.02em',
          }}>
            {portrait}
          </div>

          {/* 变更记录 */}
          {changes && (
            <div style={{
              padding: '8px 12px', borderRadius: 8,
              background: 'rgba(200, 175, 220, 0.08)',
              fontSize: 12, color: 'var(--color-text-dim)',
            }}>
              <span style={{ fontWeight: 500, color: 'var(--color-purple-dark)' }}>
                最近更新：
              </span>
              {changes}
            </div>
          )}
        </>
      )}
    </div>
  );
};
