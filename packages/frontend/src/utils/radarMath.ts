export const AXIS_COUNT = 11;
export const ANGLE_STEP = (2 * Math.PI) / AXIS_COUNT;
export const START_ANGLE = -Math.PI / 2;

export function getPoint(
  centerX: number,
  centerY: number,
  radius: number,
  value: number,
  axisIndex: number,
): { x: number; y: number } {
  const angle = START_ANGLE + axisIndex * ANGLE_STEP;
  const r = radius * value;
  return {
    x: centerX + r * Math.cos(angle),
    y: centerY + r * Math.sin(angle),
  };
}

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
