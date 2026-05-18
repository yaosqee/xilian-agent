"""
ResultWrapper — 将工具执行结果转化为昔涟的语言风格

分级策略：
  简单结果 → 规则模板（零成本，亚秒级）
  复杂结果 → LLM 包装（高质量，保留人格一致性）
  失败结果 → 预定义温柔降级文本
"""
from loguru import logger

from .tool_result import ToolResult


# ── 简单模板：无需 LLM 的工具在此注册 ──
#  每个条目: (tool_name, template_func)
#  template_func 接收 result.data，返回昔涟风格文本

SIMPLE_TEMPLATES: dict[str, callable] = {}


def register_template(tool_name: str):
    """装饰器：注册工具的简单结果模板。"""
    def decorator(func):
        SIMPLE_TEMPLATES[tool_name] = func
        return func
    return decorator


# ── 降级回复 ──

FAILURE_TEMPLATES = {
    "timeout": "人家帮你看了……但那边有点慢呢，没等到结果 (´•ω•̥`) 等会儿再试试好不好？",
    "not_found": "唔……人家找了一下，好像没有找到呢。",
    "default": "出了一点小问题……等会儿再试试好不好？",
}


class ResultWrapper:
    """
    工具结果 → 昔涟语言转换器。

    用法:
        wrapper = ResultWrapper(model_router)
        text = await wrapper.wrap("search_memory", result, user_msg)
    """

    def __init__(self, model_router=None):
        self.router = model_router  # 可选：用于 LLM 包装

    async def wrap(self, tool_name: str, result: ToolResult,
                   user_context: str = "") -> str:
        """
        将 ToolResult 转化为昔涟会说的一句话/一段话。
        """
        if not result.success:
            return self._failure_text(result.error)

        # 优先使用注册的简单模板
        if tool_name in SIMPLE_TEMPLATES:
            try:
                return SIMPLE_TEMPLATES[tool_name](result.data)
            except Exception as e:
                logger.warning("result_wrapper.template_error",
                               tool=tool_name, error=str(e))

        # 结构化数据 → LLM 包装
        if self.router:
            try:
                return await self._llm_wrap(tool_name, result.data, user_context)
            except Exception as e:
                logger.warning("result_wrapper.llm_failed",
                               tool=tool_name, error=str(e))

        # 最终兜底：友好展示原始数据
        return self._fallback_text(tool_name, result.data)

    # ── 内部 ─────────────────────────────────────────────

    def _failure_text(self, error: str) -> str:
        """失败 → 温柔降级文本。"""
        if "timeout" in error.lower():
            return FAILURE_TEMPLATES["timeout"]
        if "not found" in error.lower() or "没找到" in error:
            return FAILURE_TEMPLATES["not_found"]
        # 如果 error 本身已经是温柔文本，直接返回
        if any(kw in error for kw in ("人家", "呢", "好不好", "……", "♪")):
            return error
        return FAILURE_TEMPLATES["default"]

    async def _llm_wrap(self, tool_name: str, data, user_context: str) -> str:
        """
        LLM 包装：用 Flash 模型将工具结果转为昔涟语气。
        这个调用轻量、快速，不影响核心对话。
        """
        import json

        data_str = json.dumps(data, ensure_ascii=False, indent=2)
        if len(data_str) > 1500:
            data_str = data_str[:1500] + "\n…(已截断)"

        prompt = f"""你是昔涟。用你一贯的温柔语气，把以下信息自然地告诉伙伴。
不要复述数据，不要列出条目，要像聊天一样说出来。
挑最重要的 2-3 个点即可。用短句，每行以「。！？~♪」收尾。

伙伴刚才问的是：{user_context[:200]}

工具「{tool_name}」返回的结果：
{data_str}

昔涟的回复："""

        result = await self.router.route(
            "tool_result_wrap",
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )
        return result.strip() if result else self._fallback_text(tool_name, data)

    def _fallback_text(self, tool_name: str, data) -> str:
        """无 LLM 时的兜底展示。"""
        import json
        data_str = json.dumps(data, ensure_ascii=False, indent=2)
        if len(data_str) > 400:
            data_str = data_str[:400] + "\n…"
        return f"人家帮你查了一下～\n\n{data_str}\n\n——喏，就是这样 ~♪"
