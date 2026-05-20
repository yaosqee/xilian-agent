# 昔涟 V3.3 · 部署与运维指南

版本: 2026-05-20

---

## 一、环境依赖

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | ≥ 3.12 | 后端运行 |
| Node.js | ≥ 20 | 前端构建（Vite） |
| uv | 最新 | Python 包管理 |
| npm | ≥ 9 | 前端依赖 |
| sqlite-vec | 0.1.x | 向量存储扩展 |

系统要求：Linux（含 WSL2），macOS 未测试但理论上可行。

---

## 二、首次启动

```bash
# 1. 克隆项目
git clone https://github.com/yaosqee/xilian-agent.git
cd xilian-agent

# 2. 安装后端依赖
uv sync

# 3. 配置环境变量
cp .env.example .env   # 如无 .env.example，手动创建 .env（见下方）

# 4. 安装前端依赖 + 构建
cd packages/frontend
npm install
npm run build
cd ../..

# 5. 启动
uv run python main.py
```

前端开发模式（热重载）：
```bash
cd packages/frontend && npm run dev
```

---

## 三、环境变量 (.env)

```bash
# ── 必需 ──
DEEPSEEK_API_KEY=sk-xxx          # DeepSeek V4-Pro 主 Key
DEEPSEEK_API_KEY_2=sk-xxx        # DeepSeek V4 备用 Key（Pro 双 Key 轮询 + Flash）
EMBED_API_KEY=sk-xxx             # 硅基流动 bge-m3 嵌入 API（通常与 DEEPSEEK_API_KEY_2 相同）
EMBED_BASE_URL=https://api.siliconflow.cn/v1  # 嵌入 API 地址

# ── 可选 ──
QWEATHER_API_KEY=xxx             # 和风天气 API（query_weather 工具）
QWEATHER_API_HOST=devapi.qweather.com  # 和风天气接口地址
ZHIPU_API_KEY=xxx                # 智谱 API（search_web 工具 + 天气 fallback）
```

**获取 API Key**：
- DeepSeek: https://platform.deepseek.com
- 硅基流动: https://siliconflow.cn
- 和风天气: https://dev.qweather.com（免费版即可）
- 智谱: https://open.bigmodel.cn

---

## 四、目录结构（运维视角）

```
xilian-v3/
├── main.py                  # 启动入口
├── .env                     # 环境变量（gitignored）
├── data/
│   ├── xilian.db            # SQLite 主数据库
│   └── character_memories.json  # 角色记忆源文件（版本控制）
├── packages/
│   ├── agent/               # Agent 核心
│   │   ├── tools/           # 4 个工具
│   │   └── ...
│   ├── shared/              # 共享模块（DB/路由/向量）
│   └── frontend/            # React 前端
├── prompts/                 # 人格提示词（版本控制）
├── scripts/                 # 运维脚本
│   └── seed_character_memories.py  # 角色记忆导入（启动时自动执行）
├── backups/                 # 数据库备份
├── logs/                    # 日志文件
├── docs/                    # 项目文档
└── tests/                   # 测试套件
```

---

## 五、数据库

### 位置
`data/xilian.db`（SQLite，WAL 模式）

### 备份
BackupManager 每日 3:00 自动备份到 `backups/`，保留 7 天。

### 手动备份
```bash
cp data/xilian.db "backups/xilian-$(date +%Y%m%d-%H%M%S).db"
```

### 重置
```bash
# 清空对话历史（保留记忆和笔记）
curl -X POST http://localhost:8000/api/session/reset -H "Content-Type: application/json" -d '{}'

# 完全重置数据库
rm data/xilian.db
# 重启后自动重建表结构 + 角色记忆播种
```

---

## 六、日志

### 位置
- `logs/xilian_{date}.log` — 按天轮转
- 控制台输出 — 实时查看

### 日志级别
默认 INFO。关键模块的 DEBUG 日志需手动开启。

### 关键日志标识

| 标识 | 含义 |
|------|------|
| `agent.process.start/done` | 一次对话处理完成 |
| `memory.encoded` | 情景记忆写入 |
| `emotion.pad_updated` | PAD 情绪状态更新 |
| `portrait.consolidated` | 用户印象重写 |
| `autobiography.written` | 自传生成 |
| `notebook.auto_note` | 自动笔记创建 |
| `nudge.greeting_scheduled` | 自主问候触发 |
| `model_router.truncated` | LLM 响应被 max_tokens 截断（警告，非错误） |

---

## 七、定时任务

| 时间 | 任务 | 说明 |
|------|------|------|
| 每 15 分钟 | Nudge tick | 检查是否该问候伙伴 |
| 每 20 分钟 | Token refill | 频率控制令牌补充 |
| 每 5 秒 | Attention tick | 检查是否有要提醒的事件 |
| 每日 3:00 | 数据库备份 | 备份到 `backups/` |
| 每日 3:30 | 备份清理 | 删除 7 天前的旧备份 |
| 每日 5:00 | 印象重写 | Portrait consolidate |
| 每日 23:00 | 自传写作 | 每日生命故事 |
| 每周日 4:30 | 反思写作 | SAGE 四问 |

---

## 八、常见故障

### 端口占用
```bash
fuser -k 8000/tcp
```

### 数据库锁定
SQLite WAL 模式下极少发生。如果出现：
```bash
# 检查是否有僵尸进程
pgrep -f main.py
# 强制杀掉重启
pkill -f main.py && uv run python main.py
```

### API Key 失效
日志中出现 `model_router` 相关错误。检查 `.env` 中的 Key 是否有效、余额是否充足。

### 嵌入 API 超时
`EMBED_BASE_URL` 默认指向硅基流动，如果不可用可换为 DeepSeek 或其他 OpenAI 兼容的嵌入服务。

---

## 九、性能基线

| 指标 | 典型值 |
|------|--------|
| 对话响应（Pro） | 3-10s |
| 情感分析（Flash） | 1-2s |
| 记忆编码（Flash + 嵌入） | 3-5s |
| 印象重写（Flash） | 5-10s |
| 自传写作（Flash） | 3-5s |
| 启动时间 | ~5s（含 DB 迁移 + 角色记忆检查） |
| 内存占用 | ~300MB（Python 进程） |
| 数据库大小 | ~5MB（1000 条记忆规模） |

---

*本文档随部署环境变更持续更新。最后修订：2026-05-20*
