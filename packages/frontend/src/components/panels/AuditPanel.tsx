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
      setLogs(data);
    } catch {}
  };

  useEffect(() => { fetchLogs(); }, [filter]);

  const severityColor = (s: string) => {
    if (s === 'warning') return '#f0a020';
    if (s === 'error') return '#d04040';
    return '#888';
  };

  const typeLabel = (t: string) => {
    const map: Record<string, string> = {
      prompt_injection_detected: '提示注入',
      personality_drift_warning: '人设漂移告警',
      safe_mode_entered: '进入安全模式',
      safe_mode_exited: '退出安全模式',
      tool_executed: '工具执行',
      tool_blocked: '工具拦截',
      rate_limited: '频率限制',
      emergency_stop: '紧急熔断',
      config_changed: '配置变更',
      forgotten: '数据删除',
      personality_check: '人设自检',
    };
    return map[t] || t;
  };

  return (
    <div style={{ padding: 16, overflowY: 'auto', height: '100%' }}>
      <h3 style={{ color: '#f0c0d0', marginBottom: 12 }}>审计日志</h3>
      <select
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        style={{
          background: '#1a1a2e', color: '#ccc', border: '1px solid #333',
          padding: '4px 8px', borderRadius: 4, marginBottom: 12,
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
          <div
            key={log.id}
            style={{
              background: '#15152a', borderRadius: 6, padding: '10px 14px',
              borderLeft: `3px solid ${severityColor(log.severity)}`,
              fontSize: 13,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between' }}>
              <span style={{ color: severityColor(log.severity) }}>
                {typeLabel(log.event_type)}
              </span>
              <span style={{ color: '#666', fontSize: 11 }}>
                {new Date(log.timestamp * 1000).toLocaleString('zh-CN')}
              </span>
            </div>
            {log.detail && (
              <div style={{ color: '#999', marginTop: 4 }}>{log.detail}</div>
            )}
          </div>
        ))}
        {logs.length === 0 && (
          <div style={{ color: '#666', textAlign: 'center', padding: 24 }}>
            暂无审计记录
          </div>
        )}
      </div>
    </div>
  );
};
