"""
DatabaseManager — SQLite 数据库模块

统一管理 SQLite 连接和 conversation_logs 表的 CRUD。
阶段 2 建表就位；阶段 3 开始实际写入对话记录。
"""
import json
import uuid
import time
from pathlib import Path
from typing import Optional

import aiosqlite
from loguru import logger


# ── 建表 SQL ──────────────────────────────────────────

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS conversation_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL    NOT NULL,
    session_id      TEXT    NOT NULL,
    event_id        TEXT    NOT NULL UNIQUE,
    user_message    TEXT    NOT NULL,
    assistant_reply TEXT    NOT NULL,
    emotion_label   TEXT,
    emotion_primary TEXT,
    emotion_intensity REAL,
    user_id         TEXT    DEFAULT 'hezi',
    source          TEXT    DEFAULT 'console'
);
"""

_CREATE_INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON conversation_logs(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_logs_session ON conversation_logs(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_logs_emotion ON conversation_logs(emotion_primary);",
]


class DatabaseManager:
    """SQLite 数据库管理器 — 单连接、WAL 模式、全异步"""

    def __init__(self, db_path: str | Path = "data/xilian.db"):
        self.db_path = Path(db_path)
        self._conn: Optional[aiosqlite.Connection] = None
        self._session_id: str = uuid.uuid4().hex[:12]

    # ============================================================
    # 生命周期
    # ============================================================

    async def init(self) -> None:
        """初始化数据库：建表 + 开 WAL + 建索引（幂等）"""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row

        # 开启 WAL 模式（读写并发更好）
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")

        # 建表
        await self._conn.execute(_CREATE_TABLE_SQL)

        # 建索引
        for idx_sql in _CREATE_INDEXES_SQL:
            await self._conn.execute(idx_sql)

        await self._conn.commit()

        logger.info(
            "database.initialized",
            path=str(self.db_path),
            session_id=self._session_id,
        )

    async def close(self) -> None:
        """关闭数据库连接"""
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.debug("database.closed")

    # ============================================================
    # CRUD
    # ============================================================

    async def insert_log(
        self,
        event_id: str,
        user_message: str,
        assistant_reply: str,
        emotion_label: dict | None = None,
        emotion_primary: str | None = None,
        emotion_intensity: float | None = None,
        user_id: str = "hezi",
        source: str = "console",
    ) -> int:
        """
        写入一条对话记录。

        Returns:
            新插入行的 id
        """
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        emotion_json = json.dumps(emotion_label, ensure_ascii=False) if emotion_label else None

        cursor = await self._conn.execute(
            """INSERT INTO conversation_logs
               (timestamp, session_id, event_id, user_message, assistant_reply,
                emotion_label, emotion_primary, emotion_intensity, user_id, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                self._session_id,
                event_id,
                user_message,
                assistant_reply,
                emotion_json,
                emotion_primary,
                emotion_intensity,
                user_id,
                source,
            ),
        )
        await self._conn.commit()

        logger.debug(
            "database.insert_log",
            event_id=event_id[:8],
            emotion=emotion_primary,
        )
        return cursor.lastrowid

    async def get_recent(self, limit: int = 20) -> list[dict]:
        """
        查询最近 N 条对话记录（按 timestamp 倒序）。

        Returns:
            dict 列表，每条含所有字段
        """
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT * FROM conversation_logs ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_by_session(self, session_id: str, limit: int = 100) -> list[dict]:
        """按 session_id 查询对话记录"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT * FROM conversation_logs WHERE session_id = ? ORDER BY timestamp ASC LIMIT ?",
            (session_id, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_emotion_history(self, limit: int = 50) -> list[dict]:
        """查询有情绪标注的记录（用于情绪趋势）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT timestamp, emotion_primary, emotion_intensity, emotion_label "
            "FROM conversation_logs "
            "WHERE emotion_primary IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    # ============================================================
    # 工具属性
    # ============================================================

    @property
    def session_id(self) -> str:
        """当前会话标识"""
        return self._session_id
