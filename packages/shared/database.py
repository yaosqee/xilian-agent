"""
DatabaseManager — SQLite 数据库模块

统一管理 SQLite 连接和所有表的 CRUD。
阶段 2：conversation_logs 表建表就位。
阶段 3：新增 episodic_memories + message_queue 表 + CRUD，对话日志实际写入。
"""
import json
import uuid
import time
from pathlib import Path
from typing import Optional

import aiosqlite
from loguru import logger


# ── 建表 SQL ──────────────────────────────────────────

_CREATE_CONVERSATION_LOGS = """
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

_CREATE_EPISODIC_MEMORIES = """
CREATE TABLE IF NOT EXISTS episodic_memories (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         REAL    NOT NULL,
    summary           TEXT    NOT NULL,
    raw_conversation  TEXT    NOT NULL,
    emotion_tags      TEXT,
    importance        REAL    DEFAULT 0.5,
    embedding_id      TEXT,
    embedding_model   TEXT    DEFAULT 'bge-m3',
    embedding_version TEXT    DEFAULT 'v1',
    embedding_status  TEXT    DEFAULT 'pending',
    access_count      INTEGER DEFAULT 0,
    last_accessed     REAL,
    session_id        TEXT    NOT NULL
);
"""

_CREATE_MESSAGE_QUEUE = """
CREATE TABLE IF NOT EXISTS message_queue (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT    NOT NULL UNIQUE,
    payload      TEXT    NOT NULL,
    status       TEXT    DEFAULT 'pending',
    created_at   REAL    NOT NULL,
    started_at   REAL,
    completed_at REAL,
    error_msg    TEXT,
    retry_count  INTEGER DEFAULT 0
);
"""

_CREATE_INDEXES_SQL = [
    # conversation_logs
    "CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON conversation_logs(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_logs_session ON conversation_logs(session_id);",
    "CREATE INDEX IF NOT EXISTS idx_logs_emotion ON conversation_logs(emotion_primary);",
    # episodic_memories
    "CREATE INDEX IF NOT EXISTS idx_episodic_timestamp ON episodic_memories(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_episodic_importance ON episodic_memories(importance);",
    "CREATE INDEX IF NOT EXISTS idx_episodic_status ON episodic_memories(embedding_status);",
    "CREATE INDEX IF NOT EXISTS idx_episodic_embedding ON episodic_memories(embedding_id);",
    # message_queue
    "CREATE INDEX IF NOT EXISTS idx_queue_status ON message_queue(status, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_queue_event ON message_queue(event_id);",
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

        # 建表（幂等）
        await self._conn.execute(_CREATE_CONVERSATION_LOGS)
        await self._conn.execute(_CREATE_EPISODIC_MEMORIES)
        await self._conn.execute(_CREATE_MESSAGE_QUEUE)

        # 建索引（幂等）
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
    # episodic_memories CRUD（阶段 3 新增）
    # ============================================================

    async def insert_episodic_memory(
        self,
        summary: str,
        raw_conversation: str,
        emotion_tags: dict | None = None,
        importance: float = 0.5,
        embedding_model: str = "bge-m3",
        embedding_version: str = "v1",
        session_id: str | None = None,
    ) -> int:
        """
        写入一条情景记忆（status=pending）。
        向量化完成后调用 update_embedding_status() 标记 done。

        Returns:
            新插入行的 id
        """
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        emotion_json = json.dumps(emotion_tags, ensure_ascii=False) if emotion_tags else None
        sid = session_id or self._session_id

        cursor = await self._conn.execute(
            """INSERT INTO episodic_memories
               (timestamp, summary, raw_conversation, emotion_tags, importance,
                embedding_model, embedding_version, embedding_status, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                time.time(),
                summary,
                raw_conversation,
                emotion_json,
                importance,
                embedding_model,
                embedding_version,
                sid,
            ),
        )
        await self._conn.commit()
        logger.debug("database.insert_episodic_memory", id=cursor.lastrowid)
        return cursor.lastrowid

    async def update_embedding_status(
        self,
        memory_id: int,
        status: str,
        embedding_id: str | None = None,
    ) -> None:
        """更新记忆的向量化状态 + embedding_id"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        if embedding_id:
            await self._conn.execute(
                "UPDATE episodic_memories SET embedding_status=?, embedding_id=? WHERE id=?",
                (status, embedding_id, memory_id),
            )
        else:
            await self._conn.execute(
                "UPDATE episodic_memories SET embedding_status=? WHERE id=?",
                (status, memory_id),
            )
        await self._conn.commit()
        logger.debug("database.update_embedding_status", id=memory_id, status=status)

    async def update_embedding_model(
        self,
        memory_id: int,
        model: str,
        version: str,
    ) -> None:
        """更新嵌入模型信息（模型切换时使用）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        await self._conn.execute(
            "UPDATE episodic_memories SET embedding_model=?, embedding_version=? WHERE id=?",
            (model, version, memory_id),
        )
        await self._conn.commit()

    async def get_episodic_memory(self, memory_id: int) -> dict | None:
        """按主键查询单条记忆"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT * FROM episodic_memories WHERE id=?",
            (memory_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_episodic_by_embedding_ids(self, embedding_ids: list[str]) -> list[dict]:
        """按 ChromaDB embedding_id 批量查询"""
        if not self._conn or not embedding_ids:
            if not self._conn:
                raise RuntimeError("DatabaseManager.init() 未调用")
            return []

        placeholders = ",".join("?" for _ in embedding_ids)
        cursor = await self._conn.execute(
            f"SELECT * FROM episodic_memories WHERE embedding_id IN ({placeholders})",
            embedding_ids,
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_episodic_recent(self, limit: int = 20) -> list[dict]:
        """查询最近 N 条记忆（按 timestamp 倒序）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT * FROM episodic_memories ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_episodic_pending(self) -> list[dict]:
        """查询所有 status='pending' 的记录（repair_pending 用）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT * FROM episodic_memories WHERE embedding_status='pending'"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_all_episodic(self) -> list[dict]:
        """获取所有记忆记录（容量管理用）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT id, timestamp, importance FROM episodic_memories"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_episodic(self, memory_id: int) -> None:
        """删除单条记忆"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        await self._conn.execute(
            "DELETE FROM episodic_memories WHERE id=?",
            (memory_id,),
        )
        await self._conn.commit()
        logger.debug("database.delete_episodic", id=memory_id)

    async def increment_access_count(self, memory_id: int) -> None:
        """检索命中后更新 access_count + last_accessed"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        await self._conn.execute(
            "UPDATE episodic_memories SET access_count=access_count+1, last_accessed=? WHERE id=?",
            (time.time(), memory_id),
        )
        await self._conn.commit()

    async def get_episodic_count(self) -> int:
        """获取记忆总数（容量管理用）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT COUNT(*) as cnt FROM episodic_memories"
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    # ============================================================
    # message_queue 消息队列 CRUD（阶段 3 新增）
    # ============================================================

    async def queue_push(self, event_id: str, payload: str) -> bool:
        """
        入队。event_id 已存在 → 幂等跳过，返回 False。

        Returns:
            True  — 成功入队
            False — 重复 event_id，跳过
        """
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        try:
            await self._conn.execute(
                """INSERT INTO message_queue (event_id, payload, status, created_at)
                   VALUES (?, ?, 'pending', ?)""",
                (event_id, payload, time.time()),
            )
            await self._conn.commit()
            logger.debug("database.queue_push", event_id=event_id[:8])
            return True
        except aiosqlite.IntegrityError:
            # event_id UNIQUE 冲突 → 幂等跳过
            logger.debug("database.queue_push_duplicate", event_id=event_id[:8])
            return False

    async def queue_pop(self) -> dict | None:
        """
        出队：取最早 pending → 标记 processing → 返回。
        无 pending 时返回 None。
        """
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            """SELECT id, event_id, payload FROM message_queue
               WHERE status='pending'
               ORDER BY created_at ASC LIMIT 1"""
        )
        row = await cursor.fetchone()
        if not row:
            return None

        row_dict = dict(row)
        now = time.time()
        await self._conn.execute(
            "UPDATE message_queue SET status='processing', started_at=? WHERE id=?",
            (now, row_dict["id"]),
        )
        await self._conn.commit()
        logger.debug("database.queue_pop", event_id=row_dict["event_id"][:8])
        return row_dict

    async def queue_mark_done(self, event_id: str) -> None:
        """标记消息处理完成"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        await self._conn.execute(
            "UPDATE message_queue SET status='done', completed_at=? WHERE event_id=?",
            (time.time(), event_id),
        )
        await self._conn.commit()
        logger.debug("database.queue_mark_done", event_id=event_id[:8])

    async def queue_mark_failed(self, event_id: str, error: str) -> None:
        """标记失败 + 错误信息"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        await self._conn.execute(
            """UPDATE message_queue
               SET status='failed', completed_at=?, error_msg=?,
                   retry_count=retry_count+1
               WHERE event_id=?""",
            (time.time(), error, event_id),
        )
        await self._conn.commit()
        logger.warning("database.queue_mark_failed", event_id=event_id[:8], error=error[:80])

    async def queue_recover_stale(self, timeout_minutes: int = 5) -> int:
        """
        扫描 status='processing' 且 started_at 超过 timeout 的记录
        → 重新标记为 pending
        → 返回恢复数量
        用于 Agent 重启时恢复。
        """
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cutoff = time.time() - (timeout_minutes * 60)
        cursor = await self._conn.execute(
            """UPDATE message_queue SET status='pending', started_at=NULL
               WHERE status='processing' AND started_at < ?""",
            (cutoff,),
        )
        await self._conn.commit()
        recovered = cursor.rowcount
        if recovered > 0:
            logger.info("database.queue_recover_stale", recovered=recovered)
        return recovered

    async def queue_purge_old(self, days: int = 7) -> int:
        """清理 N 天前的 done/failed 记录"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cutoff = time.time() - (days * 86400)
        cursor = await self._conn.execute(
            """DELETE FROM message_queue
               WHERE status IN ('done', 'failed') AND completed_at < ?""",
            (cutoff,),
        )
        await self._conn.commit()
        purged = cursor.rowcount
        if purged > 0:
            logger.info("database.queue_purge_old", purged=purged, days=days)
        return purged

    # ============================================================
    # 工具属性
    # ============================================================

    @property
    def session_id(self) -> str:
        """当前会话标识"""
        return self._session_id
