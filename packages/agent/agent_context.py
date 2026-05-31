"""
AgentContext — Agent 上下文容器

维护对话历史和情感/记忆模块接口。阶段 B：滑动窗口 + Flash 压缩。
"""
from dataclasses import dataclass, field
from typing import Optional, Callable

# ═══════════════════════════════════════════════════════════
# 上下文压缩参数
# ═══════════════════════════════════════════════════════════

COMPRESS_SOFT_LIMIT = 12       # 超过此轮数开始考虑压缩
COMPRESS_BATCH = 4             # 每次压缩最老的 N 轮
MAX_RAW_ROUNDS = 16            # 硬上限：最近 N 轮绝不可压缩
COMPRESS_SUMMARY_PREFIX = "（昔涟在书页边缘轻轻记下："


@dataclass
class AgentContext:
    """Agent 运行上下文，各模块接口预留"""

    # 对话历史：简单列表 [{role, content}]
    # 正常消息 role = "user"/"assistant"
    # 压缩摘要 role = "system", content 以 COMPRESS_SUMMARY_PREFIX 开头
    history: list[dict] = field(default_factory=list)

    # 阶段 2：情绪快照（来自 EmotionAnalyzer 后台分析）
    emotion_snapshot: Optional[dict] = None

    # 阶段 3：记忆检索结果 [{summary, score, ...}]
    memory_retrieval: Optional[list] = None

    # 阶段 9：角色情景记忆检索结果（昔涟自己的过去）
    character_memory_retrieval: Optional[list] = None

    # 阶段 8+: 用户印象文档（保留兼容）
    user_portrait: Optional[str] = None
    _current_portrait_version: Optional[int] = None
    _portrait_version_injected: Optional[int] = None

    # Phase 2: 分层画像
    core_profile: Optional[str] = None        # L0 核心画像
    _current_l0_version: Optional[int] = None
    _l0_version_injected: Optional[int] = None

    phase_profile: Optional[str] = None       # L1 阶段画像
    _current_l1_version: Optional[int] = None
    _l1_version_injected: Optional[int] = None

    # 阶段 8+: 破冰冷启动（仅内存状态，不持久化）
    icebreaker_active: bool = False
    icebreaker_exchanges: int = 0
    icebreaker_deferred: bool = False  # 持久化标记：用户拒绝过破冰

    # ── 阶段 B: 压缩内部状态 ──
    _total_history_tokens: int = 0
    _compress_callback: Optional[Callable] = None  # memory_manager.compress_history
    _history_compressed: bool = False  # 是否有压缩摘要存在

    # ── 阶段 C: 跨会话感知 ──
    _last_message_time: float = 0.0     # 上次对话时间戳
    _cross_session_hint_used: bool = False  # 本轮启动后是否已发过提示

    # Phase 5: 当前用户消息（供 PortraitModule 选择性注入）
    _last_user_message: str = ""

    # Phase 5: ModelRouter 引用（供 PortraitGuidanceModule Flash LLM 提取）
    _router: Optional[object] = None

    # ============================================================
    # 对话历史
    # ============================================================

    def set_compress_callback(self, cb: Callable) -> None:
        """注入压缩回调（memory_manager.compress_history）。"""
        self._compress_callback = cb

    def add_message(self, role: str, content: str) -> None:
        """添加一条消息到历史，触发压缩检查。"""
        from .context_builder import estimate_tokens

        self.history.append({"role": role, "content": content})
        self._total_history_tokens += estimate_tokens(content)

        # 硬上限保护：最近 MAX_RAW_ROUNDS 轮绝不可压缩
        # 配合 COMPRESS_SOFT_LIMIT=12，
        # 实际首次压缩发生在 16+4=20 轮时（压缩最老的 4 轮）
        raw_rounds = self._count_raw_rounds()
        if raw_rounds <= MAX_RAW_ROUNDS:
            return

        # 软上限：超过 COMPRESS_SOFT_LIMIT 后，每增长 COMPRESS_BATCH 轮压缩一次
        if raw_rounds <= COMPRESS_SOFT_LIMIT:
            return

        # 计算可压缩的最老轮数（超出硬上限的部分）
        oldest_compressible = raw_rounds - MAX_RAW_ROUNDS
        if oldest_compressible < COMPRESS_BATCH:
            return

        # 触发压缩（fire-and-forget）
        self._schedule_compression(COMPRESS_BATCH)

    def _count_raw_rounds(self) -> int:
        """统计 history 中的原始对话轮数（不含摘要条目）。"""
        rounds = 0
        for msg in self.history:
            if msg["role"] in ("user", "assistant"):
                rounds += 1
        return rounds // 2

    def _schedule_compression(self, n_rounds: int) -> None:
        """调度后台压缩：取最老的 n 轮，异步压缩。"""
        if not self._compress_callback:
            return

        # 找到最老的 n 轮原始消息（跳过已有摘要条目）
        raw_indices = [
            i for i, m in enumerate(self.history)
            if m["role"] in ("user", "assistant")
        ]
        if len(raw_indices) < n_rounds * 2:
            return

        # 取出最老的 n 轮（2n 条消息）
        oldest_indices = raw_indices[:n_rounds * 2]
        oldest_msgs = [self.history[i] for i in oldest_indices]

        # 从 history 中移除这些消息，同步扣减 token 计数
        from .context_builder import estimate_tokens as _et
        for i in reversed(oldest_indices):
            removed = self.history.pop(i)
            self._total_history_tokens -= _et(removed["content"])

        # fire-and-forget 压缩
        import asyncio
        async def _compress():
            try:
                summary = await self._compress_callback(oldest_msgs)
                if summary:
                    self._inject_summary(summary)
            except Exception:
                pass  # 压缩失败静默，不影响对话

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(_compress())
        except RuntimeError:
            pass

    def _inject_summary(self, summary: str) -> None:
        """将压缩摘要插入 history 顶部（在所有原始消息之前）。"""
        # 如果已有摘要，与旧摘要合并（保留旧 + 追加新）
        existing_idx = None
        for i, m in enumerate(self.history):
            if m["role"] == "system" and m["content"].startswith(COMPRESS_SUMMARY_PREFIX):
                existing_idx = i
                break

        from .context_builder import estimate_tokens as _et

        if existing_idx is not None:
            # 合并：取旧摘要结尾 + 新摘要开头，拼接
            old_content = self.history[existing_idx]["content"]
            old_tokens = _et(old_content)
            merged = old_content.rstrip("）") + "；" + summary.lstrip(COMPRESS_SUMMARY_PREFIX).lstrip("（")
            self.history[existing_idx]["content"] = merged
            self._total_history_tokens += _et(merged) - old_tokens
        else:
            self.history.insert(0, {"role": "system", "content": summary})
            self._total_history_tokens += _et(summary)

        self._history_compressed = True

    def get_compressed_summary(self) -> str | None:
        """获取当前压缩摘要文本（供 ContextBuilder/MemoryModule 使用）。"""
        for m in self.history:
            if m["role"] == "system" and m["content"].startswith(COMPRESS_SUMMARY_PREFIX):
                return m["content"]
        return None

    def get_messages(self, limit: int = 20) -> list[dict]:
        """返回最近 N 条消息，供构建模型输入。跳过摘要条目。"""
        raw = [m for m in self.history if m["role"] != "system"]
        return raw[-limit:] if len(raw) > limit else raw

    def get_last_n(self, n: int = 5) -> list[dict]:
        """返回最后 N 条消息"""
        return self.history[-n:] if self.history else []

    def clear(self) -> None:
        """清空对话历史（新会话）"""
        self.history.clear()
        self._total_history_tokens = 0
        self._history_compressed = False
        self._last_message_time = 0.0
        self._cross_session_hint_used = False
        self.emotion_snapshot = None
        self.memory_retrieval = None
        self.character_memory_retrieval = None
        self._current_portrait_version = None
        self._portrait_version_injected = None
        self.core_profile = None
        self._current_l0_version = None
        self._l0_version_injected = None
        self.phase_profile = None
        self._current_l1_version = None
        self._l1_version_injected = None
        self._persona_boost_config = None  # Phase 3 缓存
        self.icebreaker_active = False
        self.icebreaker_exchanges = 0

    def __repr__(self) -> str:
        return (
            f"AgentContext(history={len(self.history)} msgs, "
            f"compressed={self._history_compressed}, "
            f"tokens={self._total_history_tokens}, "
            f"emotion={'yes' if self.emotion_snapshot else 'no'})"
        )
