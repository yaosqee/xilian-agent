export interface StickerData {
  id: string;
  file: string;
}

export interface ToolStatus {
  phase: 'call' | 'result';
  name: string;
  ok?: boolean;
  summary?: string;
  error?: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  sticker?: StickerData;       // 表情包（助手消息可附带）
  images?: string[];            // 图片 URL（用户消息可附带，单图）
  toolStatus?: ToolStatus;      // 工具执行状态（SSE tool_call / tool_result）
  timestamp: number;
}

export interface ChatState {
  messages: ChatMessage[];
  isLoading: boolean;
  error: string | null;
}
