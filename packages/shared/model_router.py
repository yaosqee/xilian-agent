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
from typing import Literal
from dotenv import load_dotenv
from openai import AsyncOpenAI
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
        # === DeepSeek V4-Pro 客户端（多 Key 轮询）===
        self._ds_pro_keys = [
            k for k in [
                os.getenv("DEEPSEEK_API_KEY"),
                os.getenv("DEEPSEEK_API_KEY_2"),
            ] if k
        ]
        self._ds_pro_clients = [
            AsyncOpenAI(api_key=k, base_url="https://api.deepseek.com")
            for k in self._ds_pro_keys
        ] if self._ds_pro_keys else []
        self._pro_key_cycle = itertools.cycle(range(len(self._ds_pro_clients)))
        self.ds_pro_model = "deepseek-v4-pro"

        # === DeepSeek V4-Flash 客户端 ===
        flash_key = os.getenv("DEEPSEEK_API_KEY_2") or os.getenv("DEEPSEEK_API_KEY")
        self._ds_flash = AsyncOpenAI(
            api_key=flash_key, base_url="https://api.deepseek.com"
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

        logger.info(
            "ModelRouter 就绪 (纯云端 mode)",
            ds_pro_keys=len(self._ds_pro_clients),
            ds_flash=bool(self._ds_flash),
            embed_provider=embed_base.split("//")[1].split("/")[0] if embed_base else "none",
            embed_model=self._embed_model,
        )

    # ========== 路由 ==========

    async def route(self, task_type: TaskType, messages: list, **kwargs):
        # --- DS Pro ---
        if task_type in self.ROUTE_DS_PRO:
            return await self._call_ds_pro(messages, **kwargs)

        # --- DS Flash ---
        if task_type in self.ROUTE_DS_FLASH:
            return await self._call_ds_flash(messages, **kwargs)

        # fallback
        logger.warning("未知任务类型，fallback DS Pro", task_type=task_type)
        return await self._call_ds_pro(messages, **kwargs)

    # ========== 嵌入 ==========

    async def embed(self, text: str) -> list[float]:
        """
        云端嵌入 API（硅基流动 bge-m3）。
        1024 维向量，与 sqlite-vec 索引维度一致。
        """
        if not self._embed_client:
            raise RuntimeError("嵌入 API 未配置（EMBED_API_KEY 缺失）")

        response = await asyncio.wait_for(
            self._embed_client.embeddings.create(
                model=self._embed_model,
                input=text,
            ),
            timeout=30,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量嵌入（合并请求省 API 调用）"""
        if not self._embed_client:
            raise RuntimeError("嵌入 API 未配置")

        response = await asyncio.wait_for(
            self._embed_client.embeddings.create(
                model=self._embed_model,
                input=texts,
            ),
            timeout=60,
        )
        return [d.embedding for d in response.data]

    # ========== 底层调用 ==========

    def _pick_pro_client(self) -> AsyncOpenAI:
        """轮询选取 Pro 客户端"""
        if not self._ds_pro_clients:
            raise RuntimeError("DeepSeek V4-Pro 未配置 API Key")
        idx = next(self._pro_key_cycle)
        logger.debug(f"DS Pro 选取 key[{idx}]")
        return self._ds_pro_clients[idx]

    async def _call_ds_pro(self, messages: list, timeout: int = 60, **kwargs):
        """DS Pro（双 Key 轮询 + fallback）"""
        # Key 1 尝试
        for attempt in range(len(self._ds_pro_clients)):
            try:
                client = self._ds_pro_clients[attempt]
                response = await asyncio.wait_for(
                    client.chat.completions.create(
                        model=self.ds_pro_model,
                        messages=messages,
                        temperature=kwargs.get("temperature", 0.7),
                        stream=kwargs.get("stream", False),
                    ),
                    timeout=timeout,
                )
                if kwargs.get("stream"):
                    return response
                return response.choices[0].message.content
            except Exception as e:
                logger.warning(f"DS Pro key[{attempt}] 失败", error=str(e))
                if attempt == len(self._ds_pro_clients) - 1:
                    raise
                continue

    async def _call_ds_flash(self, messages: list, timeout: int = 60, **kwargs):
        """DS Flash"""
        if not self._ds_flash:
            # fallback 到 Pro
            logger.warning("DS Flash 不可用，fallback DS Pro")
            return await self._call_ds_pro(messages, **kwargs)

        response = await asyncio.wait_for(
            self._ds_flash.chat.completions.create(
                model=self.ds_flash_model,
                messages=messages,
                temperature=kwargs.get("temperature", 0.7),
                stream=kwargs.get("stream", False),
            ),
            timeout=timeout,
        )
        if kwargs.get("stream"):
            return response
        return response.choices[0].message.content

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
