"""
AgentCore — 昔涟的核心大脑

ActorMind 推理链（5 阶段）：
  感知 → 上下文注入 → 人格加载 → 模型调用 → 响应包装

本阶段（阶段 1）上下文注入为空壳，工具调用仅返回占位语，
后续阶段逐步填充情绪引擎、记忆检索、工具执行。
"""
from pathlib import Path
from loguru import logger

from ..shared.model_router import ModelRouter
from ..shared.events import InternalEvent
from .agent_context import AgentContext
from .tool_registry import ToolRegistry


# ── 降级回复（模型不可用时的友好提示） ──────────────────────

DEGRADED_REPLY = (
    "人家现在有点累呢……好像一时间说不出话来。"
    "伙伴能等一小会儿吗？"
)

TOOL_PLACEHOLDER = (
    "这个功能人家还在学习呢……"
    "伙伴再等等好不好？等学会了，一定马上帮你~ ♪"
)


class AgentCore:
    """昔涟的核心引擎，接收 InternalEvent，返回文本回复"""

    def __init__(self, model_router: ModelRouter | None = None):
        self.router = model_router or ModelRouter()
        self.tool_registry = ToolRegistry()
        self.context = AgentContext()
        self._personality: str = self._load_personality()

        logger.info(
            "AgentCore 就绪",
            personality_length=len(self._personality),
            tools_registered=len(self.tool_registry),
        )

    # ============================================================
    # 人格加载
    # ============================================================

    def _load_personality(self) -> str:
        """从 prompts/personality_v1.md 加载系统提示"""
        # 从 packages/agent/ → 项目根目录
        prompt_path = (
            Path(__file__).resolve().parent.parent.parent
            / "prompts" / "personality_v2.md"
        )
        try:
            content = prompt_path.read_text(encoding="utf-8")
            logger.debug("人格提示加载成功", path=str(prompt_path), length=len(content))
            return content
        except FileNotFoundError:
            logger.error("人格提示文件缺失", path=str(prompt_path))
            # 回退：一个极简的系统提示
            return "你是昔涟。用温柔、轻盈的方式和伙伴说话。"

    # ============================================================
    # 主入口：process()
    # ============================================================

    async def process(
        self,
        event: InternalEvent,
        stream: bool = False,
    ) -> str:
        """
        处理一条用户消息，返回昔涟的回复。

        Args:
            event: Gateway 产出的标准事件
            stream: 是否流式返回（True 时返回 generator/stream 对象）

        Returns:
            昔涟的文本回复（或流对象，取决于 stream 参数）
        """
        # 绑定 trace_id 用于全链路日志
        trace_log = logger.bind(trace_id=event.event_id[:8])

        trace_log.info(
            "agent.process.start",
            source=event.source,
            owner=event.is_owner,
            msg_preview=event.payload[:80],
        )

        # ── 0. 安全：非主人消息直接忽略 ──
        if not event.is_owner:
            trace_log.warning("agent.process.blocked — 非主人消息")
            return ""

        # ── 1. 感知阶段 ──
        intent = self._perceive(event.payload)
        trace_log.debug("agent.perceive", intent=intent)

        # ── 1.5 工具意图检测 ──
        if intent.get("is_tool_request"):
            trace_log.info(
                "agent.tool_request",
                payload=event.payload[:80],
                tools_available=list(self.tool_registry.tool_names),
            )
            reply = TOOL_PLACEHOLDER
            self.context.add_message("user", event.payload)
            self.context.add_message("assistant", reply)
            trace_log.info("agent.process.done", reply_preview=reply[:60])
            return reply

        # ── 2. 上下文注入（空壳，阶段 3-4 填充） ──
        injected = self._inject_context()

        # ── 3. 人格 + 上下文 → 消息列表 ──
        messages = self._build_messages(event.payload, injected)

        # ── 4. 模型调用 ──
        try:
            result = await self.router.route(
                "chat",
                messages,
                temperature=0.8,  # 昔涟需要高温度保持语言灵动
                stream=stream,
            )
            if stream:
                # 流式响应直接返回（stream 对象），调用方负责消费
                reply = "[stream]"
                trace_log.info("agent.process.stream_started")
            else:
                reply = result
                # ── 5. 响应包装 ──
                reply = self._clean_reply(reply)

        except Exception as e:
            trace_log.error("agent.process.model_error", error=str(e))
            reply = DEGRADED_REPLY

        # ── 5. 记录历史 + 日志 ──
        self.context.add_message("user", event.payload)
        self.context.add_message("assistant", reply)

        trace_log.info(
            "agent.process.done",
            reply_preview=reply[:100],
            history_size=len(self.context.history),
        )

        return reply

    # ============================================================
    # ActorMind 各阶段
    # ============================================================

    def _perceive(self, payload: str) -> dict:
        """
        感知阶段：解析用户消息，提取意图/情绪基调。

        本阶段用简单启发式，后续阶段 2-4 替换为 LLM 情感分析。

        Returns:
            {"intent": str, "is_tool_request": bool, "emotion_hint": str}
        """
        intent = {
            "intent": "chat",
            "is_tool_request": False,
            "emotion_hint": "",
        }

        # 工具意图检测：关键词匹配（后续阶段由 LLM 判定）
        tool_keywords = {"帮我查", "查一下", "查询", "搜索一下", "发送邮件", "写邮件"}
        for kw in tool_keywords:
            if kw in payload:
                intent["is_tool_request"] = True
                intent["intent"] = "tool_request"
                break

        # 情绪基调简单判断（后续替换为 LLM 分析）
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

    def _inject_context(self) -> str:
        """
        上下文注入：拼接情绪上下文 + 记忆检索内容。

        阶段 1 返回空字符串，阶段 3-4 由对应模块填充。
        """
        parts = []

        # 阶段 4：情绪上下文
        emotion = self.context.inject_emotion_context()
        if emotion:
            parts.append(emotion)

        # 阶段 3：记忆上下文
        memory = self.context.inject_memory_context()
        if memory:
            parts.append(memory)

        return "\n".join(parts) if parts else ""

    def _build_messages(self, user_msg: str, injected_context: str) -> list[dict]:
        """
        构建模型输入消息列表：
          系统提示（人格 + 可选动态注入） + 对话历史 + 当前用户消息
        """
        # 系统提示 = 人格 + 动态注入（如果有）
        system_prompt = self._personality
        if injected_context:
            system_prompt += f"\n\n[当前上下文]\n{injected_context}"

        messages = [{"role": "system", "content": system_prompt}]

        # 注入对话历史（最近 N 条）
        history = self.context.get_messages(limit=20)
        messages.extend(history)

        # 当前用户消息
        messages.append({"role": "user", "content": user_msg})

        return messages

    # ============================================================
    # 工具方法
    # ============================================================

    def _clean_reply(self, raw: str) -> str:
        """清洗模型输出：去首尾空白，保证非空"""
        cleaned = raw.strip()
        if not cleaned:
            return "……♪"
        return cleaned

    def reset_session(self) -> None:
        """重置会话（清空历史 + 上下文）"""
        self.context.clear()
        logger.info("agent.session_reset")

    @property
    def personality_preview(self) -> str:
        """返回人格提示前 200 字符（调试用）"""
        return self._personality[:200] + "..."
