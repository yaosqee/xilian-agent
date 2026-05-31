const BASE = '/api';

export async function postChat(message: string): Promise<string> {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, user_id: 'hezi' }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data.reply;
}

export function postChatStream(
  message: string,
  onToken: (token: string) => void,
  onDone: () => void,
  onError: (err: Error) => void,
): AbortController {
  const controller = new AbortController();
  fetch(`${BASE}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, user_id: 'hezi' }),
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
        // Process complete SSE events
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // keep incomplete line
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6);
            if (data === '[DONE]') { onDone(); return; }
            // Unescape newlines from SSE transport
            onToken(data.replace(/\\n/g, '\n'));
          }
        }
      }
      onDone();
    })
    .catch((err) => {
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

/** 阶段4: 获取 PAD 轨迹历史 */
export async function fetchPADHistory(limit = 100): Promise<any> {
  const res = await fetch(`${BASE}/emotion/history?limit=${limit}`);
  return res.json();
}

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

export interface ModelConfigResponse {
  tiers: Record<string, TierModelConfig>;
  overrides: Record<string, TierModelConfig>;
  embed: { provider: string; model: string; base_url?: string } | null;
  adapters: string[];
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
