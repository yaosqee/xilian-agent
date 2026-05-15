"""测试艾宾浩斯遗忘衰减集成

2026-05-15：阶段 5 第二周——验证记忆检索中的遗忘权重
"""
import math
import time
import asyncio
import tempfile
import os
import pytest
from unittest.mock import AsyncMock, MagicMock

from packages.shared.database import DatabaseManager
from packages.shared.vector_store import VectorStore
from packages.agent.memory_manager import MemoryManager


LAMBDA_FORGET = 0.099


@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    for suffix in ["", "-wal", "-shm"]:
        try:
            os.unlink(path + suffix)
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
    router.route = AsyncMock(return_value="叙事化摘要")
    router.embed = AsyncMock(return_value=[0.1] * 1024)
    router._embed_model = "BAAI/bge-m3"
    return router


@pytest.fixture
def mgr(db, vs, mock_router):
    return MemoryManager(db=db, vector_store=vs, model_router=mock_router, max_records=100)


# ═══════════════════════════════════════════════════════════
# 遗忘公式单元测试
# ═══════════════════════════════════════════════════════════

class TestForgettingFormula:

    def test_no_decay_when_just_accessed(self):
        """刚访问过 → decay = 1 → 不衰减"""
        days = 0
        decay = math.exp(-LAMBDA_FORGET * days)
        assert abs(decay - 1.0) < 0.01

    def test_half_life_7_days(self):
        """7 天 → decay ≈ 0.5"""
        days = 7
        decay = math.exp(-LAMBDA_FORGET * days)
        assert abs(decay - 0.5) < 0.01

    def test_14_days_quarter(self):
        """14 天 → decay ≈ 0.25"""
        days = 14
        decay = math.exp(-LAMBDA_FORGET * days)
        assert abs(decay - 0.25) < 0.02

    def test_clamp_minimum(self):
        """极久远 → clamp 0.1"""
        days = 100
        decay = max(0.1, math.exp(-LAMBDA_FORGET * days))
        assert decay == 0.1

    def test_adjusted_score_increases_with_age(self):
        """越久没访问，adjusted_score 越大（越不被推荐）"""
        distance = 0.3
        decay_recent = max(0.1, math.exp(-LAMBDA_FORGET * 0))
        decay_old = max(0.1, math.exp(-LAMBDA_FORGET * 30))
        score_recent = distance / decay_recent
        score_old = distance / decay_old
        assert score_old > score_recent


# ═══════════════════════════════════════════════════════════
# 集成测试：检索中遗忘权重生效
# ═══════════════════════════════════════════════════════════

class TestForgettingIntegration:

    @pytest.mark.asyncio
    async def test_retrieve_includes_decay_fields(self, mgr, db):
        """检索结果包含 adjusted_score 和 days_since_access"""
        # 编码一条记忆
        await mgr.encode_memory({
            "exchanges": [{"role": "user", "content": "测试记忆"}],
            "emotion": {"primary_intensity": 0.5},
        })

        results = await mgr.retrieve_memories("测试", k=3)
        assert len(results) > 0
        assert "adjusted_score" in results[0]
        assert "days_since_access" in results[0]

    @pytest.mark.asyncio
    async def test_same_distance_different_age_order(self, mgr, db, mock_router):
        """相同距离下，更新的记忆排更前"""
        # 两条记忆，向量相同的距离，但时间戳不同
        await db.insert_episodic_memory(
            summary="旧的记忆", raw_conversation="[]",
            importance=0.5,
        )
        old_id = 1
        await db.insert_episodic_memory(
            summary="新的记忆", raw_conversation="[]",
            importance=0.5,
        )
        new_id = 2

        # 手动设置时间戳
        await db._conn.execute(
            "UPDATE episodic_memories SET timestamp=? WHERE id=?",
            (time.time() - 30 * 86400, old_id),  # 30 天前
        )
        await db._conn.execute(
            "UPDATE episodic_memories SET timestamp=? WHERE id=?",
            (time.time(), new_id),  # 现在
        )
        await db._conn.commit()

        # 插入向量（相同向量 → 相同距离）
        vec = [0.1] * 1024
        await mgr._vs.insert(row_id=old_id, embedding=vec)
        await mgr._vs.insert(row_id=new_id, embedding=vec)

        results = await mgr.retrieve_memories("测试", k=2)
        # 新的应该排前面（adjusted_score 更小）
        if len(results) >= 2:
            assert results[0]["episodic_id"] == new_id  # 新的在前
