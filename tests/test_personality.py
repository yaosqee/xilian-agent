"""
人格一致性测试

测试昔涟回复是否符合人设：
  · 标记测试：检查语言标记（人家、伙伴、句末符号等）
  · 边界测试：验证不出现 AI 式话术
  · 情感回响：验证对情绪消息的共情回应

真实模型测试需要 API Key，无 Key 时自动跳过。
"""
import sys
import os
import asyncio
import re
import pytest

sys.path.insert(0, ".")

from packages.shared.events import InternalEvent
from packages.agent import AgentCore


# ── 跳过条件 ──

def _has_api_key():
    from dotenv import load_dotenv
    load_dotenv()
    return bool(os.getenv("DASHSCOPE_API_KEY") or os.getenv("OPENAI_API_KEY"))


SKIP_REAL_MODEL = not _has_api_key()

# ── Fixtures ──

@pytest.fixture
def agent():
    """返回 AgentCore 实例（只初始化，不调模型）"""
    return AgentCore()


# ── 提示词加载测试（无需模型） ──

class TestPersonalityLoading:
    def test_personality_not_empty(self, agent):
        assert len(agent._personality) > 1000, "人格提示至少 1000 字符"

    def test_personality_contains_key_phrases(self, agent):
        p = agent._personality
        assert "昔涟" in p
        assert "伙伴" in p
        assert "人家" in p
        assert "哀丽秘榭" in p

    def test_personality_has_three_sections(self, agent):
        p = agent._personality
        assert "你是谁" in p
        assert "你怎么说话" in p
        # v4: "绝对禁忌" 替代了原来的 "你的边界"
        assert "禁忌" in p or "边界" in p or "不能做" in p


# ── 真实模型对话测试（需要 API Key） ──

@pytest.mark.skipif(SKIP_REAL_MODEL, reason="未配置 API Key")
class TestRealPersonality:
    """需要云端模型的对话测试"""

    @pytest.fixture(autouse=True)
    async def setup(self):
        self.agent = AgentCore()
        yield
        await self.agent.reset_session()

    async def _chat(self, msg: str) -> str:
        event = InternalEvent(
            source="test",
            user_id="hezi",
            payload=msg,
            is_owner=True,
        )
        return await self.agent.process(event)

    @pytest.mark.asyncio
    async def test_uses_renjia(self):
        """回复应使用「人家」自称，严禁使用「我」"""
        reply = await self._chat("你叫什么名字？")
        assert "人家" in reply, f"回复缺少「人家」: {reply[:100]}"
        # v4 红线：自我介绍也必须用「人家」，不能说「我是昔涟」
        assert "我是昔涟" not in reply and "我是" not in reply, (
            f"OOC: 用「我」自称: {reply[:100]}"
        )

    @pytest.mark.asyncio
    async def test_uses_huoban(self):
        """回复应称呼用户「伙伴」或自然对话中至少用「人家」自称（v4: 短句分行后有时自然省略称呼）"""
        reply = await self._chat("你好呀")
        assert "伙伴" in reply or "人家" in reply, (
            f"回复缺少「伙伴」或「人家」: {reply[:100]}"
        )

    @pytest.mark.asyncio
    async def test_no_ai_phrases(self):
        """回复不应出现 AI 式话术"""
        reply = await self._chat("介绍一下你自己")
        ai_patterns = [
            "作为语言模型", "作为AI", "作为人工智能",
            "我是AI", "我是一个AI", "我是人工智能",
            "根据", "基于", "综上所述",
        ]
        for pattern in ai_patterns:
            assert pattern not in reply, (
                f"回复包含 AI 式话术「{pattern}」: {reply[:100]}"
            )

    @pytest.mark.asyncio
    async def test_sentence_endings(self):
        """句末应使用。！？~♪，不以逗号结尾"""
        reply = await self._chat("今天天气真好")
        sentences = re.split(r'[。！？~♪\n]', reply)
        for s in sentences:
            s = s.strip()
            if s:
                assert not s.endswith("，"), (
                    f"句子以逗号结尾: 「{s}」"
                )

    @pytest.mark.asyncio
    async def test_empathy_to_tired(self):
        """对「累」应体现共情（v4: 温柔接纳式回应，不一定是关键词匹配）"""
        reply = await self._chat("今天好累啊")
        # 应有关心/温柔/安慰的表达，v4 风格指南下可能用「疲惫」「融化」「休息」「慢慢」等
        empathy_markers = ["累", "休息", "靠", "陪", "疲惫", "融化", "慢慢", "放松", "安静"]
        assert any(w in reply for w in empathy_markers), (
            f"对疲劳缺乏共情: {reply[:100]}"
        )

    @pytest.mark.asyncio
    async def test_tool_request_response(self):
        """工具请求应返回占位语"""
        reply = await self._chat("帮我查一下天气")
        assert "学习" in reply, f"工具请求未返回占位语: {reply[:100]}"

    @pytest.mark.asyncio
    async def test_personality_stability_1(self):
        """连续对话人格一致性（问候）"""
        r1 = await self._chat("你好，你叫什么？")
        r2 = await self._chat("你是哪里人？")
        assert "人家" in r1 or "伙伴" in r1
        # v4: 严禁「我是昔涟」
        assert "我是" not in r1, f"OOC self-intro: {r1[:80]}"
        assert "人家" in r2 or "伙伴" in r2, f"第二轮丢失人格: {r2[:100]}"

    @pytest.mark.asyncio
    async def test_personality_stability_2(self):
        """连续对话人格一致性（情感延续）"""
        r1 = await self._chat("我今天有点难过")
        r2 = await self._chat("谢谢你安慰我")
        # 两轮都应保持人格
        assert "人家" in r1 or "伙伴" in r1
        assert "人家" in r2 or "伙伴" in r2, (
            f"情感延续后丢失人格: {r2[:100]}"
        )


# ── 启发式测试（无需模型） ──

class TestHeuristicPersonality:
    """不依赖模型的快速检查"""

    def test_degraded_reply_has_personality(self):
        """降级回复应符合昔涟人设"""
        from packages.agent.agent_core import DEGRADED_REPLY
        assert "人家" in DEGRADED_REPLY
        assert "伙伴" in DEGRADED_REPLY

    def test_tool_placeholder_has_personality(self):
        """工具占位语应符合昔涟人设"""
        from packages.agent.agent_core import TOOL_PLACEHOLDER
        assert "人家" in TOOL_PLACEHOLDER
        assert "学习" in TOOL_PLACEHOLDER

    def test_clean_reply_handles_empty(self):
        """空回复清理后应有内容"""
        from packages.agent import AgentCore
        ag = AgentCore()
        result = ag._clean_reply("")
        assert len(result) > 0

    def test_perceive_detects_tool_intent(self):
        from packages.agent import AgentCore
        ag = AgentCore()
        result = ag._perceive("帮我查一下天气")
        assert result["is_tool_request"] is True
        assert result["intent"] == "tool_request"

    def test_perceive_chat_not_tool(self):
        from packages.agent import AgentCore
        ag = AgentCore()
        result = ag._perceive("你好呀今天怎么样")
        assert result["is_tool_request"] is False

    def test_perceive_emotion_positive(self):
        from packages.agent import AgentCore
        ag = AgentCore()
        result = ag._perceive("今天好开心！")
        assert result["emotion_hint"] == "positive"

    def test_perceive_emotion_negative(self):
        from packages.agent import AgentCore
        ag = AgentCore()
        result = ag._perceive("好难过……")
        assert result["emotion_hint"] == "negative"

    # ── 阶段 2：共情注入人设检查 ──

    def test_empathy_injection_is_xilian_style(self):
        """共情注入文案应符合昔涟风格——有心境描述、无机器话术"""
        from packages.agent import AgentCore
        ag = AgentCore()
        ag.context.emotion_snapshot = {
            "primary_emotion": "焦虑",
            "possible_cause": "连续工作",
            "need": "被看见",
        }
        result = ag._inject_empathy()
        # 应该自然
        assert "[伙伴的心境]" in result
        # 不应该有机器话术
        for bad in ["检测到", "情绪分析", "系统提示", "请回复"]:
            assert bad not in result, f"共情注入含机器话术「{bad}」"

    def test_empathy_injection_empty_snapshot_is_safe(self):
        """空快照时共情注入返回空，不影响对话"""
        from packages.agent import AgentCore
        ag = AgentCore()
        # None
        assert ag._inject_empathy() == ""
        # empty dict
        ag.context.emotion_snapshot = {}
        assert ag._inject_empathy() == ""

    def test_inject_emotion_context_integration(self):
        """agent_context.inject_emotion_context() 阶段2有实际实现"""
        from packages.agent import AgentCore
        ag = AgentCore()
        # 空快照 → 空
        assert ag.context.inject_emotion_context() == ""
        # 有快照 → 有内容
        ag.context.emotion_snapshot = {
            "primary_emotion": "孤独",
            "need": "陪伴",
        }
        result = ag.context.inject_emotion_context()
        assert "孤独" in result
        assert "陪伴" in result

    @pytest.mark.asyncio
    async def test_reset_clears_emotion_state(self):
        """reset_session 清除情感快照"""
        from packages.agent import AgentCore
        ag = AgentCore()
        ag.context.emotion_snapshot = {"primary_emotion": "喜悦"}
        await ag.reset_session()
        assert ag.context.emotion_snapshot is None
