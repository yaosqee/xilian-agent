import React, { useEffect, useState } from 'react';

interface AuditEntry {
  id: number;
  timestamp: number;
  event_type: string;
  severity: string;
  source: string;
  detail: string;
}

export const AuditPanel: React.FC = () => {
  const [logs, setLogs] = useState<AuditEntry[]>([]);
  const [filter, setFilter] = useState('');

  const fetchLogs = async () => {
    try {
      const url = filter
        ? `/api/audit/logs?event_type=${filter}&limit=30`
        : '/api/audit/logs?limit=30';
      const res = await fetch(url);
      const data = await res.json();
      setLogs(Array.isArray(data) ? data : []);
    } catch { setLogs([]); }
  };

  useEffect(() => { fetchLogs(); }, [filter]);

  const severityColor = (s: string) => {
    if (s === 'warning') return '#d08020';
    if (s === 'error') return '#c04040';
    return 'var(--color-text-dim)';
  };

  const typeLabel = (t: string) => {
    const map: Record<string, string> = {
      prompt_injection_detected: '提示注入', personality_drift_warning: '人设漂移告警',
      safe_mode_entered: '进入安全模式', safe_mode_exited: '退出安全模式',
      tool_executed: '工具执行', tool_blocked: '工具拦截',
      rate_limited: '频率限制', emergency_stop: '紧急熔断',
      config_changed: '配置变更', forgotten: '数据删除', personality_check: '人设自检',
    };
    return map[t] || t;
  };

  return (
    <div>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, color: 'var(--color-text)' }}>
        审计日志
      </h3>
      <select
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        style={{
          background: 'var(--glass-bg)', border: '1px solid rgba(200, 180, 210, 0.3)',
          padding: '6px 10px', borderRadius: 8, marginBottom: 12,
          color: 'var(--color-text)', fontSize: 13, outline: 'none',
        }}
      >
        <option value="">全部类型</option>
        <option value="prompt_injection_detected">提示注入</option>
        <option value="personality_drift_warning">人设漂移</option>
        <option value="safe_mode_entered">进入安全模式</option>
        <option value="safe_mode_exited">退出安全模式</option>
        <option value="tool_executed">工具执行</option>
        <option value="config_changed">配置变更</option>
      </select>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {logs.map((log) => (
          <div key={log.id} style={{
            background: 'rgba(255, 255, 255, 0.4)',
            borderRadius: 8, padding: '10px 14px', fontSize: 13,
            border: '1px solid rgba(200, 180, 210, 0.2)',
            borderLeft: `3px solid ${severityColor(log.severity)}`,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: severityColor(log.severity), fontWeight: 500 }}>
                {typeLabel(log.event_type)}
              </span>
              <span style={{ color: 'var(--color-text-muted)', fontSize: 11 }}>
                {new Date(log.timestamp * 1000).toLocaleString('zh-CN')}
              </span>
            </div>
            {log.detail && (
              <div style={{ color: 'var(--color-text-dim)', marginTop: 4 }}>{log.detail}</div>
            )}
          </div>
        ))}
        {logs.length === 0 && (
          <div style={{ color: 'var(--color-text-muted)', textAlign: 'center', padding: 24, fontSize: 13 }}>
            暂无审计记录
          </div>
        )}
      </div>
    </div>
  );
};
