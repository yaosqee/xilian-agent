"""供应商验证与目录导入（M2-5c）。

设置面板和首次引导共用这一层，避免两套添加逻辑。
"""
from __future__ import annotations

import asyncio
import importlib

from .providers import PROVIDER_REGISTRY


KNOWN_PROVIDERS = frozenset({"deepseek", "openai", "anthropic", "google"})

DEFAULT_BASE_URLS = {
    "deepseek": "https://api.deepseek.com",
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
}


async def validate_provider_key(
    provider: str,
    api_key: str,
    base_url: str | None = None,
) -> None:
    """验证 Key；失败抛 RuntimeError，消息可直接展示给用户。"""
    if provider not in KNOWN_PROVIDERS:
        raise RuntimeError(f"暂不支持供应商 {provider}")
    if not api_key:
        raise RuntimeError("API Key 不能为空")

    target_base = base_url or DEFAULT_BASE_URLS[provider]
    if provider == "anthropic":
        from anthropic import AsyncAnthropic
        client = AsyncAnthropic(api_key=api_key, base_url=target_base)
        await asyncio.wait_for(
            client.messages.create(
                model="claude-haiku-4-6",
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            ),
            timeout=15,
        )
    else:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=api_key, base_url=target_base)
        await asyncio.wait_for(client.models.list(), timeout=10)


def static_model_catalog(provider: str) -> list[dict]:
    """从 adapter 的静态 get_available_models() 生成 DB catalog 行。"""
    entry = PROVIDER_REGISTRY.get(provider)
    if not entry:
        return []
    module_path, class_name, _lazy = entry
    try:
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        rows = []
        for model in cls.get_available_models():
            caps = []
            if model.supports_tools:
                caps.append("tools")
            if model.supports_streaming:
                caps.append("streaming")
            if model.supports_thinking:
                caps.append("thinking")
            if "image" in (model.input_modalities or []):
                caps.append("vision")
            rows.append({
                "model_id": model.id,
                "display_name": model.name,
                "capabilities": caps,
                "context_window": model.context_window,
                "max_output_tokens": model.max_output_tokens,
                "source": "builtin",
            })
        return rows
    except Exception:
        return []


async def save_provider(
    db,
    provider: str,
    api_key: str,
    base_url: str = "",
) -> list[dict]:
    """验证并保存供应商 + 静态模型目录；返回导入的模型行。"""
    await validate_provider_key(provider, api_key, base_url or None)
    models = static_model_catalog(provider)
    await db.upsert_model_provider(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        key_source="db",
    )
    if models:
        await db.replace_model_catalog(provider, models)
    return models
