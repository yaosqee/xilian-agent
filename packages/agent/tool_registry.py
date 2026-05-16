"""
ToolRegistry — 进程内工具注册表

通过 @register_tool 装饰器注册函数，list_tools() 查询已注册工具列表。
阶段 8: +工具权限级别（read_only / read_write / execute）。
"""
from enum import Enum
from typing import Callable, Dict, Optional
from loguru import logger


class ToolPermission(Enum):
    READ_ONLY = "read_only"       # 只读（search, weather）
    READ_WRITE = "read_write"     # 读写（create_file, send_email）
    EXECUTE = "execute"           # 执行（coding_delegate, shell）


class ToolRegistry:
    """进程内工具注册中心"""

    def __init__(self):
        self._tools: Dict[str, dict] = {}

    def register(self, name: str, description: str, schema: dict,
                 permission: ToolPermission = ToolPermission.READ_ONLY):
        """装饰器：将函数注册为工具

        Args:
            name: 工具唯一名称，如 "get_weather"
            description: 工具描述，LLM 依据此选择工具
            schema: JSON Schema 格式的参数定义
            permission: 工具权限级别（阶段 8 新增）
        """
        def decorator(func: Callable) -> Callable:
            self._tools[name] = {
                "name": name,
                "description": description,
                "schema": schema,
                "func": func,
                "permission": permission,
            }
            logger.info(f"工具已注册: {name} [{permission.value}]")
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

    def is_allowed(self, name: str, safe_mode: bool = False) -> bool:
        """
        阶段 8: 检查工具是否允许执行。
        安全模式下禁用 read_write 和 execute 级别工具。
        """
        tool = self._tools.get(name)
        if not tool:
            return False
        if not safe_mode:
            return True
        return tool["permission"] == ToolPermission.READ_ONLY

    @property
    def tool_names(self) -> list:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({len(self._tools)} tools: {self.tool_names})"
