"""声明式模型路由配置（M2-1）。

只做「加载 / 校验 / 解析」，不接 `ModelRouter`，不改变现有路由行为。

配置结构：

    providers  -> base_url + api_key_env（密钥只从环境变量读）
    models     -> 能力 / 上下文 / 成本
    profiles   -> 主模型 + fallbacks + 温度 / max_tokens
    routing_groups / routing -> task_type → profile

入口：

    from packages.shared.model_config import load_model_routing

    config = load_model_routing()
    route = config.resolve("chat")
    route.model, route.provider, route.fallbacks
"""
from __future__ import annotations

import os
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from packages.shared.providers import TASK_GROUPS, TASK_TIER_MAP
from packages.shared.providers.model_policy import ModelPolicy

DEFAULT_CONFIG_PATH = Path("config/model_routing.toml")


def default_config_path() -> Path:
    """开发用项目根；frozen 优先 exe 同级 config，其次 PyInstaller 解包目录。"""
    if getattr(sys, "frozen", False):
        external = Path(sys.executable).resolve().parent / "config" / "model_routing.toml"
        if external.exists():
            return external
        bundle_dir = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        return bundle_dir / "config" / "model_routing.toml"
    return Path(__file__).resolve().parents[2] / "config" / "model_routing.toml"
CONFIG_VERSION = 1

# 允许的能力名：未知能力应当报错，避免拼写错误被静默忽略。
SUPPORTED_CAPABILITIES = frozenset({"tools", "vision", "streaming", "thinking"})

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_SECRET_KEYS = frozenset({"api_key", "apikey", "secret"})


class ModelConfigError(ValueError):
    """配置缺失、格式错误或引用无效。"""


def _table(value: Any, where: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ModelConfigError(f"{where} 必须是表（table）")
    return value


def _as_str(value: Any, where: str, *, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        raise ModelConfigError(f"{where} 必须是字符串")
    return value


def _as_int(value: Any, where: str, *, default: int) -> int:
    if value is None:
        return default
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"{where} 必须是整数") from exc
    return result


def _as_float(value: Any, where: str, *, default: float) -> float:
    if value is None:
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ModelConfigError(f"{where} 必须是数字") from exc
    return result


def _as_str_list(value: Any, where: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ModelConfigError(f"{where} 必须是字符串数组")
    return tuple(value)


def _interpolate(value: str, env: Mapping[str, str], where: str) -> str:
    """替换 `${VAR}`；缺失环境变量直接报错，避免把占位符带进运行时。"""
    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in env:
            raise ModelConfigError(f"{where} 引用了未设置的环境变量 ${{{name}}}")
        return env[name]

    return _ENV_PATTERN.sub(replace, value)


def _reject_plaintext_secrets(value: Any, where: str = "root") -> None:
    """配置文件只允许 api_key_env；出现明文密钥直接拒绝。"""
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in _SECRET_KEYS:
                raise ModelConfigError(
                    f"{where}.{key} 不允许写明文密钥，请改用 api_key_env"
                )
            _reject_plaintext_secrets(child, f"{where}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_plaintext_secrets(child, f"{where}[{index}]")
    elif isinstance(value, str) and value.startswith("sk-"):
        raise ModelConfigError(f"{where} 疑似包含明文 API Key，请改用 api_key_env")


@dataclass(frozen=True)
class ProviderSpec:
    """一个供应商；api_key 不落配置，只记录环境变量名。"""

    name: str
    base_url: str = ""
    api_key_env: str = ""

    def resolve_api_key(self, env: Mapping[str, str] | None = None) -> str:
        if not self.api_key_env:
            return ""
        return (env or os.environ).get(self.api_key_env, "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
        }


@dataclass(frozen=True)
class ModelSpec:
    name: str
    provider: str
    capabilities: frozenset[str] = frozenset()
    context_window: int = 128_000
    max_output_tokens: int = 8_000
    cost_per_1k_in: float = 0.0
    cost_per_1k_out: float = 0.0
    known_failures: tuple[str, ...] = ()

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_policy(self) -> ModelPolicy:
        return ModelPolicy(
            provider=self.provider,
            model=self.name,
            supports_tools=self.supports("tools"),
            supports_vision=self.supports("vision"),
            supports_streaming=self.supports("streaming"),
            supports_thinking=self.supports("thinking"),
            context_window=self.context_window,
            max_output_tokens=self.max_output_tokens,
            cost_per_1k_in=self.cost_per_1k_in,
            cost_per_1k_out=self.cost_per_1k_out,
            known_failures=self.known_failures,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "capabilities": sorted(self.capabilities),
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "cost_per_1k_in": self.cost_per_1k_in,
            "cost_per_1k_out": self.cost_per_1k_out,
            "known_failures": list(self.known_failures),
        }


@dataclass(frozen=True)
class ProfileSpec:
    name: str
    model: str
    fallbacks: tuple[str, ...] = ()
    temperature: float = 0.7
    max_tokens: int = 800
    requires: tuple[str, ...] = ()
    source: str = "file"

    @property
    def candidates(self) -> tuple[str, ...]:
        return (self.model, *self.fallbacks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "fallbacks": list(self.fallbacks),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "requires": list(self.requires),
            "source": self.source,
        }


@dataclass(frozen=True)
class EmbeddingSpec:
    provider: str
    model: str
    dimensions: int = 1024
    base_url: str = ""
    api_key_env: str = ""

    def resolve_api_key(self, env: Mapping[str, str] | None = None) -> str:
        if not self.api_key_env:
            return ""
        return (env or os.environ).get(self.api_key_env, "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "dimensions": self.dimensions,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
        }


@dataclass(frozen=True)
class ResolvedRoute:
    task_type: str
    profile: str
    model: str
    provider: str
    temperature: float
    max_tokens: int
    fallbacks: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    source: str = "file"
    capability_fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "profile": self.profile,
            "model": self.model,
            "provider": self.provider,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "fallbacks": list(self.fallbacks),
            "requires": list(self.requires),
            "source": self.source,
            "capability_fallback": self.capability_fallback,
        }


@dataclass
class ModelRoutingConfig:
    version: int
    providers: dict[str, ProviderSpec]
    models: dict[str, ModelSpec]
    profiles: dict[str, ProfileSpec]
    routing: dict[str, str]
    routing_groups: dict[str, str]
    embedding: EmbeddingSpec | None = None
    source_path: Path | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # ── 构造 / 校验 ──────────────────────────────────────

    @classmethod
    def from_dict(
        cls,
        data: Mapping[str, Any],
        *,
        source_path: str | Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> "ModelRoutingConfig":
        if not isinstance(data, Mapping):
            raise ModelConfigError("配置根节点必须是 TOML table")
        _reject_plaintext_secrets(data)

        env_map = dict(os.environ if env is None else env)
        version = _as_int(data.get("version"), "version", default=CONFIG_VERSION)
        if version != CONFIG_VERSION:
            raise ModelConfigError(
                f"不支持的配置版本 {version}，当前只支持 {CONFIG_VERSION}"
            )

        providers = _parse_providers(_table(data.get("providers"), "providers"), env_map)
        models = _parse_models(
            _table(data.get("models"), "models"), providers
        )
        profiles = _parse_profiles(
            _table(data.get("profiles"), "profiles"), models
        )
        routing_groups = _parse_routing_groups(
            _table(data.get("routing_groups"), "routing_groups"), profiles
        )
        routing = _parse_routing(
            _table(data.get("routing"), "routing"), profiles
        )
        embedding = _parse_embedding(
            _table(data.get("embedding"), "embedding"), providers, env_map
        )

        if not profiles:
            raise ModelConfigError("profiles 不能为空")
        if not routing and not routing_groups:
            raise ModelConfigError("routing 与 routing_groups 至少配置一个")

        return cls(
            version=version,
            providers=providers,
            models=models,
            profiles=profiles,
            routing=routing,
            routing_groups=routing_groups,
            embedding=embedding,
            source_path=Path(source_path) if source_path else None,
            raw=dict(data),
        )

    # ── 解析 ─────────────────────────────────────────────

    def policy_for(self, model_name: str) -> ModelPolicy:
        model = self.models.get(model_name)
        if model is None:
            raise ModelConfigError(f"未知模型: {model_name}")
        return model.to_policy()

    def resolve(
        self,
        task_type: str,
        *,
        source: str | None = None,
        extra_requires: tuple[str, ...] | list[str] = (),
    ) -> ResolvedRoute:
        """按 task → profile → 主模型/fallback 解析出实际路由。

        `extra_requires` 用于运行时追加硬性能力（如调用方传了 tools 时要求 tools），
        不影响配置文件里的 profile.requires。
        """
        profile_name = self.routing.get(task_type)
        if profile_name is None:
            group = _group_for_task(task_type)
            profile_name = self.routing_groups.get(group)

        if not profile_name:
            raise ModelConfigError(
                f"task_type={task_type!r} 没有匹配的 routing/routing_groups"
            )

        profile = self.profiles.get(profile_name)
        if profile is None:
            raise ModelConfigError(
                f"task_type={task_type!r} 引用了未知 profile {profile_name!r}"
            )

        required = tuple(dict.fromkeys((*profile.requires, *extra_requires)))
        candidates = profile.candidates
        selected_index: int | None = None
        for index, model_name in enumerate(candidates):
            model = self.models.get(model_name)
            if model is None:
                raise ModelConfigError(
                    f"profile {profile_name!r} 的模型 {model_name!r} 未在 [models] 定义"
                )
            if all(model.supports(cap) for cap in required):
                selected_index = index
                break

        if selected_index is None:
            raise ModelConfigError(
                f"profile {profile_name!r} 没有满足能力 {list(required)} 的模型"
            )

        selected = candidates[selected_index]
        model = self.models[selected]
        return ResolvedRoute(
            task_type=task_type,
            profile=profile_name,
            model=selected,
            provider=model.provider,
            temperature=profile.temperature,
            max_tokens=profile.max_tokens,
            fallbacks=candidates[selected_index + 1:],
            requires=required,
            source=source or profile.source,
            capability_fallback=selected_index > 0,
        )

    def with_catalog(
        self,
        providers: Mapping[str, Mapping[str, Any]],
        models: Mapping[str, Mapping[str, Any]],
    ) -> "ModelRoutingConfig":
        """把 DB 供应商/模型目录合入配置（不覆盖已有 profile/routing）。"""
        merged_providers = dict(self.providers)
        for name, data in providers.items():
            if not name:
                continue
            existing = merged_providers.get(name)
            merged_providers[name] = ProviderSpec(
                name=name,
                base_url=_as_str(
                    data.get("base_url"), f"provider:{name}.base_url",
                    default=existing.base_url if existing else "",
                ),
                api_key_env=(
                    existing.api_key_env if existing
                    else f"{name.upper()}_API_KEY"
                ),
            )

        merged_models = dict(self.models)
        for name, data in models.items():
            if not name:
                continue
            provider = _as_str(
                data.get("provider"), f"model:{name}.provider",
                default=(merged_models[name].provider if name in merged_models else ""),
            )
            if not provider:
                raise ModelConfigError(f"model:{name}.provider 不能为空")
            caps_raw = data.get("capabilities", [])
            if isinstance(caps_raw, str):
                import json as _json
                try:
                    caps_raw = _json.loads(caps_raw)
                except (TypeError, ValueError):
                    caps_raw = []
            capabilities = tuple(str(item) for item in caps_raw)
            unknown = set(capabilities) - SUPPORTED_CAPABILITIES
            if unknown:
                raise ModelConfigError(
                    f"model:{name}.capabilities 包含未知能力: {sorted(unknown)}"
                )
            merged_models[name] = ModelSpec(
                name=name,
                provider=provider,
                capabilities=frozenset(capabilities),
                context_window=_as_int(
                    data.get("context_window"), f"model:{name}.context_window",
                    default=(merged_models[name].context_window if name in merged_models else 128_000),
                ),
                max_output_tokens=_as_int(
                    data.get("max_output_tokens"), f"model:{name}.max_output_tokens",
                    default=(merged_models[name].max_output_tokens if name in merged_models else 8_000),
                ),
                cost_per_1k_in=_as_float(
                    data.get("cost_per_1k_in"), f"model:{name}.cost",
                    default=(merged_models[name].cost_per_1k_in if name in merged_models else 0.0),
                ),
                cost_per_1k_out=_as_float(
                    data.get("cost_per_1k_out"), f"model:{name}.cost_out",
                    default=(merged_models[name].cost_per_1k_out if name in merged_models else 0.0),
                ),
            )

        return ModelRoutingConfig(
            version=self.version,
            providers=merged_providers,
            models=merged_models,
            profiles=self.profiles,
            routing=self.routing,
            routing_groups=self.routing_groups,
            embedding=self.embedding,
            source_path=self.source_path,
            raw=self.raw,
        )

    def with_profile_overrides(
        self,
        overrides: Mapping[str, Mapping[str, Any]],
    ) -> "ModelRoutingConfig":
        """把 DB `source='ui'` 的 profile 覆盖合入配置，返回新对象。"""
        if not overrides:
            return self

        profiles = dict(self.profiles)
        for name, patch in overrides.items():
            base = profiles.get(name)
            if base is None:
                raise ModelConfigError(f"覆盖引用未知 profile: {name!r}")

            model = _as_str(patch.get("model"), f"profile:{name}.model", default=base.model)
            if model not in self.models:
                raise ModelConfigError(f"profile:{name}.model 引用未知模型 {model!r}")

            raw_fallbacks = patch.get("fallbacks", base.fallbacks)
            if isinstance(raw_fallbacks, (list, tuple)):
                fallbacks = tuple(str(item) for item in raw_fallbacks)
            else:
                raise ModelConfigError(f"profile:{name}.fallbacks 必须是数组")
            for fallback in fallbacks:
                if fallback not in self.models:
                    raise ModelConfigError(
                        f"profile:{name}.fallbacks 引用未知模型 {fallback!r}"
                    )

            temperature = _as_float(
                patch.get("temperature"), f"profile:{name}.temperature",
                default=base.temperature,
            )
            if not 0.0 <= temperature <= 2.0:
                raise ModelConfigError(f"profile:{name}.temperature 必须在 0..2 之间")
            max_tokens = _as_int(
                patch.get("max_tokens"), f"profile:{name}.max_tokens",
                default=base.max_tokens,
            )
            if max_tokens <= 0:
                raise ModelConfigError(f"profile:{name}.max_tokens 必须大于 0")

            candidates = (model, *fallbacks)
            if not any(
                all(self.models[item].supports(cap) for cap in base.requires)
                for item in candidates
            ):
                raise ModelConfigError(
                    f"profile:{name} 没有满足能力 {list(base.requires)} 的候选模型"
                )

            profiles[name] = ProfileSpec(
                name=name,
                model=model,
                fallbacks=fallbacks,
                temperature=temperature,
                max_tokens=max_tokens,
                requires=base.requires,
                source="ui",
            )

        return ModelRoutingConfig(
            version=self.version,
            providers=self.providers,
            models=self.models,
            profiles=profiles,
            routing=self.routing,
            routing_groups=self.routing_groups,
            embedding=self.embedding,
            source_path=self.source_path,
            raw=self.raw,
        )

    def effective_routes(self, *, source: str | None = None) -> dict[str, dict[str, Any]]:
        """返回所有已注册 task 的生效路由，便于 API / 面板展示。"""
        result: dict[str, dict[str, Any]] = {}
        for task_type in sorted(TASK_TIER_MAP):
            try:
                result[task_type] = self.resolve(task_type, source=source).to_dict()
            except ModelConfigError as exc:
                result[task_type] = {"error": str(exc)}
        return result

    def resolve_api_key(
        self,
        provider_name: str,
        *,
        env: Mapping[str, str] | None = None,
    ) -> str:
        provider = self.providers.get(provider_name)
        if provider is None:
            raise ModelConfigError(f"未知供应商: {provider_name}")
        return provider.resolve_api_key(env)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "providers": {
                name: item.to_dict() for name, item in self.providers.items()
            },
            "models": {
                name: item.to_dict() for name, item in self.models.items()
            },
            "profiles": {
                name: item.to_dict() for name, item in self.profiles.items()
            },
            "routing": dict(self.routing),
            "routing_groups": dict(self.routing_groups),
            "embedding": self.embedding.to_dict() if self.embedding else None,
        }


def _parse_providers(
    data: dict[str, Any],
    env: Mapping[str, str],
) -> dict[str, ProviderSpec]:
    providers: dict[str, ProviderSpec] = {}
    for name, value in data.items():
        where = f"providers.{name}"
        table = _table(value, where)
        api_key_env = _as_str(table.get("api_key_env"), f"{where}.api_key_env")
        if not api_key_env:
            raise ModelConfigError(f"{where}.api_key_env 不能为空")
        providers[name] = ProviderSpec(
            name=name,
            base_url=_interpolate(
                _as_str(table.get("base_url"), f"{where}.base_url"), env, f"{where}.base_url"
            ),
            api_key_env=api_key_env,
        )
    return providers


def _parse_models(
    data: dict[str, Any],
    providers: dict[str, ProviderSpec],
) -> dict[str, ModelSpec]:
    models: dict[str, ModelSpec] = {}
    for name, value in data.items():
        where = f"models.{name}"
        table = _table(value, where)
        provider = _as_str(table.get("provider"), f"{where}.provider")
        if provider not in providers:
            raise ModelConfigError(f"{where}.provider 引用了未知供应商 {provider!r}")

        capabilities = _as_str_list(table.get("capabilities"), f"{where}.capabilities")
        unknown = set(capabilities) - SUPPORTED_CAPABILITIES
        if unknown:
            raise ModelConfigError(
                f"{where}.capabilities 包含未知能力: {sorted(unknown)}"
            )

        known_failures = _as_str_list(
            table.get("known_failures"), f"{where}.known_failures"
        )
        models[name] = ModelSpec(
            name=name,
            provider=provider,
            capabilities=frozenset(capabilities),
            context_window=_as_int(
                table.get("context_window"), f"{where}.context_window",
                default=128_000,
            ),
            max_output_tokens=_as_int(
                table.get("max_output_tokens"), f"{where}.max_output_tokens",
                default=8_000,
            ),
            cost_per_1k_in=_as_float(
                table.get("cost_per_1k_in"), f"{where}.cost_per_1k_in", default=0.0,
            ),
            cost_per_1k_out=_as_float(
                table.get("cost_per_1k_out"), f"{where}.cost_per_1k_out", default=0.0,
            ),
            known_failures=known_failures,
        )
    return models


def _parse_profiles(
    data: dict[str, Any],
    models: dict[str, ModelSpec],
) -> dict[str, ProfileSpec]:
    profiles: dict[str, ProfileSpec] = {}
    for name, value in data.items():
        where = f"profiles.{name}"
        table = _table(value, where)
        model = _as_str(table.get("model"), f"{where}.model")
        if model not in models:
            raise ModelConfigError(f"{where}.model 引用了未知模型 {model!r}")

        fallbacks = _as_str_list(table.get("fallbacks"), f"{where}.fallbacks")
        for fallback in fallbacks:
            if fallback not in models:
                raise ModelConfigError(
                    f"{where}.fallbacks 引用了未知模型 {fallback!r}"
                )

        requires = _as_str_list(table.get("requires"), f"{where}.requires")
        unknown = set(requires) - SUPPORTED_CAPABILITIES
        if unknown:
            raise ModelConfigError(
                f"{where}.requires 包含未知能力: {sorted(unknown)}"
            )

        temperature = _as_float(table.get("temperature"), f"{where}.temperature", default=0.7)
        if not 0.0 <= temperature <= 2.0:
            raise ModelConfigError(f"{where}.temperature 必须在 0..2 之间")

        max_tokens = _as_int(table.get("max_tokens"), f"{where}.max_tokens", default=800)
        if max_tokens <= 0:
            raise ModelConfigError(f"{where}.max_tokens 必须大于 0")

        profiles[name] = ProfileSpec(
            name=name,
            model=model,
            fallbacks=fallbacks,
            temperature=temperature,
            max_tokens=max_tokens,
            requires=requires,
        )
    return profiles


def _parse_routing_groups(
    data: dict[str, Any],
    profiles: dict[str, ProfileSpec],
) -> dict[str, str]:
    groups: dict[str, str] = {}
    for group, profile in data.items():
        where = f"routing_groups.{group}"
        if group not in TASK_GROUPS:
            raise ModelConfigError(
                f"{where} 不是已知任务组（可用: {sorted(TASK_GROUPS)}）"
            )
        profile_name = _as_str(profile, where)
        if profile_name not in profiles:
            raise ModelConfigError(f"{where} 引用了未知 profile {profile_name!r}")
        groups[group] = profile_name
    return groups


def _parse_routing(
    data: dict[str, Any],
    profiles: dict[str, ProfileSpec],
) -> dict[str, str]:
    routing: dict[str, str] = {}
    known_tasks = set(TASK_TIER_MAP)
    for task_type, profile in data.items():
        where = f"routing.{task_type}"
        if task_type not in known_tasks:
            raise ModelConfigError(
                f"{where} 不是已知 task_type（可用: {sorted(known_tasks)}）"
            )
        profile_name = _as_str(profile, where)
        if profile_name not in profiles:
            raise ModelConfigError(f"{where} 引用了未知 profile {profile_name!r}")
        routing[task_type] = profile_name
    return routing


def _parse_embedding(
    data: dict[str, Any],
    providers: dict[str, ProviderSpec],
    env: Mapping[str, str],
) -> EmbeddingSpec | None:
    if not data:
        return None

    provider = _as_str(data.get("provider"), "embedding.provider")
    if provider not in providers:
        raise ModelConfigError(f"embedding.provider 引用了未知供应商 {provider!r}")
    model = _as_str(data.get("model"), "embedding.model")
    if not model:
        raise ModelConfigError("embedding.model 不能为空")
    api_key_env = _as_str(data.get("api_key_env"), "embedding.api_key_env")
    if not api_key_env:
        raise ModelConfigError("embedding.api_key_env 不能为空")

    dimensions = _as_int(data.get("dimensions"), "embedding.dimensions", default=1024)
    if dimensions <= 0:
        raise ModelConfigError("embedding.dimensions 必须大于 0")

    return EmbeddingSpec(
        provider=provider,
        model=model,
        dimensions=dimensions,
        base_url=_interpolate(
            _as_str(data.get("base_url"), "embedding.base_url"),
            env,
            "embedding.base_url",
        ),
        api_key_env=api_key_env,
    )


def _group_for_task(task_type: str) -> str:
    for group, tasks in TASK_GROUPS.items():
        if task_type in tasks:
            return group
    return "dialogue"


def load_model_routing(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> ModelRoutingConfig:
    """从 TOML 加载并校验；路径默认 `config/model_routing.toml`。

    `MODEL_ROUTING_CONFIG` 可覆盖路径（测试/打包用）。
    """
    config_path = Path(
        path or os.getenv("MODEL_ROUTING_CONFIG") or default_config_path()
    )
    if not config_path.exists():
        raise ModelConfigError(f"模型路由配置不存在: {config_path}")

    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ModelConfigError(f"TOML 解析失败 {config_path}: {exc}") from exc
    except OSError as exc:
        raise ModelConfigError(f"读取模型路由配置失败 {config_path}: {exc}") from exc

    return ModelRoutingConfig.from_dict(
        data,
        source_path=config_path,
        env=env,
    )
