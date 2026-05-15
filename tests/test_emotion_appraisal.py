"""测试 AppraisalExtractor + PADMapper + EmotionEngine

2026-05-15：阶段 4 第二周测试——评价提取 + PAD 映射 + 全流程
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from packages.agent.emotion_core import (
    AppraisalExtractor,
    AppraisalResult,
    PADMapper,
    PersonalityModulator,
    EmotionEngine,
    EmotionState,
    APPRAISAL_SYSTEM_PROMPT,
)


# ═══════════════════════════════════════════════════════════
# AppraisalExtractor — 启发式降级
# ═══════════════════════════════════════════════════════════

class TestAppraisalHeuristic:
    """启发式评价（不依赖 LLM）"""

    def setup_method(self):
        self.extractor = AppraisalExtractor(model_router=None)

    @pytest.mark.asyncio
    async def test_empty_message_neutral(self):
        result = await self.extractor.extract("")
        assert result.source == "heuristic"
        assert result.relevance == 0.5
        assert result.facilitation == 0.0

    @pytest.mark.asyncio
    async def test_positive_message(self):
        result = await self.extractor.extract("今天太开心了！考试及格了！")
        assert result.facilitation > 0.1  # 积极
        assert result.source == "heuristic"

    @pytest.mark.asyncio
    async def test_negative_message(self):
        result = await self.extractor.extract("唉，今天又被老板骂了一顿，好烦")
        assert result.facilitation < -0.1  # 消极
        assert result.source == "heuristic"

    @pytest.mark.asyncio
    async def test_coping_positive(self):
        result = await self.extractor.extract("虽然很难，但我能搞定的")
        assert result.coping > 0  # 有掌控感

    @pytest.mark.asyncio
    async def test_coping_negative(self):
        result = await self.extractor.extract("太难了，我不知道该怎么办")
        assert result.coping < 0  # 无力

    @pytest.mark.asyncio
    async def test_long_message_higher_relevance(self):
        short = await self.extractor.extract("嗯")
        long_msg = "今天发生了一件让我特别感动的事情，我想了很久还是觉得应该跟你说说。"
        long = await self.extractor.extract(long_msg)
        assert long.relevance >= short.relevance

    @pytest.mark.asyncio
    async def test_neutral_message(self):
        result = await self.extractor.extract("今天天气还行")
        assert abs(result.facilitation) < 0.5  # 不太极化


# ═══════════════════════════════════════════════════════════
# AppraisalExtractor — LLM 路径（mock）
# ═══════════════════════════════════════════════════════════

class TestAppraisalLLM:
    """LLM 评价提取（mock）"""

    @pytest.mark.asyncio
    async def test_valid_json_parsed(self):
        router = MagicMock()
        router.route = AsyncMock(return_value='{"relevance":0.8,"facilitation":0.6,"coping":0.4,"reason":"伙伴分享了开心的消息"}')

        extractor = AppraisalExtractor(model_router=router)
        result = await extractor.extract("我成功了！")
        assert result.relevance == 0.8
        assert result.facilitation == 0.6
        assert result.coping == 0.4
        assert result.source == "llm"

    @pytest.mark.asyncio
    async def test_markdown_json_parsed(self):
        router = MagicMock()
        router.route = AsyncMock(return_value='```json\n{"relevance":0.5,"facilitation":-0.3,"coping":0.1,"reason":"伙伴有点担心"}\n```')

        extractor = AppraisalExtractor(model_router=router)
        result = await extractor.extract("万一失败了呢")
        assert result.facilitation == -0.3
        assert result.source == "llm"

    @pytest.mark.asyncio
    async def test_malformed_fallback_to_heuristic(self):
        router = MagicMock()
        router.route = AsyncMock(return_value="不好意思我没听懂你在说什么...")

        extractor = AppraisalExtractor(model_router=router)
        result = await extractor.extract("测试消息")
        assert result.source == "heuristic"

    @pytest.mark.asyncio
    async def test_out_of_range_clamped(self):
        router = MagicMock()
        router.route = AsyncMock(return_value='{"relevance":2.5,"facilitation":-3.0,"coping":5.0}')

        extractor = AppraisalExtractor(model_router=router)
        result = await extractor.extract("极限测试")
        assert 0 <= result.relevance <= 1
        assert -1 <= result.facilitation <= 1
        assert -1 <= result.coping <= 1

    @pytest.mark.asyncio
    async def test_llm_error_fallback(self):
        router = MagicMock()
        router.route = AsyncMock(side_effect=Exception("API down"))

        extractor = AppraisalExtractor(model_router=router)
        result = await extractor.extract("不管怎样都要测试")
        assert result.source == "heuristic"


# ═══════════════════════════════════════════════════════════
# PADMapper
# ═══════════════════════════════════════════════════════════

class TestPADMapper:
    """评价 → PAD 映射"""

    def test_positive_event(self):
        """好消息 → 正 P"""
        appraisal = AppraisalResult(relevance=0.8, facilitation=0.7, coping=0.5)
        p, a, d = PADMapper.map_to_pad(appraisal)
        assert p > 0.3  # 偏正
        assert a > 0.2  # 有唤醒

    def test_negative_event(self):
        """坏消息 → 负 P"""
        appraisal = AppraisalResult(relevance=0.9, facilitation=-0.8, coping=-0.4)
        p, a, d = PADMapper.map_to_pad(appraisal)
        assert p < -0.3  # 偏负
        assert a > 0.3  # 高唤醒（重要坏消息）

    def test_calm_event(self):
        """低唤醒事件"""
        appraisal = AppraisalResult(relevance=0.2, facilitation=0.1, coping=0.2)
        p, a, d = PADMapper.map_to_pad(appraisal)
        assert abs(a) < 0.3  # 低唤醒

    def test_high_coping_high_dominance(self):
        """高应对 → 高支配"""
        appraisal = AppraisalResult(relevance=0.5, facilitation=0.3, coping=0.9)
        p, a, d = PADMapper.map_to_pad(appraisal)
        assert d > 0.5

    def test_low_coping_low_dominance(self):
        """低应对 → 低支配"""
        appraisal = AppraisalResult(relevance=0.5, facilitation=-0.2, coping=-0.8)
        p, a, d = PADMapper.map_to_pad(appraisal)
        assert d < -0.4

    def test_modulation_chain(self):
        """评价 → PAD → 人格调制 → 最终偏移"""
        appraisal = AppraisalResult(relevance=0.7, facilitation=0.6, coping=0.3)
        modulator = PersonalityModulator()
        p, a, d = PADMapper.map_to_pad_with_modulation(appraisal, modulator)
        # 调制后应在合理范围内
        assert -1 <= p <= 1
        assert -1 <= a <= 1
        assert -1 <= d <= 1

    def test_neutral_appraisal(self):
        """中性评价 → 中性 PAD"""
        appraisal = AppraisalResult.neutral()
        p, a, d = PADMapper.map_to_pad(appraisal)
        assert abs(p) < 0.05
        assert abs(a) < 0.05
        assert abs(d) < 0.05


# ═══════════════════════════════════════════════════════════
# EmotionEngine 全流程
# ═══════════════════════════════════════════════════════════

class TestEmotionEngine:
    """情感引擎全流程集成"""

    @pytest.mark.asyncio
    async def test_process_message(self):
        router = MagicMock()
        router.route = AsyncMock(return_value='{"relevance":0.7,"facilitation":0.5,"coping":0.4,"reason":"开心"}')

        engine = EmotionEngine(model_router=router, tau=DEFAULT_TAU_FOR_TEST, sensitivity=1.0)
        profile = await engine.process_message("今天真开心！")

        assert "primary_emotion" in profile
        assert "dimensions" in profile
        assert "appraisal" in profile
        assert profile["appraisal"]["source"] == "llm"
        assert len(profile["dimensions"]) == 11


# 短 τ 常量（测试中加速衰减验证）
DEFAULT_TAU_FOR_TEST = 3600  # 1h half-life for testing
