# 测试覆盖补充计划

> R3-004: tool_executor / model_router / providers 三层零测试覆盖

## 策略

**仅测纯逻辑，不测 IO**。所有 LLM 调用、DB 操作、网络请求全部 mock。

## 范围

### 1. `test_tool_executor.py` — 新增（~80 行，5 个测试）

| 测试 | 覆盖路径 |
|------|---------|
| `test_execute_not_found` | 工具未注册 → fail |
| `test_execute_safe_mode` | 安全模式 + 非只读工具 → blocked |
| `test_execute_rate_limited` | 超过频率限制 → rate_limited |
| `test_execute_success` | 正常执行 → ToolResult.ok |
| `test_record_call_updates_counts` | _record_call 正确记录时间戳 |

Mock: ToolRegistry（返回假工具字典），DB（避免真实连接）

### 2. `test_model_router.py` — 新增（~100 行，5-6 个测试）

| 测试 | 覆盖路径 |
|------|---------|
| `test_init_no_keys` | 无 API Key → warning + 空 adapters |
| `test_init_with_deepseek_key` | DEEPSEEK_API_KEY 已设置 → adapter 创建 |
| `test_route_with_tools` | 正常路由 → 返回 ProviderResponse |
| `test_route_tool_error_retry` | tool error → 重试不带 tools |
| `test_get_current_model_info` | 返回当前 (provider, model) |
| `test_supports_tools_cache` | 缓存正确读写 |

Mock: adapter（模拟 ProviderAdapter），os.environ

### 3. `test_providers.py` — 新增（~50 行，结构验证）

| 测试 | 覆盖 |
|------|------|
| `test_all_adapters_satisfy_protocol` | 5 个 adapter 实现所有 Protocol 方法 |
| `test_get_available_models` | 每个 adapter 返回非空模型列表 |
| `test_provider_registry_complete` | PROVIDER_REGISTRY 包含所有 adapter |

无需 mock，纯导入 + 反射检查。

## 执行

一次写入 3 个文件，逐文件验证。测试不依赖外部 API——全部在 CI 可运行。

## 不纳入

- 集成测试（需要真实 LLM API Key）
- agent_core / database 测试（已有测试文件覆盖）
- 前端测试
