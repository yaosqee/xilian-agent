"""
test_model_router — ModelRouter 单元测试

测试多供应商路由核心路径：初始化、路由、tool error 重试、模型信息查询。
所有 adapter 行为均 mock，不依赖外部 API。
"""
import sys
sys.path.insert(0, ".")

import os
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from packages.shared.model_config import ModelConfigError
from packages.shared.model_router import ModelRouter, ToolRelatedError
from packages.shared.providers import TierConfig, ProviderResponse, PROVIDER_REGISTRY


DEFAULT_ROUTING_CONFIG = Path(__file__).resolve().parent.parent / "config" / "model_routing.toml"


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
        """tool error → 原样重试一次成功，不永久禁用 tools。"""
        with patch.dict(os.environ, {}, clear=True):
            mock_adapter = MagicMock()
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
            # 第二次成功 → 缓存不应被污染
            assert router._supports_tools("test:test-model") is True
            assert mock_adapter.chat.call_count == 2
            snapshot = router.stats["test:test-model"]
            assert snapshot["tool_errors"] >= 1
            assert snapshot["tool_retries"] == 1

    @pytest.mark.asyncio
    async def test_route_tool_error_degrades_after_two_failures(self):
        """连续两次 tool error → 临时禁用 tools，第三次无 tools 成功。"""
        with patch.dict(os.environ, {}, clear=True):
            mock_adapter = MagicMock()
            mock_adapter.chat = AsyncMock(side_effect=[
                ToolRelatedError("tools not supported"),
                ToolRelatedError("tools not supported"),
                ProviderResponse(content="fallback-ok", tool_calls=None, reasoning_content=""),
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
            assert result.content == "fallback-ok"
            assert router._supports_tools("test:test-model") is False
            assert "test:test-model" in router._tools_disabled_until
            assert mock_adapter.chat.call_count == 3
            third_kwargs = mock_adapter.chat.await_args_list[2].kwargs
            assert third_kwargs["tools"] is None
            assert router.stats["test:test-model"]["degraded"] == 1

    @pytest.mark.asyncio
    async def test_route_tool_choice_error_retries_auto(self):
        """tool_choice 不兼容 → 改用 auto 重试，不临时禁用 tools。"""
        with patch.dict(os.environ, {}, clear=True):
            mock_adapter = MagicMock()
            mock_adapter.chat = AsyncMock(side_effect=[
                Exception("Thinking mode does not support this tool_choice"),
                ProviderResponse(content="auto-ok", tool_calls=None, reasoning_content=""),
            ])
            router = ModelRouter()
            router._adapters["test"] = mock_adapter
            router._tier_configs["powerful"] = TierConfig(
                tier="powerful", provider="test", model_name="test-model",
                temperature=0.7, max_tokens=800,
            )
            forced = {"type": "function", "function": {"name": "test"}}
            result = await router.route(
                "chat", [{"role": "user", "content": "hi"}],
                tools=[{"type": "function", "function": {"name": "test"}}],
                tool_choice=forced,
            )
            assert result.content == "auto-ok"
            second_kwargs = mock_adapter.chat.await_args_list[1].kwargs
            assert second_kwargs["tool_choice"] == "auto"
            assert second_kwargs["tools"] is not None
            assert router._supports_tools("test:test-model") is True

    # ── 能力矩阵 / 观测 ──

    def test_model_policy_from_adapter_info(self):
        from packages.shared.providers.base import ModelInfo

        with patch.dict(os.environ, {}, clear=True):
            mock_adapter = MagicMock()
            mock_adapter.get_available_models.return_value = [
                ModelInfo(
                    id="m1", name="M1", provider="test",
                    supports_tools=False, supports_streaming=False,
                    input_modalities=["text", "image"],
                    context_window=64_000,
                )
            ]
            router = ModelRouter()
            router._adapters["test"] = mock_adapter
            policy = router.get_model_policy("test", "m1")
            assert policy.supports_tools is False
            assert policy.supports_vision is True
            assert policy.context_window == 64_000

    @pytest.mark.asyncio
    async def test_stats_records_calls_and_latency(self):
        with patch.dict(os.environ, {}, clear=True):
            mock_adapter = MagicMock()
            mock_adapter.chat = AsyncMock(return_value=ProviderResponse(
                content="ok", tool_calls=None, reasoning_content="",
            ))
            router = ModelRouter()
            router._adapters["test"] = mock_adapter
            router._tier_configs["powerful"] = TierConfig(
                tier="powerful", provider="test", model_name="test-model",
                temperature=0.7, max_tokens=800,
            )
            await router.route("chat", [{"role": "user", "content": "hi"}])
            snapshot = router.stats["test:test-model"]
            assert snapshot["calls"] == 1
            assert snapshot["successes"] == 1
            assert "p95_latency_ms" in snapshot

    def test_degradation_expires(self):
        import time

        with patch.dict(os.environ, {}, clear=True):
            router = ModelRouter()
            router._tools_support_cache["x:y"] = False
            router._tools_disabled_until["x:y"] = time.time() - 1
            assert router._supports_tools("x:y") is True
            assert "x:y" not in router._tools_support_cache

    def test_tool_decision_task_group(self):
        from packages.shared.providers import TASK_TIER_MAP, task_group

        assert TASK_TIER_MAP["tool_decision"] == "powerful"
        assert task_group("tool_decision") == "tool_decision"
        assert task_group("chat") == "dialogue"
        assert task_group("memory_encoding") == "background"
        # M2: reasoning/code/planning 不再落回 dialogue
        assert task_group("reasoning") == "reasoning"
        assert task_group("code") == "reasoning"


class TestRoutingV2:
    """M2-2：声明式路由接入（默认关闭）。"""

    @staticmethod
    def _router_with_fake_adapter():
        with patch.dict(
            os.environ,
            {
                "MODEL_ROUTING_V2": "1",
                "MODEL_ROUTING_CONFIG": str(DEFAULT_ROUTING_CONFIG),
            },
            clear=True,
        ):
            router = ModelRouter()

        adapter = MagicMock()
        adapter.chat = AsyncMock(
            return_value=ProviderResponse(content="ok", tool_calls=None)
        )
        adapter.get_available_models.return_value = []
        router._adapters["deepseek"] = adapter
        return router, adapter

    def test_flag_defaults_off(self):
        with patch.dict(os.environ, {}, clear=True):
            router = ModelRouter()
            assert router.routing_v2 is False
            assert router.routing_config is None

    def test_missing_config_fails_fast(self, tmp_path):
        with patch.dict(
            os.environ,
            {
                "MODEL_ROUTING_V2": "1",
                "MODEL_ROUTING_CONFIG": str(tmp_path / "missing.toml"),
            },
            clear=True,
        ):
            with pytest.raises(ModelConfigError, match="不存在"):
                ModelRouter()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("task_type", "expected_model"),
        [
            ("chat", "deepseek-flash"),
            ("empathy", "deepseek-flash"),
            ("memory_encoding", "deepseek-flash"),
            ("autobiography", "deepseek-flash"),
            ("reasoning", "deepseek-v4-pro"),
            ("code", "deepseek-v4-pro"),
            ("planning", "deepseek-v4-pro"),
            ("personality_check", "deepseek-flash"),
            ("tool_result_wrap", "deepseek-flash"),
            ("tool_decision", "deepseek-flash"),
        ],
    )
    async def test_golden_routes_match_current_config(self, task_type, expected_model):
        router, adapter = self._router_with_fake_adapter()
        tools = (
            [{"type": "function", "function": {"name": "query_weather"}}]
            if task_type == "tool_decision" else None
        )

        await router.route(task_type, [{"role": "user", "content": "hi"}], tools=tools)

        kwargs = adapter.chat.await_args.kwargs
        assert kwargs["model"] == expected_model
        if task_type == "tool_decision":
            assert kwargs["tools"] == tools

    @pytest.mark.asyncio
    async def test_v2_ignores_legacy_tier_rows(self):
        router, adapter = self._router_with_fake_adapter()
        router._tier_configs["powerful"] = TierConfig(
            tier="powerful", provider="deepseek", model_name="deepseek-v4-pro",
            temperature=0.65, max_tokens=800,
        )

        await router.route("chat", [{"role": "user", "content": "hi"}])

        assert adapter.chat.await_args.kwargs["model"] == "deepseek-flash"

    @pytest.mark.asyncio
    async def test_v2_uses_profile_defaults_when_not_passed(self):
        router, adapter = self._router_with_fake_adapter()

        await router.route("chat", [{"role": "user", "content": "hi"}])
        chat_kwargs = adapter.chat.await_args.kwargs
        assert chat_kwargs["temperature"] == 0.65
        assert chat_kwargs["max_tokens"] == 800

        await router.route("reasoning", [{"role": "user", "content": "hi"}])
        reasoning_kwargs = adapter.chat.await_args.kwargs
        assert reasoning_kwargs["temperature"] == 0.3
        assert reasoning_kwargs["max_tokens"] == 2000

    @pytest.mark.asyncio
    async def test_v2_explicit_params_override_profile(self):
        router, adapter = self._router_with_fake_adapter()

        await router.route(
            "chat",
            [{"role": "user", "content": "hi"}],
            temperature=0.2,
            max_tokens=123,
        )

        kwargs = adapter.chat.await_args.kwargs
        assert kwargs["temperature"] == 0.2
        assert kwargs["max_tokens"] == 123

    def test_v2_current_model_info(self):
        router, _ = self._router_with_fake_adapter()
        assert router.get_current_model_info() == ("deepseek", "deepseek-flash")

    def test_v2_policy_comes_from_config(self):
        router, _ = self._router_with_fake_adapter()
        policy = router.get_model_policy("deepseek", "deepseek-v4-pro")
        assert policy.supports_tools is True
        assert policy.supports_thinking is True

    def test_v2_config_policy_wins_over_legacy_tool_cache(self):
        router, _ = self._router_with_fake_adapter()
        router._tools_support_cache["deepseek:deepseek-flash"] = False
        assert router._supports_tools("deepseek:deepseek-flash") is True

    @pytest.mark.asyncio
    async def test_v2_profile_override_from_ui_row(self):
        router, adapter = self._router_with_fake_adapter()
        router._apply_routing_overrides([{
            "config_key": "profile:dialogue",
            "model_name": "deepseek-v4-pro",
            "fallbacks": '["deepseek-flash"]',
            "temperature": 0.5,
            "max_tokens": 900,
            "source": "ui",
        }])

        await router.route("chat", [{"role": "user", "content": "hi"}])

        kwargs = adapter.chat.await_args.kwargs
        assert kwargs["model"] == "deepseek-v4-pro"
        assert kwargs["temperature"] == 0.5
        assert kwargs["max_tokens"] == 900
        route = router.routing_config.resolve("chat")
        assert route.source == "ui"
        assert route.fallbacks == ("deepseek-flash",)
