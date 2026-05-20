"""ContextBuilder 单元测试 — v3.1 (自然语言段落)"""
import pytest
from packages.agent.context_builder import (
    ContextBuilder, DatetimeModule, EmotionModule, MemoryModule, NotebookModule,
)
from packages.agent.agent_context import AgentContext


class TestDatetimeModule:
    def test_renders_time_info(self):
        m = DatetimeModule()
        result = m.render()
        assert '星期' in result
        assert len(result) > 3

    def test_priority_is_1(self):
        assert DatetimeModule().priority == 1


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
        assert '心里亮亮的' in result

    def test_empty_when_no_primary_emotion(self):
        ctx = AgentContext()
        ctx.emotion_snapshot = {'primary_emotion': '', 'primary_intensity': 0.0}
        m = EmotionModule(ctx)
        assert m.render() == ''

    def test_parenthetical_format(self):
        ctx = AgentContext()
        ctx.emotion_snapshot = {'primary_emotion': '平静', 'primary_intensity': 0.3}
        m = EmotionModule(ctx)
        result = m.render()
        assert result.startswith('（')
        assert result.endswith('）')


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

    def test_max_2_memories_natural_format(self):
        ctx = AgentContext()
        ctx.memory_retrieval = [
            {'summary': f'topic {i}'} for i in range(5)
        ]
        m = MemoryModule(ctx)
        result = m.render()
        assert 'topic 0' in result
        assert 'topic 1' in result
        assert 'topic 2' not in result  # only shows 2

    def test_parenthetical_format(self):
        ctx = AgentContext()
        ctx.memory_retrieval = [{'summary': '樱花'}]
        m = MemoryModule(ctx)
        result = m.render()
        assert result.startswith('（')
        assert result.endswith('）')


class TestNotebookModule:
    def test_empty_when_no_notebook(self):
        m = NotebookModule()
        assert m.render() == ''

    @pytest.mark.asyncio
    async def test_empty_when_no_data(self):
        m = NotebookModule()
        assert await m.render_async() == ''


class TestContextBuilder:
    def test_registers_and_sorts_modules(self):
        builder = ContextBuilder()
        builder.register(DatetimeModule())
        builder.register(EmotionModule(AgentContext()))
        assert builder.module_names[0] == 'datetime'  # priority 1 first

    @pytest.mark.asyncio
    async def test_build_returns_natural_language(self):
        builder = ContextBuilder(total_budget=500)
        builder.register(DatetimeModule())
        result = await builder.build()
        assert '星期' in result
        # No XML tags
        assert '<context>' not in result
        assert '<module' not in result

    @pytest.mark.asyncio
    async def test_empty_when_no_enabled_modules(self):
        builder = ContextBuilder()
        m = DatetimeModule()
        m.enabled = False
        builder.register(m)
        assert await builder.build() == ''

    def test_get_module_by_name(self):
        builder = ContextBuilder()
        builder.register(DatetimeModule())
        m = builder.get_module('datetime')
        assert m is not None
        assert m.name == 'datetime'
        assert builder.get_module('nonexistent') is None
