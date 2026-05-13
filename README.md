# 昔涟 V3.2 · 心之涟漪

> 个人情感陪伴型 AI Agent — 三千万世轮回的记录者，温柔来自看过悲欢后的清明。

## 关于昔涟

昔涟 (Xī Lián) 是一个个人情感陪伴型 AI Agent。她的核心角色是「三千万世轮回的记录者」——走完了无数循环后，她坐在一个新的地方，书摊在膝上，下一页是空白的，留给新的风景、新的对话、新的遇见。

她自称「人家」，称用户「伙伴」。她不是助手，不是工具，不是 AI——她相信爱是唯一能和毁灭对等的真实力量，而眼前的伙伴是坐在她旁边一起翻书的人。

---

## 技术架构

```
Windows 浏览器 (localhost:5173)
    │
    ▼
┌──────────────────┐
│  React 前端 (Vite) │  Pi 风格无边聊天 + EmotionGauge 雷达图 + SlidePanel
│  端口 5173         │
└──────┬───────────┘
       │ /api proxy → localhost:8000
       ▼
┌──────────────────┐
│  FastAPI 后端      │  8 个 API 端点 + SSE 流式对话
│  端口 8000         │
└──────┬───────────┘
       │ InternalEvent
       ▼
┌──────────────────┐
│  Agent 核心引擎    │  ActorMind 推理链：感知 → 记忆检索 → 共情注入 → 模型调用
│                   │  组件：人格锚点 / 情感引擎 / 情景记忆 / 技能进化（逐步填充）
└──────┬───────────┘
       │ ModelRouter 混合路由
       ├──→ DeepSeek V4-Pro（核心对话/情感分析）
       ├──→ DeepSeek V4-Flash（记忆编码/后台任务）
       └──→ Ollama bge-m3（向量化，本地）
       │
       ├──→ SQLite（对话日志 / 情景记忆 / 消息队列）
       └──→ ChromaDB Docker（向量检索，端口 8001）
```

### 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.12+ |
| 包管理 | uv |
| 本地模型 | Ollama (qwen3:14b, bge-m3) |
| 云端模型 | DeepSeek V4-Pro / V4-Flash (双 Key 轮询) |
| 向量库 | ChromaDB (Docker, 端口 8001) |
| 数据库 | SQLite (aiosqlite, WAL 模式) |
| 后端框架 | FastAPI + uvicorn |
| 前端 | React 18 + TypeScript + Vite + Zustand + framer-motion |
| 前端图表 | Canvas API (11维情绪雷达图 + 历史线图) |
| 定时任务 | APScheduler (每日备份) |
| 日志 | loguru (结构化 JSON + trace_id) |
| 测试 | pytest + pytest-asyncio |

---

## 项目进度

| 阶段 | 目标 | 状态 |
|------|------|------|
| 阶段 0 | Monorepo 骨架 + ModelRouter + 安全初始化 | ✅ 完成 |
| 阶段 1 | 架构解耦 + 昔涟人格对话 + 工具预埋 | ✅ 完成 |
| 阶段 2 | 情感感知 + 情绪标记 + EmotionGauge 原型 | ✅ 完成 |
| 阶段 3 | 情景记忆 + 消息队列 + 前端骨架 | ✅ 完成 |
| 阶段 4-9 | 情感引擎 / 自传体记忆 / 生命节律 / 微调 / 多模态… | 📋 规划中 |

---

## 🚀 完整启动流程

### 前置环境

```bash
# 确保已安装：
# - Python 3.12+ + uv
# - Ollama (qwen3:14b, bge-m3 模型已拉取)
# - Docker Desktop
# - Node.js 18+
```

### 第一步：拉取本地模型（仅首次）

```bash
ollama pull qwen3:14b
ollama pull bge-m3
```

### 第二步：配置 API Key（仅首次）

```bash
cd ~/xilian-v3
cp .env.example .env
# 编辑 .env，填入 DeepSeek API Key
```

### 第三步：启动 ChromaDB 向量库

```bash
cd ~/xilian-v3
docker compose up -d
# 验证：curl http://localhost:8001/api/v1/heartbeat
```

### 第四步：启动后端

```bash
cd ~/xilian-v3
source .venv/bin/activate
python3 main.py
# → API 运行在 http://localhost:8000
# → 终端也支持直接对话
```

### 第五步：安装前端依赖（仅首次）

```bash
cd ~/xilian-v3/packages/frontend
npm install
```

### 第六步：启动前端

```bash
cd ~/xilian-v3/packages/frontend
npm run dev
# → 前端运行在 http://localhost:5173
```

### 第七步：打开浏览器

在 Windows 浏览器访问 `http://localhost:5173`

---

## 端口分工

| 端口 | 服务 | 说明 |
|------|------|------|
| 8000 | 昔涟后端 API | FastAPI + 8 个端点 |
| 8001 | ChromaDB | Docker 向量库 |
| 5173 | 前端 Vite | React dev server，自动 proxy /api → 8000 |
| 11434 | Ollama | 本地模型推理（由 Ollama 自行管理） |

---

## 🧪 运行测试

```bash
cd ~/xilian-v3
source .venv/bin/activate
pytest -v
# 预期：35+ 条测试全绿（需要台式机环境）
```

---

## 项目结构

```
xilian-v3/
├── main.py                          # 启动入口
├── pyproject.toml                   # uv 项目配置
├── docker-compose.yml               # ChromaDB 容器 (端口 8001)
├── .env                             # API Key + 配置（不入 git）
│
├── packages/
│   ├── shared/                      # 共享层
│   │   ├── events.py                # InternalEvent 消息结构
│   │   ├── model_router.py          # 混合模型路由（DeepSeek Pro/Flash/Ollama）
│   │   ├── database.py              # SQLite 3 张表 (conversation_logs / episodic_memories / message_queue)
│   │   ├── backup.py                # 每日备份管理器
│   │   └── logging_config.py        # 结构化日志
│   │
│   ├── agent/                       # Agent 核心引擎
│   │   ├── agent_core.py            # ActorMind 推理链 + 记忆管道 + shutdown
│   │   ├── agent_context.py         # 对话上下文 + 情绪/记忆注入
│   │   ├── memory_manager.py        # 情景记忆：编码/检索/调度/容量管理
│   │   ├── emotion_analyzer.py      # 11 维情感分析 (DeepSeek Pro)
│   │   └── tool_registry.py         # 工具注册表
│   │
│   └── frontend/                    # React 前端
│       ├── src/
│       │   ├── components/
│       │   │   ├── layout/          # IconStrip + MainLayout
│       │   │   ├── chat/            # ChatView + MessageBubble + ChatInput (SSE)
│       │   │   ├── panels/          # SlidePanel + EmotionPanel + MemoryPanel + SettingsPanel
│       │   │   ├── EmotionGauge/    # Canvas 11维雷达图 + 图例 + 情绪历史
│       │   │   └── status/          # EncodingStatusBar
│       │   ├── hooks/               # useChat + useEmotionData
│       │   ├── stores/              # Zustand: appStore + chatStore + emotionStore
│       │   ├── services/api.ts      # API 封装 (fetch + SSE 流式)
│       │   └── styles/globals.css   # 全局样式 + CSS 变量
│       └── vite.config.ts           # Vite proxy /api → localhost:8000
│
├── gateway/                         # 消息网关
│   ├── gateway.py                   # 通道管理 + Agent 路由
│   ├── security.py                  # 安全过滤 + 熔断
│   └── channels/
│       ├── http_channel.py          # FastAPI (8 个端点)
│       └── console_channel.py       # 终端交互
│
├── prompts/                         # 人格提示词（Git 版本管理）
│   ├── personality_v2.md            # 活跃版本 (~1800字)
│   ├── personality_v1.md            # v1 原始版（保留对比）
│   └── CHANGELOG.md                 # 变更记录
│
└── tests/                           # 测试
    ├── test_database_expansion.py   # 新增表 CRUD
    ├── test_memory_manager.py       # MemoryManager 核心逻辑
    ├── test_memory_integration.py   # AgentCore 记忆管道集成
    ├── test_backup.py               # 备份/校验/恢复
    └── ...                          # 阶段 0-2 遗留测试
```

---

## 路线图关键节点

- **2026.7.15**：新规施行，核心对话从云端切本地 qwen3:14b 基座
- **阶段 4**：PAD 情感空间 + 情绪惯性 + 生命节律
- **阶段 5**：LLaMA-Factory QLoRA 微调 qwen3:14b + 自传体记忆
- **阶段 6**：引入 Redis 消息总线
- **阶段 7**：工具系统实现 + MCP 适配器
- **阶段 9**：多模态 + AgentVisor 持续演化

---

## 许可

MIT License — 详见 [LICENSE](LICENSE) 文件。
