# 昔涟工具系统 · 意图路由层与工具溯源设计（增量改进）

> 日期：2026-08-13 | 状态：设计讨论完成，待实施
> 前置文档：[tool-system-audit-and-redesign.md](./tool-system-audit-and-redesign.md)（阶段 A 已实现：LLM 驱动工具选择）
> 本文是**增量补充**，解决阶段 A 落地后暴露的「LLM 自主决定确定性查询 → 幻觉」问题。

---

## 一、背景与问题诊断

### 1.1 已有的工作（阶段 A）

`tool-system-audit-and-redesign.md` 已把工具选择从「关键词匹配」改为「LLM 驱动」——`process()` 传入 `tools` 定义 + `tool_choice="auto"`，由模型自主决定是否调用工具。这套骨架（ToolRegistry / ToolExecutor / ResultWrapper）是合理的，**本文不推翻它**。

### 1.2 暴露的问题（本文要解决的）

阶段 A 落地后出现了一个实际 bug（用户亲身踩坑）：

1. 用户问「杭州天气怎么样」→ 模型 `tool_choice="auto"` 下**偷懒没调 `query_weather`**，直接编了一个温度。
2. 加强提示词后重试 → 还是没调，因为**第一次的幻觉答案已存入 `context.history`**，模型看到历史里有完整的「天气 Q&A」，以为这件事已经做过了。
3. 现有补丁 `_sanitize_fabrication()` 用正则清洗，但只保护 `context.history` 单通道，且 `tools_called = bool(tool_results)` 粒度太粗，无法真正防止污染。

### 1.3 根因诊断

> **病根不在工具系统骨架，而在「把确定性查询交给概率模型自主决定」。**

天气查询是**确定性事实检索**——答案只有一个正确来源（API）。让 `tool_choice="auto"` 自主决定「要不要查」，等于让一个概率系统做确定性决策。2026 年主流实践（分层路由）的共识是：**确定性查询走确定性路由，LLM 只在真正需要语言理解的地方做决策。**

---

## 二、设计目标

1. **确定性查询 → 确定性路由**：天气/搜索/记忆这类意图明确的查询，用规则强制指定工具，模型物理上不可能不调。
2. **模糊查询 → LLM 自主**：语义模糊的长尾查询保持 `tool_choice="auto"`，保留灵活性。
3. **工具结果可溯源**：`context.history` 区分「工具返回」和「LLM 生成」，杜绝上下文污染。

---

## 三、核心设计

### 3.1 意图路由层（IntentRouter）—— 治幻觉

在 `_perceive()` 之后、LLM 调用之前，插入一个**确定性意图分类器**：

```
process() 流程（改造后）：
  _perceive(payload)                    # 现有感知，不变
      ↓ 新增
  _route_intent(payload) → IntentRoute  # 确定性意图路由
      ├─ 天气意图   → tool_choice 强制 = query_weather
      ├─ 搜索意图   → tool_choice 强制 = search_web
      ├─ 记忆意图   → tool_choice 强制 = search_memory
      └─ 无匹配     → tool_choice = "auto"（LLM 自主，保持灵活性）
      ↓
  router.route(..., tools=..., tool_choice=<路由结果>)
```

**天气意图识别（规则 + 关键词，零成本零幻觉）**：

```python
# 意图路由的关键词表（确定性，无 LLM 参与）
_WEATHER_TRIGGERS = (
    "天气", "气温", "温度", "几度", "多少度",
    "下雨", "晴", "阴天", "下雪", "刮风",
    "预报", "湿度", "空气质量", "雾霾", "冷吗", "热吗",
    "带伞", "穿什么",
)
_CITY_PATTERN = re.compile(
    r"(北京|上海|广州|深圳|杭州|成都|武汉|西安|南京|重庆|"
    r"长沙|郑州|青岛|大连|厦门|苏州|天津|宁波|昆明|哈尔滨|"
    r"沈阳|济南|合肥|福州|南昌|石家庄|太原|乌鲁木齐|兰州|"
    r"西宁|银川|呼和浩特|南宁|贵阳|海口|拉萨)"
)

def _route_intent(self, payload: str) -> str | None:
    """确定性意图路由。返回 tool_name 或 None（None = 交给 LLM auto）。"""
    # 天气意图：天气触发词 +（城市名 或 泛指"今天/明天/后天"）
    if any(t in payload for t in _WEATHER_TRIGGERS):
        if _CITY_PATTERN.search(payload) or any(
            t in payload for t in ("今天", "明天", "后天", "现在", "外面")
        ):
            return "query_weather"
    # 搜索意图：明确的"帮我查/搜索"
    if any(t in payload for t in ("帮我查", "搜一下", "搜索", "查一下")):
        return "search_web"
    # 记忆意图：回溯过去的对话
    if any(t in payload for t in ("你还记得", "上次", "之前说过", "我们聊过")):
        return "search_memory"
    return None
```

**强制工具调用**：意图命中后，`tool_choice` 从 `"auto"` 改为精确指定：

```python
tool_choice = "auto"
forced_tool = self._route_intent(event.payload)
if forced_tool:
    tool_choice = {"type": "function", "function": {"name": forced_tool}}
result = await self.router.route(
    "chat", messages, tools=tools, tool_choice=tool_choice,
)
```

模型此时**物理上不可能不调工具**——它没有「偷懒编一个答案」的选项。

### 3.2 工具溯源（ToolProvenance）—— 治上下文污染

`context.history` 的消息加 `source` 字段，区分回复来源：

```python
# 现在（无法区分）：
{"role": "assistant", "content": "今天杭州天气晴朗，25度左右……"}

# 改造后（可区分）：
{"role": "assistant", "content": "今天杭州天气晴朗，25度左右……",
 "source": "tool_query_weather"}   # 工具返回
# 或
{"role": "assistant", "content": "今天杭州天气晴朗，25度左右……",
 "source": "llm_generated"}        # 纯 LLM（需警惕）
```

**未调工具却回答事实类问题时，在上下文里注入警告标记**：

```python
def _mark_unverified(self, reply: str, forced_tool: str | None) -> str:
    """未走工具却回答了事实类问题 → 注入"推测"标记，防止下轮当事实。"""
    if forced_tool is None and self._looks_like_factual(reply):
        return "[注意：以下为昔涟的推测，非实际查询结果]\n" + reply
    return reply
```

**关键点**：标记只作用于存入 `context.history` 的版本，不影响用户看到的原始回复。

### 3.3 结果验证（ResultValidation）—— 兜底

工具执行后，验证结果是否真的有数据。工具失败/返回空时，明确让 LLM 说「没查到」，而不是给它机会编：

```python
# _handle_tool_calls 内，工具结果为空时
if not result.success or not result.data:
    # 回传 LLM 时明确告知"查不到"，让 LLM 转述温柔降级，而非自由发挥
    tool_msgs.append({
        "role": "tool",
        "tool_call_id": tc_id,
        "content": "（工具未返回有效数据，请如实告知伙伴没查到，不要编造）",
    })
```

---

## 四、与现有系统的衔接

| 现有模块 | 本文改动 | 变更规模 |
|----------|---------|---------|
| `agent_core.py` `process()` | 插入 `_route_intent()`，`tool_choice` 改为路由结果 | ~30 行 |
| `agent_core.py` | 新增 `_route_intent()` / `_mark_unverified()` 两个方法 | ~60 行 |
| `agent_context.py` | `add_message` 增加 `source` 参数，history 消息带溯源 | ~15 行 |
| `_sanitize_fabrication()` | **降级为兜底保险**，不再是主力防线 | 保留，不再扩展 |
| ToolRegistry / ToolExecutor / ResultWrapper | **不动**，沿用阶段 A 成果 | 0 行 |

---

## 五、分层路由的边界（诚实声明）

意图路由对「天气、时间、搜索、记忆」这类**确定性查询**完美适用。但未来若新增「语义模糊」的工具（如「帮我分析这段代码」），规则路由抓不准，仍需 `tool_choice="auto"` + LLM。

正确的架构是**分层共存**：

```
Layer 1  规则路由（本文新增）  → 确定性意图，零成本零幻觉
Layer 2  LLM 自主（现有）      → 模糊长尾查询
```

两者不是替代，是叠加。`_route_intent()` 返回 `None` 时自然落到 Layer 2。

---

## 六、实施步骤

1. **步骤 1**：在 `agent_core.py` 新增 `_route_intent()` + 关键词表，`process()` 里插入路由逻辑，`tool_choice` 改为路由结果。
2. **步骤 2**：在 `agent_context.py` 的 `add_message` 增加 `source` 参数，`process()` 里给 assistant 消息标注来源。
3. **步骤 3**：新增 `_mark_unverified()`，未走工具的事实类回复注入「推测」标记。
4. **步骤 4**：`_handle_tool_calls` 里对空结果注入「不要编造」提示。
5. **步骤 5**：`_sanitize_fabrication()` 保留为兜底，但注释明确其为「最后保险，非主力」。
6. **验证**：
   - 问「杭州天气」→ 强制调 `query_weather`，无幻觉
   - 问「今天好累」→ 正常对话，不触发工具
   - 连续两轮问天气 → 第二轮不会重复错误答案（溯源标记生效）

---

## 七、与旧补丁的关系

`_sanitize_fabrication()` 的正则清洗**不删除**，但角色从「主力防线」降级为「最后保险」：

- **意图路由**（本文）→ 从根上防止「该调不调」
- **工具溯源**（本文）→ 从根上防止「污染扩散」
- **正则清洗**（旧）→ 兜住「意图路由漏判 + 模型仍编造」的残余情况

三者叠加，形成「路由 → 溯源 → 清洗」三层防御。清洗正则本身的缺陷（漏单点温度、`tools_called` 过粗）不再是要害，因为它不再是唯一防线。
