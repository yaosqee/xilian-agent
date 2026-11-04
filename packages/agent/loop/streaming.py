"""供应商流式响应归一化。

P1.5 只做一件事：把各家的 raw stream 还原成 runner 需要的
`ProviderResponse`，并在过程中产出可见文本增量。

支持的流格式：
- OpenAI / DeepSeek：`choices[0].delta.content / reasoning_content / tool_calls`
- Anthropic：`content_block_delta`（text / thinking / input_json）
- Google Gemini：`candidates[0].content.parts`（text / function_call）

未知格式不会抛异常：忽略该 chunk；如果整条流都没有可识别内容，
runner 会得到空回复并按原有 `reason="empty"` 处理。
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator

from packages.shared.providers import ProviderResponse


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """同时兼容 SDK 对象与 dict（单测用 dict 更轻）。"""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _usage_dict(usage: Any) -> dict[str, int] | None:
    """把 SDK Usage 对象转成 runner 认识的 dict。"""
    if usage is None:
        return None
    if isinstance(usage, dict):
        raw = usage
    else:
        raw = {
            "prompt_tokens": _get(usage, "prompt_tokens"),
            "completion_tokens": _get(usage, "completion_tokens"),
            "total_tokens": _get(usage, "total_tokens"),
        }
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        value = raw.get(key)
        try:
            if value is not None:
                result[key] = int(value)
        except (TypeError, ValueError):
            continue
    return result or None


class StreamAccumulator:
    """消费一条 raw stream，边产出文本增量边聚合完整响应。"""

    def __init__(self) -> None:
        self._content: list[str] = []
        self._reasoning: list[str] = []
        # index -> {"id", "name", "arguments"}
        self._tool_calls: dict[int, dict[str, str]] = {}
        self._usage: dict[str, int] | None = None
        self._finish_reason: str | None = None
        self._chunks = 0
        self._saw_openai = False
        self._saw_anthropic = False
        self._saw_google = False

    # ── 消费 ─────────────────────────────────────────────

    async def consume(self, raw: Any) -> AsyncIterator[str]:
        """逐 chunk 消费，产出可以直接发给前端的文本增量。"""
        async for chunk in _iterate(raw):
            text = self.feed(chunk)
            if text:
                yield text

    def feed(self, chunk: Any) -> str:
        """处理单个 chunk，返回本次新增的可见文本。"""
        self._chunks += 1

        if isinstance(chunk, str):
            self._content.append(chunk)
            return chunk

        text = self._feed_openai(chunk)
        if text is not None:
            self._saw_openai = True
            return text

        text = self._feed_anthropic(chunk)
        if text is not None:
            self._saw_anthropic = True
            return text

        text = self._feed_google(chunk)
        if text is not None:
            self._saw_google = True
            return text

        return ""

    # ── OpenAI / DeepSeek ────────────────────────────────

    def _feed_openai(self, chunk: Any) -> str | None:
        choices = _get(chunk, "choices")
        if choices is None:
            return None

        usage = _get(chunk, "usage")
        if usage is not None:
            self._usage = _usage_dict(usage)

        pieces: list[str] = []
        for choice in choices or []:
            delta = _get(choice, "delta") or {}
            content = _as_text(_get(delta, "content"))
            if content:
                self._content.append(content)
                pieces.append(content)

            reasoning = _as_text(_get(delta, "reasoning_content"))
            if reasoning:
                self._reasoning.append(reasoning)

            for raw_call in _get(delta, "tool_calls") or []:
                self._merge_openai_tool_call(raw_call)

            finish = _get(choice, "finish_reason")
            if finish:
                self._finish_reason = str(finish)

        return "".join(pieces)

    def _merge_openai_tool_call(self, raw_call: Any) -> None:
        index = _get(raw_call, "index", 0)
        try:
            index = int(index)
        except (TypeError, ValueError):
            index = 0

        entry = self._tool_calls.setdefault(
            index, {"id": "", "name": "", "arguments": ""}
        )
        call_id = _get(raw_call, "id")
        if call_id:
            entry["id"] = str(call_id)

        function = _get(raw_call, "function") or {}
        name = _get(function, "name")
        if name and not entry["name"]:
            entry["name"] = str(name)

        arguments = _get(function, "arguments")
        if isinstance(arguments, str):
            entry["arguments"] += arguments
        elif isinstance(arguments, dict):
            entry["arguments"] += json.dumps(arguments, ensure_ascii=False)

    # ── Anthropic ────────────────────────────────────────

    def _feed_anthropic(self, chunk: Any) -> str | None:
        chunk_type = _get(chunk, "type")
        if not isinstance(chunk_type, str) or not chunk_type.startswith(
            ("message_", "content_block_")
        ):
            return None

        if chunk_type == "error":
            error = _get(chunk, "error") or {}
            message = _get(error, "message") or "Anthropic stream error"
            raise RuntimeError(str(message))

        pieces: list[str] = []

        if chunk_type == "message_start":
            message = _get(chunk, "message") or {}
            usage = _get(message, "usage")
            self._merge_usage(_anthropic_usage(usage))

        elif chunk_type == "content_block_start":
            block = _get(chunk, "content_block") or {}
            if _get(block, "type") == "tool_use":
                index = _get(chunk, "index", 0)
                try:
                    index = int(index)
                except (TypeError, ValueError):
                    index = 0
                entry = self._tool_calls.setdefault(
                    index, {"id": "", "name": "", "arguments": ""}
                )
                entry["id"] = str(_get(block, "id") or entry["id"])
                entry["name"] = str(_get(block, "name") or entry["name"])
                tool_input = _get(block, "input")
                if isinstance(tool_input, dict) and tool_input:
                    entry["arguments"] += json.dumps(tool_input, ensure_ascii=False)

        elif chunk_type == "content_block_delta":
            delta = _get(chunk, "delta") or {}
            delta_type = _get(delta, "type")

            if delta_type == "text_delta":
                text = _as_text(_get(delta, "text"))
                if text:
                    self._content.append(text)
                    pieces.append(text)
            elif delta_type == "thinking_delta":
                thinking = _as_text(_get(delta, "thinking"))
                if thinking:
                    self._reasoning.append(thinking)
            elif delta_type == "input_json_delta":
                index = _get(chunk, "index", 0)
                try:
                    index = int(index)
                except (TypeError, ValueError):
                    index = 0
                entry = self._tool_calls.setdefault(
                    index, {"id": "", "name": "", "arguments": ""}
                )
                entry["arguments"] += _as_text(_get(delta, "partial_json"))

        elif chunk_type == "message_delta":
            delta = _get(chunk, "delta") or {}
            stop_reason = _get(delta, "stop_reason")
            if stop_reason:
                self._finish_reason = str(stop_reason)
            usage = _get(chunk, "usage")
            self._merge_usage(_anthropic_usage(usage))

        return "".join(pieces)

    def _merge_usage(self, usage: dict[str, int] | None) -> None:
        if not usage:
            return
        merged = dict(self._usage or {})
        for key, value in usage.items():
            merged[key] = int(value)
        prompt = merged.get("prompt_tokens", 0)
        completion = merged.get("completion_tokens", 0)
        # Anthropic 的 usage 分两条事件（input / output），total 必须重算，
        # 不能沿用后一条只带 output_tokens 的 total。
        merged["total_tokens"] = prompt + completion
        self._usage = merged

    # ── Google Gemini ────────────────────────────────────

    def _feed_google(self, chunk: Any) -> str | None:
        candidates = _get(chunk, "candidates")
        usage = _get(chunk, "usage_metadata")
        if candidates is None and usage is None:
            return None

        if usage is not None:
            self._usage = _usage_dict(
                {
                    "prompt_tokens": _get(usage, "prompt_token_count"),
                    "completion_tokens": _get(usage, "candidates_token_count"),
                    "total_tokens": _get(usage, "total_token_count"),
                }
            )

        pieces: list[str] = []
        for candidate in candidates or []:
            content = _get(candidate, "content") or {}
            for part in _get(content, "parts") or []:
                text = _as_text(_get(part, "text"))
                if text:
                    self._content.append(text)
                    pieces.append(text)

                function_call = _get(part, "function_call")
                if function_call:
                    index = len(self._tool_calls)
                    name = str(_get(function_call, "name") or "")
                    args = _get(function_call, "args") or {}
                    arguments = (
                        json.dumps(args, ensure_ascii=False)
                        if isinstance(args, dict)
                        else str(args)
                    )
                    self._tool_calls[index] = {
                        "id": f"call_{index}",
                        "name": name,
                        "arguments": arguments,
                    }

            finish = _get(candidate, "finish_reason")
            if finish:
                self._finish_reason = str(finish)

        return "".join(pieces)

    # ── 聚合 ─────────────────────────────────────────────

    def to_response(self) -> ProviderResponse:
        tool_calls: list[dict[str, Any]] = []
        for index in sorted(self._tool_calls):
            entry = self._tool_calls[index]
            tool_calls.append(
                {
                    "id": entry["id"] or f"call_{index}",
                    "type": "function",
                    "function": {
                        "name": entry["name"],
                        "arguments": entry["arguments"] or "{}",
                    },
                }
            )

        return ProviderResponse(
            content="".join(self._content),
            tool_calls=tool_calls or None,
            reasoning_content="".join(self._reasoning) or None,
            usage=self._usage,
            finish_reason=self._finish_reason,
        )


def _anthropic_usage(usage: Any) -> dict[str, int] | None:
    if usage is None:
        return None
    prompt = _get(usage, "input_tokens")
    completion = _get(usage, "output_tokens")
    result: dict[str, int] = {}
    try:
        if prompt is not None:
            result["prompt_tokens"] = int(prompt)
        if completion is not None:
            result["completion_tokens"] = int(completion)
    except (TypeError, ValueError):
        return None
    if result:
        result.setdefault(
            "total_tokens", result.get("prompt_tokens", 0) + result.get("completion_tokens", 0)
        )
    return result or None


async def _iterate(raw: Any) -> AsyncIterator[Any]:
    if hasattr(raw, "__aiter__"):
        async for item in raw:
            yield item
        return
    for item in raw:
        yield item
