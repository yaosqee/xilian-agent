# M2 · 声明式模型路由（计划）

> 日期：2026-11-04
> 状态：M2-0 **已定稿**（2026-11-04）；M2-1/M2-2/M2-3a **已实施**（2026-11-05），V2 默认关闭
> 目标：把「任务 → 模型」从散落在代码/DB/env 的隐式规则，收敛成一份可校验、可解释、可回退的声明式配置。
> 范围：只改模型路由与配置层，不动人格、记忆、工具实现、评测用例。

---

## 1. 为什么做

当前一次 `router.route(task_type, ...)` 的选型结果，可能由 5 个地方共同决定：

| 层 | 位置 | 作用 |
|---|---|---|
| 代码默认 | `ModelRouter._init_default_adapter()` | 无 DB 时的 powerful/fast/reasoning |
| 代码常量 | `DEFAULT_TIER_MODELS` | 首次播种 DB 的默认模型名 |
| 任务映射 | `TASK_TIER_MAP` / `TASK_GROUPS` | task_type → tier / group |
| 环境变量 | `.env` | API Key、base URL、embed |
| DB | `model_configs` 的 `tier:*` / `override:*` | 设置面板写入的覆盖 |
| 迁移 | `alembic/versions/004_model_config.py` | 又一份默认值 |

问题不是「配置项太多」，而是**没有一个地方能回答**：

> 当前这个 task 实际会用哪个 provider + model？为什么？如果它不可用，会退到谁？

M2 要补的就是这一层。

---

## 2. 当前生效路由（2026-11-04 快照）

本机 `.env`：`LOOP_V2=1`；DB `model_configs` 只有 tier 行，无 override。

| 任务组 | 代表任务 | tier | 当前模型（DB） |
|---|---|---|---|
| dialogue | `chat` / `empathy` / `proactive_greeting` / `image_response` | powerful | `deepseek-flash` |
| tool_decision | `tool_decision`（loop 工具决策） | powerful | `deepseek-flash` |
| background | `memory_encoding` / `autobiography` / `reflection` / `dream` 等 | fast | `deepseek-flash` |
| reasoning | `reasoning` / `code` / `planning` | reasoning | `deepseek-v4-pro` |
| embedding | 记忆向量 | embed | `BAAI/bge-m3`（SiliconFlow，独立表） |

代码默认的 reasoning 是 `deepseek-reasoner`，但本机 DB 把它覆盖成了 `deepseek-v4-pro`。**M2 的默认配置必须以“当前实际生效值”为准，而不是以代码默认值为准**，否则一开 V2 就会换模型。

---

## 3. 目标与非目标

### 目标

1. 一份声明式配置能表达：providers / models / profiles / routing / limits。
2. 每个 task 都能解析出「主模型 + fallback 链 + 来源」。
3. 能力不满足时（如模型不支持 tools）自动换下一个，而不是静默禁用工具。
4. 保留设置面板和现有 DB 覆盖；迁移期可回滚。
5. 配置错误启动即报错，不静默选一个模型。

### 非目标（本轮不做）

- 不重写 ProviderAdapter。
- 不改人格提示词、记忆、情绪、工具实现。
- 不改评测用例。
- 不删除老 `tier:*` / `override:*` 路径。
- 不把 API Key 写进配置文件。

---

## 4. 配置格式（建议 TOML）

选 TOML 的理由：Python 3.12 自带 `tomllib`，零新依赖；只读配置不需要写回；比 JSON 可读，比 YAML 少一个依赖。

建议路径：`config/model_routing.toml`（开发与打包目录同级；frozen 模式取 exe 所在目录）。

### 4.1 Schema 草案

```toml
version = 1

[providers.deepseek]
base_url = "https://api.deepseek.com"
api_key_env = "DEEPSEEK_API_KEY"

[providers.openai]
base_url = "https://api.openai.com/v1"
api_key_env = "OPENAI_API_KEY"

[models.deepseek-flash]
provider = "deepseek"
capabilities = ["tools", "streaming"]
context_window = 128000
max_output_tokens = 8000
cost_per_1k_in = 0.0
cost_per_1k_out = 0.0

[models.deepseek-v4-pro]
provider = "deepseek"
capabilities = ["tools", "streaming", "thinking"]
context_window = 128000
max_output_tokens = 8000

[profiles.dialogue]
model = "deepseek-flash"
fallbacks = ["deepseek-v4-pro"]
temperature = 0.65
max_tokens = 800

[profiles.background]
model = "deepseek-flash"
temperature = 0.3
max_tokens = 800

[profiles.tool_decision]
model = "deepseek-flash"
requires = ["tools"]
fallbacks = ["deepseek-v4-pro"]
temperature = 0.65
max_tokens = 800

[profiles.reasoning]
model = "deepseek-v4-pro"
temperature = 0.3
max_tokens = 2000

[embedding]
# 向量模型独立成段：不进 profiles / routing，避免和对话模型混在一起
provider = "siliconflow"
model = "BAAI/bge-m3"
dimensions = 1024
base_url = "https://api.siliconflow.cn/v1"
api_key_env = "EMBED_API_KEY"

[routing_groups]
# 未单列的 task 落组默认；reasoning/code/planning 单独成组，不落回 dialogue
dialogue = "dialogue"
background = "background"
tool_decision = "tool_decision"
reasoning = "reasoning"

[routing]
# 可选：单任务覆盖组默认
chat = "dialogue"
empathy = "dialogue"
tool_decision = "tool_decision"
memory_encoding = "background"
reasoning = "reasoning"
```

### 4.2 解析模型

```text
task_type
  → routing[task_type]（显式）
  → routing_groups[group]（组默认）
  → profile
  → model + fallbacks
  → provider + adapter
```

`requires` 是能力断言：例如 `["tools"]`。解析时检查 `ModelPolicy`；不满足则沿 `fallbacks` 找第一个满足的模型。

> 注意：现有 `TASK_GROUPS` 没有 `reasoning` 组，`reasoning/code/planning` 会被 `task_group()` 归到 dialogue。M2 必须显式补 `reasoning` 组，否则文件里 reasoning profile 不会生效。

### 4.3 优先级

```text
内置默认 < config/model_routing.toml < DB UI 覆盖（source='ui'） < 环境变量（仅密钥/base_url）
```

- API Key 只从 `api_key_env` 指向的环境变量读。
- `override:<task>` 仍然允许，作为最高优先级的 task 级覆盖。
- 如果 DB 里只有旧 tier 行（`source='legacy'`），V2 不直接拿它覆盖文件，避免文件永远失效；旧行保留给 `MODEL_ROUTING_V2=0` 回滚。

---

## 5. 兼容与迁移（关键）

### 5.1 现状风险

本机 DB 已有 `tier:powerful` / `tier:fast` / `tier:reasoning` 三行。如果 V2 继续让所有 DB 行覆盖文件，那么**文件写什么都不生效**；如果直接忽略 DB，设置面板又会失效。

### 5.2 建议

1. 新增 `model_configs.source` 列（migration **007**，当前 head 是 006）：
   - `legacy`：迁移前已有的 tier/override 行；
   - `ui`：M2 之后设置面板写入的覆盖。
2. V2=1 时：
   - 文件是基线；
   - 只让 `source='ui'` 的 DB 行覆盖；
   - `legacy` 行仅用于迁移和回滚，日志提示一次。
3. 首次 V2 启动：
   - 把当前 `legacy` tier 行导出成 `config/model_routing.toml`（或生成 `.local.toml`），保证默认路由与今天一致；
   - 用 golden test 对比导出前后的路由结果。
4. V2=0：
   - 完全走旧逻辑，忽略 `source`，所有旧行照常生效。

### 5.3 设置面板（重做）

决定：不复用现有 tier 编辑面板，按 DSH 风格重做，分两步交付。

**信息模型（四层）**

```text
Providers（供应商：base_url + api_key_env）
  └── Models（模型：能力 / 上下文 / 成本）
        └── Profiles（用途：dialogue / background / tool_decision / reasoning）
               └── Routing（task_type → profile）
```

**界面五块**

| 区块 | 内容 | 第一版 |
|---|---|---|
| Models | 模型卡片：能力徽章（tools/vision/thinking）、上下文、价格 | 只读 |
| Profiles | 每个用途选模型 + fallback 排序 | 只读 |
| Routing | task → profile 一览 | 只读 |
| Effective | 每个 task 的 `effective_model` / `source` / `fallbacks` | 只读 |
| Embedding | 向量模型单独卡片：provider / model / dimensions / 最近写入时间 | 只读 |

**M2-3a（只读）**：`/api/models/config` 返回解析结果 + 来源；面板先只展示上面五块。
**M2-3b（可编辑）**：Models/Profiles 下拉切换、fallback 增删、保存写 DB `source='ui'`；提供「恢复文件默认」（删除 ui 行）。

Embedding 第一版**只读**：换向量模型会让已有向量失效，必须走「重新索引」流程，不做随手切换。

---

## 6. 分阶段实施

| 阶段 | 内容 | 产出 | 不改什么 | 状态 |
|---|---|---|---|---|
| **M2-0** | 本文档：schema、优先级、迁移、验收 | 计划确认 | 不改代码 | ✅ 2026-11-04 |
| **M2-1** | `packages/shared/model_config.py`：TOML 加载、schema 校验、env 插值、profile 解析 | 纯函数 + 单测；**不接 router** | 不改路由行为 | ✅ 2026-11-05（12 tests） |
| **M2-2** | `ModelRouter` 接入 V2，`MODEL_ROUTING_V2=0` 开关；golden route tests | 默认配置下路由与今天一致 | 不改 UI | ✅ 2026-11-05（19 tests） |
| **M2-3a** | `/api/models/config` 返回解析结果 + 来源；面板重做为只读五块（Models/Profiles/Routing/Effective/Embedding） | 能看到「现在用谁」 | 不做编辑 | ✅ 2026-11-05 |
| **M2-3b** | 可编辑：切换模型、fallback 增删、保存写 DB `source='ui'`、恢复文件默认 | UI 能改且立即生效 | 不动文件基线 | 待开始 |
| **M2-4** | 打开默认、迁移旧 DB、更新文档、重跑 P3 | 默认启用 + 回归 | 不删旧路径 | 待开始 |

建议 M2-1/M2-2 合并验收：只有 pure loader 通过、且 golden route 全绿，才允许打开开关。

---

## 7. 验收标准

### 功能

- `MODEL_ROUTING_V2=0`：现有 676 tests 全绿，路由结果与快照一致。
- `MODEL_ROUTING_V2=1` + 默认文件：dialogue / tool_decision / background / reasoning 的 provider+model 与快照一致。
- 缺模型、缺能力、缺 Key 时有明确错误，不静默选别的模型。
- `fallbacks` 命中时日志包含 `task / from / to / reason`。
- `/api/models/config` 能看到每个 task 的 `effective_model`、`source`、`fallbacks`。
- 面板保存后立即生效（reload 后 effective 变化），且能一键「恢复文件默认」。
- Embedding 卡片单列只读；换向量模型必须显式走重新索引流程。
- 配置文件不含任何密钥明文。

### 工程

- 新增 loader/校验/优先级/fallback/golden route 测试。
- 现有 `tests/test_model_router*`、`tests/test_model_policy*`、`tests/test_http_channel.py` 不回归。
- `evals --mode fake` 冒烟通过；P3 基线不被无意改变（除非显式换模型）。

### 回滚

- 删掉 `MODEL_ROUTING_V2=1` 即回到旧路径。
- `model_configs` 旧行不删除，`source='legacy'` 保留。
- 文件缺失时 V2 启动失败并提示路径，不静默回退到旧逻辑（避免“以为在用文件”）。

---

## 8. 风险

| 风险 | 处理 |
|---|---|
| DB 旧 tier 行让文件失效 | 加 `source` 列；V2 只认 `ui` 行；先导出再做 golden test |
| 设置面板保存后不生效 | M2-3 明确 tier → profile 映射；保存后 reload 并返回 effective |
| 打包后读不到 config | 用 `_get_env_dir()` 定位；`xilian.spec` 增加 `config/` 数据；缺失时启动报路径 |
| 配置文件被误写密钥 | 只允许 `api_key_env`；启动时检测疑似 `sk-` 明文并拒绝 |
| 热重载把坏配置带进运行态 | reload 先解析校验，失败保留旧配置并报错 |
| adapter 元数据与配置冲突 | 明确：配置是路由事实，adapter 元数据只做兜底/展示 |
| `deepseek-reasoner` vs `deepseek-v4-pro` 命名差异 | 默认文件按当前 DB 的实际值生成，golden test 锁住 |
| 评测/生产口径漂移 | M2-4 用同一份配置跑一次 `--mode all`，报告记录配置 hash |

---

## 9. 已确认决策（2026-11-04）

| # | 问题 | 决定 | 理由 / 影响 |
|---|---|---|---|
| 1 | 格式 | **TOML**：`config/model_routing.toml` | Python 3.12 自带 `tomllib`，零依赖、可注释；YAML 有隐式类型坑，JSON 不便手改。DB 覆盖存 JSON 行 |
| 2 | 优先级 | **文件基线 < DB `source='ui'` < env（仅密钥）** | 「文件完全优先」会让设置面板失效；「DB 全量覆盖」会让文件永不生效。`legacy` 行 V2 下忽略、回滚时生效 |
| 3 | UI | **重做，DSH 风格，分 M2-3a 只读 / M2-3b 可编辑** | 先让「现在用谁、为什么」可见，再做编辑；见 §5.3 |
| 4 | 开关 | **`MODEL_ROUTING_V2=0` 先验证**；M2-2 + golden tests 通过后打开，M2-4 再默认 1 | 路由错 = 所有对话错；开关是一行回滚，不是可选优化 |
| 5 | embedding | **纳入 `[embedding]` 独立段；UI 单列只读；DB `embed_config` 保留为 ui 覆盖** | 换向量模型需重嵌入，不能随手切 |

---

## 10. 相关文件

- `packages/shared/model_router.py` — 路由主流程、DB 加载、reload、stats
- `packages/shared/providers/__init__.py` — TaskType / TASK_TIER_MAP / TASK_GROUPS / TierConfig
- `packages/shared/providers/model_policy.py` — 能力矩阵
- `packages/shared/database/_manager.py` — `model_configs` / `embed_config` CRUD
- `alembic/versions/004_model_config.py` — 现有默认播种
- `gateway/channels/http_channel.py` — `/api/models/*`
- `packages/frontend/src/components/panels/SettingsPanel.tsx` — 设置面板
- `packages/frontend/src/stores/modelStore.ts` — 前端模型状态
- `evals/runner.py` — 评测用临时 DB，默认模型播种

---

## 11. M2-1 实施记录（2026-11-05）

已落地，未接 `ModelRouter`，现有路由行为不变。

| 文件 | 内容 |
|---|---|
| `packages/shared/model_config.py` | `ModelRoutingConfig` / `ProviderSpec` / `ModelSpec` / `ProfileSpec` / `EmbeddingSpec` / `ResolvedRoute`；TOML 加载、schema 校验、`${ENV}` 插值、明文密钥拒绝、能力 fallback |
| `config/model_routing.toml` | 按当前实际路由导出的默认基线：dialogue/tool_decision/background = Flash，reasoning = Pro，embedding 独立段 |
| `packages/shared/providers/__init__.py` | `TASK_GROUPS` 新增 `reasoning` 组；`TASK_GROUP_TIERS` 同步 |
| `tests/test_model_config.py` | 12 条：默认路由、effective routes、组默认、reasoning 组、能力 fallback、非法引用、未知能力、明文密钥、env 插值、缺文件、embedding |

验证：

```bash
uv run pytest tests/test_model_config.py -q   # 12 passed
uv run pytest -q --ignore=tests/test_personality_regression.py  # 688 passed / 8 skipped
```

尚未做：`ModelRouter` 接入、`MODEL_ROUTING_V2` 开关、DB `source='ui'`、API/UI。

---

## 12. M2-2 实施记录（2026-11-05）

已接入 `ModelRouter`，`MODEL_ROUTING_V2` 默认 0，现有路径不受影响。

| 文件 | 内容 |
|---|---|
| `packages/shared/model_router.py` | `MODEL_ROUTING_V2` 开关；V2=1 时 `task → profile → model`；`tools` 非空时追加 `requires=["tools"]`；显式 `temperature/max_tokens` 优先于 profile；`get_current_model_info()` / `ModelPolicy` / `supports_vision()` 读配置 |
| `packages/shared/model_config.py` | `resolve(extra_requires=...)`：运行时能力约束可触发 fallback |
| `gateway/channels/http_channel.py` | `/api/status` 暴露 `routing_v2` |
| `tests/test_model_router.py` | 17 条：开关默认、缺配置失败、10 个 task golden route、旧 tier 忽略、profile 默认值、显式参数优先、当前模型、能力矩阵 |
| `tests/test_model_config.py` | 新增 `extra_requires` 能力 fallback（合计 19 条 M2-2 新增） |

验证：

```bash
uv run pytest tests/test_model_router.py tests/test_model_config.py -q  # 45 passed
uv run pytest -q --ignore=tests/test_personality_regression.py          # 707 passed / 8 skipped
```

已知限制（M2-3 处理）：

- V2 下暂时忽略 DB `tier:*` / `override:*`；`source='ui'` 迁移和面板保存尚未接。
- fallback 只在**能力不满足**时生效；API 调用失败后的 provider 级 fallback 尚未实现。
- 配置文件的 `base_url` 还没有传给 adapter 构造函数；当前沿用各 adapter 的环境变量。
- 打包时 `config/` 还未加入 `xilian.spec`，M2-4 处理。

下一步：M2-3a 让 `/api/models/config` 返回 `effective_routes` + 来源，M2-3b 再做可编辑面板。

---

## 13. M2-3a 只读面板（2026-11-05）

已完成，只读展示，不提供编辑。

| 文件 | 内容 |
|---|---|
| `gateway/channels/http_channel.py` | `/api/models/config` 新增 `routing_v2` + `routing`：`providers/models/profiles/embedding/effective`，`effective` 每项带 `source`、`fallbacks`、`capability_fallback` 或 `error` |
| `packages/frontend/src/services/api.ts` | `RoutingConfigData` / `EffectiveRoute` 等类型；`ModelConfigResponse` 增加 `routing_v2` / `routing` |
| `packages/frontend/src/stores/modelStore.ts` | 保存 `routingV2` / `routing` |
| `packages/frontend/src/components/panels/SettingsPanel.tsx` | `routingV2=true` 时显示只读五块（Providers / Models / Profiles / Routing / Embedding）；V2=0 仍用原可编辑面板 |
| `tests/test_http_channel.py` | API 返回 effective route 的测试 |

验证：

```bash
cd packages/frontend && npm run build   # tsc + vite build 通过
uv run pytest tests/test_http_channel.py -q  # 15 passed
uv run pytest -q --ignore=tests/test_personality_regression.py  # 708 passed / 8 skipped
```

边界：

- 面板在 V2=1 时只读；编辑/保存/fallback 增删仍在 M2-3b。
- `effective.source` 目前固定 `file`，DB `source='ui'` 尚未接。
- V2=0 时仍显示原 tier/override 编辑面板，不受影响。
- 前端没有新增 API 请求，复用 `/api/models/config`。
