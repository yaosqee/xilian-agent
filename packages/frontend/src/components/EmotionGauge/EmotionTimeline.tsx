import React, { useRef, useEffect } from 'react';
import type { EmotionData } from '../../types/emotion';
import { EMOTION_COLORS } from '../../types/emotion';

interface Props {
  data: EmotionData[];
  width: number;
  height: number;
}

export const EmotionTimeline: React.FC<Props> = React.memo(({ data, width, height }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || data.length < 2) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, width, height);

    const padding = { top: 10, right: 10, bottom: 20, left: 30 };
    const plotW = width - padding.left - padding.right;
    const plotH = height - padding.top - padding.bottom;

    // Intensity over time
    const intensities = data.map((d) => d.primary_intensity);
    const maxIntensity = Math.max(...intensities, 0.1);

    ctx.beginPath();
    ctx.strokeStyle = 'rgba(100, 180, 255, 0.6)';
    ctx.lineWidth = 2;
    ctx.fillStyle = 'rgba(100, 180, 255, 0.1)';

    intensities.forEach((v, i) => {
      const x = padding.left + (i / (intensities.length - 1)) * plotW;
      const y = padding.top + plotH - (v / maxIntensity) * plotH;
      if (i === 0) { ctx.moveTo(x, y); return; }
      ctx.lineTo(x, y);
    });

    ctx.stroke();

    // Fill under curve
    ctx.lineTo(padding.left + plotW, padding.top + plotH);
    ctx.lineTo(padding.left, padding.top + plotH);
    ctx.closePath();
    ctx.fill();

    // Axis
    ctx.strokeStyle = 'rgba(255,255,255,0.1)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padding.left, padding.top + plotH);
    ctx.lineTo(padding.left + plotW, padding.top + plotH);
    ctx.stroke();

    // Labels
    if (data.length > 0) {
      const latest = data[data.length - 1];
      ctx.fillStyle = EMOTION_COLORS[latest.primary_emotion] || 'rgba(255,255,255,0.6)';
      ctx.font = '11px sans-serif';
      ctx.fillText(
        `${latest.primary_emotion} ${Math.round(latest.primary_intensity * 100)}%`,
        padding.left,
        12,
      );
    }
  }, [data, width, height]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      style={{ display: 'block', width: '100%' }}
    />
  );
});
