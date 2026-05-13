import React, { useRef, useEffect } from 'react';
import type { EmotionData } from '../../types/emotion';
import { EMOTION_DIMENSIONS } from '../../types/emotion';
import { EMOTION_COLORS } from '../../types/emotion';
import { AXIS_COUNT, ANGLE_STEP, START_ANGLE, getPoint } from '../../utils/radarMath';

interface Props {
  data: EmotionData;
  width: number;
  height: number;
}

export const EmotionGauge: React.FC<Props> = React.memo(({ data, width, height }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) / 2 - 40;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    ctx.clearRect(0, 0, width, height);

    // Background grid
    for (let i = 1; i <= 5; i++) {
      const r = (radius / 5) * i;
      ctx.beginPath();
      for (let j = 0; j <= AXIS_COUNT; j++) {
        const angle = START_ANGLE + (j % AXIS_COUNT) * ANGLE_STEP;
        const x = centerX + r * Math.cos(angle);
        const y = centerY + r * Math.sin(angle);
        if (j === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.strokeStyle = `rgba(255,255,255,${0.04 + i * 0.02})`;
      ctx.lineWidth = 1;
      ctx.stroke();
    }

    // Axes
    for (let i = 0; i < AXIS_COUNT; i++) {
      const angle = START_ANGLE + i * ANGLE_STEP;
      const x = centerX + radius * Math.cos(angle);
      const y = centerY + radius * Math.sin(angle);
      ctx.beginPath();
      ctx.moveTo(centerX, centerY);
      ctx.lineTo(x, y);
      ctx.strokeStyle = 'rgba(255,255,255,0.12)';
      ctx.stroke();

      // Labels
      ctx.fillStyle = 'rgba(255,255,255,0.5)';
      ctx.font = '11px sans-serif';
      ctx.textAlign = 'center';
      const labelR = radius + 20;
      const lx = centerX + labelR * Math.cos(angle);
      const ly = centerY + labelR * Math.sin(angle);
      ctx.fillText(EMOTION_DIMENSIONS[i], lx, ly + 4);
    }

    // Data polygon
    const dims = data.dimensions;
    ctx.beginPath();
    for (let i = 0; i < AXIS_COUNT; i++) {
      const value = dims[EMOTION_DIMENSIONS[i]] ?? 0;
      const { x, y } = getPoint(centerX, centerY, radius, value, i);
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.closePath();
    ctx.fillStyle = 'rgba(100, 180, 255, 0.15)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(100, 180, 255, 0.6)';
    ctx.lineWidth = 2;
    ctx.stroke();

    // Data points
    for (let i = 0; i < AXIS_COUNT; i++) {
      const value = dims[EMOTION_DIMENSIONS[i]] ?? 0;
      const { x, y } = getPoint(centerX, centerY, radius, value, i);
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      const color = EMOTION_COLORS[EMOTION_DIMENSIONS[i]];
      ctx.fillStyle = color;
      ctx.fill();
    }
  }, [data, width, height, centerX, centerY, radius]);

  return (
    <canvas
      ref={canvasRef}
      width={width}
      height={height}
      style={{ display: 'block', margin: '0 auto' }}
    />
  );
});
