/**
 * 标记工具 — 从 SSE 流中解析标记并派发事件。
 *
 * 阶段 7c 交付。在 useChat 的 SSE onmessage 中调用。
 */

const MARKER_RE = /\[(emotion:[a-z_]+:[0-9.]+|action:[a-z_]+|pause:[0-9.]+|emph:[^\]]+|whisper:[^\]]+)\]/g;

export interface MarkerEvent {
  kind: 'emotion' | 'action' | 'pause' | 'emph' | 'whisper';
  payload: Record<string, any>;
}

/**
 * 从文本中提取所有标记，返回 { cleaned, events }
 */
export function extractMarkers(text: string): { cleaned: string; events: MarkerEvent[] } {
  const events: MarkerEvent[] = [];
  const cleaned = text.replace(MARKER_RE, (match, inner: string) => {
    if (inner.startsWith('emotion:')) {
      const [, emotion, intensity] = inner.split(':');
      events.push({ kind: 'emotion', payload: { emotion, intensity: parseFloat(intensity) } });
    } else if (inner.startsWith('action:')) {
      events.push({ kind: 'action', payload: { action: inner.slice(7) } });
    } else if (inner.startsWith('pause:')) {
      events.push({ kind: 'pause', payload: { seconds: parseFloat(inner.slice(6)) } });
    } else if (inner.startsWith('emph:')) {
      events.push({ kind: 'emph', payload: { text: inner.slice(5) } });
    } else if (inner.startsWith('whisper:')) {
      events.push({ kind: 'whisper', payload: { text: inner.slice(8) } });
    }
    return '';
  });

  return { cleaned: cleaned.replace(/\s+/g, ' ').trim(), events };
}

/**
 * 触发 thinking 动画（在 chat container 上加 class，3s 后移除）
 */
export function triggerAction(el: HTMLElement | null, action: string) {
  if (!el) return;
  const CLASS_MAP: Record<string, string> = {
    thinking: 'xilian-thinking',
    smile: 'xilian-smile',
  };
  const cls = CLASS_MAP[action];
  if (cls) {
    el.classList.add(cls);
    setTimeout(() => el.classList.remove(cls), 3000);
  }
}
