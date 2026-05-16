import React, { useEffect, useState } from 'react';

interface SkillInfo {
  category: string;
  description: string;
  triggers: string[];
  safety: string;
  version: string;
}

export const SkillsPanel: React.FC = () => {
  const [skills, setSkills] = useState<Record<string, SkillInfo>>({});

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/skills');
        const data = await res.json();
        setSkills(data.skills || {});
      } catch {}
    })();
  }, []);

  const safetyColor = (s: string) => {
    if (s === 'execute') return '#c04040';
    if (s === 'read_write') return '#d08020';
    return '#40a040';
  };

  return (
    <div>
      <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: 10, color: 'var(--color-text)' }}>
        技能管理 ({Object.keys(skills).length})
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {Object.entries(skills).map(([name, info]) => (
          <div
            key={name}
            style={{
              background: 'rgba(255, 255, 255, 0.4)',
              borderRadius: 8,
              padding: '12px 14px',
              fontSize: 13,
              border: '1px solid rgba(200, 180, 210, 0.2)',
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: 'var(--color-text)', fontWeight: 500 }}>{name}</span>
              <span
                style={{
                  color: safetyColor(info.safety),
                  fontSize: 11,
                  border: `1px solid ${safetyColor(info.safety)}`,
                  borderRadius: 4, padding: '1px 8px',
                }}
              >
                {info.safety}
              </span>
            </div>
            <div style={{ color: 'var(--color-text-dim)', marginTop: 4 }}>{info.description}</div>
            <div style={{ color: 'var(--color-text-muted)', marginTop: 4, fontSize: 11 }}>
              触发词：{info.triggers.join('、')} | v{info.version}
            </div>
          </div>
        ))}
        {Object.keys(skills).length === 0 && (
          <div style={{ color: 'var(--color-text-muted)', textAlign: 'center', padding: 24, fontSize: 13 }}>
            暂无已加载技能
          </div>
        )}
      </div>
    </div>
  );
};
