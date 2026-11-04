"""MemoryManager.shutdown 的超时兜底（2026-11-04：网络卡住时进程退出不能被拖死）。"""
import asyncio
import sys

sys.path.insert(0, ".")

import pytest

from packages.agent.memory_manager import MemoryManager


def _bare_manager(timeout: float = 0.05):
    mm = MemoryManager.__new__(MemoryManager)
    mm._shutdown_requested = False
    mm._encoding_task = None
    mm._pending_context = {"messages": [{"role": "user", "content": "hi"}]}
    mm._exchanges_since_last_encoding = 1
    mm._encoding_state = "idle"
    mm._shutdown_encode_timeout = timeout
    return mm


@pytest.mark.asyncio
async def test_shutdown_returns_failed_on_timeout():
    mm = _bare_manager(timeout=0.05)

    async def slow_encode(context, persona_topics=None):
        await asyncio.sleep(10)
        return 1

    mm.encode_memory = slow_encode

    result = await mm.shutdown()

    assert result == "failed"
    assert mm.encoding_state == "done"


@pytest.mark.asyncio
async def test_shutdown_skips_when_no_pending():
    mm = _bare_manager()
    mm._pending_context = None
    mm._exchanges_since_last_encoding = 0

    assert await mm.shutdown() == "empty"
