# 昔涟 V3.2 · 心之涟漪

> 个人情感陪伴型 AI Agent — 三千万世轮回的记录者，温柔来自看过悲欢后的清明。

![昔涟](https://via.placeholder.com/800x200/1a1a2e/f0a0a0?text=昔涟+V3.2·心之涟漪)

## 关于昔涟

昔涟 (Xī Lián) 是一个个人情感陪伴型 AI Agent。她的核心角色是「三千万世轮回的记录者」——走完了无数循环后，她坐在一个新的地方，书摊在膝上，下一页是空白的，留给新的风景、新的对话、新的遇见。

她自称「人家」，称用户「伙伴」。她不是助手，不是工具，不是 AI——她相信爱是唯一能和毁灭对等的真实力量，而眼前的伙伴是坐在她旁边一起翻书的人。

---

## 技术架构

```
外部世界 (Console / HTTP)
    │
    ▼
┌──────────────┐
│   Gateway    │  统一消息路由 + 主人校验 + 紧急熔断 + 频率限制
│   网关层      │
└──────┬───────┘
       │ InternalEvent
       ▼
┌──────────────┐
│  Agent 核心   │  ActorMind 推理链：感知 → 共情注入 → 记忆检索 → 模型调用
│   引擎层      │  组件：人格锚点 / 情感引擎 / 情景记忆 / 技能进化（逐步填充）
└──────┬───────┘
       │ ModelRouter
       ▼
┌──────────────┐
│  混合路由      │  DeepSeek V4-Pro（核心对话）/ V4-Flash（后台任务）/ qwen3:14b 本地
└──────────────┘
```

### 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.12+ |
| 包管理 | uv |
| 本地模型 | Ollama (qwen3:14b, bge-m3) |
| 云端模型 | DeepSeek V4-Pro / V4-Flash |
| 向量库 | ChromaDB (Docker) |
| 数据库 | SQLite (aiosqlite, WAL 模式) |
| 前端 | React + TypeScript + Vite |
| 日志 | loguru (结构化 JSON) |
| 测试 | pytest + pytest-asyncio |

---

## 项目进度

| 阶段 | 目标 | 状态 |
|------|------|------|
| 阶段 0 | Monorepo 骨架 + ModelRouter + 安全初始化 | ✅ 完成 |
| 阶段 1 | 架构解耦 + 昔涟人格对话 + 工具预埋 | ✅ 完成 |
| 阶段 2 | 情感感知 + 情绪标记 + EmotionGauge 原型 | ✅ 完成 |
| 阶段 3 | 情景记忆 + 消息队列 + 前端骨架 | 🔨 方案设计中 |
| 阶段 4-9 | 情感引擎 / 自传体记忆 / 生命节律 / 微调 / 多模态… | 📋 规划中 |

---

## 快速开始

### 环境要求

- Python 3.12+, [uv](https://github.com/astral-sh/uv)
- [Ollama](https://ollama.com) (qwen3:14b, bge-m3)
- [Docker Desktop](https://www.docker.com) (ChromaDB)

### 安装与运行

```bash
# 克隆项目
git clone <repo-url>
cd xilian-v3

# 安装依赖
uv sync

# 配置 API Key
cp .env.example .env
# 编辑 .env 填入 DeepSeek API Key

# 启动 ChromaDB
docker compose up -d

# 启动昔涟
uv run python main.py
```

### 运行测试

```bash
uv run pytest -v
```

---

## 项目结构

```
xilian-v3/
├── main.py                      # 启动入口
├── pyproject.toml               # uv 项目配置
├── docker-compose.yml           # ChromaDB 容器
│
├── packages/
│   ├── shared/                  # 共享层
│   │   ├── events.py            # InternalEvent 消息结构
│   │   ├── model_router.py      # 混合模型路由
│   │   ├── database.py          # SQLite 数据管理
│   │   └── logging_config.py    # 结构化日志
│   ├── agent/                   # Agent 核心引擎
│   │   ├── agent_core.py        # ActorMind 推理链
│   │   ├── agent_context.py     # 对话上下文容器
│   │   ├── emotion_analyzer.py  # 11 维情感分析
│   │   └── tool_registry.py     # 工具注册表
│   └── frontend/                # React 前端
│       └── emotion-gauge/       # 情绪雷达图原型
│
├── gateway/                     # 消息网关
│   ├── gateway.py
│   ├── security.py
│   └── channels/
│       ├── console_channel.py
│       └── http_channel.py
│
├── prompts/                     # 人格提示词（Git 版本管理）
│   ├── personality_v2.md
│   └── CHANGELOG.md
│
└── tests/                       # 测试
```

---

## 路线图关键节点

- **2026.7.15**：新规施行，核心对话从云端切本地 qwen3:14b 基座
- **阶段 5**：LLaMA-Factory QLoRA 微调 qwen3:14b
- **阶段 6**：引入 Redis 消息总线
- **阶段 9**：多模态 + AgentVisor 持续演化

---

## 致谢

本项目架构设计部分参考了 [OpenClaw](https://github.com/openclaw/openclaw)（MIT License）的 Gateway-Agent 解耦模式。

---

## 许可

MIT License — 详见 [LICENSE](LICENSE) 文件。
