# 昔涟 V3.3 · API 参考文档

版本: 2026-05-20 | Base URL: `http://localhost:8000`

---

## 一、通用约定

### 鉴权

所有 `/api/chat` 和 `/api/chat/stream` 请求需传入 `user_id`。只有 `user_id == "hezi"`（owner）的消息会触发完整 Agent 管线，非 owner 消息被静默过滤。

### 响应格式

成功：直接返回数据（JSON 对象或数组）
错误：`{"error": "描述信息"}`

### 时间戳

所有时间戳为 Unix 秒（float），除非标注为 ISO 字符串。

---

## 二、对话核心

### `POST /api/chat`

同步聊天。阻塞等待 Agent 完整回复后返回。

**请求**：
```json
{
  "message": "今天天气真好呀",
  "user_id": "hezi",
  "stream": false
}
```

**响应**：
```json
{"reply": "嗯，风很轻呢。今天该讲什么样的故事才好呢 ♪"}
```

### `POST /api/chat/stream`

SSE 流式聊天。每个 token 以 `data: {"token": "..."}` 推送，结束信号 `data: [DONE]`。

**请求**：同 `/api/chat`，`stream` 字段忽略（始终流式）。
**响应**：Server-Sent Events 流。

---

## 三、对话历史

### `GET /api/conversation/history`

游标分页查询历史对话。`limit` 默认 10，最大 50。`before_id` 向前翻页。

**参数**：`?limit=20&before_id=100`
**响应**：
```json
{
  "items": [
    {
      "id": 99, "timestamp": 1716123456.0,
      "user_message": "你好", "assistant_reply": "初次见面呢……",
      "emotion_primary": "平静", "affection_score": 2.5
    }
  ],
  "oldest_id": 80,
  "has_more": true
}
```

---

## 四、问候与自主系统

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/greeting` | GET | 获取破冰问候或时间问候。`{"greeting":"...", "is_first_meeting":true}` |
| `/api/autonomy/status` | GET | 自主系统运行状态（running/paused/dnd 等） |
| `/api/autonomy/pending-greeting` | GET | 获取待展示的 Nudge 问候（读即消费） |
| `/api/autonomy/ack-greeting` | POST | 确认收到问候（兼容接口，实际 get 已消费） |
| `/api/autonomy/pause` | POST | 暂停自主问候 |
| `/api/autonomy/resume` | POST | 恢复自主问候 |
| `/api/autonomy/settings` | PATCH | 更新自主设置（threshold、dnd 等） |

---

## 五、笔记本

### `GET /api/notebook/notes`

获取活跃笔记列表。`limit` 默认 10。

**响应**：
```json
[
  {
    "id": 6, "kind": "note",
    "content": "下周五北京出差",
    "tags": null, "importance": 0.5, "is_active": 1,
    "due_date": 1779984000.0, "created_at": 1779240573.0,
    "session_id": "a9e3ebaf6a03"
  }
]
```

`due_date` 为 null 表示无时间信息。`due_date` 已过去时前端半透明 + "已过去" 标签。

### `DELETE /api/notebook/notes/{note_id}`

真实删除笔记（非软删除）。

### `GET /api/notebook/tasks`

获取待办任务列表。

### `POST /api/notebook/tasks/{task_id}/complete`

标记任务完成（软删除状态改为 done）。

### `POST /api/notebook/tasks/{task_id}/cancel`

取消任务（软删除）。

### `DELETE /api/notebook/tasks/{task_id}`

真实删除任务。

---

## 六、自传体

### `GET /api/autobiography`

按日期查询自传全文。

**参数**：`?date=2026-05-19`
**响应**：
```json
{
  "date": "2026-05-19", "content": "第 1 天 · 2026年05月19日\n\n...",
  "mood_summary": "偏期待", "word_count": 688
}
```

无 `date` 参数时返回最近一篇。

### `GET /api/autobiography/list`

自传列表（日期+情绪摘要+字数）。`limit` 默认 30。

### `POST /api/autobiography/generate`

手动触发当日自传生成。

### `GET /api/reflection/latest`

获取最新一篇每周反思（SAGE 四问）。

---

## 七、情感系统

### `GET /api/emotion`

当前情绪快照（PAD 坐标 + 11 维分布）。

**响应**：
```json
{
  "pad_p": 0.42, "pad_a": -0.15, "pad_d": 0.20,
  "primary_emotion": "平静", "primary_intensity": 0.6,
  "dimensions": {"喜悦": 0.1, "平静": 0.6, ...}
}
```

### `GET /api/emotion/history`

PAD 历史轨迹。`limit` 默认 50。

### `GET /api/emotion/stats`

情绪统计摘要（主要情绪比例、平均 PAD 坐标等）。

---

## 八、好感度

### `GET /api/affection`

当前好感度状态。

**响应**：
```json
{
  "score": 12.5,
  "level": 1,
  "level_label": "昔涟才刚开始认识你呢",
  "total_conversations": 25
}
```

---

## 九、用户印象

### `GET /api/user/portrait`

获取昔涟对伙伴的当前印象文档。

**响应**：
```json
{
  "portrait": "盒子是一个喜欢安静的人……（全文）",
  "version": 3,
  "updated_at": "2026-05-20T05:00:00"
}
```

---

## 十、记忆

### `GET /api/memories/recent`

最近的情景记忆摘要。`limit` 默认 20。

---

## 十一、会话管理

### `POST /api/session/reset`

清除当前会话历史（context + conversation_logs）。不影响 episodic_memories 和 notebook_entries。

### `GET /api/status`

Agent 综合状态（历史消息数、情感状态、记忆数、好感度）。

### `GET /api/encoding-status`

记忆编码状态（idle/waiting/encoding/done）。

---

## 十二、背景图片

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/background/current` | GET | 当前背景图片 URL |
| `/api/background/upload` | POST | 上传自定义背景（multipart/form-data） |

---

## 十三、审计与安全

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/audit/logs` | GET | 审计日志列表 |
| `/api/audit/stats` | GET | 审计统计摘要 |
| `/api/security/status` | GET | 安全过滤器状态 |
| `/api/privacy/forget` | POST | 隐私：清除指定用户相关数据 |

---

## 十四、技能

### `GET /api/skills`

列出当前加载的所有技能（SkillsLoader）。

---

## 端点速查表

| 路径 | 方法 | 分类 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/chat` | POST | 对话 |
| `/api/chat/stream` | POST | 对话 |
| `/api/conversation/history` | GET | 对话 |
| `/api/greeting` | GET | 问候 |
| `/api/autonomy/*` | GET/POST/PATCH | 自主系统 |
| `/api/notebook/notes` | GET/DELETE | 笔记本 |
| `/api/notebook/tasks` | GET/DELETE | 笔记本 |
| `/api/notebook/tasks/{id}/complete` | POST | 笔记本 |
| `/api/notebook/tasks/{id}/cancel` | POST | 笔记本 |
| `/api/autobiography` | GET | 自传 |
| `/api/autobiography/list` | GET | 自传 |
| `/api/autobiography/generate` | POST | 自传 |
| `/api/reflection/latest` | GET | 自传 |
| `/api/emotion` | GET | 情感 |
| `/api/emotion/history` | GET | 情感 |
| `/api/emotion/stats` | GET | 情感 |
| `/api/affection` | GET | 好感度 |
| `/api/user/portrait` | GET | 印象 |
| `/api/memories/recent` | GET | 记忆 |
| `/api/session/reset` | POST | 会话 |
| `/api/status` | GET | 会话 |
| `/api/encoding-status` | GET | 会话 |
| `/api/background/current` | GET | 背景 |
| `/api/background/upload` | POST | 背景 |
| `/api/audit/logs` | GET | 审计 |
| `/api/audit/stats` | GET | 审计 |
| `/api/security/status` | GET | 安全 |
| `/api/privacy/forget` | POST | 隐私 |
| `/api/skills` | GET | 技能 |

---

*本文档随端点增删持续更新。最后修订：2026-05-20*
