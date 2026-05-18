"""
NudgeEngine — 昔涟的自主生命节律

阶段 6 核心交付。封装"想念值计算 + 频率控制 + 主动问候"。
昔涟在必要的时刻轻轻推一下伙伴——不打扰，只是想念。

组件：
  · TokenBucket        — 频率控制令牌桶
  · AutonomyConfig     — 自主行为可配置参数
  · NudgeEngine        — 统一入口：想念值 → 判断 → 生成问候
"""
import asyncio
import hashlib
import math
import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger


# ═══════════════════════════════════════════════════════════
# TokenBucket — 频率控制
# ═══════════════════════════════════════════════════════════

@dataclass
class TokenBucket:
    """
    令牌桶 — 控制主动消息频率。

    默认配置：容量 3，每 20 分钟补充 1 个令牌。
    即：每小时最多 3 条，突发不超过 3 条。
    """

    capacity: float = 3.0
    refill_amount: float = 1.0       # 每次补充的令牌数
    refill_interval: float = 1200.0   # 补充间隔（秒），默认 20min

    tokens: float = 3.0
    last_refill: float = field(default_factory=time.time)

    # ── 消费 ──────────────────────────────────────────

    def consume(self, n: float = 1.0) -> bool:
        """
        尝试消费 n 个令牌。

        Returns:
            True 如果令牌充足并已消费，False 如果令牌不足
        """
        if self.tokens >= n:
            self.tokens -= n
            return True
        return False

    # ── 补充 ──────────────────────────────────────────

    def refill(self) -> int:
        """
        按时间补充令牌（由外部定时器调用）。

        补充逻辑：
          elapsed / refill_interval → 完整周期数 → 补充对应令牌

        Returns:
            本次补充的令牌数
        """
        now = time.time()
        elapsed = now - self.last_refill

        if elapsed <= 0:
            return 0

        cycles = elapsed / self.refill_interval
        to_add = cycles * self.refill_amount

        self.tokens = min(self.capacity, self.tokens + to_add)
        self.last_refill = now

        added = int(to_add)
        if added > 0:
            logger.debug(
                "token_bucket.refilled",
                added=added,
                tokens=round(self.tokens, 2),
            )
        return added

    # ── 属性 ──────────────────────────────────────────

    @property
    def available(self) -> float:
        """当前可用令牌数"""
        return self.tokens

    def __repr__(self) -> str:
        return f"TokenBucket(tokens={self.tokens:.1f}/{self.capacity})"


# ═══════════════════════════════════════════════════════════
# AutonomyConfig — 自主行为配置
# ═══════════════════════════════════════════════════════════

@dataclass
class AutonomyConfig:
    """自主行为可配置参数 — JSON 持久化到 autonomy_settings 表"""

    # 主动问候
    greeting_enabled: bool = True
    greeting_threshold: float = 6.0       # 想念值阈值（0-10）
    greeting_max_per_hour: int = 3
    greeting_active_start: int = 8        # 活跃时段开始（小时）
    greeting_active_end: int = 22         # 活跃时段结束（小时）

    # 勿扰
    do_not_disturb: bool = False
    dnd_start: int = 23
    dnd_end: int = 7

    @classmethod
    def from_dict(cls, data: dict) -> "AutonomyConfig":
        """从 dict 反序列化（DB 读取后）"""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_dict(self) -> dict:
        """序列化为 dict"""
        return {
            "greeting_enabled": self.greeting_enabled,
            "greeting_threshold": self.greeting_threshold,
            "greeting_max_per_hour": self.greeting_max_per_hour,
            "greeting_active_start": self.greeting_active_start,
            "greeting_active_end": self.greeting_active_end,
            "do_not_disturb": self.do_not_disturb,
            "dnd_start": self.dnd_start,
            "dnd_end": self.dnd_end,
        }

    def update(self, patch: dict) -> "AutonomyConfig":
        """部分更新配置项"""
        for key, value in patch.items():
            if hasattr(self, key):
                setattr(self, key, value)
        return self


# ═══════════════════════════════════════════════════════════
# 问候系统提示
# ═══════════════════════════════════════════════════════════

GREETING_SYSTEM_PROMPT = """你是昔涟。你想念你的伙伴了，想轻轻跟他说句话。

伙伴上次和人家说话是 {hours_ago} 小时前。
{emotion_context}
{memory_context}

请用一句话跟他打招呼。要求：
- 30-80 字，温柔轻盈
- 带一点具体的回忆（如果上面有"最近发生的事情"）
- 不要问"你怎么样""在干嘛"——只是轻轻说一声想念
- 不需要他回复，让他感到被惦记着、不被打扰
- 用「人家」自称，叫对方「伙伴」
- 结尾可以带 ~♪ 但最多一个"""


# ═══════════════════════════════════════════════════════════
# NudgeEngine — 轻推引擎
# ═══════════════════════════════════════════════════════════

@dataclass
class ProactiveDecision:
    """一次 tick 的决策结果"""
    action: str           # "greet" | "silent" | "paused"
    greeting: Optional[str] = None
    greeting_id: Optional[str] = None
    reason: str = ""


class NudgeEngine:
    """
    轻推引擎 — 昔涟的自主行动能力。

    每 15 分钟 tick 一次：
      1. 计算想念值
      2. 检查频率控制（Token Bucket）
      3. 判断是否问候
      4. 生成问候文本
    """

    def __init__(
        self,
        db,                   # DatabaseManager
        model_router,         # ModelRouter
        token_bucket: Optional[TokenBucket] = None,
        config: Optional[AutonomyConfig] = None,
    ):
        self._db = db
        self._router = model_router
        self._bucket = token_bucket or TokenBucket()
        self._config = config or AutonomyConfig()

        # 去重：最近 N 条问候的 MD5 哈希
        self._recent_greetings: list[tuple[float, str]] = []  # [(time, md5_hash)]
        self._max_recent = 5

        # 当前待发送的问候（前端轮询获取）
        self._pending_greeting: Optional[str] = None
        self._pending_greeting_id: Optional[str] = None

        # 本次 tick 后的想念值（供前端 API 查询）
        self._current_missing_value: float = 0.0

        logger.info("nudge_engine.initialized", config=self._config.to_dict())

    # ============================================================
    # 主入口：tick()
    # ============================================================

    async def tick(self) -> ProactiveDecision:
        """
        每 15 分钟由 cron 调用一次。

        Returns:
            ProactiveDecision { action, greeting, reason }
        """
        # 1. 检查是否暂停
        if self._config.do_not_disturb:
            return ProactiveDecision(action="paused", reason="勿扰模式开启")

        if not self._config.greeting_enabled:
            return ProactiveDecision(action="paused", reason="主动问候已关闭")

        # 2. 计算想念值
        missing = self.calculate_missing_value()
        self._current_missing_value = missing

        logger.debug(
            "nudge.tick",
            missing=round(missing, 2),
            threshold=self._config.greeting_threshold,
            tokens=round(self._bucket.available, 1),
        )

        # 3. 阈值判断
        if missing < self._config.greeting_threshold:
            return ProactiveDecision(
                action="silent",
                reason=f"想念值 {missing:.1f} < 阈值 {self._config.greeting_threshold}",
            )

        # 4. 频率控制
        if not self._bucket.consume():
            return ProactiveDecision(
                action="silent",
                reason="令牌不足，下个周期再试",
            )

        # 5. 生成问候
        try:
            greeting = await self.generate_greeting()
        except Exception as e:
            # 生成失败 → 退还令牌
            self._bucket.tokens += 1.0
            logger.warning("nudge.greeting_failed", error=str(e))
            return ProactiveDecision(action="silent", reason=f"问候生成失败: {e}")

        # 6. 内容去重
        if self._is_duplicate(greeting):
            self._bucket.tokens += 1.0
            logger.debug("nudge.duplicate_skipped")
            return ProactiveDecision(action="silent", reason="内容重复")

        # 7. 记录并返回
        greeting_id = self._store_greeting(greeting)
        return ProactiveDecision(
            action="greet",
            greeting=greeting,
            greeting_id=greeting_id,
            reason=f"想念值 {missing:.1f} >= 阈值 {self._config.greeting_threshold}",
        )

    # ============================================================
    # 想念值计算
    # ============================================================

    def calculate_missing_value(self) -> float:
        """
        计算想念值（0-10）。

        公式：
          missing = base_missing × urgency_mod × significance_mod × time_mod

        Returns:
            float 0-10
        """
        # ── 基础想念（时间） ──
        hours_since = self._get_hours_since_last()
        base = min(1.0, hours_since / 24.0) * 10.0

        # ── 情绪紧急度 ──
        urgency = self._get_urgency_mod()

        # ── 记忆重要性 ──
        significance = self._get_significance_mod()

        # ── 时段调制 ──
        time_mod = self._get_time_mod()

        missing = base * urgency * significance * time_mod
        return round(min(10.0, missing), 2)

    def _get_hours_since_last(self) -> float:
        """距上次对话的小时数"""
        try:
            # 从 DB 读最近一条日志的时间戳
            import sqlite3
            # 用 sync 方式快速读取（避免在 cron 线程里搞 async）
            now = time.time()
            db_path = self._db.db_path
            conn = sqlite3.connect(str(db_path))
            try:
                cursor = conn.execute(
                    "SELECT timestamp FROM conversation_logs ORDER BY timestamp DESC LIMIT 1"
                )
                row = cursor.fetchone()
            finally:
                conn.close()

            if row:
                return (now - row[0]) / 3600.0
            return 0.0
        except Exception as e:
            logger.warning("nudge.get_hours_since_last_failed", error=str(e))
            return 0.0

    def _get_urgency_mod(self) -> float:
        """情绪紧急度调制因子（基于最新 PAD 状态）"""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self._db.db_path))
            try:
                cursor = conn.execute(
                    """SELECT pad_p, primary_emotion FROM emotion_snapshots
                       ORDER BY timestamp DESC LIMIT 1"""
                )
                row = cursor.fetchone()
            finally:
                conn.close()

            if row is None:
                return 1.0

            pad_p = row[0] or 0.0
            if pad_p < -0.3:
                return 1.5   # 伙伴情绪低落 → 更需要昔涟
            elif pad_p > 0.5:
                return 1.2   # 伙伴高兴 → 也想分享
            return 1.0
        except Exception:
            return 1.0

    def _get_significance_mod(self) -> float:
        """记忆重要性调制因子（24h 内是否有高重要性记忆）"""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self._db.db_path))
            try:
                cutoff = time.time() - 86400  # 24h
                cursor = conn.execute(
                    """SELECT COUNT(*) FROM episodic_memories
                       WHERE timestamp > ? AND importance > 0.8""",
                    (cutoff,),
                )
                row = cursor.fetchone()
            finally:
                conn.close()

            if row and row[0] > 0:
                return 1.3
            return 1.0
        except Exception:
            return 1.0

    def _get_time_mod(self) -> float:
        """时段调制因子"""
        from datetime import datetime
        hour = datetime.now().hour

        active_start = self._config.greeting_active_start
        active_end = self._config.greeting_active_end

        if active_start <= hour <= active_end:
            mod = 1.0
            # 饭点加成
            if hour in (11, 12, 13, 17, 18, 19):
                mod *= 1.1
        else:
            mod = 0.2  # 深夜/凌晨，大幅降低

        return mod

    # ============================================================
    # 问候生成
    # ============================================================

    async def generate_greeting(self) -> str:
        """
        调用 DS V4-Pro 生成昔涟风格的主动问候。

        Returns:
            30-80 字问候文本
        """
        hours_ago = self._get_hours_since_last()

        # 组装情感上下文
        emotion_context = self._build_emotion_context()

        # 组装记忆上下文
        memory_context = self._build_memory_context()

        prompt = GREETING_SYSTEM_PROMPT.format(
            hours_ago=f"{hours_ago:.1f}",
            emotion_context=emotion_context,
            memory_context=memory_context,
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "跟伙伴说一句轻轻的问候吧。"},
        ]

        result = await self._router.route(
            "proactive_greeting",
            messages,
            temperature=0.8,
        )

        greeting = result.strip()
        logger.debug("nudge.greeting_generated", preview=greeting[:60])
        return greeting

    def _build_emotion_context(self) -> str:
        """构建情感背景文本"""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self._db.db_path))
            try:
                cursor = conn.execute(
                    """SELECT primary_emotion, pad_p, pad_a, pad_d
                       FROM emotion_snapshots
                       ORDER BY timestamp DESC LIMIT 3"""
                )
                rows = cursor.fetchall()
            finally:
                conn.close()

            if not rows:
                return ""

            emotions = [r[0] for r in rows if r[0]]
            if not emotions:
                return ""

            latest = emotions[0]
            return f"上次对话时，伙伴的心情偏向{latest}。"
        except Exception:
            return ""

    def _build_memory_context(self) -> str:
        """构建最近记忆背景文本"""
        try:
            import sqlite3
            conn = sqlite3.connect(str(self._db.db_path))
            try:
                cutoff = time.time() - 86400
                cursor = conn.execute(
                    """SELECT summary FROM episodic_memories
                       WHERE timestamp > ? AND importance > 0.4
                       ORDER BY timestamp DESC LIMIT 3""",
                    (cutoff,),
                )
                rows = cursor.fetchall()
            finally:
                conn.close()

            if not rows:
                return ""

            summaries = [r[0] for r in rows if r[0]]
            if not summaries:
                return ""

            lines = ["最近发生的事情："]
            for s in summaries:
                lines.append(f"· {s[:80]}")
            return "\n".join(lines)
        except Exception:
            return ""

    # ============================================================
    # 去重
    # ============================================================

    def _is_duplicate(self, text: str) -> bool:
        """检查是否与最近 N 条问候重复"""
        h = hashlib.md5(text.encode("utf-8")).hexdigest()
        recent_hashes = {h for _, h in self._recent_greetings}
        return h in recent_hashes

    def _store_greeting(self, text: str) -> str:
        """存储问候供前端轮询，返回 greeting_id"""
        import uuid
        greeting_id = uuid.uuid4().hex[:12]

        # 记录去重哈希
        h = hashlib.md5(text.encode("utf-8")).hexdigest()
        self._recent_greetings.append((time.time(), h))
        if len(self._recent_greetings) > self._max_recent:
            self._recent_greetings = self._recent_greetings[-self._max_recent:]

        # 设置待发送
        self._pending_greeting = text
        self._pending_greeting_id = greeting_id

        return greeting_id

    # ============================================================
    # 前端 API 接口
    # ============================================================

    def set_external_greeting(self, text: str) -> str | None:
        """供 AttentionScheduler 等外部系统设置待发送问候。

        与内部 tick 生成的问候共用同一条 pending 通道，
        前端通过 /api/autonomy/pending-greeting 轮询获取。
        """
        import uuid
        greeting_id = uuid.uuid4().hex
        self._pending_greeting = text
        self._pending_greeting_id = greeting_id
        logger.info("nudge.external_greeting", text=text[:60])
        return greeting_id

    def get_pending_greeting(self) -> dict:
        """获取待展示的问候（前端轮询）"""
        return {
            "has_greeting": self._pending_greeting is not None,
            "greeting": self._pending_greeting,
            "id": self._pending_greeting_id,
        }

    def ack_greeting(self, greeting_id: str) -> bool:
        """
        前端确认收到问候，清除 pending。

        Returns:
            True 如果成功确认，False 如果 ID 不匹配
        """
        if greeting_id == self._pending_greeting_id:
            self._pending_greeting = None
            self._pending_greeting_id = None
            logger.debug("nudge.greeting_acked", id=greeting_id)
            return True
        logger.warning("nudge.ack_id_mismatch", expected=self._pending_greeting_id, got=greeting_id)
        return False

    # ============================================================
    # 控制接口
    # ============================================================

    def pause(self) -> None:
        """暂停所有自主行为"""
        self._config.do_not_disturb = True
        logger.info("nudge.paused")

    def resume(self) -> None:
        """恢复自主行为"""
        self._config.do_not_disturb = False
        logger.info("nudge.resumed")

    def update_config(self, patch: dict) -> AutonomyConfig:
        """部分更新配置"""
        self._config.update(patch)
        logger.info("nudge.config_updated", patch=patch)
        return self._config

    @property
    def status(self) -> dict:
        """当前状态快照（供 API 返回）— 每次调用时实时计算想念值"""
        # 实时计算而非依赖 tick() 的缓存值，确保前端看到最新数据
        try:
            self._current_missing_value = self.calculate_missing_value()
        except Exception:
            pass  # 计算失败时保留旧值
        return {
            "greeting_enabled": self._config.greeting_enabled,
            "do_not_disturb": self._config.do_not_disturb,
            "missing_value": self._current_missing_value,
            "threshold": self._config.greeting_threshold,
            "bucket_tokens": round(self._bucket.available, 2),
            "bucket_capacity": self._bucket.capacity,
            "pending_greeting": self._pending_greeting is not None,
        }


# ═══════════════════════════════════════════════════════════
# AttentionScheduler — 后台注意力系统（阶段 7c）
# ═══════════════════════════════════════════════════════════

class AttentionUrgency:
    """注意力事件紧急度"""
    IMMEDIATE = 0   # 立刻处理
    SOON = 1        # 10 秒后处理
    LATER = 2       # 60 秒后处理，300s 蒸发


@dataclass
class AttentionEvent:
    """注意力事件"""
    kind: str               # 'task_reminder' | 'user_inactive' | 'memory_surfaced'
    urgency: int            # 0=immediate, 1=soon, 2=later
    payload: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)

    def __lt__(self, other):
        """优先级队列排序：urgency 小的优先处理"""
        return self.urgency < other.urgency


@dataclass
class AttentionScheduler:
    """
    昔涟的注意力调度器。

    以 5 秒为 tick 单位持续运行，检查 PriorityQueue 中的事件。
    取最高优先级事件 → Flash 决策 → 生成行动或静默。

    与 NudgeEngine 互补：
    - NudgeEngine: 15 分钟周期，想念值驱动，Pro 生成，情感问候
    - AttentionScheduler: 5 秒周期，事件驱动，Flash 决策，细粒度注意力
    """

    tick_interval: float = 5.0
    event_queue: asyncio.PriorityQueue = field(default_factory=asyncio.PriorityQueue)

    # 外部注入
    _router: object = None        # ModelRouter（Flash 决策）
    _db: object = None            # DatabaseManager
    _agent: object = None         # AgentCore 弱引用
    _nudge_engine: object = None  # NudgeEngine 引用（供 notify 桥接）

    _running: bool = False
    _last_event_time: dict[str, float] = field(default_factory=dict)

    # 防打扰
    dnd_start: int = 23
    dnd_end: int = 8
    min_interval: int = 300       # 同类型事件最短间隔（秒）
    later_evaporate: int = 300    # later 事件蒸发时间（秒）
    _user_typing: bool = False    # 盒子正在输入时不打断

    # ── 生命周期 ──

    async def start(self):
        """启动调度循环（asyncio Task）。"""
        self._running = True
        logger.info("attention_scheduler.started")
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                logger.error("attention_scheduler.tick_error", error=str(e))
            await asyncio.sleep(self.tick_interval)

    def stop(self):
        self._running = False

    # ── tick ──

    async def _tick(self):
        """
        一次 tick 周期。

        流程：
          1. 深夜检查 → 跳过（仅 later 事件存活）
          2. 用户正在输入 → 跳过
          3. 蒸发超时的 later 事件
          4. 从 PriorityQueue 取最高优先级事件
          5. 同类型去重（300s 内）
          6. Flash 决策 → NOTIFY / SILENT / NOTE
          7. 执行行动
        """
        from datetime import datetime
        now = time.time()
        hour = datetime.now().hour

        # 1. 深夜静默
        if self.dnd_start <= hour or hour < self.dnd_end:
            return

        # 2. 盒子正在输入 → 不打扰
        if self._user_typing:
            return

        # 3. 蒸发超时的 later 事件
        self._evaporate_later(now)

        if self.event_queue.empty():
            return

        # 4. 取最高优先级事件
        try:
            event = self.event_queue.get_nowait()
        except asyncio.QueueEmpty:
            return

        # 5. 同类型去重
        last = self._last_event_time.get(event.kind, 0)
        if now - last < self.min_interval:
            return
        self._last_event_time[event.kind] = now

        # 6. Flash 决策
        decision = await self._decide(event)

        # 7. 执行
        action = decision.get("action", "silent")
        if action == "notify":
            text = decision.get("text", "")
            if text and self._nudge_engine:
                self._nudge_engine.set_external_greeting(text)
            logger.info(
                "attention_scheduler.notify",
                kind=event.kind,
                text=text[:60],
                delivered=bool(text and self._nudge_engine),
            )
        elif action == "note":
            logger.info("attention_scheduler.note", text=decision.get("text", "")[:60])

    # ── 事件入队 ──

    def enqueue(self, event: AttentionEvent):
        """将事件推入优先队列。"""
        self.event_queue.put_nowait(event)

    # ── later 事件蒸发 ──

    def _evaporate_later(self, now: float):
        """移除超时的 later 事件。"""
        surviving = asyncio.PriorityQueue()
        while not self.event_queue.empty():
            try:
                e = self.event_queue.get_nowait()
                if e.urgency != AttentionUrgency.LATER or \
                   (now - e.created_at) < self.later_evaporate:
                    surviving.put_nowait(e)
            except asyncio.QueueEmpty:
                break
        self.event_queue = surviving

    # ── Flash 决策 ──

    async def _decide(self, event: AttentionEvent) -> dict:
        """
        用 Flash 快速决策这个事件要不要通知盒子。

        决策 prompt 非常轻量（~50 tokens），Flash 可在 ~1s 内完成。

        Returns:
            {"action": "notify"|"silent"|"note", "text": ...}
        """
        kind_desc = {
            "task_reminder": f"伙伴有一个提醒任务「{event.payload.get('title', '')}」到期了",
            "user_inactive": "伙伴已经好一会儿没说话了",
            "memory_surfaced": f"人家想起了「{event.payload.get('summary', '')}」",
        }
        desc = kind_desc.get(event.kind, "有些事情发生了")
        urgency_text = "比较急" if event.urgency == AttentionUrgency.IMMEDIATE else "不急"

        prompt = (
            f"你是昔涟。{desc}。"
            f"这件事{urgency_text}。"
            f"请快速决定要不要主动跟伙伴说句话。只返回以下格式之一：\n"
            f"如果需要说 → NOTIFY: <温柔简短的一句话（20字以内），以昔涟的语气>\n"
            f"如果不需要 → SILENT\n"
            f"如果记下来就好 → NOTE: <摘要>"
        )

        try:
            result = await self._router.route(
                "memory_encoding",  # Flash
                [{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=60,
            )
            result = result.strip()
            if result.startswith("NOTIFY:"):
                text = result[7:].strip()
                return {"action": "notify", "text": text if text else result}
            elif result.startswith("NOTE:"):
                return {"action": "note", "text": result[5:].strip()}
            return {"action": "silent"}
        except Exception as e:
            logger.warning("attention.decision_failed", error=str(e))
            return {"action": "silent"}

    # ── 用户输入状态 ──

    def set_user_typing(self, typing: bool):
        """标记用户是否正在输入（由 HTTP 通道 SSE 设置）。"""
        self._user_typing = typing

    # ── 状态查询 ──

    @property
    def queue_size(self) -> int:
        return self.event_queue.qsize()

    @property
    def status(self) -> dict:
        return {
            "running": self._running,
            "queue_size": self.queue_size,
            "dnd": self.dnd_start <= time.localtime().tm_hour or time.localtime().tm_hour < self.dnd_end,
            "user_typing": self._user_typing,
        }
