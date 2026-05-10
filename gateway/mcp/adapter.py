"""
MCPAdapter — MCP 协议适配器（阶段 7 实现）

将 @register_tool 注册的内部工具暴露为 MCP Server，
供外部 MCP 客户端接入。

本阶段（阶段 1）仅定义接口签名 + docstring。
"""
from typing import Any


class MCPAdapter:
    """
    MCP Server 适配器。

    将一个 ToolRegistry 实例注册的所有工具暴露为
    符合 MCP 协议规范的 HTTP/SSE 服务。

    用法（阶段 7）:
        adapter = MCPAdapter(tool_registry)
        await adapter.start(host="0.0.0.0", port=8100)
    """

    def __init__(self, tool_registry):
        """
        Args:
            tool_registry: ToolRegistry 实例，包含所有 @register_tool 注册的工具
        """
        self.tool_registry = tool_registry
        self._running = False

    async def start(self, host: str = "127.0.0.1", port: int = 8100) -> None:
        """
        启动 MCP Server。

        阶段 7 实现：创建 HTTP Server，注册 /tools/list 和 /tools/call 端点，
        实现 MCP 协议规范的 JSON-RPC 2.0 消息格式。

        Args:
            host: 监听地址
            port: 监听端口
        """
        raise NotImplementedError("MCPAdapter.start() — 阶段 7 实现")

    async def stop(self) -> None:
        """关闭 MCP Server"""
        raise NotImplementedError("MCPAdapter.stop() — 阶段 7 实现")

    async def list_tools(self) -> list[dict]:
        """
        MCP tools/list 端点。

        返回 ToolRegistry 中所有已注册工具的列表，
        格式符合 MCP 契约：{name, description, inputSchema}.

        Returns:
            MCP 工具列表
        """
        raise NotImplementedError("MCPAdapter.list_tools() — 阶段 7 实现")

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """
        MCP tools/call 端点。

        通过 ToolRegistry 查找并同步执行对应工具函数。

        Args:
            name: 工具名称（与 @register_tool 的 name 一致）
            arguments: 工具参数

        Returns:
            工具执行结果
        """
        raise NotImplementedError("MCPAdapter.call_tool() — 阶段 7 实现")

    def __repr__(self) -> str:
        return f"MCPAdapter({len(self.tool_registry)} tools)"
