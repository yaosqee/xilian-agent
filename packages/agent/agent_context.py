"""
AgentContext — Agent 上下文容器

维护对话历史和预留未来模块接口（情绪/记忆）。
本阶段（阶段 1）只做简单消息列表，情绪和记忆接口为空壳。
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AgentContext:
    """Agent 运行上下文，各模块接口预留"""

    # 对话历史：简单列表 [{role, content}]
    history: list[dict] = field(default_factory=list)
    _max_history: int = 40  # 保留最近 N 条消息

    # 阶段 4：情绪快照 {"emotion": str, "intensity": float, "pad": (P,A,D)}
    emotion_snapshot: Optional[dict] = None

    # 阶段 3：记忆检索结果 [{summary, score, ...}]
    memory_retrieval: Optional[list] = None

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

    # ============================================================
    # 上下文注入（阶段 3-4 填充实际内容）
    # ============================================================

    def inject_emotion_context(self) -> str:
        """
        将情绪快照转为系统提示动态注入段落。
        阶段 4 实现，本阶段返回空字符串。
        """
        if self.emotion_snapshot is None:
            return ""
        # 阶段 4 TODO: 将 emotion_snapshot 转为昔涟能感知的情感提示
        return ""

    def inject_memory_context(self) -> str:
        """
        将记忆检索结果转为系统提示动态注入段落。
        阶段 3 实现，本阶段返回空字符串。
        """
        if not self.memory_retrieval:
            return ""
        # 阶段 3 TODO: 将记忆检索结果转为昔涟能引用的上下文
        return ""

    def __repr__(self) -> str:
        return (
            f"AgentContext(history={len(self.history)} msgs, "
            f"emotion={'yes' if self.emotion_snapshot else 'no'}, "
            f"memory={'yes' if self.memory_retrieval else 'no'})"
        )
