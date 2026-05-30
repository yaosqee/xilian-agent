"""
DeepSeekAdapter — DeepSeek V4-Pro / V4-Flash provider.

Extracted from the original ModelRouter._call_ds_pro / _call_ds_flash methods.
Supports dual-key round-robin for Pro, and optional Flash client.
"""
from __future__ import annotations

import asyncio
import os
import time as _time_module
from typing import Literal

import httpx
from loguru import logger
from openai import AsyncOpenAI

from .base import ModelInfo, ProviderAdapter
from . import ProviderResponse, extract_tool_calls, extract_usage

# ── Available models ─────────────────────────────────────────

DEEPSEEK_MODELS = [
    ModelInfo(
        id="deepseek-v4-pro",
        name="V4 Pro",
        provider="deepseek",
        cost_per_1k_in=0.00174,
        cost_per_1k_out=0.00348,
        supports_tools=True,
        supports_thinking=True,
        supports_streaming=True,
        supports_prefix_cache=True,
    ),
    ModelInfo(
        id="deepseek-v4-flash",
        name="V4 Flash",
        provider="deepseek",
        cost_per_1k_in=0.00014,
        cost_per_1k_out=0.00028,
        supports_tools=True,
        supports_thinking=True,
        supports_streaming=True,
        supports_prefix_cache=True,
    ),
    ModelInfo(
        id="deepseek-reasoner",
        name="Reasoner (R1)",
        provider="deepseek",
        cost_per_1k_in=0.00028,
        cost_per_1k_out=0.00042,
        supports_tools=False,
        supports_thinking=True,
        supports_streaming=True,
        supports_prefix_cache=False,
    ),
]


class DeepSeekAdapter:
    """Adapter for DeepSeek API (OpenAI-compatible).

    Features:
    - Dual-key round-robin for Pro tier
    - Flash fallback to Pro when Flash is unavailable
    - Prefix cache hit rate logging
    - Tool call support
    """

    provider_name = "deepseek"
    supports_streaming = True
    supports_tools = True
    supports_thinking = True
    supports_prefix_cache = True
    supports_embedding = True

    def __init__(self):
        _api_timeout = httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=30.0)

        # === Pro clients (dual-key round-robin) ===
        self._pro_keys = [
            k for k in [
                os.getenv("DEEPSEEK_API_KEY"),
                os.getenv("DEEPSEEK_API_KEY_2"),
            ] if k
        ]
        self._pro_clients = [
            AsyncOpenAI(api_key=k, base_url="https://api.deepseek.com",
                        timeout=_api_timeout, max_retries=1)
            for k in self._pro_keys
        ] if self._pro_keys else []

        # === Flash client ===
        flash_key = os.getenv("DEEPSEEK_API_KEY_2") or os.getenv("DEEPSEEK_API_KEY")
        self._flash_client = AsyncOpenAI(
            api_key=flash_key, base_url="https://api.deepseek.com",
            timeout=_api_timeout, max_retries=1,
        ) if flash_key else None

        # === Embed client (optional — shared for DeepSeek embed tier) ===
        embed_key = os.getenv("EMBED_API_KEY") or flash_key
        embed_base = os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
        self._embed_client = AsyncOpenAI(
            api_key=embed_key, base_url=embed_base,
        ) if embed_key else None
        self._embed_model = os.getenv("EMBED_MODEL", "BAAI/bge-m3")

        logger.info(
            "DeepSeekAdapter 就绪",
            pro_keys=len(self._pro_clients),
            flash=bool(self._flash_client),
            embed=bool(self._embed_client),
        )

    # ── Chat ─────────────────────────────────────────────────

    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 800,
        stream: bool = False,
        tools: list | None = None,
        tool_choice: str | None = None,
    ) -> ProviderResponse | object:
        """Chat completion via DeepSeek API.

        Returns ProviderResponse for normal responses, raw stream object when stream=True.
        """
        has_tools = bool(tools)

        # Choose client based on model
        if model == "deepseek-v4-pro":
            return await self._call_pro(messages, temperature, max_tokens,
                                        stream, tools, tool_choice, has_tools)
        elif model == "deepseek-v4-flash":
            return await self._call_flash(messages, temperature, max_tokens,
                                          stream, tools, tool_choice, has_tools)
        else:
            # Unknown model → try Pro
            logger.warning("deepseek.unknown_model", model=model)
            return await self._call_pro(messages, temperature, max_tokens,
                                        stream, tools, tool_choice, has_tools)

    async def _call_pro(
        self, messages, temperature, max_tokens,
        stream, tools, tool_choice, has_tools,
    ) -> ProviderResponse | object:
        """DS Pro (dual-key round-robin + fallback)."""
        if not self._pro_clients:
            raise RuntimeError("DeepSeek V4-Pro 未配置 API Key")

        for attempt in range(len(self._pro_clients)):
            t0 = _time_module.time()
            try:
                client = self._pro_clients[attempt]
                api_kwargs = dict(
                    model="deepseek-v4-pro",
                    messages=messages,
                    temperature=temperature,
                    stream=stream,
                )
                if max_tokens:
                    api_kwargs["max_tokens"] = max_tokens
                if has_tools:
                    api_kwargs["tools"] = tools
                    api_kwargs["tool_choice"] = tool_choice or "auto"

                response = await asyncio.wait_for(
                    client.chat.completions.create(**api_kwargs),
                    timeout=90,
                )
                elapsed = (_time_module.time() - t0) * 1000
                logger.debug("ds_pro.call_ok", key=attempt, elapsed_ms=round(elapsed))

                if not stream:
                    _log_cache_usage(response, "ds_pro")

                if stream:
                    return response  # raw stream

                choice = response.choices[0]
                if choice.finish_reason == "length":
                    logger.warning(
                        "deepseek-v4-pro output truncated (max_tokens reached)",
                        usage=str(response.usage),
                    )

                msg = choice.message
                return ProviderResponse(
                    content=msg.content,
                    tool_calls=extract_tool_calls(msg),
                    reasoning_content=getattr(msg, 'reasoning_content', None),
                    model="deepseek-v4-pro",
                    usage=extract_usage(response),
                )
            except Exception as e:
                elapsed = (_time_module.time() - t0) * 1000
                logger.warning(
                    f"DS Pro key[{attempt}] 失败: {type(e).__name__}",
                    elapsed_ms=round(elapsed),
                    detail=str(e)[:300],
                )
                if attempt == len(self._pro_clients) - 1:
                    raise
                continue

    async def _call_flash(
        self, messages, temperature, max_tokens,
        stream, tools, tool_choice, has_tools,
    ) -> ProviderResponse | object:
        """DS Flash. Falls back to Pro if Flash unavailable."""
        if not self._flash_client:
            logger.warning("DS Flash 不可用，fallback DS Pro")
            return await self._call_pro(messages, temperature, max_tokens,
                                        stream, tools, tool_choice, has_tools)

        t0 = _time_module.time()
        api_kwargs = dict(
            model="deepseek-v4-flash",
            messages=messages,
            temperature=temperature,
            stream=stream,
        )
        if max_tokens:
            api_kwargs["max_tokens"] = max_tokens
        if has_tools:
            api_kwargs["tools"] = tools
            api_kwargs["tool_choice"] = tool_choice or "auto"

        try:
            response = await asyncio.wait_for(
                self._flash_client.chat.completions.create(**api_kwargs),
                timeout=90,
            )
        except Exception as e:
            elapsed = (_time_module.time() - t0) * 1000
            logger.warning(
                f"DS Flash 失败: {type(e).__name__}",
                elapsed_ms=round(elapsed),
                detail=str(e)[:300],
            )
            raise

        elapsed = (_time_module.time() - t0) * 1000
        logger.debug("ds_flash.call_ok", elapsed_ms=round(elapsed))

        if not stream:
            _log_cache_usage(response, "ds_flash")

        if stream:
            return response  # raw stream

        choice = response.choices[0]
        if choice.finish_reason == "length":
            logger.warning(
                "deepseek-v4-flash output truncated (max_tokens reached)",
                usage=str(response.usage),
            )

        msg = choice.message
        return ProviderResponse(
            content=msg.content,
            tool_calls=extract_tool_calls(msg),
            reasoning_content=getattr(msg, 'reasoning_content', None),
            model="deepseek-v4-flash",
            usage=extract_usage(response),
        )

    # ── Embed ────────────────────────────────────────────────

    async def embed(self, model: str, texts: list[str]) -> list[list[float]] | None:
        """Embedding via configured embed client (default: SiliconFlow bge-m3)."""
        if not self._embed_client:
            logger.debug("embed.unavailable")
            return None

        actual_model = model or self._embed_model
        try:
            response = await asyncio.wait_for(
                self._embed_client.embeddings.create(
                    model=actual_model,
                    input=texts,
                ),
                timeout=60 if len(texts) > 1 else 30,
            )
            return [d.embedding for d in response.data]
        except Exception as e:
            logger.warning("embed.failed", error=str(e)[:120])
            return None

    # ── Model listing ───────────────────────────────────────

    @staticmethod
    def get_available_models() -> list[ModelInfo]:
        return DEEPSEEK_MODELS


# ═══════════════════════════════════════════════════════════════
# Helpers (DeepSeek-specific)
# ═══════════════════════════════════════════════════════════════

def _log_cache_usage(response, model_label: str) -> None:
    """Log DeepSeek prefix cache hit rate."""
    usage = getattr(response, "usage", None)
    if not usage:
        return
    hit = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
    miss = getattr(usage, "prompt_cache_miss_tokens", 0) or 0
    total_prompt = (getattr(usage, "prompt_tokens", 0) or 0)
    if hit + miss == 0:
        return
    rate = round(hit / (hit + miss) * 100, 1)
    logger.debug("cache.hit_rate",
                 model=model_label,
                 hit_tokens=hit,
                 miss_tokens=miss,
                 total_prompt=total_prompt,
                 hit_rate_pct=rate)
