"""
test_model_router — ModelRouter 单元测试

测试多供应商路由核心路径：初始化、路由、tool error 重试、模型信息查询。
所有 adapter 行为均 mock，不依赖外部 API。
"""
import sys
sys.path.insert(0, ".")

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from packages.shared.model_router import ModelRouter, ToolRelatedError
from packages.shared.providers import TierConfig, ProviderResponse, PROVIDER_REGISTRY


class TestModelRouter:
    """ModelRouter 单元测试。"""

    # ── 初始化 ──

    def test_init_no_api_keys(self):
        """无任何 API Key → 空 adapters + warning。"""
        with patch.dict(os.environ, {}, clear=True):
            router = ModelRouter()
            assert len(router._adapters) == 0
            assert len(router._tier_configs) == 0

    def test_init_with_deepseek_key(self):
        """DEEPSEEK_API_KEY 已设置 → adapter 创建 + tier configs 就绪。"""
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=True):
            # Mock _create_adapter 以避免真实 SDK 导入
            with patch.object(ModelRouter, '_create_adapter', return_value=MagicMock()):
                router = ModelRouter()
                assert "deepseek" in router._adapters
                assert "powerful" in router._tier_configs
                assert router._tier_configs["powerful"].provider == "deepseek"

    # ── 工具兼容性缓存 ──

    def test_supports_tools_default_true(self):
        """未缓存 → 默认返回 True（乐观假设支持）。"""
        with patch.dict(os.environ, {}, clear=True):
            router = ModelRouter()
            assert router._supports_tools("unknown:model") is True

    def test_supports_tools_cached_false(self):
        """缓存标记为不支持 → 返回 False。"""
        with patch.dict(os.environ, {}, clear=True):
            router = ModelRouter()
            router._tools_support_cache["deepseek:test"] = False
            assert router._supports_tools("deepseek:test") is False

    # ── 获取当前模型信息 ──

    def test_get_current_model_info_with_tier(self):
        """有 tier 配置 → 返回 tier 的 provider + model。"""
        with patch.dict(os.environ, {}, clear=True):
            router = ModelRouter()
            router._tier_configs["powerful"] = TierConfig(
                tier="powerful", provider="deepseek", model_name="deepseek-v4-pro",
                temperature=0.65, max_tokens=800,
            )
            provider, model = router.get_current_model_info()
            assert provider == "deepseek"
            assert model == "deepseek-v4-pro"

    def test_get_current_model_info_with_override(self):
        """有 task override → 优先返回 override。"""
        with patch.dict(os.environ, {}, clear=True):
            router = ModelRouter()
            from packages.shared.providers import TaskOverride
            router._task_overrides["chat"] = TaskOverride(
                task_type="chat", provider="openai", model_name="gpt-5.4",
            )
            provider, model = router.get_current_model_info()
            assert provider == "openai"
            assert model == "gpt-5.4"

    # ── 路由：正常路径 ──

    @pytest.mark.asyncio
    async def test_route_success(self):
        """正常路由 → adapter.chat() 被调用并返回结果。"""
        with patch.dict(os.environ, {}, clear=True):
            mock_adapter = MagicMock()
            mock_adapter.chat = AsyncMock(return_value=ProviderResponse(
                content="hello", tool_calls=None, reasoning_content="",
            ))
            router = ModelRouter()
            router._adapters["test"] = mock_adapter
            router._tier_configs["powerful"] = TierConfig(
                tier="powerful", provider="test", model_name="test-model",
                temperature=0.7, max_tokens=800,
            )
            result = await router.route("chat", [{"role": "user", "content": "hi"}])
            assert result.content == "hello"
            mock_adapter.chat.assert_called_once()

    # ── 路由：tool error → 重试 ──

    @pytest.mark.asyncio
    async def test_route_tool_error_retry(self):
        """tool error → 缓存标记不支持 → 重试不带 tools。"""
        with patch.dict(os.environ, {}, clear=True):
            mock_adapter = MagicMock()
            # 第一次带 tools 抛出 ToolRelatedError
            mock_adapter.chat = AsyncMock(side_effect=[
                ToolRelatedError("tools not supported"),
                ProviderResponse(content="retry-ok", tool_calls=None, reasoning_content=""),
            ])
            router = ModelRouter()
            router._adapters["test"] = mock_adapter
            router._tier_configs["powerful"] = TierConfig(
                tier="powerful", provider="test", model_name="test-model",
                temperature=0.7, max_tokens=800,
            )
            result = await router.route(
                "chat", [{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "test"}}],
            )
            assert result.content == "retry-ok"
            # 缓存应标记为不支持
            assert router._supports_tools("test:test-model") is False
            # chat 应被调用两次
            assert mock_adapter.chat.call_count == 2
