"""NotebookRepository — 笔记本 + 任务管理"""

import json
import time

from ._base import BaseRepository


class NotebookRepository(BaseRepository):
    """笔记本领域 Repository。管理 notebook_entries + scheduled_tasks 表。"""

    async def insert_notebook(
        self, kind: str, content: str, tags: str = "", importance: float = 0.5,
    ) -> int:
        """写入一条笔记/关注/日记。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            """INSERT INTO notebook_entries (kind, content, tags, importance, is_active, created_at, session_id)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (kind, content, tags, importance, time.time(), self._session_id),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_notebook_notes(
        self, kind: str | None = None, limit: int = 20, offset: int = 0,
    ) -> list[dict]:
        """查询笔记（可按 kind 过滤）。"""
        conn = self._ensure_conn()
        if kind:
            cursor = await conn.execute(
                "SELECT * FROM notebook_entries WHERE kind=? AND is_active=1 ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (kind, limit, offset),
            )
        else:
            cursor = await conn.execute(
                "SELECT * FROM notebook_entries WHERE is_active=1 ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def get_notebook_today_diary(self) -> dict | None:
        """获取今日日记。"""
        import datetime
        conn = self._ensure_conn()
        today = datetime.date.today().isoformat()
        cursor = await conn.execute(
            "SELECT * FROM notebook_entries WHERE kind='diary' AND is_active=1 "
            "AND DATE(created_at, 'unixepoch')=? ORDER BY created_at DESC LIMIT 1",
            (today,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def delete_notebook_entry(self, entry_id: int) -> bool:
        """软删除笔记。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "UPDATE notebook_entries SET is_active=0 WHERE id=?", (entry_id,),
        )
        await conn.commit()
        return cursor.rowcount > 0

    async def touch_notebook_entry(self, entry_id: int) -> bool:
        """更新笔记时间戳。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "UPDATE notebook_entries SET created_at=? WHERE id=?", (time.time(), entry_id),
        )
        await conn.commit()
        return cursor.rowcount > 0

    # ── 任务管理 ──

    async def insert_task(self, title: str, details: str = "", priority: int = 0,
                          due_at: float | None = None) -> int:
        """写入一条待办任务。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            """INSERT INTO scheduled_tasks (title, details, priority, status, due_at, created_at, session_id)
               VALUES (?, ?, ?, 'pending', ?, ?, ?)""",
            (title, details, priority, due_at, time.time(), self._session_id),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_pending_tasks(self, limit: int = 20) -> list[dict]:
        """获取待办任务列表。"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM scheduled_tasks WHERE status='pending' ORDER BY priority DESC, due_at ASC LIMIT ?",
            (limit,),
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def complete_task(self, task_id: int) -> None:
        """标记任务完成。"""
        conn = self._ensure_conn()
        await conn.execute(
            "UPDATE scheduled_tasks SET status='completed', completed_at=? WHERE id=?",
            (time.time(), task_id),
        )
        await conn.commit()

    async def cancel_task(self, task_id: int) -> None:
        """取消任务。"""
        conn = self._ensure_conn()
        await conn.execute(
            "UPDATE scheduled_tasks SET status='cancelled' WHERE id=?", (task_id,),
        )
        await conn.commit()

    async def delete_task(self, task_id: int) -> bool:
        """删除任务。"""
        conn = self._ensure_conn()
        cursor = await conn.execute("DELETE FROM scheduled_tasks WHERE id=?", (task_id,))
        await conn.commit()
        return cursor.rowcount > 0
