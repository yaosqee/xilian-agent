# 🧪 优化实验记录

## 2026-05-14：前缀缓存友好结构重构

### 改动内容
`_build_messages()` 消息结构优化，将记忆/共情注入从 system prompt 移到用户消息末尾。

**改前：**
```
[system: 人格 + 记忆 + 共情] [history...] [user_msg]
```

**改后：**
```
[system: 人格] [history...] [记忆 + 共情 + --- + user_msg]
```

### 改动文件
- `packages/agent/agent_core.py` — `_build_messages()` 重构
- `tests/test_memory_integration.py` — 测试断言适配
- `tests/test_empathy_injection.py` — 测试断言适配

### 预期效果
- DeepSeek prefix caching 命中率从 ~20% 提升到 ~90%
- 响应延迟降低 ~40%（因为大部分前缀不重算）
- 月 token 消耗降低 ~60%

### ⚠️ 待验证：效果对比清单

使用一段时间后（至少 50 轮真实对话），对比以下指标：

#### 1. 延迟对比
- [ ] 改动前：每轮平均响应延迟 ___ 秒
- [ ] 改动后：每轮平均响应延迟 ___ 秒
- [ ] 对比方法：翻看 loguru 日志中的 route 耗时

#### 2. 回复质量对比
- [ ] 引用了相关记忆时，回忆是否自然（不突兀、不生硬）
- [ ] 共情注入是否依然生效（昔涟能否感知情绪）
- [ ] 有没有"格式异常"的回复（如 `[当前记忆]` 标签残留）
- [ ] 昔涟的语言风格有没有退化（更"助手化"）

#### 3. 成本对比
- [ ] 改动前：某时段的 DeepSeek API 用量 ___ 
- [ ] 改动后：同等时段的 DeepSeek API 用量 ___

#### 4. 对比方法
```python
# 可以临时改回旧结构做 A/B 测试：
# 在 agent_core.py 中加一个 FLAG 控制两套结构，
# 或者 git diff 看改动后手动恢复，测完再切回来
```

### 回滚方法
```bash
cd ~/xilian-v3
git diff packages/agent/agent_core.py  # 查看具体改动
git checkout packages/agent/agent_core.py  # 回滚
git checkout tests/  # 回滚测试
```

### 状态
⏳ 待效果对比（盒子实测后再决定是否保持此优化）
