"""
ConfirmationStore — 按会话保存待确认的工具调用（P2，内存版）。

设计目标是替代 `AgentCore._pending_confirmation` 单槽：
- key = (user_id, session_id)，两个会话并行确认不会串；
- 只存 pending 调用 + runner 给的可恢复上下文，不存业务数据；
- 带 TTL，过期自动清理（默认 300s，可用 LOOP_CONFIRMATION_TTL 覆盖）；
- 进程内内存，重启丢失；后续需要跨重启再换 DB 实现。

P2 先做内存版是刻意取舍：确认窗口很短，重启后用户重说一次即可；
DB 持久化等有真实需求再做，避免现在引入迁移成本。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from .events import ToolCall


@dataclass
class PendingConfirmation:
    """一个会话挂起的确认请求。"""

    user_id: str
    session_id: str
    calls: list[ToolCall]
    resume_messages: list[dict] = field(default_factory=list)
    created_at: float = 0.0
    expires_at: float = 0.0

    @property
    def tool_names(self) -> list[str]:
        return [call.name for call in self.calls]

    def is_expired(self, now: float) -> bool:
        return self.expires_at > 0 and now >= self.expires_at


class ConfirmationStore:
    """会话级 pending 存储。同一会话只保留最新一条。"""

    def __init__(self, ttl_seconds: float = 300.0,
                 clock: Callable[[], float] | None = None):
        self.ttl_seconds = max(1.0, float(ttl_seconds))
        self._clock = clock or time.monotonic
        self._items: dict[tuple[str, str], PendingConfirmation] = {}

    @staticmethod
    def key(user_id: str, session_id: str) -> tuple[str, str]:
        return (user_id or "anonymous", session_id or "default")

    def put(
        self,
        user_id: str,
        session_id: str,
        calls: list[ToolCall],
        resume_messages: list[dict] | None = None,
    ) -> PendingConfirmation:
        now = self._clock()
        item = PendingConfirmation(
            user_id=user_id,
            session_id=session_id,
            calls=list(calls),
            resume_messages=[dict(message) for message in (resume_messages or [])],
            created_at=now,
            expires_at=now + self.ttl_seconds,
        )
        self._items[self.key(user_id, session_id)] = item
        return item

    def get(self, user_id: str, session_id: str) -> PendingConfirmation | None:
        key = self.key(user_id, session_id)
        item = self._items.get(key)
        if item is None:
            return None
        if item.is_expired(self._clock()):
            self._items.pop(key, None)
            return None
        return item

    def discard(self, user_id: str, session_id: str) -> None:
        self._items.pop(self.key(user_id, session_id), None)

    def purge_expired(self) -> int:
        now = self._clock()
        expired = [key for key, item in self._items.items() if item.is_expired(now)]
        for key in expired:
            self._items.pop(key, None)
        return len(expired)

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        self.purge_expired()
        return len(self._items)
