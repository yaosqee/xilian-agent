"""
Repository 基类

所有 Repository 共享同一个 aiosqlite.Connection 引用。
跨 Repository 事务由 DatabaseManager 统一管理（commit / rollback），
各 Repository 不自行调用 commit() —— 只执行 SQL，事务边界由调用方控制。

设计要点：
- self._conn 是共享引用（不是每个 Repo 自己的连接），同一线程/协程中所有 Repo 在同一事务内
- _ensure_conn() 统一检查连接是否就绪，避免每个方法重复 if not self._conn 守卫
"""

from __future__ import annotations

from typing import Optional
import aiosqlite


class BaseRepository:
    """Repository 基类。所有领域 Repository 继承此类。"""

    def __init__(self, conn: aiosqlite.Connection | None, session_id: str):
        self._conn: Optional[aiosqlite.Connection] = conn
        self._session_id: str = session_id

    def _ensure_conn(self) -> aiosqlite.Connection:
        """确保连接已初始化。若未初始化则抛出 RuntimeError。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        return self._conn
