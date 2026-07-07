# 昔涟 V3 代码审计报告

> 生成时间：2026-06-05
> 审计范围：全项目逐层梳理
> 审计标准：正确性 Bug / 数据一致性 / 资源泄漏 / 安全问题 / 逻辑缺陷 / 前端特有

---

## 第1层：共享基础设施

### 1.1 packages/shared/database.py（旧文件，与 database/ 目录并存）

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L1-01 | **P1** | database.py | 全文 | **旧文件未删除，与 database/ 目录并存**。`database.py` 是拆分前的单体文件，`database/` 目录是拆分后的 Repository 模式。两者同时存在会导致 `from packages.shared.database import DatabaseManager` 的导入歧义（Python 优先导入目录中的 `__init__.py`，但旧文件可能造成混淆）。旧文件缺少 `images` 列和 `conversation_logs` 表的 `images` 字段，而 `_manager.py` 已包含。 |
| L1-02 | **P2** | database.py | 82 | **backup.py 中 `btoa()` 函数名与浏览器 API `btoa()` 冲突**。虽然 Python 中无同名内置函数，但容易误导开发者以为这是 Base64 编码函数（浏览器中 btoa = binary to ASCII）。实际功能是字节数格式化。 |
| L1-03 | **P1** | database.py / _manager.py | insert_log | **`conversation_logs` 表缺少 `images` 列定义**。旧 `database.py` 的 `_CREATE_CONVERSATION_LOGS` SQL 没有 `images` 列，但 `_manager.py` 的 `insert_log()` 方法尝试插入 `images` 字段。如果用旧文件建表，INSERT 会报错。`_manager.py` 的建表 SQL 也没有 `images` 列定义，但 `insert_log()` 插入了 11 个字段。 |
| L1-04 | **P2** | _manager.py | insert_log | **`insert_log()` 插入 `images` 字段但建表 SQL 中无 `images` 列**。`_CREATE_CONVERSATION_LOGS` 只定义了 10 列（无 images），但 INSERT 语句有 11 个占位符含 `images`。运行时会报 `table conversation_logs has no column named images` 错误。 |
| L1-05 | **P2** | _manager.py | insert_nudge_greeting | **`insert_nudge_greeting()` 只插入 10 列（无 images），与 `insert_log()` 的 11 列不一致**。如果 conversation_logs 表后来加了 images 列且有 NOT NULL 约束或无默认值，nudge_greeting 的 INSERT 会失败。 |
| L1-06 | **P2** | _manager.py | forget_user_data | **`forgetUser_data()` 使用 `f"DELETE FROM {table}"` 格式化 SQL**。虽然 `table` 来自硬编码列表而非用户输入，不存在注入风险，但这是不好的实践模式。 |
| L1-07 | **P2** | _manager.py | insert_session_summary_atomic | **手动 ROLLBACK 与 aiosqlite 自动事务管理冲突**。aiosqlite 在 `commit()` 前自动开启事务，但手动 `ROLLBACK` 可能与 aiosqlite 内部状态不一致。正确做法是使用 `async with conn` 上下文管理器或 `await conn.execute("BEGIN")` 显式控制。 |
| L1-08 | **P2** | _manager.py | get_emotion_stats | **情绪波动率算法 O(n²)**。旧 `_manager.py` 中用双重循环计算所有 PAD 点对的最大距离，当 snapshot 数量多时性能差。`emotion_repo.py` 中已优化为 O(n) 近似算法（从质心计算最大距离 ×2），但 `_manager.py` 未同步。 |
| L1-09 | **P2** | _manager.py | 全文 | **DatabaseManager 与 Repository 层的 commit 语义不一致**。`_base.py` 注释说"Repository 不自行 commit()，事务由 DatabaseManager 统一管理"，但 `ConversationRepository.insert_log()` 等方法实际上调用了 `await conn.commit()`。DatabaseManager 自己的方法也调用 `commit()`。两层都在 commit，语义混乱。 |
| L1-10 | **P1** | _manager.py | _try_alembic_migrate | **`_try_alembic_migrate()` 是 async 方法但内部调用 `subprocess.run()`（同步阻塞）**。这会阻塞整个事件循环。应使用 `asyncio.create_subprocess_exec()` 或 `await asyncio.to_thread(subprocess.run, ...)`。 |
| L1-11 | **P2** | _manager.py | update_embedding_status | **`update_embedding_status()` 当 `embedding_id` 为 None 时，将 `status` 写入 `embedding_id` 列**（第 710 行 `SET embedding_status=?, embedding_id=? WHERE id=?` vs 第 714 行 `SET embedding_status=? WHERE id=?`，else 分支只传了 2 个参数 `(status, memory_id)`）。这是正确的，但逻辑不直观——当没有 embedding_id 时，embedding_id 列保持原值不变。 |
| L1-12 | **P3** | _manager.py | get_autonomy_config | **`import json` 在方法内部重复导入**（第 1238 行和第 1252 行），文件顶部已有 `import json`。 |
| L1-13 | **P2** | _manager.py | 全文 | **DatabaseManager 同时包含所有 CRUD 方法 + Repository 实例**。`_manager.py` 有 2385 行，既保留了所有原始 CRUD 方法，又初始化了 3 个 Repository（`_conv`, `_emo`, `_episodic`），但 Repository 实例从未被使用——所有方法仍然是 DatabaseManager 自己实现的。这是拆分不完整的半成品状态。 |

### 1.2 packages/shared/database/（Repository 目录）

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L1-14 | **P1** | conversation_repo.py | insert_log | **ConversationRepository.insert_log() 包含 `images` 字段但建表 SQL 中无 `images` 列**。与 L1-04 相同问题。需要在 `_CREATE_CONVERSATION_LOGS` 中添加 `images TEXT DEFAULT '[]'` 列。 |
| L1-15 | **P2** | notebook_repo.py | insert_notebook | **NotebookRepository.insert_notebook() 签名与 DatabaseManager 不一致**。Repo 版本 `tags` 参数类型是 `str`，DatabaseManager 版本是 `list[str] \| None`。Repo 版本缺少 `due_date` 参数。调用方如果传 `due_date` 会静默丢失。 |
| L1-16 | **P2** | notebook_repo.py | get_notebook_today_diary | **Repo 版本使用 `DATE(created_at, 'unixepoch')=?` 做日期匹配**，而 DatabaseManager 版本用 Python 侧 `time.mktime()` 计算时间戳。两种实现行为可能不同（时区差异）。 |
| L1-17 | **P2** | notebook_repo.py | delete_notebook_entry | **Repo 版本是软删除（`is_active=0`），DatabaseManager 版本是硬删除（`DELETE FROM`）**。语义不一致，调用方可能期望不同行为。 |
| L1-18 | **P2** | notebook_repo.py | complete_task | **Repo 版本将 status 设为 `'completed'`，DatabaseManager 版本设为 `'done'`**。状态字符串不一致，会导致查询遗漏。 |
| L1-19 | **P2** | notebook_repo.py | cancel_task | **Repo 版本不设 `completed_at`，DatabaseManager 版本设了 `completed_at`**。 |
| L1-20 | **P2** | notebook_repo.py | insert_task | **Repo 版本 `due_at` 类型是 `float \| None`，DatabaseManager 版本是 `float`（默认 0.0）**。None vs 0.0 语义不同。 |
| L1-21 | **P2** | database/__init__.py | - | **只导出 DatabaseManager，Repository 类未导出**。外部无法直接使用 Repository，只能通过 DatabaseManager 间接调用，但 DatabaseManager 内部的 Repository 实例又没被使用。 |

### 1.3 packages/shared/events.py

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L1-22 | **P3** | events.py | 34 | **`summary()` 方法中 `self.payload[:50]` 对空字符串安全，但如果 payload 非常短则 `[:50]` 无实际截断效果**。无功能问题，仅是代码风格。 |

### 1.4 packages/shared/logging_config.py

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L1-23 | **P2** | logging_config.py | 15 | **日志格式中 `extra[trace_id]` 使用方括号访问**。如果某处 logger 调用未 bind trace_id，会输出空字符串而非报错（因为 `configure(extra={"trace_id": ""})` 提供了默认值）。这是正确设计，但日志格式中 trace_id 为空时显示为 `|  |` 不太美观。 |

### 1.5 packages/shared/vector_store.py

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L1-24 | **P1** | vector_store.py | _get_conn | **每次操作都创建新的 sqlite3 连接**。`_get_conn()` 在每次 insert/search/delete 时都 `sqlite3.connect()` + `enable_load_extension` + `sqlite_vec.load()`。频繁创建/销毁连接开销大，且 sqlite-vec 扩展加载是 CPU 密集操作。应使用连接池或线程局部缓存。 |
| L1-25 | **P2** | vector_store.py | rebuild_from_records | **`rebuild_from_records()` 逐条插入，每条都创建新连接**。对于大量记录（如 25 条角色记忆），会创建 25+ 个连接。应批量操作共享一个连接。 |
| L1-26 | **P2** | vector_store.py | insert | **insert 操作无幂等保护**。如果同一 `row_id` 重复插入，sqlite-vec 会报错（rowid 冲突）。没有 `INSERT OR REPLACE` 语义。 |
| L1-27 | **P2** | vector_store.py | search | **search 返回的 distance 值未归一化**。不同嵌入模型的距离范围不同，调用方可能误用。 |

### 1.6 packages/shared/backup.py

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L1-28 | **P1** | backup.py | run_backup | **备份时未暂停数据库写入**。`shutil.copy2` 复制 SQLite 文件时，如果同时有写入操作，可能复制到不一致的状态（WAL 模式下部分数据在 WAL 文件中）。应先执行 `PRAGMA wal_checkpoint(TRUNCATE)` 或使用 SQLite backup API。 |
| L1-29 | **P2** | backup.py | restore | **restore 使用同步 `shutil.copy2`**。在 async 函数中使用同步文件操作会阻塞事件循环。应使用 `await asyncio.to_thread()`。 |
| L1-30 | **P3** | backup.py | cleanup_old | **`shutil.rmtree()` 是同步调用**，在 async 函数中会阻塞事件循环。 |

### 1.7 packages/shared/marker_parser.py

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L1-31 | **P2** | marker_parser.py | _parse_marker | **`emotion` 标记解析时 `parts[2]` 转 float 无异常处理**。如果 LLM 输出 `[emotion:joy:abc]`，`float("abc")` 会抛出 ValueError，导致整个流式解析中断。 |
| L1-32 | **P2** | marker_parser.py | _parse_marker | **`pause` 标记解析时 `float(inner[6:])` 无异常处理**。同上，LLM 输出异常值会导致解析崩溃。 |
| L1-33 | **P3** | marker_parser.py | feed | **`_buffer` 是 dataclass 的可变默认值**。`_buffer: str = ""` 在 dataclass 中是安全的（str 不可变），但如果改为 list 则会有共享状态问题。当前无问题。 |

### 1.8 packages/shared/model_router.py

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L1-34 | **P2** | model_router.py | route | **`route()` 方法中 `model` 变量在 fallback 分支可能未定义**。当 `tier_cfg is None` 且进入 fallback 分支时，`model` 被赋值；但当 `tier_cfg` 存在且 adapter 也存在时，`model = tier_cfg.model_name`（第 406 行）。但如果 tier_cfg 存在而 adapter 为 None，进入第 394-404 行的 fallback，`model` 在第 404 行赋值后，第 406 行 `model = tier_cfg.model_name` 会覆盖 fallback 的 model。逻辑有 bug：fallback 分支设置 `provider` 和 `model` 后，第 406 行无条件执行 `model = tier_cfg.model_name`，覆盖了 fallback model。 |
| L1-35 | **P2** | model_router.py | route | **`kwargs.setdefault` 在 fallback 分支不生效**。第 408-409 行 `kwargs.setdefault("temperature", ...)` 和 `kwargs.setdefault("max_tokens", ...)` 只在 `tier_cfg` 存在且 adapter 也存在的分支执行。fallback 分支（tier_cfg 为 None）不会设置这些默认值。 |
| L1-36 | **P2** | model_router.py | _auto_seed_db | **`_auto_seed_db()` 将 API Key 明文写入数据库**。`model_configs` 表的 `api_key` 字段存储明文 API Key。虽然是本地 SQLite，但与 CLAUDE.md 中"外部 API Key 仅存储在 .env"的约定矛盾。 |
| L1-37 | **P3** | model_router.py | _init_default_adapter | **embed_provider 推断逻辑简单**。通过检查 base_url 是否包含 "siliconflow" 来推断 provider，如果用户使用自定义代理 URL 会推断错误。 |

### 1.9 packages/shared/providers/

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L1-38 | **P2** | anthropic.py | _convert_messages | **空 content 的 user 消息被丢弃**（第 224-225 行 `if content:` 过滤）。如果用户发送了图片但没有文本，content 为空字符串，消息会被丢弃。 |
| L1-39 | **P2** | anthropic.py | _convert_messages | **空 content 的 assistant 消息被丢弃**（第 220-221 行）。如果 assistant 只有 tool_calls 没有 text content，消息会被丢弃，导致 tool_use 块也丢失。 |
| L1-40 | **P1** | anthropic.py | _convert_messages | **assistant 消息有 tool_calls 但 content 为空时，整个消息被跳过**。第 204 行检查 `role == "assistant" and tool_calls`，但如果 content 为空且 tool_calls 存在，这个分支会正确处理。然而第 218-221 行的 `elif role == "assistant": if content:` 分支会丢弃空 content 的纯 assistant 消息。当 assistant 回复只有 reasoning_content 没有 content 时，消息丢失。 |
| L1-41 | **P2** | anthropic.py | _fix_role_alternation | **合并 content 时直接修改了 `prev` dict**（第 342-348 行）。由于 `prev = fixed[-1]`，修改 `prev` 实际修改了列表中的元素，这是预期行为，但如果传入的 messages 被其他地方引用，可能导致意外副作用。 |
| L1-42 | **P2** | mimo_adapter.py | chat | **MiMo chat() 返回类型声明为 `ProviderResponse` 但 Protocol 定义返回 `ProviderResponse \| str`**。当 `stream=True` 时应返回原始流对象，但 MiMo 不支持流式，声明不一致。 |
| L1-43 | **P2** | mimo_adapter.py | chat | **MiMoAdapter 不支持 `describe_image` Protocol 方法以外的 multimodal content 传递**。`chat()` 方法直接传递 messages，但未处理 image_url content block 的格式转换。 |
| L1-44 | **P2** | openai_adapter.py | - | **OpenAIAdapter 缺少 `describe_image` 方法实现**。ProviderAdapter Protocol 定义了 `describe_image` 方法，但 OpenAIAdapter 和 GoogleAdapter 都没有实现。调用时会抛出 AttributeError。 |
| L1-45 | **P2** | google_adapter.py | - | **GoogleAdapter 缺少 `describe_image` 方法实现**。同 L1-44。 |
| L1-46 | **P2** | deepseek.py | - | **DeepSeekAdapter 缺少 `describe_image` 方法实现**。同 L1-44。 |
| L1-47 | **P3** | base.py | ProviderAdapter | **`describe_image` 是 Protocol 的必需方法**，但大多数 adapter 不支持图片描述。应改为可选方法（提供默认实现抛出 NotImplementedError）。 |
| L1-48 | **P2** | anthropic.py | _convert_assistant_with_tools | **reasoning_content 以 `[thinking]` 前缀作为 text block 传递**，而非 Anthropic 原生的 thinking block。代码注释也提到了这个问题（第 264-266 行），但未修复。启用 extended thinking 时会导致 thinking 内容被当作普通文本显示给用户。 |

## 第2层：Agent核心引擎

### 2.1 关键模块

| # | 严重度 | 文件 | 行号/方法 | 问题描述 |
|---|--------|------|-----------|----------|
| L2-01 | **P0** | pipeline/multimodal.py | _resolve_image_url | **路径遍历漏洞**：`rel_path = url[len("/api/uploads/"):]` 未对 `..` 校验，攻击者可构造 `/api/uploads/../../etc/passwd` 读取服务器任意文件。 |
| L2-02 | **P1** | emotion_core.py | process_message | **异步竞态条件**：`process_message` 操作共享可变状态 `self.state`，无锁保护。并发消息处理时 PAD 值更新互相覆盖。 |
| L2-03 | **P1** | memory_manager.py | _embed_text | **零向量导致检索失效**：无 router 时返回 `[0.0]*1024`，零向量与任何向量 L2 距离都为 0，检索结果退化。应返回 None 走降级路径。 |
| L2-04 | **P1** | memory_manager.py | manage_capacity | **非原子删除导致数据不一致**：`vs.delete()` 和 `db.delete_episodic()` 是两次独立异步操作，一方失败会导致向量与关系数据不一致。 |
| L2-05 | **P1** | agent_context.py | _schedule_compression | **压缩失败时消息已丢失**：先移除最老消息再异步调度压缩，压缩失败或重启后原始消息无法恢复。 |
| L2-06 | **P1** | nudge_engine.py | TokenBucket.consume | **令牌永不自动补充**：`consume()` 不调用 `refill()`，`refill()` 需外部定时调用但无调用点。令牌耗尽后主动问候永久失效。 |
| L2-07 | **P1** | nudge_engine.py | _evaporate_later | **队列替换竞态**：创建新 PriorityQueue 替换旧队列，其他协程可能仍在操作旧队列引用，导致事件丢失。 |
| L2-08 | **P1** | nudge_engine.py | _decide | **Prompt 注入风险**：`event.payload` 中的 title/summary 直接拼入 LLM prompt，未经转义。 |
| L2-09 | **P1** | notebook_manager.py | _find_similar_jaccard | **字符级 Jaccard 假阳性严重**：`set(content)` 对中文按单字符拆分，语义不同的笔记被误判为重复。 |
| L2-10 | **P1** | notebook_manager.py | add_focus | **`archive_notebook_entries(0)` 参数疑似错误**：传入 0 语义不明，可能归档错误条目。 |

### 2.2 中低优先级问题

| # | 严重度 | 文件 | 行号/方法 | 问题描述 |
|---|--------|------|-----------|----------|
| L2-11 | **P2** | memory_manager.py | schedule_encoding | **浅拷贝导致数据共享**：`self._pending_context.copy()` 浅拷贝，嵌套可变对象在原对象和拷贝间共享。 |
| L2-12 | **P2** | memory_manager.py | retrieve_memories | **访问计数膨胀**：对检索结果中每条记忆都调用 `increment_access_count`，即使该记忆因 k 截断未被返回。 |
| L2-13 | **P2** | memory_manager.py | encode_memory | **访问 router 私有属性**：`self._router._embed_model` 直接访问私有属性，违反封装。 |
| L2-14 | **P2** | memory_manager.py | rebuild_embeddings | **重建非原子**：逐条更新状态为 done，中途失败部分记录标记 done 但向量可能无效。 |
| L2-15 | **P2** | portrait_manager.py | mark_dirty | **跨类访问私有属性**：`self._coarse_engine._tool_side_effect_seen = True` 直接修改其他类私有标志。 |
| L2-16 | **P2** | portrait_manager.py | build_retrieval_config | **话题 embedding 串行计算**：逐个 topic 调用 `embed()`，N 个话题需 N 次 API 往返。 |
| L2-17 | **P2** | autobiography_writer.py | _build_writing_prompt | **day_count 硬编码为 1**：每篇自传都显示"第 1 天"，与实际天数不符。 |
| L2-18 | **P2** | autobiography_writer.py | write_daily | **无重复写入保护**：cron 重复触发时同一天会写入多条自传记录。 |
| L2-19 | **P2** | nudge_engine.py | get_pending_greeting | **问候读即消费，崩溃丢失**：pending_greeting 被读取后立即清空，前端崩溃则问候永久丢失。 |
| L2-20 | **P2** | nudge_engine.py | _has_unanswered_greeting | **空消息判断逻辑脆弱**：`msg == ""` 假设空 user_message 代表自动问候，但用户也可能发空消息。 |
| L2-21 | **P2** | nudge_engine.py | AttentionScheduler.start | **无优雅停机**：`asyncio.sleep` 期间无法响应 `stop()`，最长等 5 秒。 |
| L2-22 | **P2** | coarse_grain_engine.py | force_coarse_all | **"强制"语义矛盾**：意在跳过阈值但内部仍检查 `L1_TRIGGER_COUNT`，可能静默失败。 |
| L2-23 | **P2** | emotion_analyzer.py | analyze | **无输入长度限制**：超长消息可能超出模型上下文窗口。 |
| L2-24 | **P2** | agent_context.py | _schedule_compression | **使用已弃用 API**：`asyncio.get_event_loop()` 在 Python 3.10+ 已弃用。 |
| L2-25 | **P2** | context_builder.py | build | **硬编码模块名判断异步**：用模块名列表决定是否走异步渲染，新增模块若未更新列表则静默走同步路径。 |
| L2-26 | **P2** | pipeline/multimodal.py | _desc_cache | **图片描述缓存无上限**：字典无限增长，处理大量图片时可能占用大量内存。 |
| L2-27 | **P3** | context_builder.py | estimate_tokens | **Token 估算精度有限**：CJK*0.6 + ASCII*0.25 是粗略近似。 |
| L2-28 | **P3** | pipeline/perception.py | perceive | **疑似废弃代码**：简单关键词匹配与 EmotionEngine 功能重叠。 |
| L2-29 | **P3** | pipeline/tool_handler.py | - | **空壳类**：仅有 `set_tools()` 注入方法，无处理逻辑。 |
| L2-30 | **P3** | micro_event_extractor.py | extract | **Prompt 模板注入风险低**：用户消息截断至 500 字但未转义。 |
| L2-31 | **P3** | notebook_manager.py | _set_cache | **缓存非线程安全**：`_embedding_cache` 是普通 dict，CPython GIL 下实际安全但非最佳实践。 |

---

## 第3层：工具系统

| # | 严重度 | 文件 | 行号/方法 | 问题描述 |
|---|--------|------|-----------|----------|
| L3-01 | **P0** | coding_delegate.py | --permission-mode bypassPermissions | **命令注入/权限绕过**：使用 `bypassPermissions` 模式启动 Claude Code，子代理可执行任意系统命令而无需确认。 |
| L3-02 | **P0** | coding_delegate.py | working_dir 参数 | **路径穿越**：`working_dir` 未做校验/沙箱限制，攻击者可传入敏感路径作为工作目录。 |
| L3-03 | **P0** | coding_delegate.py | prompt 拼接 | **Prompt 注入**：`task_description` 直接拼入 prompt 模板，未转义，配合 bypassPermissions 可执行任意命令。 |
| L3-04 | **P1** | tool_executor.py | _global_timeout=60.0 | **超时冲突**：执行器全局超时 60s，但 coding_delegate 内部超时 300s，外层先触发且子进程不被终止。 |
| L3-05 | **P1** | tool_executor.py | _check_rate_limit / _record_call | **频率限制竞态条件**：检查与记录之间非原子，并发协程可超过 max_frequency 限制。 |
| L3-06 | **P1** | coding_delegate.py | 子进程管理 | **子进程泄漏**：超时后未 `proc.kill()` 终止子进程，Claude Code 进程持续后台运行。 |
| L3-07 | **P1** | search_memory.py / query_weather.py / search_web.py | _register_template() | **模板注册死代码**：`_register_template()` 函数从未被调用，结果模板永远不会注册。 |
| L3-08 | **P1** | result_wrapper.py | user_context[:200] | **LLM Prompt 注入**：`user_context` 直接拼入 LLM prompt，恶意用户消息可操纵输出。 |
| L3-09 | **P2** | tool_registry.py | register() | **静默覆盖**：同名工具直接覆盖，无警告日志。 |
| L3-10 | **P2** | tool_registry.py | _PENDING 全局队列 | **多实例消费问题**：第一个实例 autodiscover 后清空队列，后续实例无法消费。 |
| L3-11 | **P2** | tool_executor.py | except Exception: pass | **静默吞异常**：工具使用日志写入失败被完全忽略。 |
| L3-12 | **P2** | tool_executor.py | execute() | **参数未校验**：`arguments` 未按工具 schema 做类型/必填校验。 |
| L3-13 | **P2** | coding_delegate.py | _find_claude glob 路径 | **Glob 不生效**：`Path(c).exists()` 不展开 glob，该候选路径永远不会匹配。 |
| L3-14 | **P2** | coding_delegate.py | _collect_files | **排序逻辑与注释不符**：注释说"最近 10 个"但按文件名字母排序。 |
| L3-15 | **P2** | query_weather.py | 各 API 调用 | **连接池浪费**：每个 API 调用都新建 httpx.AsyncClient，一次天气查询最多创建 5 个短命客户端。 |
| L3-16 | **P2** | search_memory.py | source 参数 | **枚举值未校验**：无效值静默返回空结果，无提示。 |
| L3-17 | **P2** | search_memory.py | 笔记本检索 | **性能隐患**：先取 50 条笔记再 Python 侧关键词匹配，数据量增长后效率低下。 |
| L3-18 | **P2** | search_web.py | search_intent 循环 | **只保留最后一个 intent**：循环中逐次覆盖，多个 intent 时前面的丢失。 |
| L3-19 | **P2** | skills_loader.py | text.split("---", 2) | **Front Matter 解析脆弱**：正文中包含 `---` 会错误截断。 |
| L3-20 | **P2** | skills_loader.py | load_all | **重复调用不清理**：旧技能残留。 |
| L3-21 | **P3** | tools/__init__.py | import 列表 | **导入不完整**：只导入了 coding_delegate 和 search_memory，缺少 query_weather 和 search_web。 |
| L3-22 | **P3** | result_wrapper.py | _failure_text | **错误匹配脆弱**：英文关键词匹配中文错误信息不可靠。 |
| L3-23 | **P3** | tool_registry.py | to_openai_tools | **required 处理不完整**：未处理 schema 顶层 required 数组。 |

---

## 第4层：Agent大脑（agent_core.py）

### 4.1 P1 严重问题

| # | 严重度 | 方法 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L4-01 | **P1** | process() | L637-674 | **Stream 模式下 `reply="[stream]"` 污染上下文**：流式响应时 reply 被设为字面量 `"[stream]"`，随后经过 `_extract_markers` 和 `_enforce_speech_rule` 处理，最终被写入 `context.history`。后续轮次模型会看到这个无意义文本，严重干扰对话质量。应在 stream 模式下跳过标记提取、语音兜底和历史写入。 |
| L4-02 | **P1** | process() | L540,546,608,739 | **实例级可变状态导致并发不安全**：`self._current_images`、`self._user_sent_sticker`、`self._pending_confirmation` 等均为实例属性，若两个事件并发处理，后一个调用会覆盖前一个的 `_current_images`，导致图片与消息错配、确认回路状态混乱。`process()` 方法整体不具备可重入性。 |
| L4-03 | **P1** | _handle_tool_calls() | L1126-1127 | **`result.data` 可能为 None 导致 AttributeError**：当 `result.error == "PENDING_CONFIRMATION"` 时，若 `result.data` 为 None，调用 `.get()` 将抛出 AttributeError，导致整个工具调用流程崩溃。 |
| L4-04 | **P1** | _ensure_character_memories() | L1542 | **同步文件 I/O 阻塞事件循环**：`with open(json_path, encoding="utf-8") as f: data = json.load(f)` 在 async 方法中使用同步文件读取，会阻塞整个 asyncio 事件循环。应使用 `aiofiles` 或 `asyncio.to_thread()`。 |
| L4-05 | **P1** | process() | L693,715,749,772 | **大量 fire-and-forget 任务无追踪，shutdown 时泄漏**：多处 `asyncio.create_task(...)` 创建后台任务但不存储引用（portrait_manager.extract_then_check_coarse、notebook_manager.auto_note_after_message、_encode_image_memory、_score_personality_consistency）。`shutdown()` 仅取消 `_cleanup_task` 和 `_pending_analysis`，上述任务在 DB 关闭后仍可能运行并抛异常。 |
| L4-06 | **P1** | reset_session() | L1497-1507 | **重置会话未清理大量状态变量**：`reset_session()` 仅清除了 context 和 DB 日志，但 `_affection_score`、`_affection_level`、`_total_conversations`、`_drift_counter`、`_round_count`、`_pending_confirmation`、`_sticker_cooldown`、`_emotion_flat_rounds`、`_last_modulated_params`、`_last_eval_data`、`_strategy_effectiveness`、`_icebreaker_pending`、`_current_images`、`_user_sent_sticker` 均未重置。 |

### 4.2 P2 中等问题

| # | 严重度 | 方法 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L4-07 | **P2** | _tick_icebreaker() | L868-872 | **破冰阈值逻辑失效**：注释称"2 轮后尝试生成，5 轮后强制生成"，但代码中两个分支均只设 `should_consolidate = True`，无任何区分。而 `_icebreaker_consolidate()` 始终以 `force=True` 调用 `consolidate()`，导致 2-4 轮时就强制生成，与设计意图不符。 |
| L4-08 | **P2** | process() | L664+L775 | **Sticker 冷却 off-by-one**：LLM 发送 sticker 后设 `self._sticker_cooldown = 3`，但同一轮末尾 `_tick_sticker_cooldown()` 立即递减为 2。实际冷却只有 2 轮而非预期的 3 轮。 |
| L4-09 | **P2** | _handle_confirmation() | L1234 | **确认词匹配过于激进**：`confirm_words` 包含单字"好"、"行"、"嗯"等，`any(user_text.startswith(w) for w in confirm_words)` 导致"好无聊"、"行吧算了"、"嗯不用了"均被误判为确认。 |
| L4-10 | **P2** | _resolve_sticker() | L1342 | **无效 sticker_id 返回空文件路径**：当 sticker_id 不在 catalog 中时，返回 `{"id": sticker_id, "file": ""}`，下游可能尝试使用空文件路径导致失败。应返回 None。 |
| L4-11 | **P2** | _handle_tool_calls() | L1173 | **`reasoning_content` 属性访问无保护**：`current_message.reasoning_content` 若模型返回对象无此属性（非 DeepSeek 模型），将抛出 AttributeError。应改为 `getattr(current_message, 'reasoning_content', None)`。 |
| L4-12 | **P2** | 多处 | L566,1520,1525,1553,1572,1589,1657,2117 | **直接访问 `self._db._conn` 私有属性破坏封装**：8 处直接访问 `DatabaseManager` 的内部连接对象，若其内部连接管理方式变更，所有调用点都会失效。 |
| L4-13 | **P2** | _ensure_character_memories() | L1525-1589 | **绕过 DatabaseManager 直接执行 SQL**：直接在 `_db._conn` 上执行 `execute`/`commit`，绕过了 DatabaseManager 的事务管理和错误处理。 |
| L4-14 | **P2** | process() | L727-731 | **await emotion_task 时 CancelledError 未捕获**：Python 3.9+ 中 CancelledError 继承自 BaseException 而非 Exception，若任务被取消，CancelledError 会向上传播导致 process() 异常退出。 |
| L4-15 | **P2** | startup() | L306-308 | **跨对象修改私有属性**：`self.router._db = self._db` 直接修改 ModelRouter 的私有属性，违反封装且极度脆弱。 |
| L4-16 | **P2** | _build_messages() | L1043 | **跨对象设置私有属性**：`self.context._last_user_message = user_msg` 直接设置 AgentContext 的私有属性，且该属性未在 `__init__` 中初始化。 |
| L4-17 | **P2** | startup() | L276 | **跨对象注入私有引用**：`self.context._router = self.router` 向 AgentContext 注入私有属性，耦合度高且脆弱。 |
| L4-18 | **P2** | _resolve_image_url() | L1429 | **调用其他对象的私有方法**：`self._multimodal._resolve_image_url(url)` 调用 MultimodalProcessor 的私有方法，违反封装。 |
| L4-19 | **P2** | process() | L527-535 | **工具确认回路的上下文不完整**：确认执行后，用户消息和助手回复加入 history，但工具调用/结果消息未加入。后续轮次模型不知道工具已被调用，可能重复调用。 |

### 4.3 P3 轻微问题

| # | 严重度 | 方法 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L4-20 | **P3** | _handle_tool_calls() | L1091 | 冗余导入 `import json`，文件顶部已导入。 |
| L4-21 | **P3** | _get_sticker_catalog() | L1350 | 冗余导入 `import json`。 |
| L4-22 | **P3** | _should_auto_sticker() / _pick_sticker_by_emotion() | L1369, L1386 | 冗余导入 `import random`，应在文件顶部统一导入。 |
| L4-23 | **P3** | _enforce_speech_rule() | L1450 | 冗余导入 `import re`，文件顶部已导入。 |
| L4-24 | **P3** | _check_personality_drift() | L2054 | 冗余导入 `from loguru import logger`。 |
| L4-25 | **P3** | mark_interaction() | L2063 | 冗余导入 `import time as _time`。 |
| L4-26 | **P3** | _ensure_character_memories() | L1516-1517 | 冗余导入 `from pathlib import Path` 和 `import json`。 |
| L4-27 | **P3** | _ensure_character_memories() | L1564 | 冗余导入 `import json as _json`。 |
| L4-28 | **P3** | _ensure_character_memories() | L1578 | `__import__("time").time()` 代替 `time.time()`，不必要且降低可读性。 |
| L4-29 | **P3** | _ensure_character_memories() | L1583 | 访问 `self.router._embed_model` 私有属性，破坏封装。 |
| L4-30 | **P3** | _extract_markers() | L1306 | 每次调用新建 `MarkerParser()`，实例可复用。 |
| L4-31 | **P3** | process() | L508 | `self._user_sent_sticker` 设置后未被消费，属于死代码。 |
| L4-32 | **P3** | startup() | L422-432 | 清理循环任务未处理 CancelledError，功能正确但不够健壮。 |
| L4-33 | **P3** | _evaluate_last_response() | L1834 | 置信度边界 `0.15 <= improved <= 0.85` 丢弃了最有信息量的极端信号（非常有效/非常无效）。 |
| L4-34 | **P3** | _pick_sticker_by_emotion() | L1412 | 加权随机使用 `<=` 而非 `<`，浮点数边界极微小偏向。 |
| L4-35 | **P3** | startup() | L355 | 对话历史恢复 `limit=40` 硬编码，无法根据配置调整。 |

---

## 第5层：网关层

| # | 严重度 | 文件 | 行号/方法 | 问题描述 |
|---|--------|------|-----------|----------|
| L5-01 | **P0** | http_channel.py | /api/chat | **身份冒充漏洞**：`user_id` 从请求体获取，客户端可设 `user_id="hezi"` 绕过白名单校验冒充主人。所有端点无认证。 |
| L5-02 | **P0** | http_channel.py | /api/privacy/forget | **未授权数据删除**：被遗忘权端点仅需确认短语即可触发级联删除，无身份认证。 |
| L5-03 | **P0** | http_channel.py | /api/models/config PUT | **未授权写入 API Key**：模型配置更新端点将 API Key 写入 os.environ 和数据库，无认证。 |
| L5-04 | **P1** | console_channel.py | start() | **运行时类型错误**：handler 返回 AgentResponse 对象，但代码将整个对象传入 `send()`，显示 repr 而非回复文本。 |
| L5-05 | **P1** | base.py | EventHandler 类型定义 | **类型签名与实际不符**：声明返回 `str`，但实际返回 `AgentResponse`。 |
| L5-06 | **P1** | security.py | filter() | **原地变异事件对象**：直接修改传入的 InternalEvent 对象，若事件被共享引用会导致数据不一致。 |
| L5-07 | **P1** | http_channel.py | get_emotion() | **GET 请求有副作用**：`engine.state.decay()` 在 GET /api/emotion 中修改情感引擎状态，违反 HTTP 幂等性。每次轮询都触发衰减。 |
| L5-08 | **P1** | http_channel.py | update_model_config() | **并发写入 os.environ**：API Key 写入进程全局环境变量，并发请求可能互相覆盖。 |
| L5-09 | **P1** | gateway.py | stop() | **Task 取消后未 await**：`task.cancel()` 后未等待任务结束，可能导致资源未正确释放。 |
| L5-10 | **P1** | console_channel.py | __init__() | **双实例 SecurityFilter**：ConsoleChannel 自行创建 SecurityFilter，与 Gateway 持有的是不同对象，频率限制桶互相独立。 |
| L5-11 | **P2** | security.py | _buckets | **内存无限增长**：defaultdict 中的 Token Bucket 按用户 ID 无限累积，无过期淘汰机制。 |
| L5-12 | **P2** | security.py | filter() | **熔断关键词误判**：`kw in event.payload` 子串匹配，合法消息包含关键词也会被拦截。 |
| L5-13 | **P2** | http_channel.py | sse_generator() | **SSE 流未处理客户端断连**：客户端断开后生成器继续执行浪费资源。 |
| L5-14 | **P2** | http_channel.py | _write_config() | **配置文件无并发保护**：background_config.json 读写无文件锁。 |
| L5-15 | **P2** | http_channel.py | conversation_history() | **直接访问私有属性**：`self._agent._db` 访问 AgentCore 私有属性，多处存在。 |
| L5-16 | **P2** | http_channel.py | /api/session/reset | **未授权会话重置**：无认证即可重置会话。 |
| L5-17 | **P2** | http_channel.py | /api/models/validate | **API Key 验证可被滥用**：无认证端点发起真实 API 请求，可做代理攻击。 |
| L5-18 | **P2** | console_channel.py | _read_line() | **阻塞线程无法取消**：`run_in_executor(None, input)` 无法取消。 |
| L5-19 | **P2** | gateway.py | start() | **重复调用覆盖任务**：多次调用 start() 会覆盖 self._tasks，旧任务成为孤儿。 |
| L5-20 | **P3** | http_channel.py | 多处 | **重复 import 遮蔽**：函数体内 import 遮蔽模块级同名导入。 |
| L5-21 | **P3** | http_channel.py | generate_autobiography() | **冗余 import**：函数内 `from loguru import logger`，模块顶部已导入。 |
| L5-22 | **P3** | console_channel.py | _read_line | **已弃用 API**：`asyncio.get_event_loop()` 在 Python 3.10+ 已弃用。 |
| L5-23 | **P3** | http_channel.py | 路径安全检查 | **错误返回格式不一致**：返回 JSON dict 而非 HTTP 错误状态码。 |
| L5-24 | **P3** | mcp/adapter.py | 全文件 | **纯桩代码**：所有方法均 raise NotImplementedError。 |

---

## 第6层：启动入口（main.py）

### 6.1 P0 致命问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L6-01 | **P0** | main.py | L23 | **`sys._MEIPASS` 无保护访问**：当 `sys.frozen=True` 但无 `_MEIPASS` 属性时（如 Nuitka 打包），直接访问将抛出 AttributeError 导致程序无法启动。应使用 `getattr(sys, '_MEIPASS', None)`。 |
| L6-02 | **P0** | main.py | L89-98 | **引导模式重启进程后旧进程可能未完全退出**：`time.sleep(0.5)` 硬编码等待不足以保证新进程绑定端口；`os._exit(0)` 跳过所有 Python 清理，可能导致数据库文件锁未释放、临时文件残留。 |
| L6-03 | **P0** | main.py | L538-583 | **`/api/config/save` 端点无任何认证**：任何人可写入 `.env` 文件并注入任意环境变量，更危险的是攻击者可通过此端点将 API 请求重定向到恶意服务器，窃取所有对话内容。 |

### 6.2 P1 严重问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L6-04 | **P1** | main.py | L503-520 | **`shutdown_all()` 与 `finally` 块双重关闭**：两者可能并发执行，导致 `scheduler.shutdown()` 和 `agent.shutdown()` 被重复调用；且后台 asyncio.Task 未被取消，在 DB 关闭后继续运行产生异常。 |
| L6-05 | **P1** | main.py | L107等10处 | **直接访问 `agent._db` 私有属性**：至少 10 处直接访问，耦合脆弱且初始化时序依赖隐式约定，若 `startup()` 初始化顺序变化将触发 AttributeError。 |
| L6-06 | **P1** | main.py | L139-154 | **`_cron_loop` 与 APScheduler 重复调度**：两套调度机制并存，加上 `_catch_up_cron()` 第三套补执行机制，三套之间无互斥锁，可能导致同一任务在同一天被执行多次。 |
| L6-07 | **P1** | main.py | L117-122 | **BackupManager 使用相对路径**：`db_path="data/xilian.db"` 和 `backup_root="backups"` 都是相对路径，CWD 变化时备份失败或备份到错误位置。 |
| L6-08 | **P1** | main.py | L480-484 | **托盘退出回调中 `asyncio.get_event_loop()` 已弃用**：在 Python 3.10+ 中若当前无运行循环会发出 DeprecationWarning；若事件循环已关闭，`call_soon_threadsafe` 将抛出 RuntimeError。 |
| L6-09 | **P1** | main.py | L464-466 | **`on_open()` 在 `NO_HTTP` 模式下变量未定义**：当 `NO_HTTP=1` 时，`bind_host` 和 `http_port` 变量未被赋值，托盘图标 `on_open` 闭包引用将触发 NameError。 |
| L6-10 | **P1** | main.py | L599-610 | **`/api/config/debug` 端点泄露系统路径**：无认证，返回 `sys.executable`、`.env` 文件路径、CWD 路径等敏感信息。 |

### 6.3 P2 中等问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L6-11 | **P2** | main.py | L74 | 版本号硬编码不一致：注释写 V3.3，日志输出 V3.2。 |
| L6-12 | **P2** | main.py | L36-42 | 第三方库导入与项目内部导入混合排列，若未来将内部包导入移到 `sys.path.insert` 之前将导致 ModuleNotFoundError。 |
| L6-13 | **P2** | main.py | L57-62 | `.env` 加载逻辑只加载第一个找到的，不合并；`load_dotenv` 默认 `override=False`，行为可能不符合预期。 |
| L6-14 | **P2** | main.py | L143-144 | `_cron_loop` 使用本地时间无时区，DST 切换时可能跳过或重复执行。 |
| L6-15 | **P2** | main.py | L308-327 | `_cron_monthly_loop` 跨月计算在月末日期不存在时可能崩溃。 |
| L6-16 | **P2** | main.py | L333-374 | `_catch_up_cron()` 补执行可能执行耗时任务（如 daily_autobiography），阻塞启动。 |
| L6-17 | **P2** | main.py | L377-383 | AttentionScheduler 通过直接赋值私有属性注入依赖，违反封装。 |
| L6-18 | **P2** | main.py | L387 | `SecurityFilter(owner_id="hezi")` 硬编码 owner_id，无法通过配置修改。 |
| L6-19 | **P2** | main.py | L427-436 | 局域网 IP 检测使用 UDP 连接 8.8.8.8，socket 未在 finally 中关闭。 |
| L6-20 | **P2** | main.py | L556 | `env_var_map` 中 `provider` 值未做大小写归一化，用户传入 `"DeepSeek"` 将回退到 `DEEPSEEK_API_KEY`。 |

### 6.4 P3 轻微问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L6-21 | **P3** | main.py | L14 | `import subprocess` 仅在引导模式重启时使用，可延迟导入。 |
| L6-22 | **P3** | main.py | L16 | `import time` 与 `asyncio` 的时间功能重叠，`time.sleep(0.5)` 在异步上下文中阻塞事件循环。 |
| L6-23 | **P3** | main.py | L141,169,276,311 | `import datetime` 在循环体内重复导入。 |
| L6-24 | **P3** | main.py | L409-412 | `StaticFiles` 在 `if` 块内重复导入。 |
| L6-25 | **P3** | main.py | L656 | `asyncio.run(main())` 无信号处理配置，Windows 上 Ctrl+C 可能不触发 finally 清理。 |
| L6-26 | **P3** | http_channel.py | L577 | 闭包变量命名 `nudge` 与外部 NudgeEngine 实例同名，容易混淆。 |
| L6-27 | **P3** | main.py | L67 | `has_key` 变量名暗示布尔值但实际为 `bool(os.getenv(...))`，语义不清晰。 |

---

## 第7层：前端

### 7.1 P1 严重问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L7-01 | **P1** | useChat.ts | L67-78 | **问候消息在 StrictMode 下重复注入**：`fetchGreeting` 的 `useEffect` 依赖数组为空且无清理函数，React 18 StrictMode 下执行两次，问候消息被 addMessage 两次。 |
| L7-02 | **P1** | useChat.ts | L97-102,109-114,168-173 | **流式更新直接覆盖 messages 数组**：`onToken` 和 `onSticker` 回调绕过 `addMessage` action 直接 setState，若期间有其他 addMessage 调度，该消息会被覆盖丢失。 |
| L7-03 | **P1** | MainLayout.tsx | L65 | **greeting.id 为空时发送空字符串 ack**：当 `PendingGreeting.id` 为 null 时，向后端发送空字符串，导致 ack 失败且 pending 问候永远无法清除。 |
| L7-04 | **P1** | SettingsPanel.tsx + modelStore.ts | L226-249, L97-130 | **API Key 双重验证**：SettingsPanel 先调用 `validateApiKey`，然后 `addProviderKey` 内部又调用一次，同一 Key 被验证两次，浪费请求且若结果不一致行为不可预测。 |
| L7-05 | **P1** | OnboardingPage.tsx | L50-66 | **轮询 interval 未在组件卸载时清理**：`setDone(true)` 后启动的 `setInterval` 没有在组件卸载时清理，可能在已卸载组件上调用 `window.location.reload()`。 |
| L7-06 | **P1** | api.ts | L44-66 | **SSE 多行 data 字段未按规范拼接**：SSE 规范要求同一事件内多个 `data:` 行以换行符拼接，当前每遇到一个 `data:` 行就立即调用 `onToken`，多行数据被错误拆分为多个 token。 |

### 7.2 P2 中等问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L7-07 | **P2** | api.ts | 多处 | 大量 API 函数未检查 `res.ok`，服务器返回非 200 时 `res.json()` 可能解析失败。 |
| L7-08 | **P2** | api.ts | L7, L28 | `user_id` 硬编码为 'hezi'，多用户场景下所有请求使用同一身份。 |
| L7-09 | **P2** | affectionStore.ts | L15, L24-31 | `loading` 状态为死代码，从未被设为 true。 |
| L7-10 | **P2** | autonomyStore.ts | L16, L29 | `loading` 状态为死代码，同 L7-09。 |
| L7-11 | **P2** | useEmotionData.ts | L20 | PAD 维度映射丢失语义信息："兴奋"和"快乐"都映射为"喜悦"，雷达图信息丢失。 |
| L7-12 | **P2** | useEmotionData.ts | L52 | `possible_cause` 被错误赋值为 `primary_emotion`，导致 EmotionPanel 显示"主要情绪：快乐 · 快乐"。 |
| L7-13 | **P2** | ChatView.tsx | L197-219 | 流式更新时频繁触发 `scrollIntoView`，平滑滚动动画被反复中断重启，造成视觉抖动。 |
| L7-14 | **P2** | ChatView.tsx | L207-212 | 历史消息前置后滚动位置恢复不可靠，rAF 不保证 DOM 布局已完成。 |
| L7-15 | **P2** | modelStore.ts | L104-109 | 新供应商默认模型 fallback 不正确：未列出供应商错误地使用 deepseek 的模型名。 |
| L7-16 | **P2** | BackgroundLayer.tsx | L47 | CSS URL 注入风险：`backgroundImage: url(${current})` 未做转义。 |
| L7-17 | **P2** | MainLayout.tsx | L68-70 | 问候去重仅检查最后一条消息，相同问候在更早位置仍会重复注入。 |
| L7-18 | **P2** | SettingsPanel.tsx | L535-536 | range 滑块 onMouseUp/onTouchEnd 重复保存，用户一次操作可能触发多次保存请求。 |
| L7-19 | **P2** | AutobiographyPanel.tsx | L61 | 绕过 api.ts 服务层直接调用 fetch，缺少错误处理和统一 BASE 路径。 |
| L7-20 | **P2** | NotebookPanel.tsx | L49-57 | 轮询 interval 内的 fetch 函数闭包可能过期。 |
| L7-21 | **P2** | StickerPanel.tsx | L113 | 表情包文件路径未做安全校验，若后端未严格校验可构造路径遍历。 |
| L7-22 | **P2** | AuditPanel.tsx | L18-19 | filter 值直接拼入 URL 未编码。 |
| L7-23 | **P2** | PADTrajectory.tsx | L38-53 | canvas 实际高度与 props height 不一致，渲染尺寸与 CSS 尺寸不匹配。 |
| L7-24 | **P2** | PortraitPanel.tsx | L33 | `stable_traits` 分隔符硬编码为中文分号，后端改用其他分隔符时前端解析失败。 |
| L7-25 | **P2** | SlidePanel.tsx | L61-71 | 快速切换面板时动画状态不一致，缺少退出动画。 |
| L7-26 | **P2** | useChat.ts | L18-56 | `loadHistory` 回调依赖 `loadedRounds` 导致不必要的重建。 |
| L7-27 | **P2** | App.tsx | L40-46 | `config/check` 响应非 JSON 时未处理，错误信息被吞没。 |

### 7.3 P3 轻微问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L7-28 | **P3** | ChatInput.tsx / MessageBubble.tsx / MessageList.tsx | 全文 | 死代码文件，已被 ChatView.tsx 中的内联组件替代。 |
| L7-29 | **P3** | MessageBubble.tsx vs ChatView.tsx | L47 / L93 | 表情包 URL 逻辑不一致：旧版有 fallback，新版 sticker.file 为空时请求无效 URL。 |
| L7-30 | **P3** | EmotionGauge.tsx | L99 | useEffect 依赖冗余，centerX/centerY/radius 已由 width/height 派生。 |
| L7-31 | **P3** | StickerPanel.tsx | L27 | 加载失败时显示误导性空状态"暂时还没有表情包呢"，用户无法区分"真的没有"和"加载失败"。 |
| L7-32 | **P3** | ChatView.tsx | L108 | 助手消息内容直接渲染为文本节点，扩展性差。 |
| L7-33 | **P3** | useChat.ts | L6 | 模块级 msgId 计数器，所有 hook 实例共享，HMR 热更新时计数器不重置。 |
| L7-34 | **P3** | MobileBottomNav.tsx | L97 | key 使用 label 而非 key，多语言化时 label 可能重复。 |
| L7-35 | **P3** | Sidebar.tsx | L170 | key 使用 label 而非 key，同 L7-34。 |
| L7-36 | **P3** | MemoryPanel.tsx | 全文 | 整个组件为占位符，SlidePanel 中已映射到 MemoryTimeline，此文件为死代码。 |

---

## 第8层：数据库迁移和测试

### 8.1 迁移层 — P0 致命问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L8-01 | **P0** | 001_initial.py | L167-168 | **PostgreSQL 专用索引在 SQLite 上无效**：`postgresql_where=sa.text("status='pending'")` 是 PostgreSQL 语法，SQLite 上被静默忽略，条件过滤索引实际不存在。 |
| L8-02 | **P0** | 005_notebook_due_date.py | L22-24 | **downgrade 为空操作，迁移不可回滚**：一旦执行升级，数据库永久包含 `due_date` 列，无法回退。 |
| L8-03 | **P0** | 004_model_config.py | L62-100 | **迁移中将 API Key 明文写入数据库**：从环境变量读取 API Key 并明文写入 `model_configs.api_key`，无任何加密保护。 |
| L8-04 | **P0** | 迁移脚本 vs _manager.py | 全文 | **迁移脚本与手动建表 schema 严重不一致**：`_manager.py` 包含 `trigger_memory_id`、`images` 等列但迁移脚本不包含；手动建表包含 18+ 张表但 Alembic 仅覆盖 9 张。通过 Alembic 全新初始化将缺少列导致运行时错误。 |

### 8.2 迁移层 — P1 严重问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L8-05 | **P1** | _manager.py | L394-415 | **Alembic 迁移成功后仍手动建表**：双重路径导致 schema 不一致，Alembic 迁移路径和手动建表路径产生两套并行的 schema 管理逻辑。 |
| L8-06 | **P1** | _manager.py | L395-397 | **Alembic 迁移仅对默认路径生效**：使用 `:memory:` 或自定义路径的数据库（包括测试）跳过 Alembic，迁移路径从未被测试覆盖。 |
| L8-07 | **P1** | 001_initial.py | L171-180 | **初始迁移 downgrade 直接删除全部 9 张表**：无任何数据备份或确认机制，误执行将导致不可逆数据丢失。 |
| L8-08 | **P1** | _manager.py | L524-527 | **`conversation_logs` 表缺少 `images` 列**：`insert_log()` 插入 images 字段但建表 SQL 和迁移脚本均未定义此列，运行时 INSERT 失败。 |
| L8-09 | **P1** | alembic/env.py | L28 | **`target_metadata = None` 导致 autogenerate 不可用**：所有迁移必须手写，无法自动检测 schema 漂移，增加遗漏风险。 |

### 8.3 迁移层 — P2/P3 问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L8-10 | **P2** | 005_notebook_due_date.py | L17-19 | 使用原始 SQL 而非 Alembic API 的 `op.add_column()`。 |
| L8-11 | **P2** | 004_model_config.py | L72-74 | 迁移中硬编码特定供应商模型名称，会随供应商 API 更新而过时。 |
| L8-12 | **P2** | 001_initial.py vs _manager.py | 全文 | 迁移脚本与手动建表 SQL 存在细微差异（due_date、trigger_memory_id 等）。 |
| L8-13 | **P2** | alembic.ini | L89 | 数据库路径使用相对路径，CWD 变化时连接错误数据库。 |
| L8-14 | **P3** | alembic/versions/ | — | 缺少多个表的迁移脚本（user_portrait、micro_events、session_summaries 等 7 张表）。 |

### 8.4 测试层 — P1 严重问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L8-15 | **P1** | tests/ | — | **无 `conftest.py` 共享 fixture**：33 个测试文件各自独立定义 fixture，大量重复代码且行为不一致。 |
| L8-16 | **P1** | test_stage78_db.py | L21-26 | 使用文件系统数据库而非内存数据库，清理失败时残留文件影响后续测试。 |
| L8-17 | **P1** | test_stage78_db.py | L13-16 | 使用同步包装器调用异步函数，与 pytest-asyncio 冲突。 |
| L8-18 | **P1** | 多个测试文件 | — | 使用已弃用的 `asyncio.get_event_loop()`（8 个文件）。 |
| L8-19 | **P1** | test_heartbeat.py | L20-96 | 单元测试文件中包含真实 API 调用，CI 不稳定。 |
| L8-20 | **P1** | test_emotion_analyzer.py | L145-203 | **Mock 返回值类型与真实接口不匹配**：mock 返回字符串但真实接口返回 ProviderResponse 对象，测试验证的路径与生产代码不同。 |
| L8-21 | **P1** | test_skills_coding.py | L81-84 | 测试依赖本地环境安装状态（假设 Claude Code 已安装）。 |
| L8-22 | **P1** | tests/ | — | **无迁移相关测试**：无任何测试验证 Alembic 迁移升级/降级/schema 一致性。 |
| L8-23 | **P1** | test_database_expansion.py | L130,140,152 | 测试直接访问私有属性 `_conn`，测试实现细节而非公共接口。 |
| L8-24 | **P1** | test_forgetting.py | L143-151 | 测试直接操作私有属性修改数据库状态，绕过公共 API。 |

### 8.5 测试层 — P2/P3 问题

| # | 严重度 | 文件 | 行号 | 问题描述 |
|---|--------|------|------|----------|
| L8-25 | **P2** | test_backup.py | — | 未测试非 dry-run 的 restore 路径。 |
| L8-26 | **P2** | test_http_channel.py | L88-114 | 测试中存在冗余代码（创建了未使用的假 Event 对象）。 |
| L8-27 | **P2** | test_model_router.py | — | 缺少关键错误路径测试（所有 provider 不可用、路由超时等）。 |
| L8-28 | **P2** | test_tool_executor.py | L68-74 | 频率限制测试依赖隐式默认值。 |
| L8-29 | **P2** | test_providers.py | — | 仅验证结构，未验证行为。 |
| L8-30 | **P2** | test_personality_regression.py | L56-77 | 每个参数化用例都创建新 AgentCore 实例，效率极低。 |
| L8-31 | **P2** | 多个测试文件 | — | 所有测试文件均使用 `sys.path.insert(0, ".")` 手动修改路径。 |
| L8-32 | **P2** | test_database_expansion.py | L14-19 | fixture 事件循环管理不当，未在 teardown 中关闭循环。 |
| L8-33 | **P2** | test_coarse_grain_engine.py | L44-49 | fixture 创建事件循环但未关闭，可能导致资源泄漏。 |
| L8-34 | **P3** | test_personality.py | L28 | 跳过条件检查 `DASHSCOPE_API_KEY` 而非 `DEEPSEEK_API_KEY`，可能导致测试被错误跳过。 |
| L8-35 | **P3** | test_emotion_appraisal.py | L212 | 测试专用常量定义在模块底部，降低可读性。 |
| L8-36 | **P3** | test_memory_manager.py | L177-178 | 在异步测试中混用同步事件循环，风格不一致。 |
| L8-37 | **P1** | _manager.py | L453-459 | 手动建表路径用 `try: ALTER TABLE ... ADD COLUMN ... except: pass` 模拟迁移，静默吞异常使真正错误无法被发现。 |

---

## 全项目问题总表

### 按严重度统计

| 层级 | P0 致命 | P1 严重 | P2 中等 | P3 轻微 | 合计 |
|------|---------|---------|---------|---------|------|
| 第1层：共享基础设施 | 0 | 5 | 33 | 5 | 43* |
| 第2层：Agent核心引擎 | 1 | 9 | 14 | 7 | 31 |
| 第3层：工具系统 | 3 | 5 | 12 | 3 | 23 |
| 第4层：Agent大脑 | 0 | 6 | 13 | 16 | 35 |
| 第5层：网关层 | 3 | 7 | 8 | 6 | 24 |
| 第6层：启动入口 | 3 | 7 | 10 | 7 | 27 |
| 第7层：前端 | 0 | 6 | 21 | 9 | 36 |
| 第8层：迁移和测试 | 4 | 15 | 11 | 3 | 33* |
| **合计** | **14** | **60** | **122** | **56** | **252** |

*注：第1层原始统计48个问题，合并重复项后为43个；第8层含跨层一致性问题。

### P0 致命问题清单（14个，必须立即修复）

| # | 层级 | 问题摘要 |
|---|------|----------|
| L2-01 | 第2层 | pipeline/multimodal.py 路径遍历漏洞 |
| L3-01 | 第3层 | coding_delegate bypassPermissions 命令注入 |
| L3-02 | 第3层 | coding_delegate 路径穿越 |
| L3-03 | 第3层 | coding_delegate Prompt 注入 |
| L5-01 | 第5层 | http_channel 身份冒充漏洞 |
| L5-02 | 第5层 | http_channel 未授权数据删除 |
| L5-03 | 第5层 | http_channel 未授权 API Key 写入 |
| L6-01 | 第6层 | main.py sys._MEIPASS 无保护访问 |
| L6-02 | 第6层 | main.py 引导模式重启进程竞争 |
| L6-03 | 第6层 | main.py /api/config/save 无认证 |
| L8-01 | 第8层 | PostgreSQL 索引在 SQLite 上无效 |
| L8-02 | 第8层 | 迁移 downgrade 不可回滚 |
| L8-03 | 第8层 | 迁移中 API Key 明文写入数据库 |
| L8-04 | 第8层 | 迁移脚本与手动建表 schema 严重不一致 |

### 跨层共性问题模式

1. **私有属性直接访问**（第1/2/4/6层）：`_db._conn`、`_router._embed_model`、`context._router` 等，至少 20+ 处跨对象访问私有属性，重构风险极高。

2. **同步阻塞 async 事件循环**（第1/4/6层）：`subprocess.run()`、`open()`+`json.load()`、`shutil.copy2()`、`time.sleep()` 等同步调用在 async 函数中使用。

3. **认证缺失**（第5/6层）：所有 HTTP 端点无认证，局域网部署时任何人可执行任意操作。

4. **fire-and-forget 任务泄漏**（第2/4层）：大量 `asyncio.create_task()` 不存储引用，shutdown 时无法取消。

5. **双路径 schema 管理**（第1/8层）：Alembic 迁移与手动建表并存，列定义不一致导致运行时错误。

6. **状态字符串不一致**（第1层）：Repository 与 DatabaseManager 使用不同的状态值（'completed' vs 'done'）。

7. **冗余导入**（第4/6层）：agent_core.py 有 8 处冗余导入，main.py 有 4 处。

8. **测试与生产代码路径不一致**（第8层）：Mock 返回类型与真实接口不匹配，测试通过但生产代码可能失败。
