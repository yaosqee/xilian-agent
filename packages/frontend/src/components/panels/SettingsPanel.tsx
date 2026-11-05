import React, { useEffect, useState, useRef } from 'react';
import { resetSession, fetchBackground, uploadBackground, validateApiKey } from '../../services/api';
import type { RoutingProfileInfo, RoutingModelInfo, ProviderInfo } from '../../services/api';
import { useChatStore } from '../../stores/chatStore';
import { useAutonomyStore } from '../../stores/autonomyStore';
import { useModelStore } from '../../stores/modelStore';

// ── Model Settings Sub-component ──────────────────────────

const TIER_LABELS: Record<string, string> = {
  powerful: '主力模型',
  fast: '后台模型',
  reasoning: '推理模型',
  embed: '嵌入模型',
};

const OVERRIDE_TASK_LABELS: Record<string, string> = {
  personality_check: '人格一致性检查',
  proactive_greeting: '主动问候生成',
  memory_encoding: '记忆叙事化',
};

const ModelSettingsSection: React.FC<{ sectionStyle: React.CSSProperties }> = ({ sectionStyle }) => {
  const {
    providers, providersLoading, tiers, overrides, loading, adapters,
    embedConfig,
    loadProviders, loadConfig, updateConfig, addProviderKey,
  } = useModelStore();

  // 只显示已配置的供应商
  const configuredProviders = providers.filter(p => adapters.includes(p.id));

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showAddProvider, setShowAddProvider] = useState(false);
  const [newProvider, setNewProvider] = useState('openai');
  const [newApiKey, setNewApiKey] = useState('');
  const [newBaseUrl, setNewBaseUrl] = useState('');
  const [addingKey, setAddingKey] = useState(false);
  const [keyError, setKeyError] = useState('');

  useEffect(() => {
    loadProviders();
    loadConfig();
  }, []);

  if (providersLoading || loading) {
    return (
      <div style={sectionStyle}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', marginBottom: 10 }}>
          模型设置
        </div>
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>加载中...</p>
      </div>
    );
  }

  // ── F1: Cost estimate ──
  const tierEntries = Object.entries(tiers).filter(([t]) => t !== 'embed');
  let costEstimate = '';
  if (tierEntries.length > 0) {
    let totalCost = 0;
    for (const [, cfg] of tierEntries) {
      const p = configuredProviders.find(pr => pr.id === cfg.provider);
      const m = p?.models.find(mm => mm.id === cfg.model);
      if (m) {
        // Typical usage: 2000 prompt + 500 completion tokens per round
        totalCost += (m.cost_per_1k_in * 2) + (m.cost_per_1k_out * 0.5);
      }
    }
    // Background tasks run ~15 rounds per day, but we show per-conversation
    const perRound = totalCost;
    const perDay = (perRound * 20) + (perRound * 0.3 * 15); // 20 chat rounds + ~15 background
    if (perDay > 0) {
      // Convert to approximate CNY (1 USD ≈ 7.2 CNY)
      const perRoundCNY = perRound * 7.2;
      const perDayCNY = perDay * 7.2;
      costEstimate = `单轮 ≈ ¥${perRoundCNY.toFixed(2)} · 日均 ~20轮 ≈ ¥${perDayCNY.toFixed(2)}`;
    }
  }

  return (
    <div style={sectionStyle}>
      <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', marginBottom: 10 }}>
        模型设置
      </div>

      {tierEntries.length === 0 ? (
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          启动后可用 · 目前使用默认配置
        </p>
      ) : (
        <>
          {tierEntries.map(([tier, cfg]) => (
            <div key={tier} style={{ marginBottom: 12 }}>
              <label style={{ fontSize: 12, color: 'var(--color-text-dim)', display: 'block', marginBottom: 4 }}>
                {TIER_LABELS[tier] || tier}
              </label>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <select
                  style={{
                    flex: 1, padding: '7px 10px', borderRadius: 8,
                    border: '1px solid rgba(216, 180, 226, 0.3)',
                    background: 'rgba(255, 255, 255, 0.6)',
                    fontSize: 12, fontFamily: 'inherit', color: '#5E4B66',
                    outline: 'none', cursor: 'pointer',
                  }}
                  value={cfg ? `${cfg.provider}:${cfg.model}` : ''}
                  onChange={async (e) => {
                    const [provider, model] = e.target.value.split(':');
                    if (provider && model) {
                      await updateConfig(tier, provider, model);
                    }
                  }}
                >
                  <option value="">{cfg ? `${cfg.provider} / ${cfg.model}` : '未配置'}</option>
                  {configuredProviders.map(p => (
                    <optgroup key={p.id} label={p.name}>
                      {p.models.map(m => (
                        <option key={`${p.id}:${m.id}`} value={`${p.id}:${m.id}`}>
                          {m.name}
                        </option>
                      ))}
                    </optgroup>
                  ))}
                </select>
              </div>
            </div>
          ))}

          {/* F1: Cost estimate */}
          {costEstimate && (
            <div style={{
              fontSize: 11, color: 'var(--color-text-muted)',
              padding: '8px 10px', borderRadius: 6,
              background: 'rgba(216, 180, 226, 0.08)',
              marginBottom: 8,
            }}>
              💰 {costEstimate}
            </div>
          )}

        </>
      )}

      {/* Embed model — read-only, configured during onboarding */}
      {embedConfig && (
        <div style={{ marginBottom: 8 }}>
          <label style={{ fontSize: 12, color: 'var(--color-text-dim)', display: 'block', marginBottom: 4 }}>
            {TIER_LABELS['embed']}（首次引导设置）
          </label>
          <div style={{
            fontSize: 12, color: 'var(--color-text-muted)',
            padding: '6px 10px', borderRadius: 8,
            background: 'rgba(216, 180, 226, 0.06)',
          }}>
            {embedConfig.provider} / {embedConfig.model}
          </div>
        </div>
      )}

      {/* F3: Add provider API key */}
      <button
        onClick={() => setShowAddProvider(!showAddProvider)}
        style={{
          width: '100%', padding: '6px 12px', borderRadius: 8,
          border: '1px dashed rgba(216, 180, 226, 0.3)',
          background: 'transparent',
          color: 'var(--color-text-dim)', cursor: 'pointer',
          fontSize: 12, fontFamily: 'inherit',
          marginBottom: 8,
        }}
      >
        {showAddProvider ? '收起' : '+ 添加供应商'}
      </button>

      {showAddProvider && (
        <div style={{ marginBottom: 12 }}>
          <select
            style={{
              width: '100%', padding: '6px 10px', borderRadius: 8,
              border: '1px solid rgba(216, 180, 226, 0.3)',
              background: 'rgba(255, 255, 255, 0.6)',
              fontSize: 12, fontFamily: 'inherit', color: '#5E4B66',
              outline: 'none', cursor: 'pointer', marginBottom: 6,
            }}
            value={newProvider}
            onChange={(e) => { setNewProvider(e.target.value); setNewApiKey(''); }}
          >
            <option value="openai">OpenAI</option>
            <option value="anthropic">Anthropic</option>
            <option value="google">Google</option>
          </select>
          <input
            type="password"
            style={{
              width: '100%', padding: '6px 10px', borderRadius: 8,
              border: '1px solid rgba(216, 180, 226, 0.3)',
              background: 'rgba(255, 255, 255, 0.6)',
              fontSize: 12, fontFamily: 'inherit', color: '#5E4B66',
              outline: 'none', boxSizing: 'border-box' as const,
              marginBottom: 6,
            }}
            placeholder={newProvider === 'anthropic' ? 'sk-ant-...' : newProvider === 'google' ? 'AIza...' : 'sk-...'}
            value={newApiKey}
            onChange={(e) => setNewApiKey(e.target.value)}
            disabled={addingKey}
          />
          <input
            type="text"
            style={{
              width: '100%', padding: '6px 10px', borderRadius: 8,
              border: '1px solid rgba(216, 180, 226, 0.3)',
              background: 'rgba(255, 255, 255, 0.6)',
              fontSize: 12, fontFamily: 'inherit', color: '#5E4B66',
              outline: 'none', boxSizing: 'border-box' as const,
              marginBottom: 6,
            }}
            placeholder="自定义 API 地址（可选，如代理或兼容端点）"
            value={newBaseUrl}
            onChange={(e) => setNewBaseUrl(e.target.value)}
            disabled={addingKey}
          />
          {keyError && (
            <p style={{ fontSize: 11, color: '#FF9EBB', margin: '0 0 6px 0' }}>{keyError}</p>
          )}
          <button
            onClick={async () => {
              if (!newApiKey.trim()) { setKeyError('请输入 API Key'); return; }
              setAddingKey(true); setKeyError('');
              try {
                // Validate first
                const vr = await validateApiKey(newProvider, newApiKey.trim());
                if (!vr.valid) {
                  setKeyError(vr.error || 'Key 验证失败');
                  setAddingKey(false);
                  return;
                }
                const ok = await addProviderKey(newProvider, newApiKey.trim(), newBaseUrl.trim() || undefined);
                if (ok) {
                  setNewApiKey('');
                  setNewBaseUrl('');
                  setKeyError('');
                  setShowAddProvider(false);
                } else {
                  setKeyError('保存失败，请重试');
                }
              } catch {
                setKeyError('网络错误，请重试');
              }
              setAddingKey(false);
            }}
            disabled={addingKey}
            style={{
              width: '100%', padding: '6px 12px', borderRadius: 8,
              border: 'none',
              background: addingKey
                ? 'rgba(200, 180, 200, 0.3)'
                : 'linear-gradient(135deg, var(--color-pink), var(--color-purple))',
              color: '#fff', cursor: addingKey ? 'default' : 'pointer',
              fontSize: 12, fontFamily: 'inherit',
            }}
          >
            {addingKey ? '验证中...' : '验证并添加'}
          </button>
        </div>
      )}

      {/* F2: Advanced task overrides */}
      <button
        onClick={() => setShowAdvanced(!showAdvanced)}
        style={{
          width: '100%', padding: '6px 12px', borderRadius: 8,
          border: 'none', background: 'transparent',
          color: 'var(--color-text-muted)', cursor: 'pointer',
          fontSize: 11, fontFamily: 'inherit',
          transition: 'color 0.3s',
        }}
      >
        {showAdvanced ? '▾ 高级设置' : '▸ 高级设置'}
      </button>

      {showAdvanced && (
        <div style={{ marginTop: 8 }}>
          <p style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 8 }}>
            为特定任务指定不同于 Tier 默认的模型。保持人格一致性时推荐人格检查单独指定。
          </p>
          {Object.entries(OVERRIDE_TASK_LABELS).map(([taskType, label]) => {
            const savedOverride = overrides[taskType];
            const overrideValue = savedOverride
              ? `${savedOverride.provider}:${savedOverride.model}`
              : '';
            return (
            <div key={taskType} style={{ marginBottom: 8 }}>
              <label style={{ fontSize: 11, color: 'var(--color-text-dim)', display: 'block', marginBottom: 3 }}>
                {label} <code style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>{taskType}</code>
              </label>
              <select
                style={{
                  width: '100%', padding: '5px 8px', borderRadius: 6,
                  border: '1px solid rgba(216, 180, 226, 0.2)',
                  background: 'rgba(255, 255, 255, 0.5)',
                  fontSize: 11, fontFamily: 'inherit', color: '#5E4B66',
                  outline: 'none', cursor: 'pointer',
                }}
                value={overrideValue}
                onChange={async (e) => {
                  const val = e.target.value;
                  if (!val) return;
                  const [provider, model] = val.split(':');
                  if (provider && model) {
                    await updateConfig(`override:${taskType}`, provider, model);
                  }
                }}
              >
                <option value="">跟随 Tier 默认</option>
                {configuredProviders.map(p => (
                  <optgroup key={p.id} label={p.name}>
                    {p.models.map(m => (
                      <option key={`${p.id}:${m.id}`} value={`${p.id}:${m.id}`}>
                        {m.name}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            </div>
          );
            })}
        </div>
      )}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════

const CAP_LABELS: Record<string, string> = {
  tools: '工具',
  vision: '视觉',
  streaming: '流式',
  thinking: '思考',
};

const RoutingBlock: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div style={{ marginBottom: 16 }}>
    <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text)', marginBottom: 6 }}>
      {title}
    </div>
    {children}
  </div>
);

const routingCardStyle: React.CSSProperties = {
  padding: '8px 10px',
  borderRadius: 9,
  background: 'rgba(255, 255, 255, 0.45)',
  border: '1px solid rgba(216, 180, 226, 0.18)',
  marginBottom: 6,
  fontSize: 11,
};

const ProfileEditor: React.FC<{
  name: string;
  profile: RoutingProfileInfo;
  models: Record<string, RoutingModelInfo>;
  saving: boolean;
  onSave: (patch: {
    provider?: string;
    model: string;
    fallbacks: string[];
    temperature: number;
    max_tokens: number;
  }) => Promise<boolean>;
  onReset: () => Promise<boolean>;
}> = ({ name, profile, models, saving, onSave, onReset }) => {
  const [model, setModel] = useState(profile.model);
  const [fallbacks, setFallbacks] = useState<string[]>(profile.fallbacks);
  const [temperature, setTemperature] = useState(String(profile.temperature));
  const [maxTokens, setMaxTokens] = useState(String(profile.max_tokens));
  const [newFallback, setNewFallback] = useState('');

  const modelEntries = Object.entries(models);
  const fallbackOptions = modelEntries.filter(
    ([id]) => id !== model && !fallbacks.includes(id),
  );

  const addFallback = () => {
    if (!newFallback || fallbacks.includes(newFallback)) return;
    setFallbacks([...fallbacks, newFallback]);
    setNewFallback('');
  };

  return (
    <div style={routingCardStyle}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 5 }}>
        <span style={{ fontWeight: 600, color: 'var(--color-text)' }}>{name}</span>
        <span style={{
          fontSize: 9, padding: '1px 5px', borderRadius: 999,
          color: profile.source === 'ui' ? 'var(--color-purple-dark)' : 'var(--color-text-muted)',
          background: profile.source === 'ui'
            ? 'rgba(216, 180, 226, 0.2)' : 'rgba(255, 255, 255, 0.35)',
        }}>
          {profile.source === 'ui' ? 'UI 覆盖' : '文件默认'}
        </span>
      </div>

      <label style={{ display: 'block', color: 'var(--color-text-muted)', marginBottom: 2 }}>主模型</label>
      <select
        value={model}
        onChange={(e) => setModel(e.target.value)}
        disabled={saving}
        style={{
          width: '100%', padding: '5px 7px', borderRadius: 6,
          border: '1px solid rgba(216, 180, 226, 0.25)',
          background: 'rgba(255, 255, 255, 0.6)',
          fontSize: 11, fontFamily: 'inherit', color: '#5E4B66',
          outline: 'none', marginBottom: 6,
        }}
      >
        {modelEntries.map(([id, m]) => (
          <option key={id} value={id}>{id} · {m.provider}</option>
        ))}
      </select>

      <label style={{ display: 'block', color: 'var(--color-text-muted)', marginBottom: 2 }}>Fallback</label>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
        {fallbacks.length === 0 && (
          <span style={{ color: 'var(--color-text-muted)' }}>无</span>
        )}
        {fallbacks.map((fb) => (
          <span key={fb} style={{
            padding: '2px 6px', borderRadius: 999,
            background: 'rgba(255, 183, 197, 0.15)',
            color: 'var(--color-pink-dark)',
          }}>
            {fb}
            <button
              onClick={() => setFallbacks(fallbacks.filter((x) => x !== fb))}
              disabled={saving}
              style={{
                border: 'none', background: 'transparent', cursor: 'pointer',
                color: 'var(--color-pink-dark)', padding: '0 0 0 4px', fontSize: 11,
              }}
              title="移除"
            >×</button>
          </span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 6 }}>
        <select
          value={newFallback}
          onChange={(e) => setNewFallback(e.target.value)}
          disabled={saving || fallbackOptions.length === 0}
          style={{
            flex: 1, padding: '4px 6px', borderRadius: 6,
            border: '1px solid rgba(216, 180, 226, 0.2)',
            background: 'rgba(255, 255, 255, 0.5)',
            fontSize: 10, fontFamily: 'inherit', color: '#5E4B66',
          }}
        >
          <option value="">+ 添加 fallback</option>
          {fallbackOptions.map(([id]) => (
            <option key={id} value={id}>{id}</option>
          ))}
        </select>
        <button
          onClick={addFallback}
          disabled={saving || !newFallback}
          style={{
            padding: '3px 8px', borderRadius: 6, border: 'none',
            background: 'rgba(216, 180, 226, 0.2)',
            color: 'var(--color-purple-dark)', cursor: 'pointer', fontSize: 10,
          }}
        >添加</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, marginBottom: 7 }}>
        <label style={{ color: 'var(--color-text-muted)' }}>
          temperature
          <input
            type="number" min="0" max="2" step="0.05"
            value={temperature}
            onChange={(e) => setTemperature(e.target.value)}
            disabled={saving}
            style={{
              width: '100%', boxSizing: 'border-box', marginTop: 2,
              padding: '4px 6px', borderRadius: 6,
              border: '1px solid rgba(216, 180, 226, 0.2)',
              background: 'rgba(255, 255, 255, 0.5)',
              fontSize: 10, fontFamily: 'inherit', color: '#5E4B66',
            }}
          />
        </label>
        <label style={{ color: 'var(--color-text-muted)' }}>
          max_tokens
          <input
            type="number" min="1" step="1"
            value={maxTokens}
            onChange={(e) => setMaxTokens(e.target.value)}
            disabled={saving}
            style={{
              width: '100%', boxSizing: 'border-box', marginTop: 2,
              padding: '4px 6px', borderRadius: 6,
              border: '1px solid rgba(216, 180, 226, 0.2)',
              background: 'rgba(255, 255, 255, 0.5)',
              fontSize: 10, fontFamily: 'inherit', color: '#5E4B66',
            }}
          />
        </label>
      </div>

      <div style={{ display: 'flex', gap: 6 }}>
        <button
          onClick={() => {
            const t = Number(temperature);
            const mt = Number(maxTokens);
            if (!Number.isFinite(t) || !Number.isFinite(mt) || mt <= 0) return;
            const provider = models[model]?.provider;
            void onSave({
              provider, model, fallbacks, temperature: t, max_tokens: mt,
            });
          }}
          disabled={saving}
          style={{
            flex: 1, padding: '5px 8px', borderRadius: 7, border: 'none',
            background: 'linear-gradient(135deg, var(--color-pink), var(--color-purple))',
            color: '#fff', cursor: saving ? 'default' : 'pointer',
            fontSize: 11, fontFamily: 'inherit',
          }}
        >{saving ? '保存中...' : '保存'}</button>
        {profile.source === 'ui' && (
          <button
            onClick={() => void onReset()}
            disabled={saving}
            style={{
              padding: '5px 8px', borderRadius: 7,
              border: '1px solid rgba(216, 180, 226, 0.3)',
              background: 'transparent', color: 'var(--color-text-muted)',
              cursor: saving ? 'default' : 'pointer', fontSize: 10,
              fontFamily: 'inherit',
            }}
          >恢复默认</button>
        )}
      </div>
    </div>
  );
};

const ProviderAddForm: React.FC<{
  providers: ProviderInfo[];
  saving: boolean;
  onAdd: (provider: string, apiKey: string, baseUrl?: string) => Promise<boolean>;
}> = ({ providers, saving, onAdd }) => {
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [baseUrl, setBaseUrl] = useState('');
  const [message, setMessage] = useState('');

  if (!open) {
    return (
      <button
        onClick={() => {
          setProvider(providers[0]?.id || '');
          setOpen(true);
        }}
        style={{
          width: '100%', padding: '7px 10px', borderRadius: 8,
          border: '1px dashed rgba(216, 180, 226, 0.35)',
          background: 'rgba(255,255,255,0.35)',
          color: 'var(--color-purple-dark)', cursor: 'pointer',
          fontSize: 11, fontFamily: 'inherit',
        }}
      >+ 添加供应商</button>
    );
  }

  return (
    <div style={{ ...routingCardStyle, marginTop: 6 }}>
      <div style={{ fontWeight: 600, color: 'var(--color-text)', marginBottom: 5 }}>
        添加供应商
      </div>
      <select
        value={provider}
        onChange={(e) => setProvider(e.target.value)}
        disabled={saving}
        style={{
          width: '100%', padding: '5px 7px', borderRadius: 6,
          border: '1px solid rgba(216, 180, 226, 0.25)',
          background: 'rgba(255,255,255,0.6)',
          fontSize: 11, fontFamily: 'inherit', color: '#5E4B66',
          marginBottom: 5,
        }}
      >
        {providers.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}{p.connected ? '（已连接，可更新 Key）' : ''}
          </option>
        ))}
      </select>
      <input
        type="password"
        placeholder="API Key"
        value={apiKey}
        onChange={(e) => setApiKey(e.target.value)}
        disabled={saving}
        style={{
          width: '100%', boxSizing: 'border-box', padding: '5px 7px',
          borderRadius: 6, border: '1px solid rgba(216, 180, 226, 0.25)',
          background: 'rgba(255,255,255,0.6)', fontSize: 11,
          fontFamily: 'inherit', color: '#5E4B66', marginBottom: 5,
        }}
      />
      <input
        type="text"
        placeholder="Base URL（可选，代理/兼容端点）"
        value={baseUrl}
        onChange={(e) => setBaseUrl(e.target.value)}
        disabled={saving}
        style={{
          width: '100%', boxSizing: 'border-box', padding: '5px 7px',
          borderRadius: 6, border: '1px solid rgba(216, 180, 226, 0.25)',
          background: 'rgba(255,255,255,0.6)', fontSize: 11,
          fontFamily: 'inherit', color: '#5E4B66', marginBottom: 6,
        }}
      />
      {message && (
        <p style={{ fontSize: 10, color: '#c56b86', margin: '0 0 6px' }}>{message}</p>
      )}
      <div style={{ display: 'flex', gap: 6 }}>
        <button
          onClick={async () => {
            if (!provider || !apiKey.trim()) {
              setMessage('请选择供应商并填写 API Key');
              return;
            }
            setMessage('');
            const ok = await onAdd(provider, apiKey.trim(), baseUrl.trim() || undefined);
            if (ok) {
              setApiKey(''); setBaseUrl(''); setOpen(false);
            } else {
              setMessage('验证或保存失败，请检查 Key / 地址');
            }
          }}
          disabled={saving}
          style={{
            flex: 1, padding: '5px 8px', borderRadius: 7, border: 'none',
            background: 'linear-gradient(135deg, var(--color-pink), var(--color-purple))',
            color: '#fff', cursor: saving ? 'default' : 'pointer',
            fontSize: 11, fontFamily: 'inherit',
          }}
        >{saving ? '验证中...' : '验证并连接'}</button>
        <button
          onClick={() => { setOpen(false); setMessage(''); }}
          disabled={saving}
          style={{
            padding: '5px 8px', borderRadius: 7, border: 'none',
            background: 'transparent', color: 'var(--color-text-muted)',
            cursor: 'pointer', fontSize: 10, fontFamily: 'inherit',
          }}
        >取消</button>
      </div>
    </div>
  );
};

const ModelAddForm: React.FC<{
  providers: string[];
  saving: boolean;
  onAdd: (
    provider: string,
    modelId: string,
    displayName: string,
    capabilities: string[],
    contextWindow: number,
    maxOutputTokens: number,
  ) => Promise<boolean>;
}> = ({ providers, saving, onAdd }) => {
  const [open, setOpen] = useState(false);
  const [provider, setProvider] = useState(providers[0] || '');
  const [modelId, setModelId] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [caps, setCaps] = useState<string[]>(['tools', 'streaming']);
  const [contextWindow, setContextWindow] = useState('128000');
  const [maxOutputTokens, setMaxOutputTokens] = useState('8000');
  const [message, setMessage] = useState('');

  const toggleCap = (cap: string) => {
    setCaps(caps.includes(cap) ? caps.filter((c) => c !== cap) : [...caps, cap]);
  };

  if (!open) {
    return (
      <button
        onClick={() => { setProvider(providers[0] || ''); setOpen(true); }}
        style={{
          width: '100%', marginTop: 4, padding: '6px 9px', borderRadius: 8,
          border: '1px dashed rgba(216, 180, 226, 0.35)',
          background: 'transparent', color: 'var(--color-text-muted)',
          cursor: 'pointer', fontSize: 10, fontFamily: 'inherit',
        }}
      >+ 自定义模型</button>
    );
  }

  return (
    <div style={{ ...routingCardStyle, marginTop: 6 }}>
      <div style={{ fontWeight: 600, color: 'var(--color-text)', marginBottom: 5 }}>自定义模型</div>
      <select
        value={provider}
        onChange={(e) => setProvider(e.target.value)}
        disabled={saving}
        style={{ width: '100%', padding: '5px 7px', borderRadius: 6, border: '1px solid rgba(216,180,226,0.25)', background: 'rgba(255,255,255,0.6)', fontSize: 11, fontFamily: 'inherit', color: '#5E4B66', marginBottom: 5 }}
      >
        {providers.map((p) => <option key={p} value={p}>{p}</option>)}
      </select>
      <input
        placeholder="模型 ID（API 实际名称）"
        value={modelId}
        onChange={(e) => setModelId(e.target.value)}
        disabled={saving}
        style={{ width: '100%', boxSizing: 'border-box', padding: '5px 7px', borderRadius: 6, border: '1px solid rgba(216,180,226,0.25)', background: 'rgba(255,255,255,0.6)', fontSize: 11, fontFamily: 'inherit', color: '#5E4B66', marginBottom: 5 }}
      />
      <input
        placeholder="显示名（可选）"
        value={displayName}
        onChange={(e) => setDisplayName(e.target.value)}
        disabled={saving}
        style={{ width: '100%', boxSizing: 'border-box', padding: '5px 7px', borderRadius: 6, border: '1px solid rgba(216,180,226,0.25)', background: 'rgba(255,255,255,0.6)', fontSize: 11, fontFamily: 'inherit', color: '#5E4B66', marginBottom: 5 }}
      />
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 5 }}>
        {(['tools', 'vision', 'streaming', 'thinking'] as const).map((cap) => (
          <label key={cap} style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>
            <input type="checkbox" checked={caps.includes(cap)} onChange={() => toggleCap(cap)} disabled={saving} />{' '}
            {CAP_LABELS[cap]}
          </label>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 5, marginBottom: 5 }}>
        <input
          type="number" value={contextWindow} onChange={(e) => setContextWindow(e.target.value)}
          disabled={saving} placeholder="context"
          style={{ width: '100%', boxSizing: 'border-box', padding: '4px 6px', borderRadius: 6, border: '1px solid rgba(216,180,226,0.2)', background: 'rgba(255,255,255,0.5)', fontSize: 10, fontFamily: 'inherit', color: '#5E4B66' }}
        />
        <input
          type="number" value={maxOutputTokens} onChange={(e) => setMaxOutputTokens(e.target.value)}
          disabled={saving} placeholder="max output"
          style={{ width: '100%', boxSizing: 'border-box', padding: '4px 6px', borderRadius: 6, border: '1px solid rgba(216,180,226,0.2)', background: 'rgba(255,255,255,0.5)', fontSize: 10, fontFamily: 'inherit', color: '#5E4B66' }}
        />
      </div>
      {message && <p style={{ fontSize: 10, color: '#c56b86', margin: '0 0 5px' }}>{message}</p>}
      <div style={{ display: 'flex', gap: 6 }}>
        <button
          onClick={async () => {
            if (!provider || !modelId.trim()) { setMessage('请选择供应商并填写模型 ID'); return; }
            setMessage('');
            const ok = await onAdd(
              provider, modelId.trim(), displayName.trim() || modelId.trim(),
              caps, Number(contextWindow) || 128000, Number(maxOutputTokens) || 8000,
            );
            if (ok) { setOpen(false); setModelId(''); setDisplayName(''); }
            else { setMessage('添加失败，请检查模型 ID 或供应商'); }
          }}
          disabled={saving}
          style={{ flex: 1, padding: '5px 8px', borderRadius: 7, border: 'none', background: 'linear-gradient(135deg, var(--color-pink), var(--color-purple))', color: '#fff', cursor: saving ? 'default' : 'pointer', fontSize: 11, fontFamily: 'inherit' }}
        >{saving ? '保存中...' : '添加模型'}</button>
        <button
          onClick={() => { setOpen(false); setMessage(''); }}
          disabled={saving}
          style={{ padding: '5px 8px', borderRadius: 7, border: 'none', background: 'transparent', color: 'var(--color-text-muted)', cursor: 'pointer', fontSize: 10, fontFamily: 'inherit' }}
        >取消</button>
      </div>
    </div>
  );
};

const ModelRoutingSection: React.FC<{ sectionStyle: React.CSSProperties }> = ({ sectionStyle }) => {
  const {
    routing, loading, saving, error, providers,
    loadProviders, addProvider, removeProvider,
    addModel, removeModel,
    saveRoutingProfile, resetRoutingProfile,
  } = useModelStore();
  const [tab, setTab] = useState<'profiles' | 'providers' | 'models' | 'routing' | 'embedding'>('profiles');

  useEffect(() => {
    loadProviders();
  }, []);

  if (loading && !routing) {
    return (
      <div style={sectionStyle}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', marginBottom: 10 }}>
          模型路由
        </div>
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>加载中...</p>
      </div>
    );
  }

  if (!routing) {
    return (
      <div style={sectionStyle}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', marginBottom: 10 }}>
          模型路由
        </div>
        <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          {error || 'V2 路由配置未加载'}
        </p>
      </div>
    );
  }

  return (
    <div style={sectionStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)' }}>
          模型路由
        </div>
        <span style={{
          fontSize: 10, padding: '1px 6px', borderRadius: 999,
          color: 'var(--color-purple-dark)',
          background: 'rgba(216, 180, 226, 0.18)',
        }}>
          M2-5 · 供应商 / 模型 / 用途
        </span>
      </div>
      <p style={{
        fontSize: 10, color: 'var(--color-text-muted)', margin: '0 0 12px',
        wordBreak: 'break-all',
      }}>
        来源：{routing.source_path || 'config/model_routing.toml'}
      </p>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 12 }}>
        {([
          ['profiles', 'Profiles'],
          ['providers', '供应商'],
          ['models', '模型'],
          ['embedding', 'Embedding'],
        ] as const).map(([id, label]) => {
          const active = tab === id;
          return (
            <button
              key={id}
              onClick={() => setTab(id)}
              style={{
                padding: '5px 9px', borderRadius: 8,
                border: active
                  ? '1px solid rgba(216, 180, 226, 0.45)'
                  : '1px solid rgba(216, 180, 226, 0.16)',
                background: active
                  ? 'linear-gradient(135deg, rgba(255,183,197,0.35), rgba(216,180,226,0.35))'
                  : 'rgba(255,255,255,0.35)',
                color: active ? 'var(--color-pink-dark)' : 'var(--color-text-muted)',
                cursor: 'pointer', fontSize: 10, fontFamily: 'inherit',
              }}
            >{label}</button>
          );
        })}
      </div>

      <div style={{ display: tab === 'providers' ? 'block' : 'none' }}>
        <RoutingBlock title="Providers">
          {Object.entries(routing.providers).map(([name, p]) => {
            const info = providers.find((item) => item.id === name);
            return (
              <div key={name} style={routingCardStyle}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                  <span style={{ fontWeight: 600, color: 'var(--color-text)' }}>{name}</span>
                  <span style={{
                    fontSize: 9, color: info?.connected ? 'var(--color-purple-dark)' : 'var(--color-text-muted)',
                  }}>
                    {info?.connected ? `已连接 · ${info.key_source || 'db'}` : '未连接'}
                  </span>
                </div>
                <div style={{ color: 'var(--color-text-muted)', marginTop: 2 }}>
                  {p.base_url || '默认地址'} · key: {p.api_key_env}
                </div>
                {info?.connected && info.key_source === 'db' && (
                  <button
                    onClick={async () => {
                      if (!window.confirm(`删除 ${name} 的本地 Key？`)) return;
                      await removeProvider(name);
                    }}
                    disabled={saving}
                    style={{
                      marginTop: 4, padding: '2px 6px', borderRadius: 5,
                      border: '1px solid rgba(197, 107, 134, 0.25)',
                      background: 'transparent', color: '#c56b86',
                      cursor: 'pointer', fontSize: 9, fontFamily: 'inherit',
                    }}
                  >删除本地 Key</button>
                )}
              </div>
            );
          })}
          <ProviderAddForm
            providers={providers}
            saving={saving}
            onAdd={(provider, apiKey, baseUrl) => addProvider(provider, apiKey, baseUrl)}
          />
          {error && (
            <p style={{ fontSize: 10, color: '#c56b86', margin: '4px 0 0' }}>{error}</p>
          )}
        </RoutingBlock>
      </div>

      <div style={{ display: tab === 'models' ? 'block' : 'none' }}>
        <RoutingBlock title="Models">
          {Object.entries(routing.models).map(([name, m]) => (
            <div key={name} style={routingCardStyle}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ fontWeight: 600, color: 'var(--color-text)' }}>{name}</span>
                <span style={{ color: 'var(--color-text-muted)' }}>{m.provider}</span>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 4 }}>
                {m.capabilities.map((cap) => (
                  <span key={cap} style={{
                    fontSize: 10, padding: '1px 6px', borderRadius: 999,
                    background: 'rgba(255, 183, 197, 0.16)',
                    color: 'var(--color-pink-dark)',
                  }}>
                    {CAP_LABELS[cap] || cap}
                  </span>
                ))}
                <span style={{ fontSize: 10, color: 'var(--color-text-muted)', alignSelf: 'center' }}>
                  ctx {Math.round(m.context_window / 1000)}k
                </span>
              </div>
              {m.source !== 'file' && (
                <button
                  onClick={async () => {
                    if (!window.confirm(`删除模型 ${name}？`)) return;
                    await removeModel(m.provider, name);
                  }}
                  disabled={saving}
                  style={{
                    marginTop: 4, padding: '2px 6px', borderRadius: 5,
                    border: '1px solid rgba(197, 107, 134, 0.25)',
                    background: 'transparent', color: '#c56b86',
                    cursor: 'pointer', fontSize: 9, fontFamily: 'inherit',
                  }}
                >删除模型</button>
              )}
            </div>
          ))}
          <ModelAddForm
            providers={Object.keys(routing.providers)}
            saving={saving}
            onAdd={(provider, modelId, displayName, capabilities, contextWindow, maxOutputTokens) =>
              addModel(provider, modelId, displayName, capabilities, contextWindow, maxOutputTokens)
            }
          />
          {error && (
            <p style={{ fontSize: 10, color: '#c56b86', margin: '4px 0 0' }}>{error}</p>
          )}
        </RoutingBlock>
      </div>

      <div style={{ display: tab === 'profiles' ? 'block' : 'none' }}>

      <RoutingBlock title="Profiles（可编辑）">
        {Object.entries(routing.profiles).map(([name, p]) => (
          <ProfileEditor
            key={`${name}:${p.model}:${p.fallbacks.join(',')}:${p.temperature}:${p.max_tokens}:${p.source}`}
            name={name}
            profile={p}
            models={routing.models}
            saving={saving}
            onSave={(patch) => saveRoutingProfile(name, patch)}
            onReset={() => resetRoutingProfile(name)}
          />
        ))}
        {error && (
          <p style={{ fontSize: 10, color: '#c56b86', margin: '4px 0 0' }}>{error}</p>
        )}
        <button
          onClick={() => void resetRoutingProfile()}
          disabled={saving}
          style={{
            marginTop: 4, padding: '4px 8px', borderRadius: 7,
            border: '1px dashed rgba(216, 180, 226, 0.3)',
            background: 'transparent', color: 'var(--color-text-muted)',
            cursor: saving ? 'default' : 'pointer', fontSize: 10,
            fontFamily: 'inherit',
          }}
        >恢复全部文件默认</button>
      </RoutingBlock>
      </div>

      <div style={{ display: tab === 'routing' ? 'block' : 'none' }}>
      <RoutingBlock title="Routing（task → profile → effective）">
        <div style={{
          display: 'grid', gridTemplateColumns: '1.1fr 0.9fr 1.5fr',
          gap: 6, fontSize: 10, color: 'var(--color-text-muted)',
          padding: '0 2px 4px',
        }}>
          <span>task</span>
          <span>profile</span>
          <span>effective</span>
        </div>
        {Object.entries(routing.effective).map(([task, r]) => (
          <div
            key={task}
            style={{
              display: 'grid', gridTemplateColumns: '1.1fr 0.9fr 1.5fr',
              gap: 6, padding: '5px 2px',
              borderTop: '1px solid rgba(216, 180, 226, 0.12)',
            }}
          >
            <code style={{ fontSize: 10, color: 'var(--color-text)' }}>{task}</code>
            <span style={{ color: 'var(--color-text-muted)' }}>{r.profile || '—'}</span>
            <span
              title={r.error || ''}
              style={{
                color: r.error ? '#c56b86' : 'var(--color-text-dim)',
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}
            >
              {r.error ? '配置错误' : `${r.provider} / ${r.model}${r.source ? ` · ${r.source}` : ''}`}
              {!r.error && r.fallbacks && r.fallbacks.length > 0
                ? ` (→ ${r.fallbacks.join(' → ')})` : ''}
            </span>
          </div>
        ))}
      </RoutingBlock>
      </div>

      <div style={{ display: tab === 'embedding' ? 'block' : 'none' }}>
      <RoutingBlock title="Embedding">
        {routing.embedding ? (
          <div style={routingCardStyle}>
            <div style={{ fontWeight: 600, color: 'var(--color-text)' }}>
              {routing.embedding.provider} / {routing.embedding.model}
            </div>
            <div style={{ color: 'var(--color-text-muted)', marginTop: 2 }}>
              {routing.embedding.dimensions} 维 · {routing.embedding.base_url || '默认地址'}
            </div>
            <div style={{ fontSize: 10, color: 'var(--color-text-muted)', marginTop: 2 }}>
              换向量模型需要重新索引，M2-3a 只读
            </div>
          </div>
        ) : (
          <p style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>未配置</p>
        )}
      </RoutingBlock>
      </div>

      <p style={{ fontSize: 10, color: 'var(--color-text-muted)', margin: 0 }}>
        供应商可添加/更新 Key；用途可编辑；路由详情不在此展示（通过 API/日志查看）。
      </p>
      <p style={{ fontSize: 9, color: 'var(--color-text-muted)', margin: '3px 0 0' }}>
        天气数据：
        <a
          href="https://open-meteo.com/"
          target="_blank"
          rel="noreferrer"
          style={{ color: 'var(--color-purple-dark)', textDecoration: 'none' }}
        >
          Open-Meteo
        </a>
        {' · '}
        <a
          href="https://creativecommons.org/licenses/by/4.0/"
          target="_blank"
          rel="noreferrer"
          style={{ color: 'var(--color-purple-dark)', textDecoration: 'none' }}
        >
          CC-BY 4.0
        </a>
      </p>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════

export const SettingsPanel: React.FC = () => {
  const clearMessages = useChatStore((s) => s.clearMessages);
  const routingV2 = useModelStore((s) => s.routingV2);
  const {
    status, loading, refreshStatus,
    doPause, doResume, updateSettings,
  } = useAutonomyStore();

  const [thresholdInput, setThresholdInput] = useState('6.0');
  const [bgFilename, setBgFilename] = useState('xilian.png');
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    refreshStatus();
    fetchBackground()
      .then((d) => setBgFilename(d.filename))
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (status) {
      setThresholdInput(String(status.threshold));
    }
  }, [status]);

  const handleReset = async () => {
    if (!window.confirm(
      '确定要重置当前会话吗？\n\n' +
      '这将清空所有对话记录，开始一段全新的对话。\n' +
      '昔涟对你的印象、记忆、笔记和好感度不会丢失。'
    )) return;
    try {
      await resetSession();
      clearMessages();
      alert('会话已重置 —— 所有对话记录已清空，开始新对话吧 ♪');
    } catch {
      alert('重置失败，请稍后再试');
    }
  };

  const handleThresholdSave = () => {
    const val = parseFloat(thresholdInput);
    if (isNaN(val) || val < 1 || val > 10) {
      alert('阈值需在 1-10 之间');
      return;
    }
    updateSettings({ greeting_threshold: val });
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const result = await uploadBackground(file);
      setBgFilename(result.filename);
      // 刷新页面背景：触发 MainLayout 重新获取
      window.dispatchEvent(new CustomEvent('background-changed', { detail: result.url }));
    } catch {
      alert('上传失败，请检查文件格式和大小（<10MB）');
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const isPaused = status?.do_not_disturb;

  const sectionStyle: React.CSSProperties = {
    background: 'rgba(255, 255, 255, 0.45)',
    backdropFilter: 'blur(12px)',
    WebkitBackdropFilter: 'blur(12px)',
    borderRadius: 'var(--radius-card)',
    padding: 16,
    marginBottom: 14,
    border: '1px solid rgba(255, 255, 255, 0.6)',
    boxShadow: '0 4px 16px rgba(180, 140, 220, 0.1)',
  };

  return (
    <div>
      <h3 style={{ fontSize: 18, fontWeight: 600, marginBottom: 2, color: 'var(--color-text)' }}>
        设置
      </h3>
      <p style={{ fontSize: 13, color: 'var(--color-text-dim)', marginBottom: 18 }}>
        调整昔涟的行为与外观
      </p>

      {/* ── 背景图片 ── */}
      <div style={sectionStyle}>
        <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)', marginBottom: 10 }}>
          背景图片
        </div>
        <div style={{ fontSize: 12, color: 'var(--color-text-dim)', marginBottom: 10 }}>
          当前：{bgFilename}
        </div>
        <input
          ref={fileRef}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          onChange={handleUpload}
          style={{ display: 'none' }}
          id="bg-upload"
        />
        <label
          htmlFor="bg-upload"
          style={{
            display: 'inline-block',
            padding: '8px 18px',
            borderRadius: 'var(--radius-btn)',
            background: uploading
              ? 'rgba(200, 180, 200, 0.3)'
              : 'linear-gradient(135deg, var(--color-pink), var(--color-purple))',
            color: '#fff',
            fontSize: 13,
            fontWeight: 500,
            cursor: uploading ? 'default' : 'pointer',
            boxShadow: '0 2px 10px rgba(255, 183, 197, 0.3)',
            transition: `all var(--duration-normal) var(--ease-spring)`,
          }}
        >
          {uploading ? '上传中...' : '选择图片上传'}
        </label>
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', marginLeft: 10 }}>
          支持 png/jpg/webp，&le;10MB
        </span>
      </div>

      {/* ── 自主问候 ── */}
      <div style={sectionStyle}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--color-text)' }}>
            自主问候
          </span>
          {status && (
            <span style={{
              fontSize: 10,
              padding: '2px 8px',
              borderRadius: 8,
              background: isPaused
                ? 'rgba(100, 140, 200, 0.12)'
                : 'rgba(255, 183, 197, 0.15)',
              color: isPaused ? 'var(--color-ice-dark)' : 'var(--color-pink-dark)',
            }}>
              {isPaused ? '已暂停' : '运行中'}
            </span>
          )}
        </div>

        {status && (
          <div style={{ fontSize: 12, color: 'var(--color-text-dim)', marginBottom: 12 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
              <span>想念值</span>
              <span style={{
                color: status.missing_value >= (status.threshold || 6)
                  ? 'var(--color-pink-dark)'
                  : 'var(--color-text-dim)',
                fontWeight: 500,
              }}>
                {status.missing_value?.toFixed(1)} / {status.threshold}
              </span>
            </div>
            <div style={{
              height: 4, borderRadius: 2,
              background: 'rgba(200, 180, 210, 0.2)',
              overflow: 'hidden',
            }}>
              <div style={{
                height: '100%',
                width: `${Math.min(100, ((status.missing_value || 0) / 10) * 100)}%`,
                background: 'linear-gradient(90deg, var(--color-pink), var(--color-purple))',
                borderRadius: 2,
                transition: 'width 0.5s var(--ease-spring)',
              }} />
            </div>
            <div style={{
              display: 'flex', justifyContent: 'space-between',
              marginTop: 6, fontSize: 11, color: 'var(--color-text-muted)',
            }}>
              <span>令牌余量</span>
              <span>{status.bucket_tokens?.toFixed(1)} / {status.bucket_capacity}</span>
            </div>
          </div>
        )}

        <div style={{ marginBottom: 12 }}>
          <label style={{ fontSize: 12, color: 'var(--color-text-dim)', display: 'block', marginBottom: 4 }}>
            触发阈值：{thresholdInput}
          </label>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <input
              type="range"
              min="1"
              max="10"
              step="0.5"
              value={thresholdInput}
              onChange={(e) => setThresholdInput(e.target.value)}
              onMouseUp={handleThresholdSave}
              onTouchEnd={handleThresholdSave}
              style={{ flex: 1, accentColor: 'var(--color-pink)' }}
            />
            <button
              onClick={handleThresholdSave}
              style={{
                padding: '4px 12px', borderRadius: 8, border: 'none',
                background: 'rgba(255, 183, 197, 0.18)',
                color: 'var(--color-pink-dark)', cursor: 'pointer', fontSize: 12,
              }}
            >
              保存
            </button>
          </div>
        </div>

        <button
          onClick={() => isPaused ? doResume() : doPause()}
          style={{
            width: '100%', padding: '8px 12px', borderRadius: 8,
            border: isPaused
              ? '1px solid rgba(162, 196, 230, 0.25)'
              : '1px solid rgba(255, 183, 197, 0.2)',
            background: isPaused
              ? 'rgba(162, 196, 230, 0.08)'
              : 'rgba(255, 183, 197, 0.06)',
            color: isPaused ? 'var(--color-ice-dark)' : 'var(--color-pink-dark)',
            cursor: 'pointer', fontSize: 13,
            transition: `all var(--duration-normal) var(--ease-spring)`,
          }}
        >
          {isPaused ? '恢复自主问候' : '暂停自主问候'}
        </button>
      </div>

      {/* ── 模型设置（V3.4: 多供应商 / M2: 声明式路由只读）── */}
      {routingV2
        ? <ModelRoutingSection sectionStyle={sectionStyle} />
        : <ModelSettingsSection sectionStyle={sectionStyle} />}

      {/* ── 会话重置 ── */}
      <div>
        <button
          onClick={handleReset}
          style={{
            width: '100%',
            padding: '10px 16px',
            borderRadius: 'var(--radius-btn)',
            border: '1px solid rgba(200, 100, 120, 0.15)',
            background: 'rgba(200, 100, 120, 0.05)',
            color: 'var(--color-text-dim)',
            cursor: 'pointer',
            fontSize: 13,
            transition: `all var(--duration-normal) var(--ease-spring)`,
          }}
        >
          重置当前会话
        </button>
      </div>
    </div>
  );
};
