"""ModelRouter — 纯云端路由核心，进程内路由

2026-05-15 修订（V3.3）：纯云端方案，砍掉本地模型。
  · 高质量（用户直接感知/安全攸关）→ DeepSeek V4-Pro（双 Key 轮询）
  · 后台异步（记忆编码/情感分析/格式化）→ DeepSeek V4-Flash
  · 嵌入向量 → 硅基流动 bge-m3（OpenAI 兼容 API）
  · 架构保留模型切换点，未来可接入本地或其他云端模型
"""
import os
import asyncio
import itertools
import time as _time_module
from typing import Literal
from dotenv import load_dotenv
from openai import AsyncOpenAI
import httpx
from loguru import logger

load_dotenv()

TaskType = Literal[
    "chat", "empathy",
    "memory_encoding", "autobiography", "reflection", "dream",
    "reasoning", "code", "planning",
    "personality_check", "prompt_injection_detect", "approval_text",
    "emotion_analysis", "tool_result_wrap",
    "proactive_greeting", "image_response",
]


class ToolRelatedError(Exception):
    """工具调用相关错误——触发模型降级（移除 tools 参数重试）。"""
    pass


class ModelRouter:
    """
    纯云端路由拓扑（2026-05-15 修订）：
    · 核心对话/共情/推理/代码/规划/安全检测 → DS V4-Pro（双Key轮询）
    · 记忆编码/自传体/反思/梦幻/审批/情感分析/工具包装 → DS V4-Flash
    · 嵌入向量 → 硅基流动 bge-m3（OpenAI 兼容 embeddings API）
    · 架构保留所有路由点的 model_override，便于调试对比
    """

    # ========== 路由表 ==========
    ROUTE_DS_PRO = {
        "chat", "empathy",
        "reasoning", "code", "planning",
        "personality_check", "prompt_injection_detect",
        "proactive_greeting", "image_response",
    }
    ROUTE_DS_FLASH = {
        "memory_encoding", "autobiography", "reflection", "dream",
        "approval_text", "emotion_analysis", "tool_result_wrap",
    }

    def __init__(self):
        # 统一超时配置：connect=15s（默认 5s 太短，网络波动时大量超时）
        _api_timeout = httpx.Timeout(connect=15.0, read=120.0, write=120.0, pool=30.0)

        # === DeepSeek V4-Pro 客户端（多 Key 轮询）===
        self._ds_pro_keys = [
            k for k in [
                os.getenv("DEEPSEEK_API_KEY"),
                os.getenv("DEEPSEEK_API_KEY_2"),
            ] if k
        ]
        self._ds_pro_clients = [
            AsyncOpenAI(api_key=k, base_url="https://api.deepseek.com", timeout=_api_timeout, max_retries=1)
            for k in self._ds_pro_keys
        ] if self._ds_pro_keys else []
        self._pro_key_cycle = itertools.cycle(range(len(self._ds_pro_clients)))
        self.ds_pro_model = "deepseek-v4-pro"

        # === DeepSeek V4-Flash 客户端 ===
        flash_key = os.getenv("DEEPSEEK_API_KEY_2") or os.getenv("DEEPSEEK_API_KEY")
        self._ds_flash = AsyncOpenAI(
            api_key=flash_key, base_url="https://api.deepseek.com", timeout=_api_timeout, max_retries=1
        ) if flash_key else None
        self.ds_flash_model = "deepseek-v4-flash"

        # === 嵌入 API（硅基流动 bge-m3，OpenAI 兼容）===
        embed_key = os.getenv("EMBED_API_KEY") or flash_key
        embed_base = os.getenv("EMBED_BASE_URL", "https://api.siliconflow.cn/v1")
        self._embed_client = AsyncOpenAI(
            api_key=embed_key,
            base_url=embed_base,
        ) if embed_key else None
        self._embed_model = os.getenv("EMBED_MODEL", "BAAI/bge-m3")

        # === Qwen（保留备查，当前路由表不引用）===
        qwen_key = os.getenv("DASHSCOPE_API_KEY")
        self.qwen = AsyncOpenAI(
            api_key=qwen_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        ) if qwen_key else None
        self.qwen_model = "qwen3.6-plus"

        # === 阶段 7a: 工具兼容性缓存 ===
        self._tools_support_cache: dict[str, bool] = {}
        self._tools_cache_reset_interval = 86400  # 24h
        self._tools_cache_last_reset = _time_module.time()

        logger.info(
            "ModelRouter 就绪 (纯云端 mode)",
            ds_pro_keys=len(self._ds_pro_clients),
            ds_flash=bool(self._ds_flash),
            embed_provider=embed_base.split("//")[1].split("/")[0] if embed_base else "none",
            embed_model=self._embed_model,
        )

    # ========== 路由 ==========

    # ========== 路由 ==========

    async def route(
        self,
        task_type: TaskType,
        messages: list,
        tools: list | None = None,
        tool_choice: str | None = None,
        **kwargs,
    ):
        """
        路由主入口。

        阶段 7a 新增 tools/tool_choice 参数，自动降级：
        - 若目标模型标记为不支持 tools → 自动移除 tools 参数
        - 若调用时抛出 ToolRelatedError → 标记不兼容 + 无 tools 重试
        """
        model_key = self._get_model_key(task_type)

        # 阶段 7a: 工具兼容性检查
        if tools and not self._supports_tools(model_key):
            logger.info("model_router.tools_degraded", model=model_key)
            tools = None
            tool_choice = None

        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

        try:
            # --- DS Pro ---
            if task_type in self.ROUTE_DS_PRO:
                return await self._call_ds_pro(messages, **kwargs)

            # --- DS Flash ---
            if task_type in self.ROUTE_DS_FLASH:
                return await self._call_ds_flash(messages, **kwargs)

            # fallback
            logger.warning("未知任务类型，fallback DS Pro", task_type=task_type)
            return await self._call_ds_pro(messages, **kwargs)

        except ToolRelatedError as e:
            logger.warning("model_router.tool_error", model=model_key, error=str(e))
            self._tools_support_cache[model_key] = False
            if tools:
                # 移除 tools 重试
                kwargs["tools"] = None
                kwargs["tool_choice"] = None
                if task_type in self.ROUTE_DS_PRO:
                    return await self._call_ds_pro(messages, **kwargs)
                return await self._call_ds_flash(messages, **kwargs)
            raise

    # ========== 嵌入 ==========

    async def embed(self, text: str) -> list[float] | None:
        """
        云端嵌入 API（硅基流动 bge-m3）。
        1024 维向量，与 sqlite-vec 索引维度一致。
        无 Key 时返回 None，由调用方降级处理。
        """
        if not self._embed_client:
            logger.debug("embed.unavailable")
            return None

        try:
            response = await asyncio.wait_for(
                self._embed_client.embeddings.create(
                    model=self._embed_model,
                    input=text,
                ),
                timeout=30,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.warning("embed.failed", error=str(e)[:120])
            return None

    async def embed_batch(self, texts: list[str]) -> list[list[float]] | None:
        """批量嵌入。无 Key 或调用失败时返回 None。"""
        if not self._embed_client:
            logger.debug("embed.unavailable")
            return None

        try:
            response = await asyncio.wait_for(
                self._embed_client.embeddings.create(
                    model=self._embed_model,
                    input=texts,
                ),
                timeout=60,
            )
            return [d.embedding for d in response.data]
        except Exception as e:
            logger.warning("embed_batch.failed", error=str(e)[:120])
            return None

    # ========== 底层调用 ==========

    def _pick_pro_client(self) -> AsyncOpenAI:
        """轮询选取 Pro 客户端"""
        if not self._ds_pro_clients:
            raise RuntimeError("DeepSeek V4-Pro 未配置 API Key")
        idx = next(self._pro_key_cycle)
        logger.debug(f"DS Pro 选取 key[{idx}]")
        return self._ds_pro_clients[idx]

    async def _call_ds_pro(self, messages: list, timeout: int = 90, **kwargs):
        """DS Pro（双 Key 轮询 + fallback）。有 tools 时返回完整 message 对象。"""
        has_tools = bool(kwargs.get("tools"))
        for attempt in range(len(self._ds_pro_clients)):
            t0 = _time_module.time()
            try:
                client = self._ds_pro_clients[attempt]
                api_kwargs = dict(
                    model=self.ds_pro_model,
                    messages=messages,
                    temperature=kwargs.get("temperature", 0.7),
                    stream=kwargs.get("stream", False),
                )
                if kwargs.get("max_tokens"):
                    api_kwargs["max_tokens"] = kwargs["max_tokens"]
                if has_tools:
                    api_kwargs["tools"] = kwargs["tools"]
                    api_kwargs["tool_choice"] = kwargs.get("tool_choice", "auto")
                response = await asyncio.wait_for(
                    client.chat.completions.create(**api_kwargs),
                    timeout=timeout,
                )
                elapsed = (_time_module.time() - t0) * 1000
                logger.debug("ds_pro.call_ok", key=attempt, elapsed_ms=round(elapsed))
                if kwargs.get("stream"):
                    return response
                choice = response.choices[0]
                finish = choice.finish_reason
                if finish == "length":
                    logger.warning("model_router.truncated",
                                  model=self.ds_pro_model,
                                  reason="max_tokens reached",
                                  usage=str(response.usage))
                msg = choice.message
                # 有 tools 时返回完整 message（可能含 tool_calls）；否则返回 content 字符串
                return msg if has_tools else msg.content
            except Exception as e:
                elapsed = (_time_module.time() - t0) * 1000
                err_type = type(e).__name__
                err_msg = str(e)[:300]
                logger.warning(f"DS Pro key[{attempt}] 失败: {err_type}",
                              elapsed_ms=round(elapsed),
                              detail=err_msg)
                if attempt == len(self._ds_pro_clients) - 1:
                    raise
                continue

    async def _call_ds_flash(self, messages: list, timeout: int = 90, **kwargs):
        """DS Flash。有 tools 时返回完整 message 对象。"""
        if not self._ds_flash:
            logger.warning("DS Flash 不可用，fallback DS Pro")
            return await self._call_ds_pro(messages, **kwargs)

        has_tools = bool(kwargs.get("tools"))
        t0 = _time_module.time()
        api_kwargs = dict(
            model=self.ds_flash_model,
            messages=messages,
            temperature=kwargs.get("temperature", 0.7),
            stream=kwargs.get("stream", False),
        )
        if kwargs.get("max_tokens"):
            api_kwargs["max_tokens"] = kwargs["max_tokens"]
        if has_tools:
            api_kwargs["tools"] = kwargs["tools"]
            api_kwargs["tool_choice"] = kwargs.get("tool_choice", "auto")

        try:
            response = await asyncio.wait_for(
                self._ds_flash.chat.completions.create(**api_kwargs),
                timeout=timeout,
            )
        except Exception as e:
            elapsed = (_time_module.time() - t0) * 1000
            logger.warning(f"DS Flash 失败: {type(e).__name__}",
                          elapsed_ms=round(elapsed),
                          detail=str(e)[:300])
            raise

        elapsed = (_time_module.time() - t0) * 1000
        logger.debug("ds_flash.call_ok", elapsed_ms=round(elapsed))
        if kwargs.get("stream"):
            return response
        choice = response.choices[0]
        finish = choice.finish_reason
        if finish == "length":
            logger.warning("model_router.truncated",
                          model=self.ds_flash_model,
                          reason="max_tokens reached",
                          usage=str(response.usage))
        msg = choice.message
        return msg if has_tools else msg.content

    # ========== 工具兼容性 ==========

    def _get_model_key(self, task_type: str) -> str:
        """根据 task_type 返回模型标识（用于缓存 key）。"""
        if task_type in self.ROUTE_DS_PRO:
            return "ds-pro"
        return "ds-flash"

    def _supports_tools(self, model_key: str) -> bool:
        """
        检查模型是否支持工具调用。
        每日自动重置缓存（避免因临时故障永久禁用）。
        """
        now = _time_module.time()
        if now - self._tools_cache_last_reset > self._tools_cache_reset_interval:
            self._tools_support_cache.clear()
            self._tools_cache_last_reset = now
            logger.debug("model_router.tools_cache_reset")
        return self._tools_support_cache.get(model_key, True)

    # ========== 手动覆盖 ==========

    async def route_with_override(
        self, task_type, messages, model_override=None, **kwargs
    ):
        """允许手动指定模型，用于对比测试"""
        if model_override in ("ds_pro", "ds"):
            return await self._call_ds_pro(messages, **kwargs)
        elif model_override == "ds_flash":
            return await self._call_ds_flash(messages, **kwargs)
        elif model_override == "qwen" and self.qwen:
            return await self._call_qwen(messages, **kwargs)
        return await self.route(task_type, messages, **kwargs)

    async def _call_qwen(self, messages: list, timeout: int = 60, **kwargs):
        """保留，当前路由表不引用"""
        if not self.qwen:
            raise RuntimeError("Qwen API 未配置")
        response = await asyncio.wait_for(
            self.qwen.chat.completions.create(
                model=self.qwen_model,
                messages=messages,
                temperature=kwargs.get("temperature", 0.7),
                stream=kwargs.get("stream", False),
            ),
            timeout=timeout,
        )
        if kwargs.get("stream"):
            return response
        return response.choices[0].message.content
