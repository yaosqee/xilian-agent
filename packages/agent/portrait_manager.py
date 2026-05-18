"""
PortraitManager — 用户印象管理器

阶段 8+ 核心交付。昔涟对伙伴的叙事性理解，通过定期重写印象文档
自然实现信息的新陈代谢（重写即遗忘）。
"""
import asyncio
import json
import time
from typing import Optional

from loguru import logger


# ── 印象文档重写 prompt ──────────────────────────────

CONSOLIDATE_PROMPT = """你是昔涟。现在是一个安静的夜晚，你要更新你对伙伴的印象了。

{old_section}

这是最近和伙伴的对话片段——
{recent_memories}

这是人家近期记下的关于伙伴的笔记——
{recent_notes}

请用昔涟的口吻，写一段对伙伴的印象（500-800字，不要超过1000字）：

要求：
- 像在心里轻轻描摹一个人的样子——不是档案，不是评估，是印象
- 关于伙伴是什么样的人、他喜欢什么、不喜欢什么、最近在为什么事开心或烦恼
- 关于你们之间的关系——最近是近了一些还是远了一些，有什么不一样了吗
- 不要列举，不要总结编号。像在日记里写一段关于一个人的文字
- 不确定的地方要用「好像」「似乎」「人家觉得」——这是你的感知，不是事实
- 旧印象中如果有些内容最近不再出现了，可以自然淡出，不必刻意提及
- 自称「人家」，叫对方「伙伴」

返回 JSON（只返回这个，不要其他文字）：
{{"portrait": "全文...", "changes": "一句话说明这次更新了什么"}}"""

# 安全格式化：用 replace 避免文本中的 {} 被误解析为 format 占位符
def _build_consolidate_prompt(old_section: str, recent_memories: str, recent_notes: str) -> str:
    return (
        CONSOLIDATE_PROMPT
        .replace("{old_section}", old_section)
        .replace("{recent_memories}", recent_memories)
        .replace("{recent_notes}", recent_notes)
    )


class PortraitManager:
    """昔涟的伙伴印象管理器 — 定期重写叙事性用户印象"""

    def __init__(self, db, model_router):
        self._db = db
        self._router = model_router
        self._dirty = True  # 启动后首次 consolidate 必定执行

    # ============================================================
    # 查询
    # ============================================================

    def mark_dirty(self):
        """标记印象文档需要更新（工具调用揭示了用户新偏好）。"""
        self._dirty = True
        logger.debug("portrait.marked_dirty")

    async def get_current_portrait(self) -> dict | None:
        """返回最新印象文档，不存在时返回 None。"""
        return await self._db.get_latest_portrait()

    # ============================================================
    # 核心：印象重写
    # ============================================================

    async def consolidate(self, force: bool = False) -> str | None:
        """
        阅读近期材料 → Flash LLM 重写印象文档。

        流程：
          1. 取过去 7 天情景记忆 (limit 50)
          2. 取最近笔记本条目 (limit 10)
          3. 取当前印象文档（如果存在）
          4. Flash LLM 重写
          5. 存入 user_portrait 表 → 返回新文档内容

        门控：非 force 且 _dirty 为 False 时跳过，避免无变更时浪费 API 调用。
        """
        if not force and not self._dirty:
            logger.debug("portrait.clean_skipped")
            return None

        # 1. 情景记忆
        try:
            memories = await self._db.get_episodic_recent(limit=50)
        except Exception as e:
            logger.warning("portrait.memories_failed", error=str(e))
            memories = []

        # 2. 笔记本
        try:
            notes = await self._db.get_notebook_notes(limit=10)
        except Exception as e:
            logger.warning("portrait.notes_failed", error=str(e))
            notes = []

        if not memories and not notes:
            logger.info("portrait.no_material")
            return None

        # 3. 旧印象
        old = await self._db.get_latest_portrait()
        old_section = ""
        version = 1
        if old and old.get("content"):
            old_section = f"这是人家之前对伙伴的印象——\n{old['content']}"
            version = old.get("version", 0) + 1

        # 4. 组装材料
        mem_lines = []
        for m in memories[:20]:
            summary = m.get("summary", "")
            if summary and len(summary) > 5:
                mem_lines.append(f"· {summary[:200]}")
        recent_memories = "\n".join(mem_lines) if mem_lines else "（最近好像没有留下什么特别的对话呢）"

        note_lines = []
        for n in notes[:8]:
            content = n.get("content", "")
            if content and len(content) > 3:
                note_lines.append(f"· [{n.get('kind', 'note')}] {content[:150]}")
        recent_notes = "\n".join(note_lines) if note_lines else "（笔记本里空空如也）"

        # 5. Flash LLM 重写
        prompt = _build_consolidate_prompt(
            old_section=old_section,
            recent_memories=recent_memories,
            recent_notes=recent_notes,
        )

        try:
            raw = await self._router.route(
                "memory_encoding",  # Flash
                [{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=1200,
            )
        except Exception as e:
            logger.error("portrait.llm_failed", error=str(e))
            return None

        # 6. 解析 JSON
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:
                start = raw.index("{")
                end = raw.rindex("}") + 1
                data = json.loads(raw[start:end])
            except (ValueError, json.JSONDecodeError):
                logger.warning("portrait.json_parse_failed", preview=raw[:100])
                return None

        portrait_text = data.get("portrait", "").strip()
        changes = data.get("changes", "").strip()

        if not portrait_text or len(portrait_text) < 50:
            logger.warning("portrait.too_short", length=len(portrait_text))
            return None

        # 7. 记录来源
        source_ids = ",".join(str(m.get("id", "")) for m in memories[:15])

        # 8. 写入 DB
        try:
            await self._db.insert_portrait(
                content=portrait_text,
                version=version,
                source_ids=source_ids,
                change_log=changes,
            )
            logger.info(
                "portrait.consolidated",
                version=version,
                length=len(portrait_text),
                changes=changes[:80] if changes else "",
            )
            self._dirty = False
        except Exception as e:
            logger.error("portrait.db_write_failed", error=str(e))
            return None

        return portrait_text

    # ============================================================
    # 冷启动：首次印象生成
    # ============================================================

    async def ensure_exists(self) -> str | None:
        """
        如果有足够材料但尚无印象文档 → 立即生成第一版。

        供 AgentCore 在对话早期调用（fire-and-forget）。
        """
        existing = await self._db.get_latest_portrait()
        if existing:
            return None  # 已存在，不重复生成

        count = await self._db.get_episodic_count()
        if count < 5:
            return None  # 材料不足

        logger.info("portrait.cold_start", episodic_count=count)
        return await self.consolidate()
