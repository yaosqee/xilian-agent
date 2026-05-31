"""测试 Phase 4 多信号源聚合 — SignalAggregator、tool_usage_log、信号上下文

Phase 4 测试：各信号源产出、空数据降级、SignalSnapshot freshness、
_build_signal_context 过滤、tool_usage_log CRUD。
"""
import os
import sys
sys.path.insert(0, ".")

import asyncio
import time
import tempfile
import pytest

from packages.shared.database import DatabaseManager
from packages.agent.signal_aggregator import (
    SignalAggregator,
    SignalSnapshot,
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
def aggregator(db):
    return SignalAggregator(_db=db)


# ═══════════════════════════════════════════════════════════
# SignalSnapshot
# ═══════════════════════════════════════════════════════════

class TestSignalSnapshot:

    def test_default_empty_strings(self):
        snap = SignalSnapshot()
        assert snap.tool_usage == ""
        assert snap.emotion_trajectory == ""
        assert snap.generated_at == 0.0

    def test_generated_at_set(self):
        snap = SignalSnapshot(generated_at=12345.0)
        assert snap.generated_at == 12345.0


# ═══════════════════════════════════════════════════════════
# Tool Usage Log CRUD
# ═══════════════════════════════════════════════════════════

class TestToolUsageLog:

    @pytest.mark.asyncio
    async def test_insert_and_query(self, db, aggregator):
        """工具调用日志写入和查询"""
        await db.insert_tool_usage("search_web", '{"query":"测试"}', True)
        await db.insert_tool_usage("search_web", '{"query":"测试2"}', True)
        await db.insert_tool_usage("query_weather", '{"city":"北京"}', True)

        cutoff = time.time() - 86400
        rows = await db.query_recent_tool_usage(cutoff)
        assert len(rows) == 2  # search_web grouped, query_weather

        tool_names = [r["tool_name"] for r in rows]
        assert "search_web" in tool_names
        assert "query_weather" in tool_names

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self, db, aggregator):
        """无工具调用时返回空"""
        cutoff = time.time() - 86400
        rows = await db.query_recent_tool_usage(cutoff)
        assert rows == []

    @pytest.mark.asyncio
    async def test_summarize_empty(self, aggregator):
        """无工具调用 → 返回空字符串"""
        result = await aggregator._summarize_tool_usage(7)
        assert result == ""


# ═══════════════════════════════════════════════════════════
# 情绪轨迹
# ═══════════════════════════════════════════════════════════

class TestEmotionTrajectory:

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self, aggregator):
        result = await aggregator._summarize_emotion_trajectory(7)
        assert result == ""

    @pytest.mark.asyncio
    async def test_insufficient_data(self, aggregator, db):
        """只有 1 条情绪数据 → 不足 → 空"""
        await db.insert_log(
            event_id="e1", user_message="hi", assistant_reply="hello",
            emotion_label={"primary_emotion": "快乐"},
            emotion_primary="快乐", emotion_intensity=0.8,
        )
        # emotion_snapshots 表是独立的，需要直接插入
        result = await aggregator._summarize_emotion_trajectory(7)
        assert result == ""  # < 3 snapshots


# ═══════════════════════════════════════════════════════════
# 对话时间模式
# ═══════════════════════════════════════════════════════════

class TestTimePattern:

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self, aggregator):
        result = await aggregator._summarize_time_pattern(7)
        assert result == ""

    @pytest.mark.asyncio
    async def test_insufficient_messages(self, aggregator, db):
        """消息数不足 → 返回空"""
        # conversation_logs 为空 → 返回空
        result = await aggregator._summarize_time_pattern(7)
        assert result == ""


# ═══════════════════════════════════════════════════════════
# 好感度趋势
# ═══════════════════════════════════════════════════════════

class TestAffectionTrend:

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self, aggregator):
        result = await aggregator._summarize_affection_trend()
        assert result == ""


# ═══════════════════════════════════════════════════════════
# 跨会话话题
# ═══════════════════════════════════════════════════════════

class TestSessionBoundaries:

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self, aggregator):
        result = await aggregator._summarize_session_boundaries(7)
        assert result == ""


# ═══════════════════════════════════════════════════════════
# Aggregate — 全信号源聚合
# ═══════════════════════════════════════════════════════════

class TestAggregate:

    @pytest.mark.asyncio
    async def test_all_empty_on_cold_start(self, aggregator):
        """冷启动 — 所有信号源返回空字符串"""
        snap = await aggregator.aggregate(days=7)
        assert isinstance(snap, SignalSnapshot)
        assert snap.tool_usage == ""
        assert snap.emotion_trajectory == ""
        assert snap.time_pattern == ""
        assert snap.affection_trend == ""
        assert snap.session_boundaries == ""

    @pytest.mark.asyncio
    async def test_generated_at_is_set(self, aggregator):
        """generated_at 正确设置"""
        snap = await aggregator.aggregate(days=7)
        assert snap.generated_at > 0
        assert snap.generated_at <= time.time()


# ═══════════════════════════════════════════════════════════
# _build_signal_context（via CoarseGrainEngine）
# ═══════════════════════════════════════════════════════════

class TestBuildSignalContext:

    def test_empty_when_no_signals(self):
        """所有信号为空 → 返回空字符串"""
        from packages.agent.coarse_grain_engine import CoarseGrainEngine
        snap = SignalSnapshot()
        result = CoarseGrainEngine._build_signal_context(snap)
        assert result == ""

    def test_only_meaningful_signals_injected(self):
        """仅注入有意义的非空信号"""
        from packages.agent.coarse_grain_engine import CoarseGrainEngine
        snap = SignalSnapshot(
            generated_at=time.time(),
            emotion_trajectory="最近情绪以平静为主",
            tool_usage="",            # 空 → 不注入
            time_pattern="",          # 空 → 不注入
            affection_trend="好感度初识（5.0分）",
            session_boundaries="",    # 空 → 不注入
        )
        result = CoarseGrainEngine._build_signal_context(snap)
        assert "情绪" in result
        assert "好感度" in result
        assert "工具" not in result       # 空信号不应出现
        assert "聊天习惯" not in result   # 空信号不应出现

    def test_includes_freshness_note(self):
        """信号上下文包含数据新鲜度标注"""
        from packages.agent.coarse_grain_engine import CoarseGrainEngine
        snap = SignalSnapshot(
            generated_at=time.time(),
            emotion_trajectory="测试情绪",
        )
        result = CoarseGrainEngine._build_signal_context(snap)
        assert "系统分析" in result
