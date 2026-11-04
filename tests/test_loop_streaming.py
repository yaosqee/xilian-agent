"""P1.5 流式归一化单测（不连网）。"""
import sys

import pytest

sys.path.insert(0, ".")

from packages.agent.loop.streaming import StreamAccumulator


async def stream_of(*chunks):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_openai_stream_text_and_reasoning_are_separated():
    acc = StreamAccumulator()
    chunks = [
        {"choices": [{"delta": {"reasoning_content": "想", "content": "你"}}]},
        {
            "choices": [
                {"delta": {"content": "好"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        },
    ]

    pieces = [piece async for piece in acc.consume(stream_of(*chunks))]
    response = acc.to_response()

    assert pieces == ["你", "好"]
    assert response.content == "你好"
    assert response.reasoning_content == "想"
    assert response.finish_reason == "stop"
    assert response.usage["total_tokens"] == 5
    assert response.tool_calls is None


@pytest.mark.asyncio
async def test_openai_stream_tool_arguments_are_merged_by_index():
    acc = StreamAccumulator()
    chunks = [
        {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "id": "c1",
                        "function": {"name": "query_weather", "arguments": '{"city":'},
                    }]
                }
            }]
        },
        {
            "choices": [{
                "delta": {
                    "tool_calls": [{
                        "index": 0,
                        "function": {"arguments": '"杭州"}'},
                    }]
                },
                "finish_reason": "tool_calls",
            }]
        },
    ]

    pieces = [piece async for piece in acc.consume(stream_of(*chunks))]
    response = acc.to_response()

    assert pieces == []
    assert response.content == ""
    assert response.tool_calls[0]["id"] == "c1"
    assert response.tool_calls[0]["function"]["name"] == "query_weather"
    assert response.tool_calls[0]["function"]["arguments"] == '{"city":"杭州"}'


@pytest.mark.asyncio
async def test_anthropic_stream_text_tool_and_usage():
    acc = StreamAccumulator()
    chunks = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 10}}},
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "你"},
        },
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {
                "type": "tool_use", "id": "toolu_1", "name": "query_weather",
            },
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"city":"杭州"}'},
        },
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 3},
        },
    ]

    pieces = [piece async for piece in acc.consume(stream_of(*chunks))]
    response = acc.to_response()

    assert pieces == ["你"]
    assert response.content == "你"
    assert response.finish_reason == "tool_use"
    assert response.tool_calls[0]["id"] == "toolu_1"
    assert response.tool_calls[0]["function"]["arguments"] == '{"city":"杭州"}'
    assert response.usage == {
        "prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13,
    }


@pytest.mark.asyncio
async def test_google_stream_text_and_function_call():
    acc = StreamAccumulator()
    chunks = [
        {
            "candidates": [{
                "content": {"parts": [{"text": "好"}]},
                "finish_reason": "STOP",
            }],
            "usage_metadata": {
                "prompt_token_count": 4,
                "candidates_token_count": 1,
                "total_token_count": 5,
            },
        },
        {
            "candidates": [{
                "content": {
                    "parts": [{
                        "function_call": {
                            "name": "query_weather", "args": {"city": "杭州"},
                        }
                    }]
                }
            }]
        },
    ]

    pieces = [piece async for piece in acc.consume(stream_of(*chunks))]
    response = acc.to_response()

    assert pieces == ["好"]
    assert response.content == "好"
    assert response.tool_calls[0]["id"] == "call_0"
    assert response.tool_calls[0]["function"]["name"] == "query_weather"
    assert response.tool_calls[0]["function"]["arguments"] == '{"city": "杭州"}'
    assert response.usage["total_tokens"] == 5


@pytest.mark.asyncio
async def test_unknown_chunks_are_ignored():
    acc = StreamAccumulator()

    pieces = [piece async for piece in acc.consume(stream_of({"foo": "bar"}))]

    assert pieces == []
    assert acc.to_response().content == ""
    assert acc.to_response().tool_calls is None
