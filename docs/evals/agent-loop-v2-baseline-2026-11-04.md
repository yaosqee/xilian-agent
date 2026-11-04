# Agent 循环 v2 · P3 基线（2026-11-04）

> 命令：`uv run python -m evals.runner --mode all --timeout 90 --output evals/reports/live_all`
> 环境：Windows / deepseek-flash / thinking off（评分固定）/ 4 个工具全部注册（QWeather + Zhipu 可用）。
> 用例：`evals/cases/agent_loop_v2.jsonl`，40 条，train 20 / holdout 20。
> 完整逐条结果：`evals/reports/live_all.json`（本地生成，gitignore）。

## 总览

| 指标 | legacy (`LOOP_V2=0`) | loop (`LOOP_V2=1`) |
|---|---:|---:|
| 用例通过率 | 77.5% | **87.5%** |
| 工具调用率 | 65.0% | 65.0% |
| 正确工具率 | 76.9% | **88.5%** |
| 不该调准确率 | 100% | 100% |
| 多步完成率 | 0.0% | **50.0%** |
| 事实正确率（时间/日期） | 66.7% | 66.7% |
| 关键词命中率 | 92.9% | **100%** |
| 平均耗时 | **3.82s** | 4.88s |
| 平均工具调用数 | 0.70 | 1.02 |
| 平均模型调用数 | 4.70 | 5.00 |

分 split：

| split | legacy 通过率 | loop 通过率 |
|---|---:|---:|
| train（20） | 75.0% | 90.0% |
| holdout（20） | 80.0% | 85.0% |

分 category（通过率）：

| category | legacy | loop |
|---|---:|---:|
| weather | 87.5% | 100% |
| time | 66.7% | 66.7% |
| memory | 100% | 100% |
| search | 100% | 100% |
| no_tool | 100% | 100% |
| multi_step | 0.0% | 50.0% |

## 结论

1. **新循环的收益集中在多步与正确工具率**：多步 0→50%，正确工具 76.9→88.5%，总通过率 +10pp。旧路径回传时不带 tools，多步在结构上就不可能，数据吻合。
2. **时间/日期仍是硬伤（X 阶段）**：两种模式都只有 66.7%。失败集中在「今天几号」——模型要么编 2026-06-06，要么明说记不住；`DatetimeModule` 没有年月日 ground truth。
3. **多步仍有一半失败**：loop 的 3 条失败中，multi-01 只调了天气没调搜索；multi-05/06 连续两次 `query_weather` 而没有 `search_web`。不是循环限制，是模型工具选择/去重问题，P3 用例把问题量化出来了。
4. **旧路径 multi_step=0%**：除了「只调一个工具」，还出现 DeepSeek 的 DSML 文本漏进正文（`<｜｜DSML｜｜tool_calls>`），说明旧回传链路对工具协议的处理不够干净。
5. **search_web 当前返回 HTTP 错误**（日志 `search_web.http_error`），但用例只校验「是否调用工具」，所以 search 类通过率仍是 100%；P3 指标暂不评搜索结果质量。

## 顺带发现并修复

- `ToolRegistry.autodiscover()` 原先只消费模块级 `_PENDING` 队列。第一个 AgentCore 导入工具后队列清空，同一进程里第二个 AgentCore（P3 的 `--mode all`）拿不到任何工具，loop 模式首轮基线出现 `available_tools=[]`、工具调用率 0%。已加 `_AVAILABLE` 缓存重放（commit `7f76d1f`），并补 `tests/test_tool_registry.py`。
- P3 runner 现在会清空每个用例的 `ToolExecutor._call_counts`，避免连续天气用例触发每小时 6 次的频率限制。

## 下一步

- **X 时间保真**：`DatetimeModule` 注入 `YYYY-MM-DD 周X HH:MM` + 「问时间直接引用」；目标 time/date 6/6。
- **多步加固**：确认 loop 的 `first_tool_choice`/`auto` 对「顺便搜一下」类句式的覆盖；可能需要 policy 快路径或提示词约束。
- 再跑一次 `--mode all` 作为对照，报告覆盖写入本文件。

---

## 更新：X + 多步提示后（2026-11-04 18:45）

改动：`DatetimeModule` 输出完整日期 + HH:MM + 「直接引用，不要推算」；loop 在多意图消息前插一条工具规划提示；multi_step 用例改为明确需要两类工具（原 multi-01/05/06 可被天气工具单独覆盖）。

| 指标 | legacy | loop |
|---|---:|---:|
| 用例通过率 | 82.5% | **97.5%** |
| 正确工具率 | 76.9% | **100%** |
| 多步完成率 | 0.0% | **100%** |
| 事实正确率 | **100%** | **100%** |
| 不该调准确率 | 100% | 100% |
| 平均耗时 | **4.19s** | 5.77s |

- loop 只剩 1 条失败：multi-02 实际调用了 `query_weather + search_web`，但搜索服务 HTTP 错误，回复靠记忆列北京景点、没有出现「北京」二字，被 `must_contain` 判失败；**工具选择本身正确**。
- legacy multi_step 仍 0%（旧路径回传不带 tools，结构性限制）；时间从 66.7% → 100%。
- 搜索 API 仍不稳定，P3 只评「是否调用工具」，不评搜索结果质量；下一轮可加 `tool_success_rate`。

---

## 第三轮：评测加固后（2026-11-04 20:10，`bad6c43`）

加固内容：冻结用例（`cases_sha256=3d49b5cc`）、新增 `tool_success_rate`、搜索额度错误分类、时间兜底（精确时间钉在 user 前）。

| 指标 | legacy | loop |
|---|---:|---:|
| 通过率（train / holdout） | 85% / 85% | **100% / 100%** |
| 正确工具率 | 76.9% | **100%** |
| 多步完成率 | 0% | **100%** |
| 事实正确率 | 100% | **100%** |
| 工具执行成功率 | 76.9% | **69.4%** |
| 平均耗时 | 4.82s | 4.76s |

关键变化：
- 时间兜底生效：事实 100%，且 3×6 次时间类复跑全过（改前 24 次采样有 1 次只答日期）。
- 搜索失败被正确归因：loop 的 11 次 `search_web` 全部 429（智谱余额不足），错误文案改为"不要重复搜索"，重试消失，loop 平均耗时从 5.7s 降到 4.76s。
- `tool_success_rate` 暴露了此前被"调用即通过"掩盖的洞：**正确工具 100% ≠ 工具成功 100%**。

遗留：搜索额度是账号问题，充值或换供应商前，search/multi_step 的"质量"无法评估。


