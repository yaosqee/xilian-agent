"""
ConversationRepository — 对话日志 CRUD

管理 conversation_logs 表的所有读写操作。
事务由 DatabaseManager 统一管理，Repository 不自行 commit()。
"""

import json
import time
from typing import Optional

from loguru import logger

from ._base import BaseRepository


class ConversationRepository(BaseRepository):
    """对话日志领域 Repository。"""

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
        images: list[str] | None = None,
    ) -> int:
        """
        写入一条对话记录。

        Returns:
            新插入行的 id
        """
        conn = self._ensure_conn()

        emotion_json = json.dumps(emotion_label, ensure_ascii=False) if emotion_label else None
        images_json = json.dumps(images, ensure_ascii=False) if images else "[]"

        cursor = await conn.execute(
            """INSERT INTO conversation_logs
               (timestamp, session_id, event_id, user_message, assistant_reply,
                emotion_label, emotion_primary, emotion_intensity, user_id, source, images)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                images_json,
            ),
        )
        await conn.commit()

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
        conn = self._ensure_conn()

        cursor = await conn.execute(
            "SELECT * FROM conversation_logs ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_by_session(self, session_id: str, limit: int = 100) -> list[dict]:
        """按 session_id 查询对话记录"""
        conn = self._ensure_conn()

        cursor = await conn.execute(
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
        conn = self._ensure_conn()

        if before_id:
            cursor = await conn.execute(
                "SELECT * FROM conversation_logs WHERE id < ? AND user_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (before_id, user_id, limit),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM conversation_logs WHERE user_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (user_id, limit),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_conversation_total(self, user_id: str = "hezi") -> int:
        """获取历史对话总轮数"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT COUNT(*) as cnt FROM conversation_logs WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        return row["cnt"] if row else 0

    async def clear_conversation_logs(self, user_id: str = "hezi") -> int:
        """清空对话日志（重置会话时调用）"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "DELETE FROM conversation_logs WHERE user_id = ?",
            (user_id,),
        )
        await conn.commit()
        return cursor.rowcount

    async def get_emotion_history(self, limit: int = 50) -> list[dict]:
        """查询有情绪标注的记录（用于情绪趋势）"""
        conn = self._ensure_conn()

        cursor = await conn.execute(
            "SELECT timestamp, emotion_primary, emotion_intensity, emotion_label "
            "FROM conversation_logs "
            "WHERE emotion_primary IS NOT NULL "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
