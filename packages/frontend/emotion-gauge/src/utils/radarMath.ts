/** 雷达图数学常量 */
export const AXIS_COUNT = 11;
export const ANGLE_STEP = (2 * Math.PI) / AXIS_COUNT;
export const START_ANGLE = -Math.PI / 2; // 第一轴在正上方

/**
 * 给定中心、半径、值和轴索引，计算数据点在画布上的坐标。
 */
export function getPoint(
  centerX: number,
  centerY: number,
  radius: number,
  value: number, // 0..1
  axisIndex: number,
): { x: number; y: number } {
  const angle = START_ANGLE + axisIndex * ANGLE_STEP;
  const r = radius * value;
  return {
    x: centerX + r * Math.cos(angle),
    y: centerY + r * Math.sin(angle),
  };
}

/**
 * 给定中心、半径和轴索引，计算轴线末端坐标（用于画标签）。
 */
export function getAxisEnd(
  centerX: number,
  centerY: number,
  radius: number,
  axisIndex: number,
  labelOffset = 0,
): { x: number; y: number } {
  const angle = START_ANGLE + axisIndex * ANGLE_STEP;
  const r = radius + labelOffset;
  return {
    x: centerX + r * Math.cos(angle),
    y: centerY + r * Math.sin(angle),
  };
}
