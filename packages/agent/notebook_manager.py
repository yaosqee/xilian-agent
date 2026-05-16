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

请在下面选择一个行动（只需要返回 1-3 个词的指令，不需要解释）：

如果伙伴提到了值得记住的事情（日期、承诺、计划、偏好、担忧、开心的事），
请返回：NOTE: <简短笔记摘要（15字以内）>

如果伙伴提到了需要提醒的事情（截止日期、考试、会议、约定），
请返回：TASK: <任务标题> @ <时间描述>

如果只是普通闲聊，没有特别值得记的，请返回：PASS

注意：
- 只记录对你的伙伴（盒子）有意义的个人化信息
- 不要把常识性的聊天内容记录下来
- 如果伙伴说「下周三考试」→ 记录笔记 + 创建提醒
- 如果伙伴说「今天吃了个苹果」→ PASS"""


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

    # ═══════════════════════════════════════════════════════
    # 自动记笔记 ★ 核心差异化
    # ═══════════════════════════════════════════════════════

    async def auto_note_after_message(
        self, user_msg: str, reply: str,
    ) -> None:
        """
        fire-and-forget: 对话后用 Flash 判断是否值得记录。

        流程：
          1. Flash 快速决策：NOTE / TASK / PASS
          2. 自动执行对应的增删操作
          3. 不阻塞、不抛异常到调用方
        """
        try:
            prompt = AUTO_NOTE_PROMPT.format(
                user_message=user_msg[:300],
                assistant_reply=reply[:300],
            )
            result = await self._router.route(
                "memory_encoding",
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=60,
            )
            result = result.strip()

            if result.startswith("NOTE:"):
                content = result[5:].strip()
                if content:
                    await self.add_note(content)
                    logger.info("notebook.auto_note", content=content[:40])
            elif result.startswith("TASK:"):
                task_str = result[5:].strip()
                title = task_str.split("@")[0].strip() if "@" in task_str else task_str
                if title:
                    await self.schedule_task(title=title, priority=1)
                    logger.info("notebook.auto_task", title=title[:40])
            # PASS → 什么都不做
        except Exception as e:
            logger.warning("notebook.auto_note_failed", error=str(e))

    # ═══════════════════════════════════════════════════════
    # 查询
    # ═══════════════════════════════════════════════════════

    async def get_recent_notes(self, limit: int = 10) -> list[dict]:
        """获取最近笔记。"""
        return await self._db.get_notebook_notes(limit=limit)

    async def get_today_diary(self) -> dict | None:
        """获取今日日记。"""
        return await self._db.get_notebook_today_diary()

    async def get_diary_list(self, limit: int = 30) -> list[dict]:
        """获取日记列表。"""
        return await self._db.get_notebook_diary_list(limit=limit)
