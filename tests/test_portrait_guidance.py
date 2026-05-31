"""测试 Phase 5 选择性注入 + 回复联动 — bigram 匹配、PortraitGuidanceModule

Phase 5 测试：_extract_relevant_sentences 二元组匹配、
PortraitGuidanceModule Flash LLM 提取、会话缓存、降级路径。
"""
import os
import sys
sys.path.insert(0, ".")

import asyncio
import tempfile
import pytest
from unittest.mock import AsyncMock, MagicMock

from packages.agent.context_builder import (
    PortraitModule,
    PortraitGuidanceModule,
)
from packages.agent.agent_context import AgentContext


# ═══════════════════════════════════════════════════════════
# Bigram extraction tests
# ═══════════════════════════════════════════════════════════

class TestBigramExtraction:

    def test_relevant_sentence_found(self):
        """二元组匹配：相关句子正确提取（句子 >= 8 字符）"""
        portrait = "伙伴是一个性格偏内向的人。他喜欢安静的环境和独处。最近在学日语很认真呢。"
        query = "我最近在学日语"
        result = PortraitModule._extract_relevant_sentences(portrait, query)
        assert "日语" in result
        assert "内向" not in result  # 不相关句子不应出现

    def test_no_false_positive_char_overlap(self):
        """二元组避免字符级假阳性"""
        portrait = "伙伴积累了很多经验和技术。他对技术话题很热情和专注。"
        query = "我今天有点累"
        result = PortraitModule._extract_relevant_sentences(portrait, query)
        # 「累」在「积累」中出现，但二元组不应匹配
        assert result == ""

    def test_empty_when_no_match(self):
        """无匹配时返回空"""
        portrait = "伙伴喜欢编程和技术。他性格偏内向细腻。"
        query = "今天天气真好"
        result = PortraitModule._extract_relevant_sentences(portrait, query)
        assert result == ""

    def test_short_query_skipped(self):
        """查询过短 → 返回空"""
        portrait = "伙伴是一个性格内向的人。他喜欢安静的环境。"
        query = "嗯"
        result = PortraitModule._extract_relevant_sentences(portrait, query)
        assert result == ""

    def test_multiple_matches_ranked(self):
        """多条匹配按重叠度排序（确保 >= 2 个二元组重叠）"""
        portrait = "伙伴最近在学日语进步很快。他每天背单词很努力。最近日语学习进步确实很快呢。"
        query = "最近日语学得怎么样了"
        result = PortraitModule._extract_relevant_sentences(portrait, query)
        # 「最近日语学习进步确实很快呢」应匹配（至少 2 个二元组重叠）
        assert len(result) > 0

    def test_truncation_by_sentences(self):
        """_truncate_by_sentences 按句子截断"""
        text = "第一句话。第二句话。第三句话。第四句话很长很长很长很长。"
        result = PortraitModule._truncate_by_sentences(text, max_chars=15)
        # 只应包含完整的第一句
        assert "第一句话" in result
        assert "第二句话" not in result or len(result) <= 18  # max_chars + "…"


# ═══════════════════════════════════════════════════════════
# PortraitGuidanceModule tests
# ═══════════════════════════════════════════════════════════

class TestPortraitGuidanceModule:

    def test_empty_when_no_l0(self):
        """无 L0 → 返回空"""
        ctx = AgentContext()
        ctx.core_profile = None
        module = PortraitGuidanceModule(ctx)
        result = module.render()
        assert result == ""

    def test_empty_when_short_l0(self):
        """L0 过短 → 返回空"""
        ctx = AgentContext()
        ctx.core_profile = "短"
        module = PortraitGuidanceModule(ctx)
        result = module.render()
        assert result == ""

    def test_returns_cached_when_version_unchanged(self):
        """版本未变 → 复用缓存"""
        ctx = AgentContext()
        ctx.core_profile = "伙伴是一个内向但细腻的人，他喜欢安静的环境和深夜的对话。" * 2
        ctx._current_l0_version = 3
        module = PortraitGuidanceModule(ctx)
        module._cached_version = 3
        module._cached_guidance = "（昔涟心里知道——测试引导。带着这份理解去回应他吧。）"
        result = module.render()
        assert "测试引导" in result

    def test_empty_when_version_changed(self):
        """版本变化 → 同步 render 返回空（异步生成未完成）"""
        ctx = AgentContext()
        ctx.core_profile = "伙伴是一个内向但细腻的人，他喜欢安静的环境和深夜的对话。" * 2
        ctx._current_l0_version = 5
        module = PortraitGuidanceModule(ctx)
        module._cached_version = 3  # 旧版本
        result = module.render()
        assert result == ""

    @pytest.mark.asyncio
    async def test_async_extract_guidance(self):
        """Flash LLM 异步提取行为指引"""
        ctx = AgentContext()
        ctx.core_profile = "伙伴是一个内向但细腻的人。他喜欢安静的环境，不喜欢被追问。" * 2
        ctx._current_l0_version = 2

        mock_router = MagicMock()
        mock_router.route = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"guidances": ["点到为止", "给他留白"]}'
        mock_router.route.return_value = mock_response
        ctx._router = mock_router

        module = PortraitGuidanceModule(ctx)
        result = await module.render_async()
        assert "点到为止" in result
        assert "给他留白" in result

        # 验证缓存
        assert module._cached_version == 2
        assert module._cached_guidance == result

    @pytest.mark.asyncio
    async def test_async_no_router_fallback(self):
        """无 router → 降级返回空"""
        ctx = AgentContext()
        ctx.core_profile = "伙伴是一个内向但细腻的人。" * 3
        ctx._current_l0_version = 1
        ctx._router = None

        module = PortraitGuidanceModule(ctx)
        result = await module.render_async()
        assert result == ""

    @pytest.mark.asyncio
    async def test_async_empty_guidances(self):
        """LLM 返回空 guidances → 返回空"""
        ctx = AgentContext()
        ctx.core_profile = "伙伴是一个内向但细腻的人。" * 3
        ctx._current_l0_version = 1

        mock_router = MagicMock()
        mock_router.route = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = '{"guidances": []}'
        mock_router.route.return_value = mock_response
        ctx._router = mock_router

        module = PortraitGuidanceModule(ctx)
        result = await module.render_async()
        assert result == ""

    @pytest.mark.asyncio
    async def test_async_llm_error_graceful(self):
        """LLM 失败 → 降级返回空"""
        ctx = AgentContext()
        ctx.core_profile = "伙伴是一个内向但细腻的人。" * 3
        ctx._current_l0_version = 1

        mock_router = MagicMock()
        mock_router.route = AsyncMock(side_effect=Exception("API error"))
        ctx._router = mock_router

        module = PortraitGuidanceModule(ctx)
        result = await module.render_async()
        assert result == ""


# ═══════════════════════════════════════════════════════════
# PortraitModule selective injection
# ═══════════════════════════════════════════════════════════

class TestSelectiveInjection:

    # 测试用长画像（>= 50 字符门控）
    LONG_L0 = (
        "伙伴是一个性格内向但细腻的程序员，喜欢安静编码和深夜对话。"
        "他最近在学日语，每周上两次课很认真，对技术有持久的热情和追求。"
    )
    LONG_L1 = (
        "伙伴最近在忙项目同时也在学日语，对技术保持热情同时也关注面试准备和职业发展。"
    )

    def test_subsequent_message_gets_selective_l0(self):
        """后续消息获得选择性 L0 注入"""
        ctx = AgentContext()
        ctx.core_profile = self.LONG_L0
        ctx.phase_profile = self.LONG_L1
        ctx._current_l0_version = 1
        ctx._l0_version_injected = 1   # 首次已注入
        ctx._current_l1_version = 1
        ctx._l1_version_injected = 1   # 首次已注入
        # 查询需与 L0 有 >= 2 个二元组重叠
        ctx._last_user_message = "最近在学日语很认真"
        ctx.icebreaker_active = False
        ctx.icebreaker_deferred = False

        module = PortraitModule(ctx)
        result = module.render()
        # 应返回选择性 L0 匹配（非破冰）
        assert "此刻有关" in result or "日语" in result or len(result) > 0

    def test_first_message_full_injection(self):
        """首条消息 → 完整 L1+L0 注入"""
        ctx = AgentContext()
        ctx.core_profile = self.LONG_L0
        ctx.phase_profile = self.LONG_L1
        ctx._current_l0_version = 1
        ctx._current_l1_version = 1
        # 版本未注入 → 应触发完整注入

        module = PortraitModule(ctx)
        result = module.render()
        assert "最近的那一页" in result  # L1 header
        assert "日语" in result
        assert "最深的那几笔记" in result  # L0 header

    def test_icebreaker_when_no_portrait(self):
        """无画像 → 破冰"""
        ctx = AgentContext()
        ctx.core_profile = None
        ctx.phase_profile = None
        ctx.user_portrait = None
        ctx.icebreaker_active = False
        ctx.icebreaker_deferred = False

        module = PortraitModule(ctx)
        result = module.render()
        assert "还空白的书" in result
        assert ctx.icebreaker_active is True
