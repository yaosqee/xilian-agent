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
from .emotion_analyzer import EmotionAnalyzer
from .emotion_core import EmotionEngine
from .memory_manager import MemoryManager
from .notebook_manager import NotebookManager

# 阶段 7a: 模块化上下文
from .context_builder import (
    ContextBuilder,
    DatetimeModule,
    EmotionModule,
    MemoryModule,
    NotebookModule,
)


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

        # 阶段 7d: 注册编码委托工具
        from .tools.coding_delegate import coding_delegate as _cd
        from .tool_registry import ToolPermission
        self.tool_registry.register(
            name="coding_delegate",
            description="委托 Claude Code 完成编码任务。适合写代码、调试、重构等编程需求。",
            schema={
                "task_description": {"type": "string", "description": "编码任务描述"},
            },
            permission=ToolPermission.EXECUTE,
        )(_cd)

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

        # 阶段 8: 安全机制（审计日志 + 人设评分，safe_mode 预留）
        self._round_count: int = 0

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
        self._context_builder.register(EmotionModule(self.context))
        self._context_builder.register(MemoryModule(self.context))
        self._context_builder.register(NotebookModule())  # 7b 通过 set_notebook() 注入

        # 阶段 7b: 笔记本管理器占位（子阶段 7b 注入）
        self.notebook_manager: NotebookManager | None = None

        # 阶段 7c: 注意力调度器占位（子阶段 7c 注入）
        self.attention_scheduler = None

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

        if intent.get("is_tool_request"):
            if intent.get("intent") == "coding_delegate":
                # 阶段 7d: 编码委托
                from .tools.coding_delegate import coding_delegate as _cd
                result = await _cd(event.payload)
                reply = result.summary
            else:
                reply = TOOL_PLACEHOLDER
            self.context.add_message("user", event.payload)
            self.context.add_message("assistant", reply)
            trace_log.info("agent.process.done", reply_preview=reply[:60])
            return reply

        # ── 2. 记忆检索 (NEW) ──
        if self.memory_manager:
            self.memory_manager.signal_new_message()
        self.context.memory_retrieval = await self._retrieve_memories(event.payload)

        # ── 3. 构建消息（情感+记忆由 ContextBuilder EmotionModule/MemoryModule 注入）──
        messages = await self._build_messages(event.payload)

        # ── 6. 模型调用 ──
        try:
            result = await self.router.route(
                "chat",
                messages,
                temperature=0.65,
                max_tokens=600,
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

        # 阶段 7d: 编码委托意图
        coding_keywords = {
            "帮我写", "写个", "写一个", "帮我改", "改一下代码",
            "调试", "bug", "报错", "重构", "帮我实现", "实现一个",
        }
        if not intent["is_tool_request"]:
            for kw in coding_keywords:
                if kw in payload:
                    intent["is_tool_request"] = True
                    intent["intent"] = "coding_delegate"
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
