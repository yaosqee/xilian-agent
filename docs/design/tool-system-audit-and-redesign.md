# 昔涟工具使用系统 · 诊断报告与重设计方案

> 日期：2026-05-18 | 状态：已确认，阶段 A 实现完成，进入阶段 B

---

## 第一步：诊断与检查

### 1.1 工具清单与必要性

#### 当前可用工具（仅 1 个）

| 工具名 | 类型 | 触发方式 | 权限级别 |
|--------|------|----------|----------|
| `coding_delegate` | 编码委托 (subprocess → Claude Code CLI) | 关键词匹配 | EXECUTE |

#### 逐工具必要性判断

**`coding_delegate`** — 必要性：**中等偏低**。陪伴型 Agent 的核心场景是情感陪伴，编码委托属于边缘场景。当前它是唯一的工具，但它的存在造成了“工具系统=编码委托”的认知错位。如果要保留，它应该是工具生态中的一个成员，而不是生态本身。

#### 仅有 1 个 Skills 定义（非工具）

`skills/manual/weather_query.md` 定义了天气查询技能，但其 `tools: ["web_search"]` 引用的工具**不存在**。SkillsLoader 会加载这个 skill，但永远不会执行它——因为 `agent_core.process()` 中没有任何代码调用 `skills_loader.match()` 或执行 skill 逻辑。

#### 关键缺失

| 缺失工具 | 陪伴场景价值 | 说明 |
|----------|-------------|------|
| 记忆检索辅助 | 极高 | 用户问“上次我们聊的那个…”时，Agent 应能主动检索记忆而非依赖 ContextBuilder 被动注入 |
| 外部信息查询 | 高 | 天气、新闻、日期时间、简单百科——陪伴中自然的“帮你看一下”场景 |
| 定时提醒 | 高 | “帮我在 X 分钟后提醒 Y”是陪伴刚需 |
| 用户偏好管理 | 高 | 记录/更新/查询用户偏好（与 portrait 不同，偏好是结构化的键值对） |
| 情绪记录 | 中 | 用户说“我今天很难过”时，主动记录情绪事件供后续回忆 |

#### 问题清单

1. **“为了有工具而有工具”**：`coding_delegate` 作为唯一工具，使整个工具注册系统（ToolRegistry、MCPAdapter、ModelRouter 的 tools 支持）看起来像过度设计。
2. **Skills 系统是死代码**：只有定义、加载和匹配，没有执行路径。
3. **关键词匹配导致工具不可发现**：用户必须说出特定中文关键词才能触达工具，而不是 Agent 理解意图后自然选择工具。
4. **缺少陪伴核心工具**：记忆检索、提醒、信息查询等高频陪伴场景无工具支撑。

---

### 1.2 调用机制

#### 当前状态

```
用户消息 → _perceive() [关键词匹配] → 
  ├─ 命中 "帮我写/写个/调试/bug..." → 直接调用 coding_delegate()
  ├─ 命中 "帮我查/查一下/搜索..." → 返回 TOOL_PLACEHOLDER（死胡同）
  └─ 未命中 → 正常 LLM 对话
```

关键特征：
- **关键词驱动，非 LLM 驱动**。LLM 从未收到任何工具定义，从未被要求做出工具选择。
- `ModelRouter.route()` 支持 `tools` 和 `tool_choice` 参数（含降级策略），但 `agent_core.process()` **从未传入工具列表**。
- 工具调用在感知阶段就被拦截，不经过 LLM 决策。

#### 当前异常处理

- `coding_delegate` 内部有 300s 超时、失败降级、错误捕获
- 但**没有系统级的工具执行保护**：无全局超时、无重试策略、无熔断
- 工具失败时返回**预定义的友好文本**（昔涟风格），这点做得不错

#### 结果反馈

- `coding_delegate` → `_package_result()` 用规则模板包装为昔涟风格文本 → 直接注入对话
- `TOOL_PLACEHOLDER` → 固定文本：“这个功能人家还在学习呢……”

**优点**：结果确实经过了“翻译”。**缺点**：规则模板僵硬，复杂结果（如代码 diff）被粗暴截断。

#### 问题清单

1. **工具选择绕过 LLM**：关键词匹配不可扩展，每新增一个工具就要扩展关键词列表，且无法处理复合意图（“帮我查一下天气然后提醒我明天带伞”）。
2. **ModelRouter 的 tools 支持是死代码**：基础设施已完备（tools 参数、降级、缓存），但从未被使用。
3. **无全局超时/熔断**：单个工具的超时保护是工具自身的实现细节，不是系统契约。
4. **结果加工只有规则模板**：`_package_result()` 对复杂结果处理能力弱。

---

### 1.3 与记忆系统的关系

#### 当前状态：完全脱节

- 工具调用结果**不写入记忆**
- 工具调用**不查询记忆**（不利用用户历史偏好）
- ContextBuilder 的 MemoryModule 注入是**被动的**（基于当前消息的向量检索），工具调用不主动触发记忆检索

#### 应该做什么

| 场景 | 是否该记 | 理由 |
|------|---------|------|
| 用户通过 Agent 查天气 → Agent 回复“明天有雨” | 不该记 | 天气是临时信息，不是关于用户的记忆 |
| 用户说“帮我查 X” → Agent 发现用户似乎对 X 有兴趣 | 应该记 | 查询行为暴露了用户的兴趣偏好 |
| 用户设置提醒“每天 9 点提醒我吃药” | 应该记 | 这是关于用户的长期结构化信息 |
| Agent 调用 coding_delegate 帮用户修 bug | 不该记 | 编码委托是一次性事务 |
| 用户通过 Agent 查询某城市的天气（反复查同一个城市） | 应该记（偏好） | “这个用户在意 XX 城市的天气” |

#### 问题清单

1. **零集成**：工具调用与记忆系统之间没有任何数据流。
2. **工具调用不更新用户印象**：印象文档（portrait）应该在用户频繁使用某类工具时感知到“这个用户偏好这类信息”。

---

### 1.4 安全与边界

#### 当前状态

| 维度 | 状态 |
|------|------|
| 权限分级 | ToolPermission 三级（READ_ONLY / READ_WRITE / EXECUTE），已定义但未充分使用（唯一工具是 EXECUTE 级） |
| 安全模式 | `ToolRegistry.is_allowed(name, safe_mode=True)` 禁用非 READ_ONLY 工具，但 `safe_mode` 参数在任何地方都未被设为 True |
| 频率限制 | 无。coding_delegate 可以无限次调用 |
| 用户确认 | 无。EXECUTE 级别工具直接执行，不征求用户同意 |
| 敏感数据 | coding_delegate 在 subprocess 中传入完整需求文本，无脱敏 |

#### 问题清单

1. **safe_mode 未被启用**：安全模式的开关存在但从未打开。
2. **无频率限制**：恶意/错误的连续调用无防护。
3. **EXECUTE 工具无确认机制**：`coding_delegate` 会实际调用外部进程并修改文件系统，但用户无感知。
4. **无审计日志**：工具调用不记录到 audit_logs 表（虽然表结构已存在）。

---

### 1.5 可扩展性

#### 当前新增工具流程

1. 在 `packages/agent/tools/` 下创建新文件，实现工具函数
2. 在 `__init__.py` 中导出
3. 在 `agent_core.__init__()` 中 `import` + `self.tool_registry.register(...)`
4. 在 `_perceive()` 中添加关键词匹配逻辑
5. 在 `process()` 中添加对应的 if-elif 分支

**步骤数：5 步，涉及 3 个文件。** 不算多，但关键词匹配和 if-elif 是线性扩展的，10 个工具时就会失控。

#### 问题清单

1. **线性扩展**：每增加一个工具都要修改 `_perceive()` 和 `process()`，违反开闭原则。
2. **工具注册分散**：注册在 `agent_core.__init__()` 中硬编码，而非在工具文件自身或统一配置中。
3. **MCPAdapter 是完整接口但从未实现**：接口设计清晰，但整个类都是 `raise NotImplementedError`。

---

## 第二步：设计原则

### 原则 1：工具是昔涟的“举手之劳”，不是她的核心能力

昔涟的核心价值是情感陪伴——倾听、理解、回应。工具是她偶尔帮伙伴做的一件小事，就像朋友聊天时顺手帮你查一下天气。这意味着：

- 工具调用频率应该低（每小时 ≤ 3 次是合理上限）
- 工具的 UI/UX 应该是“昔涟在帮你做事”，不是“Agent 在执行函数”
- 工具调用失败不应破坏对话体验——昔涟温柔地说“没查到”比系统报错重要一万倍

### 原则 2：昔涟在调用工具时，依然是昔涟

调用工具不是切换模式。昔涟从感知到“伙伴可能需要帮助”到执行工具到告知结果，全过程都应保持她的语言风格和人格。

具体实现：**工具执行前后各有一段“昔涟语言”**
- **执行前（过渡语）**：“人家帮你看看……稍等一下哦 ~♪”
- **执行后（结果包装）**：工具返回的原始数据必须经过 LLM 包装，用昔涟的语气重新表达

### 原则 3：工具结果必须被“翻译”成陪伴语言

工具返回的是数据（JSON、文本、结构化信息）。昔涟说出来的是“话”。翻译规则：
- 绝不允许 `{temperature: 25, weather: "sunny"}` 直接出现在对话中
- 数字要人性化（“大概二十几度的样子”）
- 否定结果要温柔（“人家看了一下，好像没有找到呢……”而不是 “404 Not Found”）
- 积极结果可以俏皮（“明天是个好天气呢！适合出门走走哦 ~♪”）

### 原则 4：自主性边界清晰——只读默认自主，写操作需确认

| 工具级别 | 自主决策 | 需要用户确认 |
|----------|---------|-------------|
| READ_ONLY（查询天气、搜索、查记忆） | 直接执行，结果温柔告知 | 不需要 |
| READ_WRITE（设置提醒、记录偏好） | 直接执行，但告知用户做了什么 | 事后通知 |
| EXECUTE（编码委托、执行脚本） | **禁止自主** | 必须事前确认 |

这条原则保护了陪伴体验——昔涟不会在后台悄悄做伙伴不知道的事。

### 原则 5：工具是记忆的眼睛和手

- 工具调用结果中，凡是反映用户特征的信息（偏好、习惯、关注点），应触发印象文档更新
- 记忆检索本身可以是一个工具（`search_memory`），让 LLM 自主决定何时需要回溯历史
- 工具调用前后上下文应作为情景记忆的可选编码素材

---

## 第三步：重设计方案

### 3.1 架构设计

```
                        ┌─────────────────────────────┐
                        │       AgentCore.process()    │
                        │                              │
  User Message ──────▶  │  _perceive() → Intent       │
                        │       │                      │
                        │       ▼                      │
                        │  ContextBuilder.build()      │
                        │       │                      │
                        │       ▼                      │
                        │  _build_messages()           │
                        │  ┌─ system: personality      │
                        │  ├─ history                  │
                        │  ├─ context (5 modules)      │
                        │  ├─ tool_definitions  ◀──────│── ToolRegistry.list_tools()
                        │  └─ user_message             │
                        │       │                      │
                        │       ▼                      │
                        │  ModelRouter.route(          │
                        │    messages,                 │
                        │    tools=[...],    ◀── NEW   │
                        │    tool_choice="auto"        │
                        │  )                           │
                        │       │                      │
                        │       ├── LLM 返回 text ────▶ 正常回复流程
                        │       │                      │
                        │       └── LLM 返回 tool_call ─▶ ToolExecutor.execute()
                        │              │               │
                        │              ▼               │
                        │       ┌──────────────────┐   │
                        │       │  ToolExecutor     │   │
                        │       │  ├─ validate      │   │
                        │       │  ├─ permission     │   │
                        │       │  ├─ rate_limit     │   │
                        │       │  ├─ confirm(user)  │   │
                        │       │  ├─ execute()      │   │
                        │       │  └─ audit_log      │   │
                        │       └──────┬───────────┘   │
                        │              │               │
                        │              ▼               │
                        │       ┌──────────────────┐   │
                        │       │  ResultWrapper    │   │
                        │       │  (LLM-powered)    │   │
                        │       └──────┬───────────┘   │
                        │              │               │
                        │              ▼               │
                        │       昔涟风格的文本回复        │
                        │              │               │
                        │              ▼               │
                        │       ┌──────────────────┐   │
                        │       │  记忆/印象存储     │   │
                        │       │  (条件触发)       │   │
                        │       └──────────────────┘   │
                        └─────────────────────────────┘
```

#### 与现有系统的集成点

| 现有模块 | 集成方式 | 变更规模 |
|----------|---------|---------|
| `ToolRegistry` | 保持不变，`list_tools()` 转为 LLM function calling 格式 | 无变更 |
| `ModelRouter` | 在 `route()` 调用中传入 `tools` 参数（基础设施已就绪） | 1 行变更 |
| `ContextBuilder` | 新增 `ToolContextModule`，注入最近工具调用摘要 | 新增 ~80 行 |
| `MemoryManager` | 工具调用结束后可选触发 `encode_memory()` | 新增 ~30 行 |
| `PortraitManager` | 工具调用偏好统计 → `consolidate()` 时融合 | 新增 ~50 行 |
| `agent_core.py` | `_perceive()` 删除关键词匹配，`process()` 增加 tool-call 循环 | 重构 ~100 行 |

---

### 3.2 核心组件

#### 3.2.1 工具定义规范

```yaml
# 每个工具一个文件：packages/agent/tools/{tool_name}.py
# 使用 @tool_registry.register 装饰器

@tool_registry.register(
    name="search_memory",
    description="检索昔涟关于伙伴的记忆。当伙伴提到过去的事情、问'你还记得吗'、或需要回忆上下文时使用。",
    schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或问题，用自然语言描述想找什么"
            },
            "limit": {
                "type": "integer",
                "description": "返回条数上限，默认 3",
                "default": 3
            }
        },
        "required": ["query"]
    },
    permission=ToolPermission.READ_ONLY,
    category="memory",         # 新增：工具分类
    max_frequency=10,           # 新增：每小时最大调用次数
    requires_confirmation=False # 新增：是否需要用户确认
)
async def search_memory(query: str, limit: int = 3, ctx: ToolContext) -> ToolResult:
    ...
```

**新增字段说明：**

| 字段 | 类型 | 说明 |
|------|------|------|
| `category` | str | 工具分类：memory / external / utility / system |
| `max_frequency` | int | 每小时最大调用次数，0 = 不限 |
| `requires_confirmation` | bool | True 时执行前需用户确认 |
| `ctx: ToolContext` | 隐式参数 | 由 executor 自动注入，含 user_id / db / memory_manager 等 |

#### 3.2.2 ToolExecutor（工具执行器）

```python
# packages/agent/tool_executor.py (新文件)

class ToolExecutor:
    """
    工具执行器 — 统一调度、权限校验、频率控制、审计日志。
    """

    def __init__(self, registry: ToolRegistry, db: DatabaseManager,
                 memory_manager: MemoryManager | None = None,
                 portrait_manager: PortraitManager | None = None):
        self.registry = registry
        self.db = db
        self.memory = memory_manager
        self.portrait = portrait_manager
        self._call_counts: dict[str, list[float]] = {}  # tool_name → [timestamps]
        self._global_timeout: float = 60.0               # 全局超时

    async def execute(self, tool_name: str, arguments: dict,
                      user_id: str, safe_mode: bool = False) -> ToolResult:
        """
        执行一个工具调用，返回 ToolResult。

        流程：
          1. validate — 工具是否存在、参数是否合法
          2. permission — safe_mode 检查
          3. rate_limit — 频率检查
          4. confirm — 如需确认，返回 PENDING_CONFIRMATION
          5. execute — 带超时的异步执行
          6. audit_log — 写入审计日志
        """
        ...

    def _check_rate_limit(self, tool_name: str) -> bool:
        """滑动窗口频率检查（默认每小时 N 次）"""
        ...

    def to_llm_format(self) -> list[dict]:
        """将注册的工具转为 OpenAI function-calling 格式"""
        ...
```

#### 3.2.3 ResultWrapper（结果加工层）

```python
# packages/agent/result_wrapper.py (新文件)

class ResultWrapper:
    """
    将工具执行结果转化为昔涟的语言风格。

    采用分级策略：
      - 简单结果（天气、时间）→ 规则模板（零成本，亚秒级）
      - 复杂结果（搜索结果、多条目）→ LLM 包装（高质量）
      - 失败结果 → 预定义温柔降级文本（零成本）
    """

    def __init__(self, model_router: ModelRouter):
        self.router = model_router

    async def wrap(self, tool_name: str, result: ToolResult,
                   context: str = "") -> str:
        """
        将 ToolResult 转化为昔涟会说的一句话/一段话。

        Args:
            tool_name: 工具名称
            result: 工具执行结果
            context: 用户原始消息（帮助 LLM 理解场景）

        Returns:
            昔涟风格的文本（可直接注入对话）
        """
        if not result.success:
            return self._failure_template(tool_name, result.error)

        if tool_name in SIMPLE_TOOLS:  # 预定义模板集合
            return self._template_wrap(tool_name, result.data)

        # LLM 包装
        return await self._llm_wrap(tool_name, result.data, context)
```

**LLM 包装的 prompt 设计（关键）：**

```
[System] 你是昔涟。用你一贯的温柔语气，把以下信息自然地告诉伙伴。
不要复述数据，不要列出条目，要像聊天一样说出来。
如果信息不完整或有不确定性，用"好像""大概"等柔化词。

规则：
- 用短句，每行以「。！？~♪」收束
- 可以加省略号「……」表达思考
- 不需要把所有细节都说出来，挑最重要的 2-3 个点即可

[示例]
工具返回: {city: "北京", temp: 25, weather: "晴", wind: "微风"}
昔涟说: 人家帮你看了看北京那边~
      今天天气不错呢，晴朗，大概二十几度的样子……
      微风吹着应该很舒服吧 ♪

工具返回: {error: "timeout"}
昔涟说: 唔……那边好像有点慢呢 (´•ω•̥`)
      人家没等到结果……
      等会儿再试试好不好？
```

---

### 3.3 关键流程

#### 3.3.1 一次工具调用的完整生命周期

```
1. 用户消息抵达 process()
       │
2. _perceive() → LLM（含 tools 定义）做意图识别 + 工具选择
       │  （取代关键词匹配）
       │
       ├── LLM 返回 text → 正常回复流程（不变）
       │
       └── LLM 返回 tool_call
              │
3. ToolExecutor.execute()
       │
       ├── 3a. validate → 工具存在？参数合法？
       ├── 3b. permission → safe_mode 下是否允许？
       ├── 3c. rate_limit → 频率检查通过？
       ├── 3d. confirm → 如需确认，返回过渡语 + 等待用户确认
       ├── 3e. execute → 带 60s 全局超时的异步执行
       └── 3f. audit_log → 写入执行记录
              │
4. ResultWrapper.wrap()
       │
       ├── 失败 → 温柔降级文本
       └── 成功 → 规则模板 or LLM 包装
              │
5. 注入对话
       │
       ├── self.context.add_message("user", original_msg)
       └── self.context.add_message("assistant", wrapped_reply)
              │
6. 条件记忆存储
       │
       ├── tool.result.trigger_memory == True?
       │     └── memory_manager.encode_memory(event)
       ├── tool.result.trigger_portrait_update == True?
       │     └── portrait_manager.mark_dirty()
       └── 写入 conversation_logs（含 tool_call 元数据）
```

#### 3.3.2 异常处理流程

```
ToolExecutor.execute() 异常矩阵：

┌────────────────────┬──────────────────────────────────┐
│ 异常类型            │ 处理方式                          │
├────────────────────┼──────────────────────────────────┤
│ 工具不存在          │ 温柔回复：“人家好像还没学会这个…”  │
│ 参数不合法          │ 温柔回复 + 提示正确格式            │
│ 频率限制触发        │ 温柔回复：“刚才已经帮你查过了呢…”  │
│ 安全模式禁止        │ 温柔回复 + 建议关闭安全模式         │
│ 需要用户确认        │ 返回过渡语 + 等待确认事件           │
│ 执行超时            │ 温柔降级：“那边有点慢……”           │
│ 执行异常            │ 日志记录 + 温柔降级                 │
│ LLM 幻觉工具名      │ 日志记录 + 温柔回复：“人家不太确定…” │
└────────────────────┴──────────────────────────────────┘

所有异常都不应该让对话中断或显示技术错误。
```

---

### 3.4 配置与扩展

#### 3.4.1 新增工具的标准步骤（优化后：2 步，1 个文件）

**目标**：让新增工具只涉及创建一个文件。

```
packages/agent/tools/my_new_tool.py

@tool_registry.register(
    name="my_new_tool",
    description="...",
    schema={...},
    permission=ToolPermission.READ_ONLY,
    category="utility",
    max_frequency=5,
)
async def my_new_tool(param1: str, ctx: ToolContext) -> ToolResult:
    ...
```

**自动发现机制**：`ToolRegistry.autodiscover("packages/agent/tools/")` 扫描目录，自动导入所有 `@register` 装饰的函数。不再需要手动在 `__init__` 或 `agent_core` 中注册。

#### 3.4.2 工具配置文件（可选，环境变量 + DB）

```
# .env 或 DB autonomy_settings 表中的扩展字段
TOOL_ENABLED_coding_delegate=true     # 按名称启用/禁用
TOOL_MAX_FREQ_coding_delegate=3       # 每小时最大调用
TOOL_TIMEOUT_GLOBAL=60                # 全局超时秒数
TOOL_REQUIRE_CONFIRM_coding_delegate=true  # 是否需要用户确认
```

优先级：DB 运行时配置 > 环境变量 > 工具注册时的默认值

---

### 3.5 与用户记忆模块的配合

#### 3.5.1 工具调用利用用户印象

在工具执行前，如果工具标记了 `use_portrait=True`，ToolExecutor 自动注入：

```python
# 伪代码
if tool_def.get("use_portrait"):
    portrait = await self.db.get_latest_portrait()
    if portrait:
        arguments["_portrait_context"] = portrait["content"]
```

使用场景举例：
- 天气查询：从 portrait 推断用户所在城市，作为默认城市
- 记忆检索：从 portrait 提取用户关注的话题，加权搜索

#### 3.5.2 工具调用触发印象更新

```python
@dataclass
class ToolResult:
    success: bool
    data: Any
    error: str = ""
    trigger_memory: bool = False          # 是否触发情景记忆编码
    trigger_portrait_update: bool = False # 是否标记印象文档 dirty
```

工具开发者根据工具语义设置这些标志：
- `search_memory` → `trigger_memory=False`（检索不是新记忆）
- `set_reminder` → `trigger_memory=True`, `trigger_portrait_update=True`（反映用户生活习惯）
- `query_weather` → `trigger_portrait_update=True`（反映用户关注的城市）
- `coding_delegate` → `trigger_memory=False`（一次性事务）

---

### 3.6 实施路线图

#### 阶段 A：基础设施激活（3-4 天）

**目标**：让 LLM 真正参与工具选择，激活已有基础设施

| 产出 | 说明 |
|------|------|
| `ToolExecutor` 实现 | 校验、权限、频率、审计一体化 |
| `agent_core.process()` 改造 | 删除关键词匹配，传入 tools 定义给 LLM，增加 tool-call 循环 |
| `ResultWrapper` 实现 | 规则模板 + LLM 包装双轨 |
| 过渡语生成 | “人家帮你看看……” 等固定文本 |

**验证**：
- 发送“帮我查一下天气” → LLM 返回 tool_call → 执行 → 温柔回复（不再走 TOOL_PLACEHOLDER）
- 发送“今天好累啊” → 正常对话，不触发任何工具

#### 阶段 B：陪伴核心工具实现（4-5 天）

**目标**：补齐陪伴场景高频工具

| 工具 | 优先级 | 说明 |
|------|--------|------|
| `search_memory` | P0 | 利用现有 MemoryManager.retrieve() |
| `query_weather` | P0 | 把 skills/weather_query.md 升级为真正可执行的工具（需外部 API 或 web search） |
| `search_web` | P1 | 简单网页搜索，用于快查百科/新闻 |
| `set_reminder` | P1 | 基于 Notebook 的 task 表，设置定时提醒 |
| `record_moment` | P2 | 用户主动说“记住这个”时，触发记忆编码 |
| `coding_delegate` 迁移 | — | 从关键词触发改由 LLM 自主选择调用 |

**验证**：
- 完整对话场景测试（查天气 → 聊感受 → 设提醒 → 回溯记忆）
- 工具调用频率统计（确保符合原则 1：低频辅助）

#### 阶段 C：深度集成与打磨（3-4 天）

| 产出 | 说明 |
|------|------|
| 工具调用 → 记忆编码 | trigger_memory / trigger_portrait_update 机制 |
| 工具自动发现 | `autodiscover()` 替代手动注册 |
| MCPAdapter 实现 | 让外部客户端也能调用工具（远期需求） |
| 审计日志集成 | 工具调用写入 audit_logs 表 |
| 用户确认流程 | EXECUTE 工具的确认 UI（前端 + 后端） |

**验证**：
- 连续 10 轮对话中穿插 3 次工具调用，检查记忆是否正确编码
- Portrait 在工具偏好积累后是否正确更新
- `safe_mode` 测试：启用后 READ_WRITE/EXECUTE 工具是否被拒绝

---

### 3.7 工作量和时间预估

| 阶段 | 工作量 | 时间 |
|------|--------|------|
| A: 基础设施激活 | ~800 行新代码 + ~100 行重构 | 3-4 天 |
| B: 陪伴核心工具 | ~600 行新代码（含外部 API 集成） | 4-5 天 |
| C: 深度集成与打磨 | ~500 行新代码 + 测试 | 3-4 天 |
| **总计** | **~2000 行，4 个新文件，1 个重构文件** | **10-13 天** |

---

## 附录：用户已确认的事项

| # | 问题 | 决策 |
|---|------|------|
| 1 | coding_delegate 保留？ | ✅ 保留，退为普通工具，由 LLM 自主选择 |
| 2 | LLM 驱动 vs 规则驱动？ | ✅ LLM 驱动，利用 DS Pro function calling |
| 3 | 外部 API 依赖？ | ✅ 和风天气 API 已提供 (QWEATHER_API_KEY)，搜索 API 注册中；先实现 search_memory |
| 4 | 自主性边界分级？ | ✅ 同意 READ_ONLY 自主 / READ_WRITE 事后通知 / EXECUTE 事前确认 |
| 5 | 前端适配时机？ | ✅ 阶段 B 后再规划 |


