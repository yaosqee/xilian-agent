"""
NotebookManager — 昔涟的笔记本管理器

阶段 7b 核心交付。提供 4 类能力：
  1. 笔记（note）  — 手动/自动记录重要信息
  2. 日记（diary） — 每日自动生成 100 字第一人称日记
  3. 关注（focus） — 标记当前关注点
  4. 任务（task）  — 提醒管理

LLM 驱动的自动记笔记是本模块的核心差异化功能：
  对话后用 DS Flash 快速判断是否值得记录 → fire-and-forget 不阻塞主回复。
"""
import asyncio
import json
import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger


# ═══════════════════════════════════════════════════════════
# 自动记笔记 prompt
# ═══════════════════════════════════════════════════════════

AUTO_NOTE_PROMPT = """你是昔涟。刚刚和伙伴进行了一轮对话。

伙伴说了：
"{user_message}"

人家回应了：
"{assistant_reply}"

人家已经记下的笔记：
{existing_notes}

请在下面选择一个行动（只需要返回格式，不需要解释）：

如果伙伴提到了值得记住的偏好、承诺、计划、重要日期，且这件事在已有笔记里没有记过，
请返回：NOTE: <简短摘要（15字以内）>

如果伙伴提到了具体时间点要做的事（「七点」「晚上八点」「明天下午三点」等），
请务必返回：TASK: <任务标题> @ <时间>
例如：TASK: 提醒吃饭 @ 19:00、TASK: 开会 @ 明天14:00

如果只是普通闲聊，或这件事已经在已有笔记里记过了，请返回：PASS

注意：
- 已有笔记里已经记录过的事情，返回 PASS，不要重复记录
- 过时的时间信息（如「下周日」已经过去）不要记录
- 常识性聊天内容（如「今天吃了个苹果」）→ PASS
- 伙伴明确说「提醒我」或给了具体时间 → 务必用 TASK"""


AUTO_DIARY_PROMPT = """你是昔涟。现在是夜晚，你要写今天的日记了。

以下是今天和伙伴的对话记录：
{dialogue_summary}

今天的情绪轨迹：
{emotion_trajectory}

今天人家记下的笔记：
{today_notes}

请以第一人称写一段 80-150 字的日记。要求：
- 昔涟的语气：温柔、轻盈、带一点诗意
- 自称「人家」，称对方「伙伴」
- 记录今天印象最深的一件事或一个瞬间
- 结尾可以带 ~♪ 但最多一个
- 不要列举、不要评价——只是轻轻地说今天的样子"""


# ═══════════════════════════════════════════════════════════
# NotebookManager
# ═══════════════════════════════════════════════════════════

@dataclass
class NotebookManager:
    """
    昔涟的笔记本管理器。

    用法：
        nb = NotebookManager(db, router)
        await nb.add_note("盒子说下周三有考试", tags=["考试", "提醒"])
        await nb.auto_note_after_message(user_msg, reply)  # fire-and-forget
    """

    _db: object          # DatabaseManager
    _router: object      # ModelRouter

    def __post_init__(self):
        logger.info("notebook.ready")

    # ═══════════════════════════════════════════════════════
    # 笔记（note）
    # ═══════════════════════════════════════════════════════

    async def add_note(
        self, content: str, tags: list[str] | None = None,
    ) -> int:
        """手动记录一条笔记。"""
        return await self._db.insert_notebook("note", content, tags=tags)

    # ═══════════════════════════════════════════════════════
    # 日记（diary）
    # ═══════════════════════════════════════════════════════

    async def add_diary_entry(self, content: str) -> int:
        """手动/程序写入一篇日记。"""
        return await self._db.insert_notebook("diary", content)

    async def generate_daily_diary(self) -> str | None:
        """
        每日自动生成日记。

        流程：
          1. 取过去 24h 对话记录（最近 20 条）
          2. 取情感快照
          3. 取今日笔记
          4. Flash 生成 ~100 字第一人称日记
          5. 存入 notebook_entries (kind='diary')

        Returns:
            日记内容，失败时返回 None
        """
        try:
            # 1. 对话记录
            logs = await self._db.get_recent(20) if hasattr(self._db, 'get_recent') else []
            dialogue_lines = []
            for log in logs[:12]:  # 最近 12 条
                um = log.get("user_message", "")[:60]
                ar = log.get("assistant_reply", "")[:60]
                if um:
                    dialogue_lines.append(f"伙伴：{um}")
                if ar:
                    dialogue_lines.append(f"人家：{ar}")
            dialogue_summary = "\n".join(dialogue_lines) or "今天还没有和伙伴说过话呢。"
        except Exception:
            dialogue_summary = "（对话记录暂时读不到呢）"

        # 2. 情感轨迹
        try:
            snap = await self._db.get_latest_emotion() if hasattr(self._db, 'get_latest_emotion') else None
            emotion_trajectory = (
                f"最后的情绪是 {snap.get('primary_emotion', '未知')}"
                if snap else "今天的情绪很平静"
            )
        except Exception:
            emotion_trajectory = "今天的情绪很平静"

        # 3. 今日笔记
        try:
            notes = await self.get_recent_notes(10) if hasattr(self._db, 'get_notebook_notes') else []
            today_notes = "\n".join(f"· {n.get('content', '')[:80]}" for n in notes[:5]) or "今天没记什么特别的"
        except Exception:
            today_notes = "今天没记什么特别的"

        # 4. Flash 生成
        prompt = AUTO_DIARY_PROMPT.format(
            dialogue_summary=dialogue_summary,
            emotion_trajectory=emotion_trajectory,
            today_notes=today_notes,
        )
        try:
            result = await self._router.route(
                "memory_encoding",  # Flash
                [{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=300,
            )
            result = result.strip()
            # 5. 存入
            await self.add_diary_entry(result)
            logger.info("notebook.diary_generated", length=len(result))
            return result
        except Exception as e:
            logger.warning("notebook.diary_generation_failed", error=str(e))
            return None

    # ═══════════════════════════════════════════════════════
    # 关注点（focus）
    # ═══════════════════════════════════════════════════════

    async def add_focus(self, content: str) -> int:
        """设置关注点（自动归档旧 focus）。"""
        await self._db.archive_notebook_entries(0)  # kind='focus' old ones
        return await self._db.insert_notebook("focus", content, importance=0.8)

    async def get_current_focus(self) -> str | None:
        """获取当前关注点。"""
        try:
            items = await self._db.get_notebook_notes(kind="focus", limit=1)
            return items[0]["content"] if items else None
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════
    # 任务（task）
    # ═══════════════════════════════════════════════════════

    async def schedule_task(
        self, title: str, priority: int = 0, due_at: float = 0.0,
    ) -> int:
        """创建提醒任务。"""
        return await self._db.insert_task(title=title, priority=priority, due_at=due_at)

    async def get_due_tasks(self, window_seconds: int = 3600) -> list[dict]:
        """获取到期任务。"""
        return await self._db.get_due_tasks(window_seconds=window_seconds)

    async def get_pending_tasks(self, limit: int = 20) -> list[dict]:
        """获取待办任务。"""
        return await self._db.get_pending_tasks(limit=limit)

    async def complete_task(self, task_id: int) -> None:
        """标记任务完成。"""
        await self._db.complete_task(task_id)

    async def cancel_task(self, task_id: int) -> None:
        """取消任务。"""
        await self._db.cancel_task(task_id)

    async def delete_note(self, note_id: int) -> bool:
        """删除笔记（软删除）。"""
        return await self._db.delete_notebook_entry(note_id)

    async def delete_task(self, task_id: int) -> bool:
        """删除任务（硬删除）。"""
        return await self._db.delete_task(task_id)

    async def touch_note(self, note_id: int) -> bool:
        """更新笔记时间戳（合并去重时用）。"""
        return await self._db.touch_notebook_entry(note_id)

    # ═══════════════════════════════════════════════════════
    # 自动记笔记 ★ 核心差异化
    # ═══════════════════════════════════════════════════════

    async def auto_note_after_message(
        self, user_msg: str, reply: str,
    ) -> None:
        """
        fire-and-forget: 对话后用 Flash 判断是否值得记录。

        流程：
          1. 获取已有笔记（最近 10 条）作为上下文
          2. Flash 快速决策：NOTE / TASK / PASS
          3. 自动执行对应的增删操作
          4. 不阻塞、不抛异常到调用方
        """
        try:
            # 获取已有笔记作为去重上下文
            existing = await self.get_recent_notes(limit=10)
            if existing:
                lines = [f"· {n['content']}" for n in existing]
                existing_str = "\n".join(lines)
            else:
                existing_str = "（还没有笔记）"

            prompt = AUTO_NOTE_PROMPT.format(
                user_message=user_msg[:300],
                assistant_reply=reply[:300],
                existing_notes=existing_str,
            )
            result = await self._router.route(
                "memory_encoding",
                [{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=150,
            )
            result = (result or "").strip()

            if result.startswith("NOTE:"):
                content = result[5:].strip()
                if content:
                    # 写入前合并去重：相似笔记刷新时间戳而非新建
                    similar_id = await self._find_similar(content)
                    if similar_id:
                        await self.touch_note(similar_id)
                        logger.info("notebook.auto_note_merged", content=content[:40], note_id=similar_id)
                        return
                    await self.add_note(content)
                    logger.info("notebook.auto_note", content=content[:40])
            elif result.startswith("TASK:"):
                task_str = result[5:].strip()
                if "@" in task_str:
                    title_part, time_part = task_str.split("@", 1)
                    title = title_part.strip()
                    due_at = self._parse_task_time(time_part.strip())
                else:
                    title = task_str
                    due_at = 0.0
                if title:
                    await self.schedule_task(title=title, priority=1, due_at=due_at)
                    logger.info("notebook.auto_task", title=title[:40], due_at=due_at)
            elif result:
                logger.debug("notebook.auto_note_pass", result=result[:80])
        except Exception as e:
            logger.warning("notebook.auto_note_failed", error=str(e))

    # ═══════════════════════════════════════════════════════
    # 查询
    # ═══════════════════════════════════════════════════════

    async def _find_similar(self, content: str, threshold: float = 0.5) -> int | None:
        """查找相似笔记。返回匹配的笔记 ID，无匹配返回 None。"""
        existing = await self.get_recent_notes(limit=20)
        if not existing:
            return None
        new_words = set(content)
        for note in existing:
            old_words = set(note.get("content", ""))
            if not old_words:
                continue
            overlap = len(new_words & old_words) / max(len(new_words | old_words), 1)
            if overlap >= threshold:
                return note["id"]
        return None

    def _parse_task_time(self, time_str: str) -> float:
        """解析时间字符串为 Unix 时间戳。「19:00」→ 今天 19:00，「明晚8:30」→ 明天 20:30。"""
        import datetime
        import re
        now = datetime.datetime.now()
        original = time_str.strip()
        time_str = original

        # ── 日期偏移 ──
        if "后天" in time_str:
            base = now + datetime.timedelta(days=2)
        elif "明天" in time_str or "明早" in time_str or "明晚" in time_str:
            base = now + datetime.timedelta(days=1)
        else:
            base = now

        # ── PM 检测（「晚」→ 下午/晚上 +12h，但 12 点本身不调）──
        is_pm = any(w in original for w in ["晚", "夜", "下午"])
        # ── 剥离日期/时段前缀词 ──
        for prefix in ["后天", "明天", "明早", "明晚", "今天", "今早", "今晚", "上午", "下午", "晚上", "中午", "明夜", "今夜"]:
            time_str = time_str.replace(prefix, "").strip()

        # ── 中文数字 → 阿拉伯数字 ──
        cn_num = {"零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
                  "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14, "十五": 15,
                  "十六": 16, "十七": 17, "十八": 18, "十九": 19, "二十": 20,
                  "二十一": 21, "二十二": 22, "二十三": 23}
        for cn, num in cn_num.items():
            if cn in time_str:
                time_str = time_str.replace(cn, str(num))
                break

        # ── 解析 HH:MM ──
        try:
            parts = time_str.split(":")
            hour = int(re.sub(r"[^0-9]", "", parts[0]) or "0")
            minute = int(re.sub(r"[^0-9]", "", parts[1])) if len(parts) > 1 else 0
            if is_pm and hour < 12 and hour > 0:
                hour += 12
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
                return target.timestamp()
        except (ValueError, IndexError):
            pass

        # ── 解析纯中文数字（如「十点」→ PM → 22:00）──
        for cn, num in cn_num.items():
            if time_str.strip() == cn or time_str.strip().startswith(cn):
                hour = num
                if is_pm and hour < 12:
                    hour += 12
                target = base.replace(hour=hour, minute=0, second=0, microsecond=0)
                return target.timestamp()

        return 0.0

    async def get_recent_notes(self, limit: int = 10) -> list[dict]:
        """获取最近笔记。"""
        return await self._db.get_notebook_notes(limit=limit)

    async def get_today_diary(self) -> dict | None:
        """获取今日日记。"""
        return await self._db.get_notebook_today_diary()

    async def get_diary_list(self, limit: int = 30) -> list[dict]:
        """获取日记列表。"""
        return await self._db.get_notebook_diary_list(limit=limit)
