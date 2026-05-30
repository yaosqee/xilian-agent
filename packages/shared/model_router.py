"""ModelRouter — 多供应商模型路由核心

V3.3 → V3.4 升级：硬编码 DeepSeek Pro/Flash 二分 → Tier 系统 + Provider Adapter 委派。

路由流程:
    task_type → tier (TASK_TIER_MAP) → TierConfig (provider + model) → adapter.chat()

向后兼容:
    仅设置 DEEPSEEK_API_KEY 的用户自动使用 DeepSeekAdapter，行为完全不变。
    新增供应商只需配置 DB 或 .env 中的对应 API Key。
"""
from __future__ import annotations

import asyncio
import os
import time as _time_module
from typing import Literal

import httpx
from loguru import logger

import importlib

from .providers import (
    TaskType, TierName,
    TASK_TIER_MAP, TierConfig, ProviderResponse, TaskOverride,
    DEFAULT_TIER_MODELS, DEFAULT_EMBED_MODELS, detect_configured_providers,
    PROVIDER_REGISTRY,
)
from .providers.base import ProviderAdapter

# Re-export for backward compat
__all__ = [
    "ModelRouter",
    "TaskType",
    "ToolRelatedError",
]


class ToolRelatedError(Exception):
    """工具调用相关错误——触发模型降级（移除 tools 参数重试）。"""
    pass


class ModelRouter:
    """多供应商模型路由器。

    用法:
        router = ModelRouter()
        await router.initialize()     # Phase B: async init with DB config
        # 或不调 initialize()，自动使用 DeepSeek-only 默认配置

        response = await router.route("chat", messages, tools=...)
        print(response.content)
    """

    def __init__(self, db=None):
        """
        Args:
            db: DatabaseManager (optional). Needed for DB-backed tier config and hot-reload.
                If None, uses env-vars only (backward compat).
        """
        self._db = db

        # ── Adapter cache: provider_name → ProviderAdapter ──
        self._adapters: dict[str, ProviderAdapter] = {}

        # ── Tier configs: tier_name → TierConfig ──
        self._tier_configs: dict[str, TierConfig] = {}

        # ── Task overrides: task_type → TaskOverride (from DB) ──
        self._task_overrides: dict[str, TaskOverride] = {}

        # ── Embed config (separate from tier configs) ──
        self._embed_config: dict | None = None  # {provider, model_name, base_url, api_key, dimensions}

        # ── Tool compatibility cache (per model_key, 24h TTL) ──
        self._tools_support_cache: dict[str, bool] = {}
        self._tools_cache_reset_interval = 86400  # 24h
        self._tools_cache_last_reset = _time_module.time()

        # ── Lazy init: create default DeepSeek adapter immediately ──
        self._init_default_adapter()

        logger.info(
            "ModelRouter 就绪 (multi-provider mode)",
            adapters=list(self._adapters.keys()),
            tiers=list(self._tier_configs.keys()),
        )

    def _init_default_adapter(self):
        """Create default DeepSeek adapter from env vars (backward compat).

        Auto-detects:
        - If DEEPSEEK_API_KEY is set → create DeepSeekAdapter, map deepseek models to all tiers
        - If no keys at all → empty (will fail on first route() with clear error)
        """
        ds_key = os.getenv("DEEPSEEK_API_KEY")
        if ds_key:
            adapter = self._create_adapter("deepseek")
            if adapter:
                self._adapters["deepseek"] = adapter

            # Default tier configs (all tiers use DeepSeek)
            self._tier_configs["powerful"] = TierConfig(
                tier="powerful", provider="deepseek",
                model_name="deepseek-v4-pro", temperature=0.65, max_tokens=800,
            )
            self._tier_configs["fast"] = TierConfig(
                tier="fast", provider="deepseek",
                model_name="deepseek-v4-flash", temperature=0.3, max_tokens=800,
            )
            self._tier_configs["reasoning"] = TierConfig(
                tier="reasoning", provider="deepseek",
                model_name="deepseek-reasoner", temperature=0.3, max_tokens=2000,
            )

            # Embed config (from env, may use SiliconFlow)
            embed_key = os.getenv("EMBED_API_KEY") or os.getenv("DEEPSEEK_API_KEY_2") or ds_key
            embed_base = os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
            embed_model = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
            embed_provider = "siliconflow" if "siliconflow" in embed_base else "deepseek"
            self._embed_config = {
                "provider": embed_provider,
                "model_name": embed_model,
                "base_url": embed_base,
                "api_key": embed_key,
                "dimensions": 1024,
            }
        else:
            logger.warning("ModelRouter: 未检测到任何 API Key，需引导配置")

    # ══════════════════════════════════════════════════════════
    # Phase B: DB-backed initialization
    # ══════════════════════════════════════════════════════════

    async def initialize(self):
        """异步初始化：从 DB 加载 tier 配置并创建适配器。

        若 DB 无配置，fallback 到 _init_default_adapter() 的结果。
        调用时机：agent.startup() 完成后（DB 已初始化）。
        """
        if not self._db:
            logger.info("model_router.no_db — using env-var defaults")
            return

        try:
            # 加载 tier 配置
            db_configs = await self._db.get_model_configs()
            if db_configs:
                self._adapters.clear()
                self._tier_configs.clear()
                self._task_overrides.clear()

                for row in db_configs:
                    key = row["config_key"]
                    if key.startswith("tier:"):
                        tier = key.split(":", 1)[1]
                        self._tier_configs[tier] = TierConfig(
                            tier=tier,
                            provider=row["provider"],
                            model_name=row["model_name"],
                            temperature=row.get("temperature", 0.7),
                            max_tokens=row.get("max_tokens", 800),
                            is_active=bool(row.get("is_active", 1)),
                        )
                    elif key.startswith("override:"):
                        task_type = key.split(":", 1)[1]
                        self._task_overrides[task_type] = TaskOverride(
                            task_type=task_type,
                            provider=row["provider"],
                            model_name=row["model_name"],
                        )

                # 创建各 provider 的 adapter
                await self._create_adapters_from_configs()
                logger.info(
                    "model_router.db_loaded",
                    tiers=list(self._tier_configs.keys()),
                    adapters=list(self._adapters.keys()),
                    overrides=list(self._task_overrides.keys()),
                )
            else:
                # DB 无配置 → auto-seed from env vars
                await self._auto_seed_db()

            # 加载 embed 配置
            db_embed = await self._db.get_embed_config()
            if db_embed:
                self._embed_config = db_embed

        except Exception as e:
            logger.warning("model_router.db_load_failed", error=str(e))

    async def _auto_seed_db(self):
        """首次升级：从 .env 检测现有配置，自动播种 DB。"""
        if not self._db:
            return

        providers = detect_configured_providers()
        if not providers:
            return

        # 确定主供应商
        primary = "deepseek" if "deepseek" in providers else providers[0]

        # 写入 tier 配置
        now = _time_module.time()
        tier_defaults = DEFAULT_TIER_MODELS.get(primary, DEFAULT_TIER_MODELS["deepseek"])
        for tier, model in tier_defaults.items():
            api_key = os.getenv(f"{primary.upper()}_API_KEY", "")
            # Per-tier defaults
            if tier == "powerful":
                temp, mt = 0.65, 800
            elif tier == "reasoning":
                temp, mt = 0.3, 2000
            else:
                temp, mt = 0.3, 800
            try:
                await self._db.insert_model_config(
                    config_key=f"tier:{tier}",
                    provider=primary,
                    model_name=model,
                    api_key=api_key,
                    temperature=temp,
                    max_tokens=mt,
                    is_active=1,
                    created_at=now,
                    updated_at=now,
                )
            except Exception:
                pass  # 可能已存在（唯一约束冲突）

            # 更新内存中的 tier config
            self._tier_configs[tier] = TierConfig(
                tier=tier, provider=primary, model_name=model,
                temperature=temp, max_tokens=mt,
            )

        # 写入 embed 配置（仅当 EMBED_API_KEY 实际配置时）
        if os.getenv("EMBED_API_KEY"):
            embed_defaults = DEFAULT_EMBED_MODELS.get("siliconflow")
            try:
                await self._db.insert_embed_config(
                    provider=embed_defaults["provider"],
                    model_name=embed_defaults["model_name"],
                    api_key=os.getenv("EMBED_API_KEY", ""),
                    base_url=embed_defaults["base_url"],
                    dimensions=embed_defaults["dimensions"],
                    is_active=1,
                    created_at=now,
                    updated_at=now,
                )
                self._embed_config = dict(embed_defaults, api_key=os.getenv("EMBED_API_KEY", ""))
            except Exception:
                pass

        logger.info("model_router.auto_seeded", primary=primary, tiers=list(tier_defaults.keys()))

    async def _create_adapters_from_configs(self):
        """从 tier configs 创建各 provider 的 adapter 实例。"""
        for tier_cfg in self._tier_configs.values():
            provider = tier_cfg.provider
            if provider not in self._adapters:
                adapter = self._create_adapter(provider)
                if adapter:
                    self._adapters[provider] = adapter

    def _create_adapter(self, provider: str) -> ProviderAdapter | None:
        """创建指定供应商的 adapter。从 PROVIDER_REGISTRY 懒导入。"""
        entry = PROVIDER_REGISTRY.get(provider)
        if not entry:
            logger.warning("model_router.unknown_provider", provider=provider)
            return None

        module_path, class_name, lazy_import = entry
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            return cls()
        except ImportError as e:
            if lazy_import:
                logger.warning(f"{provider}_adapter.import_failed", error=str(e))
            else:
                logger.error(f"{provider}_adapter.import_failed", error=str(e))
            return None

    # ══════════════════════════════════════════════════════════
    # Hot reload
    # ══════════════════════════════════════════════════════════

    async def reload_config(self):
        """热重载配置（无需重启进程）。

        从 DB 重新读取 tier configs，重建 adapter 实例。
        asyncio 下原子引用替换，线程安全。
        """
        if not self._db:
            logger.warning("model_router.reload_no_db")
            return

        # 保存旧配置供回退（dict() 值拷贝，避免 initialize() 的 .clear() 清空引用）
        old_adapters = dict(self._adapters)
        old_tiers = dict(self._tier_configs)
        old_overrides = dict(self._task_overrides)
        old_embed = dict(self._embed_config) if self._embed_config else None

        try:
            await self.initialize()
            logger.info("model_router.reloaded", providers=list(self._adapters.keys()))
        except Exception as e:
            # 回退
            self._adapters = old_adapters
            self._tier_configs = old_tiers
            self._task_overrides = old_overrides
            self._embed_config = old_embed
            logger.error("model_router.reload_failed", error=str(e))
            raise

    # ══════════════════════════════════════════════════════════
    # Route — main entry point
    # ══════════════════════════════════════════════════════════

    async def route(
        self,
        task_type: TaskType,
        messages: list,
        tools: list | None = None,
        tool_choice: str | None = None,
        **kwargs,
    ) -> ProviderResponse | object:
        """路由主入口。

        1. 解析 task_type → tier
        2. 检查 task_type 覆盖
        3. 解析 tier → provider + model
        4. 调用 adapter.chat()

        Returns:
            ProviderResponse (normal) or raw stream object (when stream=True)
        """
        # ── 1. 解析 tier ──
        tier = TASK_TIER_MAP.get(task_type, "powerful")
        tier_cfg = self._tier_configs.get(tier)

        # ── 2. 检查 task_type 覆盖（高级设置）──
        override = self._task_overrides.get(task_type)
        if override:
            tier_cfg = TierConfig(
                tier=tier,
                provider=override.provider,
                model_name=override.model_name,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 800),
            )

        # ── 3. 获取 adapter ──
        if tier_cfg is None:
            # 无配置 → fallback 到第一个可用 adapter
            if self._adapters:
                provider = next(iter(self._adapters.keys()))
                adapter = self._adapters[provider]
                model = DEFAULT_TIER_MODELS.get(provider, {}).get(tier, f"{provider}-default")
                logger.warning("model_router.no_tier_config", tier=tier,
                             fallback_provider=provider, fallback_model=model)
            else:
                raise RuntimeError(
                    "没有可用的模型供应商。请配置至少一个 API Key（如 DEEPSEEK_API_KEY）。"
                )
        else:
            provider = tier_cfg.provider
            adapter = self._adapters.get(provider)
            if adapter is None:
                # Adapter 未加载 → 尝试创建
                adapter = self._create_adapter(provider)
                if adapter:
                    self._adapters[provider] = adapter
                else:
                    # 回退到任意可用 adapter
                    if not self._adapters:
                        raise RuntimeError(f"供应商 '{provider}' 不可用且无其他可用供应商。")
                    fallback_provider = next(iter(self._adapters.keys()))
                    adapter = self._adapters[fallback_provider]
                    logger.warning("model_router.provider_fallback",
                                 requested=provider, fallback=fallback_provider)
                    provider = fallback_provider

            model = tier_cfg.model_name
            # Merge tier-level defaults with call-site kwargs
            kwargs.setdefault("temperature", tier_cfg.temperature)
            kwargs.setdefault("max_tokens", tier_cfg.max_tokens)

        # ── 4. Tool compatibility check ──
        model_key = f"{provider}:{model}"
        if tools and not self._supports_tools(model_key):
            logger.info("model_router.tools_degraded", model=model_key)
            tools = None
            tool_choice = None

        # ── 5. Call adapter ──
        try:
            result = await adapter.chat(
                model=model,
                messages=messages,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=kwargs.get("max_tokens", 800),
                stream=kwargs.get("stream", False),
                tools=tools,
                tool_choice=tool_choice,
            )
            return result
        except Exception as e:
            # Tool error → mark incompatible and retry without tools
            if tools and _is_tool_error(e):
                logger.warning("model_router.tool_error", model=model_key, error=str(e))
                self._tools_support_cache[model_key] = False
                return await adapter.chat(
                    model=model,
                    messages=messages,
                    temperature=kwargs.get("temperature", 0.7),
                    max_tokens=kwargs.get("max_tokens", 800),
                    stream=kwargs.get("stream", False),
                    tools=None,
                    tool_choice=None,
                )
            raise

    # ══════════════════════════════════════════════════════════
    # Embedding
    # ══════════════════════════════════════════════════════════

    @property
    def _embed_model(self) -> str:
        """Backward compat: model name used for embeddings."""
        if self._embed_config:
            return self._embed_config.get("model_name", "BAAI/bge-m3")
        return os.getenv("EMBED_MODEL", "BAAI/bge-m3")

    async def embed(self, text: str) -> list[float] | None:
        """单文本嵌入。

        优先使用 embed_config 的 provider，fallback 到 DeepSeekAdapter 的 embed。
        """
        config = self._embed_config
        if config:
            provider = config.get("provider", "deepseek")
            adapter = self._adapters.get(provider)
            if adapter and adapter.supports_embedding:
                result = await adapter.embed(config.get("model_name"), [text])
                if result:
                    return result[0]

        # Fallback: use any adapter that supports embedding
        for adapter in self._adapters.values():
            if adapter.supports_embedding:
                result = await adapter.embed(self._embed_model, [text])
                if result:
                    return result[0]

        logger.debug("embed.unavailable")
        return None

    async def embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        """批量嵌入。"""
        config = self._embed_config
        if config:
            provider = config.get("provider", "deepseek")
            adapter = self._adapters.get(provider)
            if adapter and adapter.supports_embedding:
                return await adapter.embed(config.get("model_name"), texts)

        # Fallback
        for adapter in self._adapters.values():
            if adapter.supports_embedding:
                return await adapter.embed(self._embed_model, texts)

        logger.debug("embed_batch.unavailable")
        return None

    # ══════════════════════════════════════════════════════════
    # Tool compatibility
    # ══════════════════════════════════════════════════════════

    def _supports_tools(self, model_key: str) -> bool:
        """检查模型是否支持工具调用。

        每日自动重置缓存（避免因临时故障永久禁用工具）。
        """
        now = _time_module.time()
        if now - self._tools_cache_last_reset > self._tools_cache_reset_interval:
            self._tools_support_cache.clear()
            self._tools_cache_last_reset = now
            logger.debug("model_router.tools_cache_reset")
        return self._tools_support_cache.get(model_key, True)

    # ══════════════════════════════════════════════════════════
    # Manual override (for testing / debugging)
    # ══════════════════════════════════════════════════════════

    async def route_with_override(
        self, task_type, messages, model_override=None, **kwargs
    ) -> ProviderResponse | object:
        """手动指定模型覆盖，用于对比测试。

        Args:
            model_override: "ds_pro" | "ds" | "ds_flash" | "{provider}:{model}"
        """
        if model_override is None:
            return await self.route(task_type, messages, **kwargs)

        # Legacy names
        if model_override in ("ds_pro", "ds"):
            model_override = "deepseek:deepseek-v4-pro"
        elif model_override == "ds_flash":
            model_override = "deepseek:deepseek-v4-flash"
        elif model_override == "qwen":
            model_override = "qwen:qwen3.6-plus"

        if ":" in model_override:
            provider, model = model_override.split(":", 1)
        else:
            provider, model = "deepseek", model_override

        adapter = self._adapters.get(provider)
        if not adapter:
            adapter = self._create_adapter(provider)
            if adapter:
                self._adapters[provider] = adapter
            else:
                raise RuntimeError(f"无法创建供应商 '{provider}' 的适配器")

        return await adapter.chat(
            model=model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            max_tokens=kwargs.get("max_tokens", 800),
            stream=kwargs.get("stream", False),
            tools=kwargs.get("tools"),
            tool_choice=kwargs.get("tool_choice"),
        )


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _is_tool_error(e: Exception) -> bool:
    """Check if an exception is caused by tool call incompatibility.

    Keywords are intentionally narrow to avoid false positives.
    "tools not supported" / "invalid tool" / "does not support tools"
    are specific error messages from providers when tools are unsupported.
    Generic words like "tool" or "function" alone are too broad.
    """
    if isinstance(e, ToolRelatedError):
        return True
    msg = str(e).lower()
    tool_keywords = [
        "tools not supported",
        "invalid tool",
        "does not support tool",
        "tools are not supported",
        "tool_choice is not supported",
    ]
    return any(kw in msg for kw in tool_keywords)
