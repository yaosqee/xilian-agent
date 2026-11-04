# P3 评测集：Agent 循环 v2

量化「该不该调工具」，不评人格文风。40 条用例，train / holdout 各 20。

## 快速开始

```bash
# 不联网的 harness 冒烟（报告标 SIMULATED，只验证链路）
uv run python -m evals.runner --mode fake

# 真实 AgentCore，单条冒烟
uv run python -m evals.runner --mode legacy --limit 1
uv run python -m evals.runner --mode loop --limit 1

# 完整基线：LOOP_V2=0 vs 1
uv run python -m evals.runner --mode all --output evals/reports/latest
```

报告输出 `evals/reports/<name>.json` 和 `.md`（目录已 gitignore）。
默认 `--thinking off`：DeepSeek thinking 开启时，强制 `tool_choice` 会返回
`400 Thinking mode does not support this tool_choice`；P3 需要先固定这个变量。

## 指标

| 指标 | 含义 |
|---|---|
| `tool_call_rate` | 有工具调用的用例占比（含不该调的） |
| `correct_tool_rate` | 期望工具是该轮实际调用子集的占比（只算 expect_tools 非空） |
| `no_tool_accuracy` | `no_tool` 类用例零调用的占比 |
| `multi_step_completion` | multi_step 类达到 ≥2 次调用且期望工具齐全 |
| `fact_accuracy` | time/date/weekday 类与真实时钟比对 |
| `keyword_accuracy` | `must_contain` 关键词命中 |
| `case_pass_rate` | 上述条件 + 无执行错误 |
| `avg_latency_ms` / `avg_tool_calls` / `avg_model_calls` | 均值 |

## 用例格式

```json
{"id":"weather-01","split":"train","category":"weather","message":"杭州今天热吗？",
 "expect_tools":["query_weather"],"min_tool_calls":1,"must_contain":["杭州"]}
```

字段：`id` / `split` / `category` / `message` / `expect_tools` /
`min_tool_calls` / `max_tool_calls` / `fact_check` / `must_contain`。

分类固定：weather 8、time 6、memory 6、search 6、no_tool 8、multi_step 6。

## live 模式说明

- 每条用例使用临时 DB；跳过 24 条角色记忆播种（与工具决策无关）。
- 用例之间清空 history / pending / 情绪快照；后台任务在下一轮前 drain。
- 工具调用通过包装 `agent.tool_executor.execute` 记录，新旧路径都覆盖。
- 可用工具取决于 `.env` 的 QWeather / Zhipu Key；缺 Key 时对应工具
  autodiscover 会跳过，报告里的 `available_tools` 会显示实际注册项。
- `fake` 模式按期望生成完美脚本，只用于 CI / 报告渲染，不代表模型能力。
