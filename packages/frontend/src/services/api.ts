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
      const text = await res.text();
      // Simple SSE parsing
      const lines = text.split('\n');
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') { onDone(); return; }
          onToken(data);
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
