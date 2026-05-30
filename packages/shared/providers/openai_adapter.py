"""
OpenAIAdapter — OpenAI GPT-4o / GPT-4o-mini provider.

Uses the same AsyncOpenAI SDK as DeepSeek, just different base_url + models.
"""
from __future__ import annotations

import asyncio
import os
import time as _time_module

import httpx
from loguru import logger
from openai import AsyncOpenAI

from .base import ModelInfo, ProviderAdapter
from . import ProviderResponse, extract_tool_calls, extract_usage

# ── Available models ─────────────────────────────────────────

OPENAI_MODELS = [
    # ── GPT-5.x (latest) ──
    ModelInfo(
        id="gpt-5.4",
        name="GPT-5.4",
        provider="openai",
        cost_per_1k_in=0.0025, cost_per_1k_out=0.015,
        supports_tools=True, supports_thinking=True,
        supports_streaming=True, supports_prefix_cache=False,
    ),
    ModelInfo(
        id="gpt-5.4-mini",
        name="GPT-5.4 Mini",
        provider="openai",
        cost_per_1k_in=0.00075, cost_per_1k_out=0.0045,
        supports_tools=True, supports_thinking=True,
        supports_streaming=True, supports_prefix_cache=False,
    ),
    ModelInfo(
        id="gpt-5.4-nano",
        name="GPT-5.4 Nano",
        provider="openai",
        cost_per_1k_in=0.0002, cost_per_1k_out=0.00125,
        supports_tools=True, supports_thinking=True,
        supports_streaming=True, supports_prefix_cache=False,
    ),
    # ── o-series (reasoning) ──
    ModelInfo(
        id="o4-mini",
        name="o4 Mini",
        provider="openai",
        cost_per_1k_in=0.0011, cost_per_1k_out=0.0044,
        supports_tools=True, supports_thinking=True,
        supports_streaming=True, supports_prefix_cache=False,
    ),
    # ── GPT-4.1 (long context) ──
    ModelInfo(
        id="gpt-4.1",
        name="GPT-4.1",
        provider="openai",
        cost_per_1k_in=0.002, cost_per_1k_out=0.008,
        supports_tools=True, supports_thinking=False,
        supports_streaming=True, supports_prefix_cache=False,
    ),
    ModelInfo(
        id="gpt-4.1-mini",
        name="GPT-4.1 Mini",
        provider="openai",
        cost_per_1k_in=0.0004, cost_per_1k_out=0.0016,
        supports_tools=True, supports_thinking=False,
        supports_streaming=True, supports_prefix_cache=False,
    ),
]


class OpenAIAdapter:
    """Adapter for OpenAI API (AsyncOpenAI).

    Supports: gpt-4o, gpt-4o-mini, gpt-4.1
    Embedding: text-embedding-3-small (optional)
    """

    provider_name = "openai"
    supports_streaming = True
    supports_tools = True
    supports_thinking = False
    supports_prefix_cache = False
    supports_embedding = True

    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY", "")
        base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        _api_timeout = httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=30.0)

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_api_timeout,
            max_retries=1,
        ) if api_key else None

        # Embedding support (optional)
        self._embed_client = self._client  # reuse same client
        self._embed_model = "text-embedding-3-small"

        logger.info(
            "OpenAIAdapter 就绪",
            client=bool(self._client),
            base_url=base_url,
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
        """Chat completion via OpenAI API."""
        if not self._client:
            raise RuntimeError("OpenAI API Key 未配置 (OPENAI_API_KEY)")

        has_tools = bool(tools)
        t0 = _time_module.time()

        api_kwargs = dict(
            model=model,
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
                self._client.chat.completions.create(**api_kwargs),
                timeout=90,
            )
        except Exception as e:
            elapsed = (_time_module.time() - t0) * 1000
            logger.warning(
                f"OpenAI {model} 失败: {type(e).__name__}",
                elapsed_ms=round(elapsed),
                detail=str(e)[:300],
            )
            raise

        elapsed = (_time_module.time() - t0) * 1000
        logger.debug("openai.call_ok", model=model, elapsed_ms=round(elapsed))

        if stream:
            return response  # raw stream

        choice = response.choices[0]
        if choice.finish_reason == "length":
            logger.warning(f"{model} output truncated", usage=str(response.usage))

        msg = choice.message
        return ProviderResponse(
            content=msg.content,
            tool_calls=extract_tool_calls(msg),
            reasoning_content=None,
            model=model,
            usage=extract_usage(response),
        )

    # ── Embed ────────────────────────────────────────────────

    async def embed(self, model: str, texts: list[str]) -> list[list[float]] | None:
        """Embedding via OpenAI text-embedding-3-small."""
        if not self._embed_client:
            logger.debug("openai.embed.unavailable")
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
            logger.warning("openai.embed.failed", error=str(e)[:120])
            return None

    # ── Model listing ───────────────────────────────────────

    @staticmethod
    def get_available_models() -> list[ModelInfo]:
        return OPENAI_MODELS


# ═══════════════════════════════════════════════════════════════
# Helpers (re-export shared for backward compat within this module)
# ═══════════════════════════════════════════════════════════════
