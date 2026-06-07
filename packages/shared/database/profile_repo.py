"""ProfileRepository — 用户画像 CRUD（L0 核心 + L1 阶段 + 旧表兼容）"""

import json
import time

from ._base import BaseRepository


class ProfileRepository(BaseRepository):
    """用户画像领域 Repository。管理 core_profile、phase_profile、user_portrait 三张表。"""

    async def insert_core_profile(
        self, content: str, version: int = 1,
        source_l1_ids: str = "", stable_traits: str = "", change_log: str = "",
    ) -> int:
        """写入新版 L0 核心画像。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            """INSERT INTO core_profile
               (content, version, source_l1_ids, stable_traits, change_log, created_at, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (content, version, source_l1_ids, stable_traits, change_log, time.time(), self._session_id),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_latest_core_profile(self) -> dict | None:
        """获取最新 L0 核心画像。"""
        conn = self._ensure_conn()
        cursor = await conn.execute("SELECT * FROM core_profile ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_core_profile_history(self, limit: int = 5) -> list[dict]:
        """获取 L0 核心画像版本历史。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT id, version, stable_traits, change_log, created_at FROM core_profile ORDER BY id DESC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def insert_phase_profile(
        self, content: str, version: int = 1, source_event_ids: str = "",
        active_topics: str = "[]", faded_topics: str = "[]", change_log: str = "",
    ) -> int:
        """写入新版 L1 阶段画像。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            """INSERT INTO phase_profile
               (content, version, source_event_ids, active_topics, faded_topics,
                change_log, created_at, session_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (content, version, source_event_ids, active_topics, faded_topics, change_log,
             time.time(), self._session_id),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_latest_phase_profile(self) -> dict | None:
        """获取最新 L1 阶段画像。"""
        conn = self._ensure_conn()
        cursor = await conn.execute("SELECT * FROM phase_profile ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_phase_profile_history(self, limit: int = 10) -> list[dict]:
        """获取 L1 阶段画像版本历史。"""
        conn = self._ensure_conn()
        cursor = await conn.execute("SELECT * FROM phase_profile ORDER BY id DESC LIMIT ?", (limit,))
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def insert_portrait(
        self, content: str, source_ids: str = "", change_log: str = "",
    ) -> int:
        """写入旧版用户画像（兼容）。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            """INSERT INTO user_portrait (content, version, source_ids, change_log, created_at, session_id)
               VALUES (?, 1, ?, ?, ?, ?)""",
            (content, source_ids, change_log, time.time(), self._session_id),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_latest_portrait(self) -> dict | None:
        """兼容读取：优先 core_profile，回退 user_portrait。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT content, version, created_at, change_log, stable_traits FROM core_profile ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row:
            return {"content": row["content"], "version": row["version"], "created_at": row["created_at"],
                    "change_log": row["change_log"] or "", "stable_traits": row["stable_traits"] or ""}
        cursor = await conn.execute(
            "SELECT content, version, created_at, change_log FROM user_portrait ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if row:
            return {"content": row["content"], "version": row["version"], "created_at": row["created_at"],
                    "change_log": row["change_log"] or ""}
        return None
