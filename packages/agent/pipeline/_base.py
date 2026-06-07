"""
ServiceModule 基类

注意：这不是真正的 Pipeline 模式（Stage → Stage 链式传递数据）。
这些模块被 AgentCore.process() 编排调用，各自操作 AgentContext 的不同字段。
基类只是一个依赖注入容器——为子类提供共享依赖的便捷访问。

router 和 db 为可选参数——不需要它们的模块可以不传。
"""

from __future__ import annotations


class ServiceModule:
    """所有提取模块的基类。

    子类通过 self._ctx / self._router / self._db 访问共享依赖。
    """

    def __init__(self, ctx, router=None, db=None):
        self._ctx = ctx              # AgentContext（必选）
        self._router = router        # ModelRouter（可选）
        self._db = db                # DatabaseManager（可选）
