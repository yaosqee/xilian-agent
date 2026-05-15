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
from ..shared.vector_store import VectorStore
from .agent_context import AgentContext
from .tool_registry import ToolRegistry
from .emotion_analyzer import EmotionAnalyzer
from .emotion_core import EmotionEngine
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


def _sanitize_surrogates(text: str) -> str:
    r"""
    清理 WSL/终端传入的 lone surrogate 字符。
    
    WSL 的 stdin 可能把 emoji 编码为 U+DCxx 前缀的 lone surrogates，
    这会导致 JSON 序列化失败（OpenAI API）和 loguru 日志写入失败。
    此函数将 lone surrogates 替换为 U+FFFD。
    """
    try:
        return text.encode("utf-8", errors="surrogateescape").decode("utf-8", errors="replace")
    except Exception:
        # 极端情况：替换不可编码字符
        return text.encode("ascii", errors="replace").decode("ascii")


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

        # 阶段 4: PAD 情感引擎
        self.emotion_engine: EmotionEngine = EmotionEngine(
            model_router=self.router,
        )

        # 阶段 5: 人格漂移检测 + 时间感知
        self._drift_counter: int = 0
        self._last_interaction_time: float = 0.0

        # 阶段 2: 数据库预埋 → 阶段 3 实际写入
        self._db = DatabaseManager(db_path)

        # 阶段 3: 记忆管理器（sqlite-vec 零外部依赖，conn 在 startup 中注入）
        self._vector_store: VectorStore | None = None
        self.memory_manager: MemoryManager | None = None

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
        """启动初始化：DB 连接 + 向量存储 + 记忆模块启动 + 修复 pending"""
        await self._db.init()

        # VectorStore 独立连接（sqlite-vec 扩展需要直接操作 sqlite3）
        self._vector_store = VectorStore(db_path=str(self._db.db_path))
        await self._vector_store.init()

        self.memory_manager = MemoryManager(
            db=self._db,
            vector_store=self._vector_store,
            model_router=self.router,
        )
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
        result = "empty"
        if self.memory_manager:
            result = await self.memory_manager.shutdown()

        # 关闭数据库
        await self._db.close()

        logger.info("agent.shutdown_complete", memory_result=result)
        return result

    # ============================================================
    # 人格加载
    # ============================================================

    def _load_personality(self) -> str:
        """从 prompts/personality_v3.md 加载系统提示"""
        prompt_path = (
            Path(__file__).resolve().parent.parent.parent
            / "prompts" / "personality_v3.md"
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

        # ── 0. 输入清洗：修复 WSL/终端传入的 lone surrogate 字符 ──
        event.payload = _sanitize_surrogates(event.payload)

        trace_log.info(
            "agent.process.start",
            source=event.source,
            owner=event.is_owner,
            msg_preview=event.payload[:80],
        )

        # ── 1. 安全 ──
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
        if self.memory_manager:
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

        # 阶段 5: 人格漂移检测 + 记录交互时间
        self._check_personality_drift(reply)
        self.mark_interaction()

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
            if not self.memory_manager:
                return None
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

        if not self.memory_manager:
            return

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
        构建模型输入消息列表（前缀缓存友好结构）：
          [system: 纯人格] → [历史消息] → [动态注入 + 用户消息]

        优化要点：
        - 系统提示只含静态人格，永远不变 → 前缀缓存 100% 命中
        - 历史消息与前一轮 95% 一致 → 高缓存命中率
        - 记忆/共情注入收到底部用户消息中 → 只有这部分每轮重新推理

        v3: 2026-05-14 从前缀混入改为底部注入
        """
        # 纯静态系统提示（前缀缓存友好）
        messages = [{"role": "system", "content": self._personality}]

        # 历史消息（与前一轮前缀高度一致）
        history = self.context.get_messages(limit=20)
        messages.extend(history)

        # 动态注入 + 用户消息收到底部
        user_content = user_msg
        if memory_text or empathy_text:
            context_parts = []
            if memory_text:
                context_parts.append(memory_text)
            if empathy_text:
                context_parts.append(empathy_text)
            context = "\n\n".join(context_parts)
            user_content = f"{context}\n\n---\n\n{user_msg}"

        messages.append({"role": "user", "content": user_content})

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
        从 context.emotion_snapshot 读取 PAD 情绪状态，
        生成昔涟视角的心境感知（注入到伙伴消息下方的背景中）。
        """
        snap = self.context.emotion_snapshot
        if not snap:
            return ""

        emotion = snap.get("primary_emotion", "")
        if not emotion:
            return ""

        # 心境底色描述（不说教，只告知）
        mood_map: dict[str, str] = {
            "快乐": "心里亮亮的", "悲伤": "心有点沉", "愤怒": "心里有团火",
            "恐惧": "心里发紧", "惊讶": "心里一亮", "厌恶": "心头不悦",
            "信任": "心是安稳的", "期待": "心在轻轻跳动",
            "焦虑": "心里有一小片乌云", "平静": "心像无风的湖面",
            "兴奋": "心跳在加速",
        }
        mood = mood_map.get(emotion, f"心里泛起了{emotion}的涟漪")

        return f"[伙伴的心境] {mood}。不必刻意分析他的情绪，去感受他便好。\n"

    def _schedule_emotion_analysis(self, user_message: str) -> None:
        """启动后台情感分析任务（fire-and-forget）"""
        if self._pending_analysis and not self._pending_analysis.done():
            self._pending_analysis.cancel()

        self._pending_analysis = asyncio.create_task(
            self._run_emotion_analysis(user_message)
        )

    async def _run_emotion_analysis(self, user_message: str) -> None:
        """
        后台执行情感分析 + PAD 情绪更新。

        两条管道并行（不互相阻塞）：
        ① EmotionEngine（阶段4）：appraisal → PAD → 连续状态更新 → DB
        ② ~~EmotionAnalyzer（阶段2）~~：已被 PAD 管道取代
        """
        try:
            # ── 阶段 4: PAD 情感引擎 ──
            pad_profile = await self.emotion_engine.process_message(user_message)
            if pad_profile:
                # 存储 PAD 结果到 context（兼容旧的 emotion_snapshot 字段）
                self.context.emotion_snapshot = pad_profile

                # 写入 DB 情感快照
                if self._db and self._db._conn:
                    appraisal = pad_profile.get("appraisal", {})
                    await self._db.insert_emotion_snapshot(
                        pad_p=self.emotion_engine.state.pad_p,
                        pad_a=self.emotion_engine.state.pad_a,
                        pad_d=self.emotion_engine.state.pad_d,
                        primary_emotion=pad_profile.get("primary_emotion"),
                        primary_intensity=pad_profile.get("primary_intensity", 0.0),
                        dimensions=pad_profile.get("dimensions"),
                        appraisal_relevance=appraisal.get("relevance"),
                        appraisal_facilitation=appraisal.get("facilitation"),
                        appraisal_coping=appraisal.get("coping"),
                        source=appraisal.get("source", "llm"),
                    )

                logger.debug(
                    "emotion.pad_updated",
                    pad=f"({self.emotion_engine.state.pad_p:.2f},{self.emotion_engine.state.pad_a:.2f},{self.emotion_engine.state.pad_d:.2f})",
                    emotion=pad_profile.get("primary_emotion"),
                )
        except asyncio.CancelledError:
            logger.debug("emotion.analysis_cancelled")
        except Exception as e:
            logger.warning("emotion.analysis_failed", error=str(e))

    @property
    def personality_preview(self) -> str:
        """返回人格提示前 200 字符（调试用）"""
        return self._personality[:200] + "..."

    # ============================================================
    # 阶段 5: 时间感知问候 + 人格漂移检测
    # ============================================================

    def get_time_greeting(self) -> str:
        """
        根据当前时间和上次对话时间生成自然问候。
        """
        from datetime import datetime
        now = datetime.now()
        hour = now.hour
        last_seen = self._last_interaction_time
        hours_ago = (now.timestamp() - last_seen) / 3600 if last_seen else 999

        if 5 <= hour < 12:
            time_phrase = "早安"
        elif 12 <= hour < 18:
            time_phrase = "下午好"
        elif 18 <= hour < 23:
            time_phrase = "晚上好"
        else:
            time_phrase = "夜深了呢"

        if hours_ago > 168:
            gap = "好久不见！"
        elif hours_ago > 48:
            gap = f"离上次聊天过了{hours_ago:.0f}小时呢～"
        elif hours_ago > 8:
            gap = "今天过得怎么样？"
        else:
            gap = ""

        greeting = f"{time_phrase}，伙伴。"
        if gap:
            greeting += f" {gap}"
        return greeting

    def _check_personality_drift(self, reply: str) -> None:
        """
        检查回复是否含有人格特征标记。连续 3 轮无特征 → 告警。
        """
        markers = [
            "人家", "伙伴", "……♪", "~♪", "呢", "呀",
            "涟漪", "书", "页", "花", "星", "秋千", "麦田",
        ]
        has_marker = any(m in reply for m in markers)

        if has_marker:
            self._drift_counter = 0
        else:
            self._drift_counter += 1

        if self._drift_counter >= 3:
            from loguru import logger
            logger.warning(
                "personality.drift_warning",
                counter=self._drift_counter,
                reply_preview=reply[:80],
            )

    def mark_interaction(self) -> None:
        """记录本次交互时间（每轮对话后调用）"""
        import time as _time
        self._last_interaction_time = _time.time()
