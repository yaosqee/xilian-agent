"""
Multi-provider routing system for 昔涟 V3.3.

Architecture:
    task_type → tier → (provider + model) → adapter.chat()

Key types:
    ProviderResponse — unified response wrapper (content + tool_calls + usage)
    ProviderConfig    — credentials for one provider
    TierConfig        — which provider+model serves a tier
    TASK_TIER_MAP     — which tier each task_type maps to

Usage:
    router = ModelRouter(db)
    await router.initialize()
    response = await router.route("chat", messages, tools=...)
    print(response.content)       # text
    print(response.tool_calls)    # tool calls (or None)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from .base import ModelInfo, ProviderAdapter

# ═══════════════════════════════════════════════════════════════
# Task type → Tier mapping
# ═══════════════════════════════════════════════════════════════

TierName = Literal["powerful", "fast", "embed", "reasoning"]

TaskType = Literal[
    "chat", "empathy",
    "memory_encoding", "autobiography", "reflection", "dream",
    "reasoning", "code", "planning",
    "personality_check", "prompt_injection_detect", "approval_text",
    "emotion_analysis", "tool_result_wrap",
    "proactive_greeting", "image_response",
]

# Default mapping: task_type → tier
# Users can override individual entries via model_configs table (config_key="override:<task_type>")
TASK_TIER_MAP: dict[TaskType, TierName] = {
    # ── powerful tier: user-facing quality-critical ──
    "chat":                     "powerful",
    "empathy":                  "powerful",
    "reasoning":                "reasoning",  # may fall back to powerful
    "code":                     "reasoning",
    "planning":                 "reasoning",
    "personality_check":        "powerful",
    "prompt_injection_detect":  "powerful",
    "proactive_greeting":       "powerful",
    "image_response":           "powerful",
    # ── fast tier: background async tasks ──
    "memory_encoding":          "fast",
    "autobiography":            "fast",
    "reflection":               "fast",
    "dream":                    "fast",
    "approval_text":            "fast",
    "emotion_analysis":         "fast",
    "tool_result_wrap":         "fast",
}


# ═══════════════════════════════════════════════════════════════
# Dataclasses
# ═══════════════════════════════════════════════════════════════

@dataclass
class ProviderResponse:
    """Unified response from any provider adapter.

    After any adapter.chat() call, the response is wrapped in this type.
    Call sites never touch raw API response objects directly.

    Attributes:
        content: text content (may be None for tool-only responses)
        tool_calls: standardized tool calls list (OpenAI format), or None
        model: the model that generated this response
        usage: token usage dict {prompt_tokens, completion_tokens, total_tokens}
        raw_stream: raw streaming response object (when stream=True)
    """
    content: str | None = None
    tool_calls: list[dict] | None = None
    reasoning_content: str | None = None  # DeepSeek thinking mode / Anthropic extended thinking
    model: str = ""
    usage: dict | None = None
    raw_stream: object | None = None  # raw async generator for streaming

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    @property
    def text(self) -> str:
        """Convenience: always returns a string (empty if content is None)."""
        return self.content or ""

    def __bool__(self) -> bool:
        return self.content is not None or self.tool_calls is not None


@dataclass
class ProviderConfig:
    """Credentials for one provider.

    Stored in model_configs table, api_key read from .env (then stored in DB).
    """
    provider: str           # "deepseek" | "openai" | "anthropic" | "siliconflow"
    api_key: str            # plain text (local SQLite, user's machine)
    base_url: str = ""      # optional override (proxy/custom endpoint)
    extra_headers: dict = field(default_factory=dict)  # e.g. org-id for OpenAI


@dataclass
class TierConfig:
    """Which provider+model serves a given tier."""
    tier: str               # "powerful" | "fast" | "embed" | "reasoning"
    provider: str            # "deepseek" | "openai" | "anthropic" | "siliconflow"
    model_name: str          # "deepseek-v4-pro" | "gpt-4o" | etc.
    temperature: float = 0.7
    max_tokens: int = 800
    is_active: bool = True


@dataclass
class TaskOverride:
    """Per-task-type model override (advanced settings)."""
    task_type: str
    provider: str
    model_name: str


# ═══════════════════════════════════════════════════════════════
# Default configurations per provider (fallback when no DB config)
# ═══════════════════════════════════════════════════════════════

# These are used during auto-configuration when only .env keys exist.
DEFAULT_TIER_MODELS: dict[str, dict[str, str]] = {
    "deepseek": {
        "powerful": "deepseek-v4-pro",
        "fast": "deepseek-v4-flash",
        "reasoning": "deepseek-reasoner",
    },
    "openai": {
        "powerful": "gpt-5.4-mini",
        "fast": "gpt-5.4-nano",
        "reasoning": "o4-mini",
    },
    "anthropic": {
        "powerful": "claude-sonnet-4-6",
        "fast": "claude-haiku-4-6",
        "reasoning": "claude-sonnet-4-6",
    },
    "google": {
        "powerful": "gemini-2.5-pro",
        "fast": "gemini-2.5-flash",
        "reasoning": "gemini-2.5-pro",
    },
}

# Default embedding models per provider
DEFAULT_EMBED_MODELS: dict[str, dict] = {
    "siliconflow": {
        "provider": "siliconflow",
        "model_name": "BAAI/bge-m3",
        "base_url": "https://api.siliconflow.cn/v1",
        "dimensions": 1024,
    },
    "openai": {
        "provider": "openai",
        "model_name": "text-embedding-3-small",
        "base_url": "https://api.openai.com/v1",
        "dimensions": 1536,
    },
    "deepseek": {
        "provider": "deepseek",
        "model_name": "deepseek-v4-pro",  # DeepSeek doesn't have dedicated embed; use Pro
        "base_url": "https://api.deepseek.com",
        "dimensions": 1024,
    },
}


# ═══════════════════════════════════════════════════════════════
# Provider detection
# ═══════════════════════════════════════════════════════════════

def detect_configured_providers() -> list[str]:
    """Detect which providers have API keys set in the environment.

    Returns list of provider names (e.g., ["deepseek", "siliconflow"]).
    """
    providers = []
    if os.getenv("DEEPSEEK_API_KEY"):
        providers.append("deepseek")
    if os.getenv("OPENAI_API_KEY"):
        providers.append("openai")
    if os.getenv("ANTHROPIC_API_KEY"):
        providers.append("anthropic")
    if os.getenv("GOOGLE_API_KEY"):
        providers.append("google")
    if os.getenv("EMBED_API_KEY") or os.getenv("DEEPSEEK_API_KEY"):
        providers.append("siliconflow")
    return providers


# ═══════════════════════════════════════════════════════════════
# Shared helpers — OpenAI-format message parsing
# ═══════════════════════════════════════════════════════════════

def extract_tool_calls(msg) -> list[dict] | None:
    """Extract tool_calls from an OpenAI message object, standardize to dict list."""
    raw = getattr(msg, 'tool_calls', None)
    if not raw:
        return None
    result = []
    for tc in raw:
        result.append({
            "id": tc.id,
            "type": "function",
            "function": {
                "name": tc.function.name,
                "arguments": tc.function.arguments,
            },
        })
    return result


def extract_usage(response) -> dict | None:
    """Extract token usage from a response object."""
    usage = getattr(response, 'usage', None)
    if not usage:
        return None
    return {
        "prompt_tokens": getattr(usage, 'prompt_tokens', 0) or 0,
        "completion_tokens": getattr(usage, 'completion_tokens', 0) or 0,
        "total_tokens": getattr(usage, 'total_tokens', 0) or 0,
    }
