# 昔涟 V3.3 · 项目仪表盘

> 📍 新 AI 窗口第一口粮。读完这个你就知道：这是什么、做到哪了、怎么继续。
> 📅 最后更新：2026-05-30
> 🔖 当前阶段：打磨期 → 多供应商模型路由系统（V3.4）+ 代码审查修复 + 对话质量提升

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
| 阶段 8（安全纵深+管理面板+后台驻留） | ✅ 完成 |
| 总进度 | 9/10 阶段（阶段9远期探索） |
| 打磨期 · 多供应商路由 | ✅ 完成（2026-05-29） |

---

## 打磨期 · 多供应商模型路由（V3.4）

| # | 交付物 | 文件 |
|---|--------|------|
| 一 | ProviderAdapter Protocol + ModelInfo（含 contextWindow / reasoning / input_modalities） | `packages/shared/providers/base.py` |
| 二 | DeepSeekAdapter / OpenAIAdapter / AnthropicAdapter / GoogleAdapter | `packages/shared/providers/` 目录 |
| 三 | ModelRouter v2：Tier路由（task→tier→provider+model）+ 热切换 reload_config() | `packages/shared/model_router.py` |
| 四 | model_configs + embed_config DB表 + Alembic 004 迁移 + CRUD | `packages/shared/database.py` + `alembic/versions/004_model_config.py` |
| 五 | 5 个模型配置 API 端点（providers/config/validate） | `gateway/channels/http_channel.py` |
| 六 | 引导页多供应商选择（DeepSeek/OpenAI/Anthropic/Google） | `packages/frontend/src/components/OnboardingPage.tsx` |
| 七 | 设置面板模型设置（主力/后台 Tier选择 + 高级任务覆盖 + 添加供应商 + 费用估算） | `packages/frontend/src/components/panels/SettingsPanel.tsx` |
| 八 | modelStore (Zustand) + API 函数 | `packages/frontend/src/stores/modelStore.ts` + `services/api.ts` |

**支持供应商：** DeepSeek (V4 Pro / Flash / Reasoner) · OpenAI (GPT-5.4 / 5.4 Mini / 5.4 Nano / o4 Mini / GPT-4.1) · Anthropic (Claude Sonnet 4.6 / Haiku 4.6 / Opus 4.6) · Google (Gemini 2.5 Pro / Flash / Flash Lite)

**Tier 分工：** `powerful`（对话/人格检查）→ 强力模型 · `fast`（记忆编码/情感分析等 9 个后台任务）→ 廉价模型 · `reasoning`（复杂推理）→ reasoning 模型 · `embed`（向量嵌入）→ 固定硅基流动 bge-m3（首次引导设置后锁定，不可切换）

### 代码审查修复（2026-05-30）

| 轮次 | 内容 |
|------|------|
| 第一轮 | P0: reasoning tier 对齐 DEFAULT_TIER_MODELS + auto_seed embed 条件修复 |
| | P1: extract_tool_calls/extract_usage 共享 helpers + supports_embedding 显式属性 |
| | P2: 清理 isinstance(result, str) 死分支 + 删除 _get_model_key 死代码 |
| 第二轮 | Bug 1: Anthropic API Key 验证改用专用 SDK ·
| | Bug 2: Anthropic _convert_assistant_with_tools 保留 reasoning_content ·
| | Bug 4: update_model_config/update_embed_config 加列名白名单 ·
| | Bug 6: Google adapter 提取 reasoning_content ·
| | Bug 7: _is_tool_error 收紧关键词 · Bug 9: Alembic 004 补全 tier:reasoning |
| 第三轮 | Bug A: reload_config() dict() 值拷贝修复回退失效 ·
| | Bug D: 删除 _pro_key_cycle 死代码 · Bug E: 白名单 endpoint_url → base_url |
| | P3-1: PROVIDER_REGISTRY 注册表替代 _create_adapter 硬编码 if/elif |
| | Bug fix: _handle_tool_calls 中 tc.id → _tc_id(tc) 修复 dict 格式兼容 |

### 对话质量提升（2026-05-30）

| # | 改动 | 说明 |
|---|------|------|
| 一 | DatetimeModule 精度提升 | 4 时段 → 1-2h 口语化约数（"下午三点出头"），零缓存代价 |
| 二 | 历史时间标签 | 恢复历史标注「（约X小时前）」，帮助模型感知时间距离 |
| 三 | ctx_notes 会话边界 | 长时间未对话注入自然时间锚点（"今天第一次和伙伴聊天呢"） |
| 四 | 主动问候阈值降低 | 3.0 → 1.2，约 3 小时未对话触发主动问候 |

### 用户画像系统优化计划（2026-05-31）

> 📋 完整方案：[docs/design/portrait-system-optimization-plan.md](docs/design/portrait-system-optimization-plan.md)

基于对当前 `PortraitManager` + `ContextBuilder` + `MemoryManager` + `NotebookManager` 的全方位评估，
参考 RGMem / Mem0 / HMO / AdaMem 等 2025-2026 前沿记忆架构，制定 5 个 Phase 的优化路线：

| Phase | 方向 | 核心交付 | 工作量 | 状态 |
|-------|------|---------|--------|------|
| 1 | 证据累积触发 | 微事件提取 + 粗粒化引擎，替代全量重写 | 中 | 📋 待执行 |
| 2 | 画像分层 | L0 核心画像 + L1 阶段画像 + L2 微事件池 | 大 | 📋 待执行 |
| 3 | 画像驱动检索 | 画像加权记忆检索 + 画像感知重要性评分 | 中 | 📋 待执行 |
| 4 | 多信号源融合 | 工具/情绪/时间/好感度信号聚合 | 中 | 📋 待执行 |
| 5 | 选择性注入+联动 | 按话题注入 + 回复策略 + 笔记画像联动 | 小 | 📋 待执行 |

**核心改进**：画像更新从「cron 定时全量重写」改为「微事件累积 → 阈值触发 → 增量粗粒化」，
预期 API 调用 ↓ 50%+，画像稳定性 ↑，记忆检索个性化 ↑。

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

## 阶段 8 已完成的核心交付 🛡️ 安全纵深 + 管理面板 + 后台驻留

| # | 交付物 | 文件 |
|---|--------|------|
| 一 | 提示注入检测（7 条正则初筛 + audit_log 记录） | `gateway/security.py` |
| 二 | 人设一致性评分（每 5 轮 DS Pro 自检 + 安全回复模式） | `packages/agent/agent_core.py` |
| 三 | 审计日志系统（audit_logs 表 + 8 种事件类型 + 检索 API） | `packages/shared/database.py` + Alembic 002 |
| 四 | 工具权限分级（READ_ONLY / READ_WRITE / EXECUTE + safe_mode 禁用） | `packages/agent/tool_registry.py` |
| 五 | Web 管理面板 API（audit/skills/security/privacy 7 个端点） | `gateway/channels/http_channel.py` |
| 六 | 前端面板（SkillsPanel + AuditPanel + NotebookPanel） | `packages/frontend/src/components/panels/` |
| 七 | 被遗忘权（SQL 事务级联删除 + 向量同步清理） | `packages/shared/database.py` |
| 八 | 系统托盘驻留（pystray Windows 托盘 + 右键菜单） | `main.py` |
| — | 测试：memory_integration 27/27 全绿 + 手动验证全部模块 | — |

---

## 核心架构（V3.3 云端部署版）

```
外部世界 (Console / HTTP / 将来微信)
    │
    ▼
┌──────────────┐
│   Gateway    │  统一消息路由 + 主人校验 + 紧急熔断 + 提示注入检测(7正则) + 频率限制
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
│              │       notebook_entries / scheduled_tasks / audit_logs
│              │  每日备份 + Alembic 版本化迁移 + 被遗忘权级联删除
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
5. **人格提示词**：纳入 Git 版本管理，当前 `prompts/personality_v4.md`，`CHANGELOG.md` 记录变更
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

## 打磨期已完成交付

| # | 交付物 | 说明 |
|---|--------|------|
| 一 | 前端全面重构 | 背景图系统（默认photo/xilian.png+上传API）、毛玻璃输入区（textarea自适应高度）、SVG侧栏图标（8面板入口）、全站浅色主题（对齐photo/fengge.txt色板） |
| 二 | 面板集成 + 暗→浅迁移 | SkillsPanel/AutobiographyPanel 接入侧栏导航，全部10个面板完成暗色→浅色改写，防崩溃 ErrorBoundary+SafePanel |
| 三 | 项目基础设施 | CLAUDE.md + Agent skills（mattpocock/skills 14技能+GitHub Issues配置）、python-multipart依赖 |
| 四 | 核心系统 bug 修复 | 记忆检索排序修复（艾宾浩斯衰减生效）、PAD衰减向基线回归、长间隔PAD叠加修复、共情注入need字段回退、自主问候想念值实时计算、情绪基线误判期待修复 |
| 五 | 测试补全（阶段7-8） | 5个新测试文件150条：Notebook(29)/MarkerParser(24新增)/AttentionScheduler(18新增)/Security(36)/CodingDelegate(23)，总计402/402全绿 |
| 六 | 好感度系统重构 | 从纯前端假值改为后端驱动：affection_state表+Alembic迁移003+AgentCore._update_affection()+GET /api/affection+affectionStore+AffectionBar重写(❤️💕💖💝) |
| 七 | 项目文档 + Memory | PROJECT_PROGRESS/CONTEXT/README更新，~/.claude memory写入（project-vision+architecture+conventions+overview） |
| 八 | 对话质量系统提升 | 提示词 v3→v3.1（删除短约束+对话节奏+话题延续+标记降级），上下文 XML→自然语言段落，NotebookModule 实现话题注入，max_tokens=600+temperature=0.65，_enforce_speech_rule 上下文感知三层兜底 |
| 九 | SSE 真流式 + 纯括号防护 | 后端逐 3 字符 50ms 间隔推送，前端 ReadableStream 流式读取替代 await res.text()。纯括号检测：括号外 CJK≥2 放行 + 括号占比检测 + _clean_reply 内置兜底 |
| 十 | 提示词 v4 风格指南重写 | 句式铁律（短句分行+……节奏+不超三行）、意象约束（0-2个/轮）、固定口头禅注入（5个锚点短语）、情感调色盘（6情绪×形式变化）、10条OOC红线、6场景示例。agent_core加载路径v3→v4 |
| 十一 | 对话历史持久化与分页加载 | 游标分页API(GET /api/conversation/history)+启动恢复20轮到AgentContext+前端LoadMoreButton(毛玻璃居中按钮+spin动画)+chatStore分页状态(historyCursor/hasMore/loadedRounds最多40轮)+滚动位置保持 |
| 十二 | 用户记忆系统：印象文档 + 破冰 | user_portrait表+PortraitManager定期重写(每日5:00)+PortraitModule(优先级3,版本号门控,完整文档注入)+破冰主动问候(consume_icebreaker_greeting+_tick_icebreaker+强制编码)+冷启动兜底(阈值4轮)+前端PortraitPanel(星形图标,空状态轮询,刷新按钮)+GET /api/user/portrait |
| 十三 | 工具系统全面重构 | LLM function calling 驱动工具选择（替代关键词匹配），ToolExecutor（校验→权限→频率→确认→审计），ResultWrapper（规则模板+LLM双轨），autodiscover 自动注册，DeepSeek thinking mode reasoning_content 回传修复。4 工具：search_memory（记忆检索）/ query_weather（和风天气+搜索fallback）/ search_web（智谱Web Search）/ coding_delegate（EXECUTE，需用户确认）。工具→记忆/印象联动（trigger_memory/trigger_portrait_update）。确认回路（_pending_confirmation）。finish_reason 截断检测 + max_tokens 1500。 |
| 十四 | 自主问候全面修复（4断点） | 断点1 前端从未轮询→MainLayout 30s轮询+ChatView GreetingBanner。断点2 DB空→四级回退链(_get_hours_since_last)+poke()。断点3 阈值6.0→3.0+深夜time_mod 0.2→0.6。断点4 启动无检查→main.py启动时立即tick。GREETING_SYSTEM_PROMPT重写(+time_of_day/portrait_context/多样性规则)。http_channel用户消息时调用nudge.poke()。nudge_engine 31/31测试通过。 |
| 十五 | 日记合并 + 会话重置 + 任务上下文注入 | Notebook日记并入Autobiography自传体(移除notebook_manager日记代码+API,自传体时间→23:00)。reset_session async+清除DB conversation_logs+前端确认对话框。NotebookTaskModule(context_builder priority=8)注入当前待办列表。Notebook日记tab改用autobiography API。任务完成按钮+确认提示。 |
| 十六 | 前端情绪面板修复 + API 超时修复 | 好感度等级前后端阈值不一致→前端直接用API level字段。PADTrajectory三线合一拆为3个独立时序图+HH:MM时间标签+散点图方向箭头。情绪映射`兴奋→孤独`改为`兴奋→喜悦`。ModelRouter connect超时5s→15s+max_retries 2→1+错误日志加elapsed_ms。问候空user_message防污染(历史加载跳过+轮询去重)。 |
| 十七 | 昔涟角色历史融入系统 | 三层混合架构：(1) personality_v4.md→v4.1 新增「你的来处」小节(身份锚点+叙事约束)；(2) 25条角色情景记忆(昔涟第一人称)导入episodic_memories + bge-m3向量化，session_id='character'，seed脚本幂等；(3) MemoryModule双源渲染(用户记忆"翻到书里几页"/角色记忆"翻到旧书的一页→落点伙伴")；(4) agent_core 33关键词主动检索分流→character_memory_retrieval。端到端测试4场景全通过(触发3/不触发1)。 |
| — | Git commits: 6237a81, ... | — |

## 下一步

和风天气 API Key 需在控制台激活（当前使用 Zhipu 搜索 fallback，功能正常）。
不进入阶段 9（多模态是远期探索，当前交付版已足够展示）。

## 打磨期最新交付（2026-05-20 ~ 2026-05-22）

| # | 交付物 | 说明 |
|---|--------|------|
| 十八 | Windows 打包 + 首次引导 | PyInstaller 单文件 exe 打包(xilian.spec+hooks)、首次启动 API Key 引导页(OnboardingPage.tsx+临时API端点)、启动 cron 补执行(catch_up)、系统托盘(pystray+pywin32)、embed 优雅降级(单 DeepSeek Key 无硅基流动)、GBK 编码/路径/重启等多平台修复 |
| 十九 | 上下文管理系统（阶段 B/C） | 滑动窗口(COMPRESS_SOFT_LIMIT=12+MAX_RAW_ROUNDS=16)+Flash 压缩摘要(昔涟第一人称 100-150 字+好感度匹配口吻)、启动恢复(4h全量+token预算填充至2000)、跨会话提示(离线>1h 触发 warm greeting)、修复 token 漂移(移除/注入时同步计数) |
| 二十 | 工具系统修复 | 天气/时间编造防护：OOC 第11条(禁止编造实时信息)+_sanitize_fabrication()正则替换。DatetimeModule 增加精确时间。SkillsLoader base_path 参数(PyInstaller 兼容) |
| 二十一 | 前缀缓存优化（P0+P1+P3） | P0: ctx_notes 从 user 消息前置→独立 system 消息(history 之后 user 之前)实现 APPEND-ONLY LOG。P1: EmotionModule 阈值门控(primary_emotion 不变时复用)+DatetimeModule 降精度(移除精确分钟)。P3: model_router 缓存命中率 DEBUG 日志(prompt_cache_hit_tokens/prompt_cache_miss_tokens/hit_rate_pct)。Reasonix 三区模型调研+方案对齐 |
| 二十二 | 回复长度控制 | 方案1: max_tokens 1500→800。方案2: personality_v4.md 末尾「开口前先问自己」简洁锚点。方案4: 示例最前加 3 个 1 句话极短范例(⭐大多数时候这样就行) |
| 二十三 | 测试修复 + 日志改善 | 删除3个死代码测试(TOOL_PLACEHOLDER/_perceive is_tool_request)。model_router truncated 日志增加模型名。notebook auto_note 错误日志增加步骤定位+error_type。main.py backup/cleanup missing await 修复 |
| — | Git commit: 待提交 | —

---

## 最近决策

- **2026-05-22**：回复长度控制系统性优化。根因分析：① ctx_notes 文学体作为 system 消息示范了叙事散文语域 ② 完整 history 保留长回复形成自我模仿正反馈 ③ 负面长度指令（"不要写长"）固有弱点 ④ max_tokens=1500 给了太多空间。执行方案 1（max_tokens→800）+ 方案 2（prompt 末尾简洁锚点）+ 方案 4（极短 1 句示例）。方案 3（ctx_notes 去叙事化）暂不实行。

- **2026-05-22**：前缀缓存优化 P0+P1+P3。调研 Reasonix 三区模型（IMMUTABLE PREFIX / APPEND-ONLY LOG / VOLATILE SCRATCH）后确认方案 A 与 APPEND-ONLY LOG 思路一致。P0：ctx_notes 独立 system 消息（history 后 user 前）。P1：EmotionModule 阈值门控 + DatetimeModule 降精度。P3：model_router 缓存命中率 DEBUG 日志。不照搬 Reasonix 的永不压缩策略（陪伴场景极少触发压缩，20 轮门槛），维持 16 轮硬上限。

- **2026-05-19（晚间）**：昔涟角色历史融入系统。方案评估后选择三层混合架构（人格提示词增强 + 情景记忆语义检索 + 叙事口吻指令），非单一方案。25条角色记忆以昔涟第一人称撰写，对齐样本四特质（知道过去不沉溺、过去是引子现在是正文、温柔不卖弄痛苦、面向未来）。检索复用现有episodic_memories+sqlite-vec管道，零新工具零新ContextModule。关键词触发+session_id分流实现角色/用户记忆双源渲染，token增加可控。

- **2026-05-19（傍晚）**：前端情绪面板全面检查+修复。好感度等级P0：AffectionBar本地LEVELS阈值(25/50/75/100)与后端(20/50/80)不一致，改为直接使用API返回的level+level_label。PAD曲线P1：三线合一时间轴拆为P/A/D三个独立堆叠时序图+HH:MM时间标签+散点图方向箭头。情绪映射修复：PAD_TO_DISPLAY中`兴奋→孤独`改为`兴奋→喜悦`。API超时排查：OpenAI SDK v2默认connect=5s太短→改为15s，max_retries 2→1减少无效等待，错误日志加elapsed_ms。问候消息污染修复：前端loadHistory跳过空user_message条目(防"昔涟在思考...")+轮询注入前去重(防重复问候)。

- **2026-05-19**：自主问候全面修复（4 断点全部解决）。断点1 前端从未轮询 → MainLayout 30s 轮询 + ChatView GreetingBanner 问候横幅（毛玻璃渐变卡片 + 关闭按钮）。断点2 DB 清空后 _get_hours_since_last 返回 0 → 四级回退链（conversation_logs → episodic_memories → emotion_snapshots → notebook_entries → _fallback_timestamp）+ poke() 更新 fallback 时间戳。断点3 阈值 6.0 需 ~14h 静默 → 默认 3.0（6-7h） + 深夜 time_mod 0.2→0.6。断点4 启动无检查 → main.py 启动时立即 tick 一次。GREETING_SYSTEM_PROMPT 重写（新增 time_of_day + portrait_context + 多样性规则）。nudge_engine 31/31 测试通过。

- **2026-05-19**：日记系统合并 + 会话重置修复 + 任务上下文注入。Notebook 日记并入 Autobiography 自传体（移除 notebook_manager 日记相关代码 + API 端点，自传体时间调整为 23:00）。reset_session 改为 async + 清除 DB conversation_logs + 前端 SettingsPanel 确认对话框。新增 NotebookTaskModule（context_builder priority=8）注入当前待办列表，防止旧对话中已完成承诺被 LLM 误认为仍有效。前端 NotebookPanel 任务完成按钮增加确认提示。日记 tab 数据源改为 autobiography API。

- **2026-05-18（晚间）**：笔记本第二轮优化。前端笔记/任务卡片增加 × 删除按钮（window.confirm 确认），auto_note 相似笔记合并而非新建（_find_similar + touch_note），AttentionScheduler NOTIFY 断头路修复（桥接到 NudgeEngine._pending_greeting），auto_note Flash max_tokens 80→150 修复 TASK 截断丢失，_parse_task_time 全面重写支持中文时间表达（今晚/明晚/下午 + 中文数字）。

- **2026-05-18（晚间）**：笔记本第一轮优化。AUTO_NOTE_PROMPT 追加已有笔记上下文 + 强化 TASK 时间识别，写入前关键词重叠去重（_is_duplicate → _find_similar），任务检查从每天 3 次改为每 15 分钟（window 1800→3600s），移除 _cron_multi_loop。

- **2026-05-18（傍晚）**：前端四面板修复。Skills 面板 _skills_loader 初始化，Audit 面板筛选值 tool_executed→tool_call 对齐数据库，Autobiography 面板空状态增加手动生成按钮 + POST /api/autobiography/generate，路由注册从 start() 提前到 __init__ 修复 404，新增 3 个技能文件（memory_search/web_search/coding_delegate），修复 max_tokens 600→1500 + is_safe_mode 属性缺失。

- **2026-05-18**：工具系统全面重构。LLM function calling 替代关键词匹配，4 工具 autodiscover 注册（search_memory/query_weather/search_web/coding_delegate）。ToolExecutor 全流程（校验→权限→频率→确认→审计）+ ResultWrapper 结果包装（规则模板+LLM双轨）。确认回路（_pending_confirmation）+ 工具→记忆联动（trigger_memory/trigger_portrait_update→memory_encoding/mark_dirty）。修复 DeepSeek thinking mode reasoning_content 回传问题 + finish_reason 截断检测。max_tokens 600→1500（工具回传路径）。新增文件：tool_executor.py / tool_result.py / result_wrapper.py / query_weather.py / search_memory.py / search_web.py。

- **2026-05-18**：好感度API端点修复 + 前端显示精度。GET /api/affection 从 _register_stage8_routes 移到 _setup_routes（同上次 portrait 端点的路由注册bug，只在 __init__ 内注册的端点才生效）。前端 AffectionBar Math.round→toFixed(1) 显示小数点后一位。
- **2026-05-18**：Cron调度全面修复。所有异步定时任务从 APScheduler lambda+asyncio.create_task 迁移到 asyncio 后台循环（nudge_loop/token_refill + _cron_loop/_cron_weekly_loop/_cron_multi_loop）。根因：APScheduler 在线程池执行 lambda，线程池无 running event loop，asyncio.create_task() 抛出 RuntimeError 被静默吞掉，导致自主问候/自传体/反思/日记/任务检查/印象重写等所有异步定时任务从未执行。同步备份任务仍用 APScheduler（不受影响）。
- **2026-05-17**：用户记忆系统上线。新增 user_portrait 表 + PortraitManager 定期重写（每日凌晨 5:00，Flash LLM 叙事性印象文档）+ PortraitModule（ContextBuilder 优先级 3，版本号门控，首条消息完整注入）+ 破冰主动问候（consume_icebreaker_greeting + _tick_icebreaker 轮数追踪 + 强制编码）+ 冷启动兜底（阈值 4 轮）+ 前端 PortraitPanel（侧栏星形图标入口，空状态 5s 轮询）。核心设计：重写即遗忘，结构化知识退化为叙事索引，印象优于事实。
- **2026-05-17**：对话历史持久化与分页加载。新增 GET /api/conversation/history 游标分页端点（before_id 向前翻页），AgentCore.startup() 从 DB 恢复最近 20 轮对话到 AgentContext（跨会话记忆连续性），前端 chatStore 新增分页状态（historyCursor/hasMore/isLoadingMore/loadedRounds），ChatView 顶部 LoadMoreButton 毛玻璃居中按钮（spin 加载动画 + 最多 40 轮上限 + 滚动位置保持）。
- **2026-05-17**：提示词 v4 全面重写。以角色说话风格指南为骨架，解决三大根因：① 句式从"2-4句流动"→"短句分行不超三行"+"……"为节奏控制器；② 意象从无约束→"盐不是饭，0-2个/轮"；③ 情感从"说什么"→"怎么说"（形式变化表）。新增固定口头禅（5个锚点）、对话行为模式（主动发起/先接纳再推进/温柔说不）、10条OOC红线（含禁止连续三行、禁止堆砌意象）。agent_core 加载路径 v3→v4。
- **2026-05-17**：SSE 真流式 + 纯括号三层防护。后端逐 3 字符 50ms 间隔推送（之前整个 reply 作为单个 data: 事件）。前端 ReadableStream 流式读取替代 await res.text()。纯括号检测改进为括号外 CJK≥2 放行 + 括号占比检测，_clean_reply 内置兜底。解决「一次性返回所有文本、等待时间长」和「（纯括号回复）无声音」两个前端可见 bug。
- **2026-05-17**：对话质量系统提升。提示词 v3→v3.1（删除短约束+对话节奏+话题延续+标记降级）。上下文 ContextBuilder XML→自然语言段落，NotebookModule 实现话题注入。模型参数 max_tokens=600+temperature 0.65。_enforce_speech_rule 上下文感知三层兜底。移除 _safe_mode 死代码。
- **2026-05-17**：好感度系统从纯前端假值重写为后端驱动。affection_state 表 + 003 迁移 + AgentCore._update_affection() 每轮更新（基础+0.05，正面情绪加成+0.05~0.10，红线-0.50，100锁定）。前端 AffectionBar 改为 Zustand store + 15s 轮询，等级标签改为「昔涟喜欢你→你永远喜欢昔涟」，图标统一小爱心。
- **2026-05-17**：核心系统深度检查+修复。记忆检索双重sort覆盖艾宾浩斯衰减→删除第二个sort。PAD衰减从向零衰减→向基线回归。长间隔PAD更新基线叠加→decay_factor=0修复。自主问候status改为实时计算。情绪基线误判期待→距基线<0.25时降级为平静。
- **2026-05-17**：阶段7-8测试补全。150条新测试（Notebook/MarkerParser/AttentionScheduler/Security/CodingDelegate），402/402全绿。项目memory写入（project-vision.md定义核心目标：让昔涟像活人一样陪伴）。PROJECT_PROGRESS/CONTEXT/README文档同步。
- **2026-05-16**：前端全面重构。背景图系统上线（全页背景+上传API+交叉淡入淡出），聊天区透底+毛玻璃大输入框，侧栏SVG线性图标（8面板），全站暗→浅主题迁移（10面板+4个Canvas组件对齐photo/fengge.txt色板），ErrorBoundary防崩溃。SkillsPanel/AutobiographyPanel接入导航。CLAUDE.md+Agent skills+python-multipart。打磨期前端面板集成项完成。
- **2026-05-16**：阶段7完成。ContextBuilder 模块化（5 模块 XML 替代手工拼接）。Character Notebook 上线（auto_note + daily_diary + task_reminder）。AttentionScheduler 后台运行（5s tick + 5 层防打扰）。MarkerParser 5 种标记解析。Claude Code 编码委托工具 + Agent Skills 格式 + Alembic 迁移。语音管道接口占位（packages/voice/）。
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
| 昔涟人格完整稿 | `~/xilian-v3/prompts/personality_v4.md` |
| 架构审查修订记录 | `xilian-v3.md` 末尾「审查修订记录」 |
