"""
AnthropicAdapter — Claude Sonnet 4 / Haiku 4 provider.

Message format conversion: OpenAI ↔ Anthropic content blocks.
Tool calling: function calling ↔ tool_use / tool_result blocks.
System prompt: top-level parameter (not message role).

This is the highest-complexity adapter due to Anthropic's format differences.
"""
from __future__ import annotations

import asyncio
import json
import os
import time as _time_module

from loguru import logger

from .base import ModelInfo, ProviderAdapter
from . import ProviderResponse

# ── Available models ─────────────────────────────────────────

ANTHROPIC_MODELS = [
    ModelInfo(
        id="claude-sonnet-4-6",
        name="Claude Sonnet 4.6",
        provider="anthropic",
        cost_per_1k_in=0.003, cost_per_1k_out=0.015,
        supports_tools=True,
        supports_thinking=True,
        supports_streaming=True,
        supports_prefix_cache=True,
    ),
    ModelInfo(
        id="claude-haiku-4-6",
        name="Claude Haiku 4.6",
        provider="anthropic",
        cost_per_1k_in=0.0008, cost_per_1k_out=0.004,
        supports_tools=True,
        supports_thinking=False,
        supports_streaming=True,
        supports_prefix_cache=False,
    ),
    ModelInfo(
        id="claude-opus-4-6",
        name="Claude Opus 4.6",
        provider="anthropic",
        cost_per_1k_in=0.015, cost_per_1k_out=0.075,
        supports_tools=True,
        supports_thinking=True,
        supports_streaming=True,
        supports_prefix_cache=True,
    ),
]


class AnthropicAdapter:
    """Adapter for Anthropic Messages API.

    Key conversions:
    - system messages → top-level 'system' parameter
    - assistant(tool_calls) → content blocks with tool_use
    - tool results → user messages with tool_result blocks
    - Anthropic response → ProviderResponse (OpenAI-compatible)
    """

    provider_name = "anthropic"
    supports_streaming = True
    supports_tools = True
    supports_thinking = True
    supports_prefix_cache = True
    supports_embedding = False  # Anthropic doesn't have a dedicated embedding API

    def __init__(self):
        self._api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self._base_url = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")

        if self._api_key:
            try:
                from anthropic import AsyncAnthropic
                self._client = AsyncAnthropic(
                    api_key=self._api_key,
                    base_url=self._base_url,
                    timeout=120.0,
                    max_retries=1,
                )
            except ImportError:
                logger.warning("anthropic SDK 未安装，请执行: uv sync --extra anthropic")
                self._client = None
        else:
            self._client = None

        logger.info(
            "AnthropicAdapter 就绪",
            client=bool(self._client),
            base_url=self._base_url,
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
        """Chat completion via Anthropic Messages API."""
        if not self._client:
            raise RuntimeError("Anthropic API Key 未配置 (ANTHROPIC_API_KEY)")

        # ── 1. Convert messages ──
        system_text, anthropic_messages, anthropic_tools = self._convert_messages(
            messages, tools,
        )

        # ── 2. Build kwargs ──
        api_kwargs = dict(
            model=model,
            messages=anthropic_messages,
            temperature=temperature,
            max_tokens=max_tokens or 4096,  # Anthropic requires max_tokens
            stream=stream,
        )
        if system_text:
            api_kwargs["system"] = system_text
        if anthropic_tools:
            api_kwargs["tools"] = anthropic_tools
            # Map tool_choice: "auto" → {"type": "auto"}, "none" → None (don't pass)
            if tool_choice and tool_choice != "none":
                api_kwargs["tool_choice"] = {"type": tool_choice}

        # ── 3. Call API ──
        t0 = _time_module.time()
        try:
            response = await asyncio.wait_for(
                self._client.messages.create(**api_kwargs),
                timeout=120,
            )
        except Exception as e:
            elapsed = (_time_module.time() - t0) * 1000
            logger.warning(
                f"Anthropic {model} 失败: {type(e).__name__}",
                elapsed_ms=round(elapsed),
                detail=str(e)[:300],
            )
            raise

        elapsed = (_time_module.time() - t0) * 1000
        logger.debug("anthropic.call_ok", model=model, elapsed_ms=round(elapsed))

        if stream:
            return response  # raw stream

        # ── 4. Parse response ──
        return self._parse_response(response, model)

    async def embed(self, model: str, texts: list[str]) -> list[list[float]] | None:
        """Anthropic doesn't support embeddings — return None."""
        logger.debug("anthropic.embed.not_supported")
        return None

    # ══════════════════════════════════════════════════════════
    # Message Conversion
    # ══════════════════════════════════════════════════════════

    def _convert_messages(
        self, messages: list[dict], tools: list | None,
    ) -> tuple[str, list[dict], list[dict] | None]:
        """Convert OpenAI-format messages to Anthropic format.

        Returns:
            (system_text, anthropic_messages, anthropic_tools)
        """
        # ── Extract system messages ──
        system_parts = []
        non_system = []
        for m in messages:
            if m.get("role") == "system":
                content = m.get("content", "")
                if content:
                    system_parts.append(str(content))
            else:
                non_system.append(m)

        system_text = "\n\n".join(system_parts) if system_parts else ""

        # ── Convert tools ──
        anthropic_tools = None
        if tools:
            anthropic_tools = self._convert_tools(tools)

        # ── Convert messages ──
        anthropic_messages = []
        for m in non_system:
            role = m.get("role", "user")
            content = m.get("content", "")
            tool_calls = m.get("tool_calls")

            if role == "assistant" and tool_calls:
                # assistant with tool_calls → content blocks with tool_use
                reasoning = m.get("reasoning_content")
                blocks = self._convert_assistant_with_tools(content, tool_calls, reasoning)
                anthropic_messages.append({"role": "assistant", "content": blocks})
            elif role == "tool":
                # tool result → user message with tool_result block
                tool_call_id = m.get("tool_call_id", "")
                blocks = [{
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": str(content) if content else "",
                }]
                anthropic_messages.append({"role": "user", "content": blocks})
            elif role == "assistant":
                # plain assistant message
                if content:
                    anthropic_messages.append({"role": "assistant", "content": str(content)})
            elif role == "user":
                # plain user message
                if content:
                    anthropic_messages.append({"role": "user", "content": str(content)})

        # ── Ensure proper role alternation ──
        anthropic_messages = self._fix_role_alternation(anthropic_messages)

        return system_text, anthropic_messages, anthropic_tools

    def _convert_tools(self, tools: list) -> list[dict]:
        """Convert OpenAI tool format to Anthropic tool format.

        OpenAI: {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}
        Anthropic: {"name": "...", "description": "...", "input_schema": {...}}
        """
        result = []
        for t in tools:
            if t.get("type") != "function":
                continue
            fn = t.get("function", {})
            result.append({
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            })
        return result

    def _convert_assistant_with_tools(
        self, content: str | None, tool_calls: list,
        reasoning_content: str | None = None,
    ) -> list[dict]:
        """Build Anthropic content blocks for assistant message with tool calls.

        Includes:
        - thinking preamble (if reasoning_content present in message dict)
        - text content (if any)
        - tool_use blocks
        """
        blocks = []
        # Include reasoning/thinking as a text preamble
        # (Anthropic expects thinking blocks; text block preserves context minimally)
        if reasoning_content:
            blocks.append({"type": "text", "text": f"[thinking] {reasoning_content}"})
        # Include text if present
        if content:
            blocks.append({"type": "text", "text": str(content)})

        for tc in tool_calls:
            # Handle both dict and object formats
            tc_id = tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", "")
            tc_type = tc.get("type", "function") if isinstance(tc, dict) else getattr(tc, "type", "function")

            if isinstance(tc, dict):
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args_str = fn.get("arguments", "{}")
            else:
                fn = getattr(tc, "function", None)
                name = getattr(fn, "name", "") if fn else ""
                args_str = getattr(fn, "arguments", "{}") if fn else "{}"

            # Parse arguments JSON string to dict
            try:
                args_dict = json.loads(args_str) if isinstance(args_str, str) else args_str
            except (json.JSONDecodeError, TypeError):
                args_dict = {}

            blocks.append({
                "type": "tool_use",
                "id": tc_id,
                "name": name,
                "input": args_dict,
            })

        return blocks

    def _fix_role_alternation(self, messages: list[dict]) -> list[dict]:
        """Ensure messages alternate user/assistant.

        Anthropic requires user/assistant alternation. Merge consecutive same-role messages.
        Also ensures tool_result (role=user) can follow assistant.
        """
        if not messages:
            return messages

        fixed = [messages[0]]
        for m in messages[1:]:
            prev = fixed[-1]
            if m["role"] == prev["role"] and m["role"] in ("user", "assistant"):
                # Merge: append content
                prev_content = prev.get("content", "")
                new_content = m.get("content", "")

                # Handle string content merge
                if isinstance(prev_content, str) and isinstance(new_content, str):
                    prev["content"] = prev_content + "\n" + new_content
                elif isinstance(prev_content, list) and isinstance(new_content, list):
                    prev["content"] = prev_content + new_content
                elif isinstance(prev_content, str) and isinstance(new_content, list):
                    prev["content"] = [{"type": "text", "text": prev_content}] + new_content
                elif isinstance(prev_content, list) and isinstance(new_content, str):
                    prev["content"] = prev_content + [{"type": "text", "text": new_content}]
            else:
                fixed.append(m)

        # Ensure first message is user
        if fixed and fixed[0]["role"] != "user":
            fixed.insert(0, {"role": "user", "content": "(system context)"})

        return fixed

    # ══════════════════════════════════════════════════════════
    # Response Parsing
    # ══════════════════════════════════════════════════════════

    def _parse_response(self, response, model: str) -> ProviderResponse:
        """Parse Anthropic response to ProviderResponse.

        Anthropic response structure:
        - content: list of content blocks (text, tool_use, thinking, etc.)
        - stop_reason: "end_turn" | "tool_use" | "max_tokens" | "stop_sequence"
        - usage: {input_tokens, output_tokens}
        """
        content_blocks = response.content if hasattr(response, 'content') else []
        stop_reason = getattr(response, 'stop_reason', 'end_turn')

        text_parts = []
        tool_calls = []
        reasoning = None

        for block in content_blocks:
            block_type = getattr(block, 'type', '')
            if block_type == 'text':
                text_parts.append(getattr(block, 'text', ''))
            elif block_type == 'tool_use':
                # Convert Anthropic tool_use → OpenAI tool_call format
                tool_calls.append({
                    "id": getattr(block, 'id', ''),
                    "type": "function",
                    "function": {
                        "name": getattr(block, 'name', ''),
                        "arguments": json.dumps(getattr(block, 'input', {}), ensure_ascii=False),
                    },
                })
            elif block_type == 'thinking':
                reasoning = getattr(block, 'thinking', '')

        text = "\n".join(text_parts) if text_parts else None

        # Extract usage
        usage = None
        if hasattr(response, 'usage'):
            u = response.usage
            usage = {
                "prompt_tokens": getattr(u, 'input_tokens', 0) or 0,
                "completion_tokens": getattr(u, 'output_tokens', 0) or 0,
                "total_tokens": (getattr(u, 'input_tokens', 0) or 0) + (getattr(u, 'output_tokens', 0) or 0),
            }

        # Log stop reason warnings
        if stop_reason == "max_tokens":
            logger.warning(f"{model} output truncated (max_tokens reached)", usage=str(usage))

        return ProviderResponse(
            content=text,
            tool_calls=tool_calls if tool_calls else None,
            reasoning_content=reasoning,
            model=model,
            usage=usage,
        )

    # ── Model listing ───────────────────────────────────────

    @staticmethod
    def get_available_models() -> list[ModelInfo]:
        return ANTHROPIC_MODELS
