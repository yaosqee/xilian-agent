import type { ToolStatus } from '../types/chat';

const BASE = '/api';

export async function postChat(message: string, images?: string[]): Promise<{ reply: string; sticker?: { id: string; file: string } | null }> {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, images: images || [], user_id: 'hezi', session_id: 'web' }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

export function postChatStream(
  message: string,
  images: string[],
  onToken: (token: string) => void,
  onSticker: (sticker: { id: string; file: string }) => void,
  onDone: () => void,
  onError: (err: Error) => void,
  onToolStatus?: (status: ToolStatus) => void,
): AbortController {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(new Error('SSE stream timeout')), 120_000); // 2min
  fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, images: images || [], user_id: 'hezi', session_id: 'web' }),
    signal: controller.signal,
  })
    .then(async (res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const reader = res.body?.getReader();
      if (!reader) { onDone(); return; }
      const decoder = new TextDecoder();
      let buffer = '';
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // Split by SSE message boundary (\n\n), keep incomplete message in buffer
        const messages = buffer.split('\n\n');
        buffer = messages.pop() || '';
        for (const msg of messages) {
          if (!msg.trim()) continue;
          let eventType = '';
          for (const line of msg.split('\n')) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              const data = line.slice(6);
              if (eventType === 'done' || data === '[DONE]') {
                clearTimeout(timeoutId);
                onDone();
                return;
              }
              if (eventType === 'sticker') {
                try {
                  const sticker = JSON.parse(data);
                  onSticker(sticker);
                } catch { /* ignore malformed sticker data */ }
              } else if (eventType === 'tool_call') {
                try {
                  const payload = JSON.parse(data) as { calls?: Array<{ name?: string }> };
                  for (const call of payload.calls || []) {
                    if (call.name) onToolStatus?.({ phase: 'call', name: call.name });
                  }
                } catch { /* ignore malformed tool data */ }
              } else if (eventType === 'tool_result') {
                try {
                  const payload = JSON.parse(data) as {
                    results?: Array<{
                      name?: string; ok?: boolean; needs_confirmation?: boolean;
                      summary?: string; error?: string;
                    }>;
                  };
                  for (const result of payload.results || []) {
                    if (!result.name) continue;
                    onToolStatus?.({
                      phase: 'result',
                      name: result.name,
                      ok: result.ok !== false,
                      needsConfirmation: result.needs_confirmation === true,
                      summary: result.summary || '',
                      error: result.error || '',
                    });
                  }
                } catch { /* ignore malformed tool data */ }
              } else if (eventType === 'token') {
                onToken(data.replace(/\\n/g, '\n'));
              }
            }
          }
        }
      }
      clearTimeout(timeoutId);
      onDone();
    })
    .catch((err) => {
      clearTimeout(timeoutId);
      if (err.name !== 'AbortError') onError(err);
    });
  return controller;
}

export async function fetchEmotion(): Promise<any> {
  const res = await fetch(`${BASE}/emotion`);
  return res.json();
}

export async function fetchEmotionHistory(limit = 50): Promise<any> {
  const res = await fetch(`${BASE}/emotion/history?limit=${limit}`);
  return res.json();
}

/** 阶段4: 获取 PAD 轨迹历史（fetchEmotionHistory 的语义别名） */
export const fetchPADHistory = fetchEmotionHistory;

/** 阶段4: 获取情绪统计 */
export async function fetchEmotionStats(days = 7): Promise<any> {
  const res = await fetch(`${BASE}/emotion/stats?days=${days}`);
  return res.json();
}

export async function fetchEncodingStatus(): Promise<any> {
  const res = await fetch(`${BASE}/encoding-status`);
  return res.json();
}

export async function fetchStatus(): Promise<any> {
  const res = await fetch(`${BASE}/status`);
  return res.json();
}

export async function resetSession(): Promise<any> {
  const res = await fetch(`${BASE}/session/reset`, { method: 'POST' });
  return res.json();
}

/** 阶段5: 获取最近记忆卡片 */
export async function fetchMemoriesRecent(limit = 20): Promise<any> {
  const res = await fetch(`${BASE}/memories/recent?limit=${limit}`);
  return res.json();
}

/** 阶段5: 获取自传体 */
export async function fetchAutobiography(date?: string): Promise<any> {
  const q = date ? `?date=${date}` : '';
  const res = await fetch(`${BASE}/autobiography${q}`);
  return res.json();
}

/** 阶段5: 获取自传体目录 */
export async function fetchAutobiographyList(limit = 30): Promise<any> {
  const res = await fetch(`${BASE}/autobiography/list?limit=${limit}`);
  return res.json();
}

/** 对话历史分页 */
export interface ConversationHistoryItem {
  id: number;
  timestamp: number;
  user_message: string;
  assistant_reply: string;
  images: string[];
}

export async function fetchConversationHistory(
  beforeId?: number, limit = 10,
): Promise<{
  items: ConversationHistoryItem[];
  total: number;
  has_more: boolean;
  oldest_id: number | null;
}> {
  const params = new URLSearchParams();
  if (beforeId) params.set('before_id', String(beforeId));
  params.set('limit', String(limit));
  const res = await fetch(`${BASE}/conversation/history?${params}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** 阶段5: 获取时间问候 */
export async function fetchGreeting(): Promise<any> {
  const res = await fetch(`${BASE}/greeting`);
  return res.json();
}

/** 阶段6: 获取自主行为状态 */
export async function fetchAutonomyStatus(): Promise<any> {
  const res = await fetch(`${BASE}/autonomy/status`);
  return res.json();
}

/** 阶段6: 获取待展示的主动问候 */
export async function fetchPendingGreeting(): Promise<any> {
  const res = await fetch(`${BASE}/autonomy/pending-greeting`);
  return res.json();
}

/** 阶段6: 确认收到问候 */
export async function ackGreeting(id: string): Promise<any> {
  const res = await fetch(`${BASE}/autonomy/ack-greeting`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id }),
  });
  return res.json();
}

/** 阶段6: 暂停自主行为 */
export async function pauseAutonomy(): Promise<any> {
  const res = await fetch(`${BASE}/autonomy/pause`, { method: 'POST' });
  return res.json();
}

/** 阶段6: 恢复自主行为 */
export async function resumeAutonomy(): Promise<any> {
  const res = await fetch(`${BASE}/autonomy/resume`, { method: 'POST' });
  return res.json();
}

/** 阶段6: 更新自主行为配置 */
export async function updateAutonomySettings(patch: Record<string, any>): Promise<any> {
  const res = await fetch(`${BASE}/autonomy/settings`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  return res.json();
}

/** 获取当前背景图片 URL */
export async function fetchBackground(): Promise<{ filename: string; url: string }> {
  const res = await fetch(`${BASE}/background/current`);
  if (!res.ok) return { filename: 'xilian.png', url: '/photo/xilian.png' };
  return res.json();
}

/** 上传聊天图片 */
export async function uploadImage(file: File): Promise<{ id: string; url: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/upload`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

/** 获取可用表情包列表 */
export async function fetchStickers(): Promise<{ stickers: Array<{ id: string; category: string; emotion_tags: string[]; description: string; file: string }>; version: number }> {
  const res = await fetch(`${BASE}/stickers`);
  return res.json();
}

/** 上传自定义背景图片 */
export async function uploadBackground(file: File): Promise<{ filename: string; url: string }> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${BASE}/background/upload`, {
    method: 'POST',
    body: form,
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data;
}

/** 获取好感度状态 */
export async function fetchAffection(): Promise<{
  score: number; level: number; level_label: string;
  total_conversations: number; updated_at: number;
  error?: string;
}> {
  const res = await fetch(`${BASE}/affection`);
  return res.json();
}

/** 获取用户分层画像（L0 核心 + L1 阶段） */
export async function fetchUserPortrait(): Promise<{
  portrait: string | null; version: number;
  updated_at: number | null; changes: string;
  stable_traits?: string;
  phase_portrait?: string; phase_version?: number;
  phase_updated_at?: number; phase_changes?: string;
  active_topics?: string[]; faded_topics?: string[];
  error?: string;
}> {
  const res = await fetch(`${BASE}/user/portrait`);
  return res.json();
}

// ═══════════════════════════════════════════════
// Model config API (V3.4: multi-provider)
// ═══════════════════════════════════════════════

export interface ProviderInfo {
  id: string;
  name: string;
  models: ModelInfo[];
}

export interface ModelInfo {
  id: string;
  name: string;
  cost_per_1k_in: number;
  cost_per_1k_out: number;
  supports_tools: boolean;
  supports_thinking?: boolean;
}

export interface TierModelConfig {
  provider: string;
  model: string;
  temperature?: number;
  max_tokens?: number;
}

export interface RoutingProviderInfo {
  base_url: string;
  api_key_env: string;
}

export interface RoutingModelInfo {
  provider: string;
  capabilities: string[];
  context_window: number;
  max_output_tokens: number;
  cost_per_1k_in: number;
  cost_per_1k_out: number;
  known_failures: string[];
}

export interface RoutingProfileInfo {
  model: string;
  fallbacks: string[];
  temperature: number;
  max_tokens: number;
  requires: string[];
}

export interface RoutingEmbeddingInfo {
  provider: string;
  model: string;
  dimensions: number;
  base_url: string;
  api_key_env: string;
}

export interface EffectiveRoute {
  task_type?: string;
  profile?: string;
  model?: string;
  provider?: string;
  temperature?: number;
  max_tokens?: number;
  fallbacks?: string[];
  requires?: string[];
  source?: string;
  capability_fallback?: boolean;
  error?: string;
}

export interface RoutingConfigData {
  version: number;
  source_path: string;
  providers: Record<string, RoutingProviderInfo>;
  models: Record<string, RoutingModelInfo>;
  profiles: Record<string, RoutingProfileInfo>;
  embedding: RoutingEmbeddingInfo | null;
  effective: Record<string, EffectiveRoute>;
}

export interface ModelConfigResponse {
  tiers: Record<string, TierModelConfig>;
  overrides: Record<string, TierModelConfig>;
  embed: { provider: string; model: string; base_url?: string } | null;
  adapters: string[];
  routing_v2?: boolean;
  routing?: RoutingConfigData | null;
}

export interface ModelConfigPatch {
  tiers?: Record<string, { provider: string; model: string; temperature?: number; max_tokens?: number }>;
  api_keys?: Record<string, string>;
  base_urls?: Record<string, string>;
}

/** 获取可用供应商和模型列表 */
export async function fetchModelProviders(): Promise<{ providers: ProviderInfo[] }> {
  const res = await fetch(`${BASE}/models/providers`);
  return res.json();
}

/** 获取当前模型配置 */
export async function fetchModelConfig(): Promise<ModelConfigResponse> {
  const res = await fetch(`${BASE}/models/config`);
  return res.json();
}

/** 更新模型配置 */
export async function saveModelConfig(patch: ModelConfigPatch): Promise<{ status: string; errors?: string[] }> {
  const res = await fetch(`${BASE}/models/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });
  return res.json();
}

/** 验证 API Key */
export async function validateApiKey(provider: string, apiKey: string): Promise<{ valid: boolean; error?: string }> {
  const res = await fetch(`${BASE}/models/validate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ provider, api_key: apiKey }),
  });
  return res.json();
}
