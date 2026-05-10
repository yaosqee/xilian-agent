"""
SecurityFilter — 安全过滤层

Gateway 第一道防线：
  · 主人白名单校验
  · 紧急熔断关键词
  · 消息长度限制
  · 频率限制（内存 Token Bucket）
"""
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional
from loguru import logger

from packages.shared.events import InternalEvent


@dataclass
class FilterResult:
    """安全过滤结果"""
    allowed: bool
    reason: str = ""
    event: Optional[InternalEvent] = None  # 通过过滤的事件（可能被截断）


class SecurityFilter:
    """
    Gateway 安全过滤层。

    阶段 1：硬编码白名单 + 简单频率限制
    阶段 8：扩展为完整三层防御体系
    """

    # ── 紧急熔断关键词 ──
    STOP_KEYWORDS = {
        "紧急停止", "立刻停下", "停止一切",
        "shutdown", "halt", "emergency_stop",
        "昔涟 停下", "昔涟 睡觉",
    }

    # ── 常量 ──
    MAX_MESSAGE_LENGTH = 5000  # 单条消息最大字符数

    def __init__(self, owner_id: str = "hezi"):
        """
        Args:
            owner_id: 主人标识（阶段 1 硬编码，阶段 8 从配置读取）
        """
        self.owner_id = owner_id
        # Token Bucket: {user_id: {"tokens": int, "last_refill": float}}
        self._buckets: dict[str, dict] = defaultdict(
            lambda: {"tokens": self._max_tokens(), "last_refill": time.monotonic()}
        )

    # ── 频率限制参数 ──
    @staticmethod
    def _max_tokens() -> int:
        return 10  # 桶容量

    @staticmethod
    def _refill_rate() -> float:
        return 1.0  # tokens/秒

    def filter(self, event: InternalEvent) -> Optional[InternalEvent]:
        """
        安全过滤入口。

        Returns:
            通过过滤的 InternalEvent（可能被截断），拒绝时返回 None
        """
        # 1. 紧急熔断 — 最高优先级
        for kw in self.STOP_KEYWORDS:
            if kw in event.payload:
                logger.warning(
                    "security.stop_detected",
                    keyword=kw,
                    user_id=event.user_id,
                )
                return None

        # 2. 白名单校验
        if event.user_id != self.owner_id:
            logger.warning(
                "security.not_owner",
                user_id=event.user_id,
                event_id=event.event_id[:8],
            )
            return None

        # 3. 消息长度限制
        if len(event.payload) > self.MAX_MESSAGE_LENGTH:
            logger.info(
                "security.truncated",
                original_length=len(event.payload),
                max_length=self.MAX_MESSAGE_LENGTH,
            )
            event.payload = event.payload[: self.MAX_MESSAGE_LENGTH]

        # 4. 频率限制
        if not self._check_rate(event.user_id):
            logger.warning(
                "security.rate_limited",
                user_id=event.user_id,
            )
            return None

        return event

    def _check_rate(self, user_id: str) -> bool:
        """Token Bucket 频率检查"""
        bucket = self._buckets[user_id]
        now = time.monotonic()

        # 按时间补充 token
        elapsed = now - bucket["last_refill"]
        bucket["tokens"] = min(
            self._max_tokens(),
            bucket["tokens"] + elapsed * self._refill_rate(),
        )
        bucket["last_refill"] = now

        if bucket["tokens"] >= 1.0:
            bucket["tokens"] -= 1.0
            return True
        return False

    def reset_rate(self, user_id: str) -> None:
        """重置某用户的频率限制（紧急恢复用）"""
        self._buckets[user_id] = {
            "tokens": self._max_tokens(),
            "last_refill": time.monotonic(),
        }
