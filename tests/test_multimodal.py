"""M2-8: 识图默认切到 DeepSeek 视觉模型。"""
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, ".")

from packages.agent.pipeline.multimodal import MultimodalProcessor


@pytest.mark.asyncio
async def test_describe_image_defaults_to_deepseek(monkeypatch):
    monkeypatch.delenv("VISION_PROVIDER", raising=False)
    monkeypatch.delenv("VISION_MODEL", raising=False)

    adapter = SimpleNamespace(describe_image=AsyncMock(return_value="一只橘猫趴在窗边。"))
    router = SimpleNamespace(
        _adapters={"deepseek": adapter},
        _create_adapter=lambda provider: None,
    )
    processor = MultimodalProcessor(ctx=None, router=router)

    result = await processor.describe_image("https://example.com/cat.png")

    assert result == "一只橘猫趴在窗边。"
    adapter.describe_image.assert_awaited_once_with(
        "https://example.com/cat.png",
        model="deepseek-v4-flash-vision-exp",
    )


@pytest.mark.asyncio
async def test_describe_image_cached(monkeypatch):
    monkeypatch.delenv("VISION_PROVIDER", raising=False)

    adapter = SimpleNamespace(describe_image=AsyncMock(return_value="缓存描述"))
    router = SimpleNamespace(
        _adapters={"deepseek": adapter},
        _create_adapter=lambda provider: None,
    )
    processor = MultimodalProcessor(ctx=None, router=router)

    first = await processor.describe_image("https://example.com/a.png")
    second = await processor.describe_image("https://example.com/a.png")

    assert first == second == "缓存描述"
    assert adapter.describe_image.await_count == 1
