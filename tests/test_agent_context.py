"""AgentContext 上下文压缩回插回归测试（数据丢失三件套 1.2）。"""
import asyncio
import sys

sys.path.insert(0, ".")

import pytest
from unittest.mock import AsyncMock

from packages.agent.agent_context import AgentContext


def _seed(ctx: AgentContext, rounds: int = 4, tokens: int = 1000) -> list[dict]:
    """预置 rounds 轮对话，返回原始消息列表。"""
    msgs = []
    for i in range(rounds):
        msgs.append({"role": "user", "content": f"用户消息 {i}"})
        msgs.append({"role": "assistant", "content": f"回复 {i}"})
    ctx.history = list(msgs)
    ctx._total_history_tokens = tokens
    return msgs


async def _run_scheduled_compression(ctx: AgentContext, n_rounds: int) -> None:
    """触发 _schedule_compression 并等待其 fire-and-forget 的 _compress 任务完成。"""
    before = set(asyncio.all_tasks())
    ctx._schedule_compression(n_rounds)
    for t in set(asyncio.all_tasks()) - before:
        await t


@pytest.mark.asyncio
async def test_compression_failure_rolls_back_messages():
    """压缩返回 None 时，被移除的最老消息必须回插，token 计数恢复。"""
    ctx = AgentContext()
    _seed(ctx)
    ctx.set_compress_callback(AsyncMock(return_value=None))

    await _run_scheduled_compression(ctx, 4)

    assert len(ctx.history) == 8
    assert ctx._total_history_tokens == 1000


@pytest.mark.asyncio
async def test_compression_exception_rolls_back_messages():
    """压缩抛异常时同样回插，不丢数据。"""
    ctx = AgentContext()
    _seed(ctx)

    async def boom(_msgs):
        raise RuntimeError("LLM down")

    ctx.set_compress_callback(boom)

    await _run_scheduled_compression(ctx, 4)

    assert len(ctx.history) == 8
    assert ctx._total_history_tokens == 1000


@pytest.mark.asyncio
async def test_compression_success_injects_summary():
    """压缩成功：原始 8 条被移除，注入 1 条摘要，不做回插。"""
    ctx = AgentContext()
    _seed(ctx)
    ctx.set_compress_callback(
        AsyncMock(return_value="（昔涟在书页边缘轻轻记下：测试摘要）")
    )

    await _run_scheduled_compression(ctx, 4)

    assert len(ctx.history) == 1
    assert ctx.history[0]["role"] == "system"
    assert ctx.history[0]["content"].startswith("（昔涟在书页边缘轻轻记下：")
