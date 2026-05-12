import { AXIS_COUNT } from "./radarMath";
import type { EmotionData, EmotionName } from "../types/emotion";

/**
 * 生成一份随机模拟情绪数据。
 * 阶段 3 替换为 GET /api/emotion 真实数据。
 */
export function generateMockData(): EmotionData {
  const idx = Math.floor(Math.random() * EMOTIONS.length);
  const primary = EMOTIONS[idx];

  const dimensions: Record<EmotionName, number> = {} as Record<EmotionName, number>;
  for (let i = 0; i < AXIS_COUNT; i++) {
    const name = EMOTIONS[i];
    // 主情绪高分，其他随机低分
    dimensions[name] = name === primary
      ? 0.5 + Math.random() * 0.5
      : Math.random() * 0.35;
  }

  return {
    primary_emotion: primary,
    primary_intensity: dimensions[primary],
    dimensions,
    possible_cause: CAUSES[idx],
    need: NEEDS[idx],
    timestamp: Date.now(),
  };
}

const EMOTIONS: EmotionName[] = [
  "喜悦", "悲伤", "愤怒", "焦虑", "平静",
  "期待", "疲惫", "孤独", "感激", "好奇", "恐惧",
];

const CAUSES: string[] = [
  "收到好消息", "回忆往事", "被人误解",
  "明天要汇报", "刚泡了茶", "新计划",
  "连续工作", "人群散去", "被帮助了",
  "新知识", "看了恐怖片",
];

const NEEDS: string[] = [
  "分享快乐", "被理解", "发泄",
  "安慰", "独处", "向前看",
  "被看见", "陪伴", "表达",
  "探索", "安全感",
];
