# 昔涟工具系统 · 架构文档

版本: 2026-05-20  
状态: 打磨期 — 4 工具就位，LLM function calling 驱动，与记忆系统深度联动

---

## 一、工具系统全景

### 1.1 总览表

| 工具 | 功能 | 权限 | 分类 | 确认 | 频率限制 | 记忆触发 |
|------|------|------|------|------|----------|----------|
| `search_memory` | 检索情景记忆 | READ_ONLY | memory | 否 | 10/h | — |
| `query_weather` | 查询天气（和风 API + 智谱 fallback） | READ_ONLY | external | 否 | 5/h | trigger_portrait |
| `search_web` | 网页搜索（智谱 Web Search） | READ_ONLY | external | 否 | 5/h | — |
| `coding_delegate` | 编码委托（subprocess → Claude Code CLI） | EXECUTE | system | **是** | 3/h | — |

### 1.2 数据流图

```
  用户消息
     │
     ▼
  AgentCore.process()
     │
     ├──→ ContextBuilder.build()                    ← 记忆/情感/笔记本上下文
     ├──→ ToolRegistry.list_tools() → OpenAI schema ← 工具定义
     │
     ▼
  ModelRouter.route(messages, tools=[...], tool_choice="auto")
     │
     ├── LLM 返回 text (无工具调用)
     │       └──→ 正常回复流程
     │
     └── LLM 返回 tool_calls
             │
             ▼
         ToolExecutor.execute()
             │
             ├─ 1. validate       — 工具存在 + 参数合法
             ├─ 2. permission      — safe_mode 检查
             ├─ 3. rate_limit      — 滑动窗口频率控制
             ├─ 4. confirm         — EXECUTE 级别需用户确认
             ├─ 5. execute         — asyncio.wait_for(60s超时)
             └─ 6. audit_log       — 写入审计日志
             │
             ▼
         ToolResult {success, data, error}
             │
             ▼
         ResultWrapper.wrap()
             │
             ├─ 成功 + 简单结果 → 规则模板（零LLM成本）
             ├─ 成功 + 复杂结果 → Flash LLM 包装（昔涟语气）
             └─ 失败 → 预定义降级文本（"人家看了一下，好像没有找到呢……"）
             │
             ▼
         昔涟风格的文本 → 注入对话
             │
             ▼
         工具后处理
             ├─ trigger_memory    → MemoryManager.schedule_encoding()
             └─ trigger_portrait  → PortraitManager.mark_dirty()
```

### 1.3 工具在对话中的完整周期

```
轮次 1: 用户消息 → LLM 决定调用工具 → ToolExecutor → ResultWrapper → 昔涟回复
         │
         ▼ (tool_results 非空)
轮次 2: 工具结果作为 user role 回传 LLM → LLM 综合结果再次回复（或继续调用工具）
```

每次工具调用后，LLM 会看到上一轮的工具调用结果，可以决定是否继续调用更多工具，或基于结果给出最终回复。这是标准的 OpenAI function calling 循环模式。

---

## 二、各模块详述

### 2.1 ToolRegistry — 工具注册表

**功能**：进程内工具注册中心。通过 `@register_tool` 装饰器 + `autodiscover()` 自动发现和注册工具。

**设计理念**：
- **零配置新增工具**：新工具只需在 `packages/agent/tools/` 下创建一个文件 + 添加 `@register_tool` 装饰器。autodiscover 自动扫描和注册。
- **OpenAI function calling 格式**：`to_openai_tools()` 将注册的工具转为 LLM 可理解的 function calling schema。
- **元数据丰富**：每个工具的注册信息包含权限、分类、频率限制、确认要求、记忆触发策略——这些元数据由 ToolExecutor 消费，不是死字段。

**注册格式**：
```python
@register_tool(
    name="search_memory",
    description="检索昔涟关于伙伴的记忆……",
    schema={...},
    permission=ToolPermission.READ_ONLY,
    category="memory",
    max_frequency=10,
    requires_confirmation=False,
    trigger_memory=False,
    trigger_portrait=False,
)
```

| 元数据字段 | 含义 | 消费方 |
|-----------|------|--------|
| permission | READ_ONLY / READ_WRITE / EXECUTE | ToolExecutor 权限检查 |
| category | memory / external / utility / system | 未来按类别展示/统计 |
| max_frequency | 每小时最大调用次数 | ToolExecutor 频率检查 |
| requires_confirmation | 是否需要用户确认 | ToolExecutor 确认回路 |
| trigger_memory | 调用后是否触发记忆编码 | 工具后处理 |
| trigger_portrait | 调用后是否标记肖像脏 | 工具后处理 |

---

### 2.2 ToolExecutor — 工具执行器

**功能**：统一调度、权限校验、频率控制、用户确认、审计日志。所有工具调用经过同一管道。

**执行流程**：
```
validate → permission → rate_limit → confirm → execute → audit_log
```

**各步骤详解**：

| 步骤 | 检查内容 | 失败时行为 |
|------|---------|-----------|
| validate | 工具是否存在、参数是否匹配 schema | 返回错误 ToolResult |
| permission | safe_mode=True 时禁止非 READ_ONLY | 返回权限拒绝 |
| rate_limit | 滑动窗口（每小时 max_frequency 次） | 返回频率限制 |
| confirm | requires_confirmation=True 时等待用户回复 | 返回 PENDING_CONFIRMATION |
| execute | asyncio.wait_for(60s) | 超时返回降级结果 |
| audit_log | 写入 audit_logs 表 | 静默失败 |

**设计理念**：
- **工具执行是受控的，不是放任的**。每一层检查都是一道防线，确保昔涟不会在伙伴不知情的情况下做危险操作。
- **频率限制不是为了省钱，是为了保持陪伴感**。如果昔涟每分钟都在调 API，她就不再是陪伴者，而是信息中转站。

---

### 2.3 ResultWrapper — 结果包装器

**功能**：将工具返回的原始数据（JSON、文本）转化为昔涟会用自然语言说的话。

**双轨策略**：

| 轨道 | 适用场景 | 实现 | 成本 |
|------|---------|------|------|
| 规则模板 | 简单结果（天气、单一事实） | `@register_template` 装饰器 | 零 LLM |
| LLM 包装 | 复杂结果（多条目、搜索摘要） | Flash LLM 调用 | ~1s |

**失败降级**：
```
工具成功 → 模板或 LLM 包装
工具失败 → 预定义温柔文本（不是 "Error"）
  ├─ 超时 → "人家等了一会儿……好像那边有点慢呢。"
  ├─ 无结果 → "人家看了一下，好像没有找到呢……"
  └─ 权限拒绝 → "这件事……人家现在还做不到呢。"
```

**设计理念**：
- **昔涟永远不说技术语言**。用户从来不会看到 `{"code": 200, "data": {...}}` 出现在对话中。
- **失败是温柔的**。工具失败不是系统错误——是"昔涟没帮上忙"。两者的用户体验完全不同。

---

### 2.4 工具定义规范

**文件位置**：`packages/agent/tools/{tool_name}.py`

**必须包含**：
1. `@register_tool(...)` 装饰器，含完整元数据
2. 异步函数，接受 schema 定义的参数
3. `_register_template()` 函数（可选），注册规则模板用于简单结果包装

**LLM 可见的 schema 格式**（OpenAI function calling）：
```json
{
  "type": "function",
  "function": {
    "name": "search_memory",
    "description": "检索昔涟关于伙伴的记忆。当伙伴提到过去的事情……",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {"type": "string", "description": "搜索关键词"},
        "limit": {"type": "integer", "default": 3}
      },
      "required": ["query"]
    }
  }
}
```

**关键约定**：
- `description` 是给 LLM 看的——它决定了 LLM 是否会、以及在什么时候调用这个工具。写清楚"在什么场景下使用"，不是只描述功能。
- 工具不应做"太多"——一个工具一个责任。如果 LLM 困惑于"这个工具到底是做什么的"，它就不会调用。

---

### 2.5 与记忆系统的关系

工具调用后会触发记忆处理，路径根据 `trigger_memory` / `trigger_portrait` 标志决定：

| 路径 | 触发条件 | 行为 |
|------|---------|------|
| A | `trigger_memory=True` | 工具调用上下文写入 episodic_memories |
| B | `trigger_portrait=True` | 标记 `PortraitManager._dirty=True`，下次 consolidate 时融合 |
| C | 工具调用揭示用户新偏好 | 独立于 A/B，由 LLM 在对话中判断后调用 search_memory 或触发自动笔记 |
| D | 无触发 | 工具调用不写入记忆（如纯查询天气） |

**设计理念**：
- **工具调用不是记忆**——查了一次天气不应被记住。但反复查同一个城市、表达了偏好的查询行为——应该被记住。
- **标记脏而非立即写入**：Portrait 采用"标记脏+定期重写"而非"每次工具调用都更新印象"。这保持了印象文档的一致性——工具调用是瞬间的，但印象应该是累积的。

---

### 2.6 与情感系统的关系

**工具调用不直接影响 PAD 情绪**。原因：
- 工具调用是"举手之劳"——帮伙伴查天气不应该改变昔涟的心境。
- 但工具调用的**结果可能间接影响情绪**——如果用户因为查到好天气而开心，下一轮的 EmotionAnalyzer 会捕捉到这种开心，进而更新 PAD。

**工具调用不受 PAD 情绪影响**：
- 昔涟不会因为"心情不好"而拒绝帮伙伴查天气。工具调用是理性的、服务性的，不受当前情绪状态约束。

---

## 三、设计哲学

### 3.1 核心原则

1. **工具是昔涟的"举手之劳"，不是她的核心能力**
   昔涟的核心价值是情感陪伴。工具是她偶尔帮伙伴做的事——就像朋友聊天时顺手帮你查一下天气。工具调用频率应低（每小时 ≤ 10 次是合理上限）。

2. **昔涟在调用工具时，依然是昔涟**
   不是切换模式。从感知到"伙伴可能需要帮助"，到执行工具，到告知结果——全过程保持她的语言风格和人格。工具调用是"昔涟帮你做了件事"，不是"Agent 执行了一个函数"。

3. **工具结果必须被"翻译"成陪伴语言**
   数字要人性化（"大概二十几度的样子"）。否定结果要温柔（"好像没有找到呢……"）。积极结果可以俏皮（"明天是个好天气呢 ~♪"）。

4. **自主性边界清晰：只读默认自主，写操作需确认**

   | 权限 | 自主决策 | 确认要求 |
   |------|---------|---------|
   | READ_ONLY | 直接执行 | 不需要 |
   | READ_WRITE | 直接执行，事后告知 | 事后通知 |
   | EXECUTE | **禁止自主** | 必须事前确认 |

5. **工具是记忆的眼睛和手**
   反映用户特征的工具调用结果应触发印象文档更新。LLM 可通过 `search_memory` 自主回溯历史。不是每个工具调用都该被记住——但能揭示"伙伴是什么样的人"的调用，应该。

### 3.2 原则一致性检查

| 原则 | ToolRegistry | ToolExecutor | ResultWrapper | 记忆联动 |
|------|-------------|--------------|---------------|----------|
| 举手之劳 | — | ✅ 频率限制 | — | — |
| 依然是昔涟 | — | — | ✅ 双轨翻译 | — |
| 陪伴语言 | — | — | ✅ 模板+LLM | — |
| 自主性边界 | ✅ 权限三级 | ✅ confirm检查 | — | — |
| 记忆眼睛 | ✅ trigger标志 | — | — | ✅ 四路径 |

---

## 四、优点与不足

### 4.1 优点

- **LLM 驱动工具选择**：不是关键词匹配，不是硬编码流程。LLM 理解用户意图后自然决定是否调用工具、调用哪个工具。这是整个系统从"规则引擎"到"智能决策"的关键一步。
- **模块化执行管道**：ToolExecutor 的 6 步流水线（validate→permission→rate_limit→confirm→execute→audit）每一步独立可测。新增检查步骤不影响其他步骤。
- **ResultWrapper 的温度**：规则模板 + LLM 双轨策略。简单场景零成本，复杂场景高质量。
- **与记忆系统深度联动**：工具调用不孤立——反映用户偏好的调用自动更新印象文档。LLM 可通过 `search_memory` 自主检索历史。
- **零配置新增工具**：autodiscover 自动扫描注册。新工具只需一个文件 + 装饰器。
- **ModelRouter 的 tools 降级**：如果 Flash 不支持 tools 参数，自动降级为无 tools 调用，不崩溃。

### 4.2 不足与遗留问题

| # | 问题 | 严重度 | 说明 |
|---|------|--------|------|
| 1 | 工具数量少（4个） | 低 | 目前覆盖了核心场景（记忆/天气/搜索/编码），但缺少定时提醒、偏好管理等 |
| 2 | EXECUTE 确认回路依赖 LLM 回传 | 中 | 用户确认通过"LLM 再次调用工具"实现，如果 LLM 不传回确认，工具不会执行 |
| 3 | ResultWrapper 规则模板覆盖不足 | 低 | 只有 query_weather 和 search_memory 注册了规则模板，其他工具全部走 LLM 包装 |
| 4 | coding_delegate 超时 300s | 低 | 比 ToolExecutor 的 60s 全局超时多 5 倍，在 executor 层会被误杀。但 coding_delegate 被注册为最外层工具，有自己的超时处理 |
| 5 | 无工具调用统计 | 低 | 没有"伙伴最常使用哪个工具"的汇总数据，Portrait 无法从中学习 |
| 6 | search_web 依赖智谱 API | 中 | 单点依赖，如果智谱 API 不可用，搜索功能直接不可用。无 fallback 搜索源 |

---

## 五、待优化清单

### 已完成

| # | 内容 | 状态 |
|---|------|------|
| 1 | LLM function calling 替代关键词匹配 | ✅ |
| 2 | ToolExecutor 全流程（validate→permission→rate_limit→confirm→audit） | ✅ |
| 3 | ResultWrapper 双轨包装（模板+LLM） | ✅ |
| 4 | autodiscover 自动注册 | ✅ |
| 5 | ModelRouter tools 降级 | ✅ |
| 6 | 工具→记忆联动（trigger_memory / trigger_portrait） | ✅ |
| 7 | search_memory 工具（LLM 主动检索） | ✅ |
| 8 | query_weather 工具（和风+智谱 fallback） | ✅ |
| 9 | search_web 工具（智谱 Web Search） | ✅ |
| 10 | coding_delegate 确认回路 | ✅ |

### 未完成

| # | 内容 | 优先级 | 预估改动 | 说明 |
|---|------|--------|----------|------|
| 1 | 定时提醒工具（schedule_reminder） | 中 | ~80 行新工具 | 陪伴高频场景 |
| 2 | search_web 增加 fallback 搜索源 | 中 | ~30 行 | 降低单点依赖 |
| 3 | EXECUTE 确认回路改进 | 低 | ~20 行 | 目前依赖 LLM 回传，可加前端弹窗 |
| 4 | 工具调用统计→Portrait 融合 | 低 | ~30 行 | 数据收集 + Portrait prompt 微调 |
| 5 | ResultWrapper 规则模板全覆盖 | 低 | ~40 行 | 每个工具一个模板 |

---

*本文档随系统演进持续更新。最后修订：2026-05-20*

## 相关文档

- [架构总览](../architecture-overview.md) — 三大系统如何协同
- [记忆系统架构](memory-system-architecture.md) — 工具↔记忆联动路径
- [情感系统架构](emotion-system-architecture.md) — 工具与 PAD 情绪的关系
- [API 参考](../api-reference.md) — 工具相关端点
- [数据库 Schema](../database-schema.md) — audit_logs / scheduled_tasks 表
