import { create } from 'zustand';
import type {
  ProviderInfo, TierModelConfig, ModelConfigResponse, RoutingConfigData,
} from '../services/api';
import {
  fetchModelProviders,
  fetchModelConfig,
  saveModelConfig,
  resetModelOverrides,
  validateApiKey,
} from '../services/api';

interface ModelState {
  // Provider catalog (static list from API)
  providers: ProviderInfo[];
  providersLoading: boolean;

  // Current config
  tiers: Record<string, TierModelConfig>;
  overrides: Record<string, TierModelConfig>;
  embedConfig: { provider: string; model: string; base_url?: string } | null;
  adapters: string[];
  routingV2: boolean;
  routing: RoutingConfigData | null;

  // UI state
  loading: boolean;
  saving: boolean;
  error: string | null;

  // Actions
  loadProviders: () => Promise<void>;
  loadConfig: () => Promise<void>;
  updateConfig: (tier: string, provider: string, model: string) => Promise<boolean>;
  addProviderKey: (provider: string, apiKey: string, baseUrl?: string) => Promise<boolean>;
  saveRoutingProfile: (
    name: string,
    patch: {
      provider?: string;
      model: string;
      fallbacks: string[];
      temperature: number;
      max_tokens: number;
    },
  ) => Promise<boolean>;
  resetRoutingProfile: (name?: string) => Promise<boolean>;
}

export const useModelStore = create<ModelState>((set, get) => ({
  providers: [],
  providersLoading: false,
  tiers: {},
  overrides: {},
  embedConfig: null,
  adapters: [],
  routingV2: false,
  routing: null,
  loading: false,
  saving: false,
  error: null,

  loadProviders: async () => {
    set({ providersLoading: true });
    try {
      const data = await fetchModelProviders();
      set({ providers: data.providers, providersLoading: false });
    } catch {
      set({ providersLoading: false });
    }
  },

  loadConfig: async () => {
    set({ loading: true });
    try {
      const data: ModelConfigResponse = await fetchModelConfig();
      if (!(data as any).error) {
        set({
          tiers: data.tiers || {},
          overrides: data.overrides || {},
          embedConfig: data.embed || null,
          adapters: data.adapters || [],
          routingV2: data.routing_v2 === true,
          routing: data.routing || null,
          loading: false,
          error: null,
        });
      } else {
        set({ loading: false, error: (data as any).error });
      }
    } catch (e: any) {
      set({ loading: false, error: e.message || 'Failed to load model config' });
    }
  },

  updateConfig: async (tier: string, provider: string, model: string) => {
    set({ saving: true, error: null });
    try {
      const result = await saveModelConfig({
        tiers: {
          [tier]: { provider, model },
        },
      });
      if (result.status === 'ok' || result.status === 'partial') {
        // Reload config to get fresh state
        await get().loadConfig();
        set({ saving: false });
        return true;
      }
      set({ saving: false, error: result.errors?.join(', ') || 'Save failed' });
      return false;
    } catch (e: any) {
      set({ saving: false, error: e.message || 'Save failed' });
      return false;
    }
  },

  addProviderKey: async (provider: string, apiKey: string, baseUrl?: string) => {
    set({ error: null });
    try {
      const result = await validateApiKey(provider, apiKey);
      if (result.valid) {
        // Key is valid — save it with current provider's default model
        const existingTier = get().tiers['powerful'];
        const defaultModels: Record<string, string> = {
          openai: 'gpt-5.4-mini',
          anthropic: 'claude-haiku-4-6',
          google: 'gemini-2.5-flash',
        };
        const model = defaultModels[provider] || 'deepseek-flash';

        const patch: any = {
          api_keys: { [provider]: apiKey },
        };
        if (baseUrl) {
          patch.base_urls = { [provider]: baseUrl };
        }
        if (!existingTier || existingTier.provider !== provider) {
          patch.tiers = { powerful: { provider, model }, fast: { provider, model } };
        }
        await saveModelConfig(patch);
        await get().loadConfig();
        return true;
      }
      set({ error: result.error || 'API Key 验证失败' });
      return false;
    } catch (e: any) {
      set({ error: e.message || '验证失败' });
      return false;
    }
  },

  saveRoutingProfile: async (name, patch) => {
    set({ saving: true, error: null });
    try {
      const result = await saveModelConfig({
        profiles: { [name]: patch },
      });
      if (result.status === 'ok' || result.status === 'partial') {
        await get().loadConfig();
        set({ saving: false });
        return true;
      }
      set({ saving: false, error: result.errors?.join(', ') || '保存失败' });
      return false;
    } catch (e: any) {
      set({ saving: false, error: e.message || '保存失败' });
      return false;
    }
  },

  resetRoutingProfile: async (name) => {
    set({ saving: true, error: null });
    try {
      const result = await resetModelOverrides(name ? [name] : undefined);
      if (result.status === 'ok' || result.status === 'partial') {
        await get().loadConfig();
        set({ saving: false });
        return true;
      }
      set({ saving: false, error: result.errors?.join(', ') || '恢复失败' });
      return false;
    } catch (e: any) {
      set({ saving: false, error: e.message || '恢复失败' });
      return false;
    }
  },
}));
