"""ToolHandlerProcessor — 工具调用处理 + 确认回路"""

import json
from loguru import logger

from ._base import ServiceModule


class ToolHandlerProcessor(ServiceModule):
    """工具调用处理器。依赖 tool_executor, result_wrapper（异步注入）."""

    def __init__(self, ctx, router=None, db=None):
        super().__init__(ctx, router=router, db=db)
        self._executor = None
        self._wrapper = None
        self._registry = None

    def set_tools(self, executor, wrapper, registry):
        self._executor = executor
        self._wrapper = wrapper
        self._registry = registry
