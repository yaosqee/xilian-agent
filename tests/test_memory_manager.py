"""测试 MemoryManager 核心逻辑（mock 外部服务）
import sys
sys.path.insert(0, ".")
2026-05-15 修订：适配 sqlite-vec，移除 ChromaDB/Ollama mock
"""

import os
import asyncio
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock

from packages.shared.database import DatabaseManager
from packages.shared.vector_store import VectorStore
from packages.agent.memory_manager import MemoryManager


@pytest.fixture
def tmp_db_path():
    """创建临时数据库路径"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    # 清理
    try:
        os.unlink(path)
        os.unlink(path + "-wal")
        os.unlink(path + "-shm")
    except FileNotFoundError:
        pass


@pytest.fixture
def db(tmp_db_path):
    loop = asyncio.get_event_loop()
    db = DatabaseManager(tmp_db_path)
    loop.run_until_complete(db.init())
    yield db
    loop.run_until_complete(db.close())


@pytest.fixture
def vs(tmp_db_path):
    loop = asyncio.get_event_loop()
    vs = VectorStore(db_path=tmp_db_path)
    loop.run_until_complete(vs.init())
    yield vs
    loop.run_until_complete(vs.close())


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.route = AsyncMock(return_value="叙事化总结：伙伴今天很累呢。")
    router.embed = AsyncMock(return_value=[0.1] * 1024)
    router._embed_model = "BAAI/bge-m3"
    return router


@pytest.fixture
def memory_mgr(db, vs, mock_router):
    return MemoryManager(
        db=db,
        vector_store=vs,
        model_router=mock_router,
        max_records=100,
    )


def test_calculate_importance_basic(memory_mgr):
    exchanges = [{"role": "user", "content": "今天好累啊"}, {"role": "assistant", "content": "摸摸头~"}]
    score = memory_mgr._calculate_importance(exchanges, {"primary_intensity": 0.8})
    assert 0.1 <= score <= 1.0


def test_calculate_importance_high(memory_mgr):
    exchanges = [
        {"role": "user", "content": "记住这个秘密"},
        {"role": "assistant", "content": "人家会好好记在书里的~"},
    ]
    score = memory_mgr._calculate_importance(exchanges, {"primary_intensity": 0.95})
    assert score > 0.3


def test_calculate_importance_empty_emotion(memory_mgr):
    score = memory_mgr._calculate_importance([{"role": "user", "content": "嗯"}], {})
    assert 0.1 <= score <= 1.0


def test_merge_context_new(memory_mgr):
    new = {"exchanges": [{"role": "user", "content": "hi"}], "emotion": {}}
    result = memory_mgr._merge_context(None, new)
    assert result == new


def test_merge_context_dedup(memory_mgr):
    old = {"exchanges": [{"role": "user", "content": "hi"}], "emotion": {}}
    new = {"exchanges": [{"role": "user", "content": "hi"}, {"role": "user", "content": "world"}], "emotion": {"primary_emotion": "开心"}}
    result = memory_mgr._merge_context(old, new)
    assert len(result["exchanges"]) == 2
    assert result["emotion"]["primary_emotion"] == "开心"


def test_merge_context_cap(memory_mgr):
    old = {"exchanges": [{"role": "user", "content": f"msg{i}"} for i in range(20)], "emotion": {}}
    new = {"exchanges": [{"role": "user", "content": "new"}], "emotion": {}}
    result = memory_mgr._merge_context(old, new)
    assert len(result["exchanges"]) <= 20


def test_initial_encoding_state(memory_mgr):
    assert memory_mgr.encoding_state == "idle"
    assert memory_mgr.has_pending_encoding is False
    assert memory_mgr._exchanges_since_last_encoding == 0


def test_signal_new_message(memory_mgr):
    memory_mgr._idle_event.clear()
    memory_mgr.signal_new_message()
    assert memory_mgr._idle_event.is_set()


@pytest.mark.asyncio
async def test_encode_memory_full_pipeline(memory_mgr, db, mock_router):
    exchanges = [
        {"role": "user", "content": "今天好累啊"},
        {"role": "assistant", "content": "抱抱~"},
    ]
    eid = await memory_mgr.encode_memory({"exchanges": exchanges, "emotion": {"primary_intensity": 0.7}})
    assert eid > 0
    mem = await db.get_episodic_memory(eid)
    assert mem is not None
    assert "叙事化总结" in mem["summary"]
    assert mem["importance"] > 0
    mock_router.embed.assert_called()


@pytest.mark.asyncio
async def test_encode_memory_calls_router(memory_mgr, mock_router):
    exchanges = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi~"}]
    await memory_mgr.encode_memory({"exchanges": exchanges, "emotion": {}})
    mock_router.route.assert_called_once()
    assert mock_router.route.call_args[0][0] == "memory_encoding"


@pytest.mark.asyncio
async def test_retrieve_memories(memory_mgr, mock_router):
    # 先编码一条记忆
    exchanges = [{"role": "user", "content": "今天好累啊"}, {"role": "assistant", "content": "抱抱~"}]
    await memory_mgr.encode_memory({"exchanges": exchanges, "emotion": {"primary_intensity": 0.7}})

    # 检索
    mock_router.embed.reset_mock()
    results = await memory_mgr.retrieve_memories("好累", k=3)
    assert len(results) > 0
    assert "叙事化总结" in results[0]["summary"]


@pytest.mark.asyncio
async def test_schedule_encoding_counts_exchanges(memory_mgr):
    initial = memory_mgr._exchanges_since_last_encoding
    ctx = {"exchanges": [{"role": "user", "content": "test"}], "emotion": {}}
    await memory_mgr.schedule_encoding(ctx)
    assert memory_mgr._exchanges_since_last_encoding == initial + 1
    if memory_mgr._encoding_task and not memory_mgr._encoding_task.done():
        memory_mgr._encoding_task.cancel()


@pytest.mark.asyncio
async def test_shutdown_empty(memory_mgr):
    result = await memory_mgr.shutdown()
    assert result == "empty"
    assert memory_mgr.encoding_state == "done"


def test_health_check_ok(memory_mgr):
    loop = asyncio.get_event_loop()
    ok = loop.run_until_complete(memory_mgr.health_check())
    assert ok is True


@pytest.mark.asyncio
async def test_manage_capacity_under_limit(memory_mgr, db):
    for i in range(5):
        await db.insert_episodic_memory(f"mem-{i}", "[]")
    evicted = await memory_mgr.manage_capacity(max_records=100)
    assert evicted == 0


def test_repair_pending_empty(memory_mgr):
    loop = asyncio.get_event_loop()
    repaired = loop.run_until_complete(memory_mgr.repair_pending())
    assert repaired == 0
