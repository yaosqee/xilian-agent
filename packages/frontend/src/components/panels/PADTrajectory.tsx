/**
 * PADTrajectory — Canvas 2D 三面投影 PAD 轨迹
 *
 * 阶段 4 新增。三视图并排：
 *   左上 P-A (Pleasure vs Arousal)    右上 P-D (Pleasure vs Dominance)
 *   底部时间轴 (P/A/D 随时间变化)
 *
 * 颜色：旧→浅灰(#555)，新→品牌粉(#FFB3B3)，当前点→亮粉(#FF6B9D)
 */
import React, { useRef, useEffect } from 'react';
import type { PADSnapshot, PADPoint } from '../../types/emotion';

interface Props {
  snapshots: PADSnapshot[];
  current?: PADPoint | null;
  width?: number;
  height?: number;
}

const PA_COLOR = '#FFB3B3';    // P-A 象限点色
const PD_COLOR = '#98FB98';    // P-D 象限点色
const LINE_OLD = '#555555';    // 旧轨迹线
const LINE_NEW = '#FFB3B3';    // 新轨迹线
const CURRENT_DOT = '#FF6B9D'; // 当前点
const AXIS_COLOR = 'rgba(255,255,255,0.15)';
const LABEL_COLOR = 'rgba(255,255,255,0.5)';
const BG_COLOR = 'rgba(255,255,255,0.02)';

export const PADTrajectory: React.FC<Props> = ({
  snapshots,
  current,
  width = 600,
  height = 420,
}) => {
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

    // 清空
    ctx.clearRect(0, 0, width, height);

    const topH = 270;
    const bottomH = height - topH - 20;
    const margin = { top: 25, left: 35, right: 15, bottom: 20 };
    const pw = (width - margin.left - margin.right - 20) / 2; // 每个小图画布宽度
    const ph = topH - margin.top - margin.bottom;

    const pad = current || snapshots[snapshots.length - 1]?.pad;

    // ── 绘制 P-A (Pleasure vs Arousal) ──
    drawPADPlot(ctx, margin.left, margin.top, pw, ph,
      snapshots, pad, 'P', 'A', '愉悦度', '唤醒度', PA_COLOR);

    // ── 绘制 P-D (Pleasure vs Dominance) ──
    const pdX = margin.left + pw + 20;
    drawPADPlot(ctx, pdX, margin.top, pw, ph,
      snapshots, pad, 'P', 'D', '愉悦度', '支配度', PD_COLOR);

    // ── 底部时间轴 ──
    const timeY = topH + 15;
    drawTimeline(ctx, margin.left, timeY, width - margin.left - margin.right, bottomH,
      snapshots, pad);

  }, [snapshots, current, width, height]);

  if (snapshots.length === 0) {
    return (
      <p style={{ color: 'rgba(255,255,255,0.3)', fontSize: 13, textAlign: 'center', padding: 40 }}>
        还没有 PAD 轨迹数据<br />
        多说几句话，昔涟的情绪涟漪就会出现~
      </p>
    );
  }

  return (
    <canvas
      ref={canvasRef}
      style={{ width, height, borderRadius: 12, background: BG_COLOR }}
    />
  );
};

/** 绘制单幅 PAD 象限图 */
function drawPADPlot(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number,
  snapshots: PADSnapshot[],
  currentPad: PADPoint | undefined | null,
  dimX: 'P' | 'A' | 'D',
  dimY: 'P' | 'A' | 'D',
  labelX: string,
  labelY: string,
  dotColor: string,
) {
  const cx = x + w / 2;
  const cy = y + h / 2;

  // 背景
  ctx.fillStyle = 'rgba(0,0,0,0.15)';
  ctx.fillRect(x, y, w, h);

  // 坐标轴
  ctx.strokeStyle = AXIS_COLOR;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, cy); ctx.lineTo(x + w, cy); // 水平轴
  ctx.moveTo(cx, y); ctx.lineTo(cx, y + h); // 垂直轴
  ctx.stroke();

  // 轴标签
  ctx.fillStyle = LABEL_COLOR;
  ctx.font = '11px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText(labelX, x + w / 2, y + h - 2);
  ctx.save();
  ctx.translate(x + 8, y + h / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText(labelY, 0, 0);
  ctx.restore();

  // 刻度标签
  ctx.font = '9px sans-serif';
  for (const v of [-1, -0.5, 0, 0.5, 1]) {
    const px = cx + v * (w / 2 - 15);
    ctx.fillText(v.toFixed(1), px, cy + 14);
    const py = cy - v * (h / 2 - 15);
    ctx.fillText(v.toFixed(1), cx - 22, py + 3);
  }

  if (snapshots.length === 0) return;

  // 轨迹连线（渐变）
  const scaleX = (w / 2 - 15) / 1.05; // pad ∈ [-1, 1]，留边距
  const scaleY = (h / 2 - 15) / 1.05;

  for (let i = 1; i < snapshots.length; i++) {
    const ratio = i / snapshots.length;
    const r = Math.round(85 + ratio * 170);
    const g = Math.round(85 + ratio * 100);
    const b = Math.round(85 + ratio * 100);
    ctx.strokeStyle = `rgb(${r},${g},${b})`;
    ctx.lineWidth = 1;
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

  // 轨迹点
  for (let i = 0; i < snapshots.length; i++) {
    const ratio = i / snapshots.length;
    const alpha = 0.2 + ratio * 0.6;
    ctx.fillStyle = `${dotColor.replace(')', `,${alpha})`).replace('rgb', 'rgba')}`;
    ctx.beginPath();
    ctx.arc(
      cx + snapshots[i].pad[dimX] * scaleX,
      cy - snapshots[i].pad[dimY] * scaleY,
      2.5, 0, Math.PI * 2,
    );
    ctx.fill();
  }

  // 当前点（大圆 + 发光）
  if (currentPad) {
    const cpx = cx + currentPad[dimX] * scaleX;
    const cpy = cy - currentPad[dimY] * scaleY;

    ctx.fillStyle = 'rgba(255,107,157,0.15)';
    ctx.beginPath();
    ctx.arc(cpx, cpy, 8, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = CURRENT_DOT;
    ctx.beginPath();
    ctx.arc(cpx, cpy, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  // 标题
  ctx.fillStyle = 'rgba(255,255,255,0.4)';
  ctx.font = '10px sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText(`${labelX} - ${labelY}`, x + 4, y + 12);
}

/** 底部时间轴折线图 */
function drawTimeline(
  ctx: CanvasRenderingContext2D,
  x: number, y: number, w: number, h: number,
  snapshots: PADSnapshot[],
  currentPad: PADPoint | undefined | null,
) {
  // 背景
  ctx.fillStyle = 'rgba(0,0,0,0.15)';
  ctx.fillRect(x, y, w, h);

  if (snapshots.length < 2) return;

  const padding = { top: 15, bottom: 20, left: 30, right: 10 };
  const pw = w - padding.left - padding.right;
  const ph = h - padding.top - padding.bottom;

  const tMin = snapshots[0].timestamp;
  const tMax = snapshots[snapshots.length - 1].timestamp;
  const tRange = tMax - tMin || 1;

  const toX = (t: number) => padding.left + ((t - tMin) / tRange) * pw;
  const toY = (v: number) => y + padding.top + ph / 2 - v * (ph / 2 - 5);

  // Y 轴标签
  ctx.fillStyle = LABEL_COLOR;
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'right';
  ctx.fillText('+1', padding.left - 4, y + padding.top + 8);
  ctx.fillText(' 0', padding.left - 4, y + padding.top + ph / 2 + 3);
  ctx.fillText('-1', padding.left - 4, y + padding.top + ph - 2);

  // 零线
  const zeroY = y + padding.top + ph / 2;
  ctx.strokeStyle = AXIS_COLOR;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding.left, zeroY);
  ctx.lineTo(padding.left + pw, zeroY);
  ctx.stroke();

  // 三条折线：P(粉) A(青) D(绿)
  const lines: [string, string, keyof PADPoint][] = [
    ['#FF6B9D', 'P', 'P'],
    ['#64D8FF', 'A', 'A'],
    ['#98FB98', 'D', 'D'],
  ];

  for (const [color, , dim] of lines) {
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

  // 图例
  ctx.font = '10px sans-serif';
  const legendY = y + h - 4;
  ctx.textAlign = 'left';
  ctx.fillStyle = '#FF6B9D'; ctx.fillText('P 愉悦', padding.left, legendY);
  ctx.fillStyle = '#64D8FF'; ctx.fillText('A 唤醒', padding.left + 55, legendY);
  ctx.fillStyle = '#98FB98'; ctx.fillText('D 支配', padding.left + 110, legendY);

  // 标题
  ctx.fillStyle = 'rgba(255,255,255,0.3)';
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'left';
  ctx.fillText('时间轴', x + 4, y + 10);
}
