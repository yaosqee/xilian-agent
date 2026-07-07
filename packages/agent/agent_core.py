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
import json
import math
import re
import time
from dataclasses import dataclass
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
from .emotion_core import EmotionEngine
from .memory_manager import MemoryManager
from .notebook_manager import NotebookManager
from .portrait_manager import PortraitManager
from .skills_loader import SkillsLoader

# 阶段 7a: 模块化上下文 + Pipeline ServiceModule
from .pipeline import ServiceModule
from .pipeline.perception import PerceptionProcessor
from .pipeline.multimodal import MultimodalProcessor
from .pipeline.memory_retrieval import MemoryRetrievalProcessor

from .context_builder import (
    ContextBuilder, estimate_tokens,
    DatetimeModule,
    EmotionModule,
    MemoryModule,
    NotebookModule,
    NotebookTaskModule,
    PortraitModule,
    PortraitGuidanceModule,
    AffectionModule,
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


# ── Tool call serialization helpers ─────────────────────────
# Handle both OpenAI object format (tc.id, tc.function.name)
# and ProviderResponse dict format (tc["id"], tc["function"]["name"])


def _tc_id(tc) -> str:
    """Extract tool call ID from dict or object."""
    if isinstance(tc, dict):
        return tc.get("id", "")
    return getattr(tc, "id", "")


def _tc_function_name(tc) -> str:
    """Extract function name from dict or object."""
    if isinstance(tc, dict):
        return tc.get("function", {}).get("name", "")
    fn = getattr(tc, "function", None)
    return getattr(fn, "name", "") if fn else ""


def _tc_function_arguments(tc) -> str:
    """Extract function arguments JSON string from dict or object."""
    if isinstance(tc, dict):
        return tc.get("function", {}).get("arguments", "{}")
    fn = getattr(tc, "function", None)
    return getattr(fn, "arguments", "{}") if fn else "{}"


@dataclass
class AgentResponse:
    """AgentCore.process() 的返回结构。"""
    reply: str
    sticker: dict | None = None  # {id, file} 或 None


class AgentCore:
    """
    昔涟的核心引擎，接收 InternalEvent，返回 AgentResponse。

    ── 优化路线图 (2026-06 audit) ──
    Phase 1 (当前): P1-② 情绪→LLM参数调制 (line ~494, ~1052)
    Phase 2 (后续): P1-① 情绪记忆链接 / P1-③ 反馈闭环
    Phase 3 (远期): P2-① Rupture & Repair
    ──────────────────────────────────
    """

    def __init__(self, model_router: ModelRouter | None = None, db_path: str = "data/xilian.db"):
        self.router = model_router or ModelRouter()
        self.tool_registry = ToolRegistry()
        self.tool_executor: ToolExecutor | None = None
        self.result_wrapper: ResultWrapper | None = None
        self.context = AgentContext()
        self._personality: str = self._load_personality()

        # ── Pipeline ServiceModule 实例（同步依赖，__init__ 中创建）──
        self._perception = PerceptionProcessor(self.context)
        self._multimodal = MultimodalProcessor(self.context, router=self.router)
        self._mem_retrieval = MemoryRetrievalProcessor(self.context, router=self.router)

        # 打磨期: 自动发现并注册 tools/ 目录下所有工具
        self.tool_registry.autodiscover("packages.agent.tools")
        # 注册工具的结果模板（不需要 LLM 二次包装的）
        from .tools.search_memory import _register_template as _reg_sm
        from .tools.query_weather import _register_template as _reg_qw
        from .tools.search_web import _register_template as _reg_sw
        _reg_sm()
        _reg_qw()
        _reg_sw()

        # 阶段 2+4: PAD 情感引擎（唯一情绪系统，已取代阶段2 EmotionAnalyzer）
        self._pending_analysis: asyncio.Task | None = None
        self._bg_tasks: set[asyncio.Task] = set()  # 后台任务追踪（shutdown 时统一取消）
        self._emotion_generation: int = 0  # 代数计数器，确保只有最新分析的结果被采纳

        self.emotion_engine: EmotionEngine = EmotionEngine(
            model_router=self.router,
        )

        # ── P1-②: 情绪→LLM 参数调制（防锁死）────────────────
        self._last_modulated_params: dict | None = None
        self._emotion_flat_rounds: int = 0  # PAD 变化不显著的连续轮数

        # ── P1-③: 情绪反馈闭环 ─────────────────────────
        self._strategy_effectiveness: dict[str, list[float]] = {}  # {strategy: [scores]}
        self._last_eval_data: dict | None = None  # 上一轮的 {user_msg, response, strategy}

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
        # 模块按优先级注册：datetime(1) < portrait(3) < emotion(4) < memory(5) < notebook(6) < affection(7) < tasks(8)
        self._context_builder = ContextBuilder(total_budget=800)
        self._context_builder.register(DatetimeModule())
        self._context_builder.register(PortraitGuidanceModule(self.context))
        self._context_builder.register(PortraitModule(self.context))
        self._context_builder.register(EmotionModule(self.context))
        self._context_builder.register(MemoryModule(self.context))
        self._context_builder.register(NotebookModule())  # 7b 通过 set_notebook() 注入
        self._context_builder.register(AffectionModule())  # 好感度关系感知
        self._context_builder.register(NotebookTaskModule())  # 待办任务注入

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

    def _launch_bg(self, coro, name: str = "") -> asyncio.Task:
        """统一后台任务启动：存储弱引用 + done 回调自动清理，shutdown 时统一取消。

        Args:
            coro: 要调度的协程
            name: 任务名（便于调试）

        Returns:
            创建的 Task 对象（通常调用方不需要存储返回值）
        """
        task = asyncio.create_task(coro, name=name)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

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

        # 阶段 9: 确保角色情景记忆已导入（幂等，新项目首次启动自动执行）
        await self._ensure_character_memories()

        # 阶段 B: 注册上下文压缩回调（Fire-and-forget，不影响主流程）
        self.context.set_compress_callback(
            lambda msgs: self.memory_manager.compress_history(
                msgs, affection_level=self._affection_level
            )
        )

        # 阶段 7b: 初始化 NotebookManager
        if not self.notebook_manager:
            self.notebook_manager = NotebookManager(
                _db=self._db,
                _router=self.router,
            )
        # 注入 NotebookManager 到 ContextBuilder 的 NotebookModule / NotebookTaskModule
        nb_module = self._context_builder.get_module("notebook")
        if nb_module:
            nb_module.set_notebook(self.notebook_manager)
        task_module = self._context_builder.get_module("notebook_tasks")
        if task_module:
            task_module.set_notebook(self.notebook_manager)

        # 阶段 8+: 初始化用户印象管理器 + 加载分层画像
        if not self.portrait_manager:
            self.portrait_manager = PortraitManager(
                db=self._db,
                model_router=self.router,
            )
            # 注入异步依赖到 Pipeline ServiceModule
            self._mem_retrieval.set_managers(self.memory_manager, self.portrait_manager, db=self._db)

        # Phase 5: 注入 ModelRouter 引用供 PortraitGuidanceModule 使用
        self.context._router = self.router

        # 阶段 7d: 初始化技能加载器
        if not self._skills_loader:
            # PyInstaller 打包时 skills/ 在 bundled 目录而非 CWD
            base = str(Path(__file__).resolve().parent.parent.parent)
            self._skills_loader = SkillsLoader()
            self._skills_loader.load_all(base_path=base)

        # Phase 2: 数据迁移 + 加载分层画像
        try:
            await self._db.migrate_portrait_to_layered()
        except Exception as e:
            logger.debug("portrait.migrate_skipped", error=str(e))

        await self._reload_layered_portraits()

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

        # Phase B: 初始化 ModelRouter DB 配置（热加载 + 自动播种）
        try:
            if hasattr(self.router, '_db'):
                self.router._db = self._db
            await self.router.initialize()
        except (TypeError, AttributeError):
            # Mock router 或 DB 未就绪时跳过
            logger.debug("model_router.init_skipped")

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

        # 无印象文档（L0 或旧画像均不存在）→ 准备破冰主动问候
        has_portrait = (
            self.context.core_profile
            or self.context.phase_profile
            or self.context.user_portrait
        )
        if not has_portrait:
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
                # 同步好感度到 ContextBuilder AffectionModule
                aff_module = self._context_builder.get_module("affection")
                if aff_module:
                    aff_module.set_state(self._affection_score, self._affection_level)
        except Exception:
            logger.debug("affection.load_skipped")

        # 阶段 C: 恢复最近对话历史（时间优先 + token 预算）
        try:
            recover_hours = 4
            recover_budget = 2000
            now = time.time()
            logs = await self._db.get_conversation_history(limit=40)
            logger.debug("context_restore.fetched", log_count=len(logs))

            if not logs:
                logger.debug("context_restore.empty_db")
                self.context._last_message_time = 0.0
            else:
                recovered: list[dict] = []
                seen_ids: set[int] = set()
                last_msg_time = 0.0

                # Pass 1: 最近 N 小时内的对话全部恢复
                for row in reversed(logs):
                    ts = row.get("timestamp", 0) or 0
                    if now - ts <= recover_hours * 3600:
                        recovered.append(row)
                        seen_ids.add(row.get("id", 0))
                        last_msg_time = max(last_msg_time, ts)

                # Pass 2: token 预算补全
                recovered_tokens = sum(
                    estimate_tokens(r.get("user_message") or "") + estimate_tokens(r.get("assistant_reply") or "")
                    for r in recovered
                )
                for row in reversed(logs):
                    rid = row.get("id", 0)
                    if rid in seen_ids:
                        continue
                    extra = estimate_tokens(row.get("user_message") or "") + estimate_tokens(row.get("assistant_reply") or "")
                    if recovered_tokens + extra > recover_budget:
                        break
                    recovered.append(row)
                    seen_ids.add(rid)
                    recovered_tokens += extra
                    last_msg_time = max(last_msg_time, row.get("timestamp", 0) or 0)

                # 按时间排序后注入 context（附时间标签）
                recovered.sort(key=lambda r: r.get("id", 0))
                for row in recovered:
                    user_msg = row.get("user_message") or ""
                    if not user_msg:
                        user_msg = "（昔涟轻轻推了推伙伴——她主动发来了一句问候。）"
                    # 相对时间标签：帮助模型感知对话时间距离
                    ts = row.get("timestamp", 0) or 0
                    if ts > 0:
                        age_sec = now - ts
                        if age_sec > 3600:
                            age_h = round(age_sec / 3600)
                            if age_h < 24:
                                time_label = f"（约{age_h}小时前）"
                            elif age_h < 48:
                                time_label = "（昨天）"
                            else:
                                time_label = f"（{age_h // 24}天前）"
                            user_msg = f"{time_label} {user_msg}"
                    self.context.history.append({"role": "user", "content": user_msg})
                    self.context.history.append({"role": "assistant", "content": row.get("assistant_reply") or ""})

                self.context._last_message_time = last_msg_time
                logger.info("agent.context_restored",
                    rounds=len(recovered),
                    tokens=recovered_tokens,
                    last_msg_age_minutes=round((now - last_msg_time) / 60, 1) if last_msg_time else 0,
                )
        except Exception as e:
            logger.warning(f"agent.context_restore_failed: {type(e).__name__} — {e}")

        # Phase 2: 30 天图片清理任务（每 24h 执行一次）
        async def _cleanup_loop():
            while True:
                await asyncio.sleep(86400)  # 24h
                try:
                    count = await self._db.delete_expired_images(days=30)
                    if count > 0:
                        logger.info("cleanup.expired_images", count=count)
                except Exception as e:
                    logger.warning("cleanup.failed", error=str(e))
        self._cleanup_task = asyncio.create_task(_cleanup_loop())

        logger.info("agent.startup_complete")

    async def shutdown(self) -> str:
        """
        优雅关闭：取消所有后台任务 → 编码待处理记忆 → 关闭 DB。

        Returns:
            "done" / "empty" / "failed"
        """
        # 1. 取消清理任务（tracked separately）
        if hasattr(self, '_cleanup_task') and not self._cleanup_task.done():
            self._cleanup_task.cancel()

        # 2. 取消 pending 的情感分析（tracked separately）
        if self._pending_analysis and not self._pending_analysis.done():
            self._pending_analysis.cancel()

        # 3. 取消所有后台任务（fire-and-forget tasks）
        bg_tasks = list(self._bg_tasks)
        if bg_tasks:
            logger.info("agent.shutdown.cancelling_bg_tasks", count=len(bg_tasks))
            for t in bg_tasks:
                t.cancel()
            # 等待取消完成（带超时，避免无限等待）
            await asyncio.wait(bg_tasks, timeout=5)
            remaining = [t for t in bg_tasks if not t.done()]
            if remaining:
                logger.warning("agent.shutdown.bg_tasks_timeout", remaining=len(remaining))
            self._bg_tasks.clear()

        # 4. 记忆编码兜底（此时 bg tasks 已全部取消，不会被新写入打断）
        result = "empty"
        if self.memory_manager:
            result = await self.memory_manager.shutdown()

        # 5. 关闭数据库
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
    ) -> AgentResponse:
        """
        处理一条用户消息，返回昔涟的回复。

        阶段 3 流程：
          感知 → 记忆检索 → 共情注入 → 记忆注入 → 构建消息 → 模型调用 →
          后台情感分析 + 后台记忆编码 + 写入对话日志
        """
        trace_log = logger.bind(trace_id=event.event_id[:8])

        # ── 0. 输入清洗：修复 WSL/终端传入的 lone surrogate 字符 ──
        event.payload = _sanitize_surrogates(event.payload)

        # ── 0b. 用户表情包消息转换 ──
        # 检查 payload 是否仅为 sticker 标记
        sticker_only = re.match(r'^\[sticker:([a-z_]+)\]$', event.payload.strip())
        if sticker_only:
            sticker_id = sticker_only.group(1)
            event.payload = f"伙伴发了一个表情：{sticker_id}"
            # 在 ctx_notes 层面提示（后续通过 emotion 系统感知）
            self._user_sent_sticker = True

        trace_log.info(
            "agent.process.start",
            source=event.source,
            owner=event.is_owner,
            msg_preview=event.payload[:80],
        )

        # ── 1. 安全 ──
        if not event.is_owner:
            trace_log.warning("agent.process.blocked")
            return AgentResponse(reply="")

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
                return AgentResponse(reply=reply)

        # ── 1c. 多模态：图片预处理 ──
        image_description = ""
        memory_task = None  # Native 路径的后台 MiMo 任务（不阻塞回复）
        self._current_images = list(event.images) if event.images else []
        if self._current_images:
            provider, model = self.router.get_current_model_info()
            if self.router.supports_vision(provider, model):
                # Native 路径：图片直入 multimodal，后台并行 MiMo 取描述（仅用于记忆）
                trace_log.info("agent.multimodal.native", provider=provider, model=model)
                memory_task = asyncio.create_task(
                    self._describe_image(self._current_images[0])
                )
            else:
                # Fallback 路径：先用 MiMo 描述再对话
                trace_log.info("agent.multimodal.fallback", provider=provider)
                image_description = await self._describe_image(self._current_images[0])
                if image_description:
                    trace_log.debug("agent.image_described", preview=image_description[:80])

        # ── 2. 记忆检索 ──
        if self.memory_manager:
            self.memory_manager.signal_new_message()
        # 如果图片描述存在，将其附加到用户消息中以便记忆检索
        search_query = event.payload
        if image_description:
            search_query = f"{event.payload}\n{image_description}"
        self.context.memory_retrieval = await self._retrieve_memories(search_query)

        # ── P1-①: 为检索到的记忆查询关联情绪 ──
        if self._db and self._db._conn:
            memory_ids = []
            for mem_list in (self.context.memory_retrieval, self.context.character_memory_retrieval):
                if mem_list:
                    for m in mem_list:
                        mid = m.get("id")
                        if mid is not None:
                            memory_ids.append(mid)
            if memory_ids:
                self.context.memory_emotion_map = await self._db.get_emotions_by_memory_ids(memory_ids)

        # ── P1-③: 同步策略有效性数据供 EmotionModule 消费 ──
        self.context.strategy_effectiveness = self._strategy_effectiveness

        # ── 3. 构建消息（情感+记忆由 ContextBuilder EmotionModule/MemoryModule 注入）──
        messages = await self._build_messages(event.payload)
        # 注入可用 sticker 列表（供 LLM 选择使用）
        available = self._get_available_sticker_ids()
        if available:
            sticker_hint = "可用表情包：" + "、".join(
                f"[sticker:{s['id']}]({s['desc']})" for s in available
            )
            sticker_hint += "。在对话中自然使用 [sticker:id] 标记发送表情包，不能替代文字。"
            # 在 user 消息前插入
            insert_at = len(messages) - 1
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "system":
                    insert_at = i + 1
                    break
            messages.insert(insert_at, {"role": "system", "content": sticker_hint})
        # 多模态：注入图片到消息中（vision 模型原生支持）
        if image_description:
            # 兜底路径：在 user 消息前注入图片描述
            ctx_note = f"[识图结果] 伙伴发来的图片画面：{image_description}"
            # 找到最后一条 system 消息的位置并在其后插入
            insert_idx = len(messages) - 1  # 默认在 user 消息之前
            for i in range(len(messages) - 1, -1, -1):
                if messages[i]["role"] == "system":
                    insert_idx = i + 1
                    break
            messages.insert(insert_idx, {"role": "system", "content": ctx_note})
            trace_log.debug("multimodal.injected", idx=insert_idx, total=len(messages), desc_preview=image_description[:80])
        elif self._current_images:
            # 原生 vision 路径（仅当模型确实支持 vision 时才转换）
            provider, model = self.router.get_current_model_info()
            if self.router.supports_vision(provider, model):
                self._convert_to_multimodal(messages, self._current_images, provider)
            else:
                # MiMo fallback 也失败了 → 优雅降级
                messages.insert(-1, {"role": "system", "content": "（伙伴发来了一张图片，但人家暂时看不太清楚呢……）"})
                trace_log.warning("agent.multimodal.degraded", provider=provider)

        # ── 4. 模型调用（打磨期：LLM 驱动工具选择）──
        tools = None
        if self.tool_executor and len(self.tool_registry) > 0:
            tools = self.tool_registry.to_openai_tools()

        tools_called = False
        try:
            # ── P1-②: 情绪调制 LLM 参数 ──
            emo_params = self._emotion_modulated_params()

            result = await self.router.route(
                "chat",
                messages,
                temperature=emo_params["temperature"],
                max_tokens=emo_params["max_tokens"],
                stream=stream,
                tools=tools,
                tool_choice="auto" if tools else None,
            )
            if stream:
                reply = "[stream]"
                trace_log.info("agent.process.stream_started")
            elif result.tool_calls:
                # LLM 返回了 tool_calls → 执行 + 包装 + 回传
                reply, tool_results = await self._handle_tool_calls(
                    result, event, messages, trace_log
                )
                tools_called = bool(tool_results)
                if tool_results:
                    self._process_tool_side_effects(tool_results, event.payload)
            else:
                reply = self._clean_reply(result.content or "")
        except Exception as e:
            trace_log.error(f"agent.process.model_error: {type(e).__name__}: {e}"[:300])
            reply = DEGRADED_REPLY

        # ── 6b. 阶段 7c: 标记后处理 ──
        reply, _markers = self._extract_markers(reply)
        # 提取 sticker 标记（从 markers 中收集，传递给前端）
        sticker = None
        for m in _markers:
            if m.marker_type == "sticker":
                sticker_id = m.payload.get("sticker_id", "")
                if sticker_id:
                    sticker = self._resolve_sticker(sticker_id)
                    if sticker:
                        self._sticker_cooldown = 4  # LLM 主动发的也设冷却（4→tick后3，完整3轮冷却）
                    break  # 只取第一个 sticker

        # 兜底：LLM 没发 sticker 时，情绪引擎触发
        if not sticker and self._should_auto_sticker():
            sticker = self._pick_sticker_by_emotion()
            if sticker:
                trace_log.debug("sticker.auto_triggered", sticker=sticker["id"])

        # ── 6c. 语音兜底：确保每次回复都有实际对话 ──
        reply = self._enforce_speech_rule(reply)

        # ── P1-③: 存储本轮数据供下轮反馈评估 ──
        strategy = self.context.last_emotion_strategy
        if strategy and reply and reply != DEGRADED_REPLY:
            self._last_eval_data = {
                "user_msg": event.payload,
                "response": reply[:300],  # 截断避免 prompt 过长
                "strategy": strategy,
            }

        # ── 7. 情感分析（启动后台任务，稍后等待完成再写日志）──
        emotion_task = self._schedule_emotion_analysis(event.payload)

        # ── 8. 后台记忆编码 (NEW) ──
        self._schedule_memory_encoding()

        # ── 8b. Phase 1: 微事件提取 + 粗粒化检查（链式调用，消除竞态）──
        if self.portrait_manager:
            self._launch_bg(
                self.portrait_manager.extract_then_check_coarse(
                    event.payload, reply
                ),
                name="portrait_extract",
            )

        # ── 8c. 阶段 7b: 自动记笔记 ──
        if self.notebook_manager:
            # portrait_context: Phase 1-4 为空字符串，Phase 5 起从 L0+L1 构建
            portrait_ctx = ""
            # Phase 5+ 路径（Phase 1-4 时 hasattr 返回 False，安全跳过）
            if hasattr(self.context, 'phase_profile') and (
                self.context.core_profile or self.context.phase_profile
            ):
                parts = []
                if self.context.core_profile:
                    parts.append(f"伙伴的性格底色：{self.context.core_profile[:100]}")
                if self.context.phase_profile:
                    parts.append(f"伙伴的近况：{self.context.phase_profile[:150]}")
                if parts:
                    portrait_ctx = "。".join(parts)

            self._launch_bg(
                self.notebook_manager.auto_note_after_message(
                    event.payload, reply, portrait_context=portrait_ctx
                ),
                name="auto_note",
            )
        else:
            logger.warning("notebook.manager_missing")

        # ── 8d. 阶段 8+: 破冰进度追踪 ──
        self._tick_icebreaker(reply)

        # ── 9. 等待情感分析完成 → 写入对话日志（确保 emotion_snapshot 已更新）──
        if emotion_task and not emotion_task.done():
            try:
                await emotion_task
            except Exception:
                pass

        # ── 9b. 统一记忆管线：收集图片描述 + 压缩注入 payload ──
        if memory_task:
            try:
                image_description = await memory_task  # 已完成的任务立即返回，不阻塞
            except Exception:
                pass  # 并行 MiMo 失败不影响主流程（模型已直接看了图）
        if image_description and self._current_images:
            short_desc = self._compress_image_desc(image_description)
            suffix = f"[发来一张照片：{short_desc}]"
            event.payload = f"{event.payload} {suffix}".strip() if event.payload.strip() else suffix
            trace_log.debug("memory.image_injected", short=short_desc)

        await self._write_conversation_log(event, reply)

        # ── 9c. 高价值图片记忆编码（后台异步，不阻塞）──
        if image_description and self._current_images:
            self._launch_bg(
                self._encode_image_memory(image_description, event, reply),
                name="image_memory_encode",
            )

        # ── 10. 记录历史（编造数据先清洗再入上下文，防止下轮当事实）──
        self.context.add_message("user", event.payload)
        clean_for_ctx = self._sanitize_fabrication(reply, tools_called)
        self.context.add_message("assistant", clean_for_ctx)

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
            self._launch_bg(self._score_personality_consistency(), name="personality_score")

        # 表情包冷却递减（在 sticker 设置之后，确保 LLM 发的 sticker 冷却完整 3 轮）
        self._tick_sticker_cooldown()

        return AgentResponse(reply=reply, sticker=sticker)

    # ============================================================
    # ActorMind 各阶段
    # ============================================================

    def _perceive(self, payload: str) -> dict:
        """
        感知阶段：提取情绪基调（工具选择交由 LLM function calling）。
        """
        return self._perception.perceive(payload)

    # ============================================================
    # 阶段 3: 记忆检索
    # ============================================================

    async def _retrieve_memories(self, user_message: str) -> list[dict] | None:
        """
        检索与当前消息相关的历史记忆 + 角色情景记忆。
        """
        return await self._mem_retrieval.retrieve_memories(user_message)

    # _schedule_portrait_cold_start / _portrait_cold_start_task 已废弃（Phase 1）。
    # 冷启动逻辑合并到 extract_then_check_coarse() + ensure_exists() 中。
    # process() 中不再调用此方法。

    async def _reload_layered_portraits(self) -> None:
        """
        Phase 2: 从 DB 重新加载 L0/L1 分层画像到 AgentContext。

        在 startup 和 _icebreaker_consolidate 后调用，
        确保 context 中的画像与 DB 同步。
        """
        try:
            # 加载 L0 核心画像
            l0 = await self._db.get_latest_core_profile()
            if l0 and l0.get("content"):
                self.context.core_profile = l0["content"]
                self.context._current_l0_version = l0.get("version", 1)
                logger.info("portrait.l0_loaded", version=l0.get("version"))

            # 加载 L1 阶段画像
            l1 = await self._db.get_latest_phase_profile()
            if l1 and l1.get("content"):
                self.context.phase_profile = l1["content"]
                self.context._current_l1_version = l1.get("version", 1)
                logger.info("portrait.l1_loaded", version=l1.get("version"))

            # 兼容：同时加载旧 user_portrait（供回退消费方使用）
            if not self.context.user_portrait:
                old = await self._db.get_latest_portrait()
                if old and old.get("content") and len(old.get("content", "")) >= 50:
                    self.context.user_portrait = old["content"]
                    self.context._current_portrait_version = old.get("version", 1)
                    logger.debug("portrait.legacy_loaded", version=old.get("version"))
        except Exception as e:
            logger.warning("portrait.reload_layered_failed", error=str(e))

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
                self._launch_bg(
                    self._db.insert_notebook(
                        "focus", "icebreaker_deferred", importance=0.0,
                    ),
                    name="icebreaker_deferred",
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
            self._launch_bg(self._icebreaker_consolidate(), name="icebreaker_consolidate")

    async def _icebreaker_consolidate(self) -> None:
        """
        破冰后生成首版印象文档。

        Phase 1 改造：
        1. 强制编码当前对话为情景记忆（绕过三层调度）
        2. force=True → 级联粗粒化 L2→L1→L0（回退旧式全量重写）
        3. 同步加载分层画像
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

            # 2. force=True → 级联粗粒化（回退旧式全量重写）
            result = await self.portrait_manager.consolidate(force=True)
            if result:
                self.context.user_portrait = result
                self.context.icebreaker_active = False
                # Phase 2: 重新加载分层画像
                await self._reload_layered_portraits()
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

        # Phase 3: 从缓存中提取 persona_topics 传入编码管道
        persona_topics = None
        cached = getattr(self.context, '_persona_boost_config', None)
        if cached:
            persona_topics = cached.get("persona_topics")

        # Phase 1: 微事件提取 + 粗粒化已在 process() 中独立调度
        # 此处仅负责记忆编码，不再调用 mark_dirty()

        self._launch_bg(
            self.memory_manager.schedule_encoding(
                conversation_context, persona_topics=persona_topics,
            ),
            name="memory_encode",
        )

    # 图片记忆高价值判断：实体关键词（描述含这些词时编码为视觉记忆）
    _IMAGE_ENTITY_KEYWORDS: tuple[str, ...] = (
        "人", "脸", "自拍", "朋友", "家", "猫", "狗", "宠物",
        "书桌", "房间", "风景", "山", "海", "花", "孩子",
        "合影", "照片", "桌面", "电脑", "窗外", "阳台",
    )

    async def _encode_image_memory(self, desc: str, event: InternalEvent, reply: str):
        """高价值判断后编码图片记忆到 episodic_memories（后台异步）。"""
        if not desc or not event.images:
            return
        # 启发式：描述含实体 OR 情绪强度 > 0.6
        snap = self.context.emotion_snapshot
        intensity = snap.get("primary_intensity", 0) if snap else 0
        has_entity = any(kw in desc for kw in self._IMAGE_ENTITY_KEYWORDS)
        if not (has_entity or intensity > 0.6):
            return  # 低价值，不编码

        try:
            memory = {
                "kind": "visual_memory",
                "description": desc,
                "images": event.images,
                "user_message": event.payload,
                "assistant_reply": reply[:200],
            }
            await self._db.insert_episodic_memory(
                summary=f"[图片记忆] {desc[:100]}",
                raw_conversation=json.dumps(memory, ensure_ascii=False),
                importance=0.7 if has_entity else 0.5,
            )
            logger.debug("memory.image_encoded", preview=desc[:60])
        except Exception as e:
            logger.warning("memory.image_encode_failed", error=str(e))

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
                images=event.images if event.images else None,
            )
        except Exception as e:
            logger.warning("database.log_write_failed",
                          error_type=type(e).__name__,
                          error=str(e)[:200])

    # ============================================================
    # 上下文注入（向后兼容）
    # ============================================================

    # ============================================================
    # 消息构建
    # ============================================================

    async def _build_messages(self, user_msg: str) -> list[dict]:
        """
        构建模型输入消息列表。

        结构（前缀缓存优化 v4）：
          [system: 人格提示词]          ← IMMUTABLE PREFIX，永远缓存
          [system: 压缩摘要（若有）]     ← 极少变化
          [user₁][asst₁][user₂][asst₂]... ← APPEND-ONLY LOG，跨轮字节稳定
          [system: ctx_notes（若有）]    ← VOLATILE，每轮重建，不破坏前缀
          [user: raw_msg]               ← 当前消息

        关键不变量：history 中每条消息存储原始内容，绝不嵌入动态 ctx_notes。
        这确保 request N+1 的 history 前缀与 request N 的子前缀逐字节一致。
        """
        # 纯静态系统提示（前缀缓存友好，永远不变）
        messages = [{"role": "system", "content": self._personality}]

        # 压缩摘要（插入在人格提示词之后、原始历史之前，作为前缀锚点）
        summary = self.context.get_compressed_summary()
        if summary:
            messages.append({"role": "system", "content": summary})

        # 历史消息 — APPEND-ONLY LOG：只追加不改写，保持跨轮字节稳定
        history = self.context.get_messages(limit=20)
        messages.extend(history)

        # Phase 5: 设置当前消息供 PortraitModule 选择性注入
        self.context._last_user_message = user_msg

        # ctx_notes 作为独立 system 消息放在 history 之后、user 之前
        # VOLATILE SCRATCH 语义：每轮重建，不影响 history 前缀缓存
        ctx_notes = await self._context_builder.build()

        # 会话边界感知：长时间未对话后，注入自然时间锚点
        last_time = self.context._last_message_time
        if last_time and last_time > 0:
            gap_min = (time.time() - last_time) / 60
            if gap_min > 120:  # > 2 小时
                gap_note = "（今天第一次和伙伴聊天呢。）"
            elif gap_min > 30:
                gap_note = "（有一阵没见到伙伴了。）"
            else:
                gap_note = ""
            if gap_note:
                ctx_notes = f"{gap_note}\n\n{ctx_notes}" if ctx_notes else gap_note

        if ctx_notes:
            messages.append({"role": "system", "content": ctx_notes})

        messages.append({"role": "user", "content": user_msg})

        # Token 总量告警（仅日志，不裁剪）
        total_tokens = sum(estimate_tokens(m["content"]) for m in messages)
        if total_tokens > 8000:
            logger.warning("context.token_high",
                total=total_tokens,
                history_rounds=len(history) // 2,
                ctx_len=len(ctx_notes or ""),
            )

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
            tool_calls = current_message.tool_calls
            if not tool_calls:
                content = current_message.content or ''
                if content:
                    return self._clean_reply(content), all_tool_results
                return DEGRADED_REPLY, all_tool_results

            trace_log.info("tool.iteration", iter=iteration + 1,
                          count=len(tool_calls))

            # 执行所有工具调用 + 包装结果
            tool_msgs = []
            for tc in tool_calls:
                tool_name = _tc_function_name(tc)
                try:
                    arguments = json.loads(_tc_function_arguments(tc))
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
                    "tool_call_id": _tc_id(tc),
                    "content": wrapped,
                })
                trace_log.info("tool.result", tool=tool_name,
                              success=result.success)

            # 构建回传消息：assistant(tool_calls) + tool results
            # 必须保留原消息的 reasoning_content（DeepSeek thinking mode 要求）
            follow_up = list(messages)
            assistant_content = current_message.content
            assistant_msg = {
                "role": "assistant",
                "content": assistant_content,
                "tool_calls": [
                    {
                        "id": _tc_id(tc),
                        "type": "function",
                        "function": {
                            "name": _tc_function_name(tc),
                            "arguments": _tc_function_arguments(tc),
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
                # ── P1-②: 情绪调制 LLM 参数 ──
                emo_params_fu = self._emotion_modulated_params()
                result = await self.router.route(
                    "chat", follow_up,
                    temperature=emo_params_fu["temperature"],
                    max_tokens=emo_params_fu["max_tokens"],
                )
            except Exception as e:
                # LLM 回传失败 → 降级返回已包装的工具结果
                trace_log.error("tool.follow_up_error",
                              error_type=type(e).__name__,
                              error=str(e)[:200])
                fallback = tool_msgs[0]["content"] if tool_msgs else DEGRADED_REPLY
                return fallback, all_tool_results

            if result.tool_calls:
                current_message = result
                continue
            else:
                return self._clean_reply(result.content or ""), all_tool_results

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
        confirm_words = {"确认", "好的", "好", "可以", "行", "ok", "yes", "嗯", "做吧", "去吧", "执行", "确认执行"}

        if user_text in confirm_words:
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

    # ── 编造检测：LLM 编造的天气/时间数据不入上下文 ──

    _FABRICATED_WEATHER_RE = re.compile(
        r'\d{1,2}到\d{1,2}度|'           # 17到26度
        r'[1-7]级[东西南北]*风|'          # 3级北风
        r'(晴|阴|雨|雪|多云|雾|霾|雷)(转|到)|'  # 多云转晴
        r'气温\s*\d+|'                    # 气温 25
        r'\d+%\s*湿度'                    # 80% 湿度
    )

    def _sanitize_fabrication(self, reply: str, tools_called: bool) -> str:
        """如果本轮没调工具但回复含编造的天气数据，替换具体数值为占位符。
        这样后续对话上下文不会把编造数据当事实。"""
        if tools_called:
            return reply
        # 只影响存入 context 的版本，不影响用户看到的原始回复
        sanitized = self._FABRICATED_WEATHER_RE.sub('（未查询）', reply)
        if sanitized != reply:
            logger.debug("fabrication.sanitized", preview=reply[:60])
        return sanitized

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
        # 复用实例减少对象创建（MarkerParser 无状态，feed+flush 后重置）
        if not hasattr(self, '_marker_parser'):
            self._marker_parser = MarkerParser()
        parser = self._marker_parser
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

    def _resolve_sticker(self, sticker_id: str) -> dict | None:
        """
        根据 sticker_id 查找表情包元信息。
        从 data/stickers/catalog.json 加载完整元数据。
        """
        catalog = self._get_sticker_catalog()
        if catalog:
            for s in catalog.get("stickers", []):
                if s["id"] == sticker_id:
                    return {"id": s["id"], "file": s["file"]}
        return {"id": sticker_id, "file": ""}

    def _get_sticker_catalog(self) -> dict | None:
        """加载或返回缓存的 sticker catalog。"""
        if not hasattr(self, '_sticker_catalog_cache'):
            catalog_path = Path(__file__).resolve().parent.parent.parent / "data" / "stickers" / "catalog.json"
            try:
                import json
                self._sticker_catalog_cache = json.loads(catalog_path.read_text())
            except Exception:
                self._sticker_catalog_cache = None
        return self._sticker_catalog_cache

    def _get_available_sticker_ids(self) -> list[dict]:
        """返回可用 sticker 的 id + description 列表（供 ctx_notes 注入）。"""
        catalog = self._get_sticker_catalog()
        if not catalog:
            return []
        return [{"id": s["id"], "desc": s["description"]} for s in catalog.get("stickers", [])]

    # ── 表情包兜底（规则驱动）───────────────────────────────

    _sticker_cooldown: int = 0

    def _should_auto_sticker(self) -> bool:
        """检查是否应该自动发送表情包（兜底）。
        同时缓存 compute_profile 结果供 _pick_sticker_by_emotion 复用。"""
        import random
        if self._sticker_cooldown > 0:
            return False
        if not hasattr(self, 'emotion_engine') or self.emotion_engine is None:
            return False
        state = self.emotion_engine.state
        intensity = max(abs(state.pad[1]), abs(state.pad[2]))
        if intensity < 0.65:
            return False
        self._cached_emotion_profile = state.compute_profile()  # 缓存，避免重复计算
        if self._cached_emotion_profile.get("primary_emotion") in ("悲伤", "愤怒", "恐惧"):
            return False
        return random.random() < 0.6

    def _pick_sticker_by_emotion(self) -> dict | None:
        """根据当前情绪从 catalog 中选择表情包（加权随机）。
        优先使用 _should_auto_sticker 缓存的 profile，避免重复 compute_profile。"""
        import random
        if not hasattr(self, 'emotion_engine') or self.emotion_engine is None:
            return None
        catalog = self._get_sticker_catalog()
        if not catalog:
            return None

        profile = getattr(self, '_cached_emotion_profile', None)
        if profile is None:
            profile = self.emotion_engine.state.compute_profile()
        primary = profile.get("primary_emotion", "")

        candidates = []
        for s in catalog.get("stickers", []):
            if primary in s.get("emotion_tags", []):
                score = s.get("min_intensity", 0.5)
                candidates.append((s, score))

        if not candidates:
            return None

        total = sum(c[1] for c in candidates)
        r = random.random() * total
        acc = 0
        for s, score in candidates:
            acc += score
            if r <= acc:
                self._sticker_cooldown = s.get("cooldown_rounds", 3)
                return {"id": s["id"], "file": s["file"]}

        return None

    def _tick_sticker_cooldown(self):
        """每轮递减 sticker 冷却计数。"""
        if self._sticker_cooldown > 0:
            self._sticker_cooldown -= 1

    def _convert_to_multimodal(self, messages: list[dict], images: list[str], provider: str):
        """将最后一条 user 消息的 content 从 str 转为 multimodal content array。"""
        self._multimodal.convert_to_multimodal(messages, images, provider)

    def _resolve_image_url(self, url: str) -> str:
        """将本地相对路径转为 base64 data URL，远程 URL 原样返回。"""
        return self._multimodal._resolve_image_url(url)

    async def _describe_image(self, image_url: str) -> str:
        """
        使用 MiMo-V2.5 描述图片内容（视觉兜底）。

        Phase 2: 当主模型不支持 vision 时调用。
        缓存：同一 URL 在单次会话中只调用一次。
        """
        return await self._multimodal.describe_image(image_url)

    @staticmethod
    def _compress_image_desc(description: str, max_chars: int = 30) -> str:
        """将 MiMo 描述压缩为短句，用于嵌入 user_message 存入历史。"""
        return MultimodalProcessor.compress_image_desc(description, max_chars)

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

    async def reset_session(self) -> None:
        """重置会话（取消 pending 分析 + 清空历史 + 上下文 + 清 DB 日志 + 重置运行时状态）"""
        if self._pending_analysis and not self._pending_analysis.done():
            self._pending_analysis.cancel()
            self._pending_analysis = None
        self.context.clear()
        # 重置会话级运行时状态（保留持久化状态如 affection_score）
        self._pending_confirmation = None
        self._round_count = 0
        self._drift_counter = 0
        self._sticker_cooldown = 0
        self._emotion_flat_rounds = 0
        self._last_modulated_params = None
        self._last_eval_data = None
        self._strategy_effectiveness = {}
        self._current_images = []
        self._user_sent_sticker = False
        self._emotion_generation = 0
        self._last_interaction_time = 0.0
        self.is_safe_mode = False
        try:
            deleted = await self._db.clear_conversation_logs()
            logger.info("agent.session_reset", db_rows_cleared=deleted)
        except Exception as e:
            logger.warning("agent.session_reset_db_failed", error=str(e))

    async def _ensure_character_memories(self) -> int:
        """
        确保角色情景记忆已导入数据库（幂等，项目首次启动自动执行）。

        检查 episodic_memories 中 source='character' 的记录数。
        若不足 24 条，从 data/character_memories.json 读取并向量化导入。
        """
        from pathlib import Path
        import json

        # 防御：mock DB / 未完全初始化的 DB 不执行
        if self._db._conn is None:
            logger.debug("character_memories.skip", reason="db_not_initialized")
            return 0

        # 检查已有角色记忆数
        cursor = await self._db._conn.execute(
            "SELECT COUNT(*) FROM episodic_memories WHERE session_id = 'character'"
        )
        row = await cursor.fetchone()
        existing = row[0] if row else 0

        if existing >= 24:
            logger.info("character_memories.ok", count=existing)
            return 0

        # 读取 JSON
        json_path = Path(__file__).resolve().parent.parent.parent / "data" / "character_memories.json"
        if not json_path.exists():
            logger.warning("character_memories.json_missing", path=str(json_path))
            return 0

        logger.info("character_memories.seeding", existing=existing, total=24)
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)

        source = data.get("source", "character")
        inserted = 0
        for entry in data.get("entries", []):
            eid = entry["id"]
            summary = entry["content"]

            try:
                # 去重：文本匹配
                dup = await self._db._conn.execute(
                    "SELECT COUNT(*) FROM episodic_memories WHERE session_id = ? AND summary = ?",
                    (source, summary),
                )
                if (await dup.fetchone())[0] > 0:
                    continue

                # 向量化（无 Key 时跳过）
                vector = await self.router.embed(summary) if self.router else None

                # 写入 episodic_memories
                import json as _json
                emotion_tags = _json.dumps({
                    "character_id": eid,
                    "category": entry["category"],
                    "tags": entry["tags"],
                    "source": source,
                }, ensure_ascii=False)

                cursor = await self._db._conn.execute(
                    """INSERT INTO episodic_memories
                       (timestamp, summary, raw_conversation, emotion_tags, importance,
                        embedding_model, embedding_version, embedding_status, session_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                    (
                        __import__("time").time(),
                        summary,
                        summary,
                        emotion_tags,
                        entry["importance"],
                        self.router._embed_model if self.router else "bge-m3",
                        "v1",
                        source,
                    ),
                )
                episodic_id = cursor.lastrowid
                await self._db._conn.commit()

                # 写入向量（无 Key 时跳过）
                if vector is not None:
                    await self._vector_store.insert(row_id=episodic_id, embedding=vector)

                # 标记状态
                await self._db.update_embedding_status(
                    episodic_id, "done" if vector is not None else "pending", eid
                )

                inserted += 1
                logger.debug("character_memories.seeded", id=eid, episodic_id=episodic_id)

            except Exception as exc:
                logger.error("character_memories.seed_error", id=eid, error=str(exc)[:120])

        logger.info("character_memories.seeded_done", inserted=inserted, total=len(data.get("entries", [])))
        return inserted

    # ============================================================
    # 阶段 2: 情感分析管道
    # ============================================================

    def _schedule_emotion_analysis(self, user_message: str) -> asyncio.Task | None:
        """
        启动后台情感分析任务。

        v2: 使用代数计数器代替 cancel——不再取消前一个分析，
        而是让旧分析完成但不采纳其结果（如果代数已过期）。
        这样每条消息都能触发分析，不会被快速连发消息打断。
        """
        self._emotion_generation += 1
        gen = self._emotion_generation

        self._pending_analysis = asyncio.create_task(
            self._run_emotion_analysis(user_message, gen)
        )
        return self._pending_analysis

    async def _run_emotion_analysis(self, user_message: str, generation: int = 0) -> None:
        """
        后台执行情感分析 + PAD 情绪更新。

        v2: 接受 generation 参数——只有当前代数匹配时才应用结果。
        避免了快速连发消息时旧分析覆盖新状态的问题。
        """
        try:
            # ── P1-③: 评价上一轮回应的情绪改善效果 ──
            await self._evaluate_last_response(user_message)

            # ── 阶段 4: PAD 情感引擎 ──
            last_gap = time.time() - self._last_interaction_time if self._last_interaction_time > 0 else 0.0
            pad_profile = await self.emotion_engine.process_message(user_message, last_interaction_gap=last_gap)

            # 代数检查：如果期间有新消息触发了更新的分析，丢弃旧结果
            if generation < self._emotion_generation:
                logger.debug(
                    "emotion.analysis_stale",
                    generation=generation,
                    current=self._emotion_generation,
                )
                return
            if pad_profile:
                # 存储 PAD 结果到 context（兼容旧的 emotion_snapshot 字段）
                self.context.emotion_snapshot = pad_profile

                # 写入 DB 情感快照
                if self._db and self._db._conn:
                    appraisal = pad_profile.get("appraisal", {})
                    # ── P1-①: 捕获本轮检索到的记忆 ID（取第一个有效 ID）──
                    trigger_id = None
                    for mem_list in (self.context.memory_retrieval, self.context.character_memory_retrieval):
                        if mem_list:
                            for m in mem_list:
                                mid = m.get("id")
                                if mid is not None:
                                    trigger_id = mid
                                    break
                        if trigger_id is not None:
                            break

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
                        trigger_memory_id=trigger_id,  # P1-①
                    )

                # ── P1-②: 跟踪情绪平坦度（供参数调制防锁死）──
                prev_pad = getattr(self, '_prev_pad_for_flatness', (0.0, 0.0, 0.0))
                curr_p, curr_a, curr_d = self.emotion_engine.state.pad
                pad_delta = math.sqrt(
                    (curr_p - prev_pad[0])**2 + (curr_a - prev_pad[1])**2 + (curr_d - prev_pad[2])**2
                )
                if pad_delta < 0.1:
                    self._emotion_flat_rounds += 1
                else:
                    self._emotion_flat_rounds = 0
                self._prev_pad_for_flatness = (curr_p, curr_a, curr_d)

                logger.debug(
                    "emotion.pad_updated",
                    pad=f"({curr_p:.2f},{curr_a:.2f},{curr_d:.2f})",
                    emotion=pad_profile.get("primary_emotion"),
                    flat_rounds=self._emotion_flat_rounds,
                )

                # 更新好感度
                await self._update_affection(pad_profile)
        except asyncio.CancelledError:
            logger.debug("emotion.analysis_cancelled")
        except Exception as e:
            logger.warning(
                "emotion.analysis_failed",
                error_type=type(e).__name__,
                error=str(e)[:200],
            )

    # ============================================================
    # P1-③: 情绪反馈闭环 — 评价提示词
    # ============================================================

    _EMOTION_EVAL_PROMPT = (
        "你是昔涟。回顾刚才那一轮对话——人家说了那句话之后，伙伴的心情有没有好一点点？\n"
        "\n"
        "返回 JSON（只返回这个）：\n"
        '{"improved": 0.0-1.0, "reason": "一句话"}\n'
        "\n"
        "- improved: 伙伴回应里透出的情绪，比之前好一些了吗？\n"
        "  0.0-0.3 = 更差了或还是很难过\n"
        "  0.4-0.6 = 差不多，没有明显变化\n"
        "  0.7-1.0 = 有在变好，哪怕是轻轻的一点点\n"
        "- reason: 简短说明（昔涟口吻）\n"
        "\n"
        "诚实评价。不用安慰自己。如果人家没帮上忙，就说没帮上。"
    )

    # ============================================================
    # P1-②: 情绪→LLM 参数调制（含防锁死）
    # ============================================================

    def _emotion_modulated_params(self) -> dict:
        """
        根据当前 PAD 状态返回 LLM 调用参数调制。

        当前调制维度：temperature（受 arousal 影响）、max_tokens（受 dominance 影响）。
        top_p / presence_penalty 待 router 支持后启用（Phase 2）。

        防锁死机制：
          1. 单轮参数变化上限 ±12%（temperature）/ ±50（max_tokens）
          2. 连续 10 轮 PAD 无显著变化 → 参数逐步回归默认值
          3. 参数在合理范围内 clamp
        """
        state = self.emotion_engine.state
        p, a, d = state.pad

        # 默认值（temperature 0.65→0.75 微调；max_tokens 基线 600 使调制范围 500-837 ≈ 旧值 800）
        base_temp, base_tokens = 0.75, 600

        # PAD → 目标偏移
        # arousal → temperature: 平静=0.65, 兴奋=0.95
        temp_target = base_temp + a * 0.15
        # dominance → max_tokens: 低落=100, 掌控=600
        tokens_target = base_tokens + int(d * 250)

        # 防锁死 1: 单轮变化上限
        prev = self._last_modulated_params or {
            "temperature": base_temp, "max_tokens": base_tokens,
        }
        temp = prev["temperature"] + max(-0.12, min(0.12, temp_target - prev["temperature"]))
        tokens = prev["max_tokens"] + max(-50, min(50, tokens_target - prev["max_tokens"]))

        # 防锁死 2: 回归均值力（PAD 连续平坦 > 10 轮 → 逐渐回归默认）
        if self._emotion_flat_rounds > 10:
            alpha = min(0.05 * (self._emotion_flat_rounds - 10), 0.5)
            temp = temp * (1 - alpha) + base_temp * alpha
            tokens = int(tokens * (1 - alpha) + base_tokens * alpha)

        self._last_modulated_params = {
            "temperature": max(0.6, min(0.95, temp)),
            "max_tokens": max(100, min(900, tokens)),
        }
        return self._last_modulated_params

    # ── P1-③: 评价上一轮回应效果 ────────────────────────

    async def _evaluate_last_response(self, current_user_msg: str) -> None:
        """后台评价上一轮回应的情绪改善效果，更新策略有效性追踪。"""
        if not self._last_eval_data:
            return

        prev_data = self._last_eval_data
        self._last_eval_data = None  # 只消费一次

        strategy = prev_data.get("strategy", "")
        if not strategy:
            return

        try:
            messages = [
                {"role": "system", "content": self._EMOTION_EVAL_PROMPT},
                {"role": "user", "content": (
                    f"伙伴说：{prev_data['user_msg']}\n\n"
                    f"人家回应：{prev_data['response']}\n\n"
                    f"伙伴现在说：{current_user_msg}"
                )},
            ]
            raw = await self.router.route(
                "emotion_analysis",  # 走 Flash
                messages,
                temperature=0.3,
                max_tokens=60,
            )
            raw_text = raw.content if hasattr(raw, 'content') else str(raw)

            # 解析 JSON
            import json as _json
            data = None
            try:
                data = _json.loads(raw_text)
            except _json.JSONDecodeError:
                # 尝试提取 {...}
                try:
                    start = raw_text.index("{")
                    end = raw_text.rindex("}") + 1
                    data = _json.loads(raw_text[start:end])
                except (ValueError, _json.JSONDecodeError):
                    pass

            if data is None:
                return

            improved = data.get("improved", 0.5)
            improved = max(0.0, min(1.0, float(improved)))

            # ── 置信度边界：仅当评价看起来合理时才更新 ──
            # 简单的启发式：improved 在 0.2-0.8 范围内视为有区分度的评价
            if 0.15 <= improved <= 0.85:
                if strategy not in self._strategy_effectiveness:
                    self._strategy_effectiveness[strategy] = []
                self._strategy_effectiveness[strategy].append(improved)
                # 保留最近 50 个样本
                if len(self._strategy_effectiveness[strategy]) > 50:
                    self._strategy_effectiveness[strategy] = \
                        self._strategy_effectiveness[strategy][-50:]

                logger.debug(
                    "emotion.eval_complete",
                    strategy=strategy,
                    improved=round(improved, 2),
                    samples=len(self._strategy_effectiveness[strategy]),
                )

        except Exception as e:
            logger.debug("emotion.eval_failed", error=str(e)[:120])

    # ============================================================
    # 好感度系统
    # ============================================================

    async def _update_affection(self, pad_profile: dict) -> None:
        """
        根据本轮情绪更新好感度。

        规则（v2 加速）：
          - 基础增长 0.5/轮（原 0.05，加速 10x）
          - 积极情绪加成：快乐/信任/期待 +1.0, 平静 +0.5
          - 红线扣减：人格漂移 OR 强烈负面(愤怒/厌恶/恐惧,intensity>0.5) → -1.0
          - 单轮上限：+2.0 max, -1.0 max
          - 等级阈值：20(2级)/50(3级)/80(4级)
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

            # 1. 基础增长（v2: 0.5/轮，约 40 轮到等级 2）
            delta = 0.5
            reason = "base_increment"

            # 2. 积极情绪加成（v2: +1.0 / +0.5）
            primary = pad_profile.get("primary_emotion", "")
            intensity = pad_profile.get("primary_intensity", 0.0)
            positive_high = {"快乐", "信任", "期待"}
            positive_low = {"平静"}

            if primary in positive_high:
                delta += 1.0
                reason = f"{primary}_bonus"
            elif primary in positive_low:
                delta += 0.5
                reason = f"{primary}_bonus"

            # 3. 红线扣减（v2: -1.0）
            negative_strong = {"愤怒", "厌恶", "恐惧"}
            red_line_hit = False
            if self._drift_counter > 0:
                red_line_hit = True
            if primary in negative_strong and intensity > 0.5:
                red_line_hit = True

            if red_line_hit:
                delta = -1.0
                reason = "red_line_hit"

            # 4. 钳制（v2: +2.0 / -1.0）
            delta = max(-1.0, min(2.0, delta))

            # 5. 应用
            new_score = old_score + delta
            new_score = max(0.0, min(100.0, new_score))
            new_score = round(new_score, 2)

            # 6. 锁定检查
            if new_score >= 100.0:
                new_score = 100.0
                reason = f"{reason}_max_locked"

            # 7. 等级计算（v2 阈值: 20/50/80）
            if new_score >= 80:
                level = 4
            elif new_score >= 50:
                level = 3
            elif new_score >= 20:
                level = 2
            else:
                level = 1

            self._affection_score = new_score
            self._affection_level = level
            self._total_conversations += 1

            # 同步好感度到 ContextBuilder AffectionModule
            aff_module = self._context_builder.get_module("affection")
            if aff_module:
                aff_module.set_state(self._affection_score, self._affection_level)

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
            prompt = self.PERSONALITY_SCORING_PROMPT.replace("{replies}", replies_text)

            result = await self.router.route(
                "personality_check",
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=40,
            )
            result = result.content.strip() if hasattr(result, 'content') else result.strip()

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
