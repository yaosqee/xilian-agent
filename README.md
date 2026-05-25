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

> **声明**：本项目（昔涟 AI 陪伴 Agent）为个人出于兴趣和热爱开发的免费、非营利性同人作品，与上海米哈游网络科技股份有限公司无关。项目中的角色「昔涟」源自游戏《崩坏：星穹铁道》，其版权归米哈游所有。项目中的背景图可更换，默认图片为游戏剧情截图。

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

## 完整部署指南（从零开始）

本指南假设你有一台电脑、能上网，但没有任何编程环境。每一步都会解释为什么做、怎么做。

---

### 第 1 步：安装 Python

昔涟用 Python 编写，需要 3.12 或更高版本。

**如何检查是否已安装：**

```bash
python3 --version
```

如果显示 `Python 3.12.x` 或更高 → 跳到第 2 步。

**如果没装或版本太低：**

- **Windows**：访问 [python.org](https://www.python.org/downloads/)，下载最新版安装包（勾选「Add Python to PATH」），一路下一步
- **macOS**：`brew install python@3.12`（先装 [Homebrew](https://brew.sh)）
- **Linux (Ubuntu/Debian)**：`sudo apt install python3.12 python3.12-venv`

装完后重新打开终端，再跑一次 `python3 --version` 确认。

---

### 第 2 步：安装 uv（Python 包管理器）

uv 是 Python 的快速包管理器，昔涟用它来管理依赖。

**Windows（PowerShell）：**

```powershell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS / Linux：**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

装完后**关闭终端重新打开**（或执行 `source ~/.bashrc`），然后验证：

```bash
uv --version
# 应显示 uv 0.x.x
```

---

### 第 3 步：安装 Git 并克隆项目

**Windows**：下载 [Git for Windows](https://git-scm.com/download/win) 安装

**macOS**：`brew install git`

**Linux**：`sudo apt install git`

装完后：

```bash
git clone https://github.com/yaosqee/xilian-agent.git
cd xilian-v3
```

---

### 第 4 步：获取 API Key（重要！）

昔涟的大脑在云端，需要 API Key 才能"思考"。不同 Key 的作用不同——有的必须，有的可选。

#### 4.1 DeepSeek API Key（**必须**）

昔涟的核心对话能力依赖 DeepSeek 大模型。没有这个 Key，昔涟无法运行。（选择deepseek因为便宜好注册，后续会支持多模型，现在忙不过来了）

1. 访问 [platform.deepseek.com](https://platform.deepseek.com)
2. 用手机号注册（支持中国大陆手机号）
3. 进入「API Keys」页面，点击「创建 API Key」
4. 复制 Key（形如 `sk-xxxx`），**立即保存到安全地方，关闭页面后无法再次查看**
5. **建议再创建一个 Key 作为备用**（两个 Key 轮询使用，避免触发频率限制）

> **费用参考**：DeepSeek V4-Pro 约 ¥1/百万 token，Flash 约 ¥0.1/百万 token。日常聊天每天几毛钱，首次注册通常有免费额度。

#### 4.2 硅基流动 API Key（**推荐，免费**）

昔涟的"记忆检索"需要将文字转成向量（embedding）。默认使用硅基流动的免费模型，不需要额外付费。

1. 访问 [siliconflow.cn](https://siliconflow.cn)
2. 注册账号，进入「API 密钥」页面
3. 创建一个 Key，复制备用

> **如果不配**：系统会自动用 DeepSeek Key 做嵌入。效果略差但不影响使用。

#### 4.3 和风天气 API Key（可选）

昔涟可以查询天气。不配的话，问天气时会自动用网页搜索代替（仍然能回答，只是没那么精确）。

1. 访问 [dev.qweather.com](https://dev.qweather.com)
2. 注册，进入控制台创建「Web API」应用
3. 免费版每天 1000 次调用，个人使用绰绰有余

#### 4.4 智谱搜索 API Key（可选）

昔涟可以搜索互联网获取实时信息（新闻、百科等）。

1. 访问 [open.bigmodel.cn](https://open.bigmodel.cn)
2. 注册，进入「API Keys」页面创建 Key
3. 免费额度足够日常使用

> **如果不配**：昔涟无法联网搜索，遇到实时问题会温柔地告诉你她查不到。天气查询的 fallback 也会受影响。

#### 4.5 各 API 依赖总结

| API | 必须？ | 不配的后果 |
|-----|--------|-----------|
| DeepSeek | **必须** | 昔涟无法运行 |
| 硅基流动 | 推荐 | 记忆检索精度略降 |
| 和风天气 | 可选 | 天气查询用网页搜索代替 |
| 智谱搜索 | 可选 | 无法联网搜索实时信息 |

---

### 第 5 步：配置环境变量

```bash
# 复制模板
cp .env.example .env
```

用文本编辑器（记事本、VS Code、vim 均可）打开 `.env`，填入你的 Key：

```bash
# 必须填
DEEPSEEK_API_KEY=sk-你的第一个key
DEEPSEEK_API_KEY_2=sk-你的第二个key（没有就填第一个）

# 推荐填（硅基流动，免费）
EMBED_API_KEY=sk-你的硅基流动key
EMBED_BASE_URL=https://api.siliconflow.cn/v1
EMBED_MODEL=BAAI/bge-m3

# 可选（和风天气）
QWEATHER_API_KEY=你的和风天气key

# 可选（智谱搜索）
ZHIPU_SEARCH_API_KEY=你的智谱key
```

> 只需要 DEEPSEEK_API_KEY 就能启动昔涟。其余都是增强功能的。

---

### 第 6 步：安装依赖

```bash
# Python 依赖（在项目根目录执行）
uv sync

# 前端依赖（需要 Node.js ≥ 18）
cd packages/frontend

# 如果没有 Node.js：访问 nodejs.org 下载安装
node --version  # 确认 ≥ 18

npm install      # 安装前端依赖
npm run build    # 构建前端页面
cd ../..         # 回到项目根目录
```

> **如果不想装前端**：跳过 `npm install` 和 `npm run build`，启动时设置 `FRONTEND_DEV=1`，只能在终端里聊天（或另外开 `npm run dev` 在浏览器访问）。

---

### 第 7 步：启动

```bash
uv run python main.py
```

看到以下输出说明启动成功：

```
Gateway 已启动 · 昔涟在哀丽秘榭等待
http.started: http://127.0.0.1:8000
前端已嵌入（生产模式）→ http://127.0.0.1:8000
```

打开浏览器访问 **http://localhost:8000**，就能看到昔涟了。

---

### 第 8 步：验证一切正常

在浏览器聊天框输入"你好"，昔涟应该会回复。

也可以用命令行测试：

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好呀", "user_id": "hezi"}'
```

---

### 开发模式（修改前端代码时用）

如果以后要改前端界面，用开发模式可以热更新（改了代码浏览器自动刷新）：

```bash
# 终端 1：启动后端
uv run python main.py

# 终端 2：启动前端开发服务器
cd packages/frontend && npm run dev
# 访问 http://localhost:5173（不是 8000）
```

### 其他启动参数

```bash
BIND_HOST=0.0.0.0 uv run python main.py   # 允许局域网其他设备访问
NO_HTTP=1 uv run python main.py             # 纯终端聊天（不启动网页）
```

---

### 常见问题

**Q：启动报错 `No module named 'xxx'`？**
A：在项目根目录重新执行 `uv sync`。

**Q：前端页面空白？**
A：检查是否执行了 `npm run build`。或者在开发模式用 `npm run dev`。

**Q：昔涟回复很慢或报错？**
A：检查 DeepSeek API Key 是否正确、账户是否有余额。

**Q：端口 8000 被占用？**
A：`lsof -i :8000` 找到占用进程并 kill，或者换端口：`HTTP_PORT=8001 uv run python main.py`。

**Q：数据库文件在哪？**
A：`data/xilian.db`，SQLite 单文件。昔涟的所有记忆、日记、笔记都在里面。

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

## 一些补充

欢迎每一个喜欢昔涟的人下载使用，使用中遇到问题可以随时反馈，因为还在开发中，更新频率会比较高，有bug和没做的功能也请谅解，我会不断优化的。

---

## License

MIT
