/** 11 维情绪维度名 */
export const EMOTION_DIMENSIONS = [
  "喜悦", "悲伤", "愤怒", "焦虑", "平静",
  "期待", "疲惫", "孤独", "感激", "好奇", "恐惧",
] as const;

export type EmotionName = (typeof EMOTION_DIMENSIONS)[number];

/** 情绪数据（与后端 EmotionAnalyzer 输出对齐，阶段2；阶段4 被 PAD 替代） */
export interface EmotionData {
  primary_emotion: EmotionName;
  primary_intensity: number;
  dimensions: Record<EmotionName, number>;
  possible_cause: string;
  need: string;
  timestamp: number;
}

// ═══════════════════════════════════════════════════
// 阶段 4: PAD 三维情感空间
// ═══════════════════════════════════════════════════

/** PAD 三维坐标点 */
export interface PADPoint {
  P: number;  // Pleasure 愉悦度 [-1, 1]
  A: number;  // Arousal 唤醒度 [-1, 1]
  D: number;  // Dominance 支配度 [-1, 1]
}

/** 当前 PAD 情绪快照（GET /api/emotion） */
export interface PADEmotion {
  pad: PADPoint;
  primary_emotion: string;
  primary_intensity: number;
  dimensions: Record<string, number>;
  timestamp: number;
  since_last_update_seconds?: number;
}

/** PAD 轨迹历史快照（GET /api/emotion/history） */
export interface PADSnapshot {
  timestamp: number;
  pad: PADPoint;
  primary_emotion: string | null;
}

/** PAD 轨迹历史 API 响应 */
export interface PADHistoryResponse {
  snapshots: PADSnapshot[];
  stats: {
    avg_p?: number;
    avg_a?: number;
    avg_d?: number;
    dominant_emotion?: string | null;
  };
  count: number;
}

/** 11 维情绪 → 颜色映射 */
export const EMOTION_COLORS: Record<EmotionName, string> = {
  喜悦: "#FFD700",
  悲伤: "#6495ED",
  愤怒: "#FF6347",
  焦虑: "#FFA500",
  平静: "#98FB98",
  期待: "#DDA0DD",
  疲惫: "#A9A9A9",
  孤独: "#87CEEB",
  感激: "#FFB6C1",
  好奇: "#FFDAB9",
  恐惧: "#8B0000",
};
