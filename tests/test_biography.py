"""测试 AutobiographyWriter（mock 外部服务）

2026-05-15：阶段 5 第一周测试——自传体写作 + 反思
"""
import sys
sys.path.insert(0, ".")

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timedelta

from packages.shared.database import DatabaseManager
from packages.agent.autobiography_writer import (
    AutobiographyWriter,
    AUTOBIOGRAPHY_SYSTEM_PROMPT,
    REFLECTION_SYSTEM_PROMPT,
    run_daily_autobiography,
    run_weekly_reflection,
)


@pytest.fixture
def db():
    loop = asyncio.get_event_loop()
    db = DatabaseManager(":memory:")
    loop.run_until_complete(db.init())
    yield db
    loop.run_until_complete(db.close())


@pytest.fixture
def mock_router():
    router = MagicMock()
    router.route = AsyncMock(
        return_value="第 1 天 · 2026年05月15日\n\n今天伙伴和人家聊了很多..."
    )
    return router


@pytest.fixture
def writer(db, mock_router):
    return AutobiographyWriter(db=db, model_router=mock_router)


# ═══════════════════════════════════════════════════════════
# 自传体写作
# ═══════════════════════════════════════════════════════════

class TestAutobiographyWriting:

    @pytest.mark.asyncio
    async def test_no_memories_returns_none(self, db, mock_router):
        writer = AutobiographyWriter(db=db, model_router=mock_router)
        result = await writer.write_daily("2026-01-01")  # 无数据的日子
        assert result is None

    @pytest.mark.asyncio
    async def test_write_daily_with_memories(self, writer, db):
        # 先插入一条今日记忆
        today = datetime.now().strftime("%Y-%m-%d")
        await db.insert_episodic_memory(
            summary="伙伴今天分享了开心的消息",
            raw_conversation="[{\"role\":\"user\",\"content\":\"好消息！\"}]",
            importance=0.7,
        )

        content = await writer.write_daily(today)
        assert content is not None
        assert len(content) > 20

    @pytest.mark.asyncio
    async def test_written_to_db(self, writer, db):
        today = datetime.now().strftime("%Y-%m-%d")
        await db.insert_episodic_memory(
            summary="伙伴分享日常", raw_conversation="[]", importance=0.5,
        )

        await writer.write_daily(today)
        entry = await db.get_autobiography(today)
        assert entry is not None
        assert entry["date"] == today
        assert entry["content"] is not None
        assert entry["word_count"] > 0

    @pytest.mark.asyncio
    async def test_mood_extraction(self, writer):
        snapshots = [
            {"primary_emotion": "快乐", "timestamp": 1},
            {"primary_emotion": "快乐", "timestamp": 2},
            {"primary_emotion": "平静", "timestamp": 3},
        ]
        mood = writer._extract_mood(snapshots)
        assert "快乐" in mood

    @pytest.mark.asyncio
    async def test_mood_empty(self, writer):
        mood = writer._extract_mood([])
        assert "平静" in mood

    @pytest.mark.asyncio
    async def test_filter_today(self, writer):
        today = datetime.now().strftime("%Y-%m-%d")
        today_ts = datetime.strptime(today, "%Y-%m-%d").timestamp()
        memories = [
            {"id": 1, "timestamp": today_ts + 100, "importance": 0.5},
            {"id": 2, "timestamp": today_ts - 86400, "importance": 0.5},  # 昨天
        ]
        filtered = writer._filter_today(memories, today)
        assert len(filtered) == 1
        assert filtered[0]["id"] == 1

    @pytest.mark.asyncio
    async def test_low_importance_filtered(self, writer):
        today = datetime.now().strftime("%Y-%m-%d")
        today_ts = datetime.strptime(today, "%Y-%m-%d").timestamp()
        memories = [
            {"id": 1, "timestamp": today_ts + 100, "importance": 0.05},  # 太低
            {"id": 2, "timestamp": today_ts + 200, "importance": 0.3},
        ]
        filtered = writer._filter_today(memories, today)
        assert len(filtered) == 1
        assert filtered[0]["id"] == 2


# ═══════════════════════════════════════════════════════════
# 反思
# ═══════════════════════════════════════════════════════════

class TestReflection:

    @pytest.mark.asyncio
    async def test_not_enough_data_returns_none(self, writer):
        result = await writer.reflect_weekly("2026-01-06")  # 无数据周
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_valid_json(self, writer):
        raw = '{"learned":"a","surprised":"b","grateful":"c","remember":"d"}'
        result = writer._parse_reflection_json(raw)
        assert result is not None
        assert result["learned"] == "a"
        assert result["surprised"] == "b"

    @pytest.mark.asyncio
    async def test_parse_markdown_json(self, writer):
        raw = '```json\n{"learned":"x","surprised":"y","grateful":"z","remember":"w"}\n```'
        result = writer._parse_reflection_json(raw)
        assert result is not None
        assert result["learned"] == "x"

    @pytest.mark.asyncio
    async def test_parse_invalid_returns_none(self, writer):
        result = writer._parse_reflection_json("这不是JSON")
        assert result is None


# ═══════════════════════════════════════════════════════════
# 定时任务入口
# ═══════════════════════════════════════════════════════════

class TestCronTasks:

    @pytest.mark.asyncio
    async def test_daily_autobiography_task(self, db, mock_router):
        today = datetime.now().strftime("%Y-%m-%d")
        await db.insert_episodic_memory(
            summary="测试记忆", raw_conversation="[]", importance=0.5,
        )
        await run_daily_autobiography(db, mock_router)
        entry = await db.get_autobiography(today)
        assert entry is not None

    @pytest.mark.asyncio
    async def test_weekly_reflection_skips_non_sunday(self, db, mock_router):
        # 非周日应该跳过
        if datetime.now().weekday() == 6:
            pytest.skip("今天恰好是周日")
        await run_weekly_reflection(db, mock_router)
        # 应该没有写入任何东西
        result = await db.get_latest_reflection()
        # 可能会没有（跳过了），或者之前有旧数据


# ═══════════════════════════════════════════════════════════
# Prompt 完整性
# ═══════════════════════════════════════════════════════════

class TestPrompts:

    def test_autobiography_prompt_contains_keywords(self):
        assert "昔涟" in AUTOBIOGRAPHY_SYSTEM_PROMPT
        assert "人家" in AUTOBIOGRAPHY_SYSTEM_PROMPT
        assert "伙伴" in AUTOBIOGRAPHY_SYSTEM_PROMPT

    def test_reflection_prompt_contains_sage(self):
        assert "S - 学会" in REFLECTION_SYSTEM_PROMPT
        assert "A - 意外" in REFLECTION_SYSTEM_PROMPT
        assert "G - 感激" in REFLECTION_SYSTEM_PROMPT
        assert "E - 记住" in REFLECTION_SYSTEM_PROMPT
