"""
AgentCore — 昔涟的核心大脑

ActorMind 推理链（阶段 3）：
  感知 → 记忆检索 → 共情注入 → 记忆注入 → 人格加载 → 模型调用 → 响应
          ↳ 后台情感分析 + 记忆编码 + 对话日志写入

阶段 2：共情注入 + 后台情感分析
阶段 3：记忆检索注入 + 记忆编码调度 + 对话日志实际写入 + shutdown
"""
import asyncio
import os
from pathlib import Path
from loguru import logger

from ..shared.model_router import ModelRouter
from ..shared.events import InternalEvent
from ..shared.database import DatabaseManager
from .agent_context import AgentContext
from .tool_registry import ToolRegistry
from .emotion_analyzer import EmotionAnalyzer
from .memory_manager import MemoryManager


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

    def __init__(self, model_router: ModelRouter | None = None, db_path: str = "data/xilian.db"):
        self.router = model_router or ModelRouter()
        self.tool_registry = ToolRegistry()
        self.context = AgentContext()
        self._personality: str = self._load_personality()

        # 阶段 2: 情感分析
        self.emotion_analyzer = EmotionAnalyzer(self.router)
        self._pending_analysis: asyncio.Task | None = None

        # 阶段 2: 数据库预埋 → 阶段 3 实际写入
        self._db = DatabaseManager(db_path)

        # 阶段 3: 记忆管理器（需 startup() 初始化 ChromaDB 连接）
        chroma_host = os.getenv("CHROMA_HOST", "localhost")
        chroma_port = int(os.getenv("CHROMA_PORT", "8000"))
        self.memory_manager = MemoryManager(
            db=self._db,
            chroma_host=chroma_host,
            chroma_port=chroma_port,
            ollama_client=self.router.ollama,
            model_router=self.router,
        )

        logger.info(
            "AgentCore 就绪",
            personality_length=len(self._personality),
            tools_registered=len(self.tool_registry),
            db_path=str(self._db.db_path),
        )

    # ============================================================
    # 生命周期
    # ============================================================

    async def startup(self) -> None:
        """启动初始化：DB 连接 + 记忆模块启动 + 修复 pending"""
        await self._db.init()
        await self.memory_manager.startup()
        logger.info("agent.startup_complete")

    async def shutdown(self) -> str:
        """
        优雅关闭：编码待处理记忆 → 关闭 DB。

        Returns:
            "done" / "empty" / "failed"
        """
        # 取消 pending 的情感分析
        if self._pending_analysis and not self._pending_analysis.done():
            self._pending_analysis.cancel()

        # 记忆编码兜底
        result = await self.memory_manager.shutdown()

        # 关闭数据库
        await self._db.close()

        logger.info("agent.shutdown_complete", memory_result=result)
        return result

    # ============================================================
    # 人格加载
    # ============================================================

    def _load_personality(self) -> str:
        """从 prompts/personality_v2.md 加载系统提示"""
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

        阶段 3 流程：
          感知 → 记忆检索 → 共情注入 → 记忆注入 → 构建消息 → 模型调用 →
          后台情感分析 + 后台记忆编码 + 写入对话日志
        """
        trace_log = logger.bind(trace_id=event.event_id[:8])

        trace_log.info(
            "agent.process.start",
            source=event.source,
            owner=event.is_owner,
            msg_preview=event.payload[:80],
        )

        # ── 0. 安全 ──
        if not event.is_owner:
            trace_log.warning("agent.process.blocked")
            return ""

        # ── 1. 感知 ──
        intent = self._perceive(event.payload)
        trace_log.debug("agent.perceive", intent=intent)

        if intent.get("is_tool_request"):
            reply = TOOL_PLACEHOLDER
            self.context.add_message("user", event.payload)
            self.context.add_message("assistant", reply)
            trace_log.info("agent.process.done", reply_preview=reply[:60])
            return reply

        # ── 2. 记忆检索 (NEW) ──
        self.memory_manager.signal_new_message()
        self.context.memory_retrieval = await self._retrieve_memories(event.payload)

        # ── 3. 共情注入 ──
        empathy_text = self._inject_empathy()

        # ── 4. 记忆注入 (NEW) ──
        memory_text = self.context.inject_memory_context()

        # ── 5. 构建消息 ──
        messages = self._build_messages(event.payload, empathy_text, memory_text)

        # ── 6. 模型调用 ──
        try:
            result = await self.router.route(
                "chat",
                messages,
                temperature=0.8,
                stream=stream,
            )
            if stream:
                reply = "[stream]"
                trace_log.info("agent.process.stream_started")
            else:
                reply = self._clean_reply(result)
        except Exception as e:
            trace_log.error("agent.process.model_error", error=str(e))
            reply = DEGRADED_REPLY

        # ── 7. 后台情感分析 ──
        self._schedule_emotion_analysis(event.payload)

        # ── 8. 后台记忆编码 (NEW) ──
        self._schedule_memory_encoding()

        # ── 9. 写入对话日志 (NEW) ──
        await self._write_conversation_log(event, reply)

        # ── 10. 记录历史 ──
        self.context.add_message("user", event.payload)
        self.context.add_message("assistant", reply)

        trace_log.info(
            "agent.process.done",
            reply_preview=reply[:100],
            history_size=len(self.context.history),
            memories_retrieved=len(self.context.memory_retrieval or []),
        )

        return reply

    # ============================================================
    # ActorMind 各阶段
    # ============================================================

    def _perceive(self, payload: str) -> dict:
        """
        感知阶段：解析用户消息，提取意图/情绪基调。
        """
        intent = {
            "intent": "chat",
            "is_tool_request": False,
            "emotion_hint": "",
        }

        tool_keywords = {"帮我查", "查一下", "查询", "搜索一下", "发送邮件", "写邮件"}
        for kw in tool_keywords:
            if kw in payload:
                intent["is_tool_request"] = True
                intent["intent"] = "tool_request"
                break

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

    # ============================================================
    # 阶段 3: 记忆检索
    # ============================================================

    async def _retrieve_memories(self, user_message: str) -> list[dict] | None:
        """
        检索与当前消息相关的历史记忆。

        检索条件：
        - 用户消息长度 ≥ 5 字符（太短不触发，节省资源）
        - ChromaDB 不可用时静默跳过
        """
        if len(user_message.strip()) < 5:
            return None

        try:
            results = await self.memory_manager.retrieve_memories(user_message, k=3)
            if results:
                logger.debug("memory.retrieved", count=len(results))
            return results if results else None
        except Exception as e:
            logger.warning("memory.retrieval_failed", error=str(e))
            return None

    def _schedule_memory_encoding(self):
        """
        触发后台记忆编码（三层调度）。
        对话太短（< 4 条消息）时不触发。
        """
        if len(self.context.history) < 4:
            return

        recent_exchanges = self.context.get_last_n(6)
        emotion = self.context.emotion_snapshot

        conversation_context = {
            "exchanges": recent_exchanges,
            "emotion": emotion,
        }

        asyncio.create_task(
            self.memory_manager.schedule_encoding(conversation_context)
        )

    async def _write_conversation_log(self, event: InternalEvent, reply: str):
        """每次对话后实际写入 conversation_logs（阶段 2 建表，阶段 3 写入）"""
        try:
            snap = self.context.emotion_snapshot
            await self._db.insert_log(
                event_id=event.event_id,
                user_message=event.payload,
                assistant_reply=reply,
                emotion_label=snap,
                emotion_primary=snap.get("primary_emotion") if snap else None,
                emotion_intensity=snap.get("primary_intensity") if snap else None,
                user_id=event.user_id,
                source=event.source,
            )
        except Exception as e:
            logger.warning("database.log_write_failed", error=str(e))

    # ============================================================
    # 上下文注入（向后兼容）
    # ============================================================

    def _inject_context(self) -> str:
        """拼接情绪上下文 + 记忆检索内容（向后兼容路径）"""
        parts = []
        emotion = self.context.inject_emotion_context()
        if emotion:
            parts.append(emotion)
        memory = self.context.inject_memory_context()
        if memory:
            parts.append(memory)
        return "\n".join(parts) if parts else ""

    # ============================================================
    # 消息构建
    # ============================================================

    def _build_messages(
        self,
        user_msg: str,
        empathy_text: str = "",
        memory_text: str = "",
    ) -> list[dict]:
        """
        构建模型输入消息列表：
          系统提示 = 人格 + 记忆上下文 + 共情上下文
        """
        system_prompt = self._personality

        # 记忆在前（更底层的历史背景）
        if memory_text:
            system_prompt += f"\n\n{memory_text}"

        # 共情在后（当前情绪感知）
        if empathy_text:
            system_prompt += f"\n\n{empathy_text}"

        messages = [{"role": "system", "content": system_prompt}]

        history = self.context.get_messages(limit=20)
        messages.extend(history)

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
        """重置会话（取消 pending 分析 + 清空历史 + 上下文）"""
        if self._pending_analysis and not self._pending_analysis.done():
            self._pending_analysis.cancel()
            self._pending_analysis = None
        self.context.clear()
        logger.info("agent.session_reset")

    # ============================================================
    # 阶段 2: 情感分析管道
    # ============================================================

    def _inject_empathy(self) -> str:
        """
        从 context.emotion_snapshot 读取上一轮情感分析结果，
        生成昔涟风格的动态共情段落。
        """
        snap = self.context.emotion_snapshot
        if not snap:
            return ""

        emotion = snap.get("primary_emotion", "")
        cause = snap.get("possible_cause", "")
        need = snap.get("need", "")

        if not emotion:
            return ""

        prompt = "[共情感知]\n"
        prompt += f"伙伴刚才似乎有些{emotion}呢"
        if cause:
            prompt += f"，可能是因为{cause}"
        prompt += "。"
        if need:
            prompt += f"伙伴现在需要的或许是{need}。"
        prompt += "在回复中自然地回应这份情绪，不必刻意提起，让它像涟漪一样轻轻扩散。\n"

        return prompt

    def _schedule_emotion_analysis(self, user_message: str) -> None:
        """启动后台情感分析任务（fire-and-forget）"""
        if self._pending_analysis and not self._pending_analysis.done():
            self._pending_analysis.cancel()

        self._pending_analysis = asyncio.create_task(
            self._run_emotion_analysis(user_message)
        )

    async def _run_emotion_analysis(self, user_message: str) -> None:
        """后台执行情感分析 + 存储结果到 context.emotion_snapshot"""
        try:
            result = await self.emotion_analyzer.analyze(user_message)
            if result:
                self.context.emotion_snapshot = result
                logger.debug(
                    "emotion.snapshot_updated",
                    emotion=result.get("primary_emotion"),
                )
        except asyncio.CancelledError:
            logger.debug("emotion.analysis_cancelled")
        except Exception as e:
            logger.warning("emotion.analysis_failed", error=str(e))

    @property
    def personality_preview(self) -> str:
        """返回人格提示前 200 字符（调试用）"""
        return self._personality[:200] + "..."
