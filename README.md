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

- 💬 **自然对话** — 昔涟风格：短句分行、温柔轻盈、真实感节奏（v4 人格提示词）
- 📜 **对话历史** — 游标分页持久化，刷新/重启自动恢复，最多向上加载 40 轮
- 🧠 **情感感知** — PAD 心理模型连续情感引擎，情绪惯性衰减不跳变
- 📖 **多层记忆** — 情景记忆向量检索 + 艾宾浩斯遗忘曲线 + 每日自传体 + 每周反思
- 📓 **智能笔记本** — 自动发现对话重要信息并记录，支持笔记/日记/待办任务
- 🔔 **任务提醒** — 对话中自然创建提醒（"晚上十点提醒我"），15 分钟粒度检查，主动推送
- 👤 **用户印象** — 叙事性印象文档，每日凌晨自动重写，破冰主动问候
- 💝 **好感度** — 随对话自然增长，4 级标签（昔涟喜欢你 → 你永远喜欢昔涟）
- 🛡️ **安全纵深** — 提示注入检测 + 人设自评分 + 审计日志 + 被遗忘权
- 🛠️ **4 个工具** — 记忆检索 / 天气查询 / 网络搜索 / 编码委托（LLM function calling 驱动）
- 🖥️ **9 个前端面板** — 情绪雷达 / 记忆时间线 / 笔记本 / 自传体 / 审计日志 / 技能管理 / 伙伴印象 / 设置 / PAD 轨迹
- 🎨 **浅色梦幻风** — 毛玻璃卡片 + SVG 侧栏图标 + 樱花粉色系 + 可定制全页背景

---

## 快速开始

### 环境要求

- Python ≥ 3.12
- [uv](https://docs.astral.sh/uv/) 包管理器
- DeepSeek API Key（[申请地址](https://platform.deepseek.com)）

### 安装与启动

```bash
# 1. 克隆项目
git clone https://github.com/yaosqee/xilian-agent.git
cd xilian-v3

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 DEEPSEEK_API_KEY

# 3. 安装 Python 依赖
uv sync

# 4. 构建前端
cd packages/frontend && npm install && npm run build && cd ../..

# 5. 一键启动
uv run python main.py

# 6. 打开浏览器 → http://localhost:8000
```

### 开发模式

```bash
# 后端（终端 1）
uv run python main.py

# 前端热更新开发服务器（终端 2）
cd packages/frontend && npm run dev
# 访问 http://localhost:5173，API 自动代理到 :8000
```

### 其他启动方式

```bash
FRONTEND_DEV=1 uv run python main.py   # API-only（需配合 npm run dev）
NO_HTTP=1 uv run python main.py        # 纯终端聊天
BIND_HOST=0.0.0.0 uv run python main.py  # 局域网访问
```

### 验证

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好呀", "user_id": "hezi"}'
```

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
│   │   ├── portrait_manager.py   #   用户印象管理器
│   │   ├── context_builder.py    #   模块化上下文构建
│   │   ├── nudge_engine.py       #   自主问候 + 注意力调度
│   │   ├── skills_loader.py      #   Agent Skills 加载器
│   │   └── tools/                #   4 个工具实现
│   ├── shared/                   # 🔗 共享层
│   │   ├── model_router.py       #   模型路由 (DeepSeek)
│   │   ├── database.py           #   数据库 (11 表)
│   │   ├── marker_parser.py      #   标记解析器
│   │   └── vector_store.py       #   向量存储
│   └── frontend/                 # 🎨 React 前端
│
├── gateway/                      # 🚪 消息网关
│   ├── security.py               #   安全过滤（注入检测/熔断）
│   └── channels/                 #   通道（HTTP/Console）
│
├── prompts/                      # 📝 人格提示词
├── photo/                        # 🖼️ 背景图片 + 风格参考
├── alembic/                      # 🗄️ 数据库迁移
├── skills/manual/                # 🛠️ 4 个技能文件
└── tests/                        # 🧪 402 条测试
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
