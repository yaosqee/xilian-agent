# 昔涟 V3.3 · 数据库 Schema

版本: 2026-05-20  
引擎: SQLite 3.45+ (WAL模式) + sqlite-vec 0.1.x  
路径: `data/xilian.db`

---

## 一、表全览

| # | 表名 | 用途 | 关键索引 | 数据量级 |
|---|------|------|----------|----------|
| 1 | `conversation_logs` | 对话日志（原始消息） | user_id, timestamp | ~100 |
| 2 | `episodic_memories` | 情景记忆（叙事+向量） | session_id, timestamp, importance | ~1000 |
| 3 | `memories_vec` | 记忆向量索引（vec0虚拟表） | embedding | =episodic |
| 4 | `message_queue` | 消息队列（异步任务） | — | ~10 |
| 5 | `emotion_snapshots` | PAD 情绪快照 | timestamp | ~1000 |
| 6 | `autobiography_entries` | 自传体（每日） | date | ~365 |
| 7 | `reflection_crystals` | 每周反思（SAGE） | week_start | ~52 |
| 8 | `autonomy_settings` | 自主系统配置 | — | 1 |
| 9 | `notebook_entries` | 笔记本（笔记+任务） | is_active, kind, created_at | ~50 |
| 10 | `scheduled_tasks` | 定时提醒任务 | status, due_at | ~20 |
| 11 | `audit_logs` | 审计日志（工具调用等） | timestamp, event_type | ~1000 |
| 12 | `affection_state` | 好感度记录 | — | ~200 |
| 13 | `user_portrait` | 用户印象文档 | version | ~30 |

---

## 二、各表详述

### 1. conversation_logs — 对话日志

```sql
CREATE TABLE conversation_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       REAL    NOT NULL,
    session_id      TEXT    NOT NULL,
    event_id        TEXT    NOT NULL,
    user_message    TEXT    NOT NULL,
    assistant_reply TEXT    NOT NULL,
    emotion_primary TEXT,
    emotion_intensity REAL,
    affection_score REAL,
    user_id         TEXT    DEFAULT 'hezi',
    source          TEXT    DEFAULT 'chat'
);
```

**用途**：记录每一轮对话的原始消息和回复。是系统最基础的持久化层。历史对话恢复时从此表读取。
**查询模式**：游标分页 `WHERE id < ? ORDER BY id DESC LIMIT ?`

---

### 2. episodic_memories — 情景记忆

```sql
CREATE TABLE episodic_memories (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp         REAL    NOT NULL,
    summary           TEXT    NOT NULL,          -- 叙事化摘要（~200字）
    raw_conversation  TEXT    NOT NULL,          -- 原始对话JSON
    emotion_tags      TEXT,                      -- JSON: 情绪/评价变量
    importance        REAL    DEFAULT 0.5,
    embedding_model   TEXT    DEFAULT 'bge-m3',
    embedding_version TEXT    DEFAULT 'v1',
    embedding_status  TEXT    DEFAULT 'pending',  -- pending → done
    access_count      INTEGER DEFAULT 0,
    last_accessed     REAL,
    session_id        TEXT    NOT NULL            -- 'character'=角色记忆
);
```

**用途**：存储叙事化后的情景记忆。通过 session_id 区分用户记忆和角色记忆。
**向量关联**：`id == memories_vec.rowid`（精确 1:1 对应）。
**查询模式**：按 session_id 过滤、按 importance 排序、按时间范围筛选。

---

### 3. memories_vec — 记忆向量索引

```sql
CREATE VIRTUAL TABLE memories_vec USING vec0(
    embedding float[1024]   -- bge-m3 嵌入向量
);
```

**用途**：sqlite-vec 虚拟表，存储 1024 维 bge-m3 嵌入向量。rowid 与 episodic_memories.id 精确对应。
**查询模式**：`SELECT rowid, distance FROM memories_vec WHERE embedding MATCH ? ORDER BY distance LIMIT ?`

---

### 4. emotion_snapshots — 情绪快照

```sql
CREATE TABLE emotion_snapshots (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           REAL    NOT NULL,
    primary_emotion     TEXT,
    primary_intensity   REAL,
    pad_p               REAL,     -- PAD愉悦 [-1,1]
    pad_a               REAL,     -- PAD唤醒 [-1,1]
    pad_d               REAL,     -- PAD支配 [-1,1]
    dimensions          TEXT,     -- JSON: 11维情绪分布
    appraisal_relevance REAL,
    appraisal_facilitation REAL,
    appraisal_coping    REAL,
    source              TEXT DEFAULT 'llm'
);
```

**用途**：每次对话后记录 PAD 情绪快照。用于前端 PAD 曲线、自传情绪轨迹、Nudge 情绪上下文。
**查询模式**：按时间范围筛选、按 timestamp DESC 取最近 N 条。

---

### 5. autobiography_entries — 自传体

```sql
CREATE TABLE autobiography_entries (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    date         TEXT    NOT NULL,  -- YYYY-MM-DD
    content      TEXT    NOT NULL,  -- 自传全文
    mood_summary TEXT,              -- 情绪基调（如"偏平静"）
    key_memories TEXT,              -- 素材记忆ID列表（逗号分隔）
    word_count   INTEGER DEFAULT 0
);
```

**查询**：按 date 精确查询，按 date DESC 获取列表。

---

### 6. reflection_crystals — 每周反思

```sql
CREATE TABLE reflection_crystals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start  TEXT    NOT NULL,  -- YYYY-MM-DD（周一）
    week_end    TEXT    NOT NULL,  -- YYYY-MM-DD（周日）
    learned     TEXT,              -- S: 学会
    surprised   TEXT,              -- A: 意外
    grateful    TEXT,              -- G: 感激
    remember    TEXT,              -- E: 记住
    raw_prompt  TEXT               -- 写作素材摘要
);
```

---

### 7. notebook_entries — 笔记本

```sql
CREATE TABLE notebook_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT    NOT NULL,    -- 'note' / 'task'
    content     TEXT    NOT NULL,    -- 笔记内容
    tags        TEXT,                -- JSON数组
    importance  REAL    DEFAULT 0.5,
    is_active   INTEGER DEFAULT 1,  -- 0=软删除/完成
    due_date    REAL,                -- 解析后的绝对时间戳（可NULL）
    created_at  REAL    NOT NULL,
    session_id  TEXT    NOT NULL
);
```

**due_date**：写入时从内容中提取相对时间（如"下周五"）并解析为绝对时间戳。NULL 表示无时间信息。
**查询**：`WHERE is_active=1 ORDER BY created_at DESC`

---

### 8. scheduled_tasks — 定时任务

```sql
CREATE TABLE scheduled_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    details     TEXT,
    priority    INTEGER DEFAULT 0,
    status      TEXT    DEFAULT 'pending',  -- pending/done/cancelled
    due_at      REAL,
    created_at  REAL    NOT NULL,
    completed_at REAL,
    session_id  TEXT    NOT NULL
);
```

---

### 9. affection_state — 好感度

```sql
CREATE TABLE affection_state (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           REAL    NOT NULL,
    score               REAL    NOT NULL,  -- 0-100
    level               INTEGER NOT NULL,  -- 1-4
    total_conversations INTEGER DEFAULT 0,
    reason              TEXT,              -- 变化原因
    level_label         TEXT               -- 等级标签
);
```

**查询**：`ORDER BY id DESC LIMIT 1` 获取最新状态。

---

### 10. user_portrait — 用户印象文档

```sql
CREATE TABLE user_portrait (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  REAL    NOT NULL,
    version     INTEGER NOT NULL,
    content     TEXT    NOT NULL,
    source_ids  TEXT,              -- 素材记忆ID列表
    change_log  TEXT               -- 一句话说明本次更新
);
```

**版本号门控**：ContextBuilder 注入时检查版本号，未变更则跳过（利用 LLM 前缀缓存）。

---

### 11-13. 其余表

| 表 | 用途 |
|----|------|
| `message_queue` | 暂存待处理的异步消息 |
| `audit_logs` | 工具调用审计日志（timestamp, event_type, severity, detail） |
| `autonomy_settings` | 自主系统配置（greeting_threshold, dnd_start/end 等） |

---

## 三、关键查询模式

### 游标分页（conversation_logs）
```sql
SELECT * FROM conversation_logs
WHERE id < ?              -- before_id 游标
ORDER BY id DESC LIMIT ?  -- 向前翻页
```

### 语义检索（episodic_memories + vec0）
```sql
SELECT rowid, distance FROM memories_vec
WHERE embedding MATCH vec_f32(?)  -- 查询向量
ORDER BY distance LIMIT ?         -- top-K
```
然后按 rowid 回表查询 episodic_memories。

### 艾宾浩斯衰减（检索时应用层计算）
```
adjusted_score = distance / exp(-λ × days_since_access)
λ = 0.099  (7天半衰期)
```

---

## 四、迁移策略

- **首选**：`alembic upgrade head`（仅限默认路径 `data/xilian.db`）
- **降级**：`_manual_init()` 手动建表（幂等 CREATE IF NOT EXISTS）
- **增量**：`ALTER TABLE ... ADD COLUMN`（幂等 try/except，用于 notebook_entries.due_date 等后加字段）

---

*本文档随 Schema 变更持续更新。最后修订：2026-05-20*

## 相关文档

- [架构总览](architecture-overview.md)
- [记忆系统架构](design/memory-system-architecture.md)
- [API 参考](api-reference.md)
