"""
AgentContext — Agent 上下文容器

维护对话历史和情感/记忆模块接口。
阶段 2：情绪注入已实现，记忆检索待阶段 3 填充。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentContext:
    """Agent 运行上下文，各模块接口预留"""

    # 对话历史：简单列表 [{role, content}]
    history: list[dict] = field(default_factory=list)
    _max_history: int = 40  # 保留最近 N 条消息

    # 阶段 2：情绪快照（来自 EmotionAnalyzer 后台分析）
    emotion_snapshot: Optional[dict] = None

    # 阶段 3：记忆检索结果 [{summary, score, ...}]
    memory_retrieval: Optional[list] = None

    # 阶段 9：角色情景记忆检索结果（昔涟自己的过去）
    character_memory_retrieval: Optional[list] = None

    # 阶段 8+: 用户印象文档 + 已注入版本号
    user_portrait: Optional[str] = None
    _current_portrait_version: Optional[int] = None
    _portrait_version_injected: Optional[int] = None

    # 阶段 8+: 破冰冷启动（仅内存状态，不持久化）
    icebreaker_active: bool = False
    icebreaker_exchanges: int = 0
    icebreaker_deferred: bool = False  # 持久化标记：用户拒绝过破冰

    # ============================================================
    # 对话历史
    # ============================================================

    def add_message(self, role: str, content: str) -> None:
        """添加一条消息到历史"""
        self.history.append({"role": role, "content": content})
        # 超限时裁剪旧消息
        if len(self.history) > self._max_history:
            self.history = self.history[-self._max_history:]

    def get_messages(self, limit: int = 20) -> list[dict]:
        """返回最近 N 条消息，供构建模型输入"""
        return self.history[-limit:] if len(self.history) > limit else self.history

    def get_last_n(self, n: int = 5) -> list[dict]:
        """返回最后 N 条消息"""
        return self.history[-n:] if self.history else []

    def clear(self) -> None:
        """清空对话历史（新会话）"""
        self.history.clear()
        self.emotion_snapshot = None
        self.memory_retrieval = None
        self.character_memory_retrieval = None
        self._current_portrait_version = None
        self._portrait_version_injected = None
        self.icebreaker_active = False
        self.icebreaker_exchanges = 0

    def __repr__(self) -> str:
        return (
            f"AgentContext(history={len(self.history)} msgs, "
            f"emotion={'yes' if self.emotion_snapshot else 'no'}, "
            f"memory={'yes' if self.memory_retrieval else 'no'})"
        )
