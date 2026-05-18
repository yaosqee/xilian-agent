# 昔涟 V3.3 · 代码导航

> 📍 告诉新 AI 哪个文件做什么、数据怎么流、有什么约定。
> ⚠️ 不要在对话里粘贴代码，告诉 AI 文件路径让它自己 read。
> 📅 最后更新：2026-05-18（工具系统重构：LLM function calling + 4工具 + 确认回路 + 记忆联动）

---

## 目录树

```
xilian-v3/
├── main.py                          # 启动入口：加载环境 → Agent → Gateway → cron调度 → 前端挂载 → 并发启动
├── pyproject.toml                   # uv 项目配置 + 依赖
├── CLAUDE.md                        # Agent skills 配置（GitHub Issues/标签/领域文档）
├── PROJECT_PROGRESS.md              # 项目仪表盘
├── CONTEXT.md                       # 代码导航（本文件）
├── README.md                        # 项目门面
├── .env                             # API Key（不入 git）
├── photo/                           # 背景图片（xilian.png默认+fengge.txt风格参考+上传存储）
├── docs/agents/                     # Agent skills 配置（issue-tracker/triage-labels/domain）
│
├── packages/shared/                 # 🔗 共享层（被 agent 和 gateway 共同依赖）
│   ├── events.py                    # InternalEvent dataclass
│   ├── model_router.py              # ModelRouter：纯云端路由核心（Pro双Key轮询 + Flash后台 + 工具降级）
│   ├── database.py                  # DatabaseManager：SQLite（11张表CRUD + 游标分页 + Alembic优先）
│   ├── vector_store.py              # VectorStore：sqlite-vec 向量检索（零外部依赖）
│   ├── backup.py                    # BackupManager：每日备份 + 清理 + 恢复（阶段 3）
│   ├── marker_parser.py             # MarkerParser：5种标记流式解析 + SSML接口（阶段7c）
│   └── logging_config.py            # loguru 结构化日志配置
│
├── packages/agent/                  # 🧠 Agent 核心引擎
│   ├── agent_core.py                # AgentCore：ActorMind + ContextBuilder + Marker管道 + LLM工具调用 + 确认回路 + 记忆联动
│   ├── agent_context.py             # AgentContext：对话历史 + 情绪快照 + 记忆注入
│   ├── tool_registry.py             # ToolRegistry：@register_tool 装饰器 + autodiscover + to_openai_tools()
│   ├── tool_executor.py             # ToolExecutor：校验→权限→频率→确认→执行→审计（打磨期）
│   ├── tool_result.py               # ToolResult + ToolContext dataclass（打磨期）
│   ├── result_wrapper.py            # ResultWrapper：工具结果→昔涟语言（规则模板 + LLM包装双轨，打磨期）
│   ├── context_builder.py           # ContextBuilder：模块化上下文（Datetime/Emotion/Memory/Notebook 4模块）
│   ├── notebook_manager.py          # NotebookManager：笔记/日记/关注/任务 + 自动记笔记（阶段7b）
│   ├── portrait_manager.py          # PortraitManager：用户印象文档定期重写 + mark_dirty（阶段8+）
│   ├── skills_loader.py             # SkillsLoader：Agent Skills 加载（阶段7d）
│   ├── emotion_analyzer.py          # EmotionAnalyzer：DeepSeek 11维情感分析（阶段2，被PAD增强）
│   ├── emotion_core.py              # EmotionEngine：PAD情感引擎（阶段4）
│   ├── memory_manager.py            # MemoryManager：情景记忆编码/检索/艾宾浩斯衰减/调度/容量管理（阶段3+5）
│   ├── autobiography_writer.py      # AutobiographyWriter + ReflectionWriter（阶段5）
│   ├── nudge_engine.py              # NudgeEngine + AttentionScheduler（阶段6+7c）
│   └── tools/
│       ├── __init__.py              # 工具包入口
│       ├── coding_delegate.py       # 编码委托（Claude Code CLI，EXECUTE，需确认）
│       ├── search_memory.py         # 记忆检索（利用 MemoryManager.retrieve_memories）
│       ├── query_weather.py         # 天气查询（和风天气 + Zhipu搜索fallback）
│       └── search_web.py            # 网络搜索（智谱 Web Search API）
│       └── coding_delegate.py       # Claude Code 编码委托（阶段7d）
│
├── gateway/                         # 🚪 消息网关
│   ├── gateway.py                   # Gateway：通道管理 + Agent 路由
│   ├── security.py                  # SecurityFilter：白名单 + 熔断 + 频率限制
│   ├── channels/
│   │   ├── base.py                  # Channel 抽象基类
│   │   ├── console_channel.py       # ConsoleChannel：终端交互（rich 美化）
│   │   └── http_channel.py          # HTTPChannel：FastAPI SSE API（~24个端点，含对话历史分页 + 用户印象）
│   └── mcp/
│       └── adapter.py               # MCPAdapter：接口签名预埋（阶段7实现）
│
├── prompts/                         # 📝 人格提示词（Git 版本管理）
│   ├── personality_v4.md            # 当前活跃版本（v4，短句分行+意象约束+情感调色盘）
│   ├── personality_v2.md            # v2 精简版（保留对比）
│   ├── personality_v1.md            # v1 原始版（保留对比）
│   ├── game-knowledge.md            # 昔涟游戏知识（崩坏3/原神/星铁等）
│   └── CHANGELOG.md                 # 提示词变更记录
│
├── packages/frontend/               # 🎨 前端（阶段 3 正式搭建，阶段 4-6 持续集成）
│   ├── package.json                 # Vite + React + Zustand + framer-motion
│   ├── vite.config.ts               # Vite proxy /api → localhost:8000
│   ├── dist/                        # Vite build 产物（生产模式 serve 用）
│   ├── src/
│   │   ├── main.tsx / App.tsx       # 入口 + 根组件
│   │   ├── components/
│   │   │   ├── layout/              # MainLayout + Sidebar(8入口SVG图标) + BackgroundLayer(全页背景)
│   │   │   ├── chat/                # ChatView + MessageBubble + Textarea毛玻璃输入
│   │   │   ├── panels/              # SlidePanel(absolute+SafePanel) + EmotionPanel + MemoryTimeline
│   │   │   │                       #   + AutobiographyPanel + NotebookPanel + AuditPanel
│   │   │   │                       #   + SkillsPanel + SettingsPanel(含背景上传) + PADTrajectory + PortraitPanel
│   │   │   ├── EmotionGauge/        # Canvas 11维雷达图(浅色) + 图例 + 情绪历史线图
│   │   │   ├── status/              # EncodingStatusBar（轮询编码状态）
│   │   │   └── AffectionBar.tsx     # 4级好感度/羁绊值指示器（阶段5）
│   │   ├── hooks/                   # useChat + useEmotionData
│   │   ├── stores/                  # Zustand: appStore + chatStore + emotionStore + autonomyStore + notebookStore + affectionStore
│   │   ├── services/api.ts          # API 封装（fetch + SSE 流式，含 autonomy + notebook + portrait 端点）
│   │   ├── types/                   # chat.ts + emotion.ts + memory.ts + autonomy.ts + voice.ts
│   │   ├── styles/                  # globals.css（含 thinking 动画） + theme.css（品牌视觉：樱花粉系）
│   │   ├── utils/                   # radarMath.ts + markers.ts（标记提取 + triggerAction）
│   └── emotion-gauge/               # 阶段2 独立原型（保留）
│
├── skills/                          # 🛠️ Agent Skills（阶段7d）
│   └── manual/
│       └── weather_query.md         # 示例技能：天气查询
│
├── alembic/                         # 🗄️ 数据库迁移（阶段7d）
│   ├── alembic.ini
│   ├── env.py
│   └── versions/
│       ├── 001_initial.py           # 9 表全量 schema（阶段7d）
│       ├── 002_audit_logs.py        # 审计日志表（阶段8）
│       └── 003_affection.py         # 好感度状态表（打磨期）
│
├── packages/voice/                  # 🎤 语音管道（阶段7e 接口占位）
│   ├── __init__.py
│   └── README.md                    # 语音管道规划说明
│
├── scripts/                         # 🛠️ 部署脚本（阶段6）
│   ├── setup.sh                     # 一键安装：环境检查 + uv sync + npm install + .env引导
│   └── start.sh                     # 一键启动：构建检查 + uv run python main.py
│
├── tests/                           # 🧪 测试
│   ├── test_console_channel.py
│   ├── test_http_channel.py
│   ├── test_heartbeat.py
│   ├── test_personality.py
│   ├── test_personality_regression.py   # 阶段5：20条人设回归
│   ├── test_emotion_analyzer.py         # 阶段2
│   ├── test_empathy_injection.py        # 阶段2
│   ├── test_emotion_core.py             # 阶段4：PAD引擎单元测试
│   ├── test_emotion_appraisal.py        # 阶段4：评价提取测试
│   ├── test_memory_manager.py           # 阶段3
│   ├── test_memory_integration.py       # 阶段3
│   ├── test_backup.py                   # 阶段3
│   ├── test_database_expansion.py       # 阶段3
│   ├── test_biography.py                # 阶段5：自传体+反思
│   ├── test_forgetting.py               # 阶段5：艾宾浩斯衰减
│   └── test_nudge_engine.py             # 阶段6：自主问候
│
└── logs/                            # 📋 运行时日志（JSON 格式）
```

---

## 核心数据流

```
main.py 启动
  │
  ├─→ AgentCore.__init__()
  │     ├─ 加载 personality_v3.md → self._personality
  │     ├─ 初始化 ToolRegistry + 注册 coding_delegate
  │     ├─ 初始化 AgentContext（对话历史容器）
  │     ├─ 初始化 ContextBuilder（Datetime/Portrait/Emotion/Memory/Notebook 5模块）
  │     ├─ 初始化 ModelRouter（纯云端 DeepSeek Pro双Key + Flash + 工具降级）
  │     ├─ 初始化 EmotionEngine（PAD 情感引擎，常驻内存）
  │     ├─ 初始化 MemoryManager（sqlite-vec 向量检索）
  │     └─ 初始化 NudgeEngine（TokenBucket + 想念值 + 自主问候）
  │
  ├─→ SecurityFilter(owner_id="hezi")
  │
  ├─→ Gateway(agent, security)
  │     ├─ 注册 ConsoleChannel → stdin/stdout（rich 美化）
  │     └─ 注册 HTTPChannel → FastAPI :8000
  │
  ├─→ APScheduler 定时任务
  │     ├─ 3:00   daily_backup
  │     ├─ 4:00   daily_autobiography（阶段5）
  │     ├─ 4:30   weekly_reflection（阶段5，仅周日）
  │     ├─ */15   proactive_check（阶段6：想念值检查）
  │     ├─ */20   token_bucket_refill（阶段6）
  │     ├─ 23:50  notebook_daily_diary（阶段7b：每日日记）
  │     └─ 8/12/18 check_due_tasks → AttentionScheduler（阶段7b+7c）
  │
  ├─→ AttentionScheduler（asyncio Task，阶段7c）
  │     5s tick → PriorityQueue → 防打扰 → Flash 决策
  │
  └─→ gateway.start()
        └─ 两条通道并发 asyncio.gather
             │
             ├─ ConsoleChannel: stdin 读一行 → InternalEvent → agent.process() → rich 打印
             └─ HTTPChannel: POST /api/chat → InternalEvent → agent.process() → JSON/SSE

agent.process(event) 内部（阶段 7 + 打磨期）：
  _perceive() → 情绪基调检测
  _retrieve_memories() → sqlite-vec 向量化 → top-3 + 艾宾浩斯衰减权重
  _build_messages() → ContextBuilder 自然语言上下文组装（5模块：DateTime/Portrait/Emotion/Memory/Notebook）
  router.route("chat", tools=[...]) → LLM function calling 工具选择 →
    ├─ 文本回复 → MarkerParser 后处理 → 返回
    └─ tool_calls → ToolExecutor.execute() → ResultWrapper.wrap() → 回传 LLM → 最终回复
       └─ _process_tool_side_effects() → trigger_memory/trigger_portrait
  _schedule_emotion_analysis() → fire-and-forget 后台 PAD 更新
  _schedule_memory_encoding() → 三层调度
  _write_conversation_log() → SQLite 写入
  auto_note_after_message() → Flash 自动判断是否记笔记
  add_message() → 对话历史

NudgeEngine 自主问候流程（阶段 6）：
  APScheduler 每15分钟 → proactive_check()
    → 计算想念值（base × urgency × significance × time_mod）
    → ≤ 阈值 → 静默
    → > 阈值 + TokenBucket 可用 → DS Pro 生成温柔问候
    → 写入 pending_greetings → 等待前端轮询投递
```

---

## 关键模块职责

| 模块 | 单句职责 | 关键方法 |
|------|---------|---------|
| `events.py` | 全系统统一消息结构 | `InternalEvent(event_id, timestamp, source, user_id, payload, is_owner)` |
| `model_router.py` | 纯云端 DeepSeek 路由（Pro双Key + Flash + 工具降级） | `route(task_type, messages, tools, tool_choice)` |
| `database.py` | SQLite 11张表 + 完整CRUD + Alembic优先 | `init()`, `insert_notebook()`, `insert_task()`, `get_due_tasks()` 等 |
| `vector_store.py` | sqlite-vec 向量插入 + 精确检索 | `insert(row_id, embedding)`, `search(query_vec, top_k)` |
| `backup.py` | 每日备份+清理+恢复 | `run_backup()`, `cleanup_old()`, `verify_backup()`, `restore()` |
| `agent_core.py` | 昔涟的"大脑"，ActorMind + 全管线调度 + 破冰追踪 + 印象冷启动 | `process(event)`, `_retrieve_memories()`, `_inject_empathy_pad()`, `consume_icebreaker_greeting()`, `_tick_icebreaker()`, `get_time_greeting()`, `shutdown()` |
| `agent_context.py` | 对话历史容器 + 情绪快照 + 记忆注入 | `add_message()`, `inject_emotion_context()`, `inject_memory_context()` |
| `emotion_core.py` | PAD 情感引擎：评价→PAD→惯性衰减→情绪标签 | `AppraisalExtractor.analyze()`, `EmotionState.update()`, `PersonalityModulator.modulate()`, `pad_to_emotion_profile()` |
| `memory_manager.py` | 情景记忆全管线：编码/检索/艾宾浩斯衰减/调度/容量 | `encode_memory()`, `retrieve_memories()`, `schedule_encoding()`, `manage_capacity()` |
| `autobiography_writer.py` | 每日自传体 + 每周反思结晶 | `write_daily()`, `reflect_weekly()` |
| `portrait_manager.py` | 用户印象文档定期重写 + 破冰主动问候 + 冷启动 | `consolidate()`, `ensure_exists()` |
| `context_builder.py` | 模块化上下文组装（5模块 自然语言段落 + 优先级+预算，build() async） | `ContextBuilder.register()`, `build()` |
| `notebook_manager.py` | 笔记/日记/关注/任务 + 自动记笔记 | `add_note()`, `generate_daily_diary()`, `auto_note_after_message()` |
| `skills_loader.py` | Agent Skills 加载 + 质量双门控 | `load_all()`, `match()` |
| `marker_parser.py` | 5种标记流式解析 + SSML接口 | `MarkerParser.feed()`, `flush()` |
| `tool_registry.py` | 装饰器注册 + autodiscover + OpenAI tools 格式 | `register_tool()`, `autodiscover()`, `to_openai_tools()` |
| `tool_executor.py` | 工具执行调度：校验→权限→频率→确认→审计 | `execute()`, `_check_rate_limit()` |
| `tool_result.py` | 统一工具返回格式 + 副作用标记 | `ToolResult.ok()`, `ToolResult.fail()` |
| `result_wrapper.py` | 工具结果→昔涟语言（规则模板+LLM包装双轨） | `wrap()`, `_llm_wrap()` |
| `tools/coding_delegate.py` | 编码委托（Claude Code CLI，EXECUTE，需确认） | `coding_delegate()` |
| `tools/search_memory.py` | 记忆检索（MemoryManager） | `search_memory()` |
| `tools/query_weather.py` | 天气查询（和风天气 + 搜索fallback） | `query_weather()` |
| `tools/search_web.py` | 网络搜索（智谱 Web Search API） | `search_web()` |
| `nudge_engine.py` | 自主问候 + 注意力调度（AttentionScheduler） | `TokenBucket.consume()`, `MissingValueCalculator.compute()`, `GreetingGenerator.generate()`, `AutonomyConfig` |
| `gateway.py` | 通道生命周期管理 | `register()`, `start()`, `stop()` |
| `security.py` | 白名单 + 紧急熔断 + 频率限制 | `filter(event)`, `emergency_stop()` |
| `http_channel.py` | FastAPI 应用, ~26个端点 + SSE | `/api/chat`, `/api/emotion`, `/api/notebook/*` 等 |

---

## 代码约定

1. **全异步**：所有 I/O 用 `async/await`，Gateway 和 Channel 都继承 `asyncio` 模式
2. **进程内调用**：不是微服务架构。Gateway → Agent → ModelRouter 都是 Python 函数调用，不走网络
3. **InternalEvent 解耦**：Gateway 产出 `InternalEvent`，Agent 消费 `InternalEvent`，两者通过 Gateway 桥接
4. **日志标准**：`logger.bind(trace_id=...).info("模块.动作", **kwargs)`，用 `.` 分隔日志层级
5. **错误处理**：模型不可用不崩溃，返回 `DEGRADED_REPLY` 友好提示
6. **流式响应**：`agent.process(event, stream=True)` 返回原始 stream 对象，调用方（HTTPChannel）负责 SSE 格式化
7. **测试**：`pytest` + `pytest-asyncio`，`asyncio_mode = "strict"`，测试文件放 `tests/`
8. **部署**：`uv run python main.py` 一键启动，生产模式单进程 serve API + 前端

---

## 当前已知 TODO

| 位置 | 说明 |
|------|------|
| `packages/voice/` | 语音管道接口占位，阶段 9 完整实现 |
| `gateway/mcp/adapter.py` | MCP 适配器接口签名预埋 |
| `markers_to_ssml()` | SSML 转换完整实现 |
| 和风天气 API Key | 需在控制台激活对应 API 产品（当前使用 Zhipu 搜索 fallback） |

## 下一步

打磨期继续 — 工具系统运行观察与调优 + 前端体验打磨 + 记忆/情感精度持续提升。
工具系统已交付（LLM function calling 驱动 4 工具 + 确认回路 + 记忆/印象联动）。
