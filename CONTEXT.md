# 昔涟 V3.2 · 代码导航

> 📍 告诉新 AI 哪个文件做什么、数据怎么流、有什么约定。
> ⚠️ 不要在对话里粘贴代码，告诉 AI 文件路径让它自己 read。
> 📅 最后更新：2026-05-13（阶段 3 完成）

---

## 目录树

```
xilian-v3/
├── main.py                          # 启动入口：加载环境 → Agent → Gateway → 并发启动
├── pyproject.toml                   # uv 项目配置 + 依赖
├── docker-compose.yml               # ChromaDB 容器
├── .env                             # API Key（不入 git）
│
├── packages/shared/                 # 🔗 共享层（被 agent 和 gateway 共同依赖）
│   ├── events.py                    # InternalEvent dataclass
│   ├── model_router.py              # ModelRouter：混合路由核心（~140行）
│   ├── database.py                  # DatabaseManager：SQLite（3张表：conversation_logs / episodic_memories / message_queue）
│   ├── backup.py                    # BackupManager：每日备份 + 清理 + 恢复（阶段 3）
│   └── logging_config.py            # loguru 结构化日志配置
│
├── packages/agent/                  # 🧠 Agent 核心引擎
│   ├── agent_core.py                # AgentCore：ActorMind 推理链 + 记忆管道 + shutdown
│   ├── agent_context.py             # AgentContext：对话历史 + 情绪快照 + 记忆注入
│   ├── tool_registry.py             # ToolRegistry：@register_tool 装饰器注册表
│   ├── emotion_analyzer.py          # EmotionAnalyzer：DeepSeek 11维情感分析
│   └── memory_manager.py            # MemoryManager：情景记忆编码/检索/调度/容量管理（阶段 3）
│
├── gateway/                         # 🚪 消息网关
│   ├── gateway.py                   # Gateway：通道管理 + Agent 路由
│   ├── security.py                  # SecurityFilter：白名单 + 熔断 + 频率限制
│   ├── channels/
│   │   ├── base.py                  # Channel 抽象基类
│   │   ├── console_channel.py       # ConsoleChannel：终端交互
│   │   └── http_channel.py          # HTTPChannel：FastAPI SSE API
│   └── mcp/
│       └── adapter.py               # MCPAdapter：接口签名预埋（阶段7实现）
│
├── prompts/                         # 📝 人格提示词（Git 版本管理）
│   ├── personality_v2.md            # 当前活跃版本（v2 精简版 ~1800字）
│   ├── personality_v1.md            # v1 原始版（保留对比）
│   └── CHANGELOG.md                 # 提示词变更记录
│
├── packages/frontend/               # 🎨 前端（阶段 3 正式搭建）
│   ├── package.json                 # Vite + React + Zustand + framer-motion
│   ├── vite.config.ts               # Vite proxy /api → localhost:8000
│   ├── src/
│   │   ├── main.tsx / App.tsx       # 入口 + 根组件
│   │   ├── components/
│   │   │   ├── layout/              # IconStrip(40px↔120px) + MainLayout
│   │   │   ├── chat/                # ChatView + MessageBubble + MessageList + ChatInput (SSE)
│   │   │   ├── panels/              # SlidePanel + EmotionPanel + MemoryPanel + SettingsPanel
│   │   │   ├── EmotionGauge/        # Canvas 11维雷达图 + 图例 + 情绪历史线图
│   │   │   └── status/              # EncodingStatusBar（轮询编码状态）
│   │   ├── hooks/                   # useChat + useEmotionData
│   │   ├── stores/                  # Zustand: appStore + chatStore + emotionStore
│   │   ├── services/api.ts          # API 封装（fetch + SSE 流式）
│   │   ├── types/                   # chat.ts + emotion.ts + memory.ts
│   │   └── utils/radarMath.ts       # 雷达图数学工具
│
├── tests/                           # 🧪 测试
│   ├── test_console_channel.py
│   ├── test_http_channel.py
│   ├── test_heartbeat.py
│   ├── test_personality.py
│   ├── test_emotion_analyzer.py     # 阶段 2 新增
│   └── test_empathy_injection.py    # 阶段 2 新增
│
└── logs/                            # 📋 运行时日志（JSON 格式）
```

---

## 核心数据流

```
main.py 启动
  │
  ├─→ AgentCore.__init__()
  │     ├─ 加载 personality_v2.md → self._personality
  │     ├─ 初始化 ToolRegistry
  │     ├─ 初始化 AgentContext（对话历史容器）
  │     └─ 初始化 ModelRouter（读 .env TRANSITION_MODE）
  │
  ├─→ SecurityFilter(owner_id="hezi")
  │
  ├─→ Gateway(agent, security)
  │     ├─ 注册 ConsoleChannel → stdin/stdout
  │     └─ 注册 HTTPChannel → FastAPI :8000
  │
  └─→ gateway.start()
        └─ 两条通道并发 asyncio.gather
             │
             ├─ ConsoleChannel: stdin 读一行 → InternalEvent → agent.process() → 打印
             └─ HTTPChannel: POST /api/chat → InternalEvent → agent.process() → JSON/SSE

agent.process(event) 内部（阶段 3）：
  signal_new_message() → 暂停编码
  _perceive() → 意图/情绪简单检测
  _retrieve_memories() → bge-m3 向量化 → ChromaDB top-3 → 设置 memory_retrieval
  _inject_empathy() → 读上一轮 emotion_snapshot → 昔涟风格共情段落
  inject_memory_context() → 记忆检索结果 → 叙事性上下文
  _build_messages() → 系统提示（人格 + 记忆 + 共情）+ 历史 + 用户消息
  router.route("chat") → 模型调用 → 立即返回主回复
  _schedule_emotion_analysis() → fire-and-forget 后台任务
  _schedule_memory_encoding() → 三层调度（空闲30s/强制20轮/关闭兜底）
  _write_conversation_log() → SQLite 实际写入
  add_message() → 对话历史记录
```

---

## 关键模块职责

| 模块 | 单句职责 | 关键方法 |
|------|---------|---------|
| `events.py` | 全系统统一消息结构 | `InternalEvent(event_id, timestamp, source, user_id, payload, is_owner)` |
| `model_router.py` | 按任务类型自动选择模型 | `route(task_type, messages)`, `route_with_override()` |
| `database.py` | SQLite 3张表 + 完整CRUD | `init()`, `insert_log()`, `insert_episodic_memory()`, `queue_push/pop()` |
| `backup.py` | 每日凌晨3点备份+清理 | `run_backup()`, `cleanup_old()`, `verify_backup()`, `restore()` |
| `agent_core.py` | 昔涟的"大脑"，ActorMind + 记忆管道 | `process(event)`, `_retrieve_memories()`, `_schedule_memory_encoding()`, `shutdown()` |
| `agent_context.py` | 对话历史容器 + 情绪快照 + 记忆注入 | `add_message()`, `inject_emotion_context()`, `inject_memory_context()` |
| `memory_manager.py` | 情景记忆全管线：编码/检索/调度/容量 | `encode_memory()`, `retrieve_memories()`, `schedule_encoding()`, `manage_capacity()` |
| `emotion_analyzer.py` | 调用 DeepSeek V4-Pro 做 11 维情感分析 | `analyze(user_message)` |
| `tool_registry.py` | 装饰器注册工具 | `register_tool()`, `list_tools()` |
| `gateway.py` | 通道生命周期管理 | `register()`, `start()`, `stop()` |
| `security.py` | 白名单 + 紧急熔断 + 频率限制 | `filter(event)`, `emergency_stop()` |
| `http_channel.py` | FastAPI 应用，8个端点 + SSE | `/api/chat`, `/api/emotion`, `/api/status` 等 |

---

## 代码约定

1. **全异步**：所有 I/O 用 `async/await`，Gateway 和 Channel 都继承 `asyncio` 模式
2. **进程内调用**：不是微服务架构。Gateway → Agent → ModelRouter 都是 Python 函数调用，不走网络
3. **InternalEvent 解耦**：Gateway 产出 `InternalEvent`，Agent 消费 `InternalEvent`，两者通过 Gateway 桥接
4. **日志标准**：`logger.bind(trace_id=...).info("模块.动作", **kwargs)`，用 `.` 分隔日志层级
5. **错误处理**：模型不可用不崩溃，返回 `DEGRADED_REPLY` 友好提示
6. **流式响应**：`agent.process(event, stream=True)` 返回原始 stream 对象，调用方（HTTPChannel）负责 SSE 格式化
7. **测试**：`pytest` + `pytest-asyncio`，`asyncio_mode = "strict"`，测试文件放 `tests/`

---

## 当前已知 TODO / 空壳

| 位置 | 说明 | 填充阶段 |
|------|------|---------|
| `tool_registry` 实际工具 | 只有注册表，无具体工具实现 | 阶段 7 |
| `gateway/mcp/adapter.py` | 只有接口签名，空实现 | 阶段 7 |
| Redis | 所有异步通信目前进程内，Redis 推至阶段 6 | 阶段 6 |
| PAD 情感空间 / 情绪惯性 | 情绪模型升级 | 阶段 4 |
| 艾宾浩斯衰减 / 记忆压缩 | 记忆系统升级 | 阶段 5 |

## 下一步：阶段 4

PAD 情感空间 + 情绪惯性 + 生命节律。
详细计划见 `/home/hezi/projects/xilian_plan/xilian-v3.md`
