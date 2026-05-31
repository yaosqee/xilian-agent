"""测试 CoarseGrainEngine 核心逻辑（mock 外部服务）

Phase 1 测试：阈值触发、L2 会话摘要生成、force_coarse_all、事件消费生命周期。
"""
import os
import sys
sys.path.insert(0, ".")

import asyncio
import tempfile
import time
import pytest
from unittest.mock import AsyncMock, MagicMock

from packages.shared.database import DatabaseManager
from packages.agent.coarse_grain_engine import (
    CoarseGrainEngine,
    L2_TRIGGER_COUNT,
    L2_TRIGGER_COUNT_FAST,
    L2_MIN_EVENTS,
    L2_TRIGGER_DAYS,
)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def tmp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    try:
        os.unlink(path)
        os.unlink(path + "-wal")
        os.unlink(path + "-shm")
    except FileNotFoundError:
        pass


@pytest.fixture
def db(tmp_db_path):
    loop = asyncio.new_event_loop()
    db = DatabaseManager(tmp_db_path)
    loop.run_until_complete(db.init())
    yield db
    loop.run_until_complete(db.close())
    loop.close()


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.route = AsyncMock()
    return router


@pytest.fixture
def engine(db, mock_router):
    return CoarseGrainEngine(_db=db, _router=mock_router)


# ═══════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════

async def _seed_events(db, count: int, prefix: str = "事件", category: str = "fact"):
    """向 micro_events 表播种 N 条事件"""
    for i in range(count):
        await db.insert_micro_event(f"{prefix}{i+1}", category, 0.8)


# ═══════════════════════════════════════════════════════════
# 单元测试
# ═══════════════════════════════════════════════════════════

class TestCoarseGrainThresholds:

    @pytest.mark.asyncio
    async def test_not_triggered_below_threshold(self, engine, db):
        """事件数 < threshold → 不触发"""
        await _seed_events(db, 5)  # < L2_TRIGGER_COUNT (10)

        should, reason = await engine._should_trigger_l2()
        assert should is False
        assert "count" in reason

    @pytest.mark.asyncio
    async def test_triggered_at_threshold(self, engine, db):
        """事件数 >= threshold → 触发"""
        await _seed_events(db, L2_TRIGGER_COUNT)

        should, reason = await engine._should_trigger_l2()
        assert should is True
        assert f"count={L2_TRIGGER_COUNT}" in reason

    @pytest.mark.asyncio
    async def test_triggered_above_threshold(self, engine, db):
        """事件数 > threshold → 触发"""
        await _seed_events(db, L2_TRIGGER_COUNT + 3)

        should, reason = await engine._should_trigger_l2()
        assert should is True

    @pytest.mark.asyncio
    async def test_tool_side_effect_lowers_threshold(self, engine, db):
        """工具副作用 → 使用低阈值 L2_TRIGGER_COUNT_FAST"""
        await _seed_events(db, L2_TRIGGER_COUNT_FAST)  # 恰好等于低阈值

        # 无工具副作用 → 不触发（count=5 < 10）
        should, _ = await engine._should_trigger_l2()
        assert should is False

        # 设置工具副作用标志
        engine._tool_side_effect_seen = True
        should, reason = await engine._should_trigger_l2()
        assert should is True
        assert f"threshold={L2_TRIGGER_COUNT_FAST}" in reason

        # 标志应在检查后被消费
        assert engine._tool_side_effect_seen is False

    @pytest.mark.asyncio
    async def test_not_triggered_insufficient_min_events(self, engine, db):
        """事件数 < L2_MIN_EVENTS → 即使时间窗口满足也不触发"""
        await _seed_events(db, L2_MIN_EVENTS - 1)

        should, reason = await engine._should_trigger_l2()
        assert should is False

    @pytest.mark.asyncio
    async def test_empty_events(self, engine, db):
        """无事件 → 不触发"""
        should, reason = await engine._should_trigger_l2()
        assert should is False


class TestCoarseGrainL2Generation:

    @pytest.mark.asyncio
    async def test_generate_l2_summary(self, engine, mock_router, db):
        """正常生成 L2 会话摘要"""
        await _seed_events(db, L2_TRIGGER_COUNT)

        mock_response = MagicMock()
        mock_response.content = (
            '{"summary": "最近伙伴似乎在学习一些新东西，'
            '人家注意到他提到过几次关于编程的话题。",'
            '"topics": ["编程", "学习"]}'
        )
        mock_router.route.return_value = mock_response

        l2_id = await engine._coarse_to_l2()
        assert l2_id is not None
        assert l2_id > 0

        # 验证摘要已写入 session_summaries
        summaries = await db.get_recent_session_summaries(limit=1)
        assert len(summaries) == 1
        assert "编程" in summaries[0]["content"]

    @pytest.mark.asyncio
    async def test_events_consumed_after_l2(self, engine, mock_router, db):
        """L2 生成后活跃事件被标记为已消费"""
        await _seed_events(db, L2_TRIGGER_COUNT)

        mock_response = MagicMock()
        mock_response.content = '{"summary": "一份测试摘要没有什么实质内容但格式正确符合长度要求", "topics": ["测试"]}'
        mock_router.route.return_value = mock_response

        # 生成前：全部活跃
        active_before = await db.get_active_micro_events(limit=30)
        assert len(active_before) >= L2_TRIGGER_COUNT

        await engine._coarse_to_l2()

        # 生成后：全部被消费
        active_after = await db.get_active_micro_events(limit=30)
        assert len(active_after) == 0

    @pytest.mark.asyncio
    async def test_l2_insufficient_events(self, engine, db):
        """事件不足 → 不生成"""
        await _seed_events(db, L2_MIN_EVENTS - 1)

        l2_id = await engine._coarse_to_l2()
        assert l2_id is None

    @pytest.mark.asyncio
    async def test_l2_llm_error(self, engine, mock_router, db):
        """LLM 调用失败 → 返回 None"""
        await _seed_events(db, L2_TRIGGER_COUNT)
        mock_router.route.side_effect = Exception("API error")

        l2_id = await engine._coarse_to_l2()
        assert l2_id is None

    @pytest.mark.asyncio
    async def test_l2_json_parse_error(self, engine, mock_router, db):
        """JSON 解析失败 → 返回 None"""
        await _seed_events(db, L2_TRIGGER_COUNT)

        mock_response = MagicMock()
        mock_response.content = "这不是 JSON"
        mock_router.route.return_value = mock_response

        l2_id = await engine._coarse_to_l2()
        assert l2_id is None

    @pytest.mark.asyncio
    async def test_l2_summary_too_short(self, engine, mock_router, db):
        """生成的摘要过短 → 返回 None"""
        await _seed_events(db, L2_TRIGGER_COUNT)

        mock_response = MagicMock()
        mock_response.content = '{"summary": "短", "topics": []}'
        mock_router.route.return_value = mock_response

        l2_id = await engine._coarse_to_l2()
        assert l2_id is None


class TestForceCoarseAll:

    @pytest.mark.asyncio
    async def test_force_coarse_all_with_events(self, engine, mock_router, db):
        """force_coarse_all 在事件充足时生成 L2"""
        await _seed_events(db, L2_TRIGGER_COUNT)

        mock_response = MagicMock()
        mock_response.content = '{"summary": "一份通过force模式生成的测试摘要内容充实格式正确字数足够", "topics": ["测试"]}'
        mock_router.route.return_value = mock_response

        result = await engine.force_coarse_all()
        assert result is not None
        assert "force模式" in result

    @pytest.mark.asyncio
    async def test_force_coarse_all_no_events(self, engine, db):
        """force_coarse_all 在事件不足时返回 None"""
        # 不播种任何事件
        result = await engine.force_coarse_all()
        assert result is None


class TestCheckAndCoarse:

    @pytest.mark.asyncio
    async def test_check_and_coarse_noop(self, engine, db):
        """无事件 → check_and_coarse 返回 None"""
        result = await engine.check_and_coarse()
        assert result is None

    @pytest.mark.asyncio
    async def test_check_and_coarse_triggered(self, engine, mock_router, db):
        """事件达到阈值 → check_and_coarse 触发并生成 L2"""
        await _seed_events(db, L2_TRIGGER_COUNT)

        mock_response = MagicMock()
        mock_response.content = '{"summary": "检查触发的粗粒化摘要内容充实字数足够通过验证标准", "topics": ["测试"]}'
        mock_router.route.return_value = mock_response

        result = await engine.check_and_coarse()
        assert result is not None
        assert result["l2_updated"] is True
        assert result["l2_id"] is not None


# ═══════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════

class TestSessionSummaryDB:

    @pytest.mark.asyncio
    async def test_insert_and_retrieve_summaries(self, db):
        """session_summaries 表 CRUD"""
        id1 = await db.insert_session_summary("摘要一", "1,2,3")
        id2 = await db.insert_session_summary("摘要二", "4,5,6")

        summaries = await db.get_recent_session_summaries(limit=10)
        assert len(summaries) >= 2

        # 最近的排最前
        assert summaries[0]["id"] == id2

    @pytest.mark.asyncio
    async def test_source_event_ids_tracking(self, db):
        """source_event_ids 正确追踪"""
        await db.insert_session_summary("测试摘要", "10,20,30")
        summaries = await db.get_recent_session_summaries(limit=1)
        assert summaries[0]["source_event_ids"] == "10,20,30"
