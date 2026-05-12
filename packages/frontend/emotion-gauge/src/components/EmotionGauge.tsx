import { useRef, useEffect, useCallback } from "react";
import {
  AXIS_COUNT,
  getPoint,
  getAxisEnd,
} from "../utils/radarMath";
import {
  EMOTION_DIMENSIONS,
  EMOTION_COLORS,
  type EmotionData,
  type EmotionName,
} from "../types/emotion";

const GRID_STEPS = [0.2, 0.4, 0.6, 0.8, 1.0];
const GRID_COLOR = "rgba(255,255,255,0.08)";
const AXIS_COLOR = "rgba(255,255,255,0.15)";
const LABEL_COLOR = "rgba(255,255,255,0.6)";
const LINE_WIDTH = 2;
const POINT_RADIUS = 4;

interface Props {
  data: EmotionData;
}

export default function EmotionGauge({ data }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);
  const currentDims = useRef<Record<EmotionName, number>>(data.dimensions);

  // 动画过渡
  const animateTo = useCallback((target: Record<EmotionName, number>) => {
    const start = { ...currentDims.current };
    const startTime = performance.now();
    const DURATION = 600;

    function step(now: number) {
      const elapsed = now - startTime;
      const t = Math.min(elapsed / DURATION, 1.0);
      // ease-out cubic
      const ease = 1 - Math.pow(1 - t, 3);

      const dims = {} as Record<EmotionName, number>;
      for (const name of EMOTION_DIMENSIONS) {
        dims[name] = start[name] + (target[name] - start[name]) * ease;
      }
      currentDims.current = dims;
      draw(dims);

      if (t < 1) {
        requestAnimationFrame(step);
      }
    }

    requestAnimationFrame(step);
  }, []);

  // 绘制函数
  const draw = useCallback(
    (dims: Record<EmotionName, number>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;

      const w = canvas.width;
      const h = canvas.height;
      const cx = w / 2;
      const cy = h / 2;
      const radius = Math.min(cx, cy) * 0.65;
      const dpr = window.devicePixelRatio || 1;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

      // 清空
      ctx.clearRect(0, 0, w, h);

      // ── 背景网格 ──
      for (const step of GRID_STEPS) {
        ctx.beginPath();
        for (let i = 0; i < AXIS_COUNT; i++) {
          const p = getPoint(cx, cy, radius, step, i);
          i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
        }
        ctx.closePath();
        ctx.strokeStyle = step === 1.0 ? "rgba(255,255,255,0.18)" : GRID_COLOR;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // ── 轴线 ──
      for (let i = 0; i < AXIS_COUNT; i++) {
        const { x, y } = getAxisEnd(cx, cy, radius, i);
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(x, y);
        ctx.strokeStyle = AXIS_COLOR;
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // ── 数据区域 ──
      const primary = data.primary_emotion;
      const fillColor = EMOTION_COLORS[primary] + "40"; // ~25% alpha

      ctx.beginPath();
      for (let i = 0; i < AXIS_COUNT; i++) {
        const name = EMOTION_DIMENSIONS[i];
        const val = dims[name] ?? 0;
        const p = getPoint(cx, cy, radius, val, i);
        i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y);
      }
      ctx.closePath();
      ctx.fillStyle = fillColor;
      ctx.fill();
      ctx.strokeStyle = EMOTION_COLORS[primary];
      ctx.lineWidth = LINE_WIDTH;
      ctx.stroke();

      // ── 数据点 ──
      for (let i = 0; i < AXIS_COUNT; i++) {
        const name = EMOTION_DIMENSIONS[i];
        const val = dims[name] ?? 0;
        const p = getPoint(cx, cy, radius, val, i);
        ctx.beginPath();
        ctx.arc(p.x, p.y, POINT_RADIUS, 0, Math.PI * 2);
        ctx.fillStyle = EMOTION_COLORS[primary];
        ctx.fill();
      }

      // ── 轴标签 ──
      ctx.font = "12px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";

      for (let i = 0; i < AXIS_COUNT; i++) {
        const { x, y } = getAxisEnd(cx, cy, radius, i, 22);
        ctx.fillStyle = LABEL_COLOR;
        ctx.fillText(EMOTION_DIMENSIONS[i], x, y);
      }
    },
    [data.primary_emotion],
  );

  // 首次绘制 + 数据变化时动画
  useEffect(() => {
    animateTo(data.dimensions);
  }, [data, animateTo]);

  // ResizeObserver：canvas 尺寸自适应
  useEffect(() => {
    const wrapper = wrapperRef.current;
    const canvas = canvasRef.current;
    if (!wrapper || !canvas) return;

    const resize = () => {
      const rect = wrapper.getBoundingClientRect();
      const size = Math.min(rect.width, 500);
      const dpr = window.devicePixelRatio || 1;
      canvas.width = size * dpr;
      canvas.height = size * dpr;
      canvas.style.width = `${size}px`;
      canvas.style.height = `${size}px`;
      draw(currentDims.current);
    };

    const observer = new ResizeObserver(resize);
    observer.observe(wrapper);
    resize();

    return () => observer.disconnect();
  }, [draw]);

  return (
    <div
      ref={wrapperRef}
      style={{ width: "100%", aspectRatio: "1", maxWidth: 500, margin: "0 auto" }}
    >
      <canvas
        ref={canvasRef}
        style={{ display: "block", width: "100%", height: "100%" }}
      />
    </div>
  );
}
