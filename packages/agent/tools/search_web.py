"""
search_web — 网络搜索工具

供应商可切换（`.env` → `SEARCH_PROVIDER=deepseek|zhipu`）：
- deepseek：`POST https://api.deepseek.com/v1/tools/search`，用现有 DeepSeek Key，
  5 元/1000 次成功请求，官方文档 https://api-docs.deepseek.com/zh-cn/guides/search/
- zhipu：智谱 Web Search（历史实现，保留作 fallback）

未显式配置时：有 DeepSeek Key 走 DeepSeek，否则退回智谱。
"""
import os
from datetime import datetime, timedelta

import httpx
from loguru import logger

from ..tool_registry import register_tool, ToolPermission
from ..tool_result import ToolResult

DEEPSEEK_SEARCH_URL = "https://api.deepseek.com/v1/tools/search"
ZHIPU_SEARCH_URL = "https://open.bigmodel.cn/api/paas/v4/web_search"

# 额度/鉴权类错误：重试没有意义
_PERMANENT_STATUS = {401, 402, 403}
# 瞬时错误：可以稍后再试，但不要在同一轮里连续重试
_TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}


def _deepseek_key() -> str:
    return (
        os.getenv("DEEPSEEK_API_KEY_2")
        or os.getenv("DEEPSEEK_API_KEY")
        or ""
    )


def _zhipu_key() -> str:
    return os.getenv("ZHIPU_SEARCH_API_KEY", "")


def _provider() -> str:
    explicit = (os.getenv("SEARCH_PROVIDER") or "").strip().lower()
    if explicit in ("deepseek", "zhipu"):
        return explicit
    return "deepseek" if _deepseek_key() else "zhipu"


def _available() -> bool:
    return bool(_deepseek_key() or _zhipu_key())


# ── DeepSeek Search 纯函数（便于单测）───────────────────────


def build_deepseek_query(query: str, recency: str, now: datetime | None = None) -> str:
    """把 recency 口语枚举翻成 DeepSeek 的 after: 语法。"""
    moment = now or datetime.now()
    offsets = {"oneDay": 0, "oneWeek": 6, "oneMonth": 29}
    days = offsets.get(recency)
    if days is None:
        return query
    since = (moment - timedelta(days=days)).strftime("%Y-%m-%d")
    return f"{query} after:{since}"


def map_deepseek_results(payload: dict, count: int) -> list[dict]:
    """把 DeepSeek 返回的 results 映射成工具内部统一结构。"""
    mapped = []
    for item in (payload.get("results") or [])[: max(1, count)]:
        content = item.get("summary") or item.get("content") or item.get("snippet") or ""
        mapped.append({
            "title": item.get("title", ""),
            "content": str(content)[:300],
            "link": item.get("url", ""),
            "media": item.get("site_name") or "",
            "publish_date": str(item.get("date") or "")[:10],
        })
    return mapped


def classify_status(status: int) -> tuple[bool, str]:
    """返回 (是否可重试, 给模型看的错误文案)。"""
    if status in _PERMANENT_STATUS:
        return False, (
            "搜索服务的额度或权限不可用。这次不要再重复搜索，"
            "直接如实告诉伙伴现在查不到，等会儿再试。"
        )
    if status in _TRANSIENT_STATUS:
        return True, (
            "搜索服务暂时繁忙。这次先别连续重试，直接告诉伙伴没查到，稍后再帮他查。"
        )
    return False, (
        f"搜索请求没有被接受（状态码 {status}）。这次不要重试，"
        "直接告诉伙伴没查到就好。"
    )


# ── 各供应商实现 ───────────────────────────────────────────


async def _search_deepseek(query: str, count: int, recency: str) -> ToolResult:
    key = _deepseek_key()
    if not key:
        return ToolResult.fail("搜索服务还没配置好（缺少 DeepSeek Key）。")

    body = {
        "query": build_deepseek_query(query, recency)[:128],
        "count": max(1, min(count, 10)),
        "need_content": False,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                DEEPSEEK_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except httpx.TimeoutException:
        logger.warning("search_web.timeout", provider="deepseek", query=query[:50])
        return ToolResult.fail(
            "搜索超时了。这次别再连着重试，先告诉伙伴没查到，稍后再帮他查。"
        )
    except Exception as exc:  # noqa: BLE001 — 网络异常归一成工具失败
        logger.warning("search_web.error", provider="deepseek", error=str(exc)[:200])
        return ToolResult.fail("搜索暂时不可用。这次先别重试，直接告诉伙伴没查到。")

    if resp.status_code != 200:
        retryable, message = classify_status(resp.status_code)
        logger.warning(
            "search_web.unavailable",
            provider="deepseek",
            status=resp.status_code,
            retryable=retryable,
            body=resp.text[:200],
        )
        return ToolResult.fail(message)

    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        logger.warning("search_web.bad_json", provider="deepseek")
        return ToolResult.fail("搜索返回的内容看不懂……这次先告诉伙伴没查到吧。")

    results = map_deepseek_results(payload, count)
    logger.info(
        "search_web.done", provider="deepseek", query=query[:50], results_count=len(results)
    )
    return ToolResult.ok(
        {"query": query, "results": results, "count": len(results), "provider": "deepseek"},
        trigger_memory=True,
        trigger_portrait_update=True,
    )


async def _search_zhipu(query: str, count: int, recency: str) -> ToolResult:
    key = _zhipu_key()
    if not key:
        return ToolResult.fail("搜索服务还没准备好呢……等会儿再试试好不好？")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                ZHIPU_SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {key}",
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
    except httpx.TimeoutException:
        logger.warning("search_web.timeout", provider="zhipu", query=query[:50])
        return ToolResult.fail(
            "搜索超时了。这次别再连着重试，先告诉伙伴没查到，稍后再帮他查。"
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("search_web.error", provider="zhipu", error=str(exc)[:200])
        return ToolResult.fail("搜索暂时不可用。这次先别重试，直接告诉伙伴没查到。")

    if resp.status_code != 200:
        retryable, message = classify_status(resp.status_code)
        logger.warning(
            "search_web.unavailable",
            provider="zhipu",
            status=resp.status_code,
            retryable=retryable,
            body=resp.text[:200],
        )
        return ToolResult.fail(message)

    data = resp.json()
    results = []
    for item in (data.get("search_result") or [])[:count]:
        results.append({
            "title": item.get("title", ""),
            "content": str(item.get("content", ""))[:300],
            "link": item.get("link", ""),
            "media": item.get("media", ""),
            "publish_date": item.get("publish_date", ""),
        })

    intent_info = {}
    for intent in data.get("search_intent", []):
        intent_info["intent"] = intent.get("intent", "")
        intent_info["keywords"] = intent.get("keywords", "")

    logger.info(
        "search_web.done", provider="zhipu", query=query[:50], results_count=len(results)
    )
    return ToolResult.ok(
        {
            "query": query,
            "results": results,
            "count": len(results),
            "intent": intent_info,
            "provider": "zhipu",
        },
        trigger_memory=True,
        trigger_portrait_update=True,
    )


@register_tool(
    name="search_web",
    description="搜索互联网获取实时信息。当伙伴问新闻、百科、实时事件、或'帮我查一下'某件事时使用。",
    schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词，不超过 70 字符",
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
    check_available=_available,
)
async def search_web(query: str, recency: str = "noLimit",
                     count: int = 5, ctx=None) -> ToolResult:
    """搜索网络；供应商由 SEARCH_PROVIDER 决定（默认 DeepSeek）。"""
    provider = _provider()
    if provider == "deepseek":
        return await _search_deepseek(query, count, recency)
    return await _search_zhipu(query, count, recency)


# ── 结果模板 ────────────────────────────────────────────────

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
        return "\\n".join(lines)
