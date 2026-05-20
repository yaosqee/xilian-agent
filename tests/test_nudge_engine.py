"""
NudgeEngine & TokenBucket 单元测试

覆盖：TokenBucket consume/refill · 想念值计算 · 内容去重 · 问候生成 · 配置管理
"""
import sys
sys.path.insert(0, ".")

import asyncio
import time
import json
import pytest
from unittest.mock import AsyncMock, Mock, patch

from packages.agent.nudge_engine import (
    TokenBucket,
    AutonomyConfig,
    NudgeEngine,
    ProactiveDecision,
)


# ═══════════════════════════════════════════════════════════
# TokenBucket 测试
# ═══════════════════════════════════════════════════════════

class TestTokenBucket:
    def test_consume_success(self):
        bucket = TokenBucket(capacity=3.0, tokens=3.0)
        assert bucket.consume() is True
        assert bucket.tokens == 2.0

    def test_consume_fail_empty(self):
        bucket = TokenBucket(capacity=3.0, tokens=0.0)
        assert bucket.consume() is False
        assert bucket.tokens == 0.0

    def test_consume_partial_remaining(self):
        bucket = TokenBucket(capacity=3.0, tokens=0.5)
        assert bucket.consume() is False  # 不足 1.0

    def test_refill_partial_cycle(self):
        bucket = TokenBucket(
            capacity=3.0, refill_amount=1.0, refill_interval=1200.0,  # 20min
            tokens=1.0,
            last_refill=time.time() - 600,  # 10min = 半个周期
        )
        added = bucket.refill()
        assert 0 <= added <= 1  # 半个周期补 0.5
        assert 1.0 <= bucket.tokens <= 2.0

    def test_refill_full_cycle(self):
        bucket = TokenBucket(
            capacity=3.0, refill_amount=1.0, refill_interval=10.0,  # 10s for testing
            tokens=0.0,
            last_refill=time.time() - 30,  # 3 full cycles
        )
        added = bucket.refill()
        assert 2 <= added <= 3
        assert bucket.tokens <= bucket.capacity

    def test_refill_clamped_at_capacity(self):
        bucket = TokenBucket(
            capacity=3.0, refill_amount=1.0, refill_interval=1.0,
            tokens=0.0,
            last_refill=time.time() - 100,  # 100 cycles
        )
        bucket.refill()
        assert bucket.tokens <= bucket.capacity

    def test_consume_then_refill_sequence(self):
        bucket = TokenBucket(capacity=3.0, refill_amount=1.0, refill_interval=1.0, tokens=3.0)
        assert bucket.consume()
        assert bucket.consume()
        assert bucket.consume()
        assert bucket.consume() is False  # 空
        # 等 2 秒 → refill
        bucket.last_refill = time.time() - 2
        bucket.refill()
        assert bucket.tokens >= 1.0
        assert bucket.consume() is True


# ═══════════════════════════════════════════════════════════
# AutonomyConfig 测试
# ═══════════════════════════════════════════════════════════

class TestAutonomyConfig:
    def test_default_values(self):
        cfg = AutonomyConfig()
        assert cfg.greeting_enabled is True
        assert cfg.greeting_threshold == 3.0
        assert cfg.do_not_disturb is False

    def test_from_dict(self):
        data = {"greeting_threshold": 7.0, "do_not_disturb": True}
        cfg = AutonomyConfig.from_dict(data)
        assert cfg.greeting_threshold == 7.0
        assert cfg.do_not_disturb is True
        assert cfg.greeting_enabled is True  # default

    def test_to_dict_roundtrip(self):
        cfg = AutonomyConfig(greeting_threshold=8.0)
        d = cfg.to_dict()
        cfg2 = AutonomyConfig.from_dict(d)
        assert cfg2.greeting_threshold == 8.0

    def test_update_partial(self):
        cfg = AutonomyConfig()
        cfg.update({"greeting_threshold": 5.0, "do_not_disturb": True})
        assert cfg.greeting_threshold == 5.0
        assert cfg.do_not_disturb is True
        assert cfg.greeting_enabled is True  # unchanged


# ═══════════════════════════════════════════════════════════
# NudgeEngine 测试（Mock DB + Router）
# ═══════════════════════════════════════════════════════════

class TestNudgeEngine:
    @pytest.fixture
    def mock_db(self):
        """Mock DatabaseManager — 只提供 db_path 给 sync sqlite3 读取"""
        db = Mock()
        db.db_path = ":memory:"  # 不会真的读
        return db

    @pytest.fixture
    def mock_router(self):
        router = Mock()
        router.route = AsyncMock(return_value="伙伴……人家想你了。今天翻到之前你写的那段话，忽然很想跟你说说话。~♪")
        return router

    @pytest.fixture
    def engine(self, mock_db, mock_router):
        bucket = TokenBucket(capacity=3.0, tokens=3.0)
        config = AutonomyConfig(greeting_threshold=6.0)
        return NudgeEngine(db=mock_db, model_router=mock_router, token_bucket=bucket, config=config)

    # ── 状态控制 ──

    def test_pause_resume(self, engine):
        engine.pause()
        assert engine._config.do_not_disturb is True
        engine.resume()
        assert engine._config.do_not_disturb is False

    def test_update_config(self, engine):
        cfg = engine.update_config({"greeting_threshold": 8.5, "do_not_disturb": True})
        assert cfg.greeting_threshold == 8.5
        assert cfg.do_not_disturb is True

    def test_status_dict(self, engine):
        s = engine.status
        assert "missing_value" in s
        assert "threshold" in s
        assert "bucket_tokens" in s
        assert "greeting_enabled" in s

    # ── 想念值计算（参数化不同场景）──

    @pytest.mark.parametrize("hours,expected_min,expected_max", [
        (0.5, 0, 1),    # 刚聊过 → 很低
        (12, 4, 7),     # 半天
        (24, 8, 10),    # 一整天
        (48, 9, 10),    # 两天（clamped）
    ])
    def test_missing_value_by_time(self, engine, hours, expected_min, expected_max):
        # Mock _get_hours_since_last
        with patch.object(engine, '_get_hours_since_last', return_value=hours):
            with patch.object(engine, '_get_urgency_mod', return_value=1.0):
                with patch.object(engine, '_get_significance_mod', return_value=1.0):
                    with patch.object(engine, '_get_time_mod', return_value=1.0):
                        val = engine.calculate_missing_value()
                        assert expected_min <= val <= expected_max, f"hours={hours}, val={val}"

    def test_missing_value_urgency_high(self, engine):
        """负面情绪 → 想念值放大"""
        with patch.object(engine, '_get_hours_since_last', return_value=6.0):
            with patch.object(engine, '_get_urgency_mod', return_value=1.5):
                with patch.object(engine, '_get_significance_mod', return_value=1.0):
                    with patch.object(engine, '_get_time_mod', return_value=1.0):
                        val = engine.calculate_missing_value()
                        # base = (6/24)*10 = 2.5; ×1.5 = 3.75
                        assert val >= 3.5

    # ── 问候生成 ──

    @pytest.mark.asyncio
    async def test_generate_greeting_calls_router(self, engine, mock_router):
        with patch.object(engine, '_get_hours_since_last', return_value=4.0):
            with patch.object(engine, '_build_emotion_context', return_value=""):
                with patch.object(engine, '_build_memory_context', return_value=""):
                    greeting = await engine.generate_greeting()
                    assert len(greeting) > 0
                    mock_router.route.assert_called_once()

    # ── 去重 ──

    def test_dedup_same_content(self, engine):
        text = "伙伴，人家想你了~♪"
        engine._store_greeting(text)
        assert engine._is_duplicate(text) is True

    def test_dedup_different_content(self, engine):
        engine._store_greeting("伙伴，人家想你了~♪")
        assert engine._is_duplicate("今天看到一朵小花，想起了你") is False

    def test_dedup_rotates_old(self, engine):
        for i in range(10):
            engine._store_greeting(f"问候 #{i}")
        # 只保留最近 5 条
        assert len(engine._recent_greetings) == 5

    # ── 问候投递 ──

    def test_pending_greeting_lifecycle(self, engine):
        engine._store_greeting("伙伴~")
        result = engine.get_pending_greeting()
        assert result["has_greeting"] is True
        assert result["greeting"] == "伙伴~"

        gid = result["id"]
        assert engine.ack_greeting(gid) is True
        assert engine.get_pending_greeting()["has_greeting"] is False

    def test_get_consumes_greeting(self, engine):
        """get_pending_greeting 读即消费——一次返回后清空，不可能重复投递"""
        engine._store_greeting("伙伴~")
        result = engine.get_pending_greeting()
        assert result["has_greeting"] is True
        assert result["greeting"] == "伙伴~"
        result2 = engine.get_pending_greeting()
        assert result2["has_greeting"] is False
        assert result2["greeting"] is None

    # ── tick 行为 ──

    @pytest.mark.asyncio
    async def test_tick_paused(self, engine):
        engine.pause()
        decision = await engine.tick()
        assert decision.action == "paused"

    @pytest.mark.asyncio
    async def test_tick_greeting_disabled(self, engine):
        engine._config.greeting_enabled = False
        decision = await engine.tick()
        assert decision.action == "paused"

    @pytest.mark.asyncio
    async def test_tick_silent_below_threshold(self, engine):
        with patch.object(engine, 'calculate_missing_value', return_value=3.0):
            decision = await engine.tick()
            assert decision.action == "silent"
            assert "想念值" in decision.reason

    @pytest.mark.asyncio
    async def test_tick_silent_no_tokens(self, engine, mock_router):
        engine._bucket.tokens = 0.0
        with patch.object(engine, 'calculate_missing_value', return_value=8.0):
            decision = await engine.tick()
            assert decision.action == "silent"
            assert "令牌" in decision.reason

    @pytest.mark.asyncio
    async def test_tick_greet_success(self, engine, mock_router):
        with patch.object(engine, 'calculate_missing_value', return_value=8.0):
            with patch.object(engine, 'generate_greeting', return_value="伙伴，想你了~♪"):
                decision = await engine.tick()
                assert decision.action == "greet"
                assert decision.greeting == "伙伴，想你了~♪"
                assert decision.greeting_id is not None

    @pytest.mark.asyncio
    async def test_tick_dedup_returns_token(self, engine, mock_router):
        # 先生成一次
        with patch.object(engine, 'calculate_missing_value', return_value=8.0):
            engine._store_greeting("伙伴，想你了~♪")
            tokens_before = engine._bucket.tokens

            with patch.object(engine, 'generate_greeting', return_value="伙伴，想你了~♪"):
                decision = await engine.tick()

                assert decision.action == "silent"
                assert engine._bucket.tokens == tokens_before  # 退还令牌
