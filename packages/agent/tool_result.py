"""
ToolResult — 工具执行结果 + ToolContext 执行上下文

打磨期：工具系统重设计，统一工具返回格式。
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolContext:
    """工具执行上下文，由 ToolExecutor 自动注入。"""
    user_id: str = ""
    db: Any = None
    memory_manager: Any = None
    portrait_manager: Any = None
    notebook_manager: Any = None


@dataclass
class ToolResult:
    """工具执行结果。"""
    success: bool
    data: Any = None
    error: str = ""
    # 副作用标记 — 由工具开发者根据语义设置
    trigger_memory: bool = False
    trigger_portrait_update: bool = False

    @classmethod
    def ok(cls, data: Any, **kwargs) -> "ToolResult":
        return cls(success=True, data=data, **kwargs)

    @classmethod
    def fail(cls, error: str) -> "ToolResult":
        return cls(success=False, error=error)
