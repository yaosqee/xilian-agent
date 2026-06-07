"""AnalyticsRepository — 画像管道数据源（微事件 + 会话摘要 + 工具使用）"""

import json
import time

from ._base import BaseRepository


class AnalyticsRepository(BaseRepository):
    """画像分析数据源 Repository。管理 micro_events、session_summaries、tool_usage_log。"""

    # ── 微事件 ──

    async def insert_micro_event(
        self, content: str, category: str = "fact", confidence: float = 0.5,
        source_ids: str = "",
    ) -> int:
        """写入一条微事件。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            """INSERT INTO micro_events (content, category, confidence, source_ids, is_active, created_at, session_id)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (content, category, confidence, source_ids, time.time(), self._session_id),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_active_micro_events(self, limit: int = 30) -> list[dict]:
        """获取活跃的微事件。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM micro_events WHERE is_active=1 ORDER BY created_at DESC LIMIT ?", (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def consume_micro_events(
        self, event_ids: list[int], target: str = "",
    ) -> int:
        """消费（标记 absorbed）一批微事件。"""
        conn = self._ensure_conn()
        if not event_ids:
            return 0
        placeholders = ",".join("?" for _ in event_ids)
        sql = f"UPDATE micro_events SET is_active=0, absorbed_to=? WHERE id IN ({placeholders})"
        cursor = await conn.execute(sql, [target] + event_ids)
        await conn.commit()
        return cursor.rowcount

    # ── 会话摘要 ──

    async def insert_session_summary(
        self, content: str, source_event_ids: str = "",
    ) -> int:
        """写入一条 L2 会话摘要。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            """INSERT INTO session_summaries (content, source_event_ids, created_at, session_id)
               VALUES (?, ?, ?, ?)""",
            (content, source_event_ids, time.time(), self._session_id),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_recent_session_summaries(self, limit: int = 10) -> list[dict]:
        """获取最近的 L2 会话摘要。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM session_summaries ORDER BY created_at DESC LIMIT ?", (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # ── 工具使用 ──

    async def insert_tool_usage(
        self, tool_name: str, arguments: str = "", success: bool = True,
    ) -> int:
        """写入工具调用日志。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            """INSERT INTO tool_usage_log (tool_name, arguments, success, created_at, session_id)
               VALUES (?, ?, ?, ?, ?)""",
            (tool_name, arguments, 1 if success else 0, time.time(), self._session_id),
        )
        await conn.commit()
        return cursor.lastrowid

    async def query_recent_tool_usage(self, cutoff: float) -> list[dict]:
        """查询最近 N 天的工具使用记录。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT tool_name, COUNT(*) as cnt FROM tool_usage_log "
            "WHERE created_at >= ? GROUP BY tool_name ORDER BY cnt DESC",
            (cutoff,),
        )
        rows = await cursor.fetchall()
        return [{"tool_name": r["tool_name"], "count": r["cnt"]} for r in rows]
