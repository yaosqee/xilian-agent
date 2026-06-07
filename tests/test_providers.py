"""
test_providers — Provider Adapter 结构验证

验证所有 adapter 满足 Protocol：必备属性、必备方法。
纯导入检查，不涉及网络调用。
"""
import sys
sys.path.insert(0, ".")

import pytest

from packages.shared.providers.base import ProviderAdapter, ModelInfo
from packages.shared.providers import PROVIDER_REGISTRY


# ── 所有预期的 adapter ──

EXPECTED_PROVIDERS = {"deepseek", "openai", "anthropic", "google", "mimo"}

REQUIRED_ATTRS = [
    "provider_name", "supports_streaming", "supports_tools",
    "supports_thinking", "supports_prefix_cache", "supports_embedding",
]

REQUIRED_METHODS = ["chat", "embed", "get_available_models"]
# describe_image 是可选方法——仅视觉模型（MiMo）需要实现


class TestProviderRegistry:
    """Provider 注册表完整性测试。"""

    def test_registry_contains_all_expected(self):
        """PROVIDER_REGISTRY 包含所有预期供应商。"""
        registered = set(PROVIDER_REGISTRY.keys())
        missing = EXPECTED_PROVIDERS - registered
        assert not missing, f"PROVIDER_REGISTRY 缺少: {missing}"

    def test_all_adapters_importable(self):
        """所有注册的 adapter 可正常导入。"""
        import importlib
        for pid in EXPECTED_PROVIDERS:
            entry = PROVIDER_REGISTRY.get(pid)
            assert entry is not None, f"{pid} 不在 PROVIDER_REGISTRY 中"
            module_path, class_name, _ = entry
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                assert cls is not None, f"{pid} adapter 类加载失败"
            except Exception as e:
                pytest.fail(f"{pid} adapter 导入失败: {e}")


class TestAdapterStructure:
    """Adapter 结构合规性测试。"""

    @pytest.fixture
    def all_adapters(self):
        """加载所有 adapter 类。"""
        import importlib
        adapters = {}
        for pid in EXPECTED_PROVIDERS:
            entry = PROVIDER_REGISTRY.get(pid)
            if entry:
                module_path, class_name, _ = entry
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                adapters[pid] = cls
        return adapters

    def test_all_have_required_attrs(self, all_adapters):
        """每个 adapter 都有所有必备属性。"""
        for pid, cls in all_adapters.items():
            for attr in REQUIRED_ATTRS:
                assert hasattr(cls, attr), f"{pid} 缺少属性 {attr}"

    def test_all_have_required_methods(self, all_adapters):
        """每个 adapter 都有所有必备方法。"""
        for pid, cls in all_adapters.items():
            for method in REQUIRED_METHODS:
                assert hasattr(cls, method), f"{pid} 缺少方法 {method}"

    def test_get_available_models_returns_non_empty(self, all_adapters):
        """每个 adapter 的 get_available_models() 返回非空列表。"""
        for pid, cls in all_adapters.items():
            models = cls.get_available_models()
            assert isinstance(models, list), f"{pid}.get_available_models() 应返回 list"
            assert len(models) > 0, f"{pid}.get_available_models() 返回空列表"
            for m in models:
                assert isinstance(m, ModelInfo), f"{pid} 模型不是 ModelInfo: {m}"

    def test_mimo_has_describe_image(self, all_adapters):
        """MiMoAdapter 实现 describe_image（与 Protocol 一致）。"""
        mimo = all_adapters.get("mimo")
        assert mimo is not None
        assert hasattr(mimo, "describe_image")
        assert callable(getattr(mimo, "describe_image"))
