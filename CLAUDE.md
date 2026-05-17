# 昔涟 V3.3

> 个人情感陪伴型 AI Agent。核心角色：三千万世轮回的记录者，自称「人家」称用户「伙伴」。9/10 阶段完成，打磨期。

## 启动

```bash
uv run python main.py          # 全栈启动
cd packages/frontend && npm run dev  # 前端开发模式
```

## 关键文件

- `PROJECT_PROGRESS.md` — 项目仪表盘（进度/决策/环境）
- `CONTEXT.md` — 代码导航（目录树/数据流/模块职责）
- `main.py` — 启动入口
- `packages/agent/agent_core.py` — AgentCore 核心大脑
- `packages/shared/events.py` — InternalEvent 统一消息结构
- `gateway/channels/http_channel.py` — FastAPI 所有 API 端点（含对话历史分页 /api/conversation/history）
- `packages/shared/database.py` — SQLite 11 表 CRUD + 游标分页查询
- `packages/agent/portrait_manager.py` — 用户印象文档管理器（定期重写 + 冷启动）
- `packages/agent/nudge_engine.py` — 自主生命节律引擎（想念值计算 + 主动问候 + AttentionScheduler）
- `packages/frontend/src/` — React 前端

## 技术约定

- Python 3.12+ async/await，uv 包管理
- DeepSeek V4-Pro + V4-Flash 纯云端路由（ModelRouter）
- SQLite (aiosqlite, WAL) + sqlite-vec 向量扩展，零外部依赖
- React + TypeScript + Vite + Zustand，前端嵌入后端单进程 serve
- loguru 结构化日志：`logger.bind(trace_id=...).info("模块.动作", **kwargs)`
- 测试：pytest + pytest-asyncio，asyncio_mode = "strict"
- 环境变量：.env 管理 API Key，.gitignore 排除
- 人格提示词纳入 Git 版本管理：`prompts/personality_v4.md`

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
