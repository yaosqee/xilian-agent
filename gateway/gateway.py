"""
Gateway — 消息网关

统一管理所有消息通道，连接 Agent 核心，提供安全过滤。
"""
import asyncio
from loguru import logger

from .channels.base import Channel
from .security import SecurityFilter
from packages.agent import AgentCore


class Gateway:
    """消息网关：通道管理 + 安全过滤 + Agent 路由"""

    def __init__(self, agent: AgentCore, security: SecurityFilter | None = None):
        self.agent = agent
        self.security = security or SecurityFilter()
        self.channels: list[Channel] = []
        self._tasks: list[asyncio.Task] = []

    def register(self, channel: Channel) -> "Gateway":
        """注册一个消息通道"""
        self.channels.append(channel)
        logger.info(f"gateway.channel_registered: {channel}")
        return self

    async def start(self) -> None:
        """启动所有已注册的通道（并发运行）"""
        logger.info(
            "gateway.starting",
            channels=[ch.name for ch in self.channels],
        )

        async def _run(channel: Channel):
            try:
                await channel.start(self.agent.process)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(
                    "gateway.channel_error",
                    channel=channel.name,
                    error=str(e),
                )

        # 所有通道并发启动
        self._tasks = [
            asyncio.create_task(_run(ch))
            for ch in self.channels
        ]

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            await self.stop()

    async def stop(self) -> None:
        """停止所有通道"""
        logger.info("gateway.stopping")

        for channel in self.channels:
            try:
                await channel.stop()
            except Exception as e:
                logger.warning(
                    "gateway.stop_error",
                    channel=channel.name,
                    error=str(e),
                )

        for task in self._tasks:
            if not task.done():
                task.cancel()

        logger.info("gateway.stopped")
