"""ToolRegistry autodiscover 回归：多个 registry / AgentCore 实例都能拿到工具。"""
import sys

sys.path.insert(0, ".")

from packages.agent.tool_registry import ToolRegistry


def test_autodiscover_replays_for_second_registry():
    first = ToolRegistry()
    first.autodiscover("packages.agent.tools")
    second = ToolRegistry()
    second.autodiscover("packages.agent.tools")

    assert first.tool_names
    assert set(second.tool_names) == set(first.tool_names)
    # 无论环境变量是否配齐，内置工具至少这两个不受外部 Key 影响
    assert "coding_delegate" in second.tool_names
    assert "search_memory" in second.tool_names


def test_autodiscover_is_idempotent_on_same_registry():
    registry = ToolRegistry()
    first_count = registry.autodiscover("packages.agent.tools")
    second_count = registry.autodiscover("packages.agent.tools")

    assert first_count >= 2
    assert second_count == 0
