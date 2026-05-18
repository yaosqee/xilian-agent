"""
search_memory — 记忆检索工具

让昔涟可以主动检索关于伙伴的历史记忆和笔记本条目。
当伙伴提到过去的事情、问"你还记得吗"、或需要回忆上下文时，
LLM 可自主选择调用此工具。

打磨期扩展：+source 参数支持检索 notebook_entries。
"""
from ..tool_registry import register_tool, ToolPermission
from ..tool_result import ToolResult, ToolContext


@register_tool(
    name="search_memory",
    description="检索昔涟关于伙伴的历史记忆和笔记。当伙伴提到过去的事情、问'你还记得吗'、'帮我找之前的笔记'时使用。",
    schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或自然语言描述，用中文",
            },
            "limit": {
                "type": "integer",
                "description": "每种来源返回条数上限，默认 3",
            },
            "source": {
                "type": "string",
                "description": "检索来源: 'memory'(情景记忆), 'notebook'(笔记本), 'all'(全部)。默认 'all'",
            },
        },
        "required": ["query"],
    },
    permission=ToolPermission.READ_ONLY,
    category="memory",
    max_frequency=10,
)
async def search_memory(query: str, limit: int = 3,
                        source: str = "all", ctx: ToolContext = None) -> ToolResult:
    """
    检索昔涟关于伙伴的历史记忆和笔记本条目。

    Args:
        query: 搜索关键词或自然语言描述
        limit: 每种来源返回条数上限
        source: "memory" / "notebook" / "all"
        ctx: 执行上下文（由 ToolExecutor 自动注入）
    """
    if not ctx or not ctx.memory_manager:
        return ToolResult(
            success=False,
            error="人家的记忆模块还没准备好呢……等一会儿再问好不好？",
        )

    try:
        memories = []
        notes = []

        # ── 情景记忆检索 ──
        if source in ("memory", "all"):
            try:
                results = await ctx.memory_manager.retrieve_memories(
                    user_message=query,
                    k=limit,
                )
                for r in (results or []):
                    memories.append({
                        "summary": r.get("summary", ""),
                        "relevance": round(1.0 - min(r.get("distance", 0), 1.0), 2),
                        "importance": r.get("importance", 0.5),
                    })
            except Exception as e:
                from loguru import logger
                logger.warning("search_memory.memory_failed", error=str(e))

        # ── 笔记本检索（关键词匹配，无向量索引）──
        if source in ("notebook", "all") and ctx.db:
            try:
                all_notes = await ctx.db.get_notebook_notes(limit=50)
                keywords = query.lower().split()
                for n in all_notes:
                    content = n.get("content", "")
                    title = n.get("title", "") or ""
                    search_text = f"{title} {content}".lower()
                    # 任一关键词匹配即命中
                    if any(kw in search_text for kw in keywords):
                        notes.append({
                            "kind": n.get("kind", "note"),
                            "title": title[:100],
                            "content": content[:300],
                            "created_at": n.get("created_at", ""),
                        })
                        if len(notes) >= limit:
                            break
            except Exception as e:
                from loguru import logger
                logger.warning("search_memory.notebook_failed", error=str(e))

        # ── 结果汇总 ──
        found = bool(memories or notes)
        if not found:
            return ToolResult.ok(
                {"found": False, "memories": [], "notes": [], "query": query, "source": source},
                trigger_memory=False,
            )

        return ToolResult.ok(
            {
                "found": True,
                "query": query,
                "source": source,
                "memories": memories,
                "notes": notes,
                "memory_count": len(memories),
                "note_count": len(notes),
            },
            trigger_memory=False,
            trigger_portrait_update=False,
        )

    except Exception as e:
        return ToolResult.fail(f"记忆检索出了一点小问题……{str(e)[:100]}")


# ── 结果模板 ──

def _register_template():
    from ..result_wrapper import register_template

    @register_template("search_memory")
    def wrap_search_memory(data):
        query = data.get("query", "这个")
        memories = data.get("memories", [])
        notes = data.get("notes", [])
        source = data.get("source", "all")

        if not data.get("found"):
            source_hint = ""
            if source == "notebook":
                source_hint = "笔记里"
            elif source == "memory":
                source_hint = "回忆里"
            if source_hint:
                return f"唔……人家翻了翻{source_hint}，关于「{query}」好像没有什么记录呢 (´•ω•̥`)"
            return f"唔……人家回想了一下，关于「{query}」好像没什么印象呢 (´•ω•̥`)"

        lines = [f"人家找到了～关于「{query}」……"]

        if memories:
            lines.append("【回忆里的片段】")
            for i, m in enumerate(memories, 1):
                hint = "（比较清楚）" if m["relevance"] >= 0.8 else ""
                lines.append(f"{i}. {m['summary']} {hint}")

        if notes:
            lines.append("【笔记本里的记录】")
            for i, n in enumerate(notes, 1):
                kind_icon = {"note": "📝", "task": "📋", "focus": "👀", "diary": "📖"}.get(n["kind"], "·")
                title_str = f" — {n['title']}" if n.get("title") else ""
                lines.append(f"{i}. {kind_icon}{title_str}")
                if n.get("content"):
                    lines.append(f"   {n['content'][:200]}")

        lines.append("——嗯，大概就是这些了 ~♪")
        return "\n".join(lines)
