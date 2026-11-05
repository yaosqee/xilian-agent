"""ModelRouter — 多供应商模型路由核心

V3.3 → V3.4 升级：硬编码 DeepSeek Pro/Flash 二分 → Tier 系统 + Provider Adapter 委派。

路由流程:
    V1（默认）: task_type → tier (TASK_TIER_MAP) → TierConfig → adapter.chat()
    V2（MODEL_ROUTING_V2=1）: task_type → profile → model + fallbacks → adapter.chat()

向后兼容:
    仅设置 DEEPSEEK_API_KEY 的用户自动使用 DeepSeekAdapter，行为完全不变。
    新增供应商只需配置 DB 或 .env 中的对应 API Key。
"""
from __future__ import annotations

import json
import os
import time as _time_module

from loguru import logger

import importlib

from .providers import (
    TaskType, TASK_TIER_MAP, TierConfig, ProviderResponse, TaskOverride,
    ModelPolicy, policy_from_adapter,
    DEFAULT_TIER_MODELS, DEFAULT_EMBED_MODELS, detect_configured_providers,
    PROVIDER_REGISTRY,
)
from .providers.base import ProviderAdapter
from .model_stats import ModelStatsRegistry

# tool 相关错误先重试一次；只有连续失败才临时禁用 tools
TOOL_DEGRADE_SECONDS = 900  # 15 分钟

# Re-export for backward compat
__all__ = [
    "ModelRouter",
    "TaskType",
    "ToolRelatedError",
]


class ToolRelatedError(Exception):
    """工具调用相关错误——触发模型降级（移除 tools 参数重试）。"""
    pass


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


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

        # ── M2: 声明式路由（默认关闭，保持旧 tier 路径不变）──
        self._routing_v2 = _env_flag("MODEL_ROUTING_V2", False)
        self._routing_config = None
        self._routing_file = None

        # ── Adapter cache: provider_name → ProviderAdapter ──
        self._adapters: dict[str, ProviderAdapter] = {}

        # ── Tier configs: tier_name → TierConfig ──
        self._tier_configs: dict[str, TierConfig] = {}

        # ── Task overrides: task_type → TaskOverride (from DB) ──
        self._task_overrides: dict[str, TaskOverride] = {}

        # ── Embed config (separate from tier configs) ──
        self._embed_config: dict | None = None  # {provider, model_name, base_url, api_key, dimensions}

        # ── Tool compatibility cache（兼容旧字段；新逻辑用 disabled_until）──
        self._tools_support_cache: dict[str, bool] = {}
        self._tools_disabled_until: dict[str, float] = {}
        self._tools_cache_reset_interval = 86400  # 兼容旧行为
        self._tools_cache_last_reset = _time_module.time()

        # ── 显式能力矩阵 + 观测 ──
        self._model_policies: dict[str, ModelPolicy] = {}
        self._stats = ModelStatsRegistry()

        # ── Lazy init: create default DeepSeek adapter immediately ──
        self._init_default_adapter()
        if self._routing_v2:
            self._load_routing_config()

        logger.info(
            "ModelRouter 就绪 (multi-provider mode)",
            adapters=list(self._adapters.keys()),
            tiers=list(self._tier_configs.keys()),
            routing_v2=self._routing_v2,
        )

    @property
    def routing_v2(self) -> bool:
        return self._routing_v2

    @property
    def routing_config(self):
        return self._routing_config

    def _load_routing_config(self) -> None:
        """加载并校验 `config/model_routing.toml`；失败直接抛出，不静默回退。"""
        from .model_config import load_model_routing

        config = load_model_routing()
        self._routing_file = config
        self._routing_config = config
        self._model_policies.clear()
        logger.info(
            "model_router.routing_v2_loaded",
            path=str(config.source_path) if config.source_path else "",
            models=sorted(config.models),
            profiles=sorted(config.profiles),
        )

    def _apply_routing_overrides(self, rows: list[dict]) -> None:
        """把 DB `source='ui'` 的 `profile:*` 行合入文件基线。

        坏覆盖只告警并忽略，避免一条脏数据让进程起不来；写入侧会先校验。
        """
        if not self._routing_v2 or self._routing_file is None:
            return

        overrides: dict[str, dict] = {}
        for row in rows:
            key = str(row.get("config_key") or "")
            source = str(row.get("source") or "legacy")
            if not key.startswith("profile:") or source != "ui":
                continue
            name = key.split(":", 1)[1]
            raw_fallbacks = row.get("fallbacks") or "[]"
            try:
                fallbacks = json.loads(raw_fallbacks) if isinstance(raw_fallbacks, str) else raw_fallbacks
            except (TypeError, ValueError):
                fallbacks = []
            overrides[name] = {
                "model": row.get("model_name"),
                "fallbacks": fallbacks if isinstance(fallbacks, list) else [],
                "temperature": row.get("temperature", 0.7),
                "max_tokens": row.get("max_tokens", 800),
            }

        if not overrides:
            self._routing_config = self._routing_file
            self._model_policies.clear()
            return

        try:
            self._routing_config = self._routing_file.with_profile_overrides(overrides)
            logger.info(
                "model_router.routing_overrides_loaded",
                profiles=sorted(overrides),
            )
        except Exception as exc:
            self._routing_config = self._routing_file
            logger.warning(
                "model_router.routing_overrides_ignored",
                error=f"{type(exc).__name__}: {exc}"[:300],
            )
        self._model_policies.clear()

    def _resolve_routing_v2(self, task_type: str, tools: list | None = None):
        """解析 M2 路由；tools 非空时把 tools 能力加入硬性要求。"""
        if self._routing_config is None:
            raise RuntimeError("MODEL_ROUTING_V2=1 但路由配置未加载")
        extra = ("tools",) if tools else ()
        return self._routing_config.resolve(task_type, extra_requires=extra)

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
                # 对话默认 Flash：Pro 成本高，评测/新库都应与生产一致
                self._tier_configs["powerful"] = TierConfig(
                    tier="powerful", provider="deepseek",
                    model_name="deepseek-flash", temperature=0.65, max_tokens=800,
                )
                self._tier_configs["fast"] = TierConfig(
                    tier="fast", provider="deepseek",
                    model_name="deepseek-flash", temperature=0.3, max_tokens=800,
                )
                self._tier_configs["reasoning"] = TierConfig(
                    tier="reasoning", provider="deepseek",
                    model_name="deepseek-reasoner", temperature=0.3, max_tokens=2000,
                )

                # Embed config (from env, may use SiliconFlow)
                embed_key = os.getenv("EMBED_API_KEY") or os.getenv("DEEPSEEK_API_KEY_2") or ds_key
                embed_base = os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
                embed_model = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
                # EMBED_PROVIDER 显式指定优先，否则从 base_url 推断
                embed_provider = os.getenv("EMBED_PROVIDER", "")
                if not embed_provider:
                    embed_provider = "siliconflow" if "siliconflow" in embed_base else "deepseek"
                self._embed_config = {
                    "provider": embed_provider,
                    "model_name": embed_model,
                    "base_url": embed_base,
                    "api_key": embed_key,
                    "dimensions": 1024,
                }
            else:
                logger.error("ModelRouter: DeepSeek adapter 创建失败，请检查 deepseek SDK 是否安装")
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
        if self._routing_v2:
            # 配置文件可能在热重载时被修改；先重新校验，失败则保留旧配置。
            self._load_routing_config()

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

            if self._routing_v2:
                self._apply_routing_overrides(db_configs)

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
        """创建指定供应商的 adapter。从 PROVIDER_REGISTRY 懒导入。

        创建后自动从 ModelInfo 预热 _tools_support_cache，
        避免依赖运行时 tool error 检测（节省一次 API 往返）。
        """
        entry = PROVIDER_REGISTRY.get(provider)
        if not entry:
            logger.warning("model_router.unknown_provider", provider=provider)
            return None

        module_path, class_name, lazy_import = entry
        try:
            mod = importlib.import_module(module_path)
            cls = getattr(mod, class_name)
            adapter = cls()

            # ── 预热 tool compatibility cache ──
            try:
                for m in adapter.get_available_models():
                    if not m.supports_tools:
                        self._tools_support_cache[f"{provider}:{m.id}"] = False
            except Exception:
                pass  # get_available_models 失败不影响 adapter 创建

            return adapter
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
            if not self._routing_v2:
                logger.warning("model_router.reload_no_db")
                return

        # 保存旧配置供回退（dict() 值拷贝，避免 initialize() 的 .clear() 清空引用）
        old_adapters = dict(self._adapters)
        old_tiers = dict(self._tier_configs)
        old_overrides = dict(self._task_overrides)
        old_embed = dict(self._embed_config) if self._embed_config else None
        old_routing = self._routing_config
        old_routing_file = self._routing_file

        try:
            await self.initialize()
            logger.info("model_router.reloaded", providers=list(self._adapters.keys()))
        except Exception as e:
            # 回退
            self._adapters = old_adapters
            self._tier_configs = old_tiers
            self._task_overrides = old_overrides
            self._embed_config = old_embed
            self._routing_config = old_routing
            self._routing_file = old_routing_file
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

        V1（默认）:
          1. 解析 task_type → tier
          2. 检查 task_type 覆盖
          3. 解析 tier → provider + model
          4. 调用 adapter.chat()

        V2（MODEL_ROUTING_V2=1）:
          1. 从声明式配置解析 task → profile → model + fallbacks
          2. 创建/复用 provider adapter
          3. 调用 adapter.chat()；显式参数优先于 profile 默认值

        Returns:
            ProviderResponse (normal) or raw stream object (when stream=True)
        """
        # ── 1. 解析 tier（V2 用声明式配置，V1 保持旧 tier 路径）──
        tier = TASK_TIER_MAP.get(task_type, "powerful")
        tier_cfg = self._tier_configs.get(tier)
        v2_route = None

        if self._routing_v2:
            v2_route = self._resolve_routing_v2(task_type, tools)
            tier = v2_route.profile
            tier_cfg = TierConfig(
                tier=v2_route.profile,
                provider=v2_route.provider,
                model_name=v2_route.model,
                temperature=v2_route.temperature,
                max_tokens=v2_route.max_tokens,
            )
        else:
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
        if v2_route is not None:
            provider = v2_route.provider
            adapter = self._adapters.get(provider)
            if adapter is None:
                adapter = self._create_adapter(provider)
                if adapter is not None:
                    self._adapters[provider] = adapter
            if adapter is None:
                raise RuntimeError(
                    f"MODEL_ROUTING_V2 选中的供应商 '{provider}' 不可用；"
                    "请检查对应 API Key。"
                )
            model = v2_route.model
            # 显式传入的温度/max_tokens 优先；否则用 profile 默认值。
            kwargs.setdefault("temperature", v2_route.temperature)
            kwargs.setdefault("max_tokens", v2_route.max_tokens)
            logger.debug(
                "model_router.routing_v2",
                task=task_type,
                profile=v2_route.profile,
                provider=provider,
                model=model,
                fallback=v2_route.capability_fallback,
            )
        elif tier_cfg is None:
            # 无配置 → fallback 到第一个可用 adapter
            if self._adapters:
                provider = next(iter(self._adapters.keys()))
                adapter = self._adapters[provider]
                model = DEFAULT_TIER_MODELS.get(provider, {}).get(tier, f"{provider}-default")
                logger.warning("model_router.no_tier_config", tier=tier,
                             fallback_provider=provider, fallback_model=model)
                # Set sensible defaults even in fallback path
                kwargs.setdefault("temperature", 0.7)
                kwargs.setdefault("max_tokens", 800)
            else:
                raise RuntimeError(
                    "没有可用的模型供应商。请配置至少一个 API Key（如 DEEPSEEK_API_KEY）。"
                )
        else:
            provider = tier_cfg.provider
            adapter = self._adapters.get(provider)
            if adapter is not None:
                # Adapter found directly — use tier_cfg as-is
                model = tier_cfg.model_name
                kwargs.setdefault("temperature", tier_cfg.temperature)
                kwargs.setdefault("max_tokens", tier_cfg.max_tokens)
            else:
                # Adapter 未加载 → 尝试创建
                adapter = self._create_adapter(provider)
                if adapter:
                    self._adapters[provider] = adapter
                    model = tier_cfg.model_name
                    kwargs.setdefault("temperature", tier_cfg.temperature)
                    kwargs.setdefault("max_tokens", tier_cfg.max_tokens)
                else:
                    # 回退到任意可用 adapter
                    if not self._adapters:
                        raise RuntimeError(f"供应商 '{provider}' 不可用且无其他可用供应商。")
                    fallback_provider = next(iter(self._adapters.keys()))
                    adapter = self._adapters[fallback_provider]
                    fallback_model = DEFAULT_TIER_MODELS.get(fallback_provider, {}).get(tier, tier_cfg.model_name)
                    logger.warning("model_router.provider_fallback",
                                 requested=provider, fallback=fallback_provider,
                                 requested_model=tier_cfg.model_name, fallback_model=fallback_model)
                    provider = fallback_provider
                    model = fallback_model
                    # Use fallback defaults, not the unavailable tier_cfg's
                    kwargs.setdefault("temperature", 0.7)
                    kwargs.setdefault("max_tokens", 800)

        # ── 4. Tool compatibility check ──
        model_key = f"{provider}:{model}"
        if tools and not self._supports_tools(model_key):
            logger.info("model_router.tools_degraded_active", model=model_key)
            tools = None
            tool_choice = None

        common = {
            "model": model,
            "messages": messages,
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 800),
            "stream": kwargs.get("stream", False),
        }

        # ── 5. Call adapter ──
        try:
            result = await self._invoke(
                adapter, model_key, tools=tools, tool_choice=tool_choice, **common
            )
            # ── 5b. 空回复 / 截断重试 ──
            # thinking 模型可能把 max_tokens 预算烧在 reasoning_content 上，
            # 导致 content 为空、finish_reason="length"。裸的「……♪」兜底会掩盖这次失败。
            return await self._retry_if_empty(
                result, adapter, model_key, model, messages, tools, tool_choice, kwargs,
            )
        except Exception as e:
            if not tools:
                raise

            skip_same_retry = False

            # 5c-1. tool_choice 兼容性错误（如 DeepSeek thinking 模式）→ 改 auto 重试一次
            if _is_tool_choice_error(e) and tool_choice not in (None, "auto"):
                skip_same_retry = True
                self._stats.get(model_key).tool_retries += 1
                logger.warning(
                    "model_router.tool_choice_retry",
                    model=model_key,
                    error=str(e)[:160],
                )
                try:
                    result = await self._invoke(
                        adapter, model_key, tools=tools, tool_choice="auto", **common
                    )
                    logger.info("model_router.tool_choice_retry_ok", model=model_key)
                    return await self._retry_if_empty(
                        result, adapter, model_key, model, messages, tools, "auto", kwargs,
                    )
                except Exception as auto_error:
                    e = auto_error
                    if not _is_tool_error(e):
                        raise

            # 5c-2. 普通 tool error → 先原样重试一次，仍失败才降级
            if not skip_same_retry and _is_tool_error(e):
                self._stats.get(model_key).tool_retries += 1
                logger.warning(
                    "model_router.tool_error_retry",
                    model=model_key,
                    error=str(e)[:160],
                )
                try:
                    result = await self._invoke(
                        adapter, model_key, tools=tools, tool_choice=tool_choice, **common
                    )
                    logger.info("model_router.tool_error_recovered", model=model_key)
                    return await self._retry_if_empty(
                        result, adapter, model_key, model, messages, tools, tool_choice, kwargs,
                    )
                except Exception as retry_error:
                    e = retry_error
                    if not _is_tool_error(e):
                        logger.error(
                            "model_router.tool_retry_failed",
                            model=model_key,
                            error=str(e)[:200],
                        )
                        raise

            if not _is_tool_error(e):
                raise

            # 5c-3. 连续失败 → 临时禁用 tools（15 分钟），并明确记录
            self._disable_tools(model_key, str(e))
            try:
                result = await self._invoke(
                    adapter, model_key, tools=None, tool_choice=None, **common
                )
                return await self._retry_if_empty(
                    result, adapter, model_key, model, messages, None, None, kwargs,
                )
            except Exception as retry_error:
                logger.error(
                    "model_router.tool_retry_failed",
                    model=model_key,
                    original_error=str(e)[:200],
                    retry_error=str(retry_error)[:200],
                )
                raise retry_error from e

    async def _retry_if_empty(
        self, result, adapter, model_key, model, messages, tools, tool_choice, kwargs,
    ):
        """空回复或截断时，提高预算重试一次。

        触发条件（任一）：
          - content 为空且没有 tool_calls（模型什么都没说）
          - finish_reason == "length"（输出被 max_tokens 截断）

        重试仍失败时原样返回，由上层（AgentCore）走显式降级，不再伪装成正常台词。
        流式响应（raw stream）不重试。
        """
        if not hasattr(result, "content"):
            return result  # raw stream，交给上层处理

        content = (result.content or "").strip()
        finish_reason = getattr(result, "finish_reason", None)
        empty = not content and not getattr(result, "tool_calls", None)
        truncated = finish_reason == "length"

        if not (empty or truncated):
            return result

        base_max = int(kwargs.get("max_tokens") or 800)
        retry_max = max(base_max * 2, 1500)
        logger.warning(
            "model_router.empty_retry",
            model=model,
            reason="empty" if empty else "truncated",
            finish_reason=finish_reason,
            max_tokens=retry_max,
            content_len=len(content),
        )

        try:
            retry = await self._invoke(
                adapter, model_key,
                model=model,
                messages=messages,
                temperature=kwargs.get("temperature", 0.7),
                max_tokens=retry_max,
                stream=False,
                tools=tools,
                tool_choice=tool_choice,
            )
        except Exception as e:
            logger.error("model_router.empty_retry_failed", model=model, error=str(e)[:200])
            return result

        if not hasattr(retry, "content"):
            return retry

        retry_content = (retry.content or "").strip()
        if retry_content or getattr(retry, "tool_calls", None):
            logger.info(
                "model_router.empty_retry_ok",
                model=model,
                content_len=len(retry_content),
                finish_reason=getattr(retry, "finish_reason", None),
            )
            return retry

        logger.error(
            "model_router.empty_retry_still_empty",
            model=model,
            max_tokens=retry_max,
            finish_reason=getattr(retry, "finish_reason", None),
        )
        return retry

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
    # Model policy + observability
    # ══════════════════════════════════════════════════════════

    def get_model_policy(self, provider: str, model: str) -> ModelPolicy:
        """返回显式能力矩阵（tools / vision / context / cost）。"""
        return self._policy_for(provider, model)

    def _policy_for(self, provider: str, model: str) -> ModelPolicy:
        key = f"{provider}:{model}"
        if key in self._model_policies:
            return self._model_policies[key]
        if self._routing_v2 and self._routing_config is not None:
            try:
                policy = self._routing_config.policy_for(model)
            except Exception:
                policy = None
            if policy is not None:
                self._model_policies[key] = policy
                return policy
        adapter = self._adapters.get(provider)
        if adapter is not None:
            policy = policy_from_adapter(adapter, provider, model)
        else:
            policy = ModelPolicy(provider=provider, model=model)
        self._model_policies[key] = policy
        return policy

    @property
    def stats(self) -> dict[str, dict]:
        """按模型统计：成功/失败/超时/空回复/降级/p95 延迟。"""
        return self._stats.snapshot()

    def reset_stats(self) -> None:
        self._stats.reset()

    async def _invoke(self, adapter: ProviderAdapter, model_key: str, **call_kwargs):
        """调用 adapter 并记录观测；不改变异常语义。"""
        stats = self._stats.get(model_key) if hasattr(self, "_stats") else None
        if stats is not None:
            stats.record_call()
        started = _time_module.monotonic()
        try:
            result = await adapter.chat(**call_kwargs)
        except Exception as exc:
            if stats is not None:
                stats.record_error(exc, (_time_module.monotonic() - started) * 1000)
                if _is_tool_error(exc):
                    stats.tool_errors += 1
            raise
        if stats is not None:
            stats.record_success(result, (_time_module.monotonic() - started) * 1000)
        return result

    def _disable_tools(self, model_key: str, reason: str) -> None:
        """连续 tool 失败后临时禁用 tools，而不是静默 24 小时。"""
        until = _time_module.time() + TOOL_DEGRADE_SECONDS
        self._tools_disabled_until[model_key] = until
        self._tools_support_cache[model_key] = False
        self._stats.get(model_key).degraded += 1
        logger.warning(
            "model_router.tools_degraded",
            model=model_key,
            reason=reason[:160],
            ttl_seconds=TOOL_DEGRADE_SECONDS,
        )

    # ══════════════════════════════════════════════════════════
    # Tool compatibility
    # ══════════════════════════════════════════════════════════

    def _supports_tools(self, model_key: str) -> bool:
        """显式能力矩阵 + 临时降级窗口。"""
        provider, _, model = model_key.partition(":")
        policy = self._policy_for(provider, model)
        if not policy.supports_tools:
            return False

        now = _time_module.time()
        until = self._tools_disabled_until.get(model_key)
        if until is not None:
            if now < until:
                return False
            self._tools_disabled_until.pop(model_key, None)
            self._tools_support_cache.pop(model_key, None)
            logger.info("model_router.tools_reenabled", model=model_key)

        # V2: 配置文件是能力事实，不再让旧缓存覆盖它。
        if self._routing_v2:
            return True

        # 兼容旧缓存字段（测试/旧调用方可能直接写入）
        return self._tools_support_cache.get(model_key, True)

    # ══════════════════════════════════════════════════════════
    # Multimodal support
    # ══════════════════════════════════════════════════════════

    def supports_vision(self, provider: str, model: str) -> bool:
        """检查指定模型是否支持视觉输入（image）。"""
        if self._routing_v2 and self._routing_config is not None:
            try:
                return self._routing_config.policy_for(model).supports_vision
            except Exception:
                pass
        adapter = self._adapters.get(provider)
        if adapter is None:
            return False
        try:
            models = adapter.get_available_models()
            for m in models:
                if m.id == model or m.name == model:
                    return "image" in m.input_modalities
        except Exception:
            pass
        return False

    def get_current_model_info(self) -> tuple[str, str]:
        """返回当前对话使用的 (provider, model_name)。

        优先检查 task_override（chat），因为 route() 也会先查 override。
        否则返回 powerful tier 配置。
        """
        # ── 1. 检查 chat task override（与 route() 行为保持一致）──
        if self._routing_v2 and self._routing_config is not None:
            try:
                route = self._routing_config.resolve("chat")
                return route.provider, route.model
            except Exception:
                pass

        override = self._task_overrides.get("chat")
        if override:
            return override.provider, override.model_name

        # ── 2. Powerful tier 配置 ──
        tier = self._tier_configs.get("powerful")
        if tier:
            return tier.provider, tier.model_name

        # ── 3. Fallback ──
        if self._adapters:
            provider = next(iter(self._adapters.keys()))
            return provider, DEFAULT_TIER_MODELS.get(provider, {}).get("powerful", "")
        return "deepseek", "deepseek-v4-pro"

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
            model_override = "deepseek:deepseek-flash"
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

        return await self._invoke(
            adapter, f"{provider}:{model}",
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

def _is_tool_choice_error(e: Exception) -> bool:
    """是否只是 tool_choice 参数不被当前模型/模式接受（可退回 auto）。"""
    msg = str(e).lower()
    if "tool_choice" not in msg and "tool choice" not in msg:
        return False
    return any(
        kw in msg
        for kw in ("not support", "does not support", "invalid", "unsupported")
    )


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
