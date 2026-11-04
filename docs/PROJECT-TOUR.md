# 项目现状导读（PROJECT TOUR）

> 给"半年没碰、基本忘了"的人用。两条路线：**30 分钟版**（弄清这是什么、现在在哪）和 **2 小时版**（能动手改）。
> 配合 `CONTEXT.md`（代码导航）和 `PROJECT_PROGRESS.md`（进度/决策）看。

---

## 0. 一句话

昔涟是一个"情感陪伴型 Agent"：不是客服机器人，而是有记忆、有情绪、有笔记本、会主动找你的角色。技术上是**单进程 Python 服务**：FastAPI 起 HTTP，SQLite 存一切（含向量），React 打包成静态页由后端 serve，打包成 exe 双击就能用。

## 1. 30 分钟版

### 1.1 先跑起来（5 分钟）

```bash
cd D:\xilian-v3
uv run pytest -q --ignore=tests/test_personality_regression.py   # 应看到 676 passed / 8 skipped
uv run python main.py                                            # 打开 http://127.0.0.1:8000
```

看到的就是她：聊天、侧栏 10 个面板（情绪雷达 / 记忆 / 笔记本 / 自传 / 画像 / 设置…）。

### 1.2 弄清 3 条主链路（15 分钟）

| 链路 | 起点 | 关键文件 |
|---|---|---|
| **对话**：消息 → 上下文 → 模型 → 回复 | `POST /api/chat/stream` | `gateway/channels/http_channel.py` → `packages/agent/agent_core.py::process()` |
| **工具**：模型要调工具 → 执行 → 回填 | `agent_core` 内 | `packages/agent/loop/`（新）/ `tool_executor.py`（旧执行器） |
| **记忆**：每轮结束后编码、检索、遗忘 | `agent_core` 尾部 | `packages/agent/memory_manager.py` + `packages/shared/vector_store.py` |

上下文不是"把历史全塞进去"，而是 7 个模块按优先级拼（时间/画像/情绪/记忆/笔记/好感度/待办）：
`packages/agent/context_builder.py`。

### 1.3 知道现在在哪（10 分钟）

- 测试基线：**676 passed / 8 skipped / ~32s**（真模型人格测试默认排除）。
- 新循环 `LOOP_V2` **本机已开启**（`.env` 里 `LOOP_V2=1`）；代码默认 0，只有回滚时才需要动它。老路径 `_handle_tool_calls` 仍保留作回退。
- P0–P3 + X + M1 + P1.5 已完成：新循环骨架、接线、SSE 工具事件、会话级确认状态机、40 条评测基线、时间保真 + 多步提示、ModelPolicy/重试降级/stats、真 token 流。
- 下一步：M 二阶段 DSH 风格声明式路由配置；评测侧剩 `memory` 长尾口语变体与 `weather-01` 关键词类失败观察。

## 2. 2 小时版（能动手改）

### 2.1 结构（20 分钟）

```
packages/
  agent/        # 大脑：agent_core(主流程) context_builder(上下文) memory/notebook/portrait(长期状态)
    loop/       # 新：预算式工具循环（P0–P2）
    tools/      # 4 个工具：search_memory / query_weather / search_web / coding_delegate
    pipeline/   # 感知 / 多模态 / 记忆检索
  shared/       # 基建：model_router(多供应商) database/(6 个 repo) vector_store providers/
  frontend/     # React + Vite + Zustand
gateway/        # HTTP 通道（所有 API + SSE）
prompts/        # 人格提示词（版本化，v4.1）
data/           # xilian.db（SQLite + sqlite-vec）、角色记忆、贴纸
```

### 2.2 用 codegraph 代替"翻文件"（20 分钟）

```bash
codegraph status
codegraph explore "记忆检索"          # 相关符号 + 源码 + 调用路径
codegraph callers AgentCore.process
codegraph impact ToolExecutor.execute
```

### 2.3 读代码的顺序（60 分钟）

1. `agent_core.py::process()` —— 一条消息的完整生命周期（感知 → 上下文 → 模型 → 工具 → 副作用）。
2. `packages/agent/loop/runner.py` —— 新循环（每步带 tools、结构化回填、预算）。
3. `packages/agent/context_builder.py` —— 上下文里到底有什么。
4. `packages/shared/model_router.py` —— 模型怎么选（tier → provider → adapter）。
5. `gateway/channels/http_channel.py` —— 前端能看到什么（SSE 事件）。

### 2.4 改一个小东西验证理解（20 分钟）

例：给 `DatetimeModule` 加上完整日期（现在只有"星期X 晚上 10 点多"，没有年月日）。
改完跑测试 → 启动 → 问"今天几号"，看她是否答对。这就是 X 阶段（已完成）；下一步是 M2 DSH 风格声明式路由配置。

## 3. 我们最近改了什么、为什么（对照表）

| 改动 | 当时的问题 | 做法 | commit |
|---|---|---|---|
| 迁移到 Windows 单目录 | WSL 开发 + D 盘打包，两份代码/两个库 | 合并为 `D:\xilian-v3`，补齐镜像源 | — |
| 空回复显式降级 | 模型截断后 `content` 为空，被兜底模板伪装成台词 | 重试一次 → 仍空则明确降级 + 日志 | `a40b060` |
| 语音兜底引用当轮消息 | 兜底读 history，答非所问地回忆 150 天前 | 记录 `_current_user_msg` | `a40b060` |
| 模型统一 flash | Pro 太贵；名字也不对（供应商推荐 `deepseek-flash`） | 改配置 + 适配器别名 + 未知模型兜底 Flash | `a40b060` |
| thinking 开关 | 推理吃预算导致空回复；短回复成本高 30× | `DEEPSEEK_DISABLE_THINKING=1` | `6621c60` |
| 新循环 P0 | 旧循环回传时不带 tools，多步工具链不可能 | 新建 `packages/agent/loop/` | `5d106c2` |
| 接线 + SSE P1 | 新循环没人调用；前端看不到工具过程 | `LOOP_V2` 开关 + `tool_call/tool_result` 事件 + 气泡 | `add88d5` `e90f256` |
| 确认状态机 P2 | 旧的 pending 是进程内单槽，多会话会串 | `ConfirmationStore` 按会话 + TTL | `31d6385` |
| 确认后执行修复 | `ToolExecutor` 无条件返回 PENDING，确认了也执行不了 | `confirmed=True` 旁路 | `6a015f3` |
| 评测集 P3 | 工具调用质量只能靠体感 | 40 条 JSONL + runner + 指标；loop 97.5% / legacy 82.5% | `3c383f2` |
| 时间保真 X | 日期/时间没有 ground truth，模型编造 | `DatetimeModule` 完整日期 + HH:MM；事实 100% | `3cf4069` |
| 多步提示 | loop 只调天气、不调第二类工具 | 多意图 system 提示 + P3 用例校准；多步 100% | `9450d4f` |
| 模型路由 M1 | tool 错误静默禁用 24h；无能力矩阵/统计 | `ModelPolicy` + 重试/15m 降级 + stats | `7879eb3` |
| 真 token 流 P1.5 | 正文要等完整回复再按 3 字符/50ms 切片 | `StreamAccumulator` 接 raw stream；SSE 即时转发 + 标记过滤 | `b58ea94` |
| 多 AgentCore 工具丢失 | 第二个实例 autodiscover 拿到空 registry | `_AVAILABLE` 缓存重放 | `7f76d1f` |

## 4. 快速自检（确认项目没坏）

```bash
uv run pytest -q --ignore=tests/test_personality_regression.py   # 676 passed
uv run python -c "import main"                                    # 导入无副作用
uv run python main.py                                             # 本机已是新循环（LOOP_V2=1）
# 需要对比老路径时：LOOP_V2=0 uv run python main.py
```

## 5. 常见困惑（先看这里，别急着翻代码）

| 困惑 | 答案 |
|---|---|
| "为什么有 `_handle_tool_calls` 又有 `loop/`？" | 旧的单轮逻辑仍在线（`LOOP_V2=0`），新的在开关后面；验证完再删旧的 |
| "为什么回复是 3 字 50ms 跳出来的？" | `LOOP_V2=0` 老路径仍是**假流式**（先算完再切片）；`LOOP_V2=1` 已接真 token 流（P1.5） |
| "为什么确认后还是没执行？" | 已修（`6a015f3`）。若在旧 exe 上看到，需要重新打包 |
| "为什么测试有 8 个 skip？" | 需要外部条件（API Key / 平台）的用例 |
| "为什么记忆好像没长？" | 工具调用触发记忆依赖 `trigger_memory`，新路径已透传；老路径不变 |
