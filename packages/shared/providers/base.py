"""
ProviderAdapter Protocol + ModelInfo dataclass.

All provider adapters must satisfy this Protocol.
Uses structural subtyping (not ABC inheritance) for flexibility.
"""
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class ModelInfo:
    """Public metadata about an available model.

    Cost fields are per 1K tokens (USD) for backward compat;
    frontend converts to user-facing display units.
    """
    id: str                          # "gpt-5.4"
    name: str                        # "GPT-5.4" (display name)
    provider: str                    # "openai"
    # ── Capabilities ──
    supports_tools: bool = False
    supports_thinking: bool = False
    supports_streaming: bool = True
    supports_prefix_cache: bool = False
    reasoning: bool = False          # model supports extended reasoning (o-series, thinking mode)
    input_modalities: list[str] = field(default_factory=lambda: ["text"])  # ["text", "image", "audio"]
    # ── Limits ──
    context_window: int = 128_000    # max context tokens
    max_output_tokens: int = 8_000   # max output tokens
    # ── Pricing (per 1K tokens, USD) ──
    cost_per_1k_in: float = 0.0
    cost_per_1k_out: float = 0.0
    # ── Compatibility hints ──
    reasoning_effort: bool = False   # supports reasoning_effort parameter


@runtime_checkable
class ProviderAdapter(Protocol):
    """Protocol that all provider adapters must satisfy.

    Providers handle:
    - chat completion (text + tool calls)
    - embedding (optional — some providers embed only)
    - model listing
    """

    provider_name: str
    supports_streaming: bool
    supports_tools: bool
    supports_thinking: bool
    supports_prefix_cache: bool
    supports_embedding: bool

    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.7,
        max_tokens: int = 800,
        stream: bool = False,
        tools: list | None = None,
        tool_choice: str | None = None,
    ) -> "ProviderResponse | str":  # str when stream=True (raw stream object)
        ...

    async def embed(self, model: str, texts: list[str]) -> list[list[float]] | None:
        ...

    @staticmethod
    def get_available_models() -> list[ModelInfo]:
        ...
