"""
search_memory — 记忆检索工具

让昔涟可以主动检索关于伙伴的历史记忆。
当伙伴提到过去的事情、问"你还记得吗"、或需要回忆上下文时，
LLM 可自主选择调用此工具。
"""
from ..tool_registry import register_tool, ToolPermission
from ..tool_result import ToolResult, ToolContext


@register_tool(
    name="search_memory",
    description="检索昔涟关于伙伴的历史记忆。当伙伴提到过去的事情、问'你还记得吗'、暗示想聊之前的话题时使用。",
    schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或自然语言描述，用中文",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数上限，默认 3",
            },
        },
        "required": ["query"],
    },
    permission=ToolPermission.READ_ONLY,
    category="memory",
    max_frequency=10,
)
async def search_memory(query: str, limit: int = 3, ctx: ToolContext = None) -> ToolResult:
    """
    检索昔涟关于伙伴的历史记忆。

    Args:
        query: 搜索关键词或自然语言描述
        limit: 返回条数上限，默认 3
        ctx: 执行上下文（由 ToolExecutor 自动注入）
    """
    if not ctx or not ctx.memory_manager:
        return ToolResult(
            success=False,
            error="人家的记忆模块还没准备好呢……等一会儿再问好不好？",
        )

    try:
        results = await ctx.memory_manager.retrieve_memories(
            user_message=query,
            k=limit,
        )

        if not results:
            return ToolResult.ok(
                {"found": False, "memories": [], "query": query},
                trigger_memory=False,
            )

        # 格式化为可读结构
        memories = []
        for r in results:
            memories.append({
                "summary": r.get("summary", ""),
                "relevance": round(1.0 - min(r.get("distance", 0), 1.0), 2),
                "importance": r.get("importance", 0.5),
            })

        return ToolResult.ok(
            {
                "found": True,
                "memories": memories,
                "query": query,
                "count": len(memories),
            },
            trigger_memory=False,  # 检索不是新记忆
            trigger_portrait_update=False,
        )

    except Exception as e:
        return ToolResult.fail(f"记忆检索出了一点小问题……{str(e)[:100]}")


# ── 注册为简单结果模板（不需要 LLM 二次包装）──
# 模板在 ResultWrapper 初始化时注册
def _register_template():
    from ..result_wrapper import register_template

    @register_template("search_memory")
    def wrap_search_memory(data):
        if not data.get("found") or not data.get("memories"):
            return f"唔……人家回想了一下，关于「{data.get('query', '这个')}」好像没什么印象呢 (´•ω•̥`)"

        memories = data["memories"]
        lines = [f"人家想起来了～关于「{data.get('query', '这个')}」……"]
        for i, m in enumerate(memories, 1):
            relevance_hint = ""
            if m["relevance"] >= 0.8:
                relevance_hint = "（这个记得比较清楚）"
            lines.append(f"{i}. {m['summary']} {relevance_hint}")
        lines.append("——嗯，大概就是这些了 ~♪")
        return "\n".join(lines)
