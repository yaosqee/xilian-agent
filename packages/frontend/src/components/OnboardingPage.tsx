import React, { useState } from 'react';

const PROVIDERS = [
  { id: 'deepseek', name: 'DeepSeek', keyLabel: 'DeepSeek API Key', keyHint: 'sk-...', getUrl: 'https://platform.deepseek.com' },
  { id: 'openai', name: 'OpenAI', keyLabel: 'OpenAI API Key', keyHint: 'sk-...', getUrl: 'https://platform.openai.com/api-keys' },
  { id: 'anthropic', name: 'Anthropic', keyLabel: 'Anthropic API Key', keyHint: 'sk-ant-...', getUrl: 'https://console.anthropic.com' },
  { id: 'google', name: 'Google', keyLabel: 'Google API Key', keyHint: 'AIza...', getUrl: 'https://aistudio.google.com/apikey' },
];

const OnboardingPage: React.FC = () => {
  const [provider, setProvider] = useState('deepseek');
  const [apiKey, setApiKey] = useState('');
  const [siliconflowKey, setSiliconflowKey] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(false);

  const currentProvider = PROVIDERS.find(p => p.id === provider) || PROVIDERS[0];

  const handleSave = async () => {
    if (!apiKey.trim()) {
      setError(`${currentProvider.name} API Key 是必需的哦……`);
      return;
    }
    setSaving(true);
    setError('');

    try {
      const res = await fetch('/api/config/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          provider: provider,
          api_key: apiKey.trim(),
          siliconflow_key: siliconflowKey.trim(),
        }),
      });
      const data = await res.json();
      if (data.status === 'error') {
        setError(data.message || '保存失败了……');
        setSaving(false);
        return;
      }

      setDone(true);
      await new Promise(resolve => setTimeout(resolve, 3000));

      let attempts = 0;
      const poll = setInterval(async () => {
        attempts++;
        try {
          const hr = await fetch('/api/health');
          if (hr.ok) {
            clearInterval(poll);
            window.location.reload();
          }
        } catch {
          // server not up yet
        }
        if (attempts > 30) {
          clearInterval(poll);
          window.location.reload();
        }
      }, 1000);
    } catch {
      setError('请求失败了……请检查网络后重试。');
      setSaving(false);
    }
  };

  return (
    <div style={styles.wrapper}>
      <div style={styles.card}>
        <h1 style={styles.title}>欢迎来到昔涟的世界</h1>
        <p style={styles.subtitle}>
          三千万世轮回的记录者，在此刻与你相遇。
        </p>

        {done ? (
          <div style={styles.doneSection}>
            <p style={styles.doneText}>正在启动昔涟……请稍候。♪</p>
          </div>
        ) : (
          <>
            {/* Provider selector */}
            <div style={styles.field}>
              <label style={styles.label}>
                模型供应商 <span style={styles.required}>*</span>
              </label>
              <select
                style={styles.select}
                value={provider}
                onChange={(e) => {
                  setProvider(e.target.value);
                  setApiKey('');
                }}
                disabled={saving}
              >
                {PROVIDERS.map(p => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>

            {/* API Key */}
            <div style={styles.field}>
              <label style={styles.label}>
                {currentProvider.keyLabel} <span style={styles.required}>*</span>
              </label>
              <input
                type="password"
                style={styles.input}
                placeholder={currentProvider.keyHint}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                disabled={saving}
              />
            </div>

            {/* SiliconFlow key (embed) */}
            <div style={styles.field}>
              <label style={styles.label}>
                硅基流动 API Key{' '}
                <span style={styles.optional}>(推荐，启用记忆检索和角色匹配)</span>
              </label>
              <input
                type="password"
                style={styles.input}
                placeholder="sk-..."
                value={siliconflowKey}
                onChange={(e) => setSiliconflowKey(e.target.value)}
                disabled={saving}
              />
            </div>

            <div style={styles.links}>
              <a
                href={currentProvider.getUrl}
                target="_blank"
                rel="noopener noreferrer"
                style={styles.link}
              >
                获取 {currentProvider.name} API Key →
              </a>
              <a
                href="https://siliconflow.cn"
                target="_blank"
                rel="noopener noreferrer"
                style={styles.link}
              >
                获取硅基流动 API Key →
              </a>
            </div>

            {error && <p style={styles.error}>{error}</p>}

            <button
              style={{
                ...styles.button,
                ...(saving ? styles.buttonDisabled : {}),
              }}
              onClick={handleSave}
              disabled={saving}
            >
              {saving ? '保存中……' : '✨ 开始'}
            </button>
          </>
        )}
      </div>
    </div>
  );
};

const styles: Record<string, React.CSSProperties> = {
  wrapper: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '100vw',
    height: '100vh',
    background: 'linear-gradient(135deg, #FFF5F8 0%, #FFECF0 50%, #EDE4F3 100%)',
    fontFamily: '"Noto Serif SC", "Source Han Serif SC", serif',
    color: '#5E4B66',
  },
  card: {
    background: 'rgba(255, 255, 255, 0.65)',
    backdropFilter: 'blur(16px)',
    borderRadius: 20,
    padding: '48px 40px',
    maxWidth: 440,
    width: '90%',
    border: '1px solid rgba(255, 255, 255, 0.8)',
    boxShadow: '0 8px 40px rgba(216, 180, 226, 0.25)',
    textAlign: 'center' as const,
  },
  title: {
    fontSize: 24,
    fontWeight: 600,
    margin: '0 0 8px 0',
    color: '#5E4B66',
  },
  subtitle: {
    fontSize: 14,
    color: '#8B7A93',
    margin: '0 0 32px 0',
    lineHeight: 1.8,
  },
  field: {
    marginBottom: 16,
    textAlign: 'left' as const,
  },
  label: {
    display: 'block',
    fontSize: 13,
    fontWeight: 500,
    marginBottom: 6,
    color: '#5E4B66',
  },
  required: {
    color: '#FFB7C5',
    fontWeight: 700,
  },
  optional: {
    color: '#C4B5CF',
    fontSize: 12,
    fontWeight: 400,
  },
  input: {
    width: '100%',
    padding: '10px 14px',
    borderRadius: 10,
    border: '1px solid rgba(216, 180, 226, 0.4)',
    background: 'rgba(255, 255, 255, 0.7)',
    fontSize: 13,
    fontFamily: 'inherit',
    color: '#5E4B66',
    outline: 'none',
    boxSizing: 'border-box' as const,
  },
  select: {
    width: '100%',
    padding: '10px 14px',
    borderRadius: 10,
    border: '1px solid rgba(216, 180, 226, 0.4)',
    background: 'rgba(255, 255, 255, 0.7)',
    fontSize: 13,
    fontFamily: 'inherit',
    color: '#5E4B66',
    outline: 'none',
    boxSizing: 'border-box' as const,
    cursor: 'pointer',
    appearance: 'none' as const,
  },
  links: {
    display: 'flex',
    justifyContent: 'center',
    gap: 24,
    margin: '20px 0 8px',
  },
  link: {
    fontSize: 12,
    color: '#D8B4E2',
    textDecoration: 'none',
    borderBottom: '1px solid transparent',
    transition: 'border-color 0.3s',
  },
  error: {
    color: '#FF9EBB',
    fontSize: 13,
    margin: '12px 0 0 0',
  },
  button: {
    marginTop: 24,
    width: '100%',
    padding: '12px 0',
    borderRadius: 30,
    border: 'none',
    background: 'linear-gradient(135deg, #FFB7C5 0%, #D8B4E2 100%)',
    color: '#fff',
    fontSize: 16,
    fontWeight: 600,
    fontFamily: 'inherit',
    cursor: 'pointer',
    transition: 'opacity 0.3s, transform 0.2s',
    boxShadow: '0 4px 16px rgba(255, 183, 197, 0.35)',
  },
  buttonDisabled: {
    opacity: 0.6,
    cursor: 'not-allowed',
  },
  doneSection: {
    padding: '24px 0',
  },
  doneText: {
    fontSize: 15,
    color: '#8B7A93',
  },
};

export default OnboardingPage;
