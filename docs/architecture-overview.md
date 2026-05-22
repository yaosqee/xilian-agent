# 昔涟 V3.3 · 系统架构总览

版本: 2026-05-22

---

本文档是四大子系统的顶层串联。阅读完本文后，可按需要深入：
- [记忆系统架构](design/memory-system-architecture.md)
- [情感系统架构](design/emotion-system-architecture.md)
- [工具系统架构](design/tool-system-architecture.md)
- **上下文管理 + 前缀缓存优化**（v4 新增）：滑动窗口 + Flash 压缩 + 启动恢复 + APPEND-ONLY LOG + 阈值门控缓存

## 一、系统全景

```
                          ┌─────────────────────┐
                          │     用户 (伙伴)       │
                          └─────────┬───────────┘
                                    │ HTTP/SSE
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Gateway (FastAPI)                            │
│  /api/chat  /api/chat/stream  /api/greeting  /api/notebook/*  ...  │
└─────────────────────────────┬───────────────────────────────────────┘
                              │ InternalEvent
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                         AgentCore.process()                         │
│                                                                     │
│  1. _perceive()      → 安全过滤 + Intent 感知                      │
│  2. _retrieve_memories() → 语义检索 + 角色记忆分流                  │
│  3. ContextBuilder   → 8 个 Module 组装上下文                       │
│  4. ModelRouter      → LLM 调用 (Pro/Flash)                        │
│  5. _handle_tool_calls() → 工具执行 + 结果包装                      │
│  6. EmotionEngine    → PAD 情绪更新                                 │
│  7. MemoryManager    → 情景记忆编码                                 │
│  8. NotebookManager  → 自动笔记                                     │
│  9. _update_affection() → 好感度更新                                │
│                                                                     │
└──┬──────────┬──────────┬──────────┬──────────┬─────────────────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐
│ 记忆  │ │ 情感  │ │ 工具  │ │ 笔记  │ │  好感度  │
│ 系统  │ │ 系统  │ │ 系统  │ │ 系统  │ │  系统    │
└──────┘ └──────┘ └──────┘ └──────┘ └──────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     SQLite (WAL) + sqlite-vec                       │
│  13 tables + 1 vec0 virtual table                                   │
└─────────────────────────────────────────────────────────────────────┘
```

## 二、一次完整的对话请求

以下 trace 展示了用户消息"今天好累啊……"从到达 Gateway 到 Agent 回复的完整路径：

```
1. Gateway 接收 POST /api/chat {"message":"今天好累啊……","user_id":"hezi"}
   └→ SecurityFilter.filter() ✓ owner

2. AgentCore.process(event)
   │
   ├─ _perceive() → intent {emotion_hint: "negative"}
   │
   ├─ _retrieve_memories("今天好累啊……")
   │   └→ MemoryManager.retrieve_memories()
   │       ├── embed(query) → bge-m3 1024维
   │       ├── vec search → top-20
   │       ├── 距离过滤 + 艾宾浩斯衰减 → top-3
   │       └── 关键词检查: 无角色关键词 → character_memory_retrieval=None
   │
   ├─ ContextBuilder.build() (按 priority):
   │   ├── DatetimeModule (1) → "现在是星期二的晚上。"
   │   ├── PortraitModule (3) → 版本号未变 → 跳过 (缓存命中)
   │   ├── EmotionModule (4) → snap为None(首条消息) → ""
   │   ├── MemoryModule (5) → "上一次你们聊到了「...」"
   │   ├── NotebookModule (6) → async: get_recent_notes(3) → "盒子喜欢小说/游戏/听歌"
   │   ├── AffectionModule (7) → level=1 → "昔涟才刚开始认识伙伴呢"
   │   └── NotebookTaskModule (8) → async: get_pending_tasks() → []
   │
   ├─ _build_messages():
   │   [system: personality_v4.1]
   │   [history...]
   │   [user: "（昔涟翻到书里几页——...）（昔涟感觉到——...）\n\n---\n\n今天好累啊……"]
   │
   ├─ ModelRouter.route("chat", messages, tools=[search_memory, query_weather, search_web, coding_delegate])
   │   └→ DS V4-Pro → "嗯……人家听到了。就在这里陪你一会儿吧。"
   │
   ├─ _clean_reply() → "嗯……人家听到了。就在这里陪你一会儿吧。"
   │
   ├─ (async) EmotionEngine.process_message("今天好累啊……")
   │   └→ AppraisalExtractor → PADMapper → EmotionState.update()
   │       └→ PAD: (0.05, -0.12, 0.08) → primary: "疲惫"
   │
   ├─ (async) MemoryManager.schedule_encoding()
   │   └→ 等待 120s idle → 编码为情景记忆
   │
   ├─ (async) NotebookManager.auto_note_after_message()
   │   └→ Flash 判断 → "PASS" (无具体信息)
   │
   └─ _update_affection() → score +0.5

3. Gateway 返回 {"reply": "嗯……人家听到了。就在这里陪你一会儿吧。"}
```

## 三、三大子系统协同矩阵

| 读 ↓ / 写 → | 记忆 | 情感 | 工具 | 笔记 | 好感度 |
|-------------|------|------|------|------|--------|
| **记忆** | 自写 | 不读写 | 读(episodic) | 不读写 | 不读写 |
| **情感** | 写(emotion_snapshot) | 自写 | 不读写 | 不读写 | 写(affection 输入) |
| **工具** | 写(trigger_memory) | 不读写 | 自写 | 不读写 | 不读写 |
| **笔记** | 不读写 | 不读写 | 不读写 | 自写 | 不读写 |
| **好感度** | 不读写 | 读(pad_profile) | 不读写 | 不读写 | 自写 |
| **肖像** | 读(episodic) | 不读写 | 读(trigger_portrait) | 读(notes) | 不读写 |
| **自传** | 读(当日,排除character) | 读(emotion轨迹) | 不读写 | 不读写 | 不读写 |

关键数据流：
- **记忆 → 肖像**：每日读取最近 50 条记忆作为印象重写素材
- **记忆 → 自传**：每日读取当日记忆写生命故事
- **情感 → 好感度**：积极情绪加速好感增长，红线扣减
- **工具 → 记忆**：反映用户偏好的工具调用触发记忆编码
- **笔记 → 肖像**：笔记本条目作为印象重写的补充素材

## 四、ContextBuilder 注入管线

7 个 Module 按 priority 排序，每个有独立的 budget (token)：

```
Priority 1  DatetimeModule      (50 tokens)    → "现在是星期五的下午。"（仅时段，不含分钟）
Priority 3  PortraitModule      (300 tokens)   → 昔涟对伙伴的印象（版本门控）
Priority 4  EmotionModule       (300 tokens)   → "伙伴的心情: 平静"（阈值门控，情绪不变时复用缓存）
Priority 5  MemoryModule        (300 tokens)   → 用户记忆 + 角色记忆双源（压缩时 top-k 加倍）
Priority 6  NotebookModule      (200 tokens)   → 笔记本最近条目（async）
Priority 7  AffectionModule     (150 tokens)   → 好感度话术引导
Priority 8  NotebookTaskModule  (100 tokens)   → 待办任务列表（async）
```

**总 budget**: 800 tokens 上限。每个 Module 独立渲染，超过 budget 截断。

**前缀缓存优化（v4）**：
- P0：ctx_notes 作为独立 system 消息放在 history 之后、user 之前（APPEND-ONLY LOG 模式）。history 中每条消息存储原始内容，跨轮字节稳定
- P1：EmotionModule/DatetimeModule 阈值门控 + 降精度，减少 ctx_notes 自身缓存抖动
- 预期效果：cache hit rate 从 ~60% 提升至 ~85%+

**版本门控**：PortraitModule 检查 `_current_portrait_version != _portrait_version_injected`，版本未变时跳过注入——利用 LLM 前缀缓存。

## 五、数据持久化总览

| 存储位置 | 包含数据 | 持久化 |
|----------|---------|--------|
| `data/xilian.db` | 全部 13 张表 | ✅ 磁盘 |
| `memories_vec` (vec0) | 情景记忆向量 | ✅ 磁盘（sqlite-vec 虚拟表） |
| `data/character_memories.json` | 角色记忆源文件 | ✅ 磁盘（Git 版本控制） |
| `EmotionState` (内存) | PAD 当前坐标 | ❌ 仅内存，重启从基线开始 |
| `AgentContext.history` | 对话历史 | ❌ 仅内存，启动从 DB 恢复 20 轮 |
| `_pending_greeting` | 待发送问候 | ❌ 仅内存 |
| `TokenBucket` | 频率控制令牌 | ❌ 仅内存 |

## 六、异步任务调度

```
asyncio event loop
  │
  ├── NudgeEngine tick     每 15min   → 检查是否该问候
  ├── TokenBucket refill   每 20min   → 补充频率令牌
  ├── AttentionScheduler   每 5s      → 检查是否有要提醒的事件
  ├── Memory encoding      对话后 idle 120s → 编码情景记忆
  ├── Portrait consolidate 每日 5:00   → 重写用户印象
  ├── Autobiography write  每日 23:00  → 写每日生命故事
  ├── Weekly reflection    每周日 4:30 → SAGE 四问
  ├── DB backup            每日 3:00   → 备份到 backups/
  └── DB cleanup           每日 3:30   → 清理 7 天前旧备份
```

---

*本文档随系统演进持续更新。最后修订：2026-05-22*

## 相关文档

- [记忆系统架构](design/memory-system-architecture.md)
- [情感系统架构](design/emotion-system-architecture.md)
- [工具系统架构](design/tool-system-architecture.md)
- [数据库 Schema](database-schema.md)
- [API 参考](api-reference.md)
- [提示词系统总览](prompts-overview.md)
- [部署运维指南](deployment.md)
