"""
EmotionAnalyzer 单元测试

测试 JSON 解析、校验、降级、超时处理 —— 全部 Mock 模型调用。
不依赖真实 DeepSeek API。
"""
import sys
sys.path.insert(0, ".")

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, Mock

from packages.agent.emotion_analyzer import EmotionAnalyzer, EMOTION_DIMENSIONS


# ── Mock 数据 ──

HAPPY_JSON = json.dumps({
    "primary_emotion": "喜悦",
    "primary_intensity": 0.8,
    "dimensions": {
        "喜悦": 0.8, "悲伤": 0.0, "愤怒": 0.0, "焦虑": 0.0,
        "平静": 0.5, "期待": 0.2, "疲惫": 0.0, "孤独": 0.0,
        "感激": 0.3, "好奇": 0.1, "恐惧": 0.0,
    },
    "possible_cause": "好消息",
    "need": "分享",
})

SAD_JSON = json.dumps({
    "primary_emotion": "悲伤",
    "primary_intensity": 0.75,
    "dimensions": {
        "喜悦": 0.0, "悲伤": 0.75, "愤怒": 0.1, "焦虑": 0.2,
        "平静": 0.1, "期待": 0.0, "疲惫": 0.3, "孤独": 0.5,
        "感激": 0.0, "好奇": 0.0, "恐惧": 0.1,
    },
    "possible_cause": "回忆往事",
    "need": "被理解",
})

MIXED_JSON = json.dumps({
    "primary_emotion": "疲惫",
    "primary_intensity": 0.7,
    "dimensions": {
        "喜悦": 0.3, "悲伤": 0.1, "愤怒": 0.0, "焦虑": 0.2,
        "平静": 0.4, "期待": 0.1, "疲惫": 0.7, "孤独": 0.1,
        "感激": 0.2, "好奇": 0.0, "恐惧": 0.0,
    },
    "possible_cause": "连续工作后完成",
    "need": "被看见",
})

MALFORMED_TEXT = "抱歉，我无法分析这段文字。"


# ── Fixtures ──

@pytest.fixture
def mock_router():
    r = Mock()
    r.route = AsyncMock()
    return r


@pytest.fixture
def analyzer(mock_router):
    return EmotionAnalyzer(mock_router)


# ── 解析 + 校验测试（无需 Mock） ──

class TestParseAndValidate:
    """纯函数测试：JSON 解析、校验、降级"""

    def test_parse_plain_json(self, analyzer):
        result = analyzer._parse_response(HAPPY_JSON)
        assert result is not None
        assert result["primary_emotion"] == "喜悦"
        assert result["primary_intensity"] == 0.8

    def test_parse_markdown_code_block(self, analyzer):
        raw = f"```json\n{HAPPY_JSON}\n```"
        result = analyzer._parse_response(raw)
        assert result is not None
        assert result["primary_emotion"] == "喜悦"

    def test_parse_non_json_text(self, analyzer):
        result = analyzer._parse_response(MALFORMED_TEXT)
        assert result is None

    def test_parse_missing_dimensions(self, analyzer):
        bad = '{"primary_emotion":"喜悦","primary_intensity":0.8,"dimensions":{"喜悦":0.8}}'
        result = analyzer._parse_response(bad)
        assert result is None

    def test_parse_out_of_range(self, analyzer):
        bad = json.dumps({
            "primary_emotion": "喜悦",
            "primary_intensity": 0.8,
            "dimensions": {
                "喜悦": 99.0, "悲伤": 0.0, "愤怒": 0.0, "焦虑": 0.0,
                "平静": 0.0, "期待": 0.0, "疲惫": 0.0, "孤独": 0.0,
                "感激": 0.0, "好奇": 0.0, "恐惧": 0.0,
            },
            "possible_cause": "x",
            "need": "y",
        })
        result = analyzer._parse_response(bad)
        assert result is None

    def test_parse_bad_primary_emotion(self, analyzer):
        bad = json.dumps({
            "primary_emotion": "不存在",
            "primary_intensity": 0.8,
            "dimensions": {
                "喜悦": 0.8, "悲伤": 0.0, "愤怒": 0.0, "焦虑": 0.0,
                "平静": 0.0, "期待": 0.0, "疲惫": 0.0, "孤独": 0.0,
                "感激": 0.0, "好奇": 0.0, "恐惧": 0.0,
            },
            "possible_cause": "x",
            "need": "y",
        })
        result = analyzer._parse_response(bad)
        assert result is None

    def test_validate_all_11_dimensions_present(self):
        """校验通过：11 维全在 + 值 ∈ [0,1]"""
        data = json.loads(HAPPY_JSON)
        assert len(data["dimensions"]) == len(EMOTION_DIMENSIONS)
        for name in EMOTION_DIMENSIONS:
            assert name in data["dimensions"]
            assert 0.0 <= data["dimensions"][name] <= 1.0


# ── 完整 analyze() 测试（Mock router） ──

class TestAnalyzeWithMock:
    """Mock router.route() 测试 analyze() 完整流程"""

    @pytest.mark.asyncio
    async def test_analyze_happy(self, mock_router, analyzer):
        mock_router.route.return_value = HAPPY_JSON
        result = await analyzer.analyze("今天太开心了！阳光真好~")
        assert result is not None
        assert result["primary_emotion"] == "喜悦"
        assert result["dimensions"]["喜悦"] > 0.3

    @pytest.mark.asyncio
    async def test_analyze_sad(self, mock_router, analyzer):
        mock_router.route.return_value = SAD_JSON
        result = await analyzer.analyze("我今天好难过……没人理解我")
        assert result is not None
        assert result["dimensions"]["悲伤"] > 0.3
        assert result["primary_emotion"] == "悲伤"

    @pytest.mark.asyncio
    async def test_analyze_mixed(self, mock_router, analyzer):
        mock_router.route.return_value = MIXED_JSON
        result = await analyzer.analyze("虽然很累但终于做完了，开心")
        assert result is not None
        assert result["dimensions"]["疲惫"] > 0
        assert result["dimensions"]["喜悦"] > 0
        assert result["primary_emotion"] == "疲惫"

    @pytest.mark.asyncio
    async def test_analyze_malformed_json_fallback(self, mock_router, analyzer):
        # 两次都返回非 JSON → 应返回 None，不抛异常
        mock_router.route.return_value = MALFORMED_TEXT
        result = await analyzer.analyze("测试消息")
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_timeout(self, mock_router, analyzer):
        mock_router.route.side_effect = asyncio.TimeoutError()
        result = await analyzer.analyze("测试消息")
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_api_error(self, mock_router, analyzer):
        mock_router.route.side_effect = Exception("Connection refused")
        result = await analyzer.analyze("测试消息")
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_empty_message(self, analyzer):
        result = await analyzer.analyze("")
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_whitespace_only(self, analyzer):
        result = await analyzer.analyze("   ")
        assert result is None

    @pytest.mark.asyncio
    async def test_analyze_retry_on_first_failure(self, mock_router, analyzer):
        """第一次返回非 JSON，第二次返回正确 JSON → 应成功"""
        mock_router.route.side_effect = [MALFORMED_TEXT, HAPPY_JSON]
        result = await analyzer.analyze("测试消息")
        assert result is not None
        assert result["primary_emotion"] == "喜悦"
        assert mock_router.route.call_count == 2

    @pytest.mark.asyncio
    async def test_dimensions_all_11_keys(self, mock_router, analyzer):
        """验证 analyze() 返回结果包含完整的 11 维"""
        mock_router.route.return_value = HAPPY_JSON
        result = await analyzer.analyze("测试")
        assert result is not None
        assert len(result["dimensions"]) == 11
        for name in EMOTION_DIMENSIONS:
            assert name in result["dimensions"]
            assert isinstance(result["dimensions"][name], (int, float))
            assert 0.0 <= result["dimensions"][name] <= 1.0
