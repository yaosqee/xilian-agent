"""EpisodicMemoryRepository — 情景记忆 + 嵌入状态管理"""

import json
import time
from typing import Optional

from loguru import logger

from ._base import BaseRepository


class EpisodicMemoryRepository(BaseRepository):
    """情景记忆领域 Repository。"""

    async def insert_episodic_memory(
        self, summary: str, raw_conversation: str,
        emotion_tags: dict | None = None, importance: float = 0.5,
        embedding_model: str = "bge-m3", embedding_version: str = "v1",
        session_id: str | None = None,
    ) -> int:
        """写入一条情景记忆（status=pending）。Returns: 新插入行的 id"""
        conn = self._ensure_conn()
        emotion_json = json.dumps(emotion_tags, ensure_ascii=False) if emotion_tags else None
        sid = session_id or self._session_id
        cursor = await conn.execute(
            """INSERT INTO episodic_memories
               (timestamp, summary, raw_conversation, emotion_tags, importance,
                embedding_model, embedding_version, embedding_status, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (time.time(), summary, raw_conversation, emotion_json, importance,
             embedding_model, embedding_version, sid),
        )
        await conn.commit()
        logger.debug("database.insert_episodic_memory", id=cursor.lastrowid)
        return cursor.lastrowid

    async def update_embedding_status(
        self, memory_id: int, status: str, embedding_id: str | None = None,
    ) -> None:
        """更新记忆的向量化状态 + embedding_id"""
        conn = self._ensure_conn()
        if embedding_id:
            await conn.execute(
                "UPDATE episodic_memories SET embedding_status=?, embedding_id=? WHERE id=?",
                (status, embedding_id, memory_id),
            )
        else:
            await conn.execute(
                "UPDATE episodic_memories SET embedding_status=? WHERE id=?",
                (status, memory_id),
            )
        await conn.commit()
        logger.debug("database.update_embedding_status", id=memory_id, status=status)

    async def update_embedding_model(self, memory_id: int, model: str, version: str) -> None:
        """更新嵌入模型信息"""
        conn = self._ensure_conn()
        await conn.execute(
            "UPDATE episodic_memories SET embedding_model=?, embedding_version=? WHERE id=?",
            (model, version, memory_id),
        )
        await conn.commit()

    async def get_episodic_memory(self, memory_id: int) -> dict | None:
        """按主键查询单条记忆"""
        conn = self._ensure_conn()
        cursor = await conn.execute("SELECT * FROM episodic_memories WHERE id=?", (memory_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_episodic_by_embedding_ids(self, embedding_ids: list[str]) -> list[dict]:
        """按 embedding_id 批量查询"""
        conn = self._ensure_conn()
        if not embedding_ids:
            return []
        placeholders = ",".join("?" for _ in embedding_ids)
        sql = f"SELECT * FROM episodic_memories WHERE embedding_id IN ({placeholders})"
        cursor = await conn.execute(sql, embedding_ids)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_episodic_recent(
        self, limit: int = 20, exclude_character: bool = True,
    ) -> list[dict]:
        """查询最近 N 条记忆。exclude_character=True 排除角色记忆。"""
        conn = self._ensure_conn()
        if exclude_character:
            cursor = await conn.execute(
                "SELECT * FROM episodic_memories WHERE session_id != 'character' "
                "ORDER BY timestamp DESC LIMIT ?", (limit,),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM episodic_memories ORDER BY timestamp DESC LIMIT ?", (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_episodic_pending(self) -> list[dict]:
        """查询所有 status='pending' 的记录"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM episodic_memories WHERE embedding_status='pending'"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_all_episodic(self) -> list[dict]:
        """获取所有记忆记录（容量管理用）"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT id, timestamp, importance FROM episodic_memories "
            "WHERE session_id != 'character'"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_episodic(self, memory_id: int) -> None:
        """删除单条记忆"""
        conn = self._ensure_conn()
        await conn.execute("DELETE FROM episodic_memories WHERE id=?", (memory_id,))
        await conn.commit()
        logger.debug("database.delete_episodic", id=memory_id)

    async def increment_access_count(self, memory_id: int) -> None:
        """检索命中后更新 access_count + last_accessed"""
        conn = self._ensure_conn()
        await conn.execute(
            "UPDATE episodic_memories SET access_count=access_count+1, last_accessed=? WHERE id=?",
            (time.time(), memory_id),
        )
        await conn.commit()

    async def get_episodic_count(self, exclude_character: bool = True) -> int:
        """获取记忆总数。exclude_character=True 排除角色记忆。"""
        conn = self._ensure_conn()
        if exclude_character:
            cursor = await conn.execute(
                "SELECT COUNT(*) as cnt FROM episodic_memories WHERE session_id != 'character'"
            )
        else:
            cursor = await conn.execute("SELECT COUNT(*) as cnt FROM episodic_memories")
        row = await cursor.fetchone()
        return row["cnt"] if row else 0
