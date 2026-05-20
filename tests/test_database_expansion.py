"""测试 episodic_memories + message_queue 表 CRUD"""
import sys
sys.path.insert(0, ".")
import pytest

from packages.shared.database import DatabaseManager


@pytest.fixture
def db():
    """同步 fixture — 在当前事件循环中初始化"""

    import asyncio
    db = DatabaseManager(":memory:")
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
    loop.run_until_complete(db.init())
    yield db
    loop.run_until_complete(db.close())


@pytest.mark.asyncio
async def test_insert_and_query_episodic(db):
    mid = await db.insert_episodic_memory("伙伴今天很开心", "[]", importance=0.7)
    assert mid > 0
    mem = await db.get_episodic_memory(mid)
    assert mem["summary"] == "伙伴今天很开心"
    assert mem["embedding_status"] == "pending"
    assert mem["access_count"] == 0


@pytest.mark.asyncio
async def test_update_embedding_status(db):
    mid = await db.insert_episodic_memory("测试", "[]")
    await db.update_embedding_status(mid, "done", "emb-123")
    mem = await db.get_episodic_memory(mid)
    assert mem["embedding_status"] == "done"
    assert mem["embedding_id"] == "emb-123"


@pytest.mark.asyncio
async def test_get_episodic_pending(db):
    await db.insert_episodic_memory("a", "[]")
    await db.insert_episodic_memory("b", "[]")
    mid = await db.insert_episodic_memory("c", "[]")
    await db.update_embedding_status(mid, "done", "emb-ok")
    pending = await db.get_episodic_pending()
    assert len(pending) == 2


@pytest.mark.asyncio
async def test_get_episodic_recent(db):
    for i in range(5):
        mid = await db.insert_episodic_memory(f"memory-{i}", "[]")
        await db.update_embedding_status(mid, "done", f"emb-{i}")
    recent = await db.get_episodic_recent(3)
    assert len(recent) == 3
    assert recent[0]["summary"] == "memory-4"


@pytest.mark.asyncio
async def test_get_episodic_by_embedding_ids(db):
    m1 = await db.insert_episodic_memory("a", "[]")
    await db.update_embedding_status(m1, "done", "emb-a")
    m2 = await db.insert_episodic_memory("b", "[]")
    await db.update_embedding_status(m2, "done", "emb-b")
    results = await db.get_episodic_by_embedding_ids(["emb-a", "emb-nope"])
    assert len(results) == 1
    assert results[0]["summary"] == "a"


@pytest.mark.asyncio
async def test_get_all_episodic(db):
    for _ in range(3):
        await db.insert_episodic_memory("x", "[]")
    all_mem = await db.get_all_episodic()
    assert len(all_mem) == 3
    assert "id" in all_mem[0]


@pytest.mark.asyncio
async def test_increment_access_count(db):
    mid = await db.insert_episodic_memory("test", "[]")
    await db.increment_access_count(mid)
    mem = await db.get_episodic_memory(mid)
    assert mem["access_count"] == 1
    assert mem["last_accessed"] is not None


@pytest.mark.asyncio
async def test_delete_episodic(db):
    mid = await db.insert_episodic_memory("test", "[]")
    assert await db.get_episodic_count() == 1
    await db.delete_episodic(mid)
    assert await db.get_episodic_count() == 0


@pytest.mark.asyncio
async def test_queue_push_pop_done(db):
    assert await db.queue_push("evt-1", '{"msg":"hello"}') is True
    msg = await db.queue_pop()
    assert msg["event_id"] == "evt-1"
    await db.queue_mark_done("evt-1")
    assert await db.queue_pop() is None


@pytest.mark.asyncio
async def test_queue_idempotent(db):
    assert await db.queue_push("evt-1", "p") is True
    assert await db.queue_push("evt-1", "p") is False


@pytest.mark.asyncio
async def test_queue_fifo_order(db):
    await db.queue_push("evt-a", '{}')
    await db.queue_push("evt-b", '{}')
    await db.queue_push("evt-c", '{}')
    assert (await db.queue_pop())["event_id"] == "evt-a"
    assert (await db.queue_pop())["event_id"] == "evt-b"
    assert (await db.queue_pop())["event_id"] == "evt-c"


@pytest.mark.asyncio
async def test_queue_mark_failed(db):
    await db.queue_push("evt-1", "x")
    await db.queue_pop()
    await db.queue_mark_failed("evt-1", "test error")
    cur = await db._conn.execute("SELECT status, error_msg FROM message_queue WHERE event_id='evt-1'")
    row = await cur.fetchone()
    assert row["status"] == "failed"
    assert "test error" in row["error_msg"]


@pytest.mark.asyncio
async def test_queue_recover_stale(db):
    await db.queue_push("evt-stale", "p")
    await db.queue_pop()
    await db._conn.execute("UPDATE message_queue SET started_at=0 WHERE event_id='evt-stale'")
    await db._conn.commit()
    assert await db.queue_recover_stale(timeout_minutes=5) == 1
    msg = await db.queue_pop()
    assert msg["event_id"] == "evt-stale"


@pytest.mark.asyncio
async def test_queue_purge_old(db):
    await db.queue_push("evt-old", "x")
    await db.queue_pop()
    await db.queue_mark_done("evt-old")
    await db._conn.execute("UPDATE message_queue SET completed_at=1 WHERE event_id='evt-old'")
    await db._conn.commit()
    purged = await db.queue_purge_old(days=0)
    assert purged >= 1


@pytest.mark.asyncio
async def test_init_idempotent(db):
    await db.init()
    cur = await db._conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row["name"] async for row in cur]
    assert "episodic_memories" in tables
    assert "message_queue" in tables
    assert "conversation_logs" in tables
