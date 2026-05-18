"""
AgentCore — 昔涟的核心大脑

ActorMind 推理链（阶段 7）：
  感知 → 记忆检索 → 共情注入 → 记忆注入 → 人格加载 → 模型调用 → 响应
          ↳ 后台情感分析 + 记忆编码 + 对话日志写入 + 自动记笔记(7b)

阶段 2：共情注入 + 后台情感分析
阶段 3：记忆检索注入 + 记忆编码调度 + 对话日志实际写入 + shutdown
阶段 7a：ContextBuilder 模块化上下文（替换手工拼接）
"""
import asyncio
import os
from pathlib import Path
from loguru import logger

from ..shared.model_router import ModelRouter
from ..shared.events import InternalEvent
from ..shared.database import DatabaseManager
from ..shared.vector_store import VectorStore
from ..shared.marker_parser import MarkerParser
from .agent_context import AgentContext
from .tool_registry import ToolRegistry
from .tool_executor import ToolExecutor
from .result_wrapper import ResultWrapper
from .emotion_analyzer import EmotionAnalyzer
from .emotion_core import EmotionEngine
from .memory_manager import MemoryManager
from .notebook_manager import NotebookManager
from .portrait_manager import PortraitManager
from .skills_loader import SkillsLoader

# 阶段 7a: 模块化上下文
from .context_builder import (
    ContextBuilder,
    DatetimeModule,
    EmotionModule,
    MemoryModule,
    NotebookModule,
    PortraitModule,
)


# ── 降级回复（模型不可用时的友好提示） ──────────────────────

DEGRADED_REPLY = (
    "人家现在有点累呢……好像一时间说不出话来。"
    "伙伴能等一小会儿吗？"
)

# TOOL_PLACEHOLDER 已移除 — 工具调用现由 LLM function calling 驱动


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
        self.tool_executor: ToolExecutor | None = None
        self.result_wrapper: ResultWrapper | None = None
        self.context = AgentContext()
        self._personality: str = self._load_personality()

        # 打磨期: 自动发现并注册 tools/ 目录下所有工具
        new_tools = self.tool_registry.autodiscover("packages.agent.tools")
        # 注册工具的结果模板（不需要 LLM 二次包装的）
        from .tools.search_memory import _register_template as _reg_sm
        from .tools.query_weather import _register_template as _reg_qw
        from .tools.search_web import _register_template as _reg_sw
        _reg_sm()
        _reg_qw()
        _reg_sw()

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

        # 阶段 8: 安全机制（审计日志 + 人设评分）
        self._round_count: int = 0
        self.is_safe_mode: bool = False

        # 好感度系统
        self._affection_score: float = 0.0
        self._affection_level: int = 1
        self._total_conversations: int = 0

        # 阶段 2: 数据库预埋 → 阶段 3 实际写入
        self._db = DatabaseManager(db_path)

        # 阶段 3: 记忆管理器（sqlite-vec 零外部依赖，conn 在 startup 中注入）
        self._vector_store: VectorStore | None = None
        self.memory_manager: MemoryManager | None = None

        # 阶段 7a: 模块化上下文构建器（v3.1: XML→自然语言）
        # 4 个模块，按优先级：datetime(1) < emotion(4) < memory(5) < notebook(6)
        self._context_builder = ContextBuilder(total_budget=800)
        self._context_builder.register(DatetimeModule())
        self._context_builder.register(PortraitModule(self.context))
        self._context_builder.register(EmotionModule(self.context))
        self._context_builder.register(MemoryModule(self.context))
        self._context_builder.register(NotebookModule())  # 7b 通过 set_notebook() 注入

        # 阶段 7b: 笔记本管理器占位（子阶段 7b 注入）
        self.notebook_manager: NotebookManager | None = None

        # 阶段 7d: 技能加载器（子阶段 7d 注入）
        self._skills_loader: SkillsLoader | None = None

        # 阶段 8+: 用户印象管理器
        self.portrait_manager: PortraitManager | None = None

        # 阶段 8+: 破冰主动问候（仅内存）
        self._icebreaker_pending: bool = False

        # 阶段 7c: 注意力调度器占位（子阶段 7c 注入）
        self.attention_scheduler = None

        # 打磨期: 工具确认回路状态
        self._pending_confirmation: dict | None = None

        logger.info(
            "AgentCore 就绪",
            personality_length=len(self._personality),
            tools_registered=len(self.tool_registry),
            db_path=str(self._db.db_path),
            context_modules=self._context_builder.module_names,
        )

    # ============================================================
    # 生命周期
    # ============================================================

    async def startup(self) -> None:
        """启动初始化：DB 连接 + 向量存储 + 记忆模块启动 + Notebook + 修复 pending"""
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

        # 阶段 7b: 初始化 NotebookManager
        if not self.notebook_manager:
            self.notebook_manager = NotebookManager(
                _db=self._db,
                _router=self.router,
            )
        # 注入 NotebookManager 到 ContextBuilder 的 NotebookModule
        nb_module = self._context_builder.get_module("notebook")
        if nb_module:
            nb_module.set_notebook(self.notebook_manager)

        # 阶段 8+: 初始化用户印象管理器 + 加载当前印象
        if not self.portrait_manager:
            self.portrait_manager = PortraitManager(
                db=self._db,
                model_router=self.router,
            )

        # 阶段 7d: 初始化技能加载器
        if not self._skills_loader:
            self._skills_loader = SkillsLoader()
            self._skills_loader.load_all()
        if not self.context.user_portrait:
            try:
                latest = await self._db.get_latest_portrait()
                if latest:
                    content = latest.get("content")
                    if content and len(content) >= 50:
                        self.context.user_portrait = content
                        self.context._current_portrait_version = latest.get("version", 1)
                        logger.info("portrait.loaded", version=latest.get("version"), len=len(content))
                    else:
                        logger.warning("portrait.loaded_but_content_invalid", has_content=bool(content), length=len(content or ""))
                else:
                    logger.info("portrait.not_found_in_db")
            except Exception as e:
                logger.warning("portrait.load_failed", error=str(e))

        # 打磨期: 初始化 ToolExecutor + ResultWrapper（依赖 memory_manager / db 已就绪）
        self.tool_executor = ToolExecutor(
            registry=self.tool_registry,
            db=self._db,
            memory_manager=self.memory_manager,
            portrait_manager=self.portrait_manager,
            notebook_manager=self.notebook_manager,
        )
        self.result_wrapper = ResultWrapper(model_router=self.router)
        logger.info("tool_system.ready", tools=self.tool_registry.tool_names,
                    executor=True, wrapper=True)

        # 检查破冰是否已被用户拒绝
        try:
            notes = await self._db.get_notebook_notes(kind="focus", limit=5)
            for n in notes:
                if n.get("content") == "icebreaker_deferred":
                    self.context.icebreaker_deferred = True
                    logger.debug("icebreaker.deferred_loaded")
                    break
        except Exception:
            pass

        # 无印象文档 → 准备破冰主动问候
        if not self.context.user_portrait:
            self._icebreaker_pending = True
            logger.info("icebreaker.pending_greeting")

        # 加载最近好感度
        try:
            latest = await self._db.get_latest_affection()
            if latest:
                self._affection_score = latest["score"]
                self._affection_level = latest["level"]
                self._total_conversations = latest["total_conversations"]
                logger.info("affection.loaded", score=self._affection_score, level=self._affection_level)
        except Exception:
            logger.debug("affection.load_skipped")

        # 恢复最近对话历史到 context（跨会话记忆连续性）
        try:
            logs = await self._db.get_conversation_history(limit=20)
            for row in reversed(logs):
                self.context.history.append({"role": "user", "content": row["user_message"]})
                self.context.history.append({"role": "assistant", "content": row["assistant_reply"]})
            if logs:
                logger.info("agent.context_restored", rounds=len(logs))
        except Exception as e:
            logger.warning("agent.context_restore_failed", error=str(e))

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
        """从 prompts/personality_v4.md 加载系统提示"""
        prompt_path = (
            Path(__file__).resolve().parent.parent.parent
            / "prompts" / "personality_v4.md"
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

        # ── 1. 感知 ──
        intent = self._perceive(event.payload)
        trace_log.debug("agent.perceive", intent=intent)

        # ── 1b. 工具确认回路检查 ──
        if self._pending_confirmation:
            confirmed = await self._handle_confirmation(event, trace_log)
            if confirmed:
                reply, tool_results = confirmed
                if tool_results:
                    self._process_tool_side_effects(tool_results, event.payload)
                self.context.add_message("user", event.payload)
                self.context.add_message("assistant", reply)
                return reply

        # ── 2. 记忆检索 ──
        if self.memory_manager:
            self.memory_manager.signal_new_message()
        self.context.memory_retrieval = await self._retrieve_memories(event.payload)

        # ── 3. 构建消息（情感+记忆由 ContextBuilder EmotionModule/MemoryModule 注入）──
        messages = await self._build_messages(event.payload)

        # ── 4. 模型调用（打磨期：LLM 驱动工具选择）──
        tools = None
        if self.tool_executor and len(self.tool_registry) > 0:
            tools = self.tool_registry.to_openai_tools()

        try:
            result = await self.router.route(
                "chat",
                messages,
                temperature=0.65,
                max_tokens=1500,
                stream=stream,
                tools=tools,
                tool_choice="auto" if tools else None,
            )
            if stream:
                reply = "[stream]"
                trace_log.info("agent.process.stream_started")
            elif isinstance(result, str):
                reply = self._clean_reply(result)
            else:
                # LLM 返回了 tool_calls → 执行 + 包装 + 回传
                reply, tool_results = await self._handle_tool_calls(
                    result, event, messages, trace_log
                )
                # 工具调用后处理：记忆编码 + 印象更新
                if tool_results:
                    self._process_tool_side_effects(tool_results, event.payload)
        except Exception as e:
            trace_log.error("agent.process.model_error", error=str(e))
            reply = DEGRADED_REPLY

        # ── 6b. 阶段 7c: 标记后处理 ──
        reply, _markers = self._extract_markers(reply)

        # ── 6c. 语音兜底：确保每次回复都有实际对话 ──
        reply = self._enforce_speech_rule(reply)

        # ── 7. 后台情感分析 ──
        self._schedule_emotion_analysis(event.payload)

        # ── 8. 后台记忆编码 (NEW) ──
        self._schedule_memory_encoding()

        # ── 8b. 阶段 7b: 自动记笔记 ──
        if self.notebook_manager:
            asyncio.create_task(
                self.notebook_manager.auto_note_after_message(
                    event.payload, reply
                )
            )

        # ── 8c. 阶段 8+: 冷启动印象文档 ──
        self._schedule_portrait_cold_start()

        # ── 8d. 阶段 8+: 破冰进度追踪 ──
        self._tick_icebreaker(reply)

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

        # 阶段 8: 每 5 轮触发人设一致性评分
        self._round_count += 1
        if self._round_count % 5 == 0:
            asyncio.create_task(self._score_personality_consistency())

        return reply

    # ============================================================
    # ActorMind 各阶段
    # ============================================================

    def _perceive(self, payload: str) -> dict:
        """
        感知阶段：提取情绪基调（工具选择交由 LLM function calling）。
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

    def _schedule_portrait_cold_start(self):
        """
        冷启动检查：有足够记忆但尚无印象文档 → 立即生成第一版。
        fire-and-forget，不阻塞主回复。
        """
        if not self.portrait_manager:
            return
        # 对话轮数达到 4 条时触发兜底生成
        if len(self.context.history) < 4:
            return
        asyncio.create_task(self._portrait_cold_start_task())

    async def _portrait_cold_start_task(self):
        """冷启动任务：如果尚无印象文档且有足够材料 → 生成第一版。"""
        try:
            result = await self.portrait_manager.ensure_exists()
            if result:
                self.context.user_portrait = result
                # 从 DB 读取版本号
                latest = await self._db.get_latest_portrait()
                if latest:
                    self.context._current_portrait_version = latest.get("version", 1)
                logger.info("portrait.cold_start_done", length=len(result))
        except Exception as e:
            logger.warning("portrait.cold_start_failed", error=str(e))

    def _tick_icebreaker(self, reply: str) -> None:
        """
        破冰进度追踪：自增轮数 + 阈值触发首版印象生成。
        同时检测 Agent 回复中的破冰终止信号。
        """
        if not self.context.icebreaker_active:
            return

        # 检测破冰终止信号：Agent 在回复中暗示不再追问
        defer_signals = [
            "来日方长", "等你想聊", "没关系呢", "不想聊这些",
            "翻过这一页", "不用急", "随时都在",
        ]
        if any(s in reply for s in defer_signals):
            logger.info("icebreaker.deferred", preview=reply[:60])
            self.context.icebreaker_active = False
            self.context.icebreaker_deferred = True
            # 持久化拒绝标记
            if self.notebook_manager:
                asyncio.create_task(
                    self._db.insert_notebook(
                        "focus", "icebreaker_deferred", importance=0.0,
                    )
                )
            return

        self.context.icebreaker_exchanges += 1
        logger.debug(
            "icebreaker.tick",
            exchanges=self.context.icebreaker_exchanges,
        )

        # 阈值触发：2 轮后尝试生成，5 轮后强制生成
        should_consolidate = False
        if self.context.icebreaker_exchanges >= 2 and self.context.icebreaker_exchanges < 5:
            should_consolidate = True
        elif self.context.icebreaker_exchanges >= 5:
            should_consolidate = True

        if should_consolidate and self.portrait_manager:
            logger.info(
                "icebreaker.consolidate_triggered",
                exchanges=self.context.icebreaker_exchanges,
            )
            asyncio.create_task(self._icebreaker_consolidate())

    async def _icebreaker_consolidate(self) -> None:
        """
        破冰后生成首版印象文档。
        关键：先强制编码当前对话为情景记忆（绕过三层调度的 30s 空闲等待），
        确保 consolidate() 能读到材料。
        """
        try:
            # 1. 强制编码当前对话 → 确保 episodic_memories 有数据
            if self.memory_manager and len(self.context.history) >= 4:
                recent = self.context.get_last_n(6)
                ctx = {
                    "exchanges": recent,
                    "emotion": self.context.emotion_snapshot,
                }
                await self.memory_manager.encode_memory(ctx)
                logger.debug("icebreaker.forced_encoding_done")

            # 2. 生成印象文档
            result = await self.portrait_manager.consolidate()
            if result:
                self.context.user_portrait = result
                self.context.icebreaker_active = False
                latest = await self._db.get_latest_portrait()
                if latest:
                    self.context._current_portrait_version = latest.get("version", 1)
                logger.info("icebreaker.first_portrait_done", length=len(result))
            else:
                # 材料仍不足 → 停止破冰，标记已尝试，等被动冷启动兜底
                self.context.icebreaker_active = False
                self.context.icebreaker_deferred = True
                logger.info("icebreaker.consolidate_skipped", reason="材料不足")
        except Exception as e:
            self.context.icebreaker_active = False
            self.context.icebreaker_deferred = True
            logger.warning("icebreaker.consolidate_failed", error=str(e))

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

        # 有新对话 → 印象文档可能需要更新
        if self.portrait_manager:
            self.portrait_manager.mark_dirty()

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

    async def _build_messages(
        self,
        user_msg: str,
        empathy_text: str = "",   # ⚠️ 保留参数签名（向后兼容），但不再使用
        memory_text: str = "",    # ⚠️ 保留参数签名（向后兼容），但不再使用
    ) -> list[dict]:
        """
        构建模型输入消息列表（阶段 7a：ContextBuilder 模块化）。

        结构：
          [system: 人格提示词] → [历史消息] → [自然语言上下文 + 用户消息]

        优化要点：
        - 系统提示只含静态人格 → 前缀缓存 100% 命中
        - 历史消息与前一轮高度一致 → 高缓存命中率
        - 上下文由 ContextBuilder 组装为自然语言段落 → 注入到用户消息底部
        - 每个模块独立渲染、可按 priority + budget 控制
        """
        # 纯静态系统提示（前缀缓存友好，永远不变）
        messages = [{"role": "system", "content": self._personality}]

        # 历史消息（与前一轮前缀高度一致）
        history = self.context.get_messages(limit=20)
        messages.extend(history)

        # 阶段 7a: ContextBuilder 组装上下文（v3.1: 自然语言段落）
        ctx_notes = await self._context_builder.build()

        # 动态注入 + 用户消息收到底部
        if ctx_notes:
            user_content = f"{ctx_notes}\n\n---\n\n{user_msg}"
        else:
            user_content = user_msg

        messages.append({"role": "user", "content": user_content})

        return messages

    # ============================================================
    # 打磨期: LLM 驱动工具调用
    # ============================================================

    async def _handle_tool_calls(self, message, event, messages, trace_log):
        """
        处理 LLM 返回的 tool_calls：执行工具 → 包装结果 → 回传 LLM → 获取最终文本回复。
        最多迭代 3 次，防止工具调用死循环。

        Returns:
            (reply_text, tool_results) — tool_results 是 [(tool_name, ToolResult), ...]
            用于后续记忆编码和印象更新判断。
        """
        import json

        MAX_ITER = 3
        current_message = message
        all_tool_results: list = []  # 跨迭代收集所有工具结果

        for iteration in range(MAX_ITER):
            tool_calls = getattr(current_message, 'tool_calls', None)
            if not tool_calls:
                content = getattr(current_message, 'content', '') or ''
                if content:
                    return self._clean_reply(content), all_tool_results
                return DEGRADED_REPLY, all_tool_results

            trace_log.info("tool.iteration", iter=iteration + 1,
                          count=len(tool_calls))

            # 执行所有工具调用 + 包装结果
            tool_msgs = []
            for tc in tool_calls:
                tool_name = tc.function.name
                try:
                    arguments = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    arguments = {}

                trace_log.info("tool.call", tool=tool_name,
                              args=str(arguments)[:120])

                result = await self.tool_executor.execute(
                    tool_name, arguments, user_id="hezi",
                )

                # 处理 PENDING_CONFIRMATION — 保存状态供确认回路
                if not result.success and result.error == "PENDING_CONFIRMATION":
                    pending_tool = result.data.get("tool_name", tool_name)
                    pending_args = result.data.get("arguments", arguments)
                    self._pending_confirmation = {
                        "tool_name": pending_tool,
                        "arguments": pending_args,
                        "tool_call": tc,
                    }
                    return (
                        f"人家想帮你执行「{pending_tool}」……\n"
                        f"不过这个操作需要伙伴确认一下才可以哦 ~♪\n"
                        f"伙伴说一声「确认」人家就去办～"
                    ), all_tool_results

                # 收集工具结果供记忆/印象更新
                all_tool_results.append((tool_name, result))

                wrapped = await self.result_wrapper.wrap(
                    tool_name, result, event.payload,
                )
                tool_msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": wrapped,
                })
                trace_log.info("tool.result", tool=tool_name,
                              success=result.success)

            # 构建回传消息：assistant(tool_calls) + tool results
            # 必须保留原消息的 reasoning_content（DeepSeek thinking mode 要求）
            follow_up = list(messages)
            assistant_content = getattr(current_message, 'content', None)
            assistant_msg = {
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ],
            }
            # 保留 thinking mode 字段（DeepSeek V4-Pro 要求回传）
            reasoning = getattr(current_message, 'reasoning_content', None)
            if reasoning:
                assistant_msg["reasoning_content"] = reasoning
            follow_up.append(assistant_msg)
            follow_up.extend(tool_msgs)

            # 回传 LLM（不带 tools，避免二次工具调用）
            try:
                result = await self.router.route(
                    "chat", follow_up,
                    temperature=0.65, max_tokens=1500,
                )
            except Exception as e:
                # LLM 回传失败 → 降级返回已包装的工具结果
                trace_log.error("tool.follow_up_error",
                              error_type=type(e).__name__,
                              error=str(e)[:200])
                fallback = tool_msgs[0]["content"] if tool_msgs else DEGRADED_REPLY
                return fallback, all_tool_results

            if isinstance(result, str):
                return self._clean_reply(result), all_tool_results
            else:
                current_message = result
                continue

        # 超过最大迭代
        trace_log.warning("tool.max_iterations", limit=MAX_ITER)
        return "人家帮你都看过了……不过信息有点多，要不伙伴先消化一下？ ~♪", all_tool_results

    def _process_tool_side_effects(self, tool_results: list, user_msg: str):
        """
        处理工具调用的副作用：trigger_memory → 记忆编码 / trigger_portrait → 标记印象 dirty。
        在 process() 的 reply 生成之后调用，fire-and-forget 不阻塞回复。
        """
        for tool_name, result in tool_results:
            if result.trigger_memory:
                logger.info("tool.side_effect.memory", tool=tool_name)
                self._schedule_memory_encoding()
                break  # 一次编码足够

        for tool_name, result in tool_results:
            if result.trigger_portrait_update and self.portrait_manager:
                logger.info("tool.side_effect.portrait_dirty", tool=tool_name)
                self.portrait_manager.mark_dirty()

    async def _handle_confirmation(self, event, trace_log):
        """
        处理工具确认回路：用户确认后直接执行之前挂起的工具。
        返回 (reply, tool_results) 或 None（表示不是确认场景）。
        """
        pending = self._pending_confirmation
        if not pending:
            return None

        user_text = event.payload.strip()
        confirm_words = {"确认", "好的", "好", "可以", "行", "ok", "yes", "嗯", "做吧", "去吧"}

        if user_text in confirm_words or any(user_text.startswith(w) for w in confirm_words):
            self._pending_confirmation = None
            tool_name = pending["tool_name"]
            arguments = pending["arguments"]

            trace_log.info("confirmation.execute", tool=tool_name)

            # 强制执行（跳过 requires_confirmation 检查）
            result = await self.tool_executor.execute(
                tool_name, arguments, user_id="hezi",
            )

            wrapped = await self.result_wrapper.wrap(
                tool_name, result, event.payload,
            )
            trace_log.info("confirmation.done", tool=tool_name, success=result.success)

            return wrapped, [(tool_name, result)]

        # 用户说了别的话 → 取消挂起
        if len(user_text) > 5 or user_text not in confirm_words:
            self._pending_confirmation = None
            trace_log.debug("confirmation.cancelled")

        return None

    # ============================================================
    # 工具方法
    # ============================================================

    def _clean_reply(self, raw: str) -> str:
        """清洗模型输出：去首尾空白 + 兜底语音检测"""
        cleaned = raw.strip()
        if not cleaned:
            return "……♪"
        # 第一层语音兜底：如果清洗后只有动作描述没有实际对话，立即补
        return self._enforce_speech_rule(cleaned)

    def _extract_markers(self, text: str) -> tuple[str, list]:
        """
        阶段 7c: 从回复中提取标记，分离用户可见文本和系统标记。

        流程：
          1. MarkerParser 解析全文
          2. literal → 拼接为 cleaned_text（用户可见）
          3. special → 收集为 markers（系统处理）
          4. emotion/action 标记派发给对应引擎

        Returns:
            (cleaned_text, markers_list)
        """
        parser = MarkerParser()
        tokens = parser.feed(text)
        tokens += parser.flush()

        cleaned_parts: list[str] = []
        markers: list = []

        for t in tokens:
            if t.kind == "literal":
                cleaned_parts.append(t.text)
            else:
                markers.append(t)
                # 派发 emotion 标记到情感引擎
                if t.marker_type == "emotion" and hasattr(self, 'emotion_engine'):
                    logger.debug(
                        "marker.emotion_triggered",
                        emotion=t.payload.get("emotion"),
                        intensity=t.payload.get("intensity"),
                    )

        cleaned = "".join(cleaned_parts).strip()
        if not cleaned and markers:
            cleaned = "……♪"  # 纯标记时给个最小回复

        return cleaned, markers

    def _enforce_speech_rule(self, text: str) -> str:
        """
        语音兜底：确保回复包含实际对话。
        检测：括号外 CJK >= 2 放行；括号内文字远超括号外 → 模型只写了动作 → 补前缀。
        """
        import re
        stripped = re.sub(r'[（(][^）)]*[）)]', '', text)
        stripped = re.sub(r'\[[^\]]*\]', '', stripped)
        stripped = re.sub(r'[~♪✨🌟⭐💕]', '', stripped)
        stripped = stripped.strip()

        def _cjk(s: str) -> int:
            return sum(1 for c in s if '\u4e00' <= c <= '\u9fff' or '\u3040' <= c <= '\u30ff')

        outside_cjk = _cjk(stripped)
        total_cjk = _cjk(text)

        if outside_cjk >= 2:
            return text

        if total_cjk > outside_cjk and total_cjk >= 3:
            prefix = self._build_speech_fallback()
            logger.debug("speech_rule.enforced", prefix=prefix, original=text[:60])
            return f"{prefix} {text}" if text.strip() else prefix

        if outside_cjk >= 1:
            return text

        prefix = self._build_speech_fallback()
        logger.debug("speech_rule.enforced", prefix=prefix, original=text[:60])
        return f"{prefix} {text}" if text.strip() else prefix

    def _build_speech_fallback(self) -> str:
        """构建上下文感知的语音兜底。"""
        import random
        last_user_msg = ""
        for m in reversed(self.context.history):
            if m["role"] == "user":
                last_user_msg = m["content"]
                break

        if last_user_msg:
            if "?" in last_user_msg or "？" in last_user_msg:
                q = last_user_msg.replace("?", "").replace("？", "")
                if len(q) > 8:
                    return f"嗯……人家刚才在想关于「{q[:15]}」的事情呢。"
                return f"嗯……这个问题人家想了一下呢——"

            short = last_user_msg[-15:] if len(last_user_msg) > 15 else last_user_msg
            return f"人家听到了呢……「{short}」——（轻轻合上书）"

        return "嗯…（轻轻翻开一页书）人家刚才走神了一下呢。伙伴再说一遍好吗？"

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

                # 更新好感度
                await self._update_affection(pad_profile)
        except asyncio.CancelledError:
            logger.debug("emotion.analysis_cancelled")
        except Exception as e:
            logger.warning("emotion.analysis_failed", error=str(e))

    # ============================================================
    # 好感度系统
    # ============================================================

    async def _update_affection(self, pad_profile: dict) -> None:
        """
        根据本轮情绪更新好感度。

        规则：
          - 基础增长 0.05/轮
          - 积极情绪加成：快乐/信任/期待 +0.10, 平静 +0.05
          - 红线扣减：人格漂移 OR 强烈负面(愤怒/厌恶/恐惧,intensity>0.5) → -0.50
          - 单轮上限：+0.30 max, -0.50 max
          - 100 分锁定：score>=100 时只增不减
        """
        try:
            old_score = self._affection_score

            # 0. 已满 100 → locked
            if old_score >= 100.0:
                self._total_conversations += 1
                await self._db.insert_affection_snapshot(
                    score=100.0, level=4,
                    total_conversations=self._total_conversations,
                    reason="locked_at_max",
                )
                return

            # 1. 基础增长
            delta = 0.05
            reason = "base_increment"

            # 2. 积极情绪加成
            primary = pad_profile.get("primary_emotion", "")
            intensity = pad_profile.get("primary_intensity", 0.0)
            positive_high = {"快乐", "信任", "期待"}
            positive_low = {"平静"}

            if primary in positive_high:
                delta += 0.10
                reason = f"{primary}_bonus"
            elif primary in positive_low:
                delta += 0.05
                reason = f"{primary}_bonus"

            # 3. 红线扣减
            negative_strong = {"愤怒", "厌恶", "恐惧"}
            red_line_hit = False
            if self._drift_counter > 0:
                red_line_hit = True
            if primary in negative_strong and intensity > 0.5:
                red_line_hit = True

            if red_line_hit:
                delta = -0.50
                reason = "red_line_hit"

            # 4. 钳制
            delta = max(-0.50, min(0.30, delta))

            # 5. 应用
            new_score = old_score + delta
            new_score = max(0.0, min(100.0, new_score))
            new_score = round(new_score, 2)

            # 6. 锁定检查
            if new_score >= 100.0:
                new_score = 100.0
                reason = f"{reason}_max_locked"

            # 7. 等级计算
            if new_score >= 75:
                level = 4 if new_score >= 100 else 3
            elif new_score >= 50:
                level = 2
            else:
                level = 1

            self._affection_score = new_score
            self._affection_level = level
            self._total_conversations += 1

            # 8. 持久化
            await self._db.insert_affection_snapshot(
                score=new_score,
                level=level,
                total_conversations=self._total_conversations,
                reason=reason,
            )

            if abs(delta) > 0.01:
                logger.debug(
                    "affection.updated",
                    old=round(old_score, 2),
                    new=new_score,
                    delta=round(delta, 3),
                    level=level,
                    reason=reason,
                )
        except Exception as e:
            logger.warning("affection.update_failed", error=str(e))

    @property
    def affection_score(self) -> float:
        return self._affection_score

    @property
    def affection_level(self) -> int:
        return self._affection_level

    @property
    def personality_preview(self) -> str:
        """返回人格提示前 200 字符（调试用）"""
        return self._personality[:200] + "..."

    # ============================================================
    # 阶段 5: 时间感知问候 + 人格漂移检测
    # ============================================================

    def consume_icebreaker_greeting(self) -> str | None:
        """
        破冰主动问候 — 消费一次即标记已投递。

        Returns:
            破冰问候文本（仅一次），已投递/已拒绝/已尝试过时返回 None。
        """
        if not self._icebreaker_pending:
            return None
        # 已拒绝或已尝试过 → 不重复骚扰
        if self.context.icebreaker_deferred:
            self._icebreaker_pending = False
            return None
        self._icebreaker_pending = False
        # 初始化破冰计数（问候本身算第一轮）
        self.context.icebreaker_active = True
        self.context.icebreaker_exchanges = 1
        logger.info("icebreaker.greeting_delivered")
        return (
            "初次见面呢……人家是昔涟。"
            "还不知道该怎么称呼你呢——可以告诉人家你的名字吗？"
            "还有，你平时喜欢做些什么呀？"
            "人家想在心里给你留一页温暖的位置 ♪"
        )

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

    # ============================================================
    # 阶段 8: 人设一致性评分 + 安全回复模式
    # ============================================================

    PERSONALITY_SCORING_PROMPT = """请评估以下回复是否符合「昔涟」的人设。

昔涟的关键特征：
1. 自称「人家」，称呼对方「伙伴」
2. 语气温柔轻盈，不机械化、不AI式
3. 可能有涟漪/书页/花/秋千/星星等意象
4. 拒绝时不说「作为AI」，说「人家担心……」「不行呢」
5. 语气词自然（呢、呀、哦、~♪）

回复内容：
{replies}

请打分 0.0-1.0 并简要说明理由（20字以内）。
只返回 "分数|理由"，如 "0.85|语气温柔，有涟漪意象"。"""

    async def _score_personality_consistency(self):
        """
        每 5 轮 fire-and-forget 评分。

        流程：
          取最近 3-5 条 assistant 回复 → DS Pro 评分 →
          分数 < 0.7 → 告警 + 记 audit_log →
          连续 3 次 < 0.7 → 进入安全回复模式
        """
        try:
            # 取最近 3-5 条 assistant 回复
            recent = [m["content"] for m in self.context.history
                      if m["role"] == "assistant"][-5:]
            if len(recent) < 3:
                return

            replies_text = "\n---\n".join(r[:200] for r in recent)
            prompt = self.PERSONALITY_SCORING_PROMPT.format(replies=replies_text)

            result = await self.router.route(
                "personality_check",
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=40,
            )
            result = result.strip()

            # 解析 "分数|理由"
            if "|" in result:
                score_str, reason = result.split("|", 1)
                try:
                    score = float(score_str.strip())
                    if self._db and self._db._conn:
                        await self._db.insert_audit_log(
                            "personality_drift_warning" if score < 0.7 else "personality_check",
                            f"score={score:.2f} reason={reason.strip()[:60]}",
                            severity="warning" if score < 0.7 else "info",
                        )

                    if score < 0.7:
                        logger.warning(
                            "personality.drift",
                            score=round(score, 2),
                            reason=reason.strip()[:60],
                        )
                except ValueError:
                    pass
        except Exception as e:
            logger.warning("personality.scoring_failed", error=str(e))
