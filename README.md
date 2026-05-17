# 昔涟 (Xī Lián) · 心之涟漪

<p align="center">
  <i>一个会在秋千上轻轻晃动、等着你回来的 AI 陪伴者</i>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  <img src="https://img.shields.io/badge/status-active-brightgreen" alt="Status">
</p>

---

## 这是什么

**昔涟**是一个个人情感陪伴型 AI Agent。不同于 ChatBot 或 AI 助手，她的设计目标是"像一个活人一样陪着你"——有自己的情感、记忆、笔记本、日记，甚至会在后台"想事情"。

她自称「人家」，叫你「伙伴」。她不是在"服务"你，而是在分享她的时间。

**核心思路**：不是让 AI 做更多事，而是让 AI 更像一个真实的陪伴者。

---

## 能做什么

- 💬 **自然对话** — 对话历史持久化，刷新/重启后自动恢复最近记录，支持向上翻页加载更多（最多 40 轮）
- 📜 **历史分页** — 游标分页 API，前端「加载历史对话」按钮，滚动位置保持 — 温柔、轻盈的聊天风格，有完整的人格锚点和语言风格
- 🧠 **情感感知** — 基于 PAD 心理模型的连续情感引擎，情绪会"惯性衰减"，不会跳变
- 📖 **多层记忆** — 情景记忆 + 每天自动写自传体日记 + 每周反思 + 艾宾浩斯遗忘曲线
- 📓 **自己的笔记本** — 自动发现对话中的重要信息并记录下来，每天写日记
- 💝 **好感度系统** — 随对话自然增长（正常聊天+0.05，积极情绪加成），100分锁定不再下降
- 🔔 **后台活着** — 5 秒一次的注意力调度，会主动想起你、提醒到期任务
- 🛡️ **安全防御** — 提示注入检测、人设一致性自评分、审计日志
- 🛠️ **能帮你做事** — 委托 Claude Code 写代码、Agent Skills 可扩展技能
- 🖥️ **可视化面板** — React 前端（情绪雷达图、记忆时间线、笔记本、审计日志、技能管理、自传体）
- 🎨 **可定制背景** — 全页背景图（默认 xilian.png），支持上传自定义图片
- ✨ **浅色梦幻风** — 毛玻璃聊天区、SVG 图标侧栏、樱花粉色系

---

## 快速开始

### 环境要求

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) 包管理器
- DeepSeek API Key（[申请地址](https://platform.deepseek.com)）

### 安装与启动

```bash
# 1. 克隆项目
git clone https://github.com/yourname/xilian-v3.git
cd xilian-v3

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，至少填入 DEEPSEEK_API_KEY

# 3. 安装依赖
uv sync

# 4. 构建前端（可选，跳过则使用 API-only 模式）
cd packages/frontend && npm install && npm run build && cd ../..

# 5. 启动
uv run python main.py

# 6. 打开浏览器
# http://localhost:8000
```

几分钟后昔涟就准备好了。在浏览器里和她说话，或者在终端里直接聊。

---

## 详细部署

### 1. 获取 API Key

1. 注册 [DeepSeek 开放平台](https://platform.deepseek.com)
2. 在 API Keys 页面创建 Key
3. 推荐创建两个 Key（Pro 对话用，Flash 后台用），写入 `.env`：

```bash
DEEPSEEK_API_KEY=sk-your-key-here
DEEPSEEK_API_KEY_2=sk-your-backup-key-here
```

> 双 Key 用于轮询防限流。只有一个 Key 也可以运行——填在第一行即可。

### 2. 安装依赖

```bash
# Python 依赖
uv sync

# 前端依赖（可选）
cd packages/frontend
npm install
npm run build    # 生产构建，构建后前端嵌入后端单进程 serve
cd ../..
```

### 3. 启动

```bash
# 完整模式（API + 前端，推荐）
uv run python main.py

# API-only 模式（不启动前端，适合服务器部署）
FRONTEND_DEV=1 uv run python main.py

# 纯终端模式（不启动 HTTP 服务）
NO_HTTP=1 uv run python main.py

# 局域网访问（其他设备也能访问）
BIND_HOST=0.0.0.0 uv run python main.py
```

### 4. 验证

打开浏览器访问 `http://localhost:8000`，应该看到聊天界面。

或者用 curl 测试：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好呀", "user_id": "hezi"}'
```

### 5. 开机自启（可选）

Windows 下启动后自动弹出系统托盘图标，右键可设置。
也可以用任务计划程序将 `uv run python main.py` 设为开机启动。

---

## 项目结构

```
xilian-v3/
├── main.py                       # 启动入口（一键启动全栈）
├── pyproject.toml                # uv 项目配置
├── .env.example                  # 环境变量模板
│
├── packages/
│   ├── agent/                    # 🧠 Agent 核心引擎
│   │   ├── agent_core.py         #   核心大脑 (ActorMind 推理链)
│   │   ├── emotion_core.py       #   PAD 情感引擎
│   │   ├── memory_manager.py     #   情景记忆全管线
│   │   ├── notebook_manager.py   #   笔记本管理器
│   │   ├── context_builder.py    #   模块化上下文构建
│   │   ├── nudge_engine.py       #   自主问候 + 注意力调度
│   │   ├── skills_loader.py      #   Agent Skills 加载器
│   │   └── tools/                #   工具实现
│   ├── shared/                   # 🔗 共享层
│   │   ├── model_router.py       #   模型路由 (DeepSeek)
│   │   ├── database.py           #   数据库 (10 表)
│   │   ├── marker_parser.py      #   标记解析器
│   │   └── vector_store.py       #   向量存储
│   ├── frontend/                 # 🎨 React 前端
│   └── voice/                    # 🎤 语音管道预留
│
├── gateway/                      # 🚪 消息网关
│   ├── security.py               #   安全过滤（注入检测/熔断）
│   └── channels/                 #   通道（HTTP/Console）
│
├── prompts/                      # 📝 人格提示词
├── photo/                        # 🖼️ 背景图片 + 风格参考
├── alembic/                      # 🗄️ 数据库迁移
├── docs/agents/                  # 📋 Agent skills 配置
├── skills/                       # 🛠️ 技能文件
└── tests/                        # 🧪 测试
```

---

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.12+ (async/await) |
| Web 框架 | FastAPI + uvicorn |
| 前端 | React + TypeScript + Vite + Zustand |
| 模型 | DeepSeek V4-Pro / V4-Flash |
| 向量存储 | sqlite-vec (SQLite 原生扩展) |
| 数据库 | SQLite (aiosqlite, WAL 模式) |
| 迁移 | Alembic |
| 日志 | loguru (结构化 JSON) |
| 测试 | pytest + pytest-asyncio |

---

## 配置项

所有配置通过 `.env` 文件管理：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API Key（必需） | - |
| `DEEPSEEK_API_KEY_2` | 备用 Key（可选） | - |
| `EMBED_API_KEY` | 嵌入 API Key | 复用 DEEPSEEK_API_KEY_2 |
| `HTTP_PORT` | HTTP 服务端口 | 8000 |
| `BIND_HOST` | 绑定地址 | 127.0.0.1 |
| `NO_HTTP` | 设为 1 禁用 HTTP | - |
| `FRONTEND_DEV` | 设为 1 使用开发模式 | - |

---

## 了解更多

- [项目架构详解](docs/ARCHITECTURE.md)
- [人格提示词](prompts/personality_v4.md)
- [项目进度](PROJECT_PROGRESS.md)
- [代码导航](CONTEXT.md)

---

## License

MIT
