"""
共情注入测试

测试 AgentCore 的情感分析管道：
  · _inject_empathy() 快照 → 共情段落
  · reset_session() 清理 pending + 快照
  · process() 完整流程（Mock 模型，不调真实 API）
"""
import sys
sys.path.insert(0, ".")

import pytest
from unittest.mock import AsyncMock, Mock

from packages.shared.events import InternalEvent
from packages.agent import AgentCore


@pytest.fixture
def agent():
    """AgentCore 实例 — _inject_empathy / reset_session 测试（不需模型）"""
    return AgentCore()


# ── _inject_empathy() 单元测试（无需模型） ──

class TestInjectEmpathy:
    """测试 _inject_empathy() 的各种场景"""

    def test_no_snapshot_returns_empty(self, agent):
        agent.context.emotion_snapshot = None
        result = agent._inject_empathy()
        assert result == ""

    def test_empty_snapshot_returns_empty(self, agent):
        agent.context.emotion_snapshot = {}
        result = agent._inject_empathy()
        assert result == ""

    def test_snapshot_with_emotion_and_need(self, agent):
        agent.context.emotion_snapshot = {
            "primary_emotion": "疲惫",
            "possible_cause": "连续工作",
            "need": "被看见",
        }
        result = agent._inject_empathy()
        assert "[伙伴的心境]" in result
        assert "涟漪" in result  # 疲惫 → 心境共鸣

    def test_snapshot_without_cause(self, agent):
        agent.context.emotion_snapshot = {
            "primary_emotion": "平静",
            "need": "陪伴",
        }
        result = agent._inject_empathy()
        assert "[伙伴的心境]" in result
        assert "风" in result or "湖面" in result  # 平静的心境描述

    def test_snapshot_without_need(self, agent):
        agent.context.emotion_snapshot = {
            "primary_emotion": "快乐",
            "possible_cause": "好消息",
        }
        result = agent._inject_empathy()
        assert "心里亮亮的" in result  # 快乐的心境描述

    def test_snapshot_without_emotion_field_returns_empty(self, agent):
        agent.context.emotion_snapshot = {"need": "休息"}
        result = agent._inject_empathy()
        assert result == ""

    def test_empathy_text_is_xilian_style(self, agent):
        """共情文案应符合昔涟风格——自然语言心境描述"""
        agent.context.emotion_snapshot = {
            "primary_emotion": "焦虑",
        }
        result = agent._inject_empathy()
        # 不应该出现机器指令
        assert "检测到" not in result
        assert "情绪分析" not in result
        assert "系统提示" not in result
        # 应该是自然语言心境描述
        assert "[伙伴的心境]" in result


# ── reset_session() 测试（无需模型） ──

class TestResetSession:
    """测试 reset_session() 清理情感状态"""

    def test_reset_clears_snapshot(self, agent):
        agent.context.emotion_snapshot = {
            "primary_emotion": "喜悦",
            "need": "分享",
        }
        agent.reset_session()
        assert agent.context.emotion_snapshot is None

    def test_reset_clears_pending_task(self, agent):
        agent.reset_session()
        assert agent._pending_analysis is None


# ── process() 集成测试（Mock 模型，不调真实 API） ──

class TestProcessWithEmotion:
    """Mock router.route() 测试 process() 中的情感管道"""

    @pytest.fixture
    def mock_agent(self):
        agent = AgentCore()
        agent.router.route = AsyncMock(return_value="嗯，人家感觉到了呢~ ♪")
        return agent

    @pytest.mark.asyncio
    async def test_process_without_snapshot(self, mock_agent):
        """首轮（无快照）→ 共情注入为空"""
        # 直接验证 _inject_empathy 在 process 中调用前 snapshot 为 None
        assert mock_agent.context.emotion_snapshot is None
        result = mock_agent._inject_empathy()
        assert result == ""

        event = InternalEvent(
            source="test",
            user_id="hezi",
            payload="你好呀",
            is_owner=True,
        )
        reply = await mock_agent.process(event)
        assert len(reply) > 0
        # 首轮后 snapshot 可能仍在 None（后台任务未完成时）
        assert mock_agent.router.route.call_count >= 1

    @pytest.mark.asyncio
    async def test_process_then_snapshot_set(self, mock_agent):
        """预设 snapshot → process() 中 _inject_empathy 应返回非空"""
        mock_agent.context.emotion_snapshot = {
            "primary_emotion": "疲惫",
            "need": "被看见",
        }
        empathy = mock_agent._inject_empathy()
        assert "疲惫" in empathy

        event = InternalEvent(
            source="test",
            user_id="hezi",
            payload="明天还要早起",
            is_owner=True,
        )
        reply = await mock_agent.process(event)
        assert len(reply) > 0
        # router.route 应被调用（chat 路由）
        mock_agent.router.route.assert_called()
        # 验证调用了 _schedule_emotion_analysis（会创建 task）
        assert mock_agent._pending_analysis is not None

    @pytest.mark.asyncio
    async def test_non_owner_blocked_no_empathy(self, mock_agent):
        """非主人消息 → 不触发情感分析"""
        mock_agent.context.emotion_snapshot = {
            "primary_emotion": "喜悦",
            "need": "分享",
        }
        event = InternalEvent(
            source="test",
            user_id="stranger",
            payload="你好",
            is_owner=False,
        )
        reply = await mock_agent.process(event)
        assert reply == ""
        # router 不应该被调用（block 在步骤 0）
        mock_agent.router.route.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_request_skips_emotion_analysis(self, mock_agent):
        """工具请求 → 早退，不触发情感分析（合理：工具请求不是情绪表达）"""
        mock_agent.router.route = AsyncMock()
        event = InternalEvent(
            source="test",
            user_id="hezi",
            payload="帮我查一下天气",
            is_owner=True,
        )
        reply = await mock_agent.process(event)
        assert "学习" in reply
        # 工具请求早退，不触发后台情感分析
        assert mock_agent._pending_analysis is None


# ── 序列测试：模拟两轮对话 ──

class TestTwoRoundEmpathy:
    """模拟两轮对话：第一轮分析 → 第二轮共情"""

    @pytest.mark.asyncio
    async def test_round1_sets_snapshot_round2_injects(self):
        """模拟第一轮分析完成 → 第二轮 inject 生效"""
        agent = AgentCore()
        # 用 Mock 替代 router 和 emotion_analyzer 的 router
        agent.router.route = AsyncMock(return_value="嗯……人家感觉到了呢")
        agent.emotion_analyzer.router = Mock()
        agent.emotion_analyzer.router.route = AsyncMock(return_value=(
            '{"primary_emotion":"疲惫","primary_intensity":0.8,'
            '"dimensions":{"喜悦":0.0,"悲伤":0.1,"愤怒":0.0,"焦虑":0.3,'
            '"平静":0.4,"期待":0.1,"疲惫":0.8,"孤独":0.2,'
            '"感激":0.0,"好奇":0.1,"恐惧":0.0},'
            '"possible_cause":"连续工作","need":"被看见"}'
        ))

        # 第一轮
        event1 = InternalEvent(
            source="test", user_id="hezi",
            payload="今天好累啊", is_owner=True,
        )
        await agent.process(event1)
        # 快照应为 None（后台任务还未完成）
        # 等待后台任务完成
        import asyncio
        if agent._pending_analysis and not agent._pending_analysis.done():
            await agent._pending_analysis

        # 验证快照已设置
        snap = agent.context.emotion_snapshot
        assert snap is not None
        assert "primary_emotion" in snap  # PAD 引擎产生情绪
        assert "dimensions" in snap
        assert len(snap["dimensions"]) == 11

        # 第二轮
        empathy = agent._inject_empathy()
        # 验证 PAD 驱动的共情包含情绪信息
        assert snap["primary_emotion"] in empathy or len(empathy) > 0

        event2 = InternalEvent(
            source="test", user_id="hezi",
            payload="明天还要早起", is_owner=True,
        )
        await agent.process(event2)
        # 第二轮对话中应已注入共情
        # 验证 router.route 被调用时 messages 中包含共情提示
        call_args = agent.router.route.call_args_list[-1]
        _, kwargs = call_args
        messages = kwargs.get("messages") or call_args[0][1]
        # messages[-1] 是最后一条 user 消息（v3: 动态注入移到底部），应包含共情提示
        last_msg = messages[-1]
        assert last_msg["role"] == "user"
        assert "[伙伴的心境]" in last_msg["content"]  # PAD 驱动的共情
