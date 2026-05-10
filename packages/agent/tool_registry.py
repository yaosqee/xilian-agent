"""
ToolRegistry — 进程内工具注册表

通过 @register_tool 装饰器注册函数，list_tools() 查询已注册工具列表。
本阶段只做注册和查询，不执行任何工具。调用逻辑在阶段 7 完整实现。
"""
from typing import Callable, Dict, Optional
from loguru import logger


class ToolRegistry:
    """进程内工具注册中心"""

    def __init__(self):
        self._tools: Dict[str, dict] = {}

    def register(self, name: str, description: str, schema: dict):
        """装饰器：将函数注册为工具

        Args:
            name: 工具唯一名称，如 "get_weather"
            description: 工具描述，LLM 依据此选择工具
            schema: JSON Schema 格式的参数定义
        """
        def decorator(func: Callable) -> Callable:
            self._tools[name] = {
                "name": name,
                "description": description,
                "schema": schema,
                "func": func,
            }
            logger.info(f"工具已注册: {name}")
            return func
        return decorator

    def list_tools(self) -> list[dict]:
        """返回已注册工具列表（不含函数体，安全）"""
        return [
            {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["schema"],
            }
            for t in self._tools.values()
        ]

    def get_tool(self, name: str) -> Optional[dict]:
        """内部查询工具（含函数体），仅供 Agent 调用"""
        return self._tools.get(name)

    @property
    def tool_names(self) -> list:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({len(self._tools)} tools: {self.tool_names})"
