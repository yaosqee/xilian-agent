# 昔涟 V3.2 · 项目仪表盘

> 📍 新 AI 窗口第一口粮。读完这个你就知道：这是什么、做到哪了、怎么继续。
> 📅 最后更新：2026-05-13 21:00 CST
> 🔖 当前阶段：阶段 3 ✅ 完成 → 等待进入阶段 4

---

## 一句话定位

**昔涟 (Xī Lián)** — 个人情感陪伴型 AI Agent，盒子自用，非产品化。
核心角色：三千万世轮回的记录者，温柔来自看过悲欢后的清明，自称「人家」称用户「伙伴」。

---

## 当前状态

| 项目 | 状态 |
|------|------|
| 阶段 0（奠基+安全） | ✅ 完成 |
| 阶段 1（解耦+人格+工具预埋） | ✅ 完成 |
| 阶段 2（情感感知+原型） | ✅ 完成 |
| 阶段 3（情景记忆+前端） | ✅ 完成 |
| 总进度 | 4/10 阶段 |

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
| — | ModelRouter 路由调整（empathy → DeepSeek V4-Pro） | `packages/shared/model_router.py` |

---


## 阶段 3 已完成的核心交付

| # | 交付物 | 文件 |
|---|--------|------|
| 一 | 数据库扩展：episodic_memories + message_queue 表 + CRUD |  (+~480行) |
| 二 | MemoryManager 情景记忆全管线 |  (新建) |
| 三 | AgentCore 记忆管道改造 + shutdown |  |
| 四 | AgentContext 记忆注入实现 |  |
| 五 | BackupManager 每日备份 |  (新建) |
| 六 | HTTP API 扩展（5 个新端点） |  |
| 七 | 前端骨架：Pi 风格聊天 + EmotionGauge |  (28 文件) |
| 八 | 50 条集成测试 |  +  +  +  |

## 核心架构（文字版）

```
外部世界 (Console / HTTP / 将来微信)
    │
    ▼
┌──────────────┐
│   Gateway    │  统一消息路由 + 主人校验 + 紧急熔断 + 频率限制
│  网关层      │  协议转换 → InternalEvent
└──────┬───────┘
       │ InternalEvent（进程内异步，阶段6后引入Redis）
       ▼
┌──────────────┐
│  Agent 核心   │  ActorMind 推理链：感知→共情注入→人格加载→模型调用→响应
│  引擎层      │  组件：人格锚点/情感引擎(✓)/叙事记忆/技能进化/规划器/生命节律(逐步填充)
└──────┬───────┘
       │ ModelRouter（进程内路由）
       ▼
┌──────────────┐
│ 模型推理层    │  核心对话/推理/安全/共情: DeepSeek V4-Pro（双 Key 轮询）
│ 混合路由     │  后台长文/编码/反思: DeepSeek V4-Flash · 本地优先: qwen3:14b · 7/15可切本地/阶段5可切微调
└──────────────┘
```

---

## 技术栈速查

| 层 | 技术 |
|----|------|
| 语言 | Python 3.12+ |
| 包管理 | uv |
| 本地模型 | Ollama (qwen3:14b, bge-m3) |
| 云端模型 | DeepSeek V4-Pro (双 Key 轮询), DeepSeek V4-Flash, Qwen3.6-Plus (备用) |
| 向量库 | ChromaDB (Docker) |
| 数据库 | SQLite (aiosqlite, WAL 模式), Redis 阶段6引入 |
| 前端 | React + TypeScript + Vite (EmotionGauge 原型已完成) |
| 日志 | loguru (结构化 JSON + trace_id) |
| 测试 | pytest + pytest-asyncio |
| 容器 | Docker Desktop + Compose |
| GPU | RTX 5070 Ti 16G |

---

## 关键约定

1. **代码风格**：Python async/await，进程内调用（非微服务），dataclass 定义数据结构
2. **环境变量**：`.env` 管理 API Key，`.gitignore` 排除
3. **过渡期路由**：`.env` 中 `TRANSITION_MODE=cloud`（当前），7/15后切 `local_base`，阶段5微调后切 `finetuned`
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
| GPU | RTX 5070 Ti 16G (CUDA 13.2) |
| Ollama (Windows) | v0.23.2, 模型: qwen3:14b, bge-m3 |
| Docker Desktop | 29.4.2 + Compose v5.1.3 |
| ChromaDB 容器 | 运行中 |
| .env API Key | 已配置 ✅ |

---

## 最近决策

- **2026-05-12**：阶段2完成。情感分析走 DeepSeek V4-Pro（JSON 结构化输出稳定）。共情注入为昔涟风格自然语言（非结构化指令），注入到系统提示动态段落而非对话历史。SQLite 开启 WAL 模式。EmotionGauge 原型用 Canvas 绘制雷达图。测试 64/64 全绿。
- **2026-05-12 深夜**：Qwen3.6-Plus 实测延迟 ~27s 不可接受 → 全量迁移至 DeepSeek。Pro→高质量（chat/empathy/reasoning/安全），Flash→后台（memory_encoding/reflection/dream/approval）。Pro 双 Key 轮询防限流。本地 first 任务 fallback 改走 Flash。
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
| 昔涟人格完整稿 | `~/xilian-v3/prompts/personality_v2.md` |
| 架构审查修订记录 | `xilian-v3.md` 末尾「审查修订记录」 |
