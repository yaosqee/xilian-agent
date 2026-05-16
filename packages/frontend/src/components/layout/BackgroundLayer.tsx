/* FILE: src/components/layout/BackgroundLayer.tsx */
import React, { useEffect, useState } from 'react';

interface Props {
  /** 自定义背景图 URL，为空时使用默认 xilian.png */
  customUrl?: string | null;
}

const DEFAULT_BG = '/photo/xilian.png';

export const BackgroundLayer: React.FC<Props> = ({ customUrl }) => {
  const [current, setCurrent] = useState(DEFAULT_BG);
  const [next, setNext] = useState<string | null>(null);
  const [fadeOut, setFadeOut] = useState(false);

  useEffect(() => {
    const target = customUrl || DEFAULT_BG;
    if (target === current) return;

    // 交叉淡入淡出
    setNext(target);
    setFadeOut(false);
    const t1 = setTimeout(() => setFadeOut(true), 50);
    const t2 = setTimeout(() => {
      setCurrent(target);
      setNext(null);
      setFadeOut(false);
    }, 500);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [customUrl, current]);

  return (
    <div
      aria-hidden="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
        pointerEvents: 'none',
      }}
    >
      {/* 当前层 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          backgroundImage: `url(${current})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          backgroundRepeat: 'no-repeat',
          opacity: next ? (fadeOut ? 0 : 1) : 1,
          transition: 'opacity 0.5s var(--ease-spring)',
        }}
      />
      {/* 过渡层 */}
      {next && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            backgroundImage: `url(${next})`,
            backgroundSize: 'cover',
            backgroundPosition: 'center',
            backgroundRepeat: 'no-repeat',
            opacity: fadeOut ? 1 : 0,
            transition: 'opacity 0.5s var(--ease-spring)',
          }}
        />
      )}
      {/* 柔光遮罩 — 使背景不至于太重，同时保持氛围 */}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background: 'linear-gradient(160deg, rgba(255, 240, 245, 0.27) 0%, rgba(240, 244, 255, 0.25) 100%)',
        }}
      />
    </div>
  );
};
