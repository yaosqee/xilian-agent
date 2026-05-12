"""ModelRouter — 混合路由核心，进程内路由

2026-05-12 修订：Qwen3.6-Plus 延迟过高（~27s），全量迁移至 DeepSeek。
  · 高质量（用户直接感知/安全攸关）→ DeepSeek V4-Pro（双 Key 轮询）
  · 低质量（后台异步/格式化包装）→ DeepSeek V4-Flash
  · 本地 first 任务保持，fallback 走 Flash
  · Qwen 客户端保留备查，当前路由表不再引用
"""
import os
import asyncio
import itertools
from typing import Literal
from dotenv import load_dotenv
from openai import AsyncOpenAI
from ollama import AsyncClient as OllamaClient
from loguru import logger

load_dotenv()

TaskType = Literal[
    "chat", "empathy",
    "proactive_greeting", "tool_result_wrap", "image_response",
    "memory_encoding", "autobiography", "reflection", "dream",
    "reasoning", "code", "planning",
    "personality_check", "prompt_injection_detect", "approval_text",
    "emotion_analysis",
]


class ModelRouter:
    """
    混合路由拓扑（2026-05-12 修订）：
    · 核心对话/共情/推理/代码/规划/人设自检/注入检测 → DeepSeek V4-Pro（双 Key 轮询）
    · 记忆编码/自传体/反思/梦幻/审批/情感分析 → DeepSeek V4-Flash（后台异步）
    · 自主问候/工具包装/图像回应 → 本地 qwen3:14b 优先，不可用 fallback Flash
    · 7/15 后核心对话可切本地，阶段5可切微调版
    """

    # ========== 路由表 ==========
    ROUTE_LOCAL_FIRST = {"proactive_greeting", "tool_result_wrap", "image_response"}
    ROUTE_DS_PRO = {
        "chat", "empathy",
        "reasoning", "code", "planning",
        "personality_check", "prompt_injection_detect",
    }
    ROUTE_DS_FLASH = {
        "memory_encoding", "autobiography", "reflection", "dream",
        "approval_text", "emotion_analysis",
    }

    def __init__(self):
        mode = os.getenv("TRANSITION_MODE", "cloud")
        self.use_local_for_chat = (mode in ("local_base", "finetuned"))

        # 本地客户端
        self.ollama = OllamaClient(host="http://localhost:11434")
        self.local_model = "qwen3:14b"

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
        ]
        self._pro_key_cycle = itertools.cycle(range(len(self._ds_pro_clients)))
        self.ds_pro_model = "deepseek-v4-pro"

        # === DeepSeek V4-Flash 客户端 ===
        flash_key = os.getenv("DEEPSEEK_API_KEY_2") or os.getenv("DEEPSEEK_API_KEY")
        self._ds_flash = AsyncOpenAI(
            api_key=flash_key, base_url="https://api.deepseek.com"
        )
        self.ds_flash_model = "deepseek-v4-flash"

        # === Qwen（保留备查，当前路由表不引用）===
        self.qwen = AsyncOpenAI(
            api_key=os.getenv("DASHSCOPE_API_KEY"),
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        self.qwen_model = "qwen3.6-plus"

        logger.info(
            "ModelRouter 就绪 (DeepSeek-only 模式)",
            transition_mode=mode,
            use_local_for_chat=self.use_local_for_chat,
            ds_pro_keys=len(self._ds_pro_clients),
        )

    # ========== 路由 ==========

    async def route(self, task_type: TaskType, messages: list, **kwargs):
        # --- 核心对话 ---
        if task_type == "chat":
            if self.use_local_for_chat:
                try:
                    return await self._call_ollama(messages, **kwargs)
                except Exception as e:
                    logger.warning("本地模型不可用，fallback DS Pro", error=str(e))
                    return await self._call_ds_pro(messages, **kwargs)
            else:
                return await self._call_ds_pro(messages, **kwargs)

        # --- 本地优先 ---
        if task_type in self.ROUTE_LOCAL_FIRST:
            try:
                return await self._call_ollama(messages, **kwargs)
            except Exception as e:
                logger.warning(
                    f"{task_type} 本地不可用，fallback DS Flash", error=str(e)
                )
                return await self._call_ds_flash(messages, **kwargs)

        # --- DS Pro ---
        if task_type in self.ROUTE_DS_PRO:
            return await self._call_ds_pro(messages, **kwargs)

        # --- DS Flash ---
        if task_type in self.ROUTE_DS_FLASH:
            return await self._call_ds_flash(messages, **kwargs)

        # fallback
        logger.warning("未知任务类型，fallback DS Pro", task_type=task_type)
        return await self._call_ds_pro(messages, **kwargs)

    # ========== 底层调用 ==========

    async def _call_ollama(self, messages: list, timeout: int = 120, **kwargs):
        response = await asyncio.wait_for(
            self.ollama.chat(
                model=self.local_model,
                messages=messages,
                options={"temperature": kwargs.get("temperature", 0.7)},
            ),
            timeout=timeout,
        )
        return response["message"]["content"]

    def _pick_pro_client(self) -> AsyncOpenAI:
        """轮询选取 Pro 客户端"""
        idx = next(self._pro_key_cycle)
        logger.debug(f"DS Pro 选取 key[{idx}]")
        return self._ds_pro_clients[idx]

    async def _call_ds_pro(self, messages: list, timeout: int = 60, **kwargs):
        client = self._pick_pro_client()
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

    async def _call_ds_flash(self, messages: list, timeout: int = 60, **kwargs):
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

    async def _call_qwen(self, messages: list, timeout: int = 60, **kwargs):
        """保留，当前路由表不引用"""
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

    # ========== 手动覆盖 ==========

    async def route_with_override(self, task_type, messages, model_override=None, **kwargs):
        """允许手动指定模型，用于对比测试"""
        if model_override == "local":
            return await self._call_ollama(messages, **kwargs)
        elif model_override == "qwen":
            return await self._call_qwen(messages, **kwargs)
        elif model_override == "ds_pro":
            return await self._call_ds_pro(messages, **kwargs)
        elif model_override == "ds_flash":
            return await self._call_ds_flash(messages, **kwargs)
        elif model_override == "ds":
            return await self._call_ds_pro(messages, **kwargs)  # 兼容旧接口
        return await self.route(task_type, messages, **kwargs)
