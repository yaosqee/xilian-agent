# DatabaseManager 拆分计划

> R2-002: 2403 行 God Object → 拆分为领域 Repository

## 一、现状

```
packages/shared/database.py  (2403 行, 104 方法, 18 张表)
├── conversation_logs      (8 方法)
├── episodic_memories      (12 方法)
├── message_queue           (6 方法)
├── emotion_snapshots       (6 方法)
├── autobiography_entries   (3 方法)
├── reflection_crystals     (3 方法)
├── autonomy_settings       (2 方法)
├── notebook_entries        (7 方法)
├── scheduled_tasks         (5 方法)
├── audit_logs              (3 方法)
├── affection_state         (3 方法)
├── user_portrait           (2 方法)
├── core_profile            (4 方法)
├── phase_profile           (4 方法)
├── micro_events            (3 方法)
├── session_summaries       (2 方法)
├── tool_usage_log          (2 方法)
├── cron_runs               (2 方法)
├── model_configs           (2 方法)
├── embed_config            (2 方法)
├── uploaded_images         (2 方法)
├── lifecycle               (init/close/manual_init 等 10 方法)
└── helpers                 (forget_user_data, _vec_delete_batch, migrate 等)
```

**调用方**（生产代码 9 个模块，测试 12 个模块）：

| 调用方 | 主要使用的表 |
|--------|-------------|
| `agent_core.py` | 全部（直接通过 _db 属性） |
| `http_channel.py` | conversation, emotion, memory, portrait, notebook, audit, affection, model_config |
| `memory_manager.py` | episodic_memories + embedding |
| `notebook_manager.py` | notebook_entries + scheduled_tasks |
| `nudge_engine.py` | emotion, affection, autonomy, conversation |
| `coarse_grain_engine.py` | micro_events, session_summaries, core/phase_profile |
| `micro_event_extractor.py` | micro_events |
| `signal_aggregator.py` | micro_events, conversation, tool_usage |
| `model_router.py` | model_configs, embed_config |
| `portrait_manager.py` | core/phase_profile, user_portrait, episodic_memories |

## 二、拆分策略：渐进式委托

**核心原则：零破坏性变更。**

1. 创建 `packages/shared/database/` 包，内含 7 个 Repository 类
2. 每个 Repository 接收 `aiosqlite.Connection` + `session_id`，只操作自己的表
3. `DatabaseManager` 保留全部公开方法签名，内部委托给 Repository
4. 外部调用方完全无感知——API 不变、返回值不变、异常语义不变

**为什么不用更激进的方式（如直接改调用方）？**
- 9 个调用方分散在后端/前端/网关/测试中
- `agent_core.py` 通过 `self._db.xxx()` 调用 20+ 种不同方法
- 一次性改全部调用方风险不可控
- 委托模式可渐进迁移：先提取实现 → 稳定性验证 → 逐步迁移调用方

## 三、目标分组

### 分组 1: `ConversationRepository` (~160 行)
**职责**: 对话日志 CRUD
**方法** (8):
```
insert_log, get_recent, get_by_session, get_conversation_history,
get_conversation_total, clear_conversation_logs, get_emotion_history,
get_last_activity_timestamp
```

### 分组 2: `EpisodicMemoryRepository` (~210 行)
**职责**: 情景记忆 + 嵌入状态管理
**方法** (12):
```
insert_episodic_memory, update_embedding_status, update_embedding_model,
get_episodic_memory, get_episodic_by_embedding_ids, get_episodic_recent,
get_episodic_pending, get_all_episodic, delete_episodic,
increment_access_count, get_episodic_count, count_high_importance_memories
```

### 分组 3: `EmotionRepository` (~130 行)
**职责**: PAD 情绪快照 CRUD
**方法** (6):
```
insert_emotion_snapshot, get_latest_emotion, get_emotion_snapshots,
get_emotion_snapshots_recent, get_emotions_by_memory_ids, get_emotion_stats
```

### 分组 4: `ProfileRepository` (~210 行)
**职责**: 用户画像 CRUD（L0 核心画像 + L1 阶段画像 + 旧 user_portrait 兼容读取）
**方法** (8):
```
insert_user_portrait, get_latest_portrait,
insert_core_profile, get_latest_core_profile, get_core_profile_history,
insert_phase_profile, get_latest_phase_profile, get_phase_profile_history
```
> **注意**: `migrate_portrait_to_layered()` 同时操作旧表和新表（跨 Repository 边界），
> 类似 `forget_user_data`，保留在 DatabaseManager 层。

### 分组 5: `NotebookRepository` (~180 行)
**职责**: 笔记本 + 任务管理
**方法** (12):
```
insert_notebook, get_notebook_notes, get_notebook_today_diary,
get_notebook_diary_list, archive_notebook_entries, delete_notebook_entry,
touch_notebook_entry, insert_task, get_due_tasks, get_pending_tasks,
complete_task, cancel_task, delete_task
```

### 分组 6: `AnalyticsRepository` (~100 行)
**职责**: 画像管道数据源 — 微事件、会话摘要、工具使用统计
> 这三张表天然内聚：都被 `coarse_grain_engine.py` 和 `signal_aggregator.py` 消费，
> 是画像粗粒化管线的统一数据源。
**方法** (7):
```
insert_micro_event, get_active_micro_events, absorb_micro_events,
insert_session_summary, get_recent_session_summaries,
insert_tool_usage, query_recent_tool_usage
```
> **注意**: `insert_session_summary_atomic()` 同时写 session_summaries 和 micro_events
> 两张表 → 保留在 DatabaseManager，不放入 AnalyticsRepository。
> `query_conversation_times` 和 `query_cross_session_topics` 涉及跨表查询 → 保留在 DatabaseManager。

### 其余保留在 DatabaseManager (~1050 行)

- Lifecycle: `init`, `close`, `_manual_init`, `_try_alembic_migrate`, `_vec_delete_batch`
- Autobiography: `insert_autobiography`, `get_autobiography`, `get_autobiography_list`
- Reflection: `insert_reflection`, `get_latest_reflection`, `get_reflections`
- Message Queue: `queue_push/pop/mark_done/mark_failed/recover_stale/purge_old`
- Audit: `insert_audit_log`, `get_audit_logs`, `get_audit_stats`
- Affection: `insert_affection_snapshot`, `get_latest_affection`, `get_affection_history`
- Autonomy: `get_autonomy_config`, `save_autonomy_config`
- Model Config: `insert_model_config`, `get_model_configs`, `insert_embed_config`, `get_embed_config`
- Uploads: `insert_image`, `delete_expired_images`
- Cron: `get_cron_last_run`, `set_cron_last_run`
- Cross-table ops: `forget_user_data`, `migrate_portrait_to_layered`, `insert_session_summary_atomic`, `query_conversation_times`, `query_cross_session_topics`

## 四、文件结构

```
packages/shared/database/           # 新包
├── __init__.py                     # 从 database.py 重导出 DatabaseManager
├── _base.py                        # Repository 基类（持有 conn + session_id）
│                                   #   设计要点：所有 Repository 共享同一个 aiosqlite.Connection，
│                                   #   跨 Repository 事务由 DatabaseManager 统一管理（BEGIN/COMMIT/ROLLBACK），
│                                   #   各 Repository 不自行管理事务边界。
├── conversation_repo.py            # 分组 1: 对话日志
├── episodic_memory_repo.py         # 分组 2: 情景记忆
├── emotion_repo.py                 # 分组 3: 情绪快照
├── profile_repo.py                 # 分组 4: 用户画像
├── notebook_repo.py                # 分组 5: 笔记本+任务
└── analytics_repo.py               # 分组 6: 画像分析数据源

packages/shared/database.py         # 保留，委托给 repository
```

`database.py` 中 `DatabaseManager` 变为：

```python
from .database.conversation_repo import ConversationRepository
from .database.episodic_memory_repo import EpisodicMemoryRepository
# ...

class DatabaseManager:
    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self._conn = None
        self._session_id = uuid.uuid4().hex[:12]
        # Repositories (lazy init in init())
        self._conv: ConversationRepository | None = None
        self._episodic: EpisodicMemoryRepository | None = None
        # ...

    async def init(self):
        # ... existing init logic ...
        self._conv = ConversationRepository(self._conn, self._session_id)
        self._episodic = EpisodicMemoryRepository(self._conn, self._session_id)
        # ...

    # 委托方法（签名完全不变）
    async def insert_log(self, ...):
        return await self._conv.insert_log(...)
```

## 五、波及范围

### 需要改动的文件

| 文件 | 改动类型 | 风险 |
|------|---------|------|
| `packages/shared/database.py` | 方法体改为委托 | 中 |
| `packages/shared/database/__init__.py` | 新建 | 低 |
| `packages/shared/database/_base.py` | 新建 | 低 |
| `packages/shared/database/conversation_repo.py` | 新建（从 database.py 移动） | 低 |
| `packages/shared/database/episodic_memory_repo.py` | 新建（从 database.py 移动） | 低 |
| `packages/shared/database/emotion_repo.py` | 新建（从 database.py 移动） | 低 |
| `packages/shared/database/profile_repo.py` | 新建（从 database.py 移动） | 低 |
| `packages/shared/database/notebook_repo.py` | 新建（从 database.py 移动） | 低 |
| `packages/shared/database/analytics_repo.py` | 新建（从 database.py 移动） | 低 |
| `packages/shared/__init__.py` | 可能需要更新 import 路径 | 低 |

### 不需要改动的文件

- 所有调用方（`agent_core.py`, `http_channel.py`, `memory_manager.py` 等）——委托透明
- 所有测试文件——DatabaseManager API 完全不变
- `gateway/`, `main.py`, `packages/agent/`——完全透明

## 六、验证清单

- [ ] `python3 -c "from packages.shared.database import DatabaseManager"` 导入成功
- [ ] 所有现有 AST 验证通过
- [ ] `ruff check` 无新增错误
- [ ] DatabaseManager 公开方法数量不变（grep 对比前后方法列表）
- [ ] 提取到 Repo 的方法逻辑逐行一致（`_conn.execute` 调用参数完全不变）
- [ ] **每个委托方法完整保留原始 docstring、参数类型提示、返回类型注解** — 委托方法不是空壳，需保留完整的文档
- [ ] 网络端点可正常启动（`main.py` import 链路不破坏）
- [ ] 每个 Repository 提取后立即验证（逐个 commit，不等全部完成）

## 七、风险矩阵

| 风险 | 缓解措施 | 状态 |
|------|---------|------|
| 外部 API 被破坏 | 委托模式——方法签名不变 | ✅ 已处置 |
| 导入循环 | 新包从 database.py 导入 DatabaseManager？Repository **不**反向导入 DatabaseManager，仅依赖 aiosqlite.Connection | ⚠️ 实施时验证 |
| 测试 mock 失效 | 测试 mock DatabaseManager，底层委托透明 | ✅ 已处置 |
| `self._conn is None` 检查重复 | Repository 基类 `_base.py` 提供 `_ensure_conn()` 辅助方法，各 Repo 方法统一调用 | ✅ 设计中处置 |
| 跨 Repository 事务 | 所有 Repository 共享同一个 `aiosqlite.Connection` 引用；事务由 DatabaseManager 统一管理（`commit()`），Repository 不自行 `commit()` | ✅ 设计中处置 |

## 八、执行顺序

逐个 Repository 提取，每个完成后验证：

1. `_base.py` — Repository 基类 + `_ensure_conn()` 辅助
2. `conversation_repo.py` — 对话日志（8 方法，低风险，先试水）
3. `emotion_repo.py` — 情绪快照（6 方法）
4. `episodic_memory_repo.py` — 情景记忆（12 方法）
5. `profile_repo.py` — 用户画像（8 方法）
6. `notebook_repo.py` — 笔记本+任务（12 方法）
7. `analytics_repo.py` — 画像分析数据源（7 方法）
8. `database.py` — DatabaseManager 全部委托完成

## 九、不纳入本次的范围

- `forget_user_data` 跨表操作 → 保留在 DatabaseManager
- 调用方接口迁移（`_db.insert_log()` → `_db.conv.insert_log()`）→ 后续迭代
- `_manual_init` / `_try_alembic_migrate` 生命周期 → 保留
- 构建脚本/测试文件修改 → 无需修改
