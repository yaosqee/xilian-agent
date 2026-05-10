"""
Channel — 通道抽象基类

所有消息通道（Console、HTTP、将来微信等）统一实现此接口。
Gateway 通过此接口解耦通道与 Agent。
"""
from abc import ABC, abstractmethod
from typing import Awaitable, Callable

from packages.shared.events import InternalEvent

# Agent 处理器签名：接收 InternalEvent，返回回复文本
EventHandler = Callable[[InternalEvent], Awaitable[str]]


class Channel(ABC):
    """消息通道抽象基类"""

    def __init__(self, name: str = ""):
        self.name = name or self.__class__.__name__

    @abstractmethod
    async def start(self, handler: EventHandler) -> None:
        """
        启动通道，开始监听消息。

        Args:
            handler: 消息处理回调，接收 InternalEvent 返回回复文本
        """
        ...

    @abstractmethod
    async def send(self, text: str) -> None:
        """向通道发送回复文本"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """优雅关闭通道"""
        ...

    def __repr__(self) -> str:
        return f"{self.name}"
