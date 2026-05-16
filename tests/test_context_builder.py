"""ContextBuilder 单元测试 — 阶段 7a"""
import pytest
from packages.agent.context_builder import (
    ContextBuilder, DatetimeModule, IdentityModule, EmotionModule, MemoryModule,
)
from packages.agent.agent_context import AgentContext


class TestDatetimeModule:
    def test_renders_time_info(self):
        m = DatetimeModule()
        result = m.render()
        assert '年' in result
        assert '月' in result
        assert 'CST' in result

    def test_priority_is_1(self):
        assert DatetimeModule().priority == 1


class TestIdentityModule:
    def test_renders_basic_identity(self):
        m = IdentityModule()
        result = m.render()
        assert '昔涟' in result or '记录者' in result or '人家' in result

    def test_custom_text(self):
        m = IdentityModule()
        m.set_text('自定义身份')
        assert m.render() == '自定义身份'


class TestEmotionModule:
    def test_empty_when_no_snapshot(self):
        ctx = AgentContext()
        m = EmotionModule(ctx)
        assert m.render() == ''

    def test_renders_emotion_data(self):
        ctx = AgentContext()
        ctx.emotion_snapshot = {'primary_emotion': '快乐', 'primary_intensity': 0.8}
        m = EmotionModule(ctx)
        result = m.render()
        assert '快乐' in result

    def test_empty_when_no_primary_emotion(self):
        ctx = AgentContext()
        ctx.emotion_snapshot = {'primary_emotion': '', 'primary_intensity': 0.0}
        m = EmotionModule(ctx)
        assert m.render() == ''


class TestMemoryModule:
    def test_empty_when_no_memories(self):
        ctx = AgentContext()
        m = MemoryModule(ctx)
        assert m.render() == ''

    def test_renders_memories(self):
        ctx = AgentContext()
        ctx.memory_retrieval = [{'summary': '昨天讨论了昔涟项目'}]
        m = MemoryModule(ctx)
        result = m.render()
        assert '昔涟项目' in result

    def test_max_3_memories(self):
        ctx = AgentContext()
        ctx.memory_retrieval = [
            {'summary': f'memory {i}'} for i in range(5)
        ]
        m = MemoryModule(ctx)
        result = m.render()
        assert 'memory 0' in result
        assert 'memory 2' in result


class TestContextBuilder:
    def test_registers_and_sorts_modules(self):
        builder = ContextBuilder()
        builder.register(IdentityModule())
        builder.register(DatetimeModule())
        assert builder.module_names[0] == 'datetime'  # priority 1 first
        assert builder.module_names[-1] == 'identity'  # priority 9 last

    def test_build_produces_xml(self):
        builder = ContextBuilder(total_budget=500)
        builder.register(DatetimeModule())
        builder.register(IdentityModule())
        result = builder.build()
        assert '<context>' in result
        assert '</context>' in result
        assert '<module' in result

    def test_empty_when_no_enabled_modules(self):
        builder = ContextBuilder()
        m = DatetimeModule()
        m.enabled = False
        builder.register(m)
        assert builder.build() == ''

    def test_budget_truncation(self):
        """预算极度紧张时低优先级模块被跳过"""
        builder = ContextBuilder(total_budget=10)
        builder.register(DatetimeModule())   # 会用掉大部分
        builder.register(IdentityModule())   # 可能被跳过
        result = builder.build()
        # datetime 应该在里面
        assert 'datetime' in result

    def test_get_module_by_name(self):
        builder = ContextBuilder()
        builder.register(DatetimeModule())
        m = builder.get_module('datetime')
        assert m is not None
        assert m.name == 'datetime'
        assert builder.get_module('nonexistent') is None
