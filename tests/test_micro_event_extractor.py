"""测试 MicroEventExtractor 核心逻辑（mock 外部服务）

Phase 1 测试：微事件提取各 category、空对话、confidence 过滤、错误处理。
"""
import os
import sys
sys.path.insert(0, ".")

import asyncio
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from packages.shared.database import DatabaseManager
from packages.agent.micro_event_extractor import (
    MicroEventExtractor,
    EXTRACT_PROMPT,
    MIN_CONFIDENCE,
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
    """Mock ModelRouter — 返回预定义的 JSON 响应"""
    router = MagicMock()
    router.route = AsyncMock()
    return router


@pytest.fixture
def extractor(db, mock_router):
    return MicroEventExtractor(_db=db, _router=mock_router)


# ═══════════════════════════════════════════════════════════
# 单元测试
# ═══════════════════════════════════════════════════════════

class TestMicroEventExtractor:

    @pytest.mark.asyncio
    async def test_extract_preference(self, extractor, mock_router):
        """提取偏好类事件"""
        mock_response = MagicMock()
        mock_response.content = '{"events": [{"content": "盒子不喜欢早起", "category": "preference", "confidence": 0.9}]}'
        mock_router.route.return_value = mock_response

        events = await extractor.extract("我今天六点就被吵醒了，好烦啊", "嗯，早起确实挺辛苦的呢~")

        assert len(events) == 1
        assert events[0]["content"] == "盒子不喜欢早起"
        assert events[0]["category"] == "preference"
        assert events[0]["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_extract_empty(self, extractor, mock_router):
        """日常寒暄 → 空事件列表"""
        mock_response = MagicMock()
        mock_response.content = '{"events": []}'
        mock_router.route.return_value = mock_response

        events = await extractor.extract("今天天气不错", "是呢，阳光很好 ~♪")

        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_extract_fact(self, extractor, mock_router):
        """提取事实类事件"""
        mock_response = MagicMock()
        mock_response.content = '{"events": [{"content": "盒子是程序员", "category": "fact", "confidence": 0.95}]}'
        mock_router.route.return_value = mock_response

        events = await extractor.extract("我写了一天代码", "程序员伙伴辛苦啦~")

        assert len(events) == 1
        assert events[0]["category"] == "fact"

    @pytest.mark.asyncio
    async def test_extract_plan(self, extractor, mock_router):
        """提取计划类事件"""
        mock_response = MagicMock()
        mock_response.content = '{"events": [{"content": "盒子下周三有考试", "category": "plan", "confidence": 0.9}]}'
        mock_router.route.return_value = mock_response

        events = await extractor.extract("下周三要考试了，好紧张", "加油呀伙伴！人家相信你 ~♪")

        assert len(events) == 1
        assert events[0]["category"] == "plan"

    @pytest.mark.asyncio
    async def test_confidence_filter(self, extractor, mock_router):
        """低于 MIN_CONFIDENCE 的事件被过滤"""
        mock_response = MagicMock()
        mock_response.content = (
            '{"events": ['
            '{"content": "高置信事件", "category": "fact", "confidence": 0.9},'
            '{"content": "低置信事件", "category": "habit", "confidence": 0.3}'
            ']}'
        )
        mock_router.route.return_value = mock_response

        events = await extractor.extract("测试消息", "测试回复")

        assert len(events) == 1
        assert events[0]["content"] == "高置信事件"

    @pytest.mark.asyncio
    async def test_llm_error_graceful(self, extractor, mock_router):
        """LLM 调用失败 → 返回空列表，不抛异常"""
        mock_router.route.side_effect = Exception("API timeout")

        events = await extractor.extract("测试消息", "测试回复")
        assert events == []

    @pytest.mark.asyncio
    async def test_json_parse_error(self, extractor, mock_router):
        """JSON 解析失败 → 返回空列表"""
        mock_response = MagicMock()
        mock_response.content = "这不是合法的 JSON 格式"
        mock_router.route.return_value = mock_response

        events = await extractor.extract("测试消息", "测试回复")
        assert events == []

    @pytest.mark.asyncio
    async def test_invalid_category_defaults_to_fact(self, extractor, mock_router):
        """无效 category → 默认归类为 fact"""
        mock_response = MagicMock()
        mock_response.content = '{"events": [{"content": "一些信息", "category": "invalid_cat", "confidence": 0.8}]}'
        mock_router.route.return_value = mock_response

        events = await extractor.extract("测试消息", "测试回复")

        assert len(events) == 1
        assert events[0]["category"] == "fact"

    @pytest.mark.asyncio
    async def test_content_too_long_truncated(self, extractor, mock_router):
        """过长的 content 被截断"""
        long_content = "这是一个非常非常非常非常非常非常非常非常非常非常非常非常非常非常非常长的事件描述"
        mock_response = MagicMock()
        mock_response.content = f'{{"events": [{{"content": "{long_content}", "category": "fact", "confidence": 0.8}}]}}'
        mock_router.route.return_value = mock_response

        events = await extractor.extract("测试消息", "测试回复")

        assert len(events) == 1
        assert len(events[0]["content"]) <= 60

    @pytest.mark.asyncio
    async def test_empty_content_filtered(self, extractor, mock_router):
        """content 为空字符串 → 被过滤"""
        mock_response = MagicMock()
        mock_response.content = '{"events": [{"content": "", "category": "fact", "confidence": 0.8}]}'
        mock_router.route.return_value = mock_response

        events = await extractor.extract("测试消息", "测试回复")
        assert events == []

    @pytest.mark.asyncio
    async def test_writes_to_db(self, extractor, mock_router, db):
        """提取的事件正确写入 micro_events 表"""
        mock_response = MagicMock()
        mock_response.content = '{"events": [{"content": "盒子喜欢雨天", "category": "preference", "confidence": 0.85}]}'
        mock_router.route.return_value = mock_response

        events = await extractor.extract("我最喜欢下雨天了", "雨天确实有种特别的感觉呢~")

        # 验证事件已写入 DB
        active = await db.get_active_micro_events(limit=5)
        assert len(active) >= 1
        contents = [e["content"] for e in active]
        assert "盒子喜欢雨天" in contents

    @pytest.mark.asyncio
    async def test_known_facts_context(self, extractor, mock_router, db):
        """已知事实正确传递给 LLM 作为去重上下文"""
        # 先写入一条已有事件
        await db.insert_micro_event("盒子是程序员", "fact", 0.9)

        mock_response = MagicMock()
        mock_response.content = '{"events": []}'  # 不应重复提取
        mock_router.route.return_value = mock_response

        await extractor.extract("我又写了一天代码", "辛苦啦~")

        # 验证 prompt 中包含已知事实
        call_args = mock_router.route.call_args
        prompt_text = str(call_args[0][1][0]["content"])  # messages[0]["content"]
        assert "盒子是程序员" in prompt_text


# ═══════════════════════════════════════════════════════════
# 集成测试
# ═══════════════════════════════════════════════════════════

class TestMicroEventDBIntegration:

    @pytest.mark.asyncio
    async def test_active_and_consumed_events(self, db):
        """活跃事件和已消费事件的区分"""
        # 写入事件
        id1 = await db.insert_micro_event("事件1", "fact", 0.8)
        id2 = await db.insert_micro_event("事件2", "preference", 0.7)

        # 活跃
        active = await db.get_active_micro_events(limit=10)
        assert len(active) >= 2

        # 消费
        await db.consume_micro_events([id1], "l2:1")
        active_after = await db.get_active_micro_events(limit=10)
        consumed_contents = [e["content"] for e in active_after]
        assert "事件1" not in consumed_contents
        assert "事件2" in consumed_contents

    @pytest.mark.asyncio
    async def test_micro_event_count(self, db):
        """微事件计数"""
        await db.insert_micro_event("事件A", "fact", 0.8)
        await db.insert_micro_event("事件B", "plan", 0.9)

        count = await db.get_micro_event_count(active_only=True)
        assert count >= 2
