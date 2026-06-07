"""
MiMoAdapter — Xiaomi MiMo-V2.5 全模态模型适配器

MiMo-V2.5: 310B MoE, 15B 激活, 1M 上下文, 原生支持图像/视频/音频/文本。
官方 API: https://api.xiaomimimo.com/v1 (OpenAI 兼容，使用 api-key header 鉴权)。

用途：图片描述子 Agent（不参与主对话路由）。
"""
from __future__ import annotations

import asyncio
import os
import time as _time_module

import httpx
from loguru import logger
from openai import AsyncOpenAI

from .base import ModelInfo
from . import ProviderResponse


# ── Available models ─────────────────────────────────────────

MIMO_MODELS = [
    ModelInfo(
        id="mimo-v2.5",
        name="MiMo-V2.5",
        provider="mimo",
        cost_per_1k_in=0.0, cost_per_1k_out=0.0,
        supports_tools=True,
        input_modalities=["text", "image", "video", "audio"],
        context_window=1_048_576,
        max_output_tokens=131_100,
    ),
]

# ── 图片描述 prompt ──────────────────────────────────────────

IMAGE_DESCRIPTION_PROMPT = """请用自然的中文详细描述这张图片的内容、氛围和细节。
要求：
- 2-4 句话，直接描述画面
- 不要加「图片中」「图中显示」「这是」这类前缀
- 像在跟朋友分享你看到的画面一样自然
"""


class MiMoAdapter:
    """Adapter for Xiaomi MiMo-V2.5 via official API (OpenAI-compatible endpoint).

    API Key 来源：环境变量 MIMO_API_KEY。
    Base URL: https://api.xiaomimimo.com/v1
    Auth: api-key header（非 Authorization: Bearer）
    """

    provider_name = "mimo"
    supports_streaming = False  # 仅用于图片描述，不需要流式
    supports_tools = True
    supports_thinking = False
    supports_prefix_cache = False
    supports_embedding = False

    def __init__(self):
        self._api_key = os.getenv("MIMO_API_KEY", "")
        self._base_url = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")

        if self._api_key:
            # Xiaomi API 使用 api-key header 鉴权，非标准 Bearer token
            # 设置 api_key 为空避免 SDK 发送 Authorization header
            # 通过 default_headers 发送正确的 api-key
            self._client = AsyncOpenAI(
                api_key="not-used",  # SDK 强制要求，但实际用 default_headers 鉴权
                base_url=self._base_url,
                timeout=httpx.Timeout(connect=15.0, read=60.0, write=30.0, pool=30.0),
                max_retries=1,
                default_headers={
                    "api-key": self._api_key,
                },
            )
        else:
            self._client = None

        logger.info(
            "MiMoAdapter 就绪",
            client=bool(self._client),
            base_url=self._base_url,
        )

    # ── Chat ─────────────────────────────────────────────────

    async def chat(
        self,
        model: str = "mimo-v2.5",
        messages: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 800,
        stream: bool = False,
        tools: list | None = None,
        tool_choice: str | None = None,
    ) -> ProviderResponse:
        """Chat completion via MiMo API (OpenAI-compatible, api-key auth)."""
        if not self._client:
            raise RuntimeError("MiMo API Key 未配置 (MIMO_API_KEY)")

        if messages is None:
            messages = []

        t0 = _time_module.time()
        try:
            # Xiaomi API 使用 max_completion_tokens 而非 max_tokens
            api_kwargs = dict(
                model=model,
                messages=messages,
                temperature=temperature,
                max_completion_tokens=max_tokens,
                extra_body={"chat_template_kwargs": {"thinking": False}},
            )
            if tools:
                api_kwargs["tools"] = tools
            if tool_choice:
                api_kwargs["tool_choice"] = tool_choice

            response = await asyncio.wait_for(
                self._client.chat.completions.create(**api_kwargs),
                timeout=60,
            )
        except Exception as e:
            elapsed = (_time_module.time() - t0) * 1000
            logger.warning(
                f"MiMo {model} 失败: {type(e).__name__}",
                elapsed_ms=round(elapsed),
                detail=str(e)[:300],
            )
            raise

        elapsed = (_time_module.time() - t0) * 1000

        choice = response.choices[0]
        content = choice.message.content or ""
        reasoning = getattr(choice.message, 'reasoning_content', '') or ''
        # 若 content 为空但 reasoning_content 有内容，使用 reasoning 作为兜底
        if not content and reasoning:
            content = reasoning

        logger.debug("mimo.call_ok", model=model, elapsed_ms=round(elapsed))
        return ProviderResponse(
            content=content,
            model=model,
            usage={"total_tokens": response.usage.total_tokens} if response.usage else {},
        )

    # ── Image description helper ─────────────────────────────

    async def describe_image(self, image_url: str) -> str:
        """用 MiMo-V2.5 描述图片内容。"""
        messages = [
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image_url}},
                {"type": "text", "text": IMAGE_DESCRIPTION_PROMPT},
            ]},
        ]
        try:
            response = await self.chat(
                model="mimo-v2.5",
                messages=messages,
                temperature=0.3,
                max_tokens=300,
            )
            return response.content.strip()
        except Exception as e:
            logger.warning("mimo.describe_image_failed", error=str(e))
            return ""

    # ── Embed (not supported) ────────────────────────────────

    async def embed(self, model: str, texts: list[str]) -> list[list[float]] | None:
        return None

    # ── Model listing ────────────────────────────────────────

    @staticmethod
    def get_available_models() -> list[ModelInfo]:
        return MIMO_MODELS
