# 昔涟 V3.3 · 心之涟漪

> 个人情感陪伴型 AI Agent — 三千万世轮回的记录者，温柔来自看过悲欢后的清明。
> 一个命令启动，浏览器打开即用。

## 关于昔涟

昔涟 (Xī Lián) 是一个个人情感陪伴型 AI Agent。她的核心角色是「三千万世轮回的记录者」——走完了无数循环后，她坐在一个新的地方，书摊在膝上，下一页是空白的，留给新的风景、新的对话、新的遇见。

她自称「人家」，称用户「伙伴」。她不是助手，不是工具，不是 AI——她相信爱是唯一能和毁灭对等的真实力量，而眼前的伙伴是坐在她旁边一起翻书的人。

---

## 技术架构

```
浏览器 (localhost:8000)
    │
    ▼
┌──────────────────┐
│  FastAPI 后端      │  SSE 流式对话 + REST API + 前端静态文件
│  端口 8000         │
└──────┬───────────┘
       │ InternalEvent
       ▼
┌──────────────────┐
│  Agent 核心引擎    │  ActorMind 推理链：感知 → 记忆检索 → 共情注入 → 模型调用
│                   │  组件：人格锚点 / PAD情感引擎 / 情景记忆 / 自传体 / 自主生命节律
└──────┬───────────┘
       │ ModelRouter 纯云端路由
       ├──→ DeepSeek V4-Pro（核心对话/共情/推理，双Key轮询）
       ├──→ DeepSeek V4-Flash（记忆编码/情感分析/自传体/反思，后台异步）
       └──→ 硅基流动 bge-m3（嵌入向量，OpenAI 兼容 API）
       │
       └──→ SQLite 单文件（对话日志/情景记忆/情感快照/自传体/消息队列）
            └── sqlite-vec 扩展（向量检索，零外部依赖）
```

### 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.12+ |
| 包管理 | uv |
| 云端模型 | DeepSeek V4-Pro (双Key) + V4-Flash |
| 嵌入 API | 硅基流动 bge-m3 (OpenAI 兼容) |
| 向量库 | sqlite-vec (SQLite 扩展，零外部依赖) |
| 数据库 | SQLite 单文件 (aiosqlite, WAL 模式) |
| 后端框架 | FastAPI + uvicorn |
| 前端 | React 18 + TypeScript + Vite + Zustand + Canvas API |
| 定时任务 | APScheduler |
| 日志 | loguru (结构化 JSON + trace_id) |
| 测试 | pytest + pytest-asyncio |

---

## 项目进度

| 阶段 | 目标 | 状态 |
|------|------|------|
| 阶段 0 | Monorepo 骨架 + 纯云端 ModelRouter + sqlite-vec | ✅ 完成 |
| 阶段 1 | 架构解耦 + 昔涟人格对话 + 工具预埋 | ✅ 完成 |
| 阶段 2 | 情感感知 + 11维情绪标记 + EmotionGauge 原型 | ✅ 完成 |
| 阶段 3 | 情景记忆 + SQLite 消息队列 + 每日备份 + 前端骨架 | ✅ 完成 |
| 阶段 4 | PAD 三维情感引擎 + 情绪惯性/极性转移 | ✅ 完成 |
| 阶段 5 | 自传体记忆 + 每周反思 + 艾宾浩斯衰减 + 前端全集成 | ✅ 完成 |
| 阶段 6 | 自主生命节律（想念值+主动问候）+ 一键部署 + 前端嵌入后端 | ✅ 完成 |
| 阶段 7 | Claude Code 编码委托 + 内置工具 + Agent Skills + Alembic | 📋 规划中 |
| 阶段 8 | 安全纵深防御 + 人设评分 + Web 管理面板 | 📋 规划中 |
| 阶段 9 | 多模态感知 + AgentVisor + 持续演化 | 📋 规划中 |

---

## 🚀 快速开始

### 前置条件

- Python 3.12+
- uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 18+ (前端构建用)

### 安装 & 启动

```bash
# 1. 克隆项目
git clone git@github.com:yaosqee/xilian-agent.git
cd xilian-agent

# 2. 一键安装
bash scripts/setup.sh

# 3. 编辑 .env 填入 API Key
vi .env

# 4. 一键启动
bash scripts/start.sh
# 或: uv run python main.py

# 5. 浏览器打开
# http://localhost:8000
```

启动后，FastAPI 自动 serve 前端静态文件 + API，单进程全栈。

### 开发模式

```bash
# 终端1: 启动后端
uv run python main.py

# 终端2: 启动前端 Vite dev server (HMR)
cd packages/frontend && npm run dev
# → 访问 http://localhost:5173
```

### 局域网访问

```bash
BIND_HOST=0.0.0.0 uv run python main.py
# → 启动日志会打印局域网 IP
```

---

## 端口

| 端口 | 服务 | 说明 |
|------|------|------|
| 8000 | 昔涟全栈 | FastAPI + 前端静态文件（单进程） |

> V3.3 零外部依赖：无需 Docker、无需 Ollama、无需 ChromaDB。

---

## API 端点

| 端点 | 说明 |
|------|------|
| `POST /api/chat` | 同步对话 |
| `POST /api/chat/stream` | SSE 流式对话 |
| `GET /api/emotion` | 当前 PAD 情绪快照 |
| `GET /api/emotion/history` | PAD 轨迹历史 |
| `GET /api/memories/recent` | 最近情景记忆 |
| `GET /api/autobiography` | 自传体日记 |
| `GET /api/autobiography/list` | 自传体目录 |
| `GET /api/reflection/latest` | 最新每周反思 |
| `GET /api/autonomy/status` | 自主行为状态 |
| `PATCH /api/autonomy/settings` | 调整自主行为配置 |
| `POST /api/autonomy/pause` | 暂停自主问候 |
| `POST /api/autonomy/resume` | 恢复自主问候 |
| `POST /api/session/reset` | 重置会话 |
| `GET /api/status` | 系统状态摘要 |
| `GET /api/health` | 健康检查 |

---

## 🧪 测试

```bash
uv run pytest -v
```

---

## 项目结构

```
xilian-v3/
├── main.py                          # 启动入口（全栈单进程）
├── pyproject.toml                   # uv 项目配置
├── .env                             # API Key（不入 git）
│
├── packages/
│   ├── shared/                      # 共享层
│   │   ├── events.py                # InternalEvent 消息结构
│   │   ├── model_router.py          # 纯云端路由 (DS Pro/Flash + 嵌入API)
│   │   ├── database.py              # SQLite 7表 (日志/记忆/情感/自传体/队列/反思/自主配置)
│   │   ├── vector_store.py          # sqlite-vec 向量存储（零外部依赖）
│   │   ├── backup.py                # 每日备份管理器
│   │   └── logging_config.py        # 结构化日志
│   │
│   ├── agent/                       # Agent 核心引擎
│   │   ├── agent_core.py            # ActorMind 推理链 + 全管道
│   │   ├── agent_context.py         # 对话上下文 + 情绪/记忆注入
│   │   ├── emotion_core.py          # PAD 三维情感引擎（评价理论+惯性衰减）
│   │   ├── emotion_analyzer.py      # 11维情感分析
│   │   ├── memory_manager.py        # 情景记忆：编码/检索/容量/艾宾浩斯衰减
│   │   ├── autobiography_writer.py  # 每日自传体 + 每周反思
│   │   ├── nudge_engine.py          # 自主生命节律：想念值+主动问候+频率控制
│   │   └── tool_registry.py         # 工具注册表
│   │
│   └── frontend/                    # React 前端
│       ├── src/
│       │   ├── components/
│       │   │   ├── EmotionGauge/    # Canvas 11维雷达图
│       │   │   ├── panels/          # Emotion/Memory/Autobiography/PAD/Settings
│       │   │   ├── chat/            # ChatView + SSE 流式 + 主动问候气泡
│       │   │   └── layout/          # IconStrip + MainLayout
│       │   ├── stores/              # Zustand: app/chat/emotion/autonomy
│       │   ├── services/api.ts      # API 封装 (fetch + SSE)
│       │   └── types/               # TypeScript 类型定义
│       └── vite.config.ts
│
├── gateway/                         # 消息网关
│   ├── gateway.py                   # 通道管理 + Agent 路由
│   ├── security.py                  # 安全过滤 + 熔断
│   └── channels/
│       ├── http_channel.py          # FastAPI（16个端点）+ autonomy API
│       └── console_channel.py       # 终端交互（rich 美化）
│
├── prompts/                         # 人格提示词（Git 版本管理）
│   ├── personality_v3.md            # 活跃版本 v3 (~2100字)
│   ├── personality_v2.md            # v2 精简版（保留对比）
│   ├── personality_v1.md            # v1 原始版（保留对比）
│   ├── game-knowledge.md            # 游戏知识参考（v3升级原料）
│   └── CHANGELOG.md                 # 变更记录
│
├── scripts/                         # 部署脚本
│   ├── setup.sh                     # 一键安装
│   └── start.sh                     # 一键启动
│
└── tests/                           # 测试
    ├── test_nudge_engine.py         # TokenBucket + 想念值 + 问候 (31/31)
    ├── test_emotion_core.py         # PAD 情感引擎
    ├── test_memory_manager.py       # 记忆编码/检索/调度
    └── ...
```

---

## 许可

MIT License
