"""测试 AgentCore 记忆管道集成（mock 外部服务）"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from packages.shared.events import InternalEvent
from packages.agent.agent_core import AgentCore


@pytest.fixture
def agent():
    with patch("packages.agent.agent_core.ModelRouter") as MockRouter, \
         patch("packages.agent.agent_core.MemoryManager") as MockMM:
        mock_router = MockRouter.return_value
        mock_router.route = AsyncMock(return_value="昔涟的回复~♪")

        mock_mm = MockMM.return_value
        mock_mm.encoding_state = "idle"
        mock_mm.has_pending_encoding = False
        mock_mm.startup = AsyncMock()
        mock_mm.shutdown = AsyncMock(return_value="done")
        mock_mm.retrieve_memories = AsyncMock(return_value=[])
        mock_mm.schedule_encoding = AsyncMock()
        mock_mm.signal_new_message = MagicMock()

        agent = AgentCore(db_path=":memory:")
        agent.router = mock_router
        agent.memory_manager = mock_mm
        agent._db.init = AsyncMock()
        agent._db.insert_log = AsyncMock()
        agent._db.close = AsyncMock()
        yield agent


@pytest.mark.asyncio
async def test_startup_calls_db_and_memory(agent):
    await agent.startup()
    agent._db.init.assert_awaited_once()
    agent.memory_manager.startup.assert_awaited_once()


@pytest.mark.asyncio
async def test_shutdown_returns_result(agent):
    agent.memory_manager.shutdown.return_value = "empty"
    result = await agent.shutdown()
    assert result == "empty"
    agent.memory_manager.shutdown.assert_awaited_once()
    agent._db.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_basic_flow(agent):
    event = InternalEvent(source="test", user_id="hezi", payload="你好啊昔涟，今天天气真好", is_owner=True)
    reply = await agent.process(event)
    assert reply == "昔涟的回复~♪"
    agent.memory_manager.signal_new_message.assert_called_once()
    agent.memory_manager.retrieve_memories.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_non_owner_blocked(agent):
    event = InternalEvent(source="test", user_id="stranger", payload="你好", is_owner=False)
    reply = await agent.process(event)
    assert reply == ""


@pytest.mark.asyncio
async def test_process_short_message_no_retrieval(agent):
    event = InternalEvent(source="test", user_id="hezi", payload="嗯", is_owner=True)
    await agent.process(event)
    agent.memory_manager.retrieve_memories.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_writes_log(agent):
    event = InternalEvent(source="test", user_id="hezi", payload="今天心情不错", is_owner=True)
    await agent.process(event)
    agent._db.insert_log.assert_awaited_once()


@pytest.mark.asyncio
async def test_process_schedules_encoding(agent):
    msg = {"role": "user", "content": "test msg"}
    reply = {"role": "assistant", "content": "test reply"}
    agent.context.history = [msg, reply, msg, reply, msg, reply]
    event = InternalEvent(source="test", user_id="hezi", payload="继续聊", is_owner=True)
    await agent.process(event)
    # schedule_encoding 通过 asyncio.create_task 调度（不是直接 await）
    # 所以用 assert_called_once 而不是 assert_awaited_once
    assert agent.memory_manager.schedule_encoding.call_count >= 1


@pytest.mark.asyncio
async def test_process_model_error_degraded(agent):
    agent.router.route.side_effect = Exception("API down")
    event = InternalEvent(source="test", user_id="hezi", payload="测试错误处理", is_owner=True)
    reply = await agent.process(event)
    assert "人家" in reply


@pytest.mark.asyncio
async def test_reset_session(agent):
    agent.context.add_message("user", "test")
    agent.context.emotion_snapshot = {"test": True}
    agent.context.memory_retrieval = [{"test": True}]
    agent.reset_session()
    assert len(agent.context.history) == 0
    assert agent.context.emotion_snapshot is None
    assert agent.context.memory_retrieval is None


@pytest.mark.asyncio
async def test_build_messages_with_memory(agent):
    """v3: 记忆/共情注入现在位于最后一条 user 消息中，而非 system prompt"""
    agent._personality = "你是昔涟。"
    memory_text = "[当前记忆]\n· 书页翻到一段回忆：昨天..."
    empathy_text = "[共情感知]\n伙伴似乎有些疲惫"
    msgs = agent._build_messages("今天好累", empathy_text, memory_text)

    # system prompt 仅含纯人格
    assert msgs[0]["content"] == "你是昔涟。"

    # 记忆和共情在最后一条 user 消息中
    last_msg = msgs[-1]
    assert last_msg["role"] == "user"
    last_content = last_msg["content"]
    assert "当前记忆" in last_content
    assert "共情感知" in last_content
    assert "今天好累" in last_content
    # 记忆在前，共情在后
    mem_idx = last_content.index("当前记忆")
    emp_idx = last_content.index("共情感知")
    assert mem_idx < emp_idx


@pytest.mark.asyncio
async def test_build_messages_no_injections(agent):
    agent._personality = "你是昔涟。"
    msgs = agent._build_messages("hello", "", "")
    assert msgs[0]["content"] == "你是昔涟。"
    assert msgs[-1]["content"] == "hello"


@pytest.mark.asyncio
async def test_clean_reply(agent):
    assert agent._clean_reply("  你好  ") == "你好"
    assert agent._clean_reply("") == "……♪"


def test_personality_preview(agent):
    preview = agent.personality_preview
    assert len(preview) > 0
