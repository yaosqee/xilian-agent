"""
控制台通道测试

测试 ConsoleChannel 的：
  · 内置命令解析（/quit /help /clear）
  · 事件构造
  · 安全过滤集成（熔断、非主人拦截）
"""
import sys
import asyncio
import pytest

sys.path.insert(0, ".")

from packages.shared.events import InternalEvent
from gateway.security import SecurityFilter
from gateway.channels import ConsoleChannel


class TestConsoleBuiltins:
    """内置命令测试"""

    def test_quit_command(self):
        ch = ConsoleChannel()
        ch._running = True
        assert ch._handle_builtin("/quit") is True
        assert ch._running is False

    def test_exit_alias(self):
        ch = ConsoleChannel()
        ch._running = True
        assert ch._handle_builtin("/exit") is True
        assert ch._running is False

    def test_help_command(self):
        ch = ConsoleChannel()
        assert ch._handle_builtin("/help") is True

    def test_clear_command(self):
        ch = ConsoleChannel()
        assert ch._handle_builtin("/clear") is True

    def test_unknown_command_returns_false(self):
        ch = ConsoleChannel()
        assert ch._handle_builtin("/unknown") is False

    def test_normal_message_not_builtin(self):
        ch = ConsoleChannel()
        assert ch._handle_builtin("你好昔涟") is False


class TestConsoleSecurity:
    """安全过滤集成测试"""

    def test_stop_keyword_blocked(self):
        sf = SecurityFilter(owner_id="hezi")
        ch = ConsoleChannel(sf)

        event = InternalEvent(
            source="console",
            user_id="hezi",
            payload="昔涟 停下",
            is_owner=True,
        )
        result = ch.security.filter(event)
        assert result is None, "紧急熔断关键词应被拦截"

    def test_owner_message_passes(self):
        sf = SecurityFilter(owner_id="hezi")
        ch = ConsoleChannel(sf)

        event = InternalEvent(
            source="console",
            user_id="hezi",
            payload="你好",
            is_owner=True,
        )
        result = ch.security.filter(event)
        assert result is not None
        assert result.payload == "你好"


class TestConsoleChannelLifecycle:
    """通道生命周期测试"""

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self):
        ch = ConsoleChannel()
        ch._running = True
        await ch.stop()
        assert ch._running is False
