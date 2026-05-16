/**
 * PADTrajectory — Canvas 2D PAD 三面投影轨迹 (light theme)
 */
import React, { useRef, useEffect } from 'react';
import type { PADSnapshot, PADPoint } from '../../types/emotion';

interface Props {
  snapshots: PADSnapshot[];
  current?: PADPoint | null;
  width?: number;
  height?: number;
}

const PA_COLOR = '#FF9EBB';
const PD_COLOR = '#98D89E';
const CURRENT_DOT = '#FF6B9D';
const GRID_COLOR = 'rgba(180, 160, 200, 0.2)';
const LABEL_COLOR = '#8B7A93';
const BG_COLOR = 'rgba(200, 180, 210, 0.06)';
const BORDER_COLOR = 'rgba(200, 180, 210, 0.15)';

export const PADTrajectory: React.FC<Props> = ({ snapshots, current, width = 320, height = 360 }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const topH = 200;
    const bottomH = height - topH - 16;
    const margin = { top: 22, left: 30, right: 10, bottom: 16 };
    const pw = (width - margin.left - margin.right - 14) / 2;
    const ph = topH - margin.top - margin.bottom;

    const pad = current || snapshots[snapshots.length - 1]?.pad;

    drawPADPlot(ctx, margin.left, margin.top, pw, ph, snapshots, pad, 'P', 'A', '愉悦度', '唤醒度', PA_COLOR);
    const pdX = margin.left + pw + 14;
    drawPADPlot(ctx, pdX, margin.top, pw, ph, snapshots, pad, 'P', 'D', '愉悦度', '支配度', PD_COLOR);

    const timeY = topH + 8;
    drawTimeline(ctx, margin.left, timeY, width - margin.left - margin.right, bottomH, snapshots, pad);
  }, [snapshots, current, width, height]);

  if (snapshots.length === 0) {
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 13, textAlign: 'center', padding: 40 }}>
        还没有 PAD 轨迹数据<br />多说几句话，昔涟的情绪涟漪就会出现~
      </p>
    );
  }

  return (
    <canvas ref={canvasRef} style={{ width, height, borderRadius: 12 }} />
  );
};

function drawPADPlot(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number,
  snapshots: PADSnapshot[],
  currentPad: PADPoint | undefined | null,
  dimX: 'P' | 'A' | 'D', dimY: 'P' | 'A' | 'D',
  labelX: string, labelY: string, dotColor: string,
) {
  const cx = x + w / 2;
  const cy = y + h / 2;

  // Background
  ctx.fillStyle = BG_COLOR;
  roundRect(ctx, x, y, w, h, 8);
  ctx.fill();
  ctx.strokeStyle = BORDER_COLOR;
  ctx.lineWidth = 1;
  roundRect(ctx, x, y, w, h, 8);
  ctx.stroke();

  // Axes
  ctx.strokeStyle = GRID_COLOR;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, cy); ctx.lineTo(x + w, cy);
  ctx.moveTo(cx, y); ctx.lineTo(cx, y + h);
  ctx.stroke();

  // Labels
  ctx.fillStyle = LABEL_COLOR;
  ctx.font = '10px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(labelX, cx, y + h - 4);
  ctx.save();
  ctx.translate(x + 6, cy);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText(labelY, 0, 0);
  ctx.restore();

  // Tick labels
  ctx.font = '8px sans-serif';
  for (const v of [-1, -0.5, 0, 0.5, 1]) {
    const px = cx + v * (w / 2 - 12);
    ctx.fillStyle = LABEL_COLOR;
    ctx.fillText(v.toFixed(1), px, cy + 12);
    const py = cy - v * (h / 2 - 12);
    ctx.fillText(v.toFixed(1), cx - 18, py + 3);
  }

  if (snapshots.length === 0) return;

  const scaleX = (w / 2 - 12) / 1.05;
  const scaleY = (h / 2 - 12) / 1.05;

  // Trajectory lines (gradient color)
  for (let i = 1; i < snapshots.length; i++) {
    const ratio = (i - 1) / (snapshots.length - 1 || 1);
    const r = Math.round(200 - ratio * 100);
    const g = Math.round(150 + ratio * 50);
    const b = Math.round(180 + ratio * 40);
    ctx.strokeStyle = `rgb(${r},${g},${b})`;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(
      cx + snapshots[i - 1].pad[dimX] * scaleX,
      cy - snapshots[i - 1].pad[dimY] * scaleY,
    );
    ctx.lineTo(
      cx + snapshots[i].pad[dimX] * scaleX,
      cy - snapshots[i].pad[dimY] * scaleY,
    );
    ctx.stroke();
  }

  // Trail dots
  for (let i = 0; i < snapshots.length; i++) {
    const ratio = i / (snapshots.length - 1 || 1);
    ctx.fillStyle = `rgba(255, 158, 187, ${0.15 + ratio * 0.5})`;
    ctx.beginPath();
    ctx.arc(
      cx + snapshots[i].pad[dimX] * scaleX,
      cy - snapshots[i].pad[dimY] * scaleY,
      2, 0, Math.PI * 2,
    );
    ctx.fill();
  }

  // Current dot
  if (currentPad) {
    const cpx = cx + currentPad[dimX] * scaleX;
    const cpy = cy - currentPad[dimY] * scaleY;

    ctx.fillStyle = 'rgba(255, 107, 157, 0.12)';
    ctx.beginPath();
    ctx.arc(cpx, cpy, 7, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = CURRENT_DOT;
    ctx.beginPath();
    ctx.arc(cpx, cpy, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // Title
  ctx.fillStyle = 'rgba(139, 122, 147, 0.6)';
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(`${labelX} - ${labelY}`, x + 6, y + 12);
}

function drawTimeline(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number,
  snapshots: PADSnapshot[],
  currentPad: PADPoint | undefined | null,
) {
  ctx.fillStyle = BG_COLOR;
  roundRect(ctx, x, y, w, h, 8);
  ctx.fill();
  ctx.strokeStyle = BORDER_COLOR;
  ctx.lineWidth = 1;
  roundRect(ctx, x, y, w, h, 8);
  ctx.stroke();

  if (snapshots.length < 2) return;

  const padding = { top: 12, bottom: 18, left: 28, right: 8 };
  const pw = w - padding.left - padding.right;
  const ph = h - padding.top - padding.bottom;
  const tMin = snapshots[0].timestamp;
  const tMax = snapshots[snapshots.length - 1].timestamp;
  const tRange = tMax - tMin || 1;

  const toX = (t: number) => x + padding.left + ((t - tMin) / tRange) * pw;
  const toY = (v: number) => y + padding.top + ph / 2 - v * (ph / 2 - 4);

  // Y labels
  ctx.fillStyle = LABEL_COLOR;
  ctx.font = '8px sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText('+1', x + padding.left - 4, y + padding.top + 8);
  ctx.fillText(' 0', x + padding.left - 4, y + padding.top + ph / 2 + 3);
  ctx.fillText('-1', x + padding.left - 4, y + padding.top + ph - 2);

  // Zero line
  const zeroY = y + padding.top + ph / 2;
  ctx.strokeStyle = GRID_COLOR;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x + padding.left, zeroY);
  ctx.lineTo(x + padding.left + pw, zeroY);
  ctx.stroke();

  // Three lines
  const lines: [string, keyof PADPoint][] = [['#FF6B9D', 'P'], ['#64B8E0', 'A'], ['#78C878', 'D']];
  for (const [color, dim] of lines) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < snapshots.length; i++) {
      const px = toX(snapshots[i].timestamp);
      const py = toY(snapshots[i].pad[dim]);
      if (i === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.stroke();
  }

  // Legend
  ctx.font = '9px sans-serif';
  const legendY = y + h - 4;
  ctx.textAlign = 'left';
  ctx.fillStyle = '#FF6B9D'; ctx.fillText('P 愉悦', x + padding.left, legendY);
  ctx.fillStyle = '#64B8E0'; ctx.fillText('A 唤醒', x + padding.left + 48, legendY);
  ctx.fillStyle = '#78C878'; ctx.fillText('D 支配', x + padding.left + 96, legendY);

  // Title
  ctx.fillStyle = 'rgba(139, 122, 147, 0.6)';
  ctx.font = '9px sans-serif';
  ctx.fillText('时间轴', x + 6, y + 10);
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.arcTo(x + w, y, x + w, y + r, r);
  ctx.lineTo(x + w, y + h - r);
  ctx.arcTo(x + w, y + h, x + w - r, y + h, r);
  ctx.lineTo(x + r, y + h);
  ctx.arcTo(x, y + h, x, y + h - r, r);
  ctx.lineTo(x, y + r);
  ctx.arcTo(x, y, x + r, y, r);
  ctx.closePath();
}
