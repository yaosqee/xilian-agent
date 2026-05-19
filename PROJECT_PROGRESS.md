# 昔涟 V3.3 · 项目仪表盘

> 📍 新 AI 窗口第一口粮。读完这个你就知道：这是什么、做到哪了、怎么继续。
> 📅 最后更新：2026-05-19 14:00 CST
> 🔖 当前阶段：阶段 8 ✅ 完成 → 打磨期（自主问候全面修复 + NotebookTaskModule + 日记合并）

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
| — | Git commits: 6237a81, ... f661aef | — |

## 下一步

和风天气 API Key 需在控制台激活（当前使用 Zhipu 搜索 fallback，功能正常）。
不进入阶段 9（多模态是远期探索，当前交付版已足够展示）。

---

## 最近决策

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
