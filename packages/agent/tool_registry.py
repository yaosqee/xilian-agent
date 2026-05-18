"""
ToolRegistry — 进程内工具注册表

通过 @register_tool 装饰器注册函数，list_tools() 查询已注册工具列表。
阶段 8: +工具权限级别（read_only / read_write / execute）。
打磨期: +category / max_frequency / requires_confirmation + autodiscover + to_openai_tools。
"""
import importlib
import os
import pkgutil
from enum import Enum
from typing import Callable, Dict, Optional, Any
from loguru import logger

# 模块级待注册队列：工具模块在 import 时调用 register_tool()，
# autodiscover() 消费此队列，将工具注册到 ToolRegistry 实例。
_PENDING: list[dict] = []


def register_tool(name: str, description: str, schema: dict,
                  permission: "ToolPermission" = None,
                  category: str = "general",
                  max_frequency: int = 10,
                  requires_confirmation: bool = False,
                  trigger_memory: bool = False,
                  trigger_portrait: bool = False):
    """
    模块级工具注册（供 autodiscover 使用）。
    工具文件在顶层调用此函数，autodiscover 导入后消费 _PENDING 队列。
    """
    if permission is None:
        permission = ToolPermission.READ_ONLY

    def decorator(func):
        _PENDING.append({
            "name": name,
            "description": description,
            "schema": schema,
            "func": func,
            "permission": permission,
            "category": category,
            "max_frequency": max_frequency,
            "requires_confirmation": requires_confirmation,
            "trigger_memory": trigger_memory,
            "trigger_portrait": trigger_portrait,
        })
        return func
    return decorator


class ToolPermission(Enum):
    READ_ONLY = "read_only"       # 只读（search, weather）
    READ_WRITE = "read_write"     # 读写（create_file, send_email）
    EXECUTE = "execute"           # 执行（coding_delegate, shell）


class ToolRegistry:
    """进程内工具注册中心"""

    def __init__(self):
        self._tools: Dict[str, dict] = {}

    def register(self, name: str, description: str, schema: dict,
                 permission: ToolPermission = ToolPermission.READ_ONLY,
                 category: str = "general",
                 max_frequency: int = 10,
                 requires_confirmation: bool = False,
                 trigger_memory: bool = False,
                 trigger_portrait: bool = False):
        """装饰器：将函数注册为工具

        Args:
            name: 工具唯一名称，如 "get_weather"
            description: 工具描述，LLM 依据此选择工具
            schema: JSON Schema 格式的参数定义
            permission: 工具权限级别
            category: 工具分类（memory / external / utility / system）
            max_frequency: 每小时最大调用次数，0 = 不限
            requires_confirmation: True 时执行前需用户确认
            trigger_memory: True 时工具结果触发情景记忆编码
            trigger_portrait: True 时工具结果标记印象文档 dirty
        """
        def decorator(func: Callable) -> Callable:
            self._tools[name] = {
                "name": name,
                "description": description,
                "schema": schema,
                "func": func,
                "permission": permission,
                "category": category,
                "max_frequency": max_frequency,
                "requires_confirmation": requires_confirmation,
                "trigger_memory": trigger_memory,
                "trigger_portrait": trigger_portrait,
            }
            logger.info(f"工具已注册: {name} [{permission.value}] cat={category}")
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

    def to_openai_tools(self) -> list[dict]:
        """转为 OpenAI function-calling 格式的工具列表。"""
        tools = []
        for t in self._tools.values():
            schema = t["schema"]

            # 检测 schema 格式
            if "properties" in schema and "type" in schema:
                # 已经是 OpenAI 嵌套格式，直接使用
                params = schema
            else:
                # 扁平格式 {param: {type, description, required}} → 嵌套格式
                props = {}
                required = []
                for pname, pinfo in schema.items():
                    if isinstance(pinfo, dict):
                        props[pname] = {
                            "type": pinfo.get("type", "string"),
                            "description": pinfo.get("description", ""),
                        }
                        if pinfo.get("required"):
                            required.append(pname)
                params = {
                    "type": "object",
                    "properties": props,
                    "required": required,
                }

            tools.append({
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": params,
                },
            })
        return tools

    def is_allowed(self, name: str, safe_mode: bool = False) -> bool:
        """
        检查工具是否允许执行。
        安全模式下禁用 read_write 和 execute 级别工具。
        """
        tool = self._tools.get(name)
        if not tool:
            return False
        if not safe_mode:
            return True
        return tool["permission"] == ToolPermission.READ_ONLY

    def autodiscover(self, package_path: str = "packages.agent.tools") -> int:
        """
        自动发现并导入工具模块。扫描指定 package 下所有子模块，
        导入后消费 _PENDING 队列完成注册。

        Returns:
            新注册的工具数量。
        """
        global _PENDING
        before = len(self._tools)

        try:
            package = importlib.import_module(package_path)
            pkg_dir = os.path.dirname(package.__file__) if package.__file__ else None
            if not pkg_dir:
                return 0
            for _, name, is_pkg in pkgutil.iter_modules([pkg_dir]):
                if is_pkg or name.startswith("_"):
                    continue
                try:
                    importlib.import_module(f"{package_path}.{name}")
                except Exception as e:
                    logger.warning(f"tool.autodiscover_skip: {name}", error=str(e))
        except Exception as e:
            logger.error("tool.autodiscover_failed", error=str(e))
            return 0

        # 消费 _PENDING 队列（去重：同名工具只注册一次）
        seen = set(self._tools.keys())
        for meta in _PENDING:
            if meta["name"] not in seen:
                self.register(**{k: v for k, v in meta.items() if k != "func"})(
                    meta["func"]
                )
                seen.add(meta["name"])
        _PENDING = []

        count = len(self._tools) - before
        if count > 0:
            logger.info(f"tool.autodiscover: +{count} tools")
        return count

    @property
    def tool_names(self) -> list:
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry({len(self._tools)} tools: {self.tool_names})"
