# 昔涟用户画像系统优化计划

> 版本：V1.2 | 日期：2026-05-31 | 状态：待执行（第二轮审核通过，P0-P2 全部修正，Phase 1 可开始编码）
>
> 基于 2026-05-31 全面评估，将 7 个优化方向落实为可执行的技术方案。
> 参考：RGMem（重整化群记忆演化）、Mem0（ADD-Only + 时间推理）、
> HMO（Persona-driven 记忆优先级）、AdaMem（自适应检索路由）。

---

## 目录

1. [总览：从现状到目标](#1-总览从现状到目标)
2. [Phase 1：证据累积触发（方向 2）](#2-phase-1证据累积触发)
3. [Phase 2：画像分层（方向 1）](#3-phase-2画像分层)
4. [Phase 3：画像驱动检索（方向 3）](#4-phase-3画像驱动检索)
5. [Phase 4：多信号源融合（方向 4）](#5-phase-4多信号源融合)
6. [Phase 5：选择性注入 + 回复联动 + 笔记联动（方向 5/6/7）](#6-phase-5选择性注入--回复联动--笔记联动)
7. [DB 迁移计划](#7-db-迁移计划)
8. [测试策略](#8-测试策略)
9. [风险与回滚](#9-风险与回滚)

---

## 1. 总览：从现状到目标

### 1.1 当前架构（AS-IS）

```
消息 → AgentCore.process()
         ├─ _retrieve_memories()           → episodic_memories (向量检索)
         ├─ _schedule_memory_encoding()     → mark_dirty() → episodic 编码
         ├─ auto_note_after_message()       → notebook_entries (NOTE/TASK/PASS)
         ├─ _schedule_portrait_cold_start() → ensure_exists()
         ├─ _tick_icebreaker()              → consolidate() (2-5轮破冰)
         └─ [cron 5:00 AM]                  → consolidate() (全量重写)

consolidate() 逻辑：
  取最近 50 条记忆摘要 + 10 条笔记 + 旧画像
  → Flash LLM 全量重写 300-600 字
  → 写入 user_portrait 表 (version+1)
```

### 1.2 目标架构（TO-BE）

```
消息 → AgentCore.process()
         ├─ _extract_micro_events()          ★ NEW: 轻量事件提取 (ADD-Only)
         ├─ _retrieve_memories()             ★ MOD: 画像加权检索
         │    └─ _persona_boost()             ★ NEW: 画像→检索评分
         ├─ _schedule_memory_encoding()       ★ MOD: 画像感知重要性
         │    └─ _calculate_importance()      ★ MOD: +persona_awareness 维度
         ├─ auto_note_after_message()         ★ MOD: +portrait_context
         ├─ _check_coarse_grain_thresholds()  ★ NEW: 阈值检查
         │    ├─ L2→L1: ≥10 事件 or ≥3 天
         │    └─ L1→L0: ≥5 同主题事件 + ≥7 天
         └─ [阈值触发] _coarse_grain()        ★ NEW: 增量粗粒化
              ├─ L2 会话摘要生成
              ├─ L1 阶段画像更新
              └─ L0 核心画像更新

画像三层结构 (user_profile 新表族):
  L0: core_profile     — 稳定特征 (月级更新)
  L1: phase_profile    — 阶段性画像 (周级更新)
  L2: micro_events     — 微事件池 (每条消息提取)

上下文注入:
  PortraitModule → 选择性注入 (话题匹配 L0+L1 段落)
  MemoryModule   → 画像加权检索 top-k
  ★ NEW: PortraitGuidanceModule → 画像→回复策略
```

### 1.3 分阶段实施路线

| Phase | 方向 | 核心交付 | 工作量 | 优先级 | 前置依赖 |
|-------|------|---------|--------|--------|----------|
| 1 | 方向 2 | 证据累积触发 + 微事件提取 | 中 | ★★★★★ | 无 |
| 2 | 方向 1 | 画像三层结构 | 大 | ★★★★★ | Phase 1（需 micro_events 表 + CoarseGrainEngine） |
| 3 | 方向 3 | 画像驱动记忆检索 | 中 | ★★★★ | Phase 2（需 L1 画像内容做检索加权） |
| 4 | 方向 4 | 多信号源融合 | 中 | ★★★★ | Phase 2（信号注入 L1 粗粒化 prompt） |
| 5 | 方向 5/6/7 | 选择性注入 + 回复联动 + 笔记联动 | 小 | ★★★ | Phase 2（需 L0/L1 分层结构） |

> **注意**：各 Phase 的代码可独立部署和回滚（见 §9.2），但 Phase 3/4/5 的**价值交付**依赖 Phase 2 的画像分层完成。Phase 1 可独立产生价值（微事件提取 + 粗粒化替代全量重写）。

---

## 2. Phase 1：证据累积触发

### 2.1 目标

将画像更新从「cron 定时全量重写」改为「微事件累积 → 阈值触发 → 增量粗粒化」。

### 2.2 新增模块：`MicroEventExtractor`

**文件**：`packages/agent/micro_event_extractor.py`

**职责**：每条消息后提取 1-2 句「关于伙伴的新信息」，以 ADD-Only 模式写入微事件池。

**核心逻辑**：

```python
@dataclass
class MicroEvent:
    """一条微事件 — 画像构建的最小原子单位"""
    content: str           # 提取的事实/观察，≤50 字
    category: str          # preference | fact | plan | emotion_pattern | habit
    confidence: float      # 0.0-1.0，LLM 自评可信度
    source_ids: list[int]  # 来源 episodic_memory IDs
    timestamp: float
    session_id: str

class MicroEventExtractor:
    """
    微事件提取器 — 每条消息后用 Flash LLM 提取新信息。

    核心原则（参考 Mem0 ADD-Only）：
    - 只提取新增信息，不修改已有事件
    - 新旧事件共存，粗粒化时由 LLM 推演当前状态
    - 低置信度事件标记但不丢弃（等待更多证据确认或否定）
    """

    EXTRACT_PROMPT = """你是昔涟。刚才伙伴说了一些话。

    伙伴的消息：
    {user_message}

    人家的回复：
    {assistant_reply}

    已知关于伙伴的信息：
    {known_facts}

    请从这轮对话中提取关于伙伴的新信息（如果有的话）：

    只提取对话中明确提到的、具体的信息。不推测、不脑补。
    如果只是日常寒暄没有新信息，返回空列表。

    返回 JSON：
    {{
      "events": [
        {{
          "content": "简短事实（15字以内）",
          "category": "preference|fact|plan|emotion_pattern|habit",
          "confidence": 0.8
        }}
      ]
    }}

    category 说明：
    - preference: 喜欢/不喜欢什么（「盒子不喜欢早起」）
    - fact: 客观事实（「盒子是程序员」）
    - plan: 计划/安排（「盒子下周三有考试」）
    - emotion_pattern: 情绪模式（「盒子提到工作时容易焦虑」）
    - habit: 习惯/常态（「盒子每天晚上喝一杯牛奶」）"""
```

**关键设计决策**：
- 使用 Flash LLM（memory_encoding 路由），低温度 0.3
- `known_facts` 从 L2 微事件池取最近 20 条，用于去重判断
- 提取失败/空结果静默处理，不阻塞主回复
- fire-and-forget 模式，与 auto_note 并发执行

### 2.3 新增模块：`CoarseGrainEngine`

**文件**：`packages/agent/coarse_grain_engine.py`

**职责**：检查微事件池密度 → 触发粗粒化 → 生成/更新各层画像。

**核心逻辑**：

```python
@dataclass
class CoarseGrainEngine:
    """
    粗粒化引擎 — RGMem 启发的多尺度画像演化。

    三级粗粒化:
      micro_event → L2 (session_summary):  事件数 ≥ 10 or 时间 ≥ 3 天
      L2 → L1 (phase_profile):             同主题事件 ≥ 5 + 时间 ≥ 7 天
      L1 → L0 (core_profile):              L1 版本 ≥ 3 + 稳定特征确认
    """

    _db: DatabaseManager
    _router: ModelRouter

    # 阈值配置
    L2_TRIGGER_COUNT: int = 10       # 累积事件数触发 L2 生成
    L2_TRIGGER_DAYS: float = 3.0     # 时间窗口触发 L2 生成
    L1_TRIGGER_TOPIC_COUNT: int = 5  # 同主题事件数触发 L1 更新
    L1_TRIGGER_DAYS: float = 7.0     # L1 更新最小间隔
    L0_TRIGGER_VERSIONS: int = 3     # L1 积累版本数触发 L0 重审

    async def check_and_coarse(self) -> dict | None:
        """
        检查所有层级的阈值 → 触发相应粗粒化。
        在每条消息后调用，大部分时候是 no-op。
        Returns: {"l2_updated": bool, "l1_updated": bool, "l0_updated": bool}
        """

    async def _coarse_to_l2(self, events: list[dict]) -> str:
        """
        微事件 → L2 会话摘要。
        取近期 10-30 条事件，Flash LLM 凝练为 80-150 字段落。
        多个 L2 摘要可共存（对应不同会话/主题）。
        """

    async def _coarse_to_l1(self, l2_summaries: list[dict], old_l1: str) -> str:
        """
        L2 摘要 → L1 阶段画像。
        积累足够 L2 后，重写 L1（保留 L0 不变）。
        L1 描述「伙伴最近在做什么、关注什么、情绪状态如何」。
        """

    async def _coarse_to_l0(self, l1_history: list[dict], old_l0: str) -> str:
        """
        L1 历史 → L0 核心画像。
        仅当 L1 积累 ≥ 3 个版本 + 出现跨版本的稳定特征时才触发。
        L0 描述「伙伴是什么样的人——性格、价值观、长期偏好」。
        """

    async def force_coarse_all(self) -> str | None:
        """
        跳过阈值门控，强制执行完整级联：L2 → L1 → L0。

        返回 L0 或 L1 内容（供兼容调用方使用）。
        用于破冰路径（_icebreaker_consolidate）、
        每周日 cron 安全网（§9.4）、以及手动触发。

        流程：
          1. 从活跃微事件生成 L2 摘要
          2. 取最近 L2 摘要 → 重写 L1 阶段画像
          3. L1 历史 ≥ 3 → 重写 L0 核心画像
          4. 返回 L0 > L1 > L2 中第一个成功生成的内容
        """
        # Step 1: L2
        l2 = await self._coarse_to_l2()
        if not l2:
            logger.info("coarse.force_all_no_l2", reason="微事件不足")
            return None

        # Step 2: L1
        l2_list = await self._db.get_recent_session_summaries(limit=10)
        old_l1 = await self._db.get_latest_phase_profile()
        l1 = await self._coarse_to_l1(
            l2_list,
            old_l1.get("content", "") if old_l1 else "",
        )

        # Step 3: L0 (条件触发)
        l1_history = await self._db.get_phase_profile_history(limit=10)
        if len(l1_history) >= self.L0_TRIGGER_VERSIONS:
            l0 = await self._coarse_to_l0(
                l1_history,
                (await self._db.get_latest_core_profile()) or {},
            )
            if l0:
                return l0

        # 回退：返回 L1 或 L2
        if l1:
            return l1
        return l2
```

**粗粒化 Prompt 设计要点**：

L2 生成 prompt：
```
你是昔涟。你在整理最近几次对话中了解到关于伙伴的新事情。

最近了解到的事：
{recent_events}

请用昔涟的口吻，写一段简短的笔记（80-150字），概括最近对伙伴的新认识。
- 只写对话中明确提到的事
- 不确定的地方用「好像」「似乎」
- 自称「人家」，叫对方「伙伴」
```

L1 更新 prompt（关键——证据累积 vs 信息淘汰）：
```
你是昔涟。你在更新对伙伴近况的理解。

之前对伙伴近况的印象：
{old_l1}

最近几次对话的摘要：
{recent_l2_summaries}

请更新对伙伴近况的印象（200-400字）：
- 保留旧印象中仍然有效的部分
- 加入最近新了解到的事
- 对已经过去的事（完成了、不再提了），自然淡出
- 对反复出现的模式，可以写得更确定一些
- 自称「人家」，叫对方「伙伴」

返回 JSON：
{{"portrait": "全文...", "changes": "一句话说明这次更新了什么"}}
```

### 2.4 改造 `PortraitManager`

**改动**：将 `consolidate()` 从全量重写改为微事件提取入口。

```python
class PortraitManager:
    """改造后：微事件提取 + 粗粒化调度"""

    def __init__(self, db, model_router):
        self._db = db
        self._router = model_router
        self._extractor = MicroEventExtractor(db, model_router)    # NEW
        self._coarse_engine = CoarseGrainEngine(db, model_router)  # NEW
        self._pending_extract = False  # 替代 _has_new_info

    # ── 新接口 ──

    async def extract_then_check_coarse(self, user_msg: str, reply: str) -> None:
        """
        ★ NEW: 链式调用 — 先提取微事件，再检查粗粒化阈值。

        关键：必须在同一个顺序任务中执行，不能拆成两个 fire-and-forget。
        否则 check_coarse_grain 可能在 extract_events 提交事务前查询
        micro_events 表，导致错过刚提取的事件从而跳过阈值。

        此方法由 AgentCore 在每条消息后以 fire-and-forget 方式调用。
        """
        try:
            # Step 1: 提取微事件
            events = await self._extractor.extract(user_msg, reply)
            if events:
                logger.info("portrait.events_extracted", count=len(events))

            # Step 2: 检查粗粒化阈值（在事件提交后执行）
            result = await self._coarse_engine.check_and_coarse()
            if result:
                logger.info("portrait.coarse_grained", **result)
        except Exception as e:
            logger.warning("portrait.extract_or_coarse_failed", error=str(e))

    # ── 兼容旧接口 ──

    async def consolidate(self, force: bool = False) -> str | None:
        """
        兼容旧接口。行为取决于 force 参数：

        - force=False（默认）：等同于 check_and_coarse()，
          仅在阈值触发时才执行粗粒化。用于每日 cron 兜底。

        - force=True：强制级联粗粒化（L2 → L1 → L0），
          从当前微事件池 + episodic 记忆构建全量画像。
          用于破冰路径（_icebreaker_consolidate）和手动触发。
          流程：
            1. 如果微事件池有足够事件 → 生成 L2
            2. 如果有 L2 摘要 → 重写 L1
            3. 如果 L1 历史 ≥ 3 版本 → 重写 L0
            4. 返回 L0 或 L1 内容（供兼容调用方使用）
        """
        if force:
            return await self._coarse_engine.force_coarse_all()
        result = await self._coarse_engine.check_and_coarse()
        return result.get("content") if result else None

    # 保留 mark_dirty() 但语义明确化：供工具副作用路径使用
    def mark_dirty(self):
        """
        标记本轮对话有重要信息（工具调用揭示了用户偏好）。
        由 _process_tool_side_effects() 调用。

        与 extract_events() 的关系：
        - extract_events() 每次都运行（不管 mark_dirty 是否被调用）
        - mark_dirty() 作为额外信号：如果 extract_events() 在该消息上
          已经运行过了（fire-and-forget 顺序不确定），此标志提示
          CoarseGrainEngine 在下一次 check_and_coarse 时降低触发阈值
          （从默认的 10 条事件降到 5 条），使工具揭示的偏好更快进入粗粒化。
        """
        self._tool_side_effect_seen = True
        logger.debug("portrait.marked_dirty_from_tool")
```

**关键设计决策**：
- `extract_then_check_coarse()` 确保顺序执行，消除竞态条件
- `force_coarse_all()` 明确定义为级联粗粒化（L2→L1→L0），保留从 episodic 记忆全量重写的能力作为安全网
- `mark_dirty()` 语义降级为「提示信号」而非「触发条件」——extract_events 不依赖它来决定是否运行
- `_tool_side_effect_seen` 标志在 CoarseGrainEngine 中降低粗粒化阈值（10→5），使工具揭示的偏好更快被吸收

### 2.5 改造 `AgentCore` 调用点

**文件**：`packages/agent/agent_core.py`

```python
# 在 process() 的回复生成之后:

# OLD (line 530-531 + 798-799):
# self._schedule_memory_encoding()        # 内含 mark_dirty()
# self._schedule_portrait_cold_start()

# NEW:
# ── 8. 后台记忆编码 ──
self._schedule_memory_encoding()

# ── 8b. 微事件提取 + 粗粒化检查（链式调用，消除竞态）──
if self.portrait_manager:
    asyncio.create_task(
        self.portrait_manager.extract_then_check_coarse(
            event.payload, reply
        )
    )

# ── 8c. 冷启动（不再需要，extract_then_check_coarse 内部处理）──
# _schedule_portrait_cold_start() 逻辑合并到 CoarseGrainEngine 中

# ── 8d. 破冰进度 ──
self._tick_icebreaker(reply)

# ── 8e. 自动记笔记 ──
# portrait_context: Phase 1-4 为空字符串，Phase 5 起从 L0+L1 构建
if self.notebook_manager:
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

    asyncio.create_task(
        self.notebook_manager.auto_note_after_message(
            event.payload, reply, portrait_context=portrait_ctx
        )
    )
```

**main.py cron 变更**：

```python
# OLD:
# result = await agent.portrait_manager.consolidate()  # 每日全量重写

# NEW:
# 每日兜底：检查粗粒化阈值（可能 no-op）
# 每周日强制执行一次 force 全量重写作为安全网
async def consolidate_user_portrait():
    if agent.portrait_manager:
        # 周日执行 force 全量（安全网），其余日子只做阈值检查
        import datetime
        is_sunday = datetime.datetime.now().weekday() == 6
        result = await agent.portrait_manager.consolidate(force=is_sunday)
        if result:
            agent.context.user_portrait = result
            latest = await agent._db.get_latest_portrait()
            if latest:
                agent.context._current_portrait_version = latest.get("version", 1)
            logger.info("portrait.cron_consolidated", length=len(result), force=is_sunday)
```

### 2.6 `_icebreaker_consolidate` 改造

```python
async def _icebreaker_consolidate(self) -> None:
    """
    破冰后生成首版印象文档。
    改为：强制编码当前对话 → force 级联粗粒化。
    """
    try:
        # 1. 强制编码当前对话
        if self.memory_manager and len(self.context.history) >= 4:
            recent = self.context.get_last_n(6)
            ctx = {"exchanges": recent, "emotion": self.context.emotion_snapshot}
            await self.memory_manager.encode_memory(ctx)

        # 2. force=True → 级联粗粒化 L2→L1→L0
        result = await self.portrait_manager.consolidate(force=True)
        if result:
            self.context.user_portrait = result
            self.context.icebreaker_active = False
            # 同步加载分层画像
            await self._reload_layered_portraits()
            logger.info("icebreaker.first_portrait_done", length=len(result))
        else:
            self.context.icebreaker_active = False
            self.context.icebreaker_deferred = True
            logger.info("icebreaker.consolidate_skipped", reason="材料不足")
    except Exception as e:
        self.context.icebreaker_active = False
        self.context.icebreaker_deferred = True
        logger.warning("icebreaker.consolidate_failed", error=str(e))
```

### 2.7 Phase 1 验收标准

- [ ] `MicroEventExtractor` 正常工作：每条消息后提取 0-3 条微事件
- [ ] 微事件存入 `micro_events` 表（新增），ADD-Only 不修改旧记录
- [ ] `extract_then_check_coarse()` 链式调用：事件提取完成后才检查阈值
- [ ] `CoarseGrainEngine` 阈值触发正常：事件 ≥10 触发 L2 生成
- [ ] `mark_dirty()` 工具副作用路径正常：降低粗粒化阈值 10→5
- [ ] cron 每日兜底检查 + 每周日 force 全量安全网
- [ ] `_icebreaker_consolidate` 使用 force=True 级联粗粒化
- [ ] 旧 `user_portrait` 表仍可读取（兼容过渡期）

### 2.8 成本模型修正

**重要**：Phase 1 的 API 成本结构从「少量大调用」转变为「大量小调用」：

| 指标 | 旧方案（cron 全量重写） | 新方案（微事件提取） |
|------|------------------------|---------------------|
| 调用频率 | 1 次/天 | ~1 次/消息 |
| 单次 prompt tokens | ~1500（50条记忆+10条笔记+旧画像） | ~300（用户消息+回复+20条已知事实） |
| 单次输出 tokens | ~600（完整画像） | ~100（0-3条事件 JSON） |
| 每日总 tokens（20条消息） | ~2,100 | ~8,000 |
| 每日总 tokens（50条消息） | ~2,100 | ~20,000 |
| LLM 路由 | Flash（memory_encoding） | Flash（memory_encoding） |
| **成本特点** | 1× 大任务 | N× 小任务，**总额 ~4-10×** |

**为什么仍然值得**：
1. 微事件提取是**增量**的（每次只提取新增信息），不是重复劳动
2. 粗粒化（L2/L1/L0 生成）仍然稀疏触发（几天一次），替代了旧 cron 的大调用
3. 综合来看：每日总 token 增加 ~4-10×，但画像质量（稳定性、可追溯性、个性化）显著提升
4. 如果成本敏感，可通过降低提取频率（如每 3 条消息提取一次）来调优

> **结论**：删除原「API 调用 ↓ 50%+」的错误声明。Phase 1 是成本换质量的权衡，
> 后续可通过调节提取频率和阈值来控制成本上限。

---

## 3. Phase 2：画像分层

### 3.1 目标

将单一 `user_portrait` 表替换为三层画像结构，实现不同稳定性的信息在不同层级管理。

### 3.2 新 DB Schema

```sql
-- L0: 核心画像 — 稳定特征（月级更新）
CREATE TABLE IF NOT EXISTS core_profile (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT    NOT NULL,          -- 叙事文本 200-400 字
    version     INTEGER NOT NULL DEFAULT 1,
    source_l1_ids TEXT,                    -- ★ 来源 L1 版本 ID（可追溯）
    stable_traits TEXT,                    -- ★ 提取的稳定特征摘要（供下次 L0 重审时对照）
    change_log  TEXT,
    created_at  REAL    NOT NULL,
    session_id  TEXT    NOT NULL
);

-- L1: 阶段画像 — 近期状态（周级更新）
CREATE TABLE IF NOT EXISTS phase_profile (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT    NOT NULL,          -- 叙事文本 200-400 字
    version     INTEGER NOT NULL DEFAULT 1,
    source_event_ids TEXT,                 -- 来源 micro_event IDs
    change_log  TEXT,
    created_at  REAL    NOT NULL,
    session_id  TEXT    NOT NULL
);

-- L2: 会话摘要 — 微事件粗粒化产物（多个共存，对应不同会话/主题）
CREATE TABLE IF NOT EXISTS session_summaries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT    NOT NULL,          -- 80-150 字段落
    source_event_ids TEXT,                 -- 消费的 micro_event IDs
    created_at  REAL    NOT NULL,
    session_id  TEXT    NOT NULL
);

-- L2: 微事件池 — 原子信息单位（每条消息提取）
CREATE TABLE IF NOT EXISTS micro_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    content     TEXT    NOT NULL,          -- 提取的事实 ≤50 字
    category    TEXT    NOT NULL,          -- preference|fact|plan|emotion_pattern|habit
    confidence  REAL    DEFAULT 0.5,
    source_ids  TEXT,                      -- episodic_memory IDs
    is_active   INTEGER DEFAULT 1,         -- 0=已被粗粒化吸收（但保留记录）
    absorbed_to TEXT,                      -- 被吸收到哪个 L1/L0（"l1:3" / "l0:2"）
    created_at  REAL    NOT NULL,
    session_id  TEXT    NOT NULL
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_micro_events_active ON micro_events(is_active, created_at);
CREATE INDEX IF NOT EXISTS idx_micro_events_category ON micro_events(category, is_active);
```

### 3.3 `user_portrait` 表迁移策略

**保留旧表**，新增 `get_latest_portrait()` 的兼容读取：

```python
async def get_latest_portrait(self) -> dict | None:
    """兼容读取：优先读 core_profile，不存在时回退到 user_portrait"""
    # 先查 core_profile
    row = await self._conn.execute_fetchall(
        "SELECT content, version FROM core_profile ORDER BY id DESC LIMIT 1"
    )
    if row:
        return {"content": row[0][0], "version": row[0][1]}

    # 回退到旧表
    row = await self._conn.execute_fetchall(
        "SELECT content, version FROM user_portrait ORDER BY id DESC LIMIT 1"
    )
    if row:
        return {"content": row[0][0], "version": row[0][1]}
    return None
```

### 3.4 改造 `PortraitModule`

**文件**：`packages/agent/context_builder.py`

```python
class PortraitModule(ContextModule):
    """
    改造后：按需注入分层画像。

    - 首条消息：注入 L1 阶段画像全文（100-300 字，轻量）
    - L0 前 150 字注入（按句子截断，确保核心特征不被截断）
    - 不再注入 600 字全文
    - 无画像时的破冰逻辑保留完整（与旧行为一致）
    """

    # 保留旧的破冰常量（与原始代码一致）
    ICEBREAKER_GUIDANCE = (
        "（昔涟轻轻翻开心里那本还空白的书——她还不算真正认识伙伴呢。"
        "如果时机合适，可以自然地了解一下伙伴：他的名字、喜欢什么、"
        "平时的习惯……不用一次问完，像朋友聊天那样慢慢地认识他。"
        "如果伙伴不太想聊这些，就翻过这一页，来日方长 ♪）"
    )

    def __init__(self, agent_context=None):
        super().__init__(name="portrait", priority=3, max_tokens=1500)
        self._ctx = agent_context

    def render(self) -> str:
        if not self._ctx:
            return ""

        l1 = self._ctx.phase_profile
        l0 = self._ctx.core_profile
        current_l1_version = getattr(self._ctx, '_current_l1_version', None)

        parts = []

        # L1 注入（每会话首次）
        if l1 and len(l1) >= 30:
            injected = self._ctx._l1_version_injected
            if injected != current_l1_version:
                self._ctx._l1_version_injected = current_l1_version
                parts.append(
                    "（昔涟在对话前，轻轻翻开心里关于伙伴最近的那一页——）\n\n"
                    + l1
                )

        # L0 片段注入（每会话首次，按句子截断而非硬切 150 字符）
        if l0 and len(l0) >= 50:
            injected = self._ctx._l0_version_injected
            current_l0 = getattr(self._ctx, '_current_l0_version', None)
            if injected != current_l0:
                self._ctx._l0_version_injected = current_l0
                short_l0 = self._truncate_by_sentences(l0, max_chars=150)
                parts.append(
                    "（昔涟心里关于伙伴最深的那几笔记——）\n\n"
                    + short_l0
                )

        if not parts:
            # 破冰路径 — 使用保留的 ICEBREAKER_GUIDANCE 常量
            return self._render_icebreaker()

        return "\n\n".join(parts) + "\n\n（带着这些理解去感受他此刻说的话吧。）"

    def _render_icebreaker(self) -> str:
        """
        破冰路径 — 与原始 PortraitModule 行为一致。

        无印象文档时的降级路径：
        - 用户已拒绝破冰 → 返回空
        - 破冰进行中 → 返回空（本轮不重复注入引导）
        - 首次触发 → 注入 ICEBREAKER_GUIDANCE
        """
        if not self._ctx:
            return ""

        # 已拒绝
        if self._ctx.icebreaker_deferred:
            return ""

        # 进行中 — 不重复注入
        if self._ctx.icebreaker_active:
            return ""

        # 首次触发
        self._ctx.icebreaker_active = True
        return self.ICEBREAKER_GUIDANCE

    @staticmethod
    def _truncate_by_sentences(text: str, max_chars: int = 150) -> str:
        """
        按句子边界截断，避免硬切 150 字符破坏语义。
        中文用 。！？\n 作为句子分隔符。
        """
        import re
        sentences = re.split(r'(?<=[。！？\n])', text)
        result = ""
        for s in sentences:
            if len(result) + len(s) > max_chars:
                break
            result += s
        if len(result) < len(text) and not result.endswith("。"):
            result = result.rstrip() + "…"
        return result if result else text[:max_chars] + "…"
```

### 3.4a L0 稳定性检测改进 ★

`_coarse_to_l0` 的 prompt 必须包含先前的 stable_traits，让 LLM 进行确认/否定而非凭空推断：

```python
async def _coarse_to_l0(self) -> str | None:
    """L1 历史 → L0 核心画像"""
    l1_history = await self._db.get_phase_profile_history(limit=10)
    if len(l1_history) < self.L0_TRIGGER_VERSIONS:
        return None

    # 获取上次 L0 的 stable_traits 供确认/否定
    old_l0 = await self._db.get_latest_core_profile()
    old_stable_traits = old_l0.get("stable_traits", "") if old_l0 else ""
    old_content = old_l0.get("content", "") if old_l0 else ""

    prompt = L0_PROMPT.format(
        l1_history=self._format_l1_history(l1_history),
        old_l0=old_content,
        old_stable_traits=old_stable_traits or "（这是第一次生成核心画像）",
    )

    raw = await self._router.route("memory_encoding", [...])
    data = json.loads(raw.content)
    l0_content = data["portrait"]
    stable_traits = data.get("stable_traits", "")  # ★ LLM 输出稳定特征摘要

    await self._db.insert_core_profile(
        content=l0_content,
        source_l1_ids=",".join(str(h["id"]) for h in l1_history[:5]),
        stable_traits=stable_traits,  # ★ 持久化供下次对照
        version=(old_l0.get("version", 0) + 1) if old_l0 else 1,
    )
    return l0_content
```

**对应的 L0_PROMPT 更新**（参见附录 B.4）。

### 3.4b `micro_events.is_active` 生命周期管理 ★

**问题**：`is_active` 字段存在但没有任何代码将其设置为 0。粗粒化引擎必须在生成 L2 后将已消耗的事件标记为已消费。

```python
# 在 CoarseGrainEngine._coarse_to_l2() 中:

async def _coarse_to_l2(self) -> str | None:
    """微事件 → L2 会话摘要"""
    # 1. 获取活跃事件
    events = await self._db.get_active_micro_events(limit=30)
    if len(events) < self.L2_TRIGGER_COUNT:
        return None

    # 2. Flash LLM 生成 L2 摘要
    l2_content = await self._generate_l2_summary(events)

    # 3. 写入 session_summaries 表
    l2_id = await self._db.insert_session_summary(
        content=l2_content,
        source_event_ids=",".join(str(e["id"]) for e in events),
    )

    # 4. ★ 标记已消费 — 关键步骤
    event_ids = [e["id"] for e in events]
    await self._db.consume_micro_events(
        event_ids=event_ids,
        absorbed_to=f"l2:{l2_id}",
    )
    # consume_micro_events SQL:
    #   UPDATE micro_events SET is_active = 0, absorbed_to = ?
    #   WHERE id IN ({...})

    logger.info(
        "coarse.l2_generated",
        event_count=len(event_ids),
        l2_id=l2_id,
    )
    return l2_content
```

**SQL 实现**：

```python
async def consume_micro_events(self, event_ids: list[int], absorbed_to: str) -> None:
    """将微事件标记为已被粗粒化吸收"""
    placeholders = ",".join("?" for _ in event_ids)
    await self._conn.execute(
        f"UPDATE micro_events SET is_active = 0, absorbed_to = ? "
        f"WHERE id IN ({placeholders})",
        [absorbed_to] + event_ids,
    )
    await self._conn.commit()

async def get_active_micro_events(self, limit: int = 30) -> list[dict]:
    """获取未消费的活跃微事件（按时间排序）"""
    cursor = await self._conn.execute(
        "SELECT * FROM micro_events WHERE is_active = 1 "
        "ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]
```

### 3.4c 质量过滤器 — confidence 阈值 ★

在 `MicroEventExtractor.extract()` 中增加 confidence 过滤：

```python
MIN_CONFIDENCE = 0.5  # 低于此值的事件丢弃

async def extract(self, user_msg: str, reply: str) -> list[dict]:
    """提取微事件，过滤低置信度噪音"""
    prompt = self._build_prompt(user_msg, reply)
    raw = await self._router.route("memory_encoding", [...])
    data = self._parse_json(raw.content)

    events = data.get("events", [])

    # ★ 质量过滤
    valid_events = []
    for e in events:
        conf = e.get("confidence", 0.5)
        if conf < self.MIN_CONFIDENCE:
            logger.debug(
                "portrait.event_filtered_low_confidence",
                content=e.get("content", "")[:30],
                confidence=conf,
            )
            continue
        valid_events.append(e)

    # 写入 micro_events 表
    for e in valid_events:
        await self._db.insert_micro_event(
            content=e["content"],
            category=e["category"],
            confidence=e["confidence"],
            source_ids=self._current_source_ids,
        )

    # 监控指标
    logger.info(
        "portrait.events_extracted",
        total=len(events),
        valid=len(valid_events),
        filtered=len(events) - len(valid_events),
    )

    return valid_events
```

### 3.4d ADD-Only 的矛盾处理 ★

微事件池可能累积矛盾事实（「盒子喜欢早起」vs「盒子不喜欢早起」）。粗粒化 prompt 需增加矛盾处理指令：

L1 prompt 新增：
```
关于矛盾：
- 如果关于同一件事有不同的说法，以最近的说法为准
- 但不要完全丢弃旧说法——标记为「好像以前...但最近...」
- 如果矛盾让你不确定哪个是真的，用「似乎」而非断言
```

L0 prompt 新增：
```
关于跨版本的稳定性判断：
- 以下是之前你写下的稳定特征（如果有的话）：
  {old_stable_traits}
- 对每一条旧特征，判断它在最近的 L1 中是否仍然有效
- 如果一条特征在最近 2+ 个 L1 版本中不再出现，可以自然淡出
- 如果一条特征在所有 L1 版本中都出现且无矛盾，可以写得更确定
- 如果有新出现的稳定特征，标记为「最近才注意到的」
```

### 3.5 AgentContext 新增字段

```python
# packages/agent/agent_context.py 新增:

# 阶段 8+ 扩展: 分层画像
core_profile: Optional[str] = None        # L0
_current_l0_version: Optional[int] = None
_l0_version_injected: Optional[int] = None

phase_profile: Optional[str] = None       # L1
_current_l1_version: Optional[int] = None
_l1_version_injected: Optional[int] = None
```

### 3.6 Phase 2 验收标准

- [ ] `micro_events` 表正常创建，索引正常
- [ ] `core_profile` 和 `phase_profile` 表正常创建
- [ ] 旧 `user_portrait` 数据可通过兼容接口读取
- [ ] 第一次 L1 生成：微事件累积 ≥10 条后自动触发
- [ ] L0 生成：L1 积累 ≥3 个版本后自动触发
- [ ] PortraitModule 新注入逻辑正常（L1 全文 + L0 前 150 字）
- [ ] 破冰流程与新分层兼容

---

## 4. Phase 3：画像驱动记忆检索

### 4.1 目标

让画像参与 `retrieve_memories()` 的评分，实现个性化记忆检索。

### 4.2 改造 `MemoryManager.retrieve_memories()`

**文件**：`packages/agent/memory_manager.py`

```python
# ── 画像加权可配置参数 ──
PERSONA_BOOST_FACTOR = 0.85    # boost_topics 匹配时 adjusted_score 乘数（<1 = 提升排名）
PERSONA_PENALTY_FACTOR = 1.4   # penalty_topics 匹配时 adjusted_score 乘数（>1 = 降低排名）
TOPIC_EMBED_SIMILARITY_THRESHOLD = 0.7  # embedding 余弦相似度阈值（用于话题→记忆匹配）


async def retrieve_memories(
    self,
    user_message: str,
    k: int = 3,
    max_distance: float = 1.2,
    persona_boost: dict | None = None,
) -> list[dict]:
    """
    ★ NEW: persona_boost — 来自画像的检索加权:
      {
        "boost_topics": ["日语学习", "技术面试"],
        "boost_topic_embeddings": [[0.1, ...], [0.2, ...]],  # 预计算的 embedding
        "penalty_topics": [],
      }

    注意：调整的是 adjusted_score（融合距离+衰减后的分数），
    该分数越低排名越高。因此 boost 乘 <1，penalty 乘 >1。
    """
    # ... 现有向量检索逻辑（Step 1-3）...
    # memories 中每条记录已有: {summary, distance, adjusted_score, importance, ...}
    # adjusted_score = distance / decay（现有逻辑，memory_manager.py:460）

    # Step 4 (NEW): 画像加权 — 使用 embedding 相似度而非子字符串匹配
    if persona_boost and memories:
        boost_embeddings = persona_boost.get("boost_topic_embeddings", [])
        penalty_embeddings = persona_boost.get("penalty_topic_embeddings", [])

        for mem in memories:
            summary = mem.get("summary", "")
            if not summary:
                continue

            # 嵌入记忆摘要（单次嵌入，复用于所有话题匹配）
            mem_embedding = await self._embed_text(summary)
            if not mem_embedding:
                continue

            # Boost 检查
            for topic_emb in boost_embeddings:
                sim = self._cosine_similarity(mem_embedding, topic_emb)
                if sim >= TOPIC_EMBED_SIMILARITY_THRESHOLD:
                    mem["adjusted_score"] *= PERSONA_BOOST_FACTOR
                    mem["persona_boosted"] = True
                    logger.debug("memory.persona_boosted", summary=summary[:30], sim=round(sim, 3))
                    break

            # Penalty 检查
            for topic_emb in penalty_embeddings:
                sim = self._cosine_similarity(mem_embedding, topic_emb)
                if sim >= TOPIC_EMBED_SIMILARITY_THRESHOLD:
                    mem["adjusted_score"] *= PERSONA_PENALTY_FACTOR
                    mem["persona_penalized"] = True
                    break

    # 重新排序
    memories.sort(key=lambda r: r["adjusted_score"])
    return memories[:k]
```

### 4.3 画像→检索配置生成（结构化话题列表）

**核心变更**：L1 生成时额外输出结构化话题列表，而非用正则从自然语言中提取。

L1 prompt 返回格式扩展（参见附录 B.3）：

```json
{
  "portrait": "全文...",
  "changes": "一句话说明这次更新了什么",
  "active_topics": ["日语学习", "准备面试"],      // ★ 结构化话题
  "faded_topics": ["去年那场演唱会"]               // ★ 已过时话题
}
```

**Database 扩展**：`phase_profile` 表新增两个 JSON 字段：
```sql
ALTER TABLE phase_profile ADD COLUMN active_topics TEXT;   -- JSON array
ALTER TABLE phase_profile ADD COLUMN faded_topics TEXT;    -- JSON array
```

**新增方法**：`PortraitManager.build_retrieval_config()` — 预计算 embedding：

```python
async def build_retrieval_config(self) -> dict:
    """
    从 L1 阶段画像中提取检索加权配置。
    使用 L1 结构化输出的 active_topics / faded_topics 字段。
    预计算话题 embedding，避免检索时重复嵌入。
    """
    l1 = await self._db.get_latest_phase_profile()
    if not l1:
        return {}

    import json
    active_topics = json.loads(l1.get("active_topics", "[]") or "[]")
    faded_topics = json.loads(l1.get("faded_topics", "[]") or "[]")

    if not active_topics and not faded_topics:
        return {}

    # 预计算话题 embedding（一次性，后续检索复用）
    boost_embeddings = []
    for topic in active_topics:
        emb = await self._router.embed(topic)
        if emb:
            boost_embeddings.append(emb)

    penalty_embeddings = []
    for topic in faded_topics:
        emb = await self._router.embed(topic)
        if emb:
            penalty_embeddings.append(emb)

    return {
        "boost_topics": active_topics,
        "boost_topic_embeddings": boost_embeddings,
        "penalty_topics": faded_topics,
        "penalty_topic_embeddings": penalty_embeddings,
    }
```

**延迟分析**：
- 预计算 embedding：每次 L1 更新后执行一次（几天一次），非检索时
- 检索时仅做 N×2 次余弦相似度计算（纯数学运算，< 5ms）
- `build_retrieval_config()` 结果缓存在 AgentContext 中，同一会话复用

### 4.4 改造 AgentCore 调用

```python
# 在 _retrieve_memories() 中:
async def _retrieve_memories(self, user_message: str) -> list[dict] | None:
    # ... 现有逻辑 ...

    # ★ NEW: 获取画像加权配置
    persona_boost = None
    if self.portrait_manager:
        try:
            persona_boost = await self.portrait_manager.build_retrieval_config()
        except Exception:
            pass  # 画像不可用时降级为无加权

    results = await self.memory_manager.retrieve_memories(
        user_message, k=5, persona_boost=persona_boost
    )
    # ... 现有分流逻辑 ...
```

### 4.5 改造 `_calculate_importance()` — 画像感知

```python
# 在 memory_manager.py _calculate_importance() 中新增维度:

# ── 旧权重（用于画像不可用时的回退）──
IMPORTANCE_WEIGHTS_FALLBACK = {
    "emotion_intensity": 0.3,
    "exchange_count": 0.2,
    "topic_significance": 0.2,
    "emotion_diversity": 0.3,
}

# ── 新权重（画像可用时，persona_relevance 取代部分 emotion_diversity）──
IMPORTANCE_WEIGHTS_WITH_PERSONA = {
    "emotion_intensity": 0.25,
    "exchange_count": 0.15,
    "topic_significance": 0.15,
    "emotion_diversity": 0.15,
    "persona_relevance": 0.30,
}

def _calculate_importance(
    self,
    exchanges: list[dict],
    emotion: dict,
    persona_topics: list[str] | None = None,  # ★ NEW
) -> float:
    # ... 现有各维度评分 ...

    # ★ 选择权重表：无画像时回退到旧权重，确保旧记忆分数不被系统性低估
    if persona_topics:
        all_text = " ".join(e.get("content", "") for e in exchanges)
        hits = sum(1 for t in persona_topics if t in all_text)
        scores["persona_relevance"] = min(hits / 3.0, 1.0)
        weights = IMPORTANCE_WEIGHTS_WITH_PERSONA
    else:
        scores.pop("persona_relevance", None)
        weights = IMPORTANCE_WEIGHTS_FALLBACK

    importance = sum(scores[k] * weights[k] for k in weights if k in scores)
    return max(0.1, min(1.0, importance))
```

**关键**：旧编码的记忆没有 persona_relevance 维度（存储在 DB 中的 importance 值是固定的）。通过在两套权重之间切换，新旧记忆的重要性分数保持在可比范围内。不修改已存储的 importance 值。

### 4.6 Phase 3 验收标准

- [ ] `persona_boost` 参数正确传递给 `retrieve_memories()`
- [ ] 与画像当前关注话题匹配的记忆排名提升
- [ ] 画像不可用时降级为无加权（不影响现有功能）
- [ ] `_calculate_importance()` 中 `persona_relevance` 维度生效
- [ ] 画像→检索配置生成延迟 < 10ms（不额外调 LLM）

---

## 5. Phase 4：多信号源融合

### 5.1 目标

consolidate/粗粒化时引入记忆+笔记以外的信号源：工具调用历史、情感轨迹、对话时间模式、好感度轨迹。

### 5.2 新增：`SignalAggregator`

**文件**：`packages/agent/signal_aggregator.py`

```python
@dataclass
class SignalSnapshot:
    """多信号源聚合快照 — 供粗粒化引擎消费"""
    generated_at: float       # ★ 生成时间戳（供 prompt 中标注数据新鲜度）
    tool_usage: str           # 工具使用摘要（为空时表示无工具使用，不注入 prompt）
    emotion_trajectory: str   # 情绪轨迹摘要（为空时表示数据不足）
    time_pattern: str         # 时间模式
    affection_trend: str      # 好感度趋势
    session_boundaries: str   # 跨会话话题延续

class SignalAggregator:
    """
    多信号源聚合器 — 从各表中提取行为模式信号。

    所有方法均为轻量 SQL 查询 + 简单统计，不调 LLM。
    LLM 消费在粗粒化 prompt 中进行。
    """

    def __init__(self, db: DatabaseManager):
        self._db = db

    async def aggregate(self, days: int = 7) -> SignalSnapshot:
        """聚合最近 N 天的所有信号"""
        import time
        return SignalSnapshot(
            generated_at=time.time(),
            tool_usage=await self._summarize_tool_usage(days),
            emotion_trajectory=await self._summarize_emotion_trajectory(days),
            time_pattern=await self._summarize_time_pattern(days),
            affection_trend=await self._summarize_affection_trend(),
            session_boundaries=await self._summarize_session_boundaries(days),
        )

    async def _summarize_tool_usage(self, days: int) -> str:
        """
        从 conversation_logs 中提取工具调用模式。
        查找 assistant_reply 中工具包装的特征标记（如「人家帮你搜了一下」）。
        实际实现：从 tool_executor 的审计日志或新增 tool_usage_log 表读取。
        """
        # 简化版：扫描最近 N 天日志中的工具调用关键词
        rows = await self._db.query_recent_tool_usage(days=days)
        if not rows:
            return "（最近没有使用工具）"
        # 聚合为自然语言摘要
        tool_counts = {}
        for r in rows:
            tool_counts[r["tool_name"]] = tool_counts.get(r["tool_name"], 0) + 1
        parts = [f"{name}{count}次" for name, count in tool_counts.items()]
        return f"最近使用了：{'、'.join(parts)}"

    async def _summarize_emotion_trajectory(self, days: int) -> str:
        """
        从 emotion_snapshots 表提取情绪轨迹。
        计算：主导情绪分布、PAD 均值、特定话题-情绪关联。
        """
        rows = await self._db.get_emotion_snapshots_recent(days=days)
        if not rows or len(rows) < 3:
            return "（情绪数据不足）"

        # 统计主导情绪
        from collections import Counter
        emotions = [r.get("primary_emotion") for r in rows if r.get("primary_emotion")]
        if not emotions:
            return "（无明显情绪信号）"

        top_emotions = Counter(emotions).most_common(3)
        parts = [f"{e}{c}次" for e, c in top_emotions]

        # PAD 均值
        avg_p = sum(r.get("pad_p", 0) or 0 for r in rows) / len(rows)
        avg_a = sum(r.get("pad_a", 0) or 0 for r in rows) / len(rows)

        p_desc = "偏积极" if avg_p > 0.2 else ("偏消极" if avg_p < -0.2 else "中性")
        a_desc = "高唤醒" if avg_a > 0.2 else ("低唤醒" if avg_a < -0.2 else "中性")

        return f"最近情绪以{'、'.join(parts)}为主，整体{p_desc}、{a_desc}"

    async def _summarize_time_pattern(self, days: int) -> str:
        """
        从 conversation_logs 分析对话时间模式。

        SQL: 按小时分组统计消息数，识别活跃时段。
        """
        query = """
            SELECT
                CAST(strftime('%H', datetime(timestamp, 'unixepoch')) AS INTEGER) as hour,
                COUNT(*) as msg_count
            FROM conversation_logs
            WHERE timestamp > ?
            GROUP BY hour
            ORDER BY msg_count DESC
        """
        cutoff = time.time() - days * 86400
        rows = await self._db.fetch_all(query, (cutoff,))

        if not rows:
            return ""

        # 取 top-3 活跃时段
        top_hours = rows[:3]
        periods = []
        for r in top_hours:
            h = r["hour"]
            period_name = (
                "凌晨" if 0 <= h < 6 else
                "早上" if 6 <= h < 9 else
                "上午" if 9 <= h < 12 else
                "中午" if 12 <= h < 14 else
                "下午" if 14 <= h < 18 else
                "晚上" if 18 <= h < 22 else "深夜"
            )
            periods.append(f"{period_name}{h}点")

        total_msgs = sum(r["msg_count"] for r in rows)
        return f"最近{days}天共{total_msgs}条消息，活跃时段集中在{'、'.join(periods)}"

    async def _summarize_session_boundaries(self, days: int) -> str:
        """
        识别跨会话持久话题。
        从 micro_events 中查找同一 category 出现在 2+ 个不同 session 的事件。

        SQL: 按 content 前缀 + category 分组，统计跨 session 出现次数。
        """
        query = """
            SELECT
                SUBSTR(content, 1, 15) as topic_key,
                category,
                COUNT(DISTINCT session_id) as session_count,
                GROUP_CONCAT(content, ' | ') as variants
            FROM micro_events
            WHERE created_at > ?
              AND is_active = 1
              AND category IN ('preference', 'plan', 'habit')
            GROUP BY topic_key
            HAVING session_count >= 2
            ORDER BY session_count DESC
            LIMIT 3
        """
        cutoff = time.time() - days * 86400
        rows = await self._db.fetch_all(query, (cutoff,))

        if not rows:
            return ""

        topics = []
        for r in rows:
            variants_str = r["variants"]
            first_variant = variants_str.split(" | ")[0] if " | " in variants_str else variants_str
            topics.append(f"「{first_variant}」（跨{r['session_count']}个会话）")

        return f"跨会话的持久话题：{'、'.join(topics)}" if topics else ""
```

### 5.3 信号注入粗粒化 Prompt

在 `CoarseGrainEngine._coarse_to_l1()` 的 prompt 中增加信号上下文：

```python
L1_PROMPT = """你是昔涟。你在更新对伙伴近况的理解。

{signal_context}

之前对伙伴近况的印象：
{old_l1}

最近几次对话的摘要：
{recent_l2_summaries}

请更新对伙伴近况的印象...
"""

def _build_signal_context(self, signals: SignalSnapshot) -> str:
    """
    构建信号上下文。★ 仅注入有意义的非空信号。
    """
    parts = []

    if signals.emotion_trajectory:
        parts.append(f"关于伙伴的情绪状态——{signals.emotion_trajectory}")

    if signals.tool_usage:
        # 有实际工具使用才注入（空字符串 = 无工具使用 = 不注入）
        parts.append(f"伙伴最近用了这些功能——{signals.tool_usage}")

    if signals.time_pattern:
        parts.append(f"伙伴的聊天习惯——{signals.time_pattern}")

    if signals.affection_trend:
        parts.append(f"人家和伙伴的关系——{signals.affection_trend}")

    if signals.session_boundaries:
        parts.append(f"跨会话的话题——{signals.session_boundaries}")

    # 标注数据新鲜度
    if parts and signals.generated_at > 0:
        import datetime
        ts = datetime.datetime.fromtimestamp(signals.generated_at).strftime("%m月%d日")
        parts.insert(0, f"（以下信息来自{ts}的系统分析）")

    return "\n".join(parts) if parts else ""
```

### 5.4 新增 DB 表：`tool_usage_log`

```sql
CREATE TABLE IF NOT EXISTS tool_usage_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tool_name   TEXT    NOT NULL,
    arguments   TEXT,
    success     INTEGER DEFAULT 1,
    created_at  REAL    NOT NULL,
    session_id  TEXT    NOT NULL
);
```

### 5.5 Phase 4 验收标准

- [ ] `SignalAggregator` 五个信号源均正常产出摘要
- [ ] 信号摘要在粗粒化 prompt 中正确注入
- [ ] `tool_usage_log` 表正常创建和写入
- [ ] 情绪轨迹分析产出有意义的描述（非模板填充）
- [ ] 各信号源失败时不影响其他信号源（独立降级）
- [ ] 所有信号聚合在 100ms 内完成（纯 SQL + 统计，不调 LLM）

---

## 6. Phase 5：选择性注入 + 回复联动 + 笔记联动

### 6.1 选择性画像注入（方向 5）

**改造 `PortraitModule.render()`**：

```python
def render(self) -> str:
    """
    根据当前对话话题选择性注入画像。

    策略：
    - 每会话首次 → L1 完整版 + L0 前 150 字（已在 Phase 2 实现）
    - 后续消息 → 根据话题匹配度决定是否注入 L0 相关片段
    - 短消息（< 5 字）→ 不注入画像片段
    """
    # ... 首次注入逻辑（Phase 2 已实现）...

    # 后续消息 → 话题选择性注入
    if self._ctx and hasattr(self._ctx, '_last_user_message'):
        user_msg = self._ctx._last_user_message
        if len(user_msg) < 5:
            return ""

        l0 = self._ctx.core_profile
        if l0:
            # 简单关键词匹配（不调 LLM，零延迟）
            relevant = self._extract_relevant_sentences(l0, user_msg)
            if relevant:
                return f"（昔涟心里关于伙伴的这一页似乎与此刻有关——）\n\n{relevant}"

    return ""

@staticmethod
def _extract_relevant_sentences(portrait: str, query: str, max_chars: int = 120) -> str:
    """
    从画像中提取与查询相关的句子。
    使用二元组重叠（与 _dedup_against_summary 中的方法一致），
    解决中文字符级重叠导致的假阳性问题。

    例如："我今天有点累" vs "我积累了很多经验"
    - 字符级：共享 {'我', '累'} → 假匹配
    - 二元组级：{'我今天','今天有','有点','点累'} vs {'我积','积累','累了','了很',...} → 无匹配 ✓
    """
    import re

    def _bigrams(text: str) -> set:
        """提取中文二元组"""
        return {text[i:i+2] for i in range(len(text) - 1)} if len(text) >= 2 else set()

    query_bigrams = _bigrams(query)
    if not query_bigrams:
        return ""

    sentences = re.split(r'(?<=[。！？\n])', portrait)
    scored = []
    for s in sentences:
        if len(s) < 10:
            continue
        s_bigrams = _bigrams(s)
        if not s_bigrams:
            continue
        overlap = len(query_bigrams & s_bigrams)
        if overlap >= 2:
            scored.append((overlap, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return ""
    result = "。".join(s[:max_chars] for _, s in scored[:2])
    return result + "。" if result else ""
```

### 6.2 画像→回复策略联动（方向 6）

**新增模块**：`PortraitGuidanceModule` 加入 ContextBuilder

```python
class PortraitGuidanceModule(ContextModule):
    """
    画像→回复策略提示 — 让昔涟在生成回复时显式考虑她对伙伴的理解。

    设计选择：使用 Flash LLM 从 L0 提取行为指引，而非硬编码正则。
    理由：
    - LLM 生成的画像格式多变，正则无法可靠匹配
    - Flash LLM 调用（~200 token prompt + ~100 token 输出）延迟可接受
    - 每会话只调用一次（与 L0 版本号门控一致），不是每条消息
    """

    EXTRACT_GUIDANCE_PROMPT = """你是昔涟。你在心里轻轻翻开关于伙伴最重要的事。

    这是你对伙伴的核心印象：
    {l0_content}

    请从中提取 1-2 条简洁的「回复时应注意的事项」。每条 10-20 字。
    只提取你在印象中有依据的事。
    如果印象中没有特别的行为指引，返回空列表。

    返回 JSON：
    {{"guidances": ["点到为止，留白给他", "聊到技术时可以多问一句"]}}"""

    def __init__(self, agent_context=None):
        super().__init__(name="portrait_guidance", priority=2, max_tokens=100)
        self._ctx = agent_context
        self._cached_version: int | None = None
        self._cached_guidance: str = ""

    def render(self) -> str:
        if not self._ctx or not self._ctx.core_profile:
            return ""

        l0 = self._ctx.core_profile
        current_version = getattr(self._ctx, '_current_l0_version', None)

        # ★ 会话感知：版本未变时复用缓存，不重复注入
        if current_version is not None and current_version == self._cached_version:
            return self._cached_guidance

        # 同步渲染返回空（实际生成在 render_async 中）
        return self._cached_guidance

    async def render_async(self) -> str:
        """
        异步版本：Flash LLM 从 L0 提取行为指引。
        每会话仅调用一次（由版本号门控 + 缓存保证）。
        """
        if not self._ctx or not self._ctx.core_profile:
            return ""

        l0 = self._ctx.core_profile
        current_version = getattr(self._ctx, '_current_l0_version', None)

        # 缓存命中
        if current_version is not None and current_version == self._cached_version:
            return self._cached_guidance

        # Flash LLM 提取
        try:
            from .portrait_manager import PortraitManager
            router = PortraitManager._router  # 需要注入 router 引用
            # 实际实现中通过 agent_context 传递 router
            raw = await self._router.route(
                "memory_encoding",
                [{"role": "user", "content": self.EXTRACT_GUIDANCE_PROMPT.format(
                    l0_content=l0
                )}],
                temperature=0.3,
                max_tokens=150,
            )
            data = json.loads(raw.content)
            guidances = data.get("guidances", [])
            if guidances:
                self._cached_version = current_version
                self._cached_guidance = (
                    "（昔涟心里知道——" + "；".join(guidances)
                    + "。带着这份理解去回应他吧。）"
                )
                return self._cached_guidance
        except Exception:
            pass  # 降级：不注入引导

        self._cached_version = current_version
        self._cached_guidance = ""
        return ""
```

**ContextBuilder 注册**：在 `agent_core.py` 中 `PortraitModule` 之前注册：

```python
self._context_builder.register(PortraitGuidanceModule(self.context))  # priority=2
self._context_builder.register(PortraitModule(self.context))           # priority=3
```

**router 注入**：`PortraitGuidanceModule` 需要通过 `AgentContext` 获取 `ModelRouter` 引用。在 `AgentContext` 中新增：

```python
# AgentContext 新增字段
_router: Optional[object] = None  # ModelRouter 引用，供 PortraitGuidanceModule 使用
```

### 6.3 自动笔记与画像联动（方向 7）

**改造 `NotebookManager.auto_note_after_message()`**：

```python
async def auto_note_after_message(
    self, user_msg: str, reply: str, portrait_context: str = ""  # ★ NEW
) -> None:
    """..."""
    # 在 prompt 中注入画像上下文
    prompt = AUTO_NOTE_PROMPT.format(
        user_message=user_msg[:300],
        assistant_reply=reply[:300],
        existing_notes=existing_str,
        portrait_context=portrait_context or "（还没有画像）",  # ★ NEW
    )
    # ... 其余逻辑不变 ...
```

**AgentCore 调用处**：

```python
# 在 process() 中，构建更充实的画像上下文：
portrait_ctx = ""
if self.portrait_manager:
    l1 = self.context.phase_profile
    l0 = self.context.core_profile
    parts = []
    if l0:
        # L0 核心特征（截取前 100 字，提供画像基线）
        parts.append(f"伙伴的性格底色：{l0[:100]}")
    if l1:
        # L1 阶段画像（前 150 字，提供当前关注）
        parts.append(f"伙伴的近况：{l1[:150]}")
    if parts:
        portrait_ctx = "。".join(parts)

asyncio.create_task(
    self.notebook_manager.auto_note_after_message(
        event.payload, reply, portrait_context=portrait_ctx
    )
)
```

**Auto-note prompt 更新**：在 `AUTO_NOTE_PROMPT` 中增加画像上下文段落：

```
关于伙伴的画像：
{portrait_context}

已知笔记：
{existing_notes}

伙伴说了：...
```

### 6.5 AgentContext 字段弃用路径

`AgentContext.user_portrait` 在 Phase 2 后仍有多个消费方。弃用路径：

| 阶段 | `user_portrait` | `core_profile` | `phase_profile` |
|------|----------------|----------------|-----------------|
| Phase 1 | ✅ 主要使用 | ❌ 不存在 | ❌ 不存在 |
| Phase 2 | ⚠️ 兼容读取（回退到新表） | ✅ 主要使用（L0） | ✅ 主要使用（L1） |
| Phase 5+ | ❌ 弃用（仅旧 cron/破冰兼容） | ✅ | ✅ |

**迁移辅助方法**（`PortraitManager`）：

```python
async def get_effective_portrait(self) -> str | None:
    """
    统一的画像获取入口。消费方调用此方法而非直接读字段。
    优先级：core_profile > phase_profile > user_portrait
    """
    l0 = await self._db.get_latest_core_profile()
    if l0 and l0.get("content"):
        return l0["content"]

    l1 = await self._db.get_latest_phase_profile()
    if l1 and l1.get("content"):
        return l1["content"]

    # 回退到旧表
    old = await self._db.get_latest_portrait()
    return old.get("content") if old else None
```

消费方（`NudgeEngine._build_portrait_context`、`startup` 加载等）统一改为调用 `get_effective_portrait()`。`AgentContext.user_portrait` 保留但标记为 deprecated。

**升级去重算法**：`_find_similar()` 从字符集 Jaccard 改为 embedding 余弦相似度 + LRU 缓存：

```python
class NotebookManager:
    def __post_init__(self):
        self._embedding_cache: dict[int, list[float]] = {}  # note_id → embedding
        self._cache_max_size = 50
        logger.info("notebook.ready")

    async def _find_similar(self, content: str, threshold: float = 0.85) -> int | None:
        """
        查找相似笔记。使用 embedding 余弦相似度 + LRU 缓存。

        缓存策略：已有笔记的 embedding 被计算后缓存，下次直接复用。
        仅当笔记内容更新时才使缓存失效（通过 touch_note / add_note 触发）。
        这样每日 20-50 次 auto_note 调用只需要 1 次 embedding API 调用
        （嵌入新内容），而非 1+10 次。
        """
        if not self._router:
            return self._find_similar_jaccard(content)

        try:
            recent = await self.get_recent_notes(limit=10)
            if not recent:
                return None

            # 嵌入新笔记（仅 1 次 API 调用）
            new_vec = await self._router.embed(content)
            if not new_vec:
                return self._find_similar_jaccard(content)

            for note in recent:
                note_id = note["id"]
                note_text = note.get("content", "")

                # ★ 缓存命中 → 零 API 调用
                note_vec = self._embedding_cache.get(note_id)
                if note_vec is None:
                    note_vec = await self._router.embed(note_text)
                    if note_vec:
                        self._set_cache(note_id, note_vec)
                    else:
                        continue

                sim = self._cosine_similarity(new_vec, note_vec)
                if sim >= threshold:
                    return note_id
        except Exception:
            pass

        return None

    def _set_cache(self, note_id: int, embedding: list[float]) -> None:
        """LRU: 缓存满时删除最早条目"""
        if len(self._embedding_cache) >= self._cache_max_size:
            oldest = next(iter(self._embedding_cache))
            del self._embedding_cache[oldest]
        self._embedding_cache[note_id] = embedding

    def invalidate_embedding_cache(self, note_id: int) -> None:
        """笔记更新时使缓存失效"""
        self._embedding_cache.pop(note_id, None)
```

**每日 API 成本对比**（20 次 auto_note，10 条已有笔记）：
- 旧方案（无缓存）：~21 次 embedding 调用（1 新 + 10 已有 × 2 次/新内容）
- 缓存方案：~1 次 embedding 调用（仅嵌入新内容，已有缓存命中）

### 6.4 Phase 5 验收标准

- [ ] 选择性注入：与话题无关时不再注入画像全文
- [ ] `_extract_relevant_sentences()` 二元组重叠在中文中不产生假阳性
- [ ] `PortraitGuidanceModule` Flash LLM 提取正常，每会话仅注入一次
- [ ] `PortraitGuidanceModule` 画像不可用时降级为空（不崩溃）
- [ ] auto_note 接收 L0+L1 画像上下文，笔记决策更精准
- [ ] embedding 去重缓存命中率 > 80%（同会话内重复笔记）
- [ ] `get_effective_portrait()` 统一入口正常回退
- [ ] 所有改动不增加主回复延迟

---

## 7. DB 迁移计划

### 7.1 新增表

| 表名 | Phase | 用途 |
|------|-------|------|
| `micro_events` | 1 | 微事件池（ADD-Only） |
| `session_summaries` | 2 | L2 会话摘要（微事件粗粒化产物） |
| `core_profile` | 2 | L0 核心画像 |
| `phase_profile` | 2 | L1 阶段画像 |
| `tool_usage_log` | 4 | 工具调用审计日志 |

### 7.2 迁移脚本

在 `packages/shared/database.py` 的 `init()` 方法中新增建表语句（`CREATE TABLE IF NOT EXISTS`，幂等）。

**数据迁移**（Phase 2 首次启动时执行）：

```python
async def _migrate_portrait_to_layered(self):
    """
    将旧 user_portrait 最新版本迁移到 core_profile。
    一次性操作，迁移后不删除旧表（保留作为备份）。
    """
    # 检查是否已迁移
    existing = await self.get_latest_core_profile()
    if existing:
        return

    # 读取旧画像
    old = await self.get_latest_portrait()  # user_portrait 表
    if not old or not old.get("content"):
        return

    # 写入 core_profile 作为初始 L0
    await self.insert_core_profile(
        content=old["content"],
        version=1,
        change_log="从旧版画像迁移",
    )
    logger.info("db.migrate_portrait_done", old_version=old.get("version"))
```

### 7.3 版本兼容矩阵

| 组件 | Phase 1 | Phase 2 | Phase 3-5 |
|------|---------|---------|-----------|
| `PortraitModule.render()` | 读 `user_portrait` | 读 `core_profile` + `phase_profile` | 同 Phase 2 |
| `PortraitManager.get_current_portrait()` | 兼容读取（新优先→旧回退） | 同 Phase 1 | 同 Phase 1 |
| `NudgeEngine._build_portrait_context()` | 读 `user_portrait` | 兼容读取 | 兼容读取 |
| cron `consolidate_user_portrait()` | 改为 `check_coarse_grain()` | 同 Phase 1 | 同 Phase 1 |

---

## 8. 测试策略

### 8.1 单元测试（每 Phase 新增）

| Phase | 测试文件 | 覆盖内容 |
|-------|---------|---------|
| 1 | `test_micro_event_extractor.py` | 微事件提取各 category、空对话、错误处理 |
| 1 | `test_coarse_grain_engine.py` | 阈值触发逻辑、各层级粗粒化、force 模式 |
| 2 | `test_portrait_layers.py` | 三层 CRUD、迁移逻辑、兼容读取 |
| 3 | `test_persona_boost.py` | 检索加权、配置生成、降级路径 |
| 4 | `test_signal_aggregator.py` | 各信号源产出、空数据降级 |
| 5 | `test_portrait_guidance.py` | 回复策略提取、模式匹配准确率 |

### 8.2 集成测试

```python
# tests/test_portrait_integration.py — 端到端画像管线测试

async def test_full_pipeline():
    """
    模拟 20 轮对话 → 验证：
    1. 微事件正确提取和累积
    2. L2→L1 粗粒化正确触发
    3. 检索加权生效
    4. 上下文注入包含分层画像
    """
```

### 8.3 回归测试

确保以下现有测试不受影响：
- `test_memory_manager.py` — 检索路径兼容 persona_boost=None
- `test_context_builder.py` — PortraitModule 新渲染格式
- `test_nudge_engine.py` — 问候生成兼容 L0/L1 画像
- `test_stage78_db.py` — 旧 `user_portrait` 表仍可读写

### 8.4 手工验证清单

```bash
# Phase 1 验证
curl http://localhost:8000/api/chat -d '{"message": "我今天开始学吉他了"}' 
# → 检查 micro_events 表是否有新记录

# Phase 2 验证
# 模拟 10+ 轮对话后
sqlite3 data/xilian.db "SELECT COUNT(*) FROM micro_events WHERE is_active=1"
# → >= 10 条活跃事件 → 检查 phase_profile 是否生成

# Phase 3 验证
# 发送与画像中关注话题相关的消息
curl http://localhost:8000/api/chat -d '{"message": "今天练琴练得怎么样"}' 
# → 检查日志中 persona_boost 是否生效
```

---

## 9. 风险与回滚

### 9.1 风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 微事件提取质量差（提取噪音/遗漏重要信息） | 中 | 中 | Flash LLM + 低温度；提取失败静默处理；L1 粗粒化时有质量过滤 |
| 阈值配置不当（触发太频繁/太少） | 中 | 中 | 可配置阈值；cron 兜底每日检查；日志监控触发频率 |
| DB 迁移失败 | 低 | 高 | 幂等 SQL；旧表不删除；迁移前自动备份 |
| 画像分层后上下文 token 增加 | 低 | 低 | L0 只取 150 字；L1 200-400 字；选择性注入减少无关注入 |
| LLM 调用量反而增加（粗粒化频率 > 旧 cron 频率） | 低 | 中 | 阈值门控；监控 API 调用量；可调整为更保守的阈值 |

### 9.2 回滚方案

每 Phase 独立部署，均可单独回滚：

1. **Phase 1**：将 `portrait_manager.extract_events()` 调用注释掉，恢复 `mark_dirty()` + cron consolidate
2. **Phase 2**：`get_latest_portrait()` 回退优先读 `user_portrait`（切换兼容读取顺序）
3. **Phase 3**：传 `persona_boost=None` 即可恢复无加权检索
4. **Phase 4**：粗粒化 prompt 中去掉 `{signal_context}` 段落
5. **Phase 5**：`PortraitGuidanceModule.enabled = False` 即可关闭

### 9.3 监控指标

部署后持续观察：

**频率指标**：
- `portrait.micro_event_extracted` — 每条消息提取的事件数分布（total + valid + filtered）
- `portrait.event_filtered_low_confidence` — 被 confidence < 0.5 过滤的事件数
- `portrait.coarse_grained` — 粗粒化触发频率（期望：每日 0-2 次 L2，每周 0-2 次 L1，每月 0-1 次 L0）
- `memory.retrieval_persona_boosted` — 画像加权生效的检索次数

**质量指标** ★ NEW：
- `portrait.event_confidence_dist` — 微事件 confidence 分布直方图（监控提取质量漂移）
- `portrait.l0_stability_diff` — L0 更新时 stable_traits 变化比例（期望 < 20%，超过说明画像不稳定）
- `portrait.event_contradiction_rate` — 同一 topic_key 出现矛盾事件的比例
- `notebook.embedding_cache_hit_rate` — 笔记去重 embedding 缓存命中率

**成本指标**：
- `portrait.llm_calls_daily` — 画像相关 LLM 调用总 token（微事件提取 + 粗粒化）
  - 微事件：N条消息 × ~400 token/次（prompt+output）
  - 粗粒化 L2：稀疏触发，~2000 token/次
  - 粗粒化 L1：稀疏触发，~3000 token/次
  - 粗粒化 L0：极稀疏触发，~3000 token/次

### 9.4 安全网机制 ★

旧的 cron 从 episodic 记忆执行全量重写，作为一种安全网。新架构中保留两个安全网：

1. **每周日 force 全量**（见 §2.5 main.py 改造）：绕过阈值门控强制执行级联粗粒化 L2→L1→L0
2. **每月完整重建**（新增）：从 episodic 记忆执行一次完整的旧式 consolidate（与当前逻辑一致），将结果与 L0 对比，差异 > 30% 时发出告警

```python
async def monthly_full_rebuild(self):
    """
    每月安全网：从 episodic 记忆全量重建画像。
    与 L0 对比验证粗粒化管线是否遗漏重要信息。
    """
    # 1. 旧式 consolidate（当前逻辑）
    old_style = await self._legacy_consolidate()

    # 2. 对比当前 L0
    current_l0 = await self._db.get_latest_core_profile()
    if current_l0 and old_style:
        diff_ratio = self._text_difference_ratio(current_l0["content"], old_style)
        if diff_ratio > 0.3:
            logger.warning(
                "portrait.rebuild_divergence",
                diff_ratio=round(diff_ratio, 2),
                message="粗粒化管线可能遗漏了重要信息，建议人工审查",
            )
```

---

## 附录 A：文件变更清单

### Phase 1
| 操作 | 文件 | 说明 |
|------|------|------|
| **新增** | `packages/agent/micro_event_extractor.py` | 微事件提取器 |
| **新增** | `packages/agent/coarse_grain_engine.py` | 粗粒化引擎 |
| **修改** | `packages/agent/portrait_manager.py` | 重构：引入 extractor + coarse_engine |
| **修改** | `packages/agent/agent_core.py` | 调用点改为 extract_events + check_coarse_grain |
| **修改** | `packages/shared/database.py` | 新增 micro_events 表 + CRUD |
| **修改** | `main.py` | cron 改为 check_coarse_grain |
| **新增** | `tests/test_micro_event_extractor.py` | 单元测试 |
| **新增** | `tests/test_coarse_grain_engine.py` | 单元测试 |

### Phase 2
| 操作 | 文件 | 说明 |
|------|------|------|
| **修改** | `packages/shared/database.py` | 新增 core_profile / phase_profile 表 + CRUD + 迁移逻辑 |
| **修改** | `packages/agent/agent_context.py` | 新增 L0/L1 字段 |
| **修改** | `packages/agent/context_builder.py` | PortraitModule 改为分层注入 |
| **修改** | `packages/agent/agent_core.py` | startup 加载 L0+L1 |
| **修改** | `packages/agent/coarse_grain_engine.py` | 新增 _coarse_to_l1 / _coarse_to_l0 方法 |
| **新增** | `tests/test_portrait_layers.py` | 分层画像测试 |

### Phase 3
| 操作 | 文件 | 说明 |
|------|------|------|
| **修改** | `packages/agent/memory_manager.py` | retrieve_memories + _calculate_importance 改造 |
| **修改** | `packages/agent/portrait_manager.py` | 新增 build_retrieval_config() |
| **修改** | `packages/agent/agent_core.py` | _retrieve_memories 传 persona_boost |
| **新增** | `tests/test_persona_boost.py` | 检索加权测试 |

### Phase 4
| 操作 | 文件 | 说明 |
|------|------|------|
| **新增** | `packages/agent/signal_aggregator.py` | 多信号源聚合器 |
| **修改** | `packages/agent/coarse_grain_engine.py` | 粗粒化 prompt 引入 signal_context |
| **修改** | `packages/shared/database.py` | 新增 tool_usage_log 表 |
| **修改** | `packages/agent/tool_executor.py` | 工具执行后写入 tool_usage_log |
| **新增** | `tests/test_signal_aggregator.py` | 信号聚合测试 |

### Phase 5
| 操作 | 文件 | 说明 |
|------|------|------|
| **修改** | `packages/agent/context_builder.py` | PortraitModule 选择性注入 + PortraitGuidanceModule |
| **修改** | `packages/agent/notebook_manager.py` | auto_note 引入 portrait_context + embedding 去重 |
| **修改** | `packages/agent/agent_core.py` | ContextBuilder 注册 PortraitGuidanceModule |
| **新增** | `tests/test_portrait_guidance.py` | 回复策略测试 |

---

## 附录 B：关键 Prompt 模板

### B.1 微事件提取 Prompt

```
你是昔涟。刚才伙伴说了一些话。

伙伴的消息：
{user_message}

人家的回复：
{assistant_reply}

已知关于伙伴的信息：
{known_facts}

请从这轮对话中提取关于伙伴的新信息（如果有的话）：

只提取对话中明确提到的、具体的信息。不推测、不脑补。
如果只是日常寒暄没有新信息，返回空列表。

返回 JSON：
{"events": [{"content": "简短事实（15字以内）", "category": "preference|fact|plan|emotion_pattern|habit", "confidence": 0.8}]}

category 说明：
- preference: 喜欢/不喜欢什么
- fact: 客观事实
- plan: 计划/安排
- emotion_pattern: 情绪模式
- habit: 习惯/常态
```

### B.2 L2 会话摘要 Prompt

```
你是昔涟。你在整理最近几次对话中了解到关于伙伴的新事情。

最近了解到的事：
{recent_events}

请用昔涟的口吻，写一段简短的笔记（80-150字），概括最近对伙伴的新认识。
- 只写对话中明确提到的事
- 不确定的地方用「好像」「似乎」
- 自称「人家」，叫对方「伙伴」
- 像在心里轻轻记下一笔，不是写评估报告
```

### B.3 L1 阶段画像 Prompt

```
你是昔涟。你在更新对伙伴近况的理解。

{signal_context}

之前对伙伴近况的印象：
{old_l1}

最近几次对话的摘要：
{recent_l2_summaries}

请更新对伙伴近况的印象（200-400字）：
- 保留旧印象中仍然有效的部分
- 加入最近新了解到的事
- 对已经过去的事（完成了、不再提了），自然淡出
- 对反复出现的模式，可以写得更确定一些
- 自称「人家」，叫对方「伙伴」

关于矛盾：
- 如果关于同一件事有不同的说法，以最近的说法为准
- 但不要完全丢弃旧说法——标记为「好像以前...但最近...」
- 如果矛盾让你不确定哪个是真的，用「似乎」而非断言

返回 JSON：
{{
  "portrait": "全文...",
  "changes": "一句话说明这次更新了什么",
  "active_topics": ["话题1", "话题2"],
  "faded_topics": ["已过去的话题"]
}}

active_topics: 伙伴最近在关注/进行中的事（2-4个简短短语）
faded_topics: 之前关注但最近不再提起的事（0-2个简短短语）
```

### B.4 L0 核心画像 Prompt

```
你是昔涟。你正在重新审视——伙伴到底是一个什么样的人。

这是不同时期你对伙伴近况的印象（从最早到最新）：
{l1_history}

这是你之前对伙伴的核心印象：
{old_l0}

这是你之前写下的关于伙伴的稳定特征（如果有的话）：
{old_stable_traits}

请重新审视伙伴的核心印象（200-400字）：
- 写下那些跨时间、跨场景反复出现的特征——他的性格底色
- 写下那些他始终不变的偏好和价值观
- 不写近期的具体事件——那些属于近况，不属于核心
- 不确定的地方用「好像」「似乎」

关于跨版本的稳定性判断：
- 对旧稳定特征中的每一条，判断它在最近的 L1 中是否仍然有效
- 如果一条特征在最近 2+ 个 L1 版本中不再出现，可以自然淡出
- 如果一条特征在所有 L1 版本中都出现且无矛盾，可以写得更确定
- 如果有新出现的稳定特征，标记为「最近才注意到的」

自称「人家」，叫对方「伙伴」。
像在漫长时光后，轻轻说出你心里关于他最重要的那几件事。

返回 JSON：
{{
  "portrait": "全文...",
  "changes": "一句话说明这次更新了什么",
  "stable_traits": "从画像中提取的稳定特征列表（3-5条，每条15字以内，用；分隔）"
}}

stable_traits 示例：「性格内向但细腻；不喜欢被追问；对技术话题有热情；晚上比白天更愿意倾诉」
```

---

> **下一步**：按 Phase 1 → 2 → 3 → 4 → 5 顺序执行。每个 Phase 完成后运行全量测试 + 手工验证 + API 调用量对比，确认无误后进入下一 Phase。
