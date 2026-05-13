import React from 'react';

export const MemoryPanel: React.FC = () => {
  return (
    <div>
      <h3 style={{ fontSize: 18, fontWeight: 600, marginBottom: 4 }}>📖 记忆书页</h3>
      <p style={{ fontSize: 13, color: 'rgba(255,255,255,0.4)', marginBottom: 20 }}>
        昔涟记下的点点滴滴
      </p>
      <p style={{ color: 'rgba(255,255,255,0.3)', fontSize: 14, textAlign: 'center', marginTop: 60 }}>
        记忆浏览将在后续版本中开放…<br />
        昔涟正在用心记着呢 ✨
      </p>
    </div>
  );
};
