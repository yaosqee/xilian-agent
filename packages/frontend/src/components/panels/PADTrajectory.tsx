/**
 * PADTrajectory — Canvas 2D PAD 三面投影轨迹 (light theme)
 *
 * 布局：
 *   上半部：P-A 和 P-D 两个散点轨迹图（并排）
 *   下半部：P / A / D 三个独立的时序折线图（纵向堆叠，含 HH:MM 时间标签）
 */
import React, { useRef, useEffect } from 'react';
import type { PADSnapshot, PADPoint } from '../../types/emotion';

interface Props {
  snapshots: PADSnapshot[];
  current?: PADPoint | null;
  width?: number;
  height?: number;
}

const COLORS = {
  P: '#FF6B9D',
  A: '#64B8E0',
  D: '#78C878',
  currentDot: '#FF6B9D',
  grid: 'rgba(180, 160, 200, 0.2)',
  label: '#8B7A93',
  bg: 'rgba(200, 180, 210, 0.06)',
  border: 'rgba(200, 180, 210, 0.15)',
};

export const PADTrajectory: React.FC<Props> = ({ snapshots, current, width = 320, height = 480 }) => {
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

    const margin = { top: 8, left: 28, right: 10, bottom: 4 };
    const scatterH = 180;  // 散点图高度
    const timelineAreaTop = scatterH + 16;
    const miniTimelineH = 68;  // 每个小时间轴的高度
    const timelineAreaH = miniTimelineH * 3 + 8;
    const totalH = timelineAreaTop + timelineAreaH + margin.bottom;

    // 重置 canvas 实际高度
    canvas.height = totalH * dpr;
    ctx.scale(dpr, dpr);

    const pw = (width - margin.left - margin.right - 14) / 2;
    const ph = scatterH - margin.top;

    const latestPad = current || snapshots[snapshots.length - 1]?.pad;

    // ── 上半部：散点图 ──
    drawScatter(ctx, margin.left, margin.top, pw, ph, snapshots, latestPad, 'P', 'A', '愉悦度', '唤醒度', COLORS.P, COLORS.A);
    drawScatter(ctx, margin.left + pw + 14, margin.top, pw, ph, snapshots, latestPad, 'P', 'D', '愉悦度', '支配度', COLORS.P, COLORS.D);

    // ── 下半部：三个独立时间轴 ──
    const dims: [('P' | 'A' | 'D'), string, string][] = [
      ['P', '愉悦度', COLORS.P],
      ['A', '唤醒度', COLORS.A],
      ['D', '支配度', COLORS.D],
    ];
    for (let i = 0; i < dims.length; i++) {
      const [dim, label, color] = dims[i];
      drawMiniTimeline(
        ctx,
        margin.left,
        timelineAreaTop + i * (miniTimelineH + 4),
        width - margin.left - margin.right,
        miniTimelineH,
        snapshots,
        latestPad,
        dim,
        label,
        color,
      );
    }
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

// ── 散点图（P-A 或 P-D）──────────────────────────────

function drawScatter(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number,
  snapshots: PADSnapshot[],
  currentPad: PADPoint | undefined | null,
  dimX: 'P' | 'A' | 'D', dimY: 'P' | 'A' | 'D',
  labelX: string, labelY: string,
  dotColor: string, /* unused kept for signature */ _dotColorB?: string,
) {
  const cx = x + w / 2;
  const cy = y + h / 2;

  // Background
  ctx.fillStyle = COLORS.bg;
  roundRect(ctx, x, y, w, h, 8);
  ctx.fill();
  ctx.strokeStyle = COLORS.border;
  ctx.lineWidth = 1;
  roundRect(ctx, x, y, w, h, 8);
  ctx.stroke();

  // Axes
  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, cy); ctx.lineTo(x + w, cy);
  ctx.moveTo(cx, y); ctx.lineTo(cx, y + h);
  ctx.stroke();

  // Labels
  ctx.fillStyle = COLORS.label;
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
    ctx.fillText(v.toFixed(1), cx + v * (w / 2 - 16), cy + 12);
    ctx.fillText(v.toFixed(1), cx - 20, cy - v * (h / 2 - 14) + 3);
  }

  if (snapshots.length < 2) return;

  const scaleX = (w / 2 - 16) / 1.05;
  const scaleY = (h / 2 - 14) / 1.05;

  // Trail dots (lighter = older)
  for (let i = 0; i < snapshots.length; i++) {
    const ratio = i / (snapshots.length - 1 || 1);
    ctx.fillStyle = `rgba(255, 158, 187, ${0.12 + ratio * 0.45})`;
    ctx.beginPath();
    ctx.arc(
      cx + snapshots[i].pad[dimX] * scaleX,
      cy - snapshots[i].pad[dimY] * scaleY,
      i === snapshots.length - 1 ? 3 : 1.8, 0, Math.PI * 2,
    );
    ctx.fill();
  }

  // Connecting line (gradient from old to new)
  ctx.lineWidth = 1.2;
  for (let i = 1; i < snapshots.length; i++) {
    const ratio = (i - 1) / (snapshots.length - 1 || 1);
    ctx.strokeStyle = `rgba(255, 158, 187, ${0.2 + ratio * 0.5})`;
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

  // Direction arrows every N points
  const arrowInterval = Math.max(3, Math.floor(snapshots.length / 8));
  for (let i = arrowInterval; i < snapshots.length; i += arrowInterval) {
    const px = cx + snapshots[i].pad[dimX] * scaleX;
    const py = cy - snapshots[i].pad[dimY] * scaleY;
    const angle = Math.atan2(
      -(snapshots[i].pad[dimY] - snapshots[i - 1].pad[dimY]) * scaleY,
      (snapshots[i].pad[dimX] - snapshots[i - 1].pad[dimX]) * scaleX,
    );
    ctx.fillStyle = 'rgba(255, 158, 187, 0.6)';
    ctx.beginPath();
    ctx.moveTo(px + Math.cos(angle) * 4, py + Math.sin(angle) * 4);
    ctx.lineTo(px + Math.cos(angle + 2.5) * 6, py + Math.sin(angle + 2.5) * 6);
    ctx.lineTo(px + Math.cos(angle - 2.5) * 6, py + Math.sin(angle - 2.5) * 6);
    ctx.closePath();
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
    ctx.fillStyle = COLORS.currentDot;
    ctx.beginPath();
    ctx.arc(cpx, cpy, 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // Title
  ctx.fillStyle = 'rgba(139, 122, 147, 0.5)';
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(`${labelX} - ${labelY}`, x + 6, y + 12);
}

// ── 单个维度的时间轴 ──────────────────────────────

function drawMiniTimeline(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number,
  snapshots: PADSnapshot[],
  currentPad: PADPoint | undefined | null,
  dim: 'P' | 'A' | 'D',
  label: string,
  color: string,
) {
  // Background
  ctx.fillStyle = COLORS.bg;
  roundRect(ctx, x, y, w, h, 6);
  ctx.fill();
  ctx.strokeStyle = COLORS.border;
  ctx.lineWidth = 0.5;
  roundRect(ctx, x, y, w, h, 6);
  ctx.stroke();

  const padL = 26, padR = 6, padT = 14, padB = 14;
  const pw = w - padL - padR;
  const ph = h - padT - padB;

  if (snapshots.length < 2) return;

  const tMin = snapshots[0].timestamp;
  const tMax = snapshots[snapshots.length - 1].timestamp;
  const tRange = (tMax - tMin) || 1;

  const toX = (t: number) => x + padL + ((t - tMin) / tRange) * pw;
  const toY = (v: number) => y + padT + ph / 2 - v * (ph / 2 - 3);

  // Zero line
  const zeroY = y + padT + ph / 2;
  ctx.strokeStyle = COLORS.grid;
  ctx.lineWidth = 0.5;
  ctx.beginPath();
  ctx.moveTo(x + padL, zeroY);
  ctx.lineTo(x + padL + pw, zeroY);
  ctx.stroke();

  // Dimension label (left)
  ctx.fillStyle = color;
  ctx.font = 'bold 9px sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText(label, x + padL - 4, y + padT + 8);

  // Y ticks
  ctx.fillStyle = COLORS.label;
  ctx.font = '7px sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText('+1', x + padL - 3, y + padT + 8);
  ctx.fillText(' 0', x + padL - 3, zeroY + 3);
  ctx.fillText('-1', x + padL - 3, y + padT + ph);

  // Time labels (bottom, ~4 labels)
  const labelCount = Math.min(4, Math.floor(pw / 40));
  ctx.fillStyle = COLORS.label;
  ctx.font = '7px sans-serif';
  ctx.textAlign = 'center';
  for (let i = 0; i < labelCount; i++) {
    const frac = i / (labelCount - 1 || 1);
    const ts = tMin + frac * tRange;
    const date = new Date(ts * 1000);
    const text = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
    ctx.fillText(text, toX(ts), y + h - 3);
  }

  // Line
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.3;
  ctx.beginPath();
  for (let i = 0; i < snapshots.length; i++) {
    const px = toX(snapshots[i].timestamp);
    const py = toY(snapshots[i].pad[dim]);
    if (i === 0) ctx.moveTo(px, py);
    else ctx.lineTo(px, py);
  }
  ctx.stroke();

  // Dot at latest point
  if (snapshots.length > 0) {
    const last = snapshots[snapshots.length - 1];
    const lx = toX(last.timestamp);
    const ly = toY(last.pad[dim]);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(lx, ly, 2.5, 0, Math.PI * 2);
    ctx.fill();
  }

  // Current (real-time) dot
  if (currentPad) {
    // Place at the right edge (now)
    const cx = x + padL + pw;
    const cy = toY(currentPad[dim]);
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(cx - 2, cy, 3, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1;
    ctx.stroke();
  }
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
