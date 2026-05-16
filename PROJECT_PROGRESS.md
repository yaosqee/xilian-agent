# 昔涟 V3.3 · 项目仪表盘

> 📍 新 AI 窗口第一口粮。读完这个你就知道：这是什么、做到哪了、怎么继续。
> 📅 最后更新：2026-05-16 16:00 CST
> 🔖 当前阶段：阶段 7 ✅ 完成 → 等待进入阶段 8

---

## 一句话定位

**昔涟 (Xī Lián)** — 个人情感陪伴型 AI Agent，盒子自用，秋招展示核心项目。
核心角色：三千万世轮回的记录者，温柔来自看过悲欢后的清明，自称「人家」称用户「伙伴」。

---

## 当前状态

| 项目 | 状态 |
|------|------|
| 阶段 0（奠基+安全） | ✅ 完成 |
| 阶段 1（解耦+人格+工具预埋） | ✅ 完成 |
| 阶段 2（情感感知+原型） | ✅ 完成 |
| 阶段 3（情景记忆+前端） | ✅ 完成 |
| 阶段 4（PAD 情感引擎） | ✅ 完成 |
| 阶段 5（自传体+前端全集成） | ✅ 完成 |
| 阶段 6（自主生命节律+一键部署） | ✅ 完成 |
| 阶段 7（内心世界+工具执行+表达管道） | ✅ 完成 |
| 总进度 | 8/10 阶段 |

---

## 阶段 1 已完成的核心交付

| # | 交付物 | 文件 |
|---|--------|------|
| 一 | InternalEvent 消息结构 | `packages/shared/events.py` |
| 二 | 工具注册表（装饰器注册） | `packages/agent/tool_registry.py` |
| 三 | 昔涟人格系统提示 v2（精简版 ~1800字） | `prompts/personality_v2.md` |
| 四 | AgentCore + ActorMind + AgentContext | `packages/agent/agent_core.py` + `agent_context.py` |
| 五 | Gateway 通道层（Console + HTTP） + 安全过滤 | `gateway/` 目录 |
| 六 | MCP 适配器签名预埋 | `gateway/mcp/adapter.py` |
| 七 | main.py 启动入口 + 集成测试 40/40 全绿 | `main.py` + `tests/` |
| — | Git commit: 599d8ba | — |

## 阶段 2 已完成的核心交付

| # | 交付物 | 文件 |
|---|--------|------|
| 一 | EmotionAnalyzer 11 维情感分析模块 | `packages/agent/emotion_analyzer.py` |
| 二 | SQLite DatabaseManager + conversation_logs 表 | `packages/shared/database.py` |
| 三 | AgentCore 情感管道集成（共情注入 + 后台分析） | `packages/agent/agent_core.py` + `agent_context.py` |
| 四 | EmotionGauge React 原型（Vite + Canvas 11 维雷达图） | `packages/frontend/emotion-gauge/` |
| 五 | 集成测试 64/64 全绿（新增 32 条） | `tests/test_emotion_analyzer.py` + `test_empathy_injection.py` |
| — | Git commit: ccbeefd | — |

---

## 阶段 3 已完成的核心交付

| # | 交付物 | 文件 |
|---|--------|------|
| 一 | 数据库扩展：episodic_memories + message_queue 表 + CRUD | `packages/shared/database.py` (+~480行) |
| 二 | MemoryManager 情景记忆全管线 | `packages/agent/memory_manager.py` (新建) |
| 三 | AgentCore 记忆管道改造 + shutdown | `packages/agent/agent_core.py` |
| 四 | AgentContext 记忆注入实现 | `packages/agent/agent_context.py` |
| 五 | BackupManager 每日备份 | `packages/shared/backup.py` (新建) |
| 六 | HTTP API 扩展（5 个新端点） | `gateway/channels/http_channel.py` |
| 七 | 前端骨架：Pi 风格聊天 + EmotionGauge | `packages/frontend/` (28 文件) |
| 八 | 50 条集成测试 | `tests/` |
| — | Git commit: 824e8f5 | — |

---

## 阶段 4 已完成的核心交付 🧠 PAD 情感引擎

| # | 交付物 | 文件 |
|---|--------|------|
| 一 | EmotionEngine：AppraisalExtractor + PADMapper + EmotionState + PersonalityModulator | `packages/agent/emotion_core.py` (新建) |
| 二 | evaluation → PAD 映射公式（心理学 Mehrabian 文献参数） | `packages/agent/emotion_core.py` |
| 三 | 情绪状态更新器：惯性衰减 + 极性转移 + 人格调制 | `packages/agent/emotion_core.py` |
| 四 | PAD → 11 维情绪映射（兼容阶段2 雷达图） | `packages/agent/emotion_core.py` |
| 五 | emotion_snapshots 表 + CRUD | `packages/shared/database.py` |
| 六 | 3 个新 API：/api/emotion + /api/emotion/history + /api/emotion/stats | `gateway/channels/http_channel.py` |
| 七 | AgentCore 集成 EmotionEngine + 共情注入改造 | `packages/agent/agent_core.py` |
| 八 | 前端 PADTrajectory 3D 轨迹组件 | `packages/frontend/src/components/panels/PADTrajectory.tsx` |
| 九 | 173/173 测试全绿 | `tests/test_emotion_core.py` + `test_emotion_appraisal.py` |
| — | Git commit: 8f41139（阶段4-6 合并提交） | — |

---

## 阶段 5 已完成的核心交付 ✨ 自传体 + 前端全集成

| # | 交付物 | 文件 |
|---|--------|------|
| 一 | AutobiographyWriter：每日凌晨自传体写作（300-500字昔涟视角） | `packages/agent/autobiography_writer.py` (新建) |
| 二 | ReflectionWriter：每周日凌晨 SAGE 反思结晶 | `packages/agent/autobiography_writer.py` |
| 三 | autobiography_entries + reflection_crystals 表 + CRUD | `packages/shared/database.py` |
| 四 | 艾宾浩斯遗忘衰减集成到 MemoryManager | `packages/agent/memory_manager.py` |
| 五 | 6 个新 API：/api/memories/recent + /api/autobiography + /api/autobiography/list + /api/reflection/latest + /api/greeting | `gateway/channels/http_channel.py` |
| 六 | 时间感知问候 get_time_greeting() | `packages/agent/agent_core.py` |
| 七 | 人格漂移检测 _check_personality_drift() | `packages/agent/agent_core.py` |
| 八 | 前端 MemoryTimeline + AutobiographyPanel + AffectionBar | `packages/frontend/src/components/` |
| 九 | 品牌视觉系统 theme.css（樱花粉系 + 圆角气泡 + 水波纹过渡） | `packages/frontend/src/styles/theme.css` |
| 十 | 人格升级 v3 + 游戏知识整理 | `prompts/personality_v3.md` + `prompts/game-knowledge.md` |
| 十一 | 195/195 测试全绿 | `tests/test_biography.py` + `test_forgetting.py` + `test_personality_regression.py` |
| — | Git commit: 8f41139（阶段4-6 合并提交） | — |

---

## 阶段 6 已完成的核心交付 🚀 自主生命节律 + 一键部署

| # | 交付物 | 文件 |
|---|--------|------|
| 一 | TokenBucket 频率控制（≤3条/h + 内容哈希去重） | `packages/agent/nudge_engine.py` (新建) |
| 二 | 想念值计算 + 自主问候生成（DS Pro） | `packages/agent/nudge_engine.py` |
| 三 | AutonomyConfig 可持久化配置 | `packages/agent/nudge_engine.py` |
| 四 | autonomy_settings 表 + CRUD | `packages/shared/database.py` |
| 五 | /api/autonomy/* 端点（status/pause/resume/settings/pending-greeting/ack） | `gateway/channels/http_channel.py` |
| 六 | proactive_check cron 每15分钟 + token_bucket_refill | `main.py` |
| 七 | 前端嵌入后端（FastAPI StaticFiles 挂载 Vite build） | `main.py` |
| 八 | SettingsPanel 扩展 + autonomyStore | `packages/frontend/src/` |
| 九 | 一键部署 setup.sh + start.sh | `scripts/setup.sh` + `scripts/start.sh` |
| 十 | Console TUI 美化（rich 库） | `gateway/channels/console_channel.py` |
| 十一 | ~25 条新测试 | `tests/test_nudge_engine.py` |
| — | Git commit: ab890f0 | — |

---

## 阶段 7 已完成的核心交付 🛠️ 内心世界 + 工具执行 + 表达管道

| # | 交付物 | 文件 |
|---|--------|------|
| 一 | ContextBuilder 模块化上下文（5 模块 XML + 优先级+预算） | `packages/agent/context_builder.py` (新建) |
| 二 | ModelRouter 工具兼容降级（tools_support_cache） | `packages/shared/model_router.py` |
| 三 | Character Notebook（笔记/日记/关注/任务 + 自动记笔记） | `packages/agent/notebook_manager.py` (新建) + 2 表 |
| 四 | AttentionScheduler 注意力调度（5s tick + 防打扰） | `packages/agent/nudge_engine.py` 扩展 |
| 五 | MarkerParser 标记解析器（5 种标记 + 跨 chunk + SSML 接口） | `packages/shared/marker_parser.py` (新建) |
| 六 | Claude Code 编码委托工具 | `packages/agent/tools/coding_delegate.py` (新建) |
| 七 | Agent Skills 格式 + SkillsLoader + 示例技能 | `packages/agent/skills_loader.py` + `skills/manual/weather_query.md` |
| 八 | Alembic 数据库迁移（001_initial.py，9 表全量 schema） | `alembic/` |
| 九 | 语音管道接口占位 | `packages/voice/` + `types/voice.ts` |
| 十 | AgentCore 全管线改造（ContextBuilder + Notebook + Marker + coding_delegate） | `packages/agent/agent_core.py` |
| 十一 | 6 个 Notebook API + 前端标记工具 + thinking CSS 动画 | `http_channel.py` + `markers.ts` + `globals.css` |
| — | 测试：memory_integration 13/13 + empathy_injection 14/14 全绿 | — |

---

## 核心架构（V3.3 云端部署版）

```
外部世界 (Console / HTTP / 将来微信)
    │
    ▼
┌──────────────┐
│   Gateway    │  统一消息路由 + 主人校验 + 紧急熔断 + 频率限制
│  网关层      │  协议转换 → InternalEvent
└──────┬───────┘
       │ InternalEvent（进程内异步，asyncio.Queue + SQLite 持久化）
       ▼
┌──────────────┐
│  Agent 核心   │  ActorMind 推理链：感知→记忆检索→ContextBuilder(XML)→模型调用→标记解析→响应
│  引擎层      │  组件：人格锚点/情感引擎(PAD)/叙事记忆/Notebook/AttentionScheduler/coding_delegate
└──────┬───────┘
       │ ModelRouter（进程内路由）
       ▼
┌──────────────┐
│ 模型推理层    │  核心对话/推理/安全/共情: DeepSeek V4-Pro（双 Key 轮询）
│ 纯云端路由   │  后台记忆/反思/评价/情感/工具包装: DeepSeek V4-Flash
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Storage       │  SQLite 单文件（含 sqlite-vec 向量扩展）
│ 持久化层      │  表：conversation_logs / episodic_memories / emotion_snapshots
│              │       autobiography_entries / reflection_crystals / autonomy_settings
│              │       notebook_entries / scheduled_tasks（阶段7b）
│              │  每日备份 + Alembic 版本化迁移（阶段7d）
└──────────────┘
```

---

## 技术栈速查

| 层 | 技术 |
|----|------|
| 语言 | Python 3.12+ |
| 包管理 | uv |
| 云端模型 | DeepSeek V4-Pro（双 Key 轮询）, DeepSeek V4-Flash |
| 向量存储 | sqlite-vec（SQLite 原生向量扩展，零外部依赖） |
| 数据库 | SQLite（aiosqlite, WAL 模式），单文件 xilian.db |
| 前端 | React + TypeScript + Vite（全功能面板集成） |
| 日志 | loguru（结构化 JSON + trace_id） |
| 测试 | pytest + pytest-asyncio |
| 迁移 | Alembic（SQLite schema 版本化） |
| 部署 | `uv run python main.py` 一键启动，单进程 serve API + 前端 |

---

## 关键约定

1. **代码风格**：Python async/await，进程内调用（非微服务），dataclass 定义数据结构
2. **环境变量**：`.env` 管理 API Key，`.gitignore` 排除
3. **纯云端路由**：全量 DeepSeek，架构保留本地模型扩展点
4. **Git 提交**：做完功能就 commit，commit message 当变更日志
5. **人格提示词**：纳入 Git 版本管理，`prompts/CHANGELOG.md` 记录变更
6. **文件位置**：代码 `~/xilian-v3/`，计划文档 `/home/hezi/projects/xilian_plan/`

---

## 环境状态（台式机）

| 组件 | 版本/状态 |
|------|----------|
| Python | 3.12.3 |
| uv | 0.11.12 |
| Git | 2.43 |
| GPU | RTX 5070 Ti 16G (CUDA 13.2) — 当前方案无需 GPU |
| Docker Desktop | 29.4.2 + Compose v5.1.3 — 当前方案零 Docker 依赖 |
| .env API Key | 已配置 ✅ |

---

## 最近决策

- **2026-05-16**：阶段7完成。ContextBuilder 模块化（5 模块 XML 替代手工拼接）。Character Notebook 上线（auto_note + daily_diary + task_reminder）。AttentionScheduler 后台运行（5s tick + 5 层防打扰）。MarkerParser 5 种标记解析。Claude Code 编码委托工具 + Agent Skills 格式 + Alembic 迁移。语音管道接口占位（packages/voice/）。详细方案见 `xilian-phase7-design.md`。
- **2026-05-16**：阶段6完成。自主问候上线（想念值计算 + Token Bucket ≤3条/h）。一键部署完成（setup.sh + start.sh + 前端嵌入后端单进程 serve）。Console TUI 美化（rich 库）。砍独立梦幻循环（与阶段5自传体重叠），改为在自传体结尾追加睡前感想。
- **2026-05-15（大修订）**：V3.2 → V3.3 云端部署版。纯云端 DeepSeek（砍本地 Ollama/qwen3:14b）→ ChromaDB → sqlite-vec（零外部依赖）→ 砍 Redis（单用户过度设计）→ 砍微调（数据不足、面试难展示）→ 部署对标 OpenClaw：`uv run python main.py` 一键启动。
- **2026-05-14**：前缀缓存优化。`_build_messages()` 重构：系统提示只含纯静态人格，记忆/共情注入从 system prompt 移到用户消息末尾。预期效果：DeepSeek prefix caching 命中率大幅提升，响应延迟降低 ~40%，月 token 消耗降低 ~60%。
- **2026-05-12 深夜**：Qwen3.6-Plus 实测延迟 ~27s 不可接受 → 全量迁移至 DeepSeek。Pro→高质量（chat/empathy/reasoning/安全），Flash→后台（memory_encoding/reflection/dream/approval）。Pro 双 Key 轮询防限流。本地 first 任务 fallback 改走 Flash。
- **2026-05-12**：阶段2完成。情感分析走 DeepSeek V4-Pro。共情注入为昔涟风格自然语言。SQLite 开启 WAL 模式。EmotionGauge 原型用 Canvas 绘制雷达图。64/64 测试全绿。
- **2026-05-10**：架构审查完成，LiteLLM → ModelRouter 进程内路由，MCP 降级为可选适配器，AgentVisor 推迟至阶段9
- **2026-05-10**：人格提示词 v1→v2 精简（3000→~1800字），去 markdown 格式，语言标记更自然
- **2026-05-10**：阶段1完成，40/40 测试全绿

---

## 要看细节？

| 想了解 | 去读 |
|--------|------|
| 完整 10 阶段方案 | `xilian-v3.md` |
| 阶段 0 做了什么 | `xilian-phase0-checklist.md` |
| 阶段 1 做了什么 | `xilian-phase1-checklist.md` |
| 阶段 2 做了什么 | `xilian-phase2-checklist.md` |
| 阶段 3 做了什么 | `xilian-phase3-checklist.md` |
| 阶段 4 做了什么 | `xilian-phase4-checklist.md` |
| 阶段 5 做了什么 | `xilian-phase5-checklist.md` |
| 阶段 6 做了什么 | `xilian-phase6-design.md` |
| 阶段 7 设计方案 | `xilian-phase7-design.md` |
| 昔涟人格完整稿 | `~/xilian-v3/prompts/personality_v3.md` |
| 架构审查修订记录 | `xilian-v3.md` 末尾「审查修订记录」 |
