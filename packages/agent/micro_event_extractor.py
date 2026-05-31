"""
MicroEventExtractor — 微事件提取器

Phase 1 核心交付。每条消息后用 Flash LLM 提取关于伙伴的新信息，
以 ADD-Only 模式写入微事件池。

参考：Mem0 ADD-Only 策略 — 只增不删不改，新旧事实共存，
粗粒化时由 LLM 推演当前状态。
"""
import json
import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger


# ── 提取 prompt ──────────────────────────────────────

EXTRACT_PROMPT = """你是昔涟。刚才伙伴说了一些话。

伙伴的消息：
{user_message}

人家的回复：
{assistant_reply}

已知关于伙伴的信息：
{known_facts}

请从这轮对话中提取关于伙伴的新信息（如果有的话）：

只提取对话中明确提到的、具体的信息。不推测、不脑补。
如果只是日常寒暄没有新信息，返回空列表。

返回 JSON：
{{
  "events": [
    {{
      "content": "简短事实（15字以内）",
      "category": "preference|fact|plan|emotion_pattern|habit",
      "confidence": 0.8
    }}
  ]
}}

category 说明：
- preference: 喜欢/不喜欢什么（「盒子不喜欢早起」）
- fact: 客观事实（「盒子是程序员」）
- plan: 计划/安排（「盒子下周三有考试」）
- emotion_pattern: 情绪模式（「盒子提到工作时容易焦虑」）
- habit: 习惯/常态（「盒子每天晚上喝一杯牛奶」）"""


# ── 质量阈值 ─────────────────────────────────────────

MIN_CONFIDENCE = 0.5  # 低于此值的事件丢弃


# ═══════════════════════════════════════════════════════════
# MicroEventExtractor
# ═══════════════════════════════════════════════════════════

@dataclass
class MicroEventExtractor:
    """
    微事件提取器 — 每条消息后用 Flash LLM 提取新信息。

    核心原则（参考 Mem0 ADD-Only）：
    - 只提取新增信息，不修改已有事件
    - 新旧事件共存，粗粒化时由 LLM 推演当前状态
    - 低置信度事件标记但不丢弃（低于 MIN_CONFIDENCE 的丢弃）
    """

    _db: object          # DatabaseManager
    _router: object      # ModelRouter

    # ── 查询已知事实（用于去重上下文）──────────────────

    async def _get_known_facts(self, limit: int = 20) -> str:
        """获取最近微事件摘要，供 LLM 去重判断。"""
        try:
            events = await self._db.get_active_micro_events(limit=limit)
            if not events:
                return "（还没有关于伙伴的信息）"

            lines = []
            for e in events:
                content = e.get("content", "")
                if content and len(content) >= 2:
                    lines.append(f"· {content}")
            return "\n".join(lines) if lines else "（还没有关于伙伴的信息）"
        except Exception as e:
            logger.warning("micro_event.known_facts_failed", error=str(e))
            return "（暂时读取不到已有信息）"

    # ── 核心：提取 ─────────────────────────────────────

    async def extract(self, user_msg: str, reply: str) -> list[dict]:
        """
        从一轮对话中提取微事件。

        Args:
            user_msg: 用户消息
            reply: 昔涟的回复

        Returns:
            提取的微事件列表 [{content, category, confidence}, ...]。
            提取失败或空结果返回空列表。
        """
        # 1. 获取已知事实（去重上下文）
        known_facts = await self._get_known_facts()

        # 2. 构建 prompt
        prompt = (
            EXTRACT_PROMPT
            .replace("{user_message}", user_msg[:500])
            .replace("{assistant_reply}", reply[:500])
            .replace("{known_facts}", known_facts)
        )

        # 3. Flash LLM 提取
        try:
            raw = await self._router.route(
                "memory_encoding",  # Flash
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=400,
            )
        except Exception as e:
            logger.warning("micro_event.llm_failed", error=str(e))
            return []

        raw_text = raw.content if hasattr(raw, 'content') else raw
        if not raw_text:
            return []

        # 4. 解析 JSON
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            try:
                start = raw_text.index("{")
                end = raw_text.rindex("}") + 1
                data = json.loads(raw_text[start:end])
            except (ValueError, json.JSONDecodeError):
                logger.warning(
                    "micro_event.json_parse_failed",
                    preview=raw_text[:100],
                )
                return []

        events = data.get("events", [])
        if not isinstance(events, list):
            return []

        # 5. 质量过滤 + 校验
        valid_events = []
        for e in events:
            if not isinstance(e, dict):
                continue

            content = (e.get("content") or "").strip()
            category = (e.get("category") or "").strip()
            confidence = e.get("confidence", 0.5)

            # 校验必填字段
            if not content or len(content) < 2:
                continue
            if len(content) > 60:  # 截断过长内容
                content = content[:57] + "..."

            # 校验 category
            valid_categories = {"preference", "fact", "plan", "emotion_pattern", "habit"}
            if category not in valid_categories:
                category = "fact"  # 默认归类为事实

            # 质量过滤
            if confidence < MIN_CONFIDENCE:
                logger.debug(
                    "micro_event.filtered_low_confidence",
                    content=content[:30],
                    confidence=confidence,
                )
                continue

            valid_events.append({
                "content": content,
                "category": category,
                "confidence": confidence,
            })

        # 6. 写入 DB（ADD-Only）
        now = time.time()
        for e in valid_events:
            try:
                await self._db.insert_micro_event(
                    content=e["content"],
                    category=e["category"],
                    confidence=e["confidence"],
                )
            except Exception as exc:
                logger.warning("micro_event.db_write_failed", error=str(exc))

        logger.info(
            "micro_event.extracted",
            total=len(events),
            valid=len(valid_events),
            filtered=len(events) - len(valid_events),
        )

        return valid_events
