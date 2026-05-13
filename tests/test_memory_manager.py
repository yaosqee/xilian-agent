"""测试 MemoryManager 核心逻辑（mock 外部服务）"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from packages.shared.database import DatabaseManager
from packages.agent.memory_manager import MemoryManager


@pytest.fixture
def db():
    db = DatabaseManager(":memory:")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(db.init())
    yield db
    loop.run_until_complete(db.close())


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.route = AsyncMock(return_value="叙事化总结：伙伴今天很累呢。")
    return router


@pytest.fixture
def mock_ollama():
    ollama = MagicMock()
    ollama.embed = AsyncMock(return_value={"embeddings": [[0.1] * 1024]})
    return ollama


@pytest.fixture
def memory_mgr(db, mock_router, mock_ollama):
    mgr = MemoryManager(
        db=db, chroma_host="localhost", chroma_port=9999,
        ollama_client=mock_ollama, model_router=mock_router,
        max_records=100,
    )
    return mgr


@pytest.mark.asyncio
async def test_calculate_importance_basic(memory_mgr):
    exchanges = [{"role": "user", "content": "今天好累啊"}, {"role": "assistant", "content": "摸摸头~"}]
    score = memory_mgr._calculate_importance(exchanges, {"primary_intensity": 0.8})
    assert 0.1 <= score <= 1.0


@pytest.mark.asyncio
async def test_calculate_importance_high(memory_mgr):
    exchanges = [
        {"role": "user", "content": "记住这个秘密"},
        {"role": "assistant", "content": "人家会好好记在书里的~"},
    ]
    score = memory_mgr._calculate_importance(exchanges, {"primary_intensity": 0.95})
    assert score > 0.3


@pytest.mark.asyncio
async def test_calculate_importance_empty_emotion(memory_mgr):
    score = memory_mgr._calculate_importance([{"role": "user", "content": "嗯"}], {})
    assert 0.1 <= score <= 1.0


@pytest.mark.asyncio
async def test_merge_context_new(memory_mgr):
    new = {"exchanges": [{"role": "user", "content": "hi"}], "emotion": {}}
    result = memory_mgr._merge_context(None, new)
    assert result == new


@pytest.mark.asyncio
async def test_merge_context_dedup(memory_mgr):
    old = {"exchanges": [{"role": "user", "content": "hi"}], "emotion": {}}
    new = {"exchanges": [{"role": "user", "content": "hi"}, {"role": "user", "content": "world"}], "emotion": {"primary_emotion": "开心"}}
    result = memory_mgr._merge_context(old, new)
    assert len(result["exchanges"]) == 2
    assert result["emotion"]["primary_emotion"] == "开心"


@pytest.mark.asyncio
async def test_merge_context_cap(memory_mgr):
    old = {"exchanges": [{"role": "user", "content": f"msg{i}"} for i in range(20)], "emotion": {}}
    new = {"exchanges": [{"role": "user", "content": "new"}], "emotion": {}}
    result = memory_mgr._merge_context(old, new)
    assert len(result["exchanges"]) <= 20


@pytest.mark.asyncio
async def test_initial_encoding_state(memory_mgr):
    assert memory_mgr.encoding_state == "idle"
    assert memory_mgr.has_pending_encoding is False
    assert memory_mgr._exchanges_since_last_encoding == 0


@pytest.mark.asyncio
async def test_signal_new_message(memory_mgr):
    memory_mgr._idle_event.clear()
    memory_mgr.signal_new_message()
    assert memory_mgr._idle_event.is_set()


@pytest.mark.asyncio
async def test_encode_memory_full_pipeline(memory_mgr, db):
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


@pytest.mark.asyncio
async def test_encode_memory_calls_router(memory_mgr, mock_router):
    exchanges = [{"role": "user", "content": "hello"}, {"role": "assistant", "content": "hi~"}]
    await memory_mgr.encode_memory({"exchanges": exchanges, "emotion": {}})
    mock_router.route.assert_called_once()
    assert mock_router.route.call_args[0][0] == "memory_encoding"


@pytest.mark.asyncio
async def test_retrieve_without_chroma(memory_mgr):
    results = await memory_mgr.retrieve_memories("测试消息", k=3)
    assert results == []


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


@pytest.mark.asyncio
async def test_health_check_unavailable(memory_mgr):
    ok = await memory_mgr.health_check()
    assert ok is False


@pytest.mark.asyncio
async def test_manage_capacity_under_limit(memory_mgr, db):
    for i in range(5):
        await db.insert_episodic_memory(f"mem-{i}", "[]")
    evicted = await memory_mgr.manage_capacity(max_records=100)
    assert evicted == 0


@pytest.mark.asyncio
async def test_repair_pending_empty(memory_mgr):
    repaired = await memory_mgr.repair_pending()
    assert repaired == 0
