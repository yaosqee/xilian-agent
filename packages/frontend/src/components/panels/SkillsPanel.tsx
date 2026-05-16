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
    const fetchSkills = async () => {
      try {
        const res = await fetch('/api/skills');
        const data = await res.json();
        setSkills(data.skills || {});
      } catch {}
    };
    fetchSkills();
  }, []);

  const safetyColor = (s: string) => {
    if (s === 'execute') return '#d04040';
    if (s === 'read_write') return '#f0a020';
    return '#40a040';
  };

  return (
    <div style={{ padding: 16, overflowY: 'auto', height: '100%' }}>
      <h3 style={{ color: '#f0c0d0', marginBottom: 12 }}>
        技能管理 ({Object.keys(skills).length})
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {Object.entries(skills).map(([name, info]) => (
          <div
            key={name}
            style={{
              background: '#15152a', borderRadius: 6, padding: '12px 14px',
              fontSize: 13,
            }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span style={{ color: '#e0c0d0', fontWeight: 500 }}>{name}</span>
              <span
                style={{
                  color: safetyColor(info.safety),
                  fontSize: 11,
                  border: `1px solid ${safetyColor(info.safety)}`,
                  borderRadius: 3, padding: '1px 6px',
                }}
              >
                {info.safety}
              </span>
            </div>
            <div style={{ color: '#999', marginTop: 4 }}>{info.description}</div>
            <div style={{ color: '#666', marginTop: 4, fontSize: 11 }}>
              触发词：{info.triggers.join('、')} | v{info.version}
            </div>
          </div>
        ))}
        {Object.keys(skills).length === 0 && (
          <div style={{ color: '#666', textAlign: 'center', padding: 24 }}>
            暂无已加载技能
          </div>
        )}
      </div>
    </div>
  );
};
