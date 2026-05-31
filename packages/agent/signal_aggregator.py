"""
SignalAggregator — 多信号源聚合器

Phase 4 核心交付。从各表中提取行为模式信号，
所有方法均为轻量 SQL 查询 + 简单统计，不调 LLM。
LLM 消费在粗粒化 prompt 中进行。

信号源：
  1. 工具使用摘要（tool_usage_log 表）
  2. 情绪轨迹（emotion_snapshots 表）
  3. 对话时间模式（conversation_logs 表）
  4. 好感度趋势（affection_state 表）
  5. 跨会话话题延续（micro_events 表）
"""
import time
from collections import Counter
from dataclasses import dataclass
from typing import Optional

from loguru import logger


# ═══════════════════════════════════════════════════════════
# SignalSnapshot
# ═══════════════════════════════════════════════════════════

@dataclass
class SignalSnapshot:
    """多信号源聚合快照 — 供粗粒化引擎消费。空字符串表示数据不足/无有意义信号。"""
    generated_at: float = 0.0
    tool_usage: str = ""
    emotion_trajectory: str = ""
    time_pattern: str = ""
    affection_trend: str = ""
    session_boundaries: str = ""


# ═══════════════════════════════════════════════════════════
# SignalAggregator
# ═══════════════════════════════════════════════════════════

@dataclass
class SignalAggregator:
    """
    多信号源聚合器 — 从各表中提取行为模式信号。

    所有方法均为轻量 SQL 查询 + 简单统计，不调 LLM。
    LLM 消费在粗粒化 prompt 中进行。
    """

    _db: object  # DatabaseManager

    async def aggregate(self, days: int = 7) -> SignalSnapshot:
        """聚合最近 N 天的所有信号。各信号源独立降级。"""
        return SignalSnapshot(
            generated_at=time.time(),
            tool_usage=await self._summarize_tool_usage(days),
            emotion_trajectory=await self._summarize_emotion_trajectory(days),
            time_pattern=await self._summarize_time_pattern(days),
            affection_trend=await self._summarize_affection_trend(),
            session_boundaries=await self._summarize_session_boundaries(days),
        )

    # ═══════════════════════════════════════════════════════
    # 1. 工具使用摘要
    # ═══════════════════════════════════════════════════════

    async def _summarize_tool_usage(self, days: int) -> str:
        """从 tool_usage_log 表提取工具调用模式。"""
        try:
            cutoff = time.time() - days * 86400
            rows = await self._db.query_recent_tool_usage(cutoff)
            if not rows:
                return ""

            tool_counts: dict[str, int] = {}
            for r in rows:
                name = r.get("tool_name", "unknown")
                tool_counts[name] = tool_counts.get(name, 0) + 1

            parts = [f"{name}{count}次" for name, count in tool_counts.items()]
            return f"最近{days}天使用了：{'、'.join(parts)}" if parts else ""
        except Exception as e:
            logger.debug("signal.tool_usage_failed", error=str(e))
            return ""

    # ═══════════════════════════════════════════════════════
    # 2. 情绪轨迹
    # ═══════════════════════════════════════════════════════

    async def _summarize_emotion_trajectory(self, days: int) -> str:
        """从 emotion_snapshots 表提取情绪轨迹。SQL 时间过滤，避免 Python 侧丢弃。"""
        try:
            recent = await self._db.get_emotion_snapshots_recent(days=days, limit=200)
            if not recent or len(recent) < 3:
                return ""

            # 主导情绪分布
            emotions = [s.get("primary_emotion") for s in recent if s.get("primary_emotion")]
            if not emotions:
                return ""

            top_emotions = Counter(emotions).most_common(3)
            parts = [f"{e}{c}次" for e, c in top_emotions]

            # PAD 均值
            avg_p = sum(s.get("pad_p", 0) or 0 for s in recent) / len(recent)
            avg_a = sum(s.get("pad_a", 0) or 0 for s in recent) / len(recent)

            p_desc = "偏积极" if avg_p > 0.2 else ("偏消极" if avg_p < -0.2 else "中性")
            a_desc = "高唤醒" if avg_a > 0.2 else ("低唤醒" if avg_a < -0.2 else "中性")

            return (
                f"最近{days}天情绪以{'、'.join(parts)}为主，"
                f"整体{p_desc}、{a_desc}"
            )
        except Exception as e:
            logger.debug("signal.emotion_trajectory_failed", error=str(e))
            return ""

    # ═══════════════════════════════════════════════════════
    # 3. 对话时间模式
    # ═══════════════════════════════════════════════════════

    async def _summarize_time_pattern(self, days: int) -> str:
        """从 conversation_logs 分析对话时间模式。"""
        try:
            cutoff = time.time() - days * 86400
            rows = await self._db.query_conversation_times(cutoff)
            if not rows:
                return ""

            # 按小时分组统计
            hour_counts: dict[int, int] = {}
            total = 0
            for r in rows:
                ts = r.get("timestamp", 0)
                if ts > 0:
                    import datetime
                    hour = datetime.datetime.fromtimestamp(ts).hour
                    hour_counts[hour] = hour_counts.get(hour, 0) + 1
                    total += 1

            if total < 3:
                return ""

            # Top-3 活跃时段
            top_hours = sorted(hour_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            period_names = {
                0: "凌晨", 1: "凌晨", 2: "凌晨", 3: "凌晨", 4: "凌晨", 5: "凌晨",
                6: "早上", 7: "早上", 8: "早上",
                9: "上午", 10: "上午", 11: "上午",
                12: "中午", 13: "中午",
                14: "下午", 15: "下午", 16: "下午", 17: "下午",
                18: "晚上", 19: "晚上", 20: "晚上", 21: "晚上",
                22: "深夜", 23: "深夜",
            }
            periods = [f"{period_names.get(h, str(h)+'点')}{h}点" for h, _ in top_hours]

            return f"最近{days}天共{total}条消息，活跃时段集中在{'、'.join(periods)}"
        except Exception as e:
            logger.debug("signal.time_pattern_failed", error=str(e))
            return ""

    # ═══════════════════════════════════════════════════════
    # 4. 好感度趋势
    # ═══════════════════════════════════════════════════════

    async def _summarize_affection_trend(self) -> str:
        """好感度变化趋势。"""
        try:
            latest = await self._db.get_latest_affection()
            if not latest:
                return ""

            level = latest.get("level", 1)
            score = latest.get("score", 0)
            level_names = {1: "初识", 2: "亲近", 3: "亲密", 4: "至交"}
            level_name = level_names.get(level, "未知")
            return f"好感度{level_name}（{score:.1f}分）"
        except Exception as e:
            logger.debug("signal.affection_trend_failed", error=str(e))
            return ""

    # ═══════════════════════════════════════════════════════
    # 5. 跨会话话题延续
    # ═══════════════════════════════════════════════════════

    async def _summarize_session_boundaries(self, days: int) -> str:
        """
        识别跨会话持久话题。
        从 micro_events 中查找同一 content 前缀出现在 2+ 个不同 session 的事件。
        """
        try:
            cutoff = time.time() - days * 86400
            rows = await self._db.query_cross_session_topics(cutoff)
            if not rows:
                return ""

            topics = []
            for r in rows[:3]:
                variants = r.get("variants", "")
                first_variant = variants.split(" | ")[0] if " | " in variants else variants
                session_count = r.get("session_count", 0)
                topics.append(f"「{first_variant}」（跨{session_count}个会话）")

            return f"跨会话的持久话题：{'、'.join(topics)}" if topics else ""
        except Exception as e:
            logger.debug("signal.session_boundaries_failed", error=str(e))
            return ""
