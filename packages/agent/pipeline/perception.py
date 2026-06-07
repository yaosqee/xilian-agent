"""
PerceptionProcessor — 感知阶段：从用户消息中提取情绪基调

这是最小的 ServiceModule 子类，仅用于验证提取模式。
"""

from ._base import ServiceModule


class PerceptionProcessor(ServiceModule):
    """感知阶段处理器。纯函数，无外部依赖。"""

    def perceive(self, payload: str) -> dict:
        """
        感知阶段：提取情绪基调（工具选择交由 LLM function calling）。

        Returns:
            {"intent": str, "emotion_hint": str}
        """
        intent = {
            "intent": "chat",
            "emotion_hint": "",
        }

        positive = {"开心", "高兴", "好耶", "哈哈", "太棒了", "喜欢", "爱"}
        negative = {"难过", "累", "烦", "焦虑", "害怕", "孤独", "不开心", "哭"}

        for w in positive:
            if w in payload:
                intent["emotion_hint"] = "positive"
                break
        if not intent["emotion_hint"]:
            for w in negative:
                if w in payload:
                    intent["emotion_hint"] = "negative"
                    break

        return intent
