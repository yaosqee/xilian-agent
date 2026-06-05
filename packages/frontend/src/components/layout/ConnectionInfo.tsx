/* FILE: src/components/layout/ConnectionInfo.tsx */
import React, { useState, useEffect, useRef } from 'react';
import QRCode from 'qrcode';

/* ── 局域网信息 API 返回 ── */
interface LanInfo {
  host: string;
  port: number;
  lan_url: string | null;
  lan_ip: string | null;
}

/* ══════════════════════════════════════════════
   连接信息 · 局域网 URL + 二维码（桌面不显示）
   ══════════════════════════════════════════════ */
export const ConnectionInfo: React.FC = () => {
  const [lanInfo, setLanInfo] = useState<LanInfo | null>(null);
  const [showQR, setShowQR] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    fetch('/api/lan-info')
      .then((r) => r.json())
      .then((data) => {
        if (data.lan_url) setLanInfo(data);
      })
      .catch(() => {});
  }, []);

  // 生成二维码到 canvas
  useEffect(() => {
    if (showQR && lanInfo?.lan_url && canvasRef.current) {
      QRCode.toCanvas(canvasRef.current, lanInfo.lan_url, {
        width: 240,
        margin: 1,
        color: {
          dark: '#5E4B66',
          light: '#FFF5F8',
        },
      });
    }
  }, [showQR, lanInfo]);

  if (!lanInfo || dismissed) return null;

  return (
    <>
      {/* 横幅 */}
      <div
        onClick={() => setShowQR(true)}
        style={{
          padding: '8px 16px',
          margin: '4px 12px 0',
          borderRadius: 'var(--radius-btn)',
          background: 'rgba(255, 183, 197, 0.12)',
          border: '1px solid rgba(255, 183, 197, 0.25)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: 8,
          cursor: 'pointer',
          fontSize: 12,
          color: 'var(--color-text)',
          flexShrink: 0,
        }}
      >
        <span>📱 {lanInfo.lan_url}</span>
        <button
          onClick={(e) => {
            e.stopPropagation();
            setDismissed(true);
          }}
          aria-label="关闭"
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--color-text-muted)',
            fontSize: 14,
            cursor: 'pointer',
            padding: '2px 6px',
            lineHeight: 1,
          }}
        >
          ×
        </button>
      </div>

      {/* 二维码模态框 */}
      {showQR && (
        <div
          onClick={() => setShowQR(false)}
          style={{
            position: 'fixed',
            inset: 0,
            zIndex: 100,
            background: 'rgba(94, 75, 102, 0.4)',
            backdropFilter: 'blur(8px)',
            WebkitBackdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: 'rgba(255, 255, 255, 0.7)',
              backdropFilter: 'blur(20px)',
              WebkitBackdropFilter: 'blur(20px)',
              border: '1px solid rgba(255, 255, 255, 0.8)',
              borderRadius: 20,
              padding: '32px',
              textAlign: 'center',
              boxShadow: '0 12px 48px rgba(180, 140, 220, 0.3)',
              maxWidth: '90vw',
            }}
          >
            <canvas ref={canvasRef} style={{ display: 'block', borderRadius: 12 }} />
            <p style={{
              fontSize: 13,
              color: 'var(--color-text-dim)',
              margin: '16px 0 0',
              fontFamily: 'monospace',
              wordBreak: 'break-all',
            }}>
              {lanInfo.lan_url}
            </p>
            <p style={{
              fontSize: 12,
              color: 'var(--color-text-muted)',
              margin: '8px 0 0',
            }}>
              手机浏览器扫描二维码，或直接输入地址
            </p>
            <button
              onClick={() => setShowQR(false)}
              style={{
                marginTop: 16,
                padding: '8px 32px',
                borderRadius: 'var(--radius-full)',
                border: '1px solid rgba(200, 160, 190, 0.3)',
                background: 'var(--glass-bg)',
                color: 'var(--color-text)',
                fontSize: 14,
                cursor: 'pointer',
              }}
            >
              关闭
            </button>
          </div>
        </div>
      )}
    </>
  );
};
