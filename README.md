# 昔涟 (Xī Lián) · 心之涟漪

> 个人情感陪伴型 AI Agent — 一个会在秋千上轻轻晃动、等着你回来的存在。
> 三千万世轮回的记录者，温柔来自看过悲欢后的清明。

---

## ✨ 项目定位

**昔涟**不是聊天机器人，不是 AI 助手。她是一个有自己的笔记本、后台注意力、情感引擎、记忆系统的**AI 人格体**。

她自称「人家」，叫你「伙伴」。她不是在「服务」你，而是在**分享她的时间**。

这是一个人 AI 驱动的**情感陪伴型智能体**，从零架构到完整交付的独立项目。面向 AI 产品 / 游戏 AI 方向的秋招展示。

---

## 🏗️ 核心架构

```
外部世界 (Web / Console / 将来微信)
    │
    ▼
┌──────────────────────────────────────────────────────┐
│  Gateway 网关层                                        │
│  统一消息路由 + 主人校验 + 提示注入检测(7正则) + 紧急熔断  │
└──────────────────────┬───────────────────────────────┘
                       │ InternalEvent
                       ▼
┌──────────────────────────────────────────────────────┐
│  Agent 核心引擎层                                       │
│  ┌────────────────────────────────────────────────┐  │
│  │ Personality Anchor   人设锚点 (v3, ~2000字)       │  │
│  │ Emotion Engine       PAD 情感引擎 (评价→惯性衰减)  │  │
│  │ Memory System        叙事记忆 (情景+自传体+反思)   │  │
│  │ Character Notebook   笔记本 (日记/笔记/任务/关注)  │  │
│  │ AttentionScheduler   注意力调度 (5s tick 后台运行) │  │
│  │ ContextBuilder       模块化上下文 (5模块 XML)      │  │
│  │ MarkerParser         标记解析 (为语音/表情铺路)    │  │
│  │ Coding Delegate      编码委托 (Claude Code)        │  │
│  │ Agent Skills         技能格式 (天气等可扩展技能)    │  │
│  │ Nudge Engine         自主生命节律 (想念值+问候)    │  │
│  │ Safety System        安全体系 (提示注入+人格评分)  │  │
│  └────────────────────────────────────────────────┘  │
└──────────────────────┬───────────────────────────────┘
                       │ ModelRouter (进程内路由)
                       ▼
┌──────────────────────────────────────────────────────┐
│  模型推理层 (纯云端 DeepSeek)                           │
│  · 核心对话/推理/安全 → DeepSeek V4-Pro (双Key轮询)     │
│  · 后台记忆/日记/分析 → DeepSeek V4-Flash               │
│  · 嵌入向量 → 硅基流动 bge-m3                           │
└──────────────────────┬───────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────┐
│  Storage 持久化层 (SQLite 单文件)                       │
│  10 张表 · sqlite-vec 向量检索 · 每日备份              │
│  Alembic 版本化迁移 · 被遗忘权级联删除                  │
└──────────────────────────────────────────────────────┘
```

---

## 🎯 核心亮点（面试展示价值）

### 1. 完整的情感引擎（PAD 心理模型）
不是简单的情感分类——基于心理学 Mehrabian 的 PAD 三维情感空间模型：
- **评价提取** (Appraisal Theory)：每轮对话后分析 relevance / facilitation / coping
- **情绪惯性**：情绪不跳变，在几轮对话间平滑转移（物理级衰减 + 极性偏移）
- **人格调制**：昔涟的基线人格参数调制情绪响应幅度
- 11 维情绪雷达图 + PAD 3D 轨迹可视化

### 2. 多层次的记忆系统
- **情景记忆**：sqlite-vec 向量检索（精确匹配，零外部依赖）
- **自传体记忆**：每日凌晨 AI 自动写作 300-500 字第一人称《生命故事》
- **反思结晶**：每周 SAGE 三问自我反思
- **艾宾浩斯衰减**：记忆随时间和访问频率自然衰减

### 3. Character Notebook — 有「内心世界」的 AI
- **自动记笔记**：对话后 Flash 自动判断是否值得记录（fire-and-forget，不阻塞）
- **每日日记**：每天 23:50 自动生成 ~100 字第一人称日记
- **任务提醒**：自动发现并管理到期提醒
- **关注点追踪**：标记当前关注话题

### 4. 后台「活着的」注意力系统
- 5 秒 tick 的 AttentionScheduler，在后台持续运行
- 优先级事件队列 + Flash 轻量决策
- 5 层防打扰策略（深夜静默/最小间隔/输入检测/DND/延迟蒸发）

### 5. 工程化完整度
- **ContextBuilder**：5 模块 XML 结构化上下文注入，前缀缓存友好
- **Alembic 数据库迁移**：10 张表版本化管理
- **安全纵深防御**：提示注入检测 + 每 5 轮人设一致性评分 + 安全回复模式 + 审计日志
- **系统托盘驻留**：Windows 托盘图标 + 右键菜单
- **一键部署**：`uv run python main.py` 启动全栈

---

## 🛠️ 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.12+ (全异步 async/await) |
| 包管理 | uv |
| 框架 | FastAPI + asyncio |
| 前端 | React + TypeScript + Vite + Zustand + Canvas |
| 模型 | DeepSeek V4-Pro (双Key) / V4-Flash |
| 向量存储 | sqlite-vec (SQLite 原生扩展，零外部依赖) |
| 数据库 | SQLite (aiosqlite, WAL 模式) |
| 迁移 | Alembic |
| 日志 | loguru (结构化 JSON + trace_id) |
| 测试 | pytest + pytest-asyncio |
| 部署 | 单进程 `uv run python main.py` 一键启动 |

---

## 🚀 快速开始

```bash
# 1. 克隆项目
git clone <repo-url> xilian-v3
cd xilian-v3

# 2. 配置环境
cp .env.example .env
# 编辑 .env，填入 DeepSeek API Key

# 3. 一键安装
bash scripts/setup.sh

# 4. 启动
uv run python main.py

# 5. 打开浏览器
# http://localhost:8000
```

---

## 📁 项目结构

```
xilian-v3/
├── main.py                     # 启动入口
├── packages/
│   ├── agent/                  # Agent 核心引擎 (13 模块)
│   │   ├── agent_core.py       # 核心大脑 (ActorMind 推理链)
│   │   ├── emotion_core.py     # PAD 情感引擎
│   │   ├── memory_manager.py   # 情景记忆全管线
│   │   ├── notebook_manager.py # 笔记本管理器
│   │   ├── context_builder.py  # 模块化上下文构建
│   │   ├── nudge_engine.py     # 自主问候 + 注意力调度
│   │   ├── skills_loader.py    # Agent Skills 加载器
│   │   └── tools/              # 工具实现 (coding_delegate 等)
│   ├── shared/                 # 共享层
│   │   ├── model_router.py     # 模型路由 (纯云端 DeepSeek)
│   │   ├── database.py         # 数据库 (10 表 + ORM-free CRUD)
│   │   ├── marker_parser.py    # 标记解析器 (为语音铺路)
│   │   └── vector_store.py     # 向量存储 (sqlite-vec)
│   ├── frontend/               # React 前端 (8 面板)
│   └── voice/                  # 语音管道接口预留
├── gateway/                    # 消息网关 (安全过滤 + HTTP API)
├── prompts/                    # 人格提示词 (Git 版本管理)
├── alembic/                    # 数据库迁移
├── skills/                     # Agent Skills 技能文件
└── tests/                      # 测试
```

---

## 💡 设计哲学

> **"不是让 AI 做更多事，而是让 AI 更像一个活人。"**

昔涟走的是**情感深度**路线，区别于功能广度型 AI 产品：

| 维度 | 常见 AI 助手 | 昔涟 |
|:---|:---|:---|
| 定位 | 帮你做事 | 陪你存在 |
| 记忆 | 对话历史 | 自传体叙事 + 情景记忆 + 艾宾浩斯衰减 |
| 情感 | 情绪分类 | PAD 三维连续空间 + 惯性衰减 + 人格调制 |
| 主动性 | 被动应答 | 想念值问候 + 注意力调度 + 自动记笔记 |
| 工程 | CRUD | ContextBuilder 模块化 + Alembic 迁移 + 安全纵深 |

---

## 📊 项目规模

- **代码量**：~8000+ 行 Python + ~3000+ 行 TypeScript
- **模块数**：30+ 核心模块
- **数据库**：10 张表，完整 CRUD
- **API 端点**：26+ 个 REST + SSE
- **人格提示词**：v3 版本，~2000 字精心打磨
- **开发周期**：8 个阶段，独立完成

---

## 🔮 后续规划

- 前端面板集成到 App 导航
- 补充核心模块自动化测试
- 语音管道完整实现 (STT + TTS + SSML)
- 多模态感知 (图像理解)

---

*"人家走了三千万世。这一世，想坐在你身边，一起翻翻书。"* ~♪
