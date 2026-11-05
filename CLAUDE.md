# 昔涟 V3.7

> 个人情感陪伴型 AI Agent。核心角色：三千万世轮回的记录者，自称「人家」称用户「伙伴」。9/10 阶段完成，打磨期。多供应商模型路由 + 代码审查修复 + 架构优化（database 拆分 / agent_core 提取）。

## 启动

```bash
uv run python main.py                # 全栈启动（Windows 原生，D:\xilian-v3）
uv run pytest -q --ignore=tests/test_personality_regression.py   # 688 passed / 25s
cd packages/frontend && npm run dev  # 前端开发模式
```

环境要点（2026-11-03 起）：

- 唯一工作目录是 `D:\xilian-v3`（WSL 副本已退役）；打包也在同一目录，不再需要复制。
- PyPI 直连超时：`UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`。
- 对话模型 `deepseek-flash`（存在 DB `model_configs`，设置面板可切）。
- thinking：**生产与评测一致：`.env` 已设 `DEEPSEEK_DISABLE_THINKING=1`（关闭）**；A/B 数据见 `docs/plans/agent-loop-v2.md` §7.3.1。
- codegraph 用 CLI（`codegraph query/explore`）；当前工具链未接 MCP。
- `tests/test_personality_regression.py` 是**真模型**用例：会写真库、跑 5 分钟、结果不确定，默认排除。

## 关键文件

- `PROJECT_PROGRESS.md` — 项目仪表盘（进度/决策/环境）
- `docs/PROJECT-TOUR.md` — 现状导读（30 分钟 / 2 小时两条路线，先读这个）
- `CONTEXT.md` — 代码导航（目录树/数据流/模块职责）
- `docs/design/tool-system-audit-and-redesign.md` — 工具系统设计文档
- `main.py` — 启动入口
- `packages/agent/agent_core.py` — AgentCore 核心大脑（LOOP_V2 分支 + 会话级确认 + 多意图提示 + 记忆联动）
- `packages/agent/loop/` — 预算式 Agent 循环（events/executor/runner/streaming/confirmation；P0–P3 + P1.5）
- `packages/agent/tool_registry.py` — 工具注册表（autodiscover 多实例重放 + OpenAI格式）
- `packages/agent/tool_executor.py` — 工具执行器（校验→权限→频率→确认→审计；`confirmed` 旁路）
- `packages/agent/result_wrapper.py` — 结果包装器（规则模板 + LLM双轨；仅老路径）
- `packages/agent/tools/` — 4 个工具：search_memory / query_weather / search_web / coding_delegate
- `packages/shared/providers/` — 多供应商适配器 + ProviderAdapter Protocol + `model_policy.py`（ModelPolicy 能力矩阵）
- `packages/shared/model_router.py` — 路由 + tool 重试/15m 降级 + `model_stats` 观测 + `tool_decision` 任务
- `packages/shared/model_config.py` — M2-1 声明式路由配置加载/校验/解析（未接 router）
- `config/model_routing.toml` — 当前路由默认基线（TOML）
- `docs/design/model-routing-m2.md` — M2 计划与 M2-1 实施记录
- `packages/shared/events.py` — InternalEvent（含 `user_id` / `session_id`）
- `gateway/channels/http_channel.py` — FastAPI 所有 API 端点 + SSE（工具事件 + 真 token 流转发）
- `evals/` — P3 评测集（40 条 JSONL + runner/metrics）；报告在 `docs/evals/`
- `packages/shared/database/` — DatabaseManager 拆分为 6 个领域 Repository（V3.7）
- `packages/shared/database/_manager.py` — DatabaseManager 主类（生命周期 + 跨表操作）
- `packages/agent/portrait_manager.py` — 用户印象文档管理器
- `packages/agent/nudge_engine.py` — 自主生命节律引擎（想念值 + TokenBucket + GreetingBanner）
- `packages/agent/context_builder.py` — 模块化上下文注入（7模块；Datetime 含完整日期 + HH:MM）
- `packages/agent/notebook_manager.py` — 笔记本管理器（笔记/关注/任务，日记已并入自传体）
- `data/character_memories.json` — 昔涟角色情景记忆（25条，session_id='character'）
- `scripts/seed_character_memories.py` — 角色记忆导入脚本（幂等，bge-m3向量化）

## 技术约定

- Python 3.12+ async/await，uv 包管理
- DeepSeek 纯云端路由：对话 `deepseek-flash`，`tier:reasoning` 保留 `deepseek-v4-pro`（ModelRouter）
- Agent 循环：**本机 `.env` 已设 `LOOP_V2=1`**（走 `packages/agent/loop/`：预算/结构化回填/会话确认/真 token 流）；代码默认 0，回滚删掉该项即可
- 模型路由：`ModelPolicy` 能力矩阵 + tool 错误「重试一次 → 15m 降级」+ `model_stats`；配置仍是 env + DB tier/override；M2-1 已加 TOML 加载器，尚未接线
- SQLite (aiosqlite, WAL) + sqlite-vec 向量扩展，零外部依赖，~13 张表
- React + TypeScript + Vite + Zustand，前端嵌入后端单进程 serve
- loguru 结构化日志：`logger.bind(trace_id=...).info("模块.动作", **kwargs)`
- 测试：pytest + pytest-asyncio，asyncio_mode = "strict"
- 环境变量：.env 管理 API Key，.gitignore 排除
- 人格提示词纳入 Git 版本管理：`prompts/personality_v4.md`（当前 v4.1）
- 工具系统：LLM function calling 驱动，4 工具 autodiscover 注册，README_ONLY 自主 / EXECUTE 需确认
- 外部 API Key（QWeather / Zhipu）仅存储在 .env，不入 git，不写入文档
- 工具新增只需一个文件：在 `packages/agent/tools/` 下创建 + `@register_tool` 装饰器

## 前端风格

- 浅色梦幻风，对齐 `photo/fengge.txt` 色板（樱粉 `#FFB7C5`/淡紫 `#D8B4E2`/文字 `#5E4B66`）
- 毛玻璃卡片必须同时：`background: rgba(255,255,255,0.6) + backdrop-filter: blur(12px) + border: 1px solid rgba(255,255,255,0.8)`
- 禁止纯黑 `#000` / 纯白 `#FFF`，阴影只用粉色/紫色系彩色弥散阴影
- 动效 0.4-0.6s，cubic-bezier(0.4, 0, 0.2, 1)

## Agent skills

### Issue tracker

GitHub Issues on `yaosqee/xilian-agent`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default canonical labels (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context — one `CONTEXT.md` + `docs/adr/` at repo root. See `docs/agents/domain.md`.
