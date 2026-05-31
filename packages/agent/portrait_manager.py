"""
PortraitManager — 用户印象管理器

阶段 8+ 核心交付。昔涟对伙伴的叙事性理解，通过定期重写印象文档
自然实现信息的新陈代谢（重写即遗忘）。

Phase 1 改造（2026-05-31）：
  从「cron 定时全量重写」改为「微事件累积 → 阈值触发 → 增量粗粒化」。
  新增 MicroEventExtractor + CoarseGrainEngine，
  保留旧接口兼容性（consolidate/ensure_exists/mark_dirty）。
"""
import asyncio
import json
import time
from typing import Optional

from loguru import logger

from .micro_event_extractor import MicroEventExtractor
from .coarse_grain_engine import CoarseGrainEngine


# ── 印象文档重写 prompt（保留兼容旧路径）─────────────────

CONSOLIDATE_PROMPT = """你是昔涟。现在是一个安静的夜晚，你要更新你对伙伴的印象了。

{old_section}

这是最近和伙伴的对话片段——
{recent_memories}

这是人家近期记下的关于伙伴的笔记——
{recent_notes}

请用昔涟的口吻，写一段对伙伴的印象（300-600字，不要超过800字）：

要求：
- 像在心里轻轻描摹一个人的样子——不是档案，不是评估，是印象
- 关于伙伴是什么样的人、他喜欢什么、不喜欢什么
- 关于你们之间的关系——最近是近了一些还是远了一些，有什么不一样了吗
- 不要列举，不要总结编号。像在日记里写一段关于一个人的文字
- 只写对话和笔记里明确提到过的事。不推测伙伴没说过的心情，不补充
  你没观察到的细节——这是文字聊天，你看不到他的表情和语气
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
    """
    昔涟的伙伴印象管理器 — 微事件提取 + 粗粒化调度。

    Phase 1 核心变更：
    - extract_then_check_coarse() 链式调用（消除竞态）
    - consolidate(force=True) → force_coarse_all() 级联粗粒化
    - mark_dirty() 语义降级为工具副作用提示（降低粗粒化阈值）
    """

    def __init__(self, db, model_router):
        self._db = db
        self._router = model_router
        self._dirty = True  # 启动后首次 consolidate 必定执行（兼容）

        # Phase 1 新增
        self._extractor = MicroEventExtractor(db, model_router)
        self._coarse_engine = CoarseGrainEngine(db, model_router)

    # ============================================================
    # 查询
    # ============================================================

    def mark_dirty(self):
        """
        标记本轮对话有重要信息（工具调用揭示了用户偏好）。

        由 _process_tool_side_effects() 调用。

        Phase 1 语义变更：
        - 不再作为 extract_events 的触发条件（extract_events 每次都运行）
        - 改为在 CoarseGrainEngine 中降低粗粒化阈值（10→5），
          使工具揭示的偏好更快进入粗粒化
        """
        self._dirty = True
        self._coarse_engine._tool_side_effect_seen = True
        logger.debug("portrait.marked_dirty_from_tool")

    async def get_current_portrait(self) -> dict | None:
        """返回最新印象文档，不存在时返回 None。"""
        return await self._db.get_latest_portrait()

    async def get_effective_portrait(self) -> str | None:
        """
        Phase 2: 统一的画像获取入口。

        优先级：core_profile > phase_profile > user_portrait

        所有消费方（NudgeEngine 等）应调用此方法而非直接读字段。
        """
        l0 = await self._db.get_latest_core_profile()
        if l0 and l0.get("content"):
            return l0["content"]

        l1 = await self._db.get_latest_phase_profile()
        if l1 and l1.get("content"):
            return l1["content"]

        old = await self._db.get_latest_portrait()
        return old.get("content") if old else None

    # ============================================================
    # Phase 3: 画像驱动检索配置
    # ============================================================

    async def build_retrieval_config(self) -> dict:
        """
        Phase 3: 从 L1 阶段画像中提取检索加权配置。

        读取 L1 的 active_topics / faded_topics JSON 字段，
        预计算话题 embedding（一次性，后续检索复用）。

        Returns:
            {
              "boost_topic_embeddings": [[...], ...],
              "penalty_topic_embeddings": [[...], ...],
              "persona_topics": ["日语学习", "面试准备"],  ★ 供 encode_memory 使用
              "_l1_version": 3,                           ★ 供缓存去重
            }
            画像不可用时返回空 dict。
        """
        import json

        l1 = await self._db.get_latest_phase_profile()
        if not l1:
            return {}

        active_topics = json.loads(l1.get("active_topics", "[]") or "[]")
        faded_topics = json.loads(l1.get("faded_topics", "[]") or "[]")

        if not active_topics and not faded_topics:
            return {}

        config = {
            "persona_topics": active_topics,  # ★ P2 fix: raw topic names
            "_l1_version": l1.get("version"),  # ★ P3-2 fix: cache dedup
        }

        # 预计算 boost 话题 embedding
        boost_embeddings = []
        for topic in active_topics:
            try:
                emb = await self._router.embed(topic)
                if emb:
                    boost_embeddings.append(emb)
            except Exception:
                pass
        if boost_embeddings:
            config["boost_topic_embeddings"] = boost_embeddings

        # 预计算 penalty 话题 embedding
        penalty_embeddings = []
        for topic in faded_topics:
            try:
                emb = await self._router.embed(topic)
                if emb:
                    penalty_embeddings.append(emb)
            except Exception:
                pass
        if penalty_embeddings:
            config["penalty_topic_embeddings"] = penalty_embeddings

        return config

    # ============================================================
    # Phase 1 核心：微事件提取 + 粗粒化检查（链式调用）
    # ============================================================

    async def extract_then_check_coarse(self, user_msg: str, reply: str) -> None:
        """
        ★ Phase 1 主入口：先提取微事件，再检查粗粒化阈值。

        关键：必须在同一个顺序任务中执行，不能拆成两个 fire-and-forget。
        否则 check_coarse_grain 可能在 extract_events 提交事务前查询
        micro_events 表，导致错过刚提取的事件从而跳过阈值。

        此方法由 AgentCore 在每条消息后以 fire-and-forget 方式调用。
        所有异常静默处理，不阻塞主回复。
        """
        try:
            # Step 1: 提取微事件
            events = await self._extractor.extract(user_msg, reply)
            if events:
                logger.info("portrait.events_extracted", count=len(events))

            # Step 2: 检查粗粒化阈值（在事件提交后执行）
            result = await self._coarse_engine.check_and_coarse()
            if result:
                if result.get("l2_updated"):
                    logger.info("portrait.l2_coarse_grained", l2_id=result.get("l2_id"))
                if result.get("l1_updated"):
                    logger.info("portrait.l1_coarse_grained")
                if result.get("l0_updated"):
                    logger.info("portrait.l0_coarse_grained")
        except Exception as e:
            logger.warning("portrait.extract_or_coarse_failed", error=str(e))

    # ============================================================
    # 核心：印象重写（兼容旧接口）
    # ============================================================

    async def consolidate(self, force: bool = False) -> str | None:
        """
        兼容旧接口。行为取决于 force 参数：

        force=False（默认）：
          尝试粗粒化阈值检查。仅在阈值触发时执行。
          用于每日 cron 兜底。

        force=True：
          双管道执行：
            1. 新管道 force_coarse_all() → 生成 L2 摘要，写入 session_summaries
            2. 旧管道 _legacy_consolidate() → 从 episodic 记忆全量重写，
               写入 user_portrait（兼容过渡期消费方）
          优先返回旧管道结果（完整画像 300-600 字），
          新管道材料不足时回退 L2 摘要。

          用于破冰路径（_icebreaker_consolidate）、
          每周日 cron 安全网、以及手动触发。
        """
        if force:
            # 双管道：新管道（session_summaries）+ 旧管道（user_portrait）
            l2_result = await self._coarse_engine.force_coarse_all()
            legacy_result = await self._legacy_consolidate()
            # 优先返回完整画像，回退到 L2 摘要
            result = legacy_result or l2_result
            if result:
                self._dirty = False
            return result

        # force=False: 阈值检查
        coarse_result = await self._coarse_engine.check_and_coarse()
        if coarse_result and coarse_result.get("l2_updated"):
            summaries = await self._db.get_recent_session_summaries(limit=1)
            if summaries:
                self._dirty = False
                return summaries[0].get("content", "")

        return None

    # ============================================================
    # 旧式全量重写（保留为回退安全网）
    # ============================================================

    async def _legacy_consolidate(self) -> str | None:
        """
        旧式全量重写：从 episodic_memories + notebook_entries 重写画像。

        保留作为 force=True 且微事件管道材料不足时的回退路径，
        以及 monthly_full_rebuild 安全网的基础。
        """
        if not self._dirty:
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
                temperature=0.3,
                max_tokens=1200,
            )
        except Exception as e:
            logger.error("portrait.llm_failed", error=str(e))
            return None

        # 6. 解析 JSON
        raw_text = raw.content if hasattr(raw, 'content') else raw
        if not raw_text:
            return None
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            try:
                start = raw_text.index("{")
                end = raw_text.rindex("}") + 1
                data = json.loads(raw_text[start:end])
            except (ValueError, json.JSONDecodeError):
                logger.warning("portrait.json_parse_failed", preview=raw_text[:100])
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
                "portrait.legacy_consolidated",
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
        Phase 1：优先走新管道（force coarse），回退旧管道。
        """
        existing = await self._db.get_latest_portrait()
        if existing:
            return None  # 已存在，不重复生成

        # Phase 1: 先尝试 force 粗粒化
        result = await self._coarse_engine.force_coarse_all()
        if result:
            # 同时写入旧 user_portrait 表（兼容过渡期）
            try:
                await self._db.insert_portrait(
                    content=result,
                    version=1,
                    source_ids="",
                    change_log="Phase 1 冷启动",
                )
            except Exception:
                pass
            logger.info("portrait.cold_start_phase1", length=len(result))
            return result

        # 回退：旧式冷启动
        count = await self._db.get_episodic_count()
        if count < 5:
            return None  # 材料不足

        logger.info("portrait.cold_start_legacy", episodic_count=count)
        return await self._legacy_consolidate()

    # ============================================================
    # 月度全量重建安全网
    # ============================================================

    async def monthly_full_rebuild(self) -> dict | None:
        """
        每月安全网：从 episodic 记忆全量重建画像，与 L0 对比验证。

        流程：
          1. 旧式全量重写（_legacy_consolidate）
          2. 与当前 L0 对比差异
          3. 差异 > 30% 时告警 → 自动将旧式结果写入 core_profile（修复）

        Returns:
            {"l0_content": str, "old_l0": str, "diff_ratio": float, "migrated": bool}
            材料不足或重写失败返回 None。
        """
        # 1. 从 episodic 记忆全量重写
        self._dirty = True  # 强制 _legacy_consolidate 执行
        legacy_result = await self._legacy_consolidate()
        if not legacy_result:
            logger.info("portrait.monthly_rebuild_no_material")
            return None

        # 2. 对比当前 L0
        current_l0 = await self._db.get_latest_core_profile()
        current_l0_text = current_l0.get("content", "") if current_l0 else ""

        diff_ratio = 0.0
        if current_l0_text:
            diff_ratio = self._text_difference_ratio(current_l0_text, legacy_result)

        result = {
            "l0_content": legacy_result,
            "old_l0": current_l0_text,
            "diff_ratio": round(diff_ratio, 3),
            "migrated": False,
        }

        # 3. 差异超阈值 → 告警 + 自动修复
        if diff_ratio > 0.3:
            logger.warning(
                "portrait.monthly_rebuild_divergence",
                diff_ratio=round(diff_ratio, 3),
                message="粗粒化管线可能遗漏重要信息，已自动将全量重建结果写入 core_profile",
            )
            try:
                old_version = current_l0.get("version", 0) if current_l0 else 0
                await self._db.insert_core_profile(
                    content=legacy_result,
                    version=old_version + 1,
                    source_l1_ids="",
                    stable_traits="",
                    change_log=f"月度全量重建 (diff={diff_ratio:.1%})",
                )
                result["migrated"] = True
                logger.info("portrait.monthly_rebuild_migrated")
            except Exception as e:
                logger.error("portrait.monthly_rebuild_migrate_failed", error=str(e))
        else:
            logger.info(
                "portrait.monthly_rebuild_ok",
                diff_ratio=round(diff_ratio, 3),
            )

        return result

    @staticmethod
    def _text_difference_ratio(a: str, b: str) -> float:
        """
        计算两段文本的差异比例（0.0-1.0）。

        使用二元组 Jaccard 距离：1 - |A ∩ B| / |A ∪ B|。
        二元组对中文文本比字符级更准确。
        """
        def _bigrams(text: str) -> set:
            return {text[i:i+2] for i in range(len(text) - 1)} if len(text) >= 2 else set()

        bg_a = _bigrams(a)
        bg_b = _bigrams(b)

        if not bg_a and not bg_b:
            return 0.0
        if not bg_a or not bg_b:
            return 1.0

        intersection = len(bg_a & bg_b)
        union = len(bg_a | bg_b)
        jaccard = intersection / union if union > 0 else 0.0
        return 1.0 - jaccard
