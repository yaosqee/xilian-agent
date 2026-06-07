# AgentCore 拆分计划

> R2-003: 2276 行 God Object → 按 ActorMind 阶段提取 Pipeline Processor

## 〇、database 拆分的教训（最高优先级）

本次必须遵守的约束：

| # | 教训 | 本次如何避免 |
|---|------|-------------|
| 1 | **禁止自动化 Python 代码生成/替换** — bulk sed/Python 脚本替换在含中文/装饰器/嵌套函数的代码上极易出错 | 只使用 Edit 工具进行精确的字符串替换，每次单文件操作 |
| 2 | **禁止文件+目录同名** — `database.py` + `database/` 导致导入歧义 | 新包直接命名为 `agent/pipeline/`，不与任何 .py 文件冲突 |
| 3 | **先做最小可行提取，验证后再继续** — 不应一次性提取所有分组 | 第一个提取目标选最小的（PerceptionProcessor，~30 行），验证通过后再做下一个 |
| 4 | **始终保留原始代码可恢复** — 自动化操作丢失了整个文件内容 | 每次 Edit 前确保 git 可恢复；不改动超过 50 行的方法体 |
| 5 | **委托方法保留完整签名和 docstring** — 类型提示丢失会导致 IDE/类型检查退化 | 每个委托方法完整复制原始签名 + docstring |
| 6 | **不在同一轮中同时修改调用方和被调用方** — database 拆分只改了内部结构 | AgentCore 拆分同样：只提取内部实现，不改外部调用接口 |

## 一、现状分析

```
agent_core.py (2276 行)
├── 工具函数 (_sanitize_surrogates, _tc_id 等)     ~50 行
├── AgentResponse dataclass                           ~10 行
├── AgentCore.__init__()                              ~100 行
├── AgentCore.startup() / shutdown()                  ~210 行
├── AgentCore.process() 主入口                        ~290 行 ← 核心问题
├── ActorMind 各阶段:
│   ├── _perceive()                                    ~25 行
│   ├── _retrieve_memories()                          ~70 行
│   ├── _build_messages()                             ~65 行
│   ├── _handle_tool_calls()                          ~120 行
│   ├── _handle_confirmation()                         ~40 行
│   ├── _process_tool_side_effects()                   ~15 行
│   └── _clean_reply / _sanitize_fabrication           ~25 行
├── 后台任务调度:
│   ├── _schedule_emotion_analysis()                   ~15 行
│   ├── _run_emotion_analysis()                        ~55 行
│   ├── _schedule_memory_encoding()                    ~30 行
│   └── _encode_image_memory()                         ~35 行
├── 多模态:
│   ├── _describe_image()                              ~35 行
│   ├── _convert_to_multimodal()                       ~25 行
│   ├── _resolve_image_url()                           ~20 行
│   └── _compress_image_desc()                         ~10 行
├── 表情包系统:
│   ├── _should_auto_sticker()                         ~20 行
│   ├── _pick_sticker_by_emotion()                     ~30 行
│   ├── _resolve_sticker()                             ~10 行
│   └── _get_sticker_catalog()                         ~10 行
├── 破冰/画像/人格:
│   ├── _load_personality()                            ~15 行
│   ├── _tick_icebreaker()                             ~55 行
│   ├── _icebreaker_consolidate()                      ~60 行
│   ├── _reload_layered_portraits()                    ~45 行
│   └── _ensure_character_memories()                   ~95 行
├── 语音兜底:
│   ├── _enforce_speech_rule()                         ~35 行
│   └── _build_speech_fallback()                       ~25 行
├── 人格漂移检测 + 一致性评分                           ~30 行
├── 好感度更新 + 情感调制                               ~50 行
└── 标记提取 + 其他辅助                                  ~30 行
```

**关键观察**：
- `process()` 方法 290 行，是所有子系统的调度中心——但它本身就是 ActorMind 管线的**编排层**
- 子系统之间通过 `self.context`（AgentContext）共享状态——提取为独立 Processor 时必须注入此引用
- 与 database 拆分不同：database 方法是**独立 CRUD**，agent_core 方法是**有状态管线**

## 二、拆分策略：Processor 提取（非 Repository 模式）

database.py 用的是**委托模式**（方法签名不变，内部转发）——适合无状态 CRUD。
agent_core.py 需要的是**提取模式**（移动方法到 Processor 类，通过依赖注入访问共享状态）——适合有状态管线。

### 目标文件结构

```
packages/agent/
├── agent_core.py                          # AgentCore 精简为协调器（~1200 行）
├── pipeline/                              # 新包（不与 agent_core.py 冲突）
│   ├── __init__.py
│   ├── _base.py                           # PipelineStage 基类
│   ├── perception.py                      # _perceive()
│   ├── memory_retrieval.py                # _retrieve_memories()
│   ├── message_builder.py                 # _build_messages()
│   ├── tool_handler.py                    # _handle_tool_calls + _handle_confirmation
│   ├── emotion_pipeline.py               # 情绪分析调度
│   ├── memory_encoding.py                # 记忆编码管线
│   ├── multimodal.py                      # 多模态处理
│   ├── sticker.py                         # 表情包系统
│   └── icebreaker.py                      # 破冰 + 画像
```

### 提取规则

每个 ServiceModule 子类：
- 接收 `ctx`（必选）+ `router`（可选）+ `db`（可选）作为基类构造参数；额外依赖通过子类 `__init__` 注入
- **不**持有对 `AgentCore` 的反向引用（避免循环依赖）
- 方法签名保持原样——仅 `self` 从 AgentCore 变为 ServiceModule 实例
- 所有对 `self.context` / `self.router` / `self._db` 的引用 → 改为 `self._ctx` / `self._router` / `self._db`

## 三、执行顺序（由简到繁）

### Step 1: `pipeline/_base.py` — ServiceModule 基类

> 注意：这不是真正的 Pipeline 模式（Stage → Stage 链式传递数据）。这些模块被 AgentCore.process() 编排调用，
> 各自操作 AgentContext 的不同字段。基类只是一个依赖注入容器——为子类提供共享依赖的便捷访问。

```python
class ServiceModule:
    """所有提取模块的基类。router 和 db 为可选参数——不需要它们的 Processor 可以不传。"""
    def __init__(self, ctx, router=None, db=None):
        self._ctx = ctx          # AgentContext（必选，所有模块都需要）
        self._router = router    # ModelRouter（可选）
        self._db = db            # DatabaseManager（可选）
```

### 各 Processor 额外依赖清单

| Processor | 基类参数 | 额外依赖 | 注入时机 |
|-----------|---------|---------|---------|
| PerceptionProcessor | ctx | 无 | `__init__` |
| MultimodalProcessor | ctx, router | 无 | `__init__` |
| StickerProcessor | ctx | emotion_engine | `startup`（emotion_engine 异步初始化） |
| MemoryRetrievalProcessor | ctx, router, db | memory_manager, portrait_manager | `startup` |
| ToolHandlerProcessor | ctx, router | tool_executor, tool_registry, result_wrapper | `startup` |
| EmotionPipelineProcessor | ctx, router, db | emotion_engine | `startup` |
| MemoryEncodingProcessor | ctx, db | memory_manager | `startup` |
| MessageBuilderProcessor | ctx | context_builder | `__init__`（context_builder 在 __init__ 构建） |
| IcebreakerProcessor | ctx, db | portrait_manager, memory_manager, notebook_manager | `startup` |

> **时序规则**：纯同步依赖（ctx/router/db/context_builder）的 Processor 在 `AgentCore.__init__()` 创建；
> 依赖异步初始化对象（emotion_engine/memory_manager 等，需等 `startup()` 完成）的 Processor 在 `startup()` 中创建。

### Step 2: `perception.py` — 最小 (~30 行)，验证模式可行

- 移动 `_perceive()` → `PerceptionProcessor.analyze()`
- 在 AgentCore 中保留委托方法

### Step 3: `multimodal.py` (~90 行)

- 移动 4 个多模态方法

### Step 4: `sticker.py` (~70 行)

- 移动 5 个表情包方法

### Step 5: `memory_retrieval.py` (~70 行)

- 移动 `_retrieve_memories()`

### Step 6: `tool_handler.py` (~175 行)

- 移动 `_handle_tool_calls()` + `_handle_confirmation()` + `_process_tool_side_effects()`

### Step 7: `emotion_pipeline.py` (~70 行)

- 移动情绪分析调度方法

### Step 8: `memory_encoding.py` (~65 行)

- 移动记忆编码方法

### Step 9: `message_builder.py` (~65 行)

- 移动 `_build_messages()` — 只依赖 context_builder（一个模块），比 icebreaker 简单

### Step 10: `icebreaker.py` (~170 行)

- 移动破冰/画像方法 — **最复杂的提取目标**：依赖 portrait_manager + memory_manager + notebook_manager 三个异步模块
- 在完成前 8 个较简单的模块后执行，积累足够经验

### Step 11: 最终清理 — `agent_core.py` 精简

- 移除已移动的方法体
- 验证 agent_core.py 行数从 ~2276 → ~1000

## 四、不提取的内容

- `process()` 主入口 — 它是编排层，保留在 AgentCore 中
- `startup()` / `shutdown()` — 生命周期方法，跨子系统协调
- `__init__()` — 构造函数，初始化所有 Processor 实例
- `_load_personality()` — 简单文件读取
- `_clean_reply()` / `_sanitize_fabrication()` — 纯函数
- `_enforce_speech_rule()` / `_build_speech_fallback()` — 简单辅助
- `_extract_markers()` — 与 MarkerParser 紧耦合
- `_ensure_character_memories()` — 只运行一次（startup），不参与热路径；操作 `self._db` + `self.router`，提取价值低
- P1-②/P1-③ 情绪调制/反馈方法 — 与 process() 紧耦合

## 五、验证清单（每步执行）

- [ ] AST 解析通过
- [ ] `from packages.agent import AgentCore` 导入成功
- [ ] 所有 Processor 类可独立导入
- [ ] git diff 确认只移动了代码，未改变逻辑
- [ ] 委托方法签名与原始方法完全一致（包括类型提示）
- [ ] `ruff check` 无新增错误

## 六、风险矩阵 & 缓解

| 风险 | 缓解 |
|------|------|
| `self.xxx` → `self._processor.xxx` 引用变更遗漏 | 每步提取后 grep 确认原方法引用已清理 |
| Processor 间共享状态不一致 | 使用同一个 `AgentContext` 引用（不拷贝） |
| `process()` 中直接访问已移动的方法 | process() 中的调用改为 `self._processor.method()` |
| 循环导入 | pipeline/ 包不导入 agent_core，只导入 shared 层 |
| 中文注释/字符串在替换中损坏 | 只用 Edit 工具精确替换，不批量处理 |