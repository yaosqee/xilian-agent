"""
EmotionRepository — PAD 情绪快照 CRUD

管理 emotion_snapshots 表的所有读写操作。
"""

import json
import time
from typing import Optional
from collections import Counter

from ._base import BaseRepository


class EmotionRepository(BaseRepository):
    """PAD 情绪快照领域 Repository。"""

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
        trigger_memory_id: int | None = None,
    ) -> int:
        """写入一条情感快照"""
        conn = self._ensure_conn()

        dims_json = json.dumps(dimensions, ensure_ascii=False) if dimensions else None

        cursor = await conn.execute(
            """INSERT INTO emotion_snapshots
               (timestamp, pad_p, pad_a, pad_d,
                primary_emotion, primary_intensity, dimensions_json,
                appraisal_relevance, appraisal_facilitation, appraisal_coping,
                source, session_id, trace_id, trigger_memory_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                time.time(),
                pad_p, pad_a, pad_d,
                primary_emotion, primary_intensity, dims_json,
                appraisal_relevance, appraisal_facilitation, appraisal_coping,
                source, self._session_id, trace_id,
                trigger_memory_id,
            ),
        )
        await conn.commit()
        return cursor.lastrowid

    async def get_latest_emotion(self) -> dict | None:
        """获取最新的情感快照"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM emotion_snapshots ORDER BY timestamp DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_emotion_snapshots(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict]:
        """按时间倒序查询情感快照历史"""
        conn = self._ensure_conn()
        cursor = await conn.execute(
            "SELECT * FROM emotion_snapshots ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_emotion_snapshots_recent(
        self, days: int = 7, limit: int = 200
    ) -> list[dict]:
        """查询最近 N 天的情感快照（SQL 时间过滤）"""
        conn = self._ensure_conn()
        cutoff = time.time() - days * 86400
        cursor = await conn.execute(
            "SELECT * FROM emotion_snapshots "
            "WHERE timestamp >= ? "
            "ORDER BY timestamp DESC LIMIT ?",
            (cutoff, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def get_emotions_by_memory_ids(
        self, memory_ids: list[int],
    ) -> dict[int, dict]:
        """批量查询记忆条目关联的情绪快照。返回 {memory_id: {emotion, pad_p, pad_a, pad_d}}。"""
        conn = self._ensure_conn()
        if not memory_ids:
            return {}

        placeholders = ",".join("?" for _ in memory_ids)
        sql = f"SELECT trigger_memory_id, primary_emotion, pad_p, pad_a, pad_d, timestamp FROM emotion_snapshots WHERE trigger_memory_id IN ({placeholders}) ORDER BY timestamp DESC"
        cursor = await conn.execute(sql, memory_ids)
        rows = await cursor.fetchall()
        result: dict[int, dict] = {}
        for row in rows:
            row_d = dict(row)
            mid = row_d["trigger_memory_id"]
            if mid and mid not in result:
                result[mid] = {
                    "emotion": row_d["primary_emotion"],
                    "pad_p": row_d["pad_p"],
                    "pad_a": row_d["pad_a"],
                    "pad_d": row_d["pad_d"],
                }
        return result

    async def get_emotion_stats(self, days: int = 7) -> dict:
        """获取情绪统计摘要"""
        conn = self._ensure_conn()
        cutoff = time.time() - days * 86400
        cursor = await conn.execute(
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

        emotions = [r["primary_emotion"] for r in records if r["primary_emotion"]]
        distribution = {k: v / n for k, v in Counter(emotions).most_common()}

        # 情绪波动率：近似最大 PAD 距离（O(n)）
        pads = [(r["pad_p"], r["pad_a"], r["pad_d"]) for r in records]
        cx = sum(p[0] for p in pads) / n
        cy = sum(p[1] for p in pads) / n
        cz = sum(p[2] for p in pads) / n
        max_dist = 0.0
        for p in pads:
            d = ((p[0] - cx) ** 2 + (p[1] - cy) ** 2 + (p[2] - cz) ** 2) ** 0.5
            if d > max_dist:
                max_dist = d
        max_dist *= 2.0

        return {
            "avg_pad": {"P": round(avg_p, 4), "A": round(avg_a, 4), "D": round(avg_d, 4)},
            "emotion_distribution": distribution,
            "emotional_volatility": round(max_dist, 4),
            "snapshot_count": n,
        }
