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

_CREATE_EMOTION_SNAPSHOTS = """
CREATE TABLE IF NOT EXISTS emotion_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL    NOT NULL,
    pad_p           REAL    NOT NULL DEFAULT 0.0,
    pad_a           REAL    NOT NULL DEFAULT 0.0,
    pad_d           REAL    NOT NULL DEFAULT 0.0,
    primary_emotion TEXT,
    primary_intensity REAL,
    dimensions_json TEXT,
    appraisal_relevance  REAL,
    appraisal_facilitation REAL,
    appraisal_coping     REAL,
    source          TEXT    DEFAULT 'appraisal',
    session_id      TEXT    NOT NULL,
    trace_id        TEXT
);
"""

_CREATE_AUTOBIOGRAPHY = """
CREATE TABLE IF NOT EXISTS autobiography_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT    NOT NULL UNIQUE,
    content     TEXT    NOT NULL,
    word_count  INTEGER DEFAULT 0,
    mood_summary TEXT,
    key_memories TEXT,
    created_at  REAL    NOT NULL,
    session_id  TEXT    NOT NULL
);
"""

_CREATE_REFLECTION_CRYSTALS = """
CREATE TABLE IF NOT EXISTS reflection_crystals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start  TEXT    NOT NULL,
    week_end    TEXT    NOT NULL,
    learned     TEXT,
    surprised   TEXT,
    grateful    TEXT,
    remember    TEXT,
    raw_prompt  TEXT,
    created_at  REAL    NOT NULL,
    session_id  TEXT    NOT NULL
);
"""

_CREATE_AUTONOMY_SETTINGS = """
CREATE TABLE IF NOT EXISTS autonomy_settings (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL,
    updated_at  REAL NOT NULL
);
"""

# ── 阶段 7b: Notebook ──

_CREATE_NOTEBOOK_ENTRIES = """
CREATE TABLE IF NOT EXISTS notebook_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    tags        TEXT,
    importance  REAL    DEFAULT 0.5,
    is_active   INTEGER DEFAULT 1,
    due_date    REAL,
    created_at  REAL    NOT NULL,
    session_id  TEXT    NOT NULL
);
"""

_CREATE_SCHEDULED_TASKS = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    details     TEXT,
    priority    INTEGER DEFAULT 0,
    status      TEXT    DEFAULT 'pending',
    due_at      REAL,
    created_at  REAL    NOT NULL,
    completed_at REAL,
    session_id  TEXT    NOT NULL
);
"""

# ── 阶段 8: 审计日志 ──

_CREATE_AUDIT_LOGS = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL    NOT NULL,
    event_type  TEXT    NOT NULL,
    severity    TEXT    DEFAULT 'info',
    source      TEXT    DEFAULT 'system',
    detail      TEXT,
    user_id     TEXT    DEFAULT 'hezi',
    trace_id    TEXT
);
"""

_CREATE_AFFECTION = """
CREATE TABLE IF NOT EXISTS affection_state (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    score               REAL    NOT NULL DEFAULT 0.0,
    level               INTEGER NOT NULL DEFAULT 1,
    total_conversations INTEGER NOT NULL DEFAULT 0,
    reason              TEXT,
    updated_at          REAL    NOT NULL
);
"""

_CREATE_USER_PORTRAIT = """
CREATE TABLE IF NOT EXISTS user_portrait (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT    NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    source_ids  TEXT,
    change_log  TEXT,
    created_at  REAL    NOT NULL,
    session_id  TEXT    NOT NULL
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
    # emotion_snapshots
    "CREATE INDEX IF NOT EXISTS idx_emo_timestamp ON emotion_snapshots(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_emo_session ON emotion_snapshots(session_id);",
    # autobiography
    "CREATE INDEX IF NOT EXISTS idx_auto_date ON autobiography_entries(date);",
    # reflection
    "CREATE INDEX IF NOT EXISTS idx_ref_week ON reflection_crystals(week_start);",
    # notebook
    "CREATE INDEX IF NOT EXISTS idx_notebook_kind ON notebook_entries(kind, created_at);",
    "CREATE INDEX IF NOT EXISTS idx_notebook_active ON notebook_entries(is_active, created_at);",
    # scheduled_tasks
    "CREATE INDEX IF NOT EXISTS idx_tasks_status ON scheduled_tasks(status, due_at);",
    "CREATE INDEX IF NOT EXISTS idx_tasks_due ON scheduled_tasks(due_at) WHERE status='pending';",
    # audit_logs
    "CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp);",
    "CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_logs(event_type, timestamp);",
    # affection
    "CREATE INDEX IF NOT EXISTS idx_affection_updated ON affection_state(updated_at);",
    # user_portrait
    "CREATE INDEX IF NOT EXISTS idx_portrait_version ON user_portrait(version);",
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
        """
        初始化数据库：Alembic 迁移优先，降级为手动建表（幂等）。

        阶段 7d: 首选 alembic upgrade head，失败或不可用时手动建表。
        注意：alembic.ini 硬编码了 data/xilian.db，非默认路径时跳过 alembic。
        """
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = await aiosqlite.connect(str(self.db_path))
        self._conn.row_factory = aiosqlite.Row

        # 开启 WAL 模式（读写并发更好）
        await self._conn.execute("PRAGMA journal_mode=WAL;")
        await self._conn.execute("PRAGMA foreign_keys=ON;")

        # 阶段 7d: 尝试 Alembic 迁移（仅默认路径）
        default_db = Path("data/xilian.db").resolve()
        is_default = self.db_path.resolve() == default_db
        migrated = await self._try_alembic_migrate() if is_default else False

        if not migrated:
            # 降级：手动建表（幂等）
            await self._manual_init()
        else:
            # Alembic 路径：确保新增表也创建（Alembic 迁移未覆盖时兜底）
            await self._conn.execute(_CREATE_USER_PORTRAIT)
            for idx_sql in _CREATE_INDEXES_SQL:
                if "user_portrait" in idx_sql or "portrait_version" in idx_sql:
                    await self._conn.execute(idx_sql)

        await self._conn.commit()

        logger.info(
            "database.initialized",
            path=str(self.db_path),
            session_id=self._session_id,
            method="alembic" if migrated else "manual",
        )

    async def _try_alembic_migrate(self) -> bool:
        """尝试用 Alembic 迁移。成功返回 True，失败返回 False。"""
        try:
            import subprocess, os as _os
            root = Path(__file__).resolve().parent.parent.parent
            env = {**_os.environ, "SQLALCHEMY_URL": f"sqlite:///{self.db_path}"}
            result = subprocess.run(
                ["uv", "run", "alembic", "upgrade", "head"],
                cwd=str(root),
                capture_output=True, text=True,
                timeout=30,
                env=env,
            )
            if result.returncode == 0:
                logger.info("database.alembic_migrated")
                return True
            logger.warning("database.alembic_failed", stderr=result.stderr[:200])
            return False
        except Exception as e:
            logger.info("database.alembic_unavailable", reason=str(e))
            return False

    async def _manual_init(self):
        """降级：手动建表 + 建索引（幂等）。"""
        await self._conn.execute(_CREATE_CONVERSATION_LOGS)
        await self._conn.execute(_CREATE_EPISODIC_MEMORIES)
        await self._conn.execute(_CREATE_MESSAGE_QUEUE)
        await self._conn.execute(_CREATE_EMOTION_SNAPSHOTS)
        await self._conn.execute(_CREATE_AUTOBIOGRAPHY)
        await self._conn.execute(_CREATE_REFLECTION_CRYSTALS)
        await self._conn.execute(_CREATE_AUTONOMY_SETTINGS)
        await self._conn.execute(_CREATE_NOTEBOOK_ENTRIES)
        # 迁移：为已有 notebook_entries 表补加 due_date 列（幂等）
        try:
            await self._conn.execute(
                "ALTER TABLE notebook_entries ADD COLUMN due_date REAL"
            )
        except Exception:
            pass  # 列已存在
        await self._conn.execute(_CREATE_SCHEDULED_TASKS)
        await self._conn.execute(_CREATE_AUDIT_LOGS)
        await self._conn.execute(_CREATE_AFFECTION)
        await self._conn.execute(_CREATE_USER_PORTRAIT)
        for idx_sql in _CREATE_INDEXES_SQL:
            await self._conn.execute(idx_sql)
        await self._conn.commit()

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

    async def get_conversation_history(
        self, before_id: int | None = None, limit: int = 10,
        user_id: str = "hezi",
    ) -> list[dict]:
        """
        游标分页查询历史对话（按 id 倒序，最新在前）。

        不传 before_id → 返回最新 N 条。
        传 before_id → 返回 id < before_id 的 N 条（更早的记录）。
        """
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        if before_id:
            cursor = await self._conn.execute(
                "SELECT * FROM conversation_logs WHERE id < ? AND user_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (before_id, user_id, limit),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM conversation_logs WHERE user_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_conversation_total(self, user_id: str = "hezi") -> int:
        """获取历史对话总轮数"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_logs WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def clear_conversation_logs(self, user_id: str = "hezi") -> int:
        """清空对话日志（重置会话时调用）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            "DELETE FROM conversation_logs WHERE user_id = ?",
            (user_id,),
        )
        await self._conn.commit()
        return cursor.rowcount

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
    # emotion_snapshots CRUD（阶段 4 新增）
    # ============================================================

    async def insert_emotion_snapshot(
        self,
        pad_p: float, pad_a: float, pad_d: float,
        primary_emotion: str | None = None,
        primary_intensity: float = 0.0,
        dimensions: dict | None = None,
        appraisal_relevance: float | None = None,
        appraisal_facilitation: float | None = None,
        appraisal_coping: float | None = None,
        source: str = "appraisal",
        trace_id: str | None = None,
    ) -> int:
        """写入一条情感快照"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        dims_json = json.dumps(dimensions, ensure_ascii=False) if dimensions else None

        cursor = await self._conn.execute(
            """INSERT INTO emotion_snapshots
               (timestamp, pad_p, pad_a, pad_d,
                primary_emotion, primary_intensity, dimensions_json,
                appraisal_relevance, appraisal_facilitation, appraisal_coping,
                source, session_id, trace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                pad_p, pad_a, pad_d,
                primary_emotion, primary_intensity, dims_json,
                appraisal_relevance, appraisal_facilitation, appraisal_coping,
                source, self._session_id, trace_id,
            ),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_latest_emotion(self) -> dict | None:
        """获取最新的情感快照"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT * FROM emotion_snapshots ORDER BY timestamp DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_emotion_snapshots(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        """按时间倒序查询情感快照历史"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT * FROM emotion_snapshots ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_emotion_stats(self, days: int = 7) -> dict:
        """获取情绪统计摘要"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cutoff = time.time() - days * 86400
        cursor = await self._conn.execute(
            "SELECT * FROM emotion_snapshots WHERE timestamp >= ? ORDER BY timestamp ASC",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        if not rows:
            return {"avg_pad": {"P": 0, "A": 0, "D": 0}, "snapshot_count": 0}

        records = [dict(r) for r in rows]
        n = len(records)
        avg_p = sum(r["pad_p"] for r in records) / n
        avg_a = sum(r["pad_a"] for r in records) / n
        avg_d = sum(r["pad_d"] for r in records) / n

        # 情绪分布
        from collections import Counter
        emotions = [r["primary_emotion"] for r in records if r["primary_emotion"]]
        distribution = {k: v / n for k, v in Counter(emotions).most_common()}

        # 情绪波动率（最大 PAD 距离）
        pads = [(r["pad_p"], r["pad_a"], r["pad_d"]) for r in records]
        max_dist = 0.0
        for i in range(len(pads)):
            for j in range(i + 1, len(pads)):
                dist = sum((pads[i][k] - pads[j][k]) ** 2 for k in range(3)) ** 0.5
                if dist > max_dist:
                    max_dist = dist

        return {
            "avg_pad": {"P": round(avg_p, 4), "A": round(avg_a, 4), "D": round(avg_d, 4)},
            "emotion_distribution": distribution,
            "emotional_volatility": round(max_dist, 4),
            "snapshot_count": n,
        }

    # ============================================================
    # autobiography + reflection CRUD（阶段 5 新增）
    # ============================================================

    async def insert_autobiography(
        self,
        date: str,
        content: str,
        mood_summary: str | None = None,
        key_memories: str | None = None,
        word_count: int = 0,
    ) -> int:
        """写入每日自传体"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            """INSERT OR REPLACE INTO autobiography_entries
               (date, content, word_count, mood_summary, key_memories, created_at, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (date, content, word_count, mood_summary, key_memories, time.time(), self._session_id),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_autobiography(self, date: str | None = None) -> dict | None:
        """获取指定日期或最新的自传体"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        if date:
            cursor = await self._conn.execute(
                "SELECT * FROM autobiography_entries WHERE date=?", (date,)
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM autobiography_entries ORDER BY date DESC LIMIT 1"
            )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_autobiography_list(self, limit: int = 30) -> list[dict]:
        """获取自传体目录（不含正文，轻量）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT date, mood_summary, word_count FROM autobiography_entries ORDER BY date DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def insert_reflection(
        self,
        week_start: str,
        week_end: str,
        learned: str = "",
        surprised: str = "",
        grateful: str = "",
        remember: str = "",
        raw_prompt: str | None = None,
    ) -> int:
        """写入每周反思结晶"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            """INSERT INTO reflection_crystals
               (week_start, week_end, learned, surprised, grateful, remember, raw_prompt, created_at, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (week_start, week_end, learned, surprised, grateful, remember, raw_prompt, time.time(), self._session_id),
        )
        await self._conn.commit()
        return cursor.lastrowid

    async def get_latest_reflection(self) -> dict | None:
        """获取最新的反思结晶"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT * FROM reflection_crystals ORDER BY week_start DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_reflections(self, limit: int = 10) -> list[dict]:
        """获取反思历史"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT * FROM reflection_crystals ORDER BY week_start DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

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
    # autonomy_settings CRUD（阶段 6 新增）
    # ============================================================

    async def get_autonomy_config(self) -> dict | None:
        """读取自主行为配置（单行 JSON）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        import json
        cursor = await self._conn.execute(
            "SELECT value FROM autonomy_settings WHERE key='config'"
        )
        row = await cursor.fetchone()
        if row:
            return json.loads(row[0])
        return None

    async def save_autonomy_config(self, config: dict) -> None:
        """保存自主行为配置（INSERT OR REPLACE）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        import json
        now = time.time()
        await self._conn.execute(
            """INSERT OR REPLACE INTO autonomy_settings (key, value, updated_at)
               VALUES ('config', ?, ?)""",
            (json.dumps(config, ensure_ascii=False), now),
        )
        await self._conn.commit()
        logger.debug("database.autonomy_config_saved")

    # ============================================================
    # notebook CRUD（阶段 7b 新增）
    # ============================================================

    async def insert_notebook(
        self, kind: str, content: str,
        tags: list[str] | None = None, importance: float = 0.5,
        due_date: float | None = None,
    ) -> int:
        """插入一条笔记本条目。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        tags_json = json.dumps(tags, ensure_ascii=False) if tags else None
        cursor = await self._conn.execute(
            """INSERT INTO notebook_entries
               (kind, content, tags, importance, due_date, created_at, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (kind, content, tags_json, importance, due_date, time.time(), self._session_id),
        )
        await self._conn.commit()
        logger.debug("database.insert_notebook", kind=kind, due_date=due_date)
        return cursor.lastrowid

    async def get_notebook_notes(
        self, limit: int = 10, kind: str | None = None,
    ) -> list[dict]:
        """获取最近笔记（默认不过滤 kind）。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        if kind:
            cursor = await self._conn.execute(
                "SELECT * FROM notebook_entries WHERE kind=? AND is_active=1 "
                "ORDER BY created_at DESC LIMIT ?",
                (kind, limit),
            )
        else:
            cursor = await self._conn.execute(
                "SELECT * FROM notebook_entries WHERE is_active=1 "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_notebook_today_diary(self) -> dict | None:
        """获取今日日记（按日期字符串匹配）。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        import datetime
        today = datetime.date.today().isoformat()
        today_start = time.mktime(
            datetime.datetime.combine(
                datetime.date.today(), datetime.time.min
            ).timetuple()
        )
        cursor = await self._conn.execute(
            "SELECT * FROM notebook_entries WHERE kind='diary' AND created_at >= ? "
            "ORDER BY created_at DESC LIMIT 1",
            (today_start,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_notebook_diary_list(self, limit: int = 30) -> list[dict]:
        """获取日记列表（不含正文，轻量）。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            "SELECT id, created_at, "
            "SUBSTR(content, 1, 80) as preview "
            "FROM notebook_entries WHERE kind='diary' AND is_active=1 "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def archive_notebook_entries(self, days: int = 30) -> int:
        """归档旧笔记（> days 天前的标记 is_active=0）。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cutoff = time.time() - days * 86400
        cursor = await self._conn.execute(
            "UPDATE notebook_entries SET is_active=0 WHERE created_at < ?",
            (cutoff,),
        )
        await self._conn.commit()
        return cursor.rowcount

    async def delete_notebook_entry(self, entry_id: int) -> bool:
        """真实删除一条笔记本条目。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            "DELETE FROM notebook_entries WHERE id=?",
            (entry_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def touch_notebook_entry(self, entry_id: int) -> bool:
        """更新笔记时间戳（合并去重时用）。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        await self._conn.execute(
            "UPDATE notebook_entries SET created_at=? WHERE id=?",
            (time.time(), entry_id),
        )
        await self._conn.commit()
        return True

    # ============================================================
    # scheduled_tasks CRUD（阶段 7b 新增）
    # ============================================================

    async def insert_task(
        self, title: str, details: str = "",
        priority: int = 0, due_at: float = 0.0,
    ) -> int:
        """创建计划任务。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            """INSERT INTO scheduled_tasks
               (title, details, priority, due_at, created_at, session_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (title, details, priority, due_at, time.time(), self._session_id),
        )
        await self._conn.commit()
        logger.debug("database.insert_task", title=title[:30])
        return cursor.lastrowid

    async def get_due_tasks(
        self, now: float | None = None, window_seconds: int = 3600,
    ) -> list[dict]:
        """获取到期任务（status=pending 且 due_at 在窗口内）。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        now = now or time.time()
        cursor = await self._conn.execute(
            "SELECT * FROM scheduled_tasks "
            "WHERE status='pending' AND due_at > 0 "
            "AND ABS(due_at - ?) <= ? "
            "ORDER BY priority DESC, due_at ASC",
            (now, window_seconds),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_pending_tasks(self, limit: int = 20) -> list[dict]:
        """获取全部待办任务。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            "SELECT * FROM scheduled_tasks WHERE status='pending' "
            "ORDER BY priority DESC, due_at ASC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def complete_task(self, task_id: int) -> None:
        """标记任务完成。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        await self._conn.execute(
            "UPDATE scheduled_tasks SET status='done', completed_at=? WHERE id=?",
            (time.time(), task_id),
        )
        await self._conn.commit()

    async def cancel_task(self, task_id: int) -> None:
        """取消任务（软删除）。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        await self._conn.execute(
            "UPDATE scheduled_tasks SET status='cancelled', completed_at=? WHERE id=?",
            (time.time(), task_id),
        )
        await self._conn.commit()

    async def delete_task(self, task_id: int) -> bool:
        """硬删除任务。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            "DELETE FROM scheduled_tasks WHERE id=?",
            (task_id,),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    # ============================================================
    # audit_logs CRUD（阶段 8 新增）
    # ============================================================

    async def insert_audit_log(
        self, event_type: str, detail: str = "",
        severity: str = "info", source: str = "system",
        user_id: str = "hezi", trace_id: str = "",
    ) -> int:
        """写入一条审计日志。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            """INSERT INTO audit_logs
               (timestamp, event_type, severity, source, detail, user_id, trace_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (time.time(), event_type, severity, source, detail, user_id, trace_id),
        )
        await self._conn.commit()
        logger.debug("audit.logged", type=event_type, severity=severity)
        return cursor.lastrowid

    async def get_audit_logs(
        self, limit: int = 50, event_type: str | None = None,
        severity: str | None = None,
    ) -> list[dict]:
        """检索审计日志（按时间倒序）。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        conditions = []
        params: list = []
        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        cursor = await self._conn.execute(
            f"SELECT * FROM audit_logs{where} ORDER BY timestamp DESC LIMIT ?",
            params + [limit],
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_audit_stats(self) -> dict:
        """安全统计摘要。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            "SELECT event_type, COUNT(*) as cnt FROM audit_logs "
            "GROUP BY event_type ORDER BY cnt DESC"
        )
        rows = await cursor.fetchall()
        return {
            "total": sum(r[1] for r in rows),
            "by_type": {r[0]: r[1] for r in rows},
        }

    # ============================================================
    # 好感度系统
    # ============================================================

    async def insert_affection_snapshot(
        self, score: float, level: int,
        total_conversations: int, reason: str = "",
    ) -> int:
        """写入一条好感度快照"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            """INSERT INTO affection_state
               (score, level, total_conversations, reason, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (score, level, total_conversations, reason, time.time()),
        )
        await self._conn.commit()
        logger.debug("affection.snapshot", score=score, level=level, reason=reason)
        return cursor.lastrowid

    async def get_latest_affection(self) -> dict | None:
        """获取最新好感度快照"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            "SELECT * FROM affection_state ORDER BY updated_at DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_affection_history(self, limit: int = 50) -> list[dict]:
        """获取好感度历史（按时间倒序）"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")
        cursor = await self._conn.execute(
            "SELECT * FROM affection_state ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ============================================================
    # user_portrait CRUD（阶段 8+: 用户印象文档）
    # ============================================================

    async def insert_portrait(
        self,
        content: str,
        version: int = 1,
        source_ids: str | None = None,
        change_log: str = "",
    ) -> int:
        """写入新版用户印象文档。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            """INSERT INTO user_portrait
               (content, version, source_ids, change_log, created_at, session_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (content, version, source_ids, change_log, time.time(), self._session_id),
        )
        await self._conn.commit()
        logger.debug("database.insert_portrait", version=version, length=len(content))
        return cursor.lastrowid

    async def get_latest_portrait(self) -> dict | None:
        """获取最新版用户印象文档。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT * FROM user_portrait ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row:
            result = dict(row)
            logger.debug("database.get_latest_portrait", id=result.get("id"), version=result.get("version"), content_len=len(result.get("content", "")))
            return result
        logger.debug("database.get_latest_portrait.empty")
        return None

    async def get_portrait_history(self, limit: int = 10) -> list[dict]:
        """获取印象文档版本历史（轻量，不含正文）。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT id, version, change_log, created_at "
            "FROM user_portrait ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_portrait_count(self) -> int:
        """获取印象文档版本总数。"""
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        cursor = await self._conn.execute(
            "SELECT COUNT(*) as cnt FROM user_portrait"
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    # ============================================================
    # 阶段 8: 被遗忘权 — 级联删除
    # ============================================================

    async def forget_user_data(self, user_id: str = "hezi") -> dict:
        """
        级联删除用户所有数据（SQL 事务内完成）。

        删除顺序：
          1. 收集 embedding_id → 删除 sqlite-vec 向量
          2. 删除所有关联表中的数据
          3. 记 audit_log

        Returns:
            {"deleted": {table: count}, "audit_id": int}
        """
        if not self._conn:
            raise RuntimeError("DatabaseManager.init() 未调用")

        deleted = {}

        # 1. 收集 embedding_id 列表（用于向量清理）
        cursor = await self._conn.execute(
            "SELECT embedding_id FROM episodic_memories "
            "WHERE embedding_id IS NOT NULL"
        )
        embed_ids = [row[0] for row in await cursor.fetchall()]

        # 2. 级联删除
        tables = [
            "conversation_logs", "episodic_memories", "message_queue",
            "emotion_snapshots", "affection_state", "notebook_entries",
            "scheduled_tasks", "user_portrait",
        ]
        for table in tables:
            cursor = await self._conn.execute(
                f"DELETE FROM {table}"
            )
            deleted[table] = cursor.rowcount

        # 3. 清理向量存储
        if embed_ids:
            try:
                import sqlite3 as _sync_sqlite
                vec_conn = _sync_sqlite.connect(str(self.db_path))
                for eid in embed_ids:
                    vec_conn.execute(
                        "DELETE FROM memories_vec WHERE rowid = ?", (eid,)
                    )
                vec_conn.commit()
                vec_conn.close()
                deleted["memories_vec"] = len(embed_ids)
            except Exception as e:
                logger.warning("forget.vec_cleanup_failed", error=str(e))

        # 4. 记审计
        await self._conn.commit()
        await self.insert_audit_log(
            "forgotten",
            f"user={user_id} deleted={str(deleted)}",
            severity="warning",
        )

        logger.info("privacy.forgotten", deleted=deleted)
        return {"deleted": deleted}
    # ============================================================

    @property
    def conn(self):
        """aiosqlite 连接（供 VectorStore 等复用）"""
        if self._conn is None:
            raise RuntimeError("DatabaseManager.init() 未调用")
        return self._conn

    @property
    def session_id(self) -> str:
        """当前会话标识"""
        return self._session_id
