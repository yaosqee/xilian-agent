"""Gateway 停止顺序：先等通道优雅退出，再取消残余任务。"""
import asyncio
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, ".")

from gateway import Gateway


class _Channel:
    name = "fake"

    def __init__(self):
        self.started = asyncio.Event()
        self.stop_event = asyncio.Event()

    async def start(self, handler):
        self.started.set()
        await self.stop_event.wait()

    async def stop(self):
        self.stop_event.set()


@pytest.mark.asyncio
async def test_gateway_stop_waits_for_channel():
    channel = _Channel()
    gateway = Gateway(agent=SimpleNamespace(process=lambda event: None))
    gateway.register(channel)

    task = asyncio.create_task(gateway.start())
    await asyncio.wait_for(channel.started.wait(), timeout=2)

    await asyncio.wait_for(gateway.stop(), timeout=3)
    await asyncio.wait_for(task, timeout=2)
