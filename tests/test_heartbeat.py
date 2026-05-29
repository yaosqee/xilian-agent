"""
心跳测试：验证全链路连通性（V3.3 纯云端版）

2026-05-15 修订：移除本地 Ollama 测试，改为纯云端 DeepSeek 路由测试
Gateway(模拟) → Agent(模拟) → ModelRouter → 云端 API → 返回
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
async def test_ds_flash_chat():
    """DS V4-Flash 基础连通"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        pytest.skip("未配置 DEEPSEEK_API_KEY")

    router = ModelRouter()
    trace_id = str(uuid.uuid4())[:8]

    messages = [{"role": "user", "content": "你好，请用一句话介绍自己"}]

    logger.info("heartbeat.start", trace_id=trace_id, model="deepseek-v4-flash")

    try:
        reply = await router.route("memory_encoding", messages)
        reply_text = reply.content if hasattr(reply, 'content') else reply
        logger.info(
            "heartbeat.ds_flash_ok",
            trace_id=trace_id,
            reply_preview=reply_text[:100],
        )
        assert len(reply_text) > 0, "DS Flash 应返回非空回复"
    except Exception as e:
        logger.error("heartbeat.ds_flash_fail", trace_id=trace_id, error=str(e))
        pytest.fail(f"DS Flash 连接失败: {e}")


@pytest.mark.asyncio
async def test_ds_pro_chat():
    """DS V4-Pro 基础连通"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        pytest.skip("未配置 DEEPSEEK_API_KEY")

    router = ModelRouter()
    messages = [{"role": "user", "content": "回复：OK"}]

    try:
        reply = await router.route("chat", messages)
        reply_text = reply.content if hasattr(reply, 'content') else reply
        assert len(reply_text) > 0, "DS Pro 应返回非空回复"
    except Exception as e:
        pytest.fail(f"DS Pro 连接失败: {e}")


@pytest.mark.asyncio
async def test_embed_api():
    """嵌入 API 连通"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        pytest.skip("未配置 DEEPSEEK_API_KEY")
    if not os.getenv("EMBED_API_KEY"):
        # 尝试用 DEEPSEEK_API_KEY 作为 fallback
        pass

    router = ModelRouter()
    try:
        vec = await router.embed("你好世界")
        assert len(vec) == 1024, f"嵌入向量应为 1024 维，实际 {len(vec)}"
    except Exception as e:
        pytest.fail(f"嵌入 API 连接失败: {e}")


@pytest.mark.asyncio
async def test_routing():
    """路由逻辑测试"""
    if not os.getenv("DEEPSEEK_API_KEY"):
        pytest.skip("未配置 DEEPSEEK_API_KEY")

    router = ModelRouter()
    messages = [{"role": "user", "content": "回复：你好"}]

    # chat → DS Pro
    reply = await router.route("chat", messages)
    assert len(reply.content) > 0

    # memory_encoding → DS Flash
    reply = await router.route("memory_encoding", messages)
    assert len(reply.content) > 0


async def main():
    setup_logging()
    print("=" * 50)
    print("  昔涟 V3.3 · 心跳验证（纯云端）")
    print("=" * 50)

    await test_ds_flash_chat()
    await test_ds_pro_chat()
    await test_embed_api()
    await test_routing()

    print("=" * 50)
    print("  验证完成 ✅")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
