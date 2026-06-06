"""
InternalEvent — 全系统统一消息结构

Gateway 产出 → Agent 消费，一个 InternalEvent 贯穿全链路。
后续阶段扩展字段不破坏兼容性。
"""
import uuid
import time
from dataclasses import dataclass, field


@dataclass
class InternalEvent:
    """Gateway 层处理后产出的标准事件"""
    
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = field(default_factory=time.time)
    source: str = ""           # "console" | "http" | 将来 "wechat"
    user_id: str = ""          # 发送者标识
    payload: str = ""          # 用户原始消息文本
    images: list[str] = field(default_factory=list)  # 图片 URL 列表（单图，仅第一张处理）
    sticker: dict | None = None  # 用户发送的表情包 {id, file} 或 None
    is_owner: bool = False     # Gateway 层白名单判定，Agent 信任此字段
    
    def summary(self) -> str:
        """日志友好的摘要"""
        has_images = bool(self.images)
        has_sticker = bool(self.sticker)
        return (
            f"Event({self.event_id[:8]}..) "
            f"src={self.source} "
            f"user={self.user_id} "
            f"owner={self.is_owner} "
            f"msg={self.payload[:50]}..."
            f"{' [img]' if has_images else ''}"
            f"{' [stk]' if has_sticker else ''}"
        )
