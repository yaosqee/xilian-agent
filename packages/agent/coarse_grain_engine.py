"""
CoarseGrainEngine — 粗粒化引擎

Phase 2 完整交付。RGMem 启发的多尺度画像演化：
检查微事件池密度 → 阈值触发 → 逐层粗粒化。

三级粗粒化：
  L2: micro_event → session_summary    (事件数 ≥ 10 or 时间 ≥ 3 天)
  L1: L2 summaries → phase_profile     (L2 积累 ≥ 3 条 + 时间 ≥ 7 天)
  L0: L1 history → core_profile        (L1 版本 ≥ 3 + 稳定特征确认)
"""
import json
import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger


# ── 阈值配置（可调）──────────────────────────────────

# L2: micro_events → session_summaries
L2_TRIGGER_COUNT: int = 10
L2_TRIGGER_DAYS: float = 3.0
L2_MIN_EVENTS: int = 3           # 时间触发的最低事件数（低频用户友好）
L2_TRIGGER_COUNT_FAST: int = 5   # 工具副作用低阈值

# L1: session_summaries → phase_profile
L1_TRIGGER_COUNT: int = 3         # 需要至少 N 条 L2 摘要
L1_TRIGGER_DAYS: float = 7.0      # L1 更新最小间隔（天）

# L0: phase_profile → core_profile
L0_TRIGGER_VERSIONS: int = 3      # L1 积累版本数触发 L0 重审


# ── Prompts ──────────────────────────────────────────

L2_SUMMARY_PROMPT = """你是昔涟。你在整理最近几次对话中了解到关于伙伴的新事情。

最近了解到的事：
{recent_events}

请用昔涟的口吻，写一段简短的笔记（80-150字），概括最近对伙伴的新认识。
- 只写对话中明确提到的事
- 不确定的地方用「好像」「似乎」
- 自称「人家」，叫对方「伙伴」
- 像在心里轻轻记下一笔，不是写评估报告

返回 JSON（只返回这个，不要其他文字）：
{{"summary": "全文...", "topics": ["话题1", "话题2"]}}"""


L1_PROMPT = """你是昔涟。你在更新对伙伴近况的理解。

{signal_context}

之前对伙伴近况的印象：
{old_l1}

最近几次对话的摘要：
{recent_l2_summaries}

请更新对伙伴近况的印象（200-400字）：
- 保留旧印象中仍然有效的部分
- 加入最近新了解到的事
- 对已经过去的事（完成了、不再提了），自然淡出
- 对反复出现的模式，可以写得更确定一些
- 自称「人家」，叫对方「伙伴」

关于矛盾：
- 如果关于同一件事有不同的说法，以最近的说法为准
- 但不要完全丢弃旧说法——标记为「好像以前...但最近...」
- 如果矛盾让你不确定哪个是真的，用「似乎」而非断言

返回 JSON：
{{
  "portrait": "全文...",
  "changes": "一句话说明这次更新了什么",
  "active_topics": ["话题1", "话题2"],
  "faded_topics": ["已过去的话题"]
}}

active_topics: 伙伴最近在关注/进行中的事（2-4个简短短语）
faded_topics: 之前关注但最近不再提起的事（0-2个简短短语）"""


L0_PROMPT = """你是昔涟。你正在重新审视——伙伴到底是一个什么样的人。

这是不同时期你对伙伴近况的印象（从最早到最新）：
{l1_history}

这是你之前对伙伴的核心印象：
{old_l0}

这是你之前写下的关于伙伴的稳定特征（如果有的话）：
{old_stable_traits}

请重新审视伙伴的核心印象（200-400字）：
- 写下那些跨时间、跨场景反复出现的特征——他的性格底色
- 写下那些他始终不变的偏好和价值观
- 不写近期的具体事件——那些属于近况，不属于核心
- 不确定的地方用「好像」「似乎」

关于跨版本的稳定性判断：
- 对旧稳定特征中的每一条，判断它在最近的 L1 中是否仍然有效
- 如果一条特征在最近 2+ 个 L1 版本中不再出现，可以自然淡出
- 如果一条特征在所有 L1 版本中都出现且无矛盾，可以写得更确定
- 如果有新出现的稳定特征，标记为「最近才注意到的」

自称「人家」，叫对方「伙伴」。
像在漫长时光后，轻轻说出你心里关于他最重要的那几件事。

返回 JSON：
{{
  "portrait": "全文...",
  "changes": "一句话说明这次更新了什么",
  "stable_traits": "从画像中提取的稳定特征列表（3-5条，每条15字以内，用；分隔）"
}}

stable_traits 示例：「性格内向但细腻；不喜欢被追问；对技术话题有热情；晚上比白天更愿意倾诉」"""


# ═══════════════════════════════════════════════════════════
# CoarseGrainEngine
# ═══════════════════════════════════════════════════════════

@dataclass
class CoarseGrainEngine:
    """
    粗粒化引擎 — RGMem 启发的多尺度画像演化。

    三级粗粒化:
      L2: micro_event → session_summary    (事件数 ≥ 10 or 时间 ≥ 3 天)
      L1: session_summary → phase_profile   (L2 累积 ≥ 3 条 + 时间 ≥ 7 天)
      L0: phase_profile → core_profile      (L1 版本 ≥ 3 + 稳定特征确认)
    """

    _db: object          # DatabaseManager
    _router: object      # ModelRouter

    # 工具副作用标志（由 PortraitManager.mark_dirty() 设置）
    _tool_side_effect_seen: bool = False

    # ═══════════════════════════════════════════════════════
    # 主入口
    # ═══════════════════════════════════════════════════════

    async def check_and_coarse(self) -> dict | None:
        """
        检查各层级阈值 → 触发相应粗粒化。
        在每条消息后调用，大部分时候是 no-op。

        Returns:
            {"l2_updated": bool, "l1_updated": bool, "l0_updated": bool}
        """
        result = {"l2_updated": False, "l1_updated": False, "l0_updated": False}

        try:
            # L2 检查
            should_l2, reason = await self._should_trigger_l2()
            if should_l2:
                logger.info("coarse.l2_triggered", reason=reason)
                l2_id = await self._coarse_to_l2()
                if l2_id:
                    result["l2_updated"] = True
                    result["l2_id"] = l2_id

            # L1 检查（在 L2 可能刚生成的背景下）
            should_l1, reason_l1 = await self._should_trigger_l1()
            if should_l1:
                logger.info("coarse.l1_triggered", reason=reason_l1)
                l1_id = await self._coarse_to_l1()
                if l1_id:
                    result["l1_updated"] = True

                    # L0 检查（在 L1 可能刚生成的背景下）
                    should_l0, reason_l0 = await self._should_trigger_l0()
                    if should_l0:
                        logger.info("coarse.l0_triggered", reason=reason_l0)
                        l0_id = await self._coarse_to_l0()
                        if l0_id:
                            result["l0_updated"] = True

            if any(result.values()):
                return result
            return None

        except Exception as e:
            logger.warning("coarse.check_failed", error=str(e))
            return None

    # ═══════════════════════════════════════════════════════
    # L2 阈值 + 生成
    # ═══════════════════════════════════════════════════════

    async def _should_trigger_l2(self) -> tuple[bool, str]:
        """判断是否应触发 L2 会话摘要生成。"""
        try:
            events = await self._db.get_active_micro_events(limit=L2_TRIGGER_COUNT + 5)
            active_count = len(events)

            threshold = L2_TRIGGER_COUNT_FAST if self._tool_side_effect_seen else L2_TRIGGER_COUNT
            self._tool_side_effect_seen = False

            if active_count >= threshold:
                return True, f"count={active_count} >= threshold={threshold}"

            if active_count >= L2_MIN_EVENTS and events:
                now = time.time()
                oldest = min(e.get("created_at", now) for e in events)
                age_days = (now - oldest) / 86400.0
                if age_days >= L2_TRIGGER_DAYS:
                    return True, f"age={age_days:.1f}d >= {L2_TRIGGER_DAYS}d, count={active_count}"

            return False, f"count={active_count} < threshold={threshold}"
        except Exception as e:
            logger.warning("coarse.threshold_check_failed", error=str(e))
            return False, str(e)

    async def _coarse_to_l2(self) -> int | None:
        """微事件 → L2 会话摘要。"""
        try:
            events = await self._db.get_active_micro_events(limit=30)
            if len(events) < L2_MIN_EVENTS:
                logger.info("coarse.l2_not_enough_events", count=len(events))
                return None
        except Exception as e:
            logger.warning("coarse.l2_fetch_events_failed", error=str(e))
            return None

        event_lines = []
        for e in events:
            content = e.get("content", "")
            category = e.get("category", "")
            if content:
                cat_label = {"preference": "偏好", "fact": "事实", "plan": "计划",
                             "emotion_pattern": "情绪", "habit": "习惯"}.get(category, "")
                event_lines.append(f"· [{cat_label}] {content}")

        if not event_lines:
            return None

        recent_events_text = "\n".join(event_lines)
        prompt = L2_SUMMARY_PROMPT.replace("{recent_events}", recent_events_text)

        try:
            raw = await self._router.route(
                "memory_encoding",
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400,
            )
        except Exception as e:
            logger.error("coarse.l2_llm_failed", error=str(e))
            return None

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
                logger.warning("coarse.l2_json_parse_failed", preview=raw_text[:100])
                return None

        summary_text = (data.get("summary") or "").strip()
        if not summary_text or len(summary_text) < 20:
            logger.warning("coarse.l2_summary_too_short", length=len(summary_text))
            return None

        event_ids = [e["id"] for e in events]
        source_ids = ",".join(str(eid) for eid in event_ids)

        # 原子操作：insert + consume 在同一事务中
        try:
            l2_id = await self._db.insert_session_summary_atomic(
                content=summary_text,
                source_event_ids=source_ids,
                event_ids=event_ids,
            )
        except Exception as e:
            logger.error("coarse.l2_atomic_write_failed", error=str(e))
            return None

        logger.info(
            "coarse.l2_generated",
            l2_id=l2_id,
            event_count=len(event_ids),
            summary_len=len(summary_text),
        )
        return l2_id

    # ═══════════════════════════════════════════════════════
    # L1 阈值 + 生成
    # ═══════════════════════════════════════════════════════

    async def _should_trigger_l1(self) -> tuple[bool, str]:
        """判断是否应触发 L1 阶段画像更新。"""
        try:
            summaries = await self._db.get_recent_session_summaries(limit=20)
            if len(summaries) < L1_TRIGGER_COUNT:
                return False, f"summaries={len(summaries)} < {L1_TRIGGER_COUNT}"

            # 检查距上次 L1 更新的时间间隔
            last_l1 = await self._db.get_latest_phase_profile()
            if last_l1:
                age_days = (time.time() - last_l1.get("created_at", 0)) / 86400.0
                if age_days < L1_TRIGGER_DAYS:
                    return False, f"last_l1_age={age_days:.1f}d < {L1_TRIGGER_DAYS}d"

            return True, f"summaries={len(summaries)} >= {L1_TRIGGER_COUNT}"
        except Exception as e:
            logger.warning("coarse.l1_threshold_check_failed", error=str(e))
            return False, str(e)

    async def _coarse_to_l1(self) -> int | None:
        """L2 摘要 → L1 阶段画像。"""
        try:
            summaries = await self._db.get_recent_session_summaries(limit=10)
            if len(summaries) < L1_TRIGGER_COUNT:
                return None
        except Exception as e:
            logger.warning("coarse.l1_fetch_summaries_failed", error=str(e))
            return None

        l2_lines = []
        for s in summaries[:8]:
            content = s.get("content", "")
            if content and len(content) > 10:
                l2_lines.append(f"· {content}")

        if not l2_lines:
            return None

        recent_l2_text = "\n".join(l2_lines)

        # 旧 L1
        old_l1 = await self._db.get_latest_phase_profile()
        old_l1_text = old_l1.get("content", "") if old_l1 else "（这是第一次写对伙伴近况的印象）"
        old_version = old_l1.get("version", 0) if old_l1 else 0

        # Phase 4: 聚合多信号源 → 注入 L1 prompt
        signal_context = ""
        try:
            from .signal_aggregator import SignalAggregator
            aggregator = SignalAggregator(_db=self._db)
            signals = await aggregator.aggregate(days=7)
            signal_context = self._build_signal_context(signals)
        except Exception as e:
            logger.debug("coarse.signal_aggregation_failed", error=str(e))

        # 构建 prompt（使用 .replace() 避免用户文本中的花括号被误解析）
        prompt = (
            L1_PROMPT
            .replace("{signal_context}", signal_context)
            .replace("{old_l1}", old_l1_text)
            .replace("{recent_l2_summaries}", recent_l2_text)
        )

        try:
            raw = await self._router.route(
                "memory_encoding",
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500,
            )
        except Exception as e:
            logger.error("coarse.l1_llm_failed", error=str(e))
            return None

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
                logger.warning("coarse.l1_json_parse_failed", preview=raw_text[:100])
                return None

        portrait_text = (data.get("portrait") or "").strip()
        if not portrait_text or len(portrait_text) < 50:
            logger.warning("coarse.l1_portrait_too_short", length=len(portrait_text))
            return None

        changes = (data.get("changes") or "").strip()
        active_topics = json.dumps(data.get("active_topics", []) or [], ensure_ascii=False)
        faded_topics = json.dumps(data.get("faded_topics", []) or [], ensure_ascii=False)

        source_ids = ",".join(str(s["id"]) for s in summaries[:5])

        try:
            l1_id = await self._db.insert_phase_profile(
                content=portrait_text,
                version=old_version + 1,
                source_event_ids=source_ids,
                active_topics=active_topics,
                faded_topics=faded_topics,
                change_log=changes,
            )
        except Exception as e:
            logger.error("coarse.l1_db_write_failed", error=str(e))
            return None

        logger.info(
            "coarse.l1_generated",
            l1_id=l1_id,
            version=old_version + 1,
            length=len(portrait_text),
        )
        return l1_id

    # ═══════════════════════════════════════════════════════
    # L0 阈值 + 生成
    # ═══════════════════════════════════════════════════════

    async def _should_trigger_l0(self) -> tuple[bool, str]:
        """判断是否应触发 L0 核心画像重审。"""
        try:
            l1_history = await self._db.get_phase_profile_history(limit=10)
            if len(l1_history) < L0_TRIGGER_VERSIONS:
                return False, f"l1_versions={len(l1_history)} < {L0_TRIGGER_VERSIONS}"
            return True, f"l1_versions={len(l1_history)} >= {L0_TRIGGER_VERSIONS}"
        except Exception as e:
            logger.warning("coarse.l0_threshold_check_failed", error=str(e))
            return False, str(e)

    async def _coarse_to_l0(self) -> int | None:
        """L1 历史 → L0 核心画像。"""
        try:
            l1_history = await self._db.get_phase_profile_history(limit=10)
            if len(l1_history) < L0_TRIGGER_VERSIONS:
                return None
        except Exception as e:
            logger.warning("coarse.l0_fetch_history_failed", error=str(e))
            return None

        # 获取旧 L0
        old_l0 = await self._db.get_latest_core_profile()
        old_l0_text = old_l0.get("content", "") if old_l0 else "（这是第一次写对伙伴的核心印象）"
        old_stable_traits = old_l0.get("stable_traits", "") if old_l0 else ""
        old_version = old_l0.get("version", 0) if old_l0 else 0

        # 格式化 L1 历史
        l1_lines = []
        for h in l1_history[:8]:
            content = h.get("content", "")
            if content and len(content) > 20:
                l1_lines.append(f"· [v{h.get('version', '?')}] {content[:300]}")

        l1_history_text = "\n\n".join(l1_lines) if l1_lines else "（无历史数据）"

        # 构建 prompt（使用 .replace() 避免用户文本中的花括号被误解析）
        prompt = (
            L0_PROMPT
            .replace("{l1_history}", l1_history_text)
            .replace("{old_l0}", old_l0_text)
            .replace("{old_stable_traits}", old_stable_traits or "（这是第一次生成核心画像）")
        )

        try:
            raw = await self._router.route(
                "memory_encoding",
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=1500,
            )
        except Exception as e:
            logger.error("coarse.l0_llm_failed", error=str(e))
            return None

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
                logger.warning("coarse.l0_json_parse_failed", preview=raw_text[:100])
                return None

        portrait_text = (data.get("portrait") or "").strip()
        if not portrait_text or len(portrait_text) < 50:
            logger.warning("coarse.l0_portrait_too_short", length=len(portrait_text))
            return None

        changes = (data.get("changes") or "").strip()
        stable_traits = (data.get("stable_traits") or "").strip()

        source_l1_ids = ",".join(str(h["id"]) for h in l1_history[:5])

        try:
            l0_id = await self._db.insert_core_profile(
                content=portrait_text,
                version=old_version + 1,
                source_l1_ids=source_l1_ids,
                stable_traits=stable_traits,
                change_log=changes,
            )
        except Exception as e:
            logger.error("coarse.l0_db_write_failed", error=str(e))
            return None

        logger.info(
            "coarse.l0_generated",
            l0_id=l0_id,
            version=old_version + 1,
            length=len(portrait_text),
            stable_traits=stable_traits[:80] if stable_traits else "",
        )
        return l0_id

    # ═══════════════════════════════════════════════════════
    # 信号上下文构建（Phase 4）
    # ═══════════════════════════════════════════════════════

    @staticmethod
    def _build_signal_context(signals) -> str:
        """
        构建信号上下文 — 仅注入有意义的非空信号。
        空字符串的信号（数据不足/无意义）不注入 prompt。
        """
        parts = []

        if signals.emotion_trajectory:
            parts.append(f"关于伙伴的情绪状态——{signals.emotion_trajectory}")

        if signals.tool_usage:
            parts.append(f"伙伴最近用了这些功能——{signals.tool_usage}")

        if signals.time_pattern:
            parts.append(f"伙伴的聊天习惯——{signals.time_pattern}")

        if signals.affection_trend:
            parts.append(f"人家和伙伴的关系——{signals.affection_trend}")

        if signals.session_boundaries:
            parts.append(f"跨会话的话题——{signals.session_boundaries}")

        # 标注数据新鲜度
        if parts and signals.generated_at > 0:
            import datetime
            ts = datetime.datetime.fromtimestamp(
                signals.generated_at
            ).strftime("%m月%d日")
            parts.insert(0, f"（以下信息来自{ts}的系统分析）")

        return "\n".join(parts) if parts else ""

    # ═══════════════════════════════════════════════════════
    # force_coarse_all — 强制级联粗粒化
    # ═══════════════════════════════════════════════════════

    async def force_coarse_all(self) -> str | None:
        """
        跳过阈值门控，强制执行完整级联：L2 → L1 → L0。

        返回 L0 > L1 > L2 中第一个成功生成的内容。
        用于破冰路径（_icebreaker_consolidate）、
        每周日 cron 安全网、以及手动触发。
        """
        logger.info("coarse.force_all_start")

        # Step 1: L2（强制，忽略阈值）
        l2_id = await self._coarse_to_l2()
        if not l2_id:
            logger.info("coarse.force_all_no_l2", reason="微事件不足或 LLM 失败")
            return None

        # Step 2: L1（条件：有足够 L2 摘要）
        l1_id = await self._coarse_to_l1()
        l1_content = None
        if l1_id:
            l1 = await self._db.get_latest_phase_profile()
            if l1:
                l1_content = l1.get("content", "")

        # Step 3: L0（条件：L1 版本足够）
        l0_id = await self._coarse_to_l0()
        if l0_id:
            l0 = await self._db.get_latest_core_profile()
            if l0:
                logger.info("coarse.force_all_done", l0_id=l0_id, l1_id=l1_id)
                return l0.get("content", "")

        # 回退：返回 L1 或 L2
        if l1_content:
            logger.info("coarse.force_all_done_l1", l1_id=l1_id)
            return l1_content

        # 回退到 L2
        try:
            summaries = await self._db.get_recent_session_summaries(limit=1)
            if summaries:
                content = summaries[0].get("content", "")
                logger.info("coarse.force_all_done_l2", l2_id=l2_id)
                return content
        except Exception as e:
            logger.warning("coarse.force_all_read_failed", l2_id=l2_id, error=str(e))

        return None
