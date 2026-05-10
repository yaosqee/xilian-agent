"""
心跳测试：验证全链路连通性
Gateway(模拟) → Agent(模拟) → ModelRouter → 本地模型 → 返回
"""
import sys
sys.path.insert(0, ".")

import os
import asyncio
import uuid
import pytest
from loguru import logger
from packages.shared import ModelRouter
from packages.shared.logging_config import setup_logging


@pytest.mark.asyncio
async def test_local_chat():
    """本地模型基础连通"""
    router = ModelRouter()
    trace_id = str(uuid.uuid4())[:8]

    messages = [{"role": "user", "content": "你好，请用一句话介绍自己"}]

    logger.info("heartbeat.start", trace_id=trace_id, model="qwen3:14b")

    try:
        reply = await router._call_ollama(messages)
        logger.info(
            "heartbeat.local_ok",
            trace_id=trace_id,
            reply_preview=reply[:100],
        )
        assert len(reply) > 0, "本地模型应返回非空回复"
    except Exception as e:
        logger.error("heartbeat.local_fail", trace_id=trace_id, error=str(e))
        pytest.fail(f"本地模型连接失败: {e}")


@pytest.mark.asyncio
async def test_cloud_fallback():
    """云端模型连通（需要配置 API Key）"""
    if not os.getenv("DASHSCOPE_API_KEY"):
        pytest.skip("未配置 DASHSCOPE_API_KEY")

    router = ModelRouter()
    messages = [{"role": "user", "content": "回复：OK"}]

    try:
        reply = await router._call_qwen(messages)
        assert len(reply) > 0, "云端模型应返回非空回复"
    except Exception as e:
        pytest.fail(f"云端连接失败: {e}")


@pytest.mark.asyncio
async def test_routing():
    """路由逻辑测试"""
    if not os.getenv("DASHSCOPE_API_KEY"):
        pytest.skip("未配置 DASHSCOPE_API_KEY")

    router = ModelRouter()
    messages = [{"role": "user", "content": "回复：你好"}]

    reply = await router.route("chat", messages)
    assert len(reply) > 0, "chat 路由应返回非空回复"

    reply = await router.route("reasoning", messages)
    assert len(reply) > 0, "reasoning 路由应返回非空回复"


# 保留手动运行入口
async def main():
    setup_logging()
    print("=" * 50)
    print("  昔涟 V3.2 · 阶段 0 · 心跳验证")
    print("=" * 50)

    await test_local_chat()
    await test_cloud_fallback()
    await test_routing()

    print("=" * 50)
    print("  验证完成 ✅")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
