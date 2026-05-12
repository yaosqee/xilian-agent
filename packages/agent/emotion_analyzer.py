"""
EmotionAnalyzer — 情感分析模块

用 DeepSeek V4-Flash 做专一任务：输入用户消息，输出结构化情绪标注 JSON。
分析异步执行（fire-and-forget），不阻塞主回复。

11 维情绪维度：喜悦 悲伤 愤怒 焦虑 平静 期待 疲惫 孤独 感激 好奇 恐惧
"""
import json
import re
import asyncio
from loguru import logger

# 11 维情绪维度常量
EMOTION_DIMENSIONS = [
    "喜悦", "悲伤", "愤怒", "焦虑", "平静",
    "期待", "疲惫", "孤独", "感激", "好奇", "恐惧",
]

# ── 情感分析专用 System Prompt ──────────────────────────

_ANALYSIS_SYSTEM_PROMPT = (
    "你是情感观察者。感受消息里的情绪流动，对以下维度独立打分"
    "（0=无，1=极强，可混合）：\n"
    "喜悦、悲伤、愤怒、焦虑、平静、期待、疲惫、孤独、感激、好奇、恐惧\n\n"
    "规则：\n"
    "1. 各维度独立，不必互斥\n"
    "2. 主情绪取最高分维度\n"
    "3. possible_cause 简短推断原因（≤20字）\n"
    "4. need 简短推断心理需求（≤15字）\n\n"
    "只返回 JSON，不解释：\n"
    '{"primary_emotion":"...","primary_intensity":0.0,'
    '"dimensions":{"喜悦":0.0,"悲伤":0.0,"愤怒":0.0,"焦虑":0.0,"平静":0.0,'
    '"期待":0.0,"疲惫":0.0,"孤独":0.0,"感激":0.0,"好奇":0.0,"恐惧":0.0},'
    '"possible_cause":"...","need":"..."}'
)


class EmotionAnalyzer:
    """情感分析器 — 无状态，每次 analyze() 独立调用 DeepSeek API"""

    def __init__(self, model_router):
        self.router = model_router

    # ============================================================
    # 核心方法
    # ============================================================

    async def analyze(self, user_message: str) -> dict | None:
        """
        分析用户消息的情感状态。

        Args:
            user_message: 用户原始消息文本

        Returns:
            11 维情绪标注 dict，解析/调用失败时返回 None
        """
        if not user_message or not user_message.strip():
            logger.debug("emotion.analyze_skip_empty")
            return None

        messages = self._build_analysis_prompt(user_message)

        # 第一次调用
        raw = await self._call_model(messages)
        if raw is None:
            return None

        result = self._parse_response(raw)
        if result is not None:
            logger.debug(
                "emotion.analyzed",
                primary=result.get("primary_emotion"),
                intensity=result.get("primary_intensity"),
            )
            return result

        # 重试一次
        logger.debug("emotion.retry_parse")
        raw = await self._call_model(messages)
        if raw is None:
            return None

        result = self._parse_response(raw)
        if result is not None:
            logger.debug(
                "emotion.analyzed_retry_ok",
                primary=result.get("primary_emotion"),
            )
            return result

        logger.warning("emotion.parse_failed_after_retry")
        return None

    # ============================================================
    # Prompt 构造
    # ============================================================

    def _build_analysis_prompt(self, user_message: str) -> list[dict]:
        """构造情感分析专用 messages（system + user）"""
        return [
            {"role": "system", "content": _ANALYSIS_SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]

    # ============================================================
    # 模型调用
    # ============================================================

    async def _call_model(self, messages: list[dict]) -> str | None:
        """
        调用 DeepSeek V4-Flash 获取原始回复。

        路由到 "emotion_analysis" 任务类型 → DS V4-Flash（结构化 JSON 提取，Flash 足够）。
        """
        try:
            result = await self.router.route(
                "emotion_analysis",
                messages,
                temperature=0.3,
                timeout=30,
            )
            return result if isinstance(result, str) else str(result)
        except asyncio.TimeoutError:
            logger.warning("emotion.timeout")
            return None
        except Exception as e:
            logger.warning("emotion.model_call_failed", error=str(e))
            return None

    # ============================================================
    # JSON 解析 + 校验
    # ============================================================

    def _parse_response(self, raw: str) -> dict | None:
        """
        解析模型返回的原始文本为情绪标注 dict。

        容错策略：
        1. 直接 json.loads
        2. 尝试提取 markdown code block 内容再 json.loads
        3. 尝试正则提取最外层 JSON 对象
        4. 全部失败 → None
        """
        # Step 1: 直接解析
        result = self._try_json_parse(raw)
        if result:
            return result

        # Step 2: 提取 markdown code block
        md_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL
        )
        if md_match:
            result = self._try_json_parse(md_match.group(1))
            if result:
                return result

        # Step 3: 正则提取最外层 {...}
        brace_match = re.search(r"\{.*\}", raw, re.DOTALL)
        if brace_match:
            result = self._try_json_parse(brace_match.group(0))
            if result:
                return result

        logger.debug("emotion.parse_all_failed", raw_preview=raw[:200])
        return None

    def _try_json_parse(self, text: str) -> dict | None:
        """尝试 JSON 解析 + 校验，成功返回 dict，失败返回 None"""
        try:
            data = json.loads(text.strip())
        except (json.JSONDecodeError, TypeError):
            return None

        if not isinstance(data, dict):
            return None

        if not self._validate_dimensions(data):
            return None

        return data

    # ============================================================
    # 校验
    # ============================================================

    def _validate_dimensions(self, data: dict) -> bool:
        """
        校验情绪标注 dict 是否完整有效。

        要求：
        - dimensions 存在且为 dict
        - 11 个维度键名完全匹配
        - 每个维度值在 [0, 1] 区间
        - primary_emotion 存在
        - primary_intensity 在 [0, 1] 区间
        """
        dims = data.get("dimensions")
        if not isinstance(dims, dict):
            logger.debug("emotion.validate_missing_dimensions")
            return False

        # 校验 11 个维度
        for name in EMOTION_DIMENSIONS:
            val = dims.get(name)
            if not isinstance(val, (int, float)):
                logger.debug("emotion.validate_missing_key", key=name)
                return False
            if not (0.0 <= val <= 1.0):
                logger.debug("emotion.validate_out_of_range", key=name, val=val)
                return False

        # 校验主情绪
        primary = data.get("primary_emotion")
        if not isinstance(primary, str) or primary not in EMOTION_DIMENSIONS:
            logger.debug("emotion.validate_bad_primary", primary=primary)
            return False

        # 校验主情绪强度
        intensity = data.get("primary_intensity")
        if not isinstance(intensity, (int, float)) or not (0.0 <= intensity <= 1.0):
            logger.debug("emotion.validate_bad_intensity", intensity=intensity)
            return False

        return True
