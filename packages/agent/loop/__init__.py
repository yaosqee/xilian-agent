"""
Agent 循环 v2（P0 骨架）。

只新增模块，不切换 `AgentCore.process()` 的现有调用路径。
对外入口：

    from packages.agent.loop import AgentLoopRunner, LoopBudget, LoopToolExecutor

    runner = AgentLoopRunner(router, LoopToolExecutor(tool_executor))
    async for event in runner.run(messages, tools=openai_tools, budget=LoopBudget()):
        ...
"""
from .confirmation import ConfirmationStore, PendingConfirmation
from .events import (
    DoneEvent,
    LoopEvent,
    LoopEventType,
    ToolCall,
    ToolCallEvent,
    ToolOutcome,
    ToolResultEvent,
    TokenEvent,
)
from .executor import LoopToolExecutor
from .runner import (
    DEFAULT_BUDGET_TEXT,
    AgentLoopRunner,
    LoopBudget,
    LoopResult,
)

__all__ = [
    "AgentLoopRunner",
    "ConfirmationStore",
    "DEFAULT_BUDGET_TEXT",
    "DoneEvent",
    "LoopBudget",
    "LoopEvent",
    "LoopEventType",
    "LoopResult",
    "LoopToolExecutor",
    "PendingConfirmation",
    "ToolCall",
    "ToolCallEvent",
    "ToolOutcome",
    "ToolResultEvent",
    "TokenEvent",
]
