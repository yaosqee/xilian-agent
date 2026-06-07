# 代码审查问题记录

> **执行纪律**：每轮只发现不修复 → 全部完成后统一审核确认 → 确认后才修复

---

## 第〇轮：自动化工具扫描

### 工具清单
- ruff (未使用 import、代码风格、潜在 bug)
- vulture (死代码检测)
- mypy (宽松模式类型检查)
- grep TODO/FIXME/HACK/XXX

### 扫描结果

#### R0-001: 未使用的 import — 源码文件 (ruff F401)  ⚠️ 需确认后清理

| # | 文件 | 行 | 未使用项 |
|---|------|----|---------|
| 1 | `gateway/channels/console_channel.py` | 8 | `import sys` |
| 2 | `gateway/channels/console_channel.py` | 21 | `from rich.live import Live` |
| 3 | `gateway/channels/console_channel.py` | 22 | `from rich.spinner import Spinner` |
| 4 | `gateway/channels/http_channel.py` | 65 | `import re` |
| 5 | `main.py` | 44 | `from packages.shared import ModelRouter` |
| 6 | `packages/agent/agent_core.py` | 17 | `import os` |
| 7 | `packages/agent/agent_core.py` | 1621 | `import random` (函数内) |
| 8 | `packages/agent/autobiography_writer.py` | 8 | `import asyncio` |
| 9 | `packages/agent/autobiography_writer.py` | 9 | `import time` |
| 10 | `packages/agent/coarse_grain_engine.py` | 15 | `from typing import Optional` |
| 11 | `packages/agent/context_builder.py` | 341 | `import re` (函数内) |
| 12 | `packages/agent/emotion_analyzer.py` | 8 | `import math` |
| 13 | `packages/agent/emotion_analyzer.py` | 10 | `import asyncio` |
| 14 | `packages/agent/emotion_analyzer.py` | 11 | `import time` |
| 15 | `packages/agent/emotion_core.py` | 15 | `from typing import Optional` |
| 16 | `packages/agent/emotion_core.py` | 422 | `import random` (函数内) |
| 17 | `packages/agent/memory_manager.py` | 529 | `import math` (函数内) |
| 18 | `packages/agent/notebook_manager.py` | 7 | `import asyncio` |
| 19 | `packages/agent/notebook_manager.py` | 8 | `import json` |
| 20 | `packages/agent/nudge_engine.py` | 11 | `import json` |
| 21 | `packages/agent/nudge_engine.py` | 13 | `from typing import Optional` |
| 22 | `packages/agent/skills_loader.py` | 6 | `import asyncio` |
| 23 | `packages/shared/database.py` | 656 | `import math` (函数内) |
| 24 | `packages/shared/model_router.py` | 10 | `import time` |
| 25 | `packages/shared/vector_store.py` | 9 | `import asyncio` |
| 26 | `alembic/versions/005_notebook_due_date.py` | 8 | `import sqlalchemy as sa` |

> 共 26 处未使用的 import。函数内 import 的 `random`、`math`、`re` 等需要检查是否原本打算使用但遗漏了逻辑。

#### R0-002: 赋值后未使用的变量 (ruff F841)  ⚠️

| # | 文件 | 行 | 变量 | 备注 |
|---|------|----|------|------|
| 1 | `gateway/channels/http_channel.py` | 117 | `agent` | `agent = self` 闭包引用未使用 |
| 2 | `gateway/channels/http_channel.py` | 288 | `profile` | `profile = engine.state.compute_profile()` 未使用 |
| 3 | `packages/agent/agent_core.py` | 131 | `new_tools` | `new_tools = self.tool_registry.autodiscover(...)` 未使用 |
| 4 | `packages/agent/autobiography_writer.py` | 263 | `emo` | `emo = mem.get("emotion_tags", "")` 未使用 |
| 5 | `packages/agent/emotion_analyzer.py` | 167 | `valence_norm` | 计算后未使用 |
| 6 | `packages/agent/emotion_core.py` | 439 | `response_text` | 函数内赋值后未使用 |
| 7 | `packages/agent/emotion_core.py` | 443 | `personality_profile` | 函数内赋值后未使用 |
| 8 | `packages/agent/nudge_engine.py` | 569 | `memories` | 赋值后未使用 |
| 9 | `packages/shared/model_router.py` | 48 | `default_model` | 赋值后未使用 |

#### R0-003: f-string 无占位符 (ruff F541)  🟡

| # | 文件 | 行 |
|---|------|----|
| 1 | `main.py` | 413 |
| 2 | `main.py` | 424 |
| 3 | `main.py` | 636 |

#### R0-004: 模糊变量名 (ruff E741)  🟡

- `main.py:578` — `l` 变量名（lambda 常见，但此处应为更有意义的名称）

#### R0-005: vulture 死代码 — 高置信度需确认  🔴

以下为 vulture 报告的可能死代码（排除 FastAPI 路由嵌套函数等已知误报）：

| # | 文件 | 行 | 符号 | vulture 判断 |
|---|------|----|------|-------------|
| 1 | `gateway/security.py` | 21 | `FilterResult` class | unused (60%) |
| 2 | `gateway/mcp/adapter.py` | 49 | `list_tools` method | unused (60%) |
| 3 | `gateway/mcp/adapter.py` | 61 | `call_tool` method | unused (60%) |
| 4 | `main.py` | 538 | `save_config` function | unused (60%) |
| 5 | `main.py` | 599 | `debug_config` function | unused (60%) |
| 6 | `main.py` | 612 | `check_config` function | unused (60%) |
| 7 | `packages/agent/agent_core.py` | 497 | `_user_sent_sticker` attr | unused (60%) |
| 8 | `packages/agent/agent_core.py` | 2106 | `affection_score` property | unused (60%) |
| 9 | `packages/agent/emotion_core.py` | 478 | `_last_appraisal_time` attr | unused (60%) |
| 10 | `packages/agent/nudge_engine.py` | 646 | `should_exit` attr | unused (60%) |
| 11 | `packages/shared/database.py` | 1808 | `embed_batch` method | unused (60%) |
| 12 | `packages/shared/model_router.py` | 557 | `route_with_override` method | unused (60%) |
| 13 | `packages/shared/providers/__init__.py` | 105 | `ProviderConfig` class | unused (60%) |
| 14 | `packages/shared/vector_store.py` | 140 | `delete_many` method | unused (60%) |
| 15 | `hooks/hook-sqlite_vec.py` | 20,23,25 | `binaries`, `datas` | unused (60%) |

> **注意**：vulture 对动态调用（注册表/路由/反射）有大量误报。以上仅列出置信度较高且非明显动态调用的条目，需人工确认。

#### R0-006: vulture 已知误报（已排除）  ✅

以下 vulture 报告经判断为误报：
- `http_channel.py` 所有嵌套函数 → FastAPI 路由装饰器注册，vulture 无法追踪
- Provider adapter 类（`AnthropicAdapter`, `DeepSeekAdapter` 等）→ 通过 `PROVIDER_REGISTRY` 动态注册
- `base.py` Protocol 字段（`provider_name`, `supports_streaming` 等）→ Protocol 定义，子类实现
- `console_channel.py` `YELLOW_HEX`/`GREEN_HEX` → 可能在其他文件引用或用于富文本输出

#### R0-007: TODO/FIXME 遗留标记  🟡

| # | 文件 | 行 | 内容 |
|---|------|----|------|
| 1 | `packages/shared/marker_parser.py` | 204 | `# TODO(阶段 9): 实现完整 SSML 转换` |
| 2 | `packages/shared/providers/anthropic.py` | 264 | `# TODO: when enabling Anthropic extended thinking` |

#### R0-008: 测试文件未使用的 import (ruff F401)  🟡

| # | 文件 | 行 | 未使用项 |
|---|------|----|---------|
| 1 | `tests/test_coarse_grain_engine.py` | 12 | `from unittest.mock import MagicMock` |
| 2 | `tests/test_console_channel.py` | 10 | `import asyncio` |
| 3 | `tests/test_emotion_appraisal.py` | 16,17 | `EmotionState`, `APPRAISAL_SYSTEM_PROMPT` |
| 4 | `tests/test_emotion_core.py` | 7,8 | `import math`, `import pytest` |
| 5 | `tests/test_http_channel.py` | 11,19 | `import json`, `ToolRegistry` |
| 6 | `tests/test_micro_event_extractor.py` | 12,17,18 | `patch`, `EXTRACT_PROMPT`, `MIN_CONFIDENCE` |
| 7 | `tests/test_notebook_manager.py` | 10 | `from unittest.mock import patch` |
| 8 | `tests/test_nudge_engine.py` | 9,11,19 | `asyncio`, `json`, `ProactiveDecision` |
| 9 | `tests/test_persona_boost.py` | 13,16 | `import math`, `patch` |
| 10 | `tests/test_personality.py` | 13 | `import asyncio` |
| 11 | `tests/test_personality_regression.py` | 12 | `pytestmark` |
| 12 | `tests/test_portrait_guidance.py` | 6,10,11 | `os`, `asyncio`, `tempfile` |
| 13 | `tests/test_portrait_integration.py` | 15 | `import time` |
| 14 | `tests/test_portrait_integration.py` | 64 | `LEGACY_PORTRAIT` |
| 15 | `tests/test_security.py` | 11,13 | `patch`, `FilterResult` |
| 16 | `tests/test_security_stage8.py` | 4 | `import pytest` |
| 17 | `tests/test_skills_coding.py` | 4,6,8 | `pytest`, `tempfile`, `Skill` |

#### R0-009: 测试文件未使用变量 (ruff F841)  🟡

| # | 文件 | 行 | 变量 | 备注 |
|---|------|----|------|------|
| 1 | `tests/test_http_channel.py` | 91 | `event` | 赋值后未使用 |
| 2 | `tests/test_micro_event_extractor.py` | 194 | `events` | 赋值后未使用 |
| 3 | `tests/test_micro_event_extractor.py` | 279 | `id2` | 赋值后未使用 |

#### R0-010: TypeScript 检查  ✅

`tsc --noEmit` 通过，零类型错误。

#### R0-011: mypy 检查  ⚠️

mypy 因 `packages/shared/events.py` 模块路径冲突未能完成全量扫描（需配置 `--explicit-package-bases` 或调整 MYPYPATH）。待后续轮次补充。

---

## 第一轮：核心路径逐文件 Review

### P0 — 当前修改文件

#### R1-P0-001 `database.py` — Bare except 吞异常（多处） 🔴

多处 `except Exception: pass` 模式，异常被完全忽略且无日志：
- **L393-L398**: Alembic ALTER TABLE 加 images 列 → `except Exception: pass`
- **L446-L451**: `_manual_init()` 中同样的 ALTER TABLE → `except Exception: pass`
- **L457-L461**: `trigger_memory_id` ALTER TABLE → `except Exception: pass`
- **L467-L472**: `due_date` ALTER TABLE → `except Exception: pass`
- **L1805-L1808**: `insert_session_summary` ROLLBACK → `except Exception: pass`
- **L2136-L2137**: forget_user_data 向量清理失败 → 仅有 log 但无回滚

**风险**：这些 silently pass 的异常可能掩盖真正的 schema 错误（如 SQL 语法错误、表被锁等）。迁移列确实需要幂等，但应该 **至少 log 异常类型** 或仅忽略 "duplicate column" 错误。

#### R1-P0-002 `database.py` — SQL 注入风险（LIKE 查询） 🔴

**L2353**: `delete_expired_images` 中：
```python
await self._conn.execute(
    "SELECT COUNT(*) as cnt FROM conversation_logs WHERE images LIKE ?",
    (f"%{sp}%",),
)
```
虽然使用了参数化查询（`?`），LIKE 通配符在参数中是安全的。但 `stored_path`（`sp`）值从 DB 读取，若被恶意写入含有 `%`/`_` 的值会匹配意外的行。**低风险但需注意防御深度**。

#### R1-P0-003 `database.py` — `forget_user_data` 未清理 `autobiography_entries` 和 `reflection_crystals` 🔴

**L2107-L2113**: `forget_user_data()` 删除表列表缺少：
- `autobiography_entries`
- `reflection_crystals`
- `uploaded_images`

用户请求"删除所有数据"后这些表的数据仍然保留，违反"被遗忘权"语义。

#### R1-P0-004 `database.py` — `forget_user_data` 中向量删除使用同步 sqlite3 连接 🔴

**L2127-L2134**: 在 async 上下文中创建同步 `sqlite3.connect()`：
```python
vec_conn = _sync_sqlite.connect(str(self.db_path))
```
这会阻塞事件循环。应使用 `aiosqlite` 或 `run_in_executor`。

#### R1-P0-005 `database.py` — `insert_log` 缺少事务保护 ⚠️

**L525-L551**: `insert_log` 只有 `await self._conn.commit()`，如果 INSERT 成功但 commit 失败（连接中断），无重试机制。与其他方法一致（都无事务保护），但考虑其关键性值得注意。

#### R1-P0-006 `database.py` — `get_emotion_stats` 嵌套循环 O(n²) 🟡

**L997-L999**: 计算 PAD 最大距离：
```python
for i in range(len(pads)):
    for j in range(i + 1, len(pads)):
        dist = ...
```
当数据量大时（如 7 天有 200+ 快照），复杂度为 O(n²)。可用 min/max 近似代替。

#### R1-P0-007 `http_channel.py` — `_register_notebook_routes` / `_register_stage8_routes` 闭包引用 🟡

**L710-L765, L769-L832**: 这些方法在 `__init__` 中调用，使用 `agent = self._agent` 捕获引用。如果 `__init__` 时 `self._agent` 为 None（构造函数中确实可能为 None），这些路由将永久持有 `agent = None`。虽然后续 setter 会重新赋值 `self._agent`，路由闭包中的 `agent` 不会更新。

**L714**: `notebook_notes()` 等路由中 `agent` 可能为 None → 返回空列表。需确认运行时 `self._agent` 是否在 `__init__` 调用时已赋值。

#### R1-P0-008 `http_channel.py` — 图片上传 DB 写入异常被吞 🟡

**L876-L887**: `upload_image()`:
```python
try:
    await self._agent._db.insert_image(...)
except Exception:
    pass  # DB 非关键路径
```
DB 写入失败无日志，后续排查困难。即使是"非关键路径"也应记录 WARNING。

#### R1-P0-009 `http_channel.py` — `update_model_config` 直接写 `os.environ` ⚠️

**L1101, L1121-1124, L1129-1132**: API 端点中直接修改 `os.environ`。在多 worker 环境下只影响当前进程，其他 worker 不会感知。且无锁保护，并发请求可能导致竞态。应通过 ModelRouter 的配置热重载统一管理。

#### R1-P0-010 `http_channel.py` — `validate_api_key` 对未配置的供应商返回 `valid: True` 🟡

**L1187-L1188**: 
```python
if not base_url:
    return {"valid": True, "note": "无法验证此供应商，请直接使用"}
```
未知供应商返回 `valid: True` 会误导前端以为 Key 可用。应返回 `valid: null` 或增加 `unverified: true` 标记。

#### R1-P0-011 `agent_core.py` — 重复的 `_perceive()` 调用（已修复但需确认） ✅

Git diff 显示移除了重复的 `_perceive()` 调用（原 L515-L516），已修复。

#### R1-P0-012 `agent_core.py` — `process()` 过长（~290行） ⚠️

`AgentCore.process()` 方法承担了感知→检索→构建→模型调用→工具→情感→记忆→日志的全流程，维护困难。建议按 `ActorMind` 阶段拆分为子方法。

#### R1-P0-013 `agent_core.py` — `_encode_image_memory` 实体关键词列表硬编码 🟡

**L1039-L1042**: `entity_keywords` 列表硬编码在方法内。若需调整需改代码，建议提取为类常量或配置文件。

#### R1-P0-014 `agent_core.py` — `memory_task` 生命周期管理中 `image_description` 初始值覆盖 🟡

**L527**: `image_description = ""`
**L723-L727**: 后台任务等待后重新赋值 `image_description`：
```python
if memory_task:
    image_description = await memory_task
```
问题是 **L542**: Fallback 路径已经给 `image_description` 赋值了，Native 路径下 `image_description` 为 ""。然后 L723 重新等待 `memory_task` 获取结果。这个流程是正确的（Native 路径不等待，fallback 直接获取），但变量重赋值使逻辑不够清晰。

#### R1-P0-015 `agent_core.py` — `_build_speech_fallback` 中 `import random` 未使用 ✅

已被 R0-001 捕获 — `random` 导入了但实际使用在 `_should_auto_sticker` 和 `_pick_sticker_by_emotion` 中。`_build_speech_fallback` 自己的 `import random` 确实未使用。

#### R1-P0-016 `model_router.py` — `_init_default_adapter` 未处理 provider 创建失败 ⚠️

**L100-L132**: 若 `_create_adapter("deepseek")` 返回 None（缺少 SDK），仍然配置了 `_tier_configs`（L105-L116），导致 `route()` 中 TierConfig 存在但 adapter 为 None → 每个请求都会尝试创建 adapter 失败。

#### R1-P0-017 `model_router.py` — `route()` 中 fallback adapter 未检查 `supports_tools` 🟡

**L397-L403**: 当 target provider 不可用时，fallback 到第一个可用 adapter，但未重新检查该 adapter 是否支持工具调用。可能导致工具支持的模型被降级。

#### R1-P0-018 `model_router.py` — Tool error retry 无次数限制 🔴

**L429-L442**: 当 tools error 发生时，retry 一次但不设上限。如果 retry 也失败（如其他 error），exception 会 propagate 到 agent_core 的 catch-all → 返回 DEGRADED_REPLY。但第一次 attempt 的异常信息丢失。**更严重的是**：如果第一次 attempt 是 tool error 但 retry 也是 tool error（如模型确实不支持 tools），retry 的异常会直接 raise，不会再被 `_is_tool_error` 捕获（因为已经不带 tools 了）。

#### R1-P0-019 `model_router.py` — `reload_config()` 回退后旧 adapter 引用可能失效 ⚠️

**L319-L335**: 回退时将 `old_adapters` 等赋值回 self，但 `initialize()` 中可能已经 `clear()` 了这些 dict（L154-L156）。回退逻辑使用 `dict()` 拷贝，避免了引用被清空。✅ 正确但依赖拷贝行为，缺少注释说明设计意图。

#### R1-P0-020 `useChat.ts` — SSE `buffer` 处理可能导致消息截断 🟡

**L42-L63**: SSE parser 按 `\n` 分割 buffer，但 SSE 标准使用 `\n\n`（双换行）作为消息边界。如果 data 字段包含 `\n`（如多行 JSON），会被错误分割。不过当前 data 是简单 token 字符串，实际影响小。

#### R1-P0-021 `api.ts` — `postChatStream` 缺少超时处理 🟡

流式请求无超时设置。如果后端挂住不发 `[DONE]`，前端会永久等待。建议添加 `AbortSignal.timeout()` 或请求级超时。

#### R1-P0-022 `api.ts` — `fetchPADHistory` 和 `fetchEmotionHistory` 完全重复 🟢

**L85-L88**: `fetchPADHistory` 调用完全相同的端点 `fetchEmotionHistory`。应删除一个或明确其差异。

#### R1-P0-023 `agent_core.py` — `_should_auto_sticker` 中 `compute_profile()` 重复计算 ⚠️

**L1441-L1455**: `_should_auto_sticker` 调用 `state.compute_profile()`，而 `_pick_sticker_by_emotion` 又调用一次（L1467）。`compute_profile()` 可能包含 LLM 调用或重计算，每个 process 周期可能调用 2-3 次。

#### R1-P0-024 `database.py` — `delete_expired_images` 使用 `f-string` 构建 SQL 🔴

**L2371-L2374**:
```python
await self._conn.execute(
    f"DELETE FROM uploaded_images WHERE id IN ({placeholders})",
    ids_to_delete,
)
```
虽然 `placeholders` 是由 `",".join(["?"] * len(ids_to_delete))` 生成的（安全），但 f-string 构建 SQL 本身就是危险模式。应使用显式 SQL 构建函数或添加注释说明安全性。

### P1 — 核心大文件

#### R1-P1-001 `memory_manager.py` — `retrieve_memories` 异步 gather 无超时 ⚠️

**L564-L568**: 画像加权阶段并行嵌入记忆摘要时使用 `asyncio.gather(*embed_tasks, return_exceptions=True)`，无 timeout。若 `_embed_text` 中 ModelRouter 调用超时或卡住，整个检索会被阻塞。

#### R1-P1-002 `nudge_engine.py` — `calculate_missing_value` 子步骤异常完全静默 🟡

**L329-L389**: 四个子步骤各自 try/except 返回 fallback 值。若 DB 连接临时断开，不会报错但使用错误 fallback（如 `hours_ago=0` 或系统启动时间），导致想念值计算严重不准却无告警。

#### R1-P1-003 `nudge_engine.py` — 问候生成使用链式 `.replace()` 存在模板注入风险 🟡

**L432-L438**: 上下文变量若含 `{` 字符会被后续 `.replace()` 误替换。应使用 `string.Template` 或带安全转义的模板引擎。

#### R1-P1-004 `emotion_core.py` — `EmotionState.decay()` 修改内存状态但进程重启丢失衰减 🟡

情绪衰减仅更新内存 PAD 坐标。若进程重启，重启之前最后一次 DB snapshot 到重启之间的衰减周期丢失。

#### R1-P1-005 `tool_executor.py` — `_record_call` 方法从未被调用 🔴

**L164-L169**: `_record_call` 定义了但在 `execute()` 方法中从未调用。`_check_rate_limit` 读取 `_call_counts` 但成功执行后不会记录时间戳 → **频率限制永远无法达到阈值**（只清理不添加）→ 工具限频机制完全失效。

#### R1-P1-006 `tool_executor.py` — `inspect.signature` 每次执行都调用 🟢

**L126-L129**: 每次工具执行都 `inspect.signature(func)` 检查是否接受 ctx 参数。高频工具调用时增加不必要开销。可缓存检测结果。

#### R1-P1-007 `context_builder.py` — `render_with_budget` 和 `render_with_budget_async` 90% 代码重复 ⚠️

两个方法仅 render 调用方式不同，其余逻辑完全一致。应提取公共辅助函数减少维护成本。

#### R1-P1-008 通用 — 日志格式不一致 (f-string vs structured) 🟡

代码库中混用：
- `logger.info(f"xxx → {host}:{port}")` — f-string
- `logger.info("agent.startup_complete")` — 结构化
不一致导致按 key 聚合/告警困难。建议统一为结构化格式（key=value）。

#### R1-P1-009 通用 — 函数内重复导入标准库 🟢

`import json`, `import time`, `import re`, `import random` 在多个函数/方法内部重复导入。虽不影响性能（Python 缓存），但增加代码噪音。

### P2 — 中等文件

#### R1-P2-001 `portrait_manager.py` — 高复杂度模块，需专项审查

画像管理器涉及 L0/L1/L2 三级级联、微事件提取、粗粒化引擎联动、冷启动破冰等多个子系统交织。当前审查未覆盖其全部交互面。**建议作为第二轮架构级检查的重点目标。**

#### R1-P2-002 `coarse_grain_engine.py` — 依赖画像管理器广播更新

粗粒化引擎触发 L2→L1→L0 更新后通过 portrait_manager 广播。广播失败时的降级路径需确认是否健全。

#### R1-P2-003 Provider Adapters 通用 — Protocol 定义子类实现不完整验证

`base.py` 定义 `ProviderAdapter` Protocol，但无运行时检查确保各子类实现了所有 required 方法。若某 adapter 缺少方法，会在运行时 `AttributeError` 而非启动时明确报错。

### P3 — 小文件

#### R1-P3-001 `tools/search_memory.py` / `tools/query_weather.py` / `tools/search_web.py` / `tools/coding_delegate.py`

四个工具的代码结构健康，无紧急问题。`coding_delegate.py` 中的 CLI 工具路径检测（`_find_claude()`）有较好的降级处理。

#### R1-P3-002 `gateway/security.py` — `FilterResult` 类被 vulture 标记为未使用 ⚠️

需确认 `FilterResult` 是否被其他模块通过动态导入使用。若确实未被引用，应移除。

#### R1-P3-003 `hooks/hook-sqlite_vec.py` — PyInstaller hook 文件 ⚠️

被 vulture 标记为 `binaries`/`datas` 变量未使用。hook 文件是 PyInstaller 的特殊入口，其命名约定决定行为。需确认这些变量是否必需或应清理。

#### R1-P3-004 `skills_loader.py` — `asyncio` 导入未使用 ✅

已被 R0-001 捕获。

---

## 第二轮：架构级检查

### R2-001: 零循环依赖 ✅

Import 图分析确认整个代码库无循环依赖。模块依赖方向清晰：
```
gateway/ → packages/agent/ → packages/shared/
tests/   → gateway/ + packages/
main.py  → gateway/ + packages/
```

### R2-002: `database.py` God Object 🔴

**104 个方法，2403 行，管理 13+ 张表**。职责横跨：
- 对话日志 (conversation_logs)
- 情景记忆 + 嵌入 (episodic_memories)
- 消息队列 (message_queue)
- 情感快照 (emotion_snapshots)
- 自传体 + 反思 (autobiography_entries, reflection_crystals)
- 笔记本 + 任务 (notebook_entries, scheduled_tasks)
- 审计日志 (audit_logs)
- 好感度 (affection_state)
- 用户画像 (user_portrait, core_profile, phase_profile)
- 微事件 + 会话摘要 (micro_events, session_summaries)
- 工具使用日志 (tool_usage_log)
- Cron 运行记录 (cron_runs)
- 模型配置 (model_configs, embed_config)
- 图片上传 (uploaded_images)

**建议**：拆分为 4-5 个 Repository 类：
- `ConversationRepository` — 对话日志
- `MemoryRepository` — episodic_memories + 向量
- `EmotionRepository` — emotion_snapshots
- `ProfileRepository` — user_portrait + core_profile + phase_profile
- `NotebookRepository` — notebook_entries + scheduled_tasks

拆分后可渐进迁移，不改变现有调用方的接口签名。

### R2-003: `agent_core.py` God Object 🔴

**导入 18 个模块（全项目最高 fan-out），2276 行**。`process()` 方法 290 行涵盖全部 ActorMind 阶段 + 多模态 + 工具调用 + 情感 + 记忆 + 日志。

**建议**：按 ActorMind 阶段提取独立 Pipeline：
```
感知 → 记忆检索 → 共情注入 → 记忆注入 → 人格加载 → 模型调用 → 响应
```
但注意：当前的"一条到底"设计有原子性优势——拆分过早可能导致中间状态不一致。**建议暂不拆分 process() 本身，先拆分 database.py，再重构 agent_core 内部辅助方法**。

### R2-004: Provider Adapter 模式一致 ✅（一次例外）⚠️

5 个主要 adapter 均正确实现 Protocol：
- 所有有 `provider_name`, `supports_streaming`, `supports_tools`, `supports_embedding` 等类属性
- 所有有 `@staticmethod get_available_models()`
- 所有实现 `chat()`, `embed()`

**例外**: `MiMoAdapter.describe_image()` 不在 Protocol 中定义，仅在 `agent_core._describe_image()` 通过 Duck Typing 调用。新增 adapter 如果需要 `describe_image` 会运行时 AttributeError。建议在 Protocol 中声明为 optional 方法（`NotImplementedError` 默认实现）。

### R2-005: 事件流契约清晰 ✅

Gateway → Channel → Agent 的依赖链使用回调模式：
```python
# gateway.py:38
await channel.start(self.agent.process)  # 传递 process 方法引用
```
各 Channel 通过 `EventHandler = Callable[[InternalEvent], Awaitable[AgentResponse]]` 协议接收，松耦合设计正确。`InternalEvent` 结构在 `shared/events.py` 统一定义，全链路一致。

### R2-006: `InternalEvent` 字段使用 linter 误报 ✅

`events.py` 的 `InternalEvent` 有多个字段（`images`, `sticker`, `metadata` 等），部分在 console_channel 中不传 → mypy/vulture 会误报"未使用"——这些是协议字段，不同 channel 传不同子集是正确的。

### R2-007: 数据库连接管理 — 双连接模式 🟡

系统维护两个独立的 SQLite 连接：
1. `DatabaseManager._conn` — `aiosqlite` 异步连接，用于所有 CRUD
2. `VectorStore._conn` — 同步 `sqlite3` 连接，因为 `sqlite-vec` 扩展需要直接操作

两者指向同一个 `.db` 文件。WAL 模式下读写可并发，但需注意：
- 同步连接会阻塞事件循环（已在 `forget_user_data` L2127 处发现）
- 事务隔离：两个连接看不到彼此未提交的更改

### R2-008: 配置热重载的原子性 ⚠️

`model_router.reload_config()` 的备份-重试-回退模式正确（L319-L335），但 `http_channel.update_model_config` 直接写 `os.environ` 绕过了 ModelRouter 的热重载机制。**两套配置更新路径不一致** — API 写 DB + os.environ → 手动调 reload_config() 才生效。应统一为：API 只写 DB → 自动触发 reload_config()。

### R2-009: 模块边界总结

| 模块 | 行数 | 职责 | 健康度 |
|------|------|------|--------|
| `database.py` | 2403 | 全部数据访问 | 🔴 需拆分 |
| `agent_core.py` | 2276 | 全部业务逻辑 | 🔴 需拆分 |
| `context_builder.py` | 989 | 上下文组装 | 🟡 可接受 |
| `nudge_engine.py` | 867 | 自主问候 | 🟡 可接受 |
| `memory_manager.py` | 858 | 记忆全生命周期 | 🟡 可接受 |
| `emotion_core.py` | 806 | PAD 情绪引擎 | 🟢 健康 |
| `model_router.py` | 622 | 多供应商路由 | 🟢 健康 |
| `http_channel.py` | 1207 | API 端点 | 🟡 路由过多 |
| 其余 < 600 | — | 单一职责 | 🟢 健康 |

---

## 第三轮：测试覆盖与回归

> 注意: 全量测试因依赖外部 API（LLM / embedding）无法在 CI 快速完成，采用静态覆盖分析。

### R3-001: 零测试覆盖的核心模块 🔴

| 模块 | 行数 | 已知 bug | 风险 |
|------|------|----------|------|
| `model_router.py` | 622 | R1-P0-018 tool error retry 无上限 | 无直接/间接测试 |
| `tool_executor.py` | 175 | R1-P1-005 频率限制完全失效 | 零引用 |
| `result_wrapper.py` | 126 | 未经独立测试 | 零引用 |
| `providers/*.py` | ~1400 | 多 adapter 仅集成测试 | 零直接测试 |
| `gateway/mcp/adapter.py` | — | vulture 标记为未使用 | 零引用 |

### R3-002: 仅有集成测试、缺少单元测试的模块 ⚠️

| 模块 | 间接引用数 | 风险 |
|------|----------|------|
| `agent_core.py` | 2 个测试文件 | 核心 2276 行无单元测试 |
| `tool_registry.py` | 1 个 | autodiscover 逻辑未独立验证 |
| `portrait_manager.py` | 2 个 | 级联粗粒化流程未隔离测试 |
| `vector_store.py` | 4 个 | sqlite-vec 操作仅集成验证 |

### R3-003: 测试数量充足但可能偏向 Happy Path ⚠️

现有 552 个测试，28 个测试文件覆盖了大部分子系统。数量健康，但审查发现：
- 16 个测试文件大量使用 `MagicMock`/`AsyncMock`/`side_effect` — 其中部分 mock 过度，可能掩盖真实集成问题
- `tool_executor.py` 零测试但 `test_security_stage8.py` 间接使用了 `ToolRegistry` — 说明工具系统测试完全是附带测试，覆盖面不足
- `test_personality.py` 和 `test_personality_regression.py` 侧重人格一致性检测，非功能正确性

### R3-004: 缺少测试的关键路径 🔴

以下路径在 R1/R2 审查中发现 bug，但没有对应测试：
1. **`tool_executor.execute()` 频率限制路径** → R1-P1-005
2. **`model_router.route()` tool error retry 路径** → R1-P0-018
3. **`database.forget_user_data()` 级联删除完整性** → R1-P0-003
4. **`http_channel._register_notebook_routes` 闭包过期** → R1-P0-007
5. **`agent_core._encode_image_memory` 高价值判断** → 新功能无测试

### R3-005: 测试覆盖总结

| 状态 | 模块数 | 说明 |
|------|--------|------|
| ✅ 有独立测试 | 18 | 包括 database, emotion_core, memory_manager 等 |
| ⚠️ 仅间接覆盖 | 10 | agent_core, tool_registry, skills_loader 等 |
| 🔴 零覆盖 | 11 | model_router, tool_executor, providers, result_wrapper 等 |

**核心缺口**: 路由/工具/Provider 三个基础设施层完全没有独立测试。这三层恰恰是 R1 审查中发现最多 bug 的地方。

---

## 综合审核结论

### 统计总览

| 严重度 | 数量 | 说明 |
|--------|------|------|
| 🔴 关键 | 5 | 必须立即修复 |
| ⚠️ 重要 | 10 | 应在下一版本修复 |
| 🟡 中 | 12 | 可排入 backlog |
| 🏗️ 架构债务 | 4 | 长期重构 |
| ✅ 确认无误 | 8 | 误报/架构正确 |

### 🚨 第一批：立即修复（影响正确性）

| # | ID | 问题 | 文件 |
|---|-----|------|------|
| 1 | R1-P1-005 | `_record_call` 从未调用 → 工具频率限制完全失效 | `tool_executor.py` |
| 2 | R1-P0-003 | `forget_user_data` 未清理 3 张表 | `database.py` |
| 3 | R1-P0-004 | `forget_user_data` 同步 sqlite3 阻塞事件循环 | `database.py` |
| 4 | R1-P0-018 | `route()` tool error retry 无次数限制 | `model_router.py` |
| 5 | R1-P0-024 | `delete_expired_images` f-string 构建 SQL | `database.py` |

### ⚠️ 第二批：下一迭代

| # | ID | 问题 | 文件 |
|---|-----|------|------|
| 6 | R1-P0-007 | `_register_notebook_routes` 闭包引用可能过期 | `http_channel.py` |
| 7 | R1-P0-009 | `update_model_config` 直接写 `os.environ` | `http_channel.py` |
| 8 | R1-P0-016 | `_init_default_adapter` 不检查创建失败 | `model_router.py` |
| 9 | R2-008 | 配置热重载路径不一致 | `http_channel.py` + `model_router.py` |
| 10 | R1-P0-001 | Bare except 吞异常（批量清理） | `database.py` |
| 11 | R1-P1-003 | `calculate_missing_value` 异常静默 | `nudge_engine.py` |
| 12 | R1-P1-001 | `retrieve_memories` gather 无超时 | `memory_manager.py` |
| 13 | R1-P0-023 | `compute_profile()` 重复计算 | `agent_core.py` |
| 14 | R0-001 | 26 处未使用 import 批量清理 | 多文件 |
| 15 | R1-P0-013 | 实体关键词硬编码 | `agent_core.py` |

### 🟡 第三批：Backlog

| # | ID | 问题 |
|---|-----|------|
| 16 | R1-P0-006 | 情绪统计 O(n²) |
| 17 | R1-P0-008 | 图片上传 DB 异常无日志 |
| 18 | R1-P0-010 | validate_api_key 未知供应商返回 valid:true |
| 19 | R1-P0-012 | process() 过长 290 行 |
| 20 | R1-P1-004 | 链式 .replace() 模板注入风险 |
| 21 | R1-P1-007 | render_with_budget 代码重复 |
| 22 | R1-P0-017 | route() fallback 不检查 tools |
| 23 | R1-P0-021 | SSE 无超时 |
| 24 | R1-P0-022 | fetchPADHistory/fetchEmotionHistory 重复 |
| 25 | R1-P0-020 | SSE buffer 可能截断 |
| 26 | R1-P1-008 | 日志格式不一致 |
| 27 | R0-007 | 2 处 TODO 遗留 |

### 🏗️ 架构债务

| # | ID | 问题 |
|---|-----|------|
| 28 | R2-002 | database.py God Object → 拆 5 Repository |
| 29 | R2-003 | agent_core.py God Object → 提取 Pipeline |
| 30 | R3-004 | tool_executor/model_router/providers 零测试 |
| 31 | R2-004 | MiMoAdapter.describe_image → Protocol |

### ✅ 确认无误（关闭）

| ID | 判定 |
|-----|------|
| R0-006 | vulture 误报：FastAPI 嵌套路由 + Provider Registry |
| R2-001 | 零循环依赖 ✅ |
| R2-005 | 事件流契约清晰 ✅ |
| R2-006 | InternalEvent 字段正确（协议字段） ✅ |
| R1-P0-011 | 重复 _perceive 已修复 ✅ |
| R1-P0-015 | import random 未使用（R0-001 覆盖） ✅ |
| R0-010 | tsc --noEmit 零错误 ✅ |
