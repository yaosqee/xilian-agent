"""
search_web — 网络搜索工具

使用智谱 Web Search API，支持意图识别、多搜索引擎、时间过滤。
当伙伴想了解实时信息、新闻、百科知识时使用。
"""
import os
import httpx
from loguru import logger

from ..tool_registry import register_tool, ToolPermission
from ..tool_result import ToolResult

ZHIPU_KEY = os.getenv("ZHIPU_SEARCH_API_KEY", "")
SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"


@register_tool(
    name="search_web",
    description="搜索互联网获取实时信息。当伙伴问新闻、百科、实时事件、或'帮我查一下'某件事时使用。",
    schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词，不超过70字符",
            },
            "recency": {
                "type": "string",
                "description": "时间范围: 'noLimit'(不限), 'oneDay'(一天), 'oneWeek'(一周), 'oneMonth'(一月), 默认'noLimit'",
            },
            "count": {
                "type": "integer",
                "description": "返回条数，默认 5，最大 10",
            },
        },
        "required": ["query"],
    },
    permission=ToolPermission.READ_ONLY,
    category="external",
    max_frequency=8,
)
async def search_web(query: str, recency: str = "noLimit",
                     count: int = 5, ctx=None) -> ToolResult:
    """
    使用智谱 Web Search API 搜索网络。
    """
    if not ZHIPU_KEY:
        return ToolResult.fail("搜索服务还没准备好呢……等会儿再试试好不好？")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {ZHIPU_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "search_query": query[:70],
                    "search_engine": "search_std",
                    "search_intent": True,
                    "count": min(count, 10),
                    "search_recency_filter": recency,
                },
            )

            if resp.status_code != 200:
                logger.warning("search_web.http_error",
                             status=resp.status_code, body=resp.text[:200])
                return ToolResult.fail(
                    f"搜索服务好像有点忙……状态码{resp.status_code}，等会儿再试试？"
                )

            data = resp.json()

            # 提取搜索结果
            results = []
            for item in data.get("search_result", [])[:count]:
                results.append({
                    "title": item.get("title", ""),
                    "content": item.get("content", "")[:300],  # 摘要截断
                    "link": item.get("link", ""),
                    "media": item.get("media", ""),
                    "publish_date": item.get("publish_date", ""),
                })

            # 提取搜索意图
            intent_info = {}
            for intent in data.get("search_intent", []):
                intent_info["intent"] = intent.get("intent", "")
                intent_info["keywords"] = intent.get("keywords", "")

            logger.info("search_web.done", query=query[:50],
                       results_count=len(results))

            return ToolResult.ok(
                {
                    "query": query,
                    "results": results,
                    "count": len(results),
                    "intent": intent_info,
                },
                trigger_memory=True,       # 打磨期 P1：验证工具→记忆编码路径
                trigger_portrait_update=True,
            )

    except httpx.TimeoutException:
        logger.warning("search_web.timeout", query=query[:50])
        return ToolResult.fail("搜索花了比较久还没回来……等会儿再试试好不好？")
    except Exception as e:
        logger.error("search_web.error", error=str(e))
        return ToolResult.fail("搜索出了一点小问题……等会儿再试试好不好？")


# ── 结果模板 ──

def _register_template():
    from ..result_wrapper import register_template

    @register_template("search_web")
    def wrap_search(data):
        results = data.get("results", [])
        query = data.get("query", "这个问题")

        if not results:
            return f"唔……人家搜了一下「{query}」，好像没有找到相关内容呢 (´•ω•̥`) 换个关键词试试？"

        lines = [f"人家帮你搜了一下「{query}」～找到这些："]
        for i, r in enumerate(results[:5], 1):
            title = r.get("title", "无标题")
            content = r.get("content", "")[:200]
            date = r.get("publish_date", "")
            date_str = f"（{date}）" if date else ""
            lines.append(f"{i}. {title}{date_str}")
            if content:
                lines.append(f"   {content}")
        lines.append("——喏，大概就是这些了 ~♪")
        return "\n".join(lines)
