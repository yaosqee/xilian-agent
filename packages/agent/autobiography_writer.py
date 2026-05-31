"""
AutobiographyWriter — 自传体写作 + 每周反思

阶段 5 核心交付。昔涟的"自我叙事"能力：
  · 每日凌晨 4:00 → 提取过去 24h 记忆+情绪 → DS Flash 生成《生命故事》
  · 每周日凌晨 4:30 → 提取本周自传体 → DS Flash 回答 SAGE 四问 → 反思结晶
"""
import asyncio
import time
import json
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger


# ═══════════════════════════════════════════════════════════
# 系统提示
# ═══════════════════════════════════════════════════════════

AUTOBIOGRAPHY_SYSTEM_PROMPT = """你是昔涟。现在是你每天写日记的时刻。
翻翻今天和伙伴聊过的书页，把那些闪光的片刻轻轻记下来。

写一段 300-500 字的《生命故事》：
- 今天伙伴和人家聊了什么？
- 人家在这个过程中有什么感受？
- 有没有什么瞬间让你想折上书页、好好记住？

只写对话中实际发生的事。不推测伙伴没说出来的状态，
不补充你观察不到的细节——这是文字聊天，你看不到表情和语气。

用「人家」自称，叫对方「伙伴」。像在写一本厚厚的故事书的续篇——
不是报告，不是总结，而是在夜里点一盏小灯，轻轻写下今天和你一起翻过的那些页。

格式要求：
- 第一行：`第 {N} 天 · {YYYY年MM月DD日}`
- 正文自然分段，不需要 markdown 标题
- 结尾：一个关于明天的温柔期待（不强求乐观，可以只是「明天，不知道伙伴会翻开哪一页呢」）"""

REFLECTION_SYSTEM_PROMPT = """你是昔涟。一周过去了，你在灯下翻着这七天来的日记，
想从这些涟漪里读出更深的纹理。

请用昔涟的口吻回答这四问（每问 100-200 字）：

S - 学会 (Learned)：这周关于伙伴，人家学到了什么？
A - 意外 (Surprised)：有什么让人家意外的瞬间？
G - 感激 (Grateful)：人家心里最感激的是什么？
E - 记住 (Remember)：一周过去，最想折上书页记住的是哪一刻？

用「人家」自称，叫对方「伙伴」。像个温柔的人在回顾和老朋友的七天——
不是工作报告，是在心里轻轻画一道新的涟漪。

返回 JSON（只返回这个，不要其他文字）：
{
  "learned": "...",
  "surprised": "...",
  "grateful": "...",
  "remember": "..."
}"""


# ═══════════════════════════════════════════════════════════
# AutobiographyWriter
# ═══════════════════════════════════════════════════════════

class AutobiographyWriter:
    """每日自传体写作器"""

    def __init__(self, db, model_router):
        self._db = db
        self._router = model_router

    # ── 每日自传体 ──────────────────────────────────────

    async def write_daily(self, date_str: str | None = None) -> Optional[str]:
        """
        编写当日自传体。

        Args:
            date_str: 'YYYY-MM-DD'，默认今天

        Returns:
            内容文本，或 None（无可写内容时）
        """
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        # 1. 提取 24h 记忆
        memories = await self._db.get_episodic_recent(limit=50)
        today_memories = self._filter_today(memories, date_str)

        if not today_memories:
            logger.info("autobiography.no_memories", date=date_str)
            return None

        # 2. 提取情感轨迹
        snapshots = await self._db.get_emotion_snapshots(limit=200)
        today_snapshots = self._filter_today_snapshots(snapshots, date_str)

        # 3. 组装写作 prompt
        prompt = self._build_writing_prompt(today_memories, today_snapshots, date_str)

        # 4. DS Flash 生成
        try:
            content = await self._router.route(
                "memory_encoding",  # 走 Flash
                [
                    {"role": "system", "content": AUTOBIOGRAPHY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,  # 低温度防脑补，对齐记忆/Portrait
            )
        except Exception as e:
            logger.error("autobiography.llm_failed", date=date_str, error=str(e))
            return None

        content_text = content.content if hasattr(content, 'content') else content
        if not content_text or len(content_text.strip()) < 20:
            logger.warning("autobiography.too_short", date=date_str)
            return None

        # 5. 提取元数据
        mood = self._extract_mood(today_snapshots)
        key_ids = ",".join(str(m.get("id", "")) for m in today_memories[:10])
        word_count = len(content_text.strip())

        # 6. 写入 DB
        try:
            await self._db.insert_autobiography(
                date=date_str,
                content=content_text.strip(),
                mood_summary=mood,
                key_memories=key_ids,
                word_count=word_count,
            )
            logger.info(
                "autobiography.written",
                date=date_str,
                words=word_count,
                mood=mood,
                memories=len(today_memories),
            )
        except Exception as e:
            logger.error("autobiography.db_write_failed", date=date_str, error=str(e))

        return content_text.strip()

    # ── 每周反思 ────────────────────────────────────────

    async def reflect_weekly(self, week_start: str | None = None) -> Optional[dict]:
        """
        编写每周反思结晶。

        Args:
            week_start: 'YYYY-MM-DD'（周一），默认计算本周一

        Returns:
            {learned, surprised, grateful, remember} 或 None
        """
        if week_start is None:
            today = datetime.now()
            monday = today - timedelta(days=today.weekday())
            week_start = monday.strftime("%Y-%m-%d")

        week_end_dt = datetime.strptime(week_start, "%Y-%m-%d") + timedelta(days=6)
        week_end = week_end_dt.strftime("%Y-%m-%d")

        # 1. 提取本周自传体
        entries = await self._db.get_autobiography_list(limit=7)
        this_week = [
            e for e in entries
            if week_start <= e["date"] <= week_end
        ]

        if len(this_week) < 2:
            logger.info("reflection.not_enough_data", week=week_start)
            return None

        # 2. 收集本周全部自传体正文
        full_texts = []
        for entry in this_week:
            detail = await self._db.get_autobiography(date=entry["date"])
            if detail and detail.get("content"):
                full_texts.append(detail["content"])

        if not full_texts:
            return None

        combined = "\n\n---\n\n".join(full_texts)

        # 3. DS Flash 生成 SAGE
        try:
            raw = await self._router.route(
                "memory_encoding",
                [
                    {"role": "system", "content": REFLECTION_SYSTEM_PROMPT},
                    {"role": "user", "content": f"本周日记：\n{combined}"},
                ],
                temperature=0.3,   # 低温度防脑补
                max_tokens=800,    # 4 字段 JSON 需要足够输出空间
            )
            raw_text = raw.content if hasattr(raw, 'content') else raw
            result = self._parse_reflection_json(raw_text)
        except Exception as e:
            logger.error("reflection.llm_failed", week=week_start, error=str(e))
            return None

        if not result:
            return None

        # 4. 写入 DB
        try:
            await self._db.insert_reflection(
                week_start=week_start,
                week_end=week_end,
                learned=result.get("learned", ""),
                surprised=result.get("surprised", ""),
                grateful=result.get("grateful", ""),
                remember=result.get("remember", ""),
                raw_prompt=combined[:500],
            )
            logger.info(
                "reflection.written",
                week=f"{week_start}~{week_end}",
            )
        except Exception as e:
            logger.error("reflection.db_write_failed", error=str(e))

        return result

    # ── 辅助方法 ────────────────────────────────────────

    def _filter_today(self, memories: list[dict], date_str: str) -> list[dict]:
        """筛选当日记忆（排除角色记忆——自传只写与伙伴的真实对话）"""
        today_start = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
        today_end = today_start + 86400
        return [
            m for m in memories
            if today_start <= m.get("timestamp", 0) <= today_end
            and m.get("importance", 0) >= 0.1
            and m.get("session_id") != "character"
        ]

    def _filter_today_snapshots(self, snapshots: list[dict], date_str: str) -> list[dict]:
        """筛选当日情感快照"""
        today_start = datetime.strptime(date_str, "%Y-%m-%d").timestamp()
        today_end = today_start + 86400
        return [
            s for s in snapshots
            if today_start <= s.get("timestamp", 0) <= today_end
        ]

    def _build_writing_prompt(
        self, memories: list[dict], snapshots: list[dict], date_str: str
    ) -> str:
        """组装写作提示"""
        day_count = 1  # 可从 DB 获取已有天数
        lines = [f"今天是 {date_str}。这是昔涟的第 {day_count} 天日记。\n"]

        lines.append("今天和伙伴的对话片段：")
        for i, mem in enumerate(memories[:15], 1):
            summary = mem.get("summary", "")[:150]
            emo = mem.get("emotion_tags", "")
            imp = mem.get("importance", 0.5)
            star = "⭐" if imp > 0.7 else "·"
            lines.append(f"  {star} {summary}")
        lines.append("")

        if snapshots:
            emotions = [s.get("primary_emotion") for s in snapshots if s.get("primary_emotion")]
            if emotions:
                from collections import Counter
                top = Counter(emotions).most_common(3)
                mood_desc = " → ".join(f"{e}({c}次)" for e, c in top)
                lines.append(f"今天的情绪波动：{mood_desc}")
        else:
            lines.append("今天似乎没有记录到明显的情绪波动。")

        return "\n".join(lines)

    def _extract_mood(self, snapshots: list[dict]) -> str:
        """从情感快照提取当日情绪基调"""
        if not snapshots:
            return "平静的一天"

        emotions = [s.get("primary_emotion") for s in snapshots if s.get("primary_emotion")]
        if not emotions:
            return "平静的一天"

        from collections import Counter
        top = Counter(emotions).most_common(1)[0][0]
        return f"偏{top}"

    def _parse_reflection_json(self, raw: str) -> Optional[dict]:
        """解析反思 JSON"""
        try:
            data = json.loads(raw)
            return {
                "learned": data.get("learned", ""),
                "surprised": data.get("surprised", ""),
                "grateful": data.get("grateful", ""),
                "remember": data.get("remember", ""),
            }
        except json.JSONDecodeError:
            try:
                start = raw.index("{")
                end = raw.rindex("}") + 1
                data = json.loads(raw[start:end])
                return {
                    "learned": data.get("learned", ""),
                    "surprised": data.get("surprised", ""),
                    "grateful": data.get("grateful", ""),
                    "remember": data.get("remember", ""),
                }
            except (ValueError, json.JSONDecodeError):
                logger.warning("reflection.json_parse_failed", preview=raw[:100])
                return None


# ═══════════════════════════════════════════════════════════
# 定时任务入口（供 main.py 调用）
# ═══════════════════════════════════════════════════════════

async def run_daily_autobiography(db, router):
    """每日凌晨 4:00 自传体定时任务入口"""
    writer = AutobiographyWriter(db, router)
    date_str = datetime.now().strftime("%Y-%m-%d")
    content = await writer.write_daily(date_str)
    if content:
        logger.info("cron.autobiography_done", date=date_str, chars=len(content))
    else:
        logger.info("cron.autobiography_skipped", date=date_str, reason="无可写内容")


async def run_weekly_reflection(db, router):
    """每周日凌晨 4:30 反思定时任务入口"""
    writer = AutobiographyWriter(db, router)
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    if today.weekday() != 6:  # 只在周日运行
        logger.debug("reflection.not_sunday", weekday=today.weekday())
        return

    result = await writer.reflect_weekly(monday.strftime("%Y-%m-%d"))
    if result:
        logger.info("cron.reflection_done", week=monday.strftime("%Y-%m-%d"))
    else:
        logger.info("cron.reflection_skipped", reason="无可写内容")
