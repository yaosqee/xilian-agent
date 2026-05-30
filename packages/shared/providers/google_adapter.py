"""
GoogleAdapter — Gemini 2.5 Pro / Flash provider.

Google Gemini API is OpenAI-compatible via the /v1beta/openai endpoint.
Uses the same AsyncOpenAI SDK, just different base_url.
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

GEMINI_MODELS = [
    ModelInfo(
        id="gemini-2.5-pro",
        name="Gemini 2.5 Pro",
        provider="google",
        cost_per_1k_in=0.00125, cost_per_1k_out=0.005,
        supports_tools=True, supports_thinking=True,
        reasoning=True, input_modalities=["text", "image"],
        context_window=1_000_000, max_output_tokens=64_000,
    ),
    ModelInfo(
        id="gemini-2.5-flash",
        name="Gemini 2.5 Flash",
        provider="google",
        cost_per_1k_in=0.000075, cost_per_1k_out=0.0003,
        supports_tools=True, supports_thinking=False,
        reasoning=False, input_modalities=["text", "image"],
        context_window=1_000_000, max_output_tokens=8_000,
    ),
    ModelInfo(
        id="gemini-2.5-flash-lite",
        name="Gemini 2.5 Flash Lite",
        provider="google",
        cost_per_1k_in=0.0000375, cost_per_1k_out=0.00015,
        supports_tools=True, supports_thinking=False,
        reasoning=False, input_modalities=["text"],
        context_window=1_000_000, max_output_tokens=8_000,
    ),
]


class GoogleAdapter:
    """Adapter for Google Gemini API (OpenAI-compatible endpoint).

    Base URL: https://generativelanguage.googleapis.com/v1beta/openai/
    Auth: GOOGLE_API_KEY env var
    """

    provider_name = "google"
    supports_streaming = True
    supports_tools = True
    supports_thinking = True
    supports_prefix_cache = False
    supports_embedding = True

    def __init__(self):
        api_key = os.getenv("GOOGLE_API_KEY", "")
        base_url = os.getenv("GOOGLE_BASE_URL",
                             "https://generativelanguage.googleapis.com/v1beta/openai/")

        _api_timeout = httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=30.0)

        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=_api_timeout,
            max_retries=1,
        ) if api_key else None

        logger.info(
            "GoogleAdapter 就绪",
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
        """Chat completion via Google Gemini API."""
        if not self._client:
            raise RuntimeError("Google API Key 未配置 (GOOGLE_API_KEY)")

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
                f"Gemini {model} 失败: {type(e).__name__}",
                elapsed_ms=round(elapsed),
                detail=str(e)[:300],
            )
            raise

        elapsed = (_time_module.time() - t0) * 1000
        logger.debug("gemini.call_ok", model=model, elapsed_ms=round(elapsed))

        if stream:
            return response

        choice = response.choices[0]
        if choice.finish_reason == "length":
            logger.warning(f"{model} output truncated", usage=str(response.usage))

        msg = choice.message
        return ProviderResponse(
            content=msg.content,
            tool_calls=extract_tool_calls(msg),
            reasoning_content=getattr(msg, 'reasoning_content', None),
            model=model,
            usage=extract_usage(response),
        )

    # ── Embed ────────────────────────────────────────────────

    async def embed(self, model: str, texts: list[str]) -> list[list[float]] | None:
        """Google embedding (text-embedding-004 or similar)."""
        if not self._client:
            return None

        actual_model = model or "text-embedding-004"
        try:
            response = await asyncio.wait_for(
                self._client.embeddings.create(
                    model=actual_model,
                    input=texts,
                ),
                timeout=60 if len(texts) > 1 else 30,
            )
            return [d.embedding for d in response.data]
        except Exception as e:
            logger.warning("gemini.embed.failed", error=str(e)[:120])
            return None

    # ── Model listing ───────────────────────────────────────

    @staticmethod
    def get_available_models() -> list[ModelInfo]:
        return GEMINI_MODELS


# ═══════════════════════════════════════════════════════════════
# Helpers (shared extract_tool_calls / extract_usage imported above)
